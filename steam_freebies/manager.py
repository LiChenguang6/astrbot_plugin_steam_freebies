"""Optional, opt-in local ASF runtime. Never vendors binaries or Steam credentials."""
import asyncio
import hashlib
import json
import os
import platform
import re
import secrets
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

import aiohttp

RELEASE_URL = 'https://api.github.com/repos/JustArchiNET/ArchiSteamFarm/releases/latest'
BOT_RE = re.compile(r'^[A-Za-z0-9_-]{1,64}$')


def archive_variant(system=None, machine=None):
    system = (system or platform.system()).lower()
    machine = (machine or platform.machine()).lower()
    cpu = 'arm64' if machine in ('aarch64', 'arm64') else 'x64' if machine in ('x86_64', 'amd64') else None
    os_name = {'linux': 'linux', 'windows': 'win', 'darwin': 'osx'}.get(system)
    if not cpu or not os_name:
        raise ValueError('当前操作系统或 CPU 架构没有对应的 ASF 自包含安装包')
    return f'ASF-{os_name}-{cpu}.zip'


def verify_and_extract(archive: bytes, checksum: str, root: Path):
    if not re.fullmatch('[0-9a-fA-F]{64}', checksum):
        raise ValueError('发布版本未提供可信 SHA256，拒绝安装')
    if hashlib.sha256(archive).hexdigest().lower() != checksum.lower():
        raise ValueError('下载文件校验失败，未安装 ASF')
    import io
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
        infos = z.infolist()
        if len(infos) > 2000 or sum(x.file_size for x in infos) > 300 * 1024 * 1024:
            raise ValueError('ASF 安装包超出安全解压限制')
        for item in infos:
            p = PurePosixPath(item.filename)
            if p.is_absolute() or '..' in p.parts or ':' in item.filename or '\\' in item.filename:
                raise ValueError('安装包包含不安全路径')
            if (item.external_attr >> 16) & 0o170000 == stat.S_IFLNK:
                raise ValueError('不允许安装包包含符号链接')
            target = root.joinpath(*p.parts)
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(item) as src, target.open('wb') as dst:
                shutil.copyfileobj(src, dst, length=1024 * 1024)
    exe = root / ('ArchiSteamFarm.exe' if platform.system() == 'Windows' else 'ArchiSteamFarm')
    if not exe.is_file():
        raise ValueError('ASF 安装包不包含预期可执行文件')
    if os.name != 'nt':
        exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    return exe


class ManagedASF:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / 'runtime'
        self.settings_path = self.root / 'manager.json'
        self.process = None
        self.log_handle = None
        self.install_task = None
        self.install_state = 'idle'
        self.last_error = ''
        self.version = ''
        self._lock = asyncio.Lock()

    def settings(self):
        default = {'mode': 'external', 'bot_name': '', 'start_on_boot': False}
        if self.settings_path.exists():
            try:
                obj = json.loads(self.settings_path.read_text(encoding='utf-8'))
                default.update({k:v for k,v in obj.items() if k in default})
            except (OSError, ValueError, TypeError):
                pass
        return default

    def save_settings(self, values):
        if not isinstance(values, dict) or set(values) - {'mode','bot_name','start_on_boot'}:
            raise ValueError('不支持的 ASF 设置')
        for key, value in values.items():
            if key == 'mode' and value not in ('external','managed'):
                raise ValueError('ASF 模式只能选 external 或 managed')
            if key == 'bot_name' and value and not BOT_RE.fullmatch(value):
                raise ValueError('ASF Bot 名称只允许英文、数字、_、-，最长64位')
            if key == 'start_on_boot' and type(value) is not bool:
                raise ValueError('自动启动必须是布尔值')
        saved = {**self.settings(),**values}
        if saved['mode'] == 'managed' and not self.installed():
            raise ValueError('请先通过官方发布包安装托管 ASF')
        temp = self.settings_path.with_suffix('.tmp')
        temp.write_text(json.dumps(saved,ensure_ascii=False,indent=2),encoding='utf-8')
        if os.name != 'nt': temp.chmod(0o600)
        temp.replace(self.settings_path)
        return saved

    def binary(self):
        return self.path / ('ArchiSteamFarm.exe' if os.name == 'nt' else 'ArchiSteamFarm')

    def installed(self):
        return self.binary().is_file()

    def running(self):
        return self.process is not None and self.process.returncode is None

    def status(self):
        return {'installed':self.installed(),'running':self.running(), 'install_state':self.install_state,
                'error':self.last_error, 'settings':self.settings(), 'version':self.version,
                'variant': archive_variant() if self._supported() else 'unsupported',
                'ipc_url': 'http://127.0.0.1:1242' if self.running() else ''}

    def _supported(self):
        try:
            archive_variant()
            return True
        except ValueError: return False

    def install(self):
        if self.install_task and not self.install_task.done():
            raise ValueError('正在下载 ASF，请勿重复操作')
        if self.running():
            raise ValueError('请先停止已运行的 ASF，再更新安装')
        self.install_state = 'downloading'
        self.last_error = ''
        self.install_task = asyncio.create_task(self._install_job(), name='steam-freebies-asf-install')

    async def _install_job(self):
        staging = None
        try:
            asset_name = archive_variant()
            timeout = aiohttp.ClientTimeout(total=180)
            headers = {'User-Agent':'AstrBot-Steam-Freebies/0.2', 'Accept':'application/vnd.github+json'}
            async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
                async with session.get(RELEASE_URL) as resp:
                    resp.raise_for_status()
                    release = await resp.json(content_type=None)
                if release.get('prerelease') or release.get('draft'):
                    raise ValueError('只允许安装 ASF 稳定版')
                asset = next((x for x in release.get('assets',[]) if x.get('name') == asset_name),None)
                if not asset:
                    raise ValueError('官方发布页缺少对应平台安装包')
                digest = str(asset.get('digest') or '')
                if not digest.startswith('sha256:'):
                    raise ValueError('官方 GitHub 发布信息缺少 SHA256，不自动安装')
                url = asset.get('browser_download_url','')
                parsed = urlparse(url)
                if parsed.scheme != 'https' or parsed.netloc != 'github.com' or not parsed.path.startswith('/JustArchiNET/ArchiSteamFarm/releases/download/'):
                    raise ValueError('发布资源地址不可信')
                if int(asset.get('size',0)) > 80*1024*1024:
                    raise ValueError('ASF 压缩包过大')
                async with session.get(url) as resp:
                    resp.raise_for_status()
                    chunks=[]
                    count=0
                    async for chunk in resp.content.iter_chunked(1024*1024):
                        count += len(chunk)
                        if count > 80*1024*1024:
                            raise ValueError('下载文件超过80MB限制')
                        chunks.append(chunk)
                archive = b''.join(chunks)
            self.install_state='verifying'
            staging=Path(tempfile.mkdtemp(prefix='asf-stage-',dir=self.root))
            verify_and_extract(archive,digest[7:],staging)
            config_dir = staging / 'config'
            config_dir.mkdir(exist_ok=True)
            # New installs generate their own IPC auth token, never checked into GitHub.
            previous = self.path / 'config'
            if previous.is_dir():
                shutil.copytree(previous,config_dir,dirs_exist_ok=True)
            else:
                ipc_secret=secrets.token_urlsafe(40)
                (config_dir/'ASF.json').write_text(json.dumps({
                    'IPC':True,'IPCPassword':ipc_secret,'OptimizationMode':1,
                    'UpdatePeriod':0,'Headless':True
                },indent=2),encoding='utf-8')
            if os.name != 'nt':
                for p in config_dir.iterdir():
                    if p.is_file(): p.chmod(0o600)
            old = self.root / 'runtime-previous'
            if old.exists(): shutil.rmtree(old)
            if self.path.exists(): self.path.rename(old)
            try: staging.rename(self.path)
            except Exception:
                if old.exists() and not self.path.exists(): old.rename(self.path)
                raise
            staging = None
            if old.exists(): shutil.rmtree(old)
            self.version = str(release.get('tag_name') or '')[:40]
            self.install_state='installed'
        except asyncio.CancelledError:
            self.install_state='cancelled'
            raise
        except Exception as exc:
            self.install_state='error'
            self.last_error=f'{type(exc).__name__}: {str(exc)[:200]}'
        finally:
            if staging is not None:
                shutil.rmtree(staging,ignore_errors=True)

    async def start(self):
        async with self._lock:
            if self.running(): return
            if not self.installed(): raise ValueError('请先安装 ASF 官方独立版本')
            # Prevent silently attaching to another process on the default IPC port.
            import socket
            try:
                with socket.create_connection(('127.0.0.1',1242),timeout=0.2):
                    raise ValueError('本机 1242 端口已被占用，请停止其他 ASF，避免连接错账号')
            except (ConnectionRefusedError,TimeoutError,OSError):
                pass
            self.log_handle=(self.root/'asf.log').open('ab')
            try:
                self.process=await asyncio.create_subprocess_exec(str(self.binary()), '--no-restart',
                    cwd=str(self.path),stdin=asyncio.subprocess.DEVNULL,
                    stdout=self.log_handle,stderr=asyncio.subprocess.STDOUT)
                await asyncio.sleep(1)
                if self.process.returncode is not None:
                    raise RuntimeError('ASF 进程启动后立即退出，请查看服务器本地 asf.log')
            except Exception:
                self.process=None
                self.log_handle.close()
                self.log_handle=None
                raise

    async def stop(self):
        async with self._lock:
            proc=self.process
            self.process=None
            if proc and proc.returncode is None:
                proc.terminate()
                try: await asyncio.wait_for(proc.wait(),timeout=8)
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.wait()
            if self.log_handle:
                self.log_handle.close()
                self.log_handle=None

    def prepare_bot(self, bot_name, steam_login):
        """Non-secret onboarding only; account password/Steam Guard handled by ASF-ui."""
        if not self.installed(): raise ValueError('请先安装托管 ASF')
        if type(bot_name) is not str or not BOT_RE.fullmatch(bot_name) or bot_name.lower() == 'asf':
            raise ValueError('Bot 名称不合法')
        if type(steam_login) is not str or not re.fullmatch(r'[A-Za-z0-9_.-]{1,80}',steam_login):
            raise ValueError('Steam 登录名格式不合法')
        path=self.path/'config'/f'{bot_name}.json'
        if path.exists(): raise ValueError('此 Bot 配置已存在，为保护原凭据不会覆盖')
        if not path.parent.is_dir(): raise ValueError('ASF 配置目录不存在')
        # Disabled initially: user must complete login and explicitly enable it in ASF-ui.
        cfg={'Enabled':False,'SteamLogin':steam_login,'FarmingPreferences':1}
        with path.open('x',encoding='utf-8') as f:
            json.dump(cfg,f,ensure_ascii=False,indent=2)
        if os.name!='nt':path.chmod(0o600)
        self.save_settings({'bot_name':bot_name})
        return {'bot_name':bot_name, 'notice':'Bot 配置已创建（默认停用挂卡，尚未登录）。请到本机 ASF-ui 完成 Steam Guard 和启用账号。'}

    def ipc(self):
        if not self.running(): raise ValueError('托管 ASF 未运行，请在后台启动')
        cfg = self.path/'config'/'ASF.json'
        try: obj=json.loads(cfg.read_text(encoding='utf-8'))
        except (OSError,ValueError) as exc: raise ValueError('无法读取托管 ASF IPC 配置') from exc
        return 'http://127.0.0.1:1242',self.settings()['bot_name'],str(obj.get('IPCPassword') or '')

    async def close(self):
        if self.install_task and not self.install_task.done():
            self.install_task.cancel()
            await asyncio.gather(self.install_task,return_exceptions=True)
        await self.stop()
