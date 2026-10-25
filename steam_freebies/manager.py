"""Optional, opt-in local ASF runtime. Never vendors binaries or Steam credentials."""
import asyncio
import errno
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
from datetime import datetime, timezone
from urllib.parse import urlparse

from .asf_release import PINNED_VERSION, PINNED_SHA256, DOWNLOAD_RELAYS

import aiohttp

RELEASE_URL = 'https://api.github.com/repos/JustArchiNET/ArchiSteamFarm/releases/latest'
BOT_RE = re.compile(r'^[A-Za-z0-9_-]{1,64}$')


def diagnose_start_failure(log_text: str = '', exit_code=None, error: BaseException | None = None) -> str:
    """Turn startup output into safe, actionable hints; never expose raw ASF logs or Steam credentials."""
    source = (log_text or '')[-16_000:].lower()
    if isinstance(error, PermissionError) or 'permission denied' in source or 'operation not permitted' in source:
        return 'ASF 执行权限被拒绝：检查容器数据卷是否 noexec、可执行位及目录权限。'
    if isinstance(error, OSError) and error.errno == errno.ENOEXEC or 'exec format error' in source:
        return '可执行文件格式不匹配：请核对 Docker 容器的 CPU 架构与 ASF 安装包。'
    if 'libicu' in source or 'couldn\'t find a valid icu' in source or 'failed to load system icu' in source:
        return '容器缺少 .NET 所需的 ICU 本地库（libicu）；依赖需要安装在 AstrBot 容器内部，而不是群晖宿主机。'
    if 'libssl' in source or 'libcrypto.so' in source:
        return '容器缺少 OpenSSL 本地依赖（libssl/libcrypto）；需要调整 AstrBot 容器镜像。'
    if 'glibc_' in source or 'ld-linux' in source or 'musl' in source:
        return '容器的 glibc/musl 运行时与 ASF-linux-x64 不兼容；需要匹配 Linux 发行版的运行镜像。'
    if 'hostfxr' in source or 'hostpolicy' in source:
        return '.NET 运行时宿主加载失败（hostfxr/hostpolicy）；检查容器本地库与安装包架构。'
    if 'no bots are running' in source:
        return 'ASF 因没有启用的 Steam Bot 而退出；请确认已更新到包含 --process-required 的插件版本。'
    if 'no such file or directory' in source or isinstance(error, FileNotFoundError):
        return '系统找不到 ASF 的执行加载器或依赖库；即使可执行文件存在，也可能缺少容器内的 Linux 动态加载器。'
    if 'segmentation fault' in source or 'core dumped' in source:
        return 'ASF 启动发生本地崩溃，请检查系统架构、运行时依赖和容器日志。'
    if 'failed to bind' in source or 'address already in use' in source:
        return '本地 IPC 端口冲突：请检查容器内是否已运行 ASF。'
    if error is not None and isinstance(error, OSError):
        return f'操作系统拒绝启动 ASF（errno={error.errno}）。请检查容器权限及本地依赖。'
    return f'ASF 启动后退出（退出码 {exit_code if exit_code is not None else "未知"}）。请查看容器内 asf-manager/asf.log 尾部并隐藏账号信息。'



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
        self.start_error = ''
        self.last_exit_code = None
        self.running_profile = ''
        self._active_claims = 0
        self._idle_task = None
        self.install_task = None
        self.state_path = self.root / 'install-state.json'
        persisted = self._load_install_state()
        self.install_state = 'installed' if self.installed() else persisted.get('state', 'idle')
        if self.install_state in ('downloading', 'verifying', 'extracting'):
            self.install_state = 'interrupted'
        self.last_error = str(persisted.get('error') or '')[:600]
        self.version = str(persisted.get('version') or '')[:40]
        self.download_source = ''
        self.download_bytes = 0
        self.download_total = 0
        self.metadata_source = ''
        self._lock = asyncio.Lock()

    def _load_install_state(self):
        try:
            data = json.loads(self.state_path.read_text(encoding='utf-8'))
            if isinstance(data, dict):
                return {key: data.get(key) for key in ('state', 'error', 'version')}
        except (OSError, ValueError, TypeError):
            pass
        return {}

    def _write_install_state(self):
        """Persist non-secret installer diagnostics across AstrBot plugin reloads."""
        data = {'state':self.install_state, 'error':self.last_error[:600],
                'version':self.version, 'at':datetime.now(timezone.utc).isoformat()}
        target = self.state_path.with_suffix('.tmp')
        try:
            target.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
            if os.name != 'nt': target.chmod(0o600)
            target.replace(self.state_path)
        except OSError:
            # The write failure is surfaced by the install preflight or the job itself.
            pass

    def environment(self):
        """Non-sensitive runtime diagnostics for NAS / Docker installations."""
        try:
            free_mb = shutil.disk_usage(self.root).free // (1024 * 1024)
        except OSError:
            free_mb = None
        container = Path('/.dockerenv').exists()
        return {'container':container, 'python_platform':platform.system(),
                'free_mb':free_mb, 'writable':os.access(self.root, os.W_OK | os.X_OK)}

    def settings(self):
        default = {'mode': 'external', 'bot_name': '', 'start_on_boot': False, 'download_mode': 'auto',
                   'profile': 'compatible', 'on_demand': True, 'idle_minutes': 10}
        if self.settings_path.exists():
            try:
                obj = json.loads(self.settings_path.read_text(encoding='utf-8'))
                default.update({k:v for k,v in obj.items() if k in default})
            except (OSError, ValueError, TypeError):
                pass
        return default

    def save_settings(self, values):
        if not isinstance(values, dict) or set(values) - {'mode','bot_name','start_on_boot','download_mode','profile','on_demand','idle_minutes'}:
            raise ValueError('不支持的 ASF 设置')
        for key, value in values.items():
            if key == 'mode' and value not in ('external','managed'):
                raise ValueError('ASF 模式只能选 external 或 managed')
            if key == 'bot_name' and value and not BOT_RE.fullmatch(value):
                raise ValueError('ASF Bot 名称只允许英文、数字、_、-，最长64位')
            if key == 'download_mode' and value not in ('auto', 'mirror', 'official'):
                raise ValueError('下载模式只能选自动加速、只用镜像或只用官方')
            if key == 'start_on_boot' and type(value) is not bool:
                raise ValueError('自动启动必须是布尔值')
            if key == 'profile' and value not in ('performance', 'compatible'):
                raise ValueError('ASF 运行模式只能选高性能或低资源兼容')
            if key == 'on_demand' and type(value) is not bool:
                raise ValueError('按需启动必须是布尔值')
            if key == 'idle_minutes' and (type(value) is not int or value not in (5, 10, 15, 30)):
                raise ValueError('空闲停止时间只能设置为 5、10、15 或 30 分钟')
        saved = {**self.settings(),**values}
        if saved['mode'] == 'managed' and not self.installed():
            raise ValueError('请先通过官方发布包安装托管 ASF')
        temp = self.settings_path.with_suffix('.tmp')
        temp.write_text(json.dumps(saved,ensure_ascii=False,indent=2),encoding='utf-8')
        if os.name != 'nt': temp.chmod(0o600)
        temp.replace(self.settings_path)
        # Apply on-demand timer policy immediately; child runtime profile still needs restart.
        if not saved['on_demand'] or saved['mode'] != 'managed':
            self._cancel_idle_timer()
        elif self._idle_task is not None and not self._idle_task.done() and not self._active_claims:
            self._cancel_idle_timer()
            if self.running():
                self._idle_task = asyncio.create_task(self._stop_when_idle(saved['idle_minutes']))
        return saved

    def binary(self):
        return self.path / ('ArchiSteamFarm.exe' if os.name == 'nt' else 'ArchiSteamFarm')

    def installed(self):
        return self.binary().is_file()

    def running(self):
        return self.process is not None and self.process.returncode is None

    def rss_mb(self):
        """Process resident memory on Linux, never includes credentials."""
        if not self.running():
            return None
        pid = getattr(self.process, 'pid', None)
        if not pid or os.name != 'posix':
            return None
        try:
            for line in Path(f'/proc/{pid}/status').read_text(encoding='ascii').splitlines():
                if line.startswith('VmRSS:'):
                    return round(int(line.split()[1]) / 1024, 1)
        except (OSError, ValueError, IndexError):
            pass
        return None

    def _runtime_environment(self, profile):
        """Only applies .NET settings to the ASF child process; never mutates AstrBot environment."""
        env = os.environ.copy()
        if profile == 'compatible':
            # Microsoft's supported escape hatch for Linux containers without libicu.
            env['DOTNET_SYSTEM_GLOBALIZATION_INVARIANT'] = '1'
            env['DOTNET_SYSTEM_GLOBALIZATION_PREDEFINED_CULTURES_ONLY'] = '0'
        elif profile == 'performance':
            env['DOTNET_SYSTEM_GLOBALIZATION_INVARIANT'] = '0'
            env.pop('DOTNET_SYSTEM_GLOBALIZATION_PREDEFINED_CULTURES_ONLY', None)
        else:
            raise ValueError('不支持的 ASF 性能模式')
        return env

    def _configure_optimization(self, profile):
        """Safely preserve all existing ASF.json keys (including the locally stored IPC password)."""
        path = self.path / 'config' / 'ASF.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            settings = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'IPC': True}
        except (OSError, ValueError) as exc:
            raise ValueError('ASF.json 配置文件无法解析；为保护账号数据，未覆盖现有配置') from exc
        if not isinstance(settings, dict):
            raise ValueError('ASF.json 必须是 JSON 对象')
        optimization = 1 if profile == 'compatible' else 0
        if settings.get('OptimizationMode') == optimization:
            return
        settings['OptimizationMode'] = optimization
        tmp = path.with_suffix('.json.tmp')
        try:
            tmp.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding='utf-8')
            if os.name != 'nt':
                tmp.chmod(0o600)
            tmp.replace(path)
        finally:
            if tmp.exists():
                tmp.unlink()

    async def prepare_for_claim(self):
        """Start a managed ASF only when configured for on-demand use."""
        settings = self.settings()
        if settings['mode'] != 'managed':
            return False
        self._cancel_idle_timer()
        self._active_claims += 1
        try:
            if not self.running() and settings['on_demand']:
                await self.start()
            elif not self.running():
                raise RuntimeError('ASF 当前未运行；请启动 ASF 或勾选按需自动启动')
            return True
        except BaseException:
            self._active_claims -= 1
            raise

    def finish_claim(self):
        self._active_claims = max(0, self._active_claims - 1)
        settings = self.settings()
        if settings['mode'] == 'managed' and settings['on_demand'] and not self._active_claims and self.running():
            self._cancel_idle_timer()
            self._idle_task = asyncio.create_task(self._stop_when_idle(settings['idle_minutes']))

    def _cancel_idle_timer(self):
        task = self._idle_task
        self._idle_task = None
        if task is not None and not task.done() and task is not asyncio.current_task():
            task.cancel()

    async def _stop_when_idle(self, minutes):
        try:
            await asyncio.sleep(minutes * 60)
            if not self._active_claims and self.running():
                await self.stop()
        except asyncio.CancelledError:
            return
        finally:
            if self._idle_task is asyncio.current_task():
                self._idle_task = None

    def status(self):
        return {'installed':self.installed(),'running':self.running(), 'install_state':self.install_state,
                'running_profile': self.running_profile, 'rss_mb': self.rss_mb(),
                'idle_timer_active': self._idle_task is not None and not self._idle_task.done(),
                'error':self.last_error, 'settings':self.settings(), 'version':self.version,
                'variant': archive_variant() if self._supported() else 'unsupported',
                'download_source': self.download_source, 'download_bytes': self.download_bytes,
                'download_total': self.download_total, 'metadata_source': self.metadata_source,
                'ipc_url': 'http://127.0.0.1:1242' if self.running() else '',
                'environment':self.environment(),
                'start_error':self.start_error, 'last_exit_code':self.last_exit_code}

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
        archive_variant()  # Surface unsupported Synology CPU architecture immediately.
        info = self.environment()
        if not info['writable']:
            raise ValueError('ASF 私有目录不可写，请检查群晖 Container Manager 的映射卷读写权限')
        if info['free_mb'] is not None and info['free_mb'] < 350:
            raise ValueError('ASF 目录剩余空间低于 350 MB，无法安全解压安装包')
        self.install_state = 'downloading'
        self.last_error = ''
        self.download_source = ''
        self.download_bytes = 0
        self.download_total = 0
        self._write_install_state()
        self.install_task = asyncio.create_task(self._install_job(), name='steam-freebies-asf-install')

    @staticmethod
    def download_urls(official_url, mode):
        """Known relay presets only. No arbitrary admin-provided download URL/SSRF."""
        prefix = 'https://github.com/JustArchiNET/ArchiSteamFarm/releases/download/'
        if not official_url.startswith(prefix):
            raise ValueError('安装包地址不是 ASF 官方 Release')
        if mode not in ('auto', 'mirror', 'official'):
            raise ValueError('下载模式不合法')
        mirrors = [(name, base + official_url) for name, base in DOWNLOAD_RELAYS]
        if mode == 'mirror':
            return mirrors
        if mode == 'official':
            return [('GitHub 官方', official_url)]
        return mirrors + [('GitHub 官方', official_url)]

    @staticmethod
    def official_asset(release, asset_name):
        if not isinstance(release, dict) or release.get('prerelease') or release.get('draft'):
            raise ValueError('ASF 官方元数据无效或不是稳定版')
        version = release.get('tag_name')
        if not isinstance(version, str) or not re.fullmatch(r'[0-9]+(?:\.[0-9]+){2,5}', version):
            raise ValueError('ASF Release 版本号不符合预期')
        asset = next((a for a in release.get('assets', []) if a.get('name') == asset_name), None)
        if not isinstance(asset, dict):
            raise ValueError('官方发布页缺少对应系统架构的安装包')
        digest = str(asset.get('digest') or '')
        if not re.fullmatch(r'sha256:[0-9a-fA-F]{64}', digest):
            raise ValueError('ASF 官方 Release 未提供有效 SHA256')
        url = f'https://github.com/JustArchiNET/ArchiSteamFarm/releases/download/{version}/{asset_name}'
        if asset.get('browser_download_url') != url:
            raise ValueError('ASF 官方 Release 安装包地址不符合预期')
        size = asset.get('size')
        if type(size) is not int or not 1 <= size <= 80 * 1024 * 1024:
            raise ValueError('ASF 官方安装包大小异常')
        return version, url, digest[7:].lower(), size

    async def _release_metadata(self, session, asset_name):
        """Prefer latest release; fall back to audited pinned hash on API network failure."""
        try:
            async with session.get(RELEASE_URL, timeout=aiohttp.ClientTimeout(total=12)) as resp:
                resp.raise_for_status()
                release = await resp.json(content_type=None)
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError):
            digest = PINNED_SHA256.get(asset_name)
            if not digest:
                raise ValueError('此平台没有离线可验证的 ASF 安装包')
            version = PINNED_VERSION
            url = f'https://github.com/JustArchiNET/ArchiSteamFarm/releases/download/{version}/{asset_name}'
            self.metadata_source = f'固定官方校验清单 {version}（GitHub API 不可达）'
            return version, url, digest, 0
        self.metadata_source = 'GitHub 官方最新版本元数据'
        return self.official_asset(release, asset_name)

    async def _download_verified(self, session, url, digest, expected_size, mode):
        errors = []
        for provider, download_url in self.download_urls(url, mode):
            self.download_source = provider
            self.download_bytes = 0
            self.download_total = expected_size
            self.install_state = 'downloading'
            try:
                async with session.get(download_url, timeout=aiohttp.ClientTimeout(total=75)) as resp:
                    resp.raise_for_status()
                    if resp.url.scheme != 'https':
                        raise ValueError('拒绝非 HTTPS 下载跳转')
                    declared = int(resp.headers.get('Content-Length') or 0)
                    if declared > 80 * 1024 * 1024:
                        raise ValueError('下载内容超过 80MB 限制')
                    content_type = resp.headers.get('Content-Type', '').lower()
                    if content_type.startswith(('text/html', 'text/plain')):
                        raise ValueError('镜像返回网页而非 ASF ZIP 压缩包')
                    parts = []
                    running_hash = hashlib.sha256()
                    async for chunk in resp.content.iter_chunked(1024 * 1024):
                        self.download_bytes += len(chunk)
                        if self.download_bytes > 80 * 1024 * 1024:
                            raise ValueError('下载内容超过 80MB 限制')
                        running_hash.update(chunk)
                        parts.append(chunk)
                if not self.download_bytes:
                    raise ValueError('下载为空')
                self.install_state = 'verifying'
                if running_hash.hexdigest().lower() != digest.lower():
                    raise ValueError('SHA256 校验不匹配，拒绝该下载源')
                if expected_size and self.download_bytes != expected_size:
                    raise ValueError('安装包大小与官方元数据不符')
                return b''.join(parts)
            except asyncio.CancelledError:
                raise
            except (aiohttp.ClientError, asyncio.TimeoutError, OSError, ValueError) as exc:
                errors.append(f'{provider}: {type(exc).__name__}: {str(exc)[:100]}')
        raise RuntimeError('ASF 所有下载源均失败；' + '；'.join(errors))

    async def _install_job(self):
        staging = None
        try:
            asset_name = archive_variant()
            headers = {'User-Agent':'AstrBot-Steam-Freebies/0.3', 'Accept':'application/vnd.github+json'}
            timeout = aiohttp.ClientTimeout(total=90)
            async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
                version, url, digest, size = await self._release_metadata(session, asset_name)
                archive = await self._download_verified(
                    session, url, digest, size, self.settings()['download_mode'])
            self.install_state = 'extracting'
            staging = Path(tempfile.mkdtemp(prefix='asf-stage-', dir=self.root))
            verify_and_extract(archive, digest, staging)
            config_dir = staging / 'config'
            config_dir.mkdir(exist_ok=True)
            previous = self.path / 'config'
            if previous.is_dir():
                shutil.copytree(previous, config_dir, dirs_exist_ok=True)
            else:
                ipc_secret = secrets.token_urlsafe(40)
                (config_dir / 'ASF.json').write_text(json.dumps({
                    'IPC': True, 'IPCPassword': ipc_secret, 'OptimizationMode': 1,
                    'UpdatePeriod': 0, 'Headless': True
                }, indent=2), encoding='utf-8')
            if os.name != 'nt':
                for config in config_dir.iterdir():
                    if config.is_file():
                        config.chmod(0o600)
            old = self.root / 'runtime-previous'
            if old.exists():
                shutil.rmtree(old)
            if self.path.exists():
                self.path.rename(old)
            try:
                staging.rename(self.path)
            except Exception:
                if old.exists() and not self.path.exists():
                    old.rename(self.path)
                raise
            staging = None
            if old.exists():
                shutil.rmtree(old)
            self.version = version
            self.install_state = 'installed'
        except asyncio.CancelledError:
            self.install_state = 'cancelled'
            raise
        except Exception as exc:
            self.install_state = 'error'
            self.last_error = f'{type(exc).__name__}: {str(exc)[:600]}'
        finally:
            if staging is not None:
                shutil.rmtree(staging, ignore_errors=True)
            self._write_install_state()

    def _recent_startup_output(self, limit=16384):
        """Read only locally for classification. NEVER return raw logs through the dashboard."""
        try:
            with (self.root / 'asf.log').open('rb') as stream:
                stream.seek(0, os.SEEK_END)
                size = stream.tell()
                stream.seek(max(0, size - limit))
                return stream.read().decode('utf-8', 'replace')
        except OSError:
            return ''

    async def start(self):
        async with self._lock:
            if self.running():
                return
            if not self.installed():
                raise ValueError('请先安装 ASF 官方独立版本')
            self.start_error = ''
            self.last_exit_code = None
            selected_profile = self.settings()['profile']
            self._configure_optimization(selected_profile)
            # Do not accidentally attach to another ASF listening on the default IPC port.
            import socket
            try:
                with socket.create_connection(('127.0.0.1', 1242), timeout=0.2):
                    raise ValueError('本机 1242 端口已被占用，请停止其他 ASF，避免连接错账号')
            except (ConnectionRefusedError, TimeoutError, OSError):
                pass
            self.log_handle = (self.root / 'asf.log').open('ab')
            marker = self.log_handle.tell()
            proc = None
            try:
                # Crucial on fresh installs: ASF normally exits if there are no enabled bots.
                # --process-required keeps IPC alive so accounts can be provisioned later.
                proc = await asyncio.create_subprocess_exec(
                    str(self.binary()), '--no-restart', '--process-required',
                    cwd=str(self.path), stdin=asyncio.subprocess.DEVNULL,
                    stdout=self.log_handle, stderr=asyncio.subprocess.STDOUT,
                    env=self._runtime_environment(selected_profile)
                )
                self.process = proc
                self.running_profile = selected_profile
                await asyncio.sleep(2)
                if proc.returncode is not None:
                    self.last_exit_code = proc.returncode
                    self.log_handle.flush()
                    output = self._recent_startup_output()
                    if marker:
                        # Don't classify an error from an earlier process launch.
                        with (self.root / 'asf.log').open('rb') as stream:
                            stream.seek(marker)
                            output = stream.read(16_384).decode('utf-8', 'replace')
                    self.start_error = diagnose_start_failure(output, proc.returncode)
                    raise RuntimeError(self.start_error)
            except asyncio.CancelledError:
                if proc and proc.returncode is None:
                    proc.terminate()
                    await proc.wait()
                raise
            except Exception as exc:
                if not self.start_error:
                    self.start_error = diagnose_start_failure(error=exc)
                if proc and proc.returncode is None:
                    proc.terminate()
                    try:
                        await asyncio.wait_for(proc.wait(), timeout=5)
                    except asyncio.TimeoutError:
                        proc.kill()
                        await proc.wait()
                raise RuntimeError(self.start_error) from exc
            finally:
                if self.process is None or self.process.returncode is not None:
                    self.process = None
                    self.running_profile = ''
                    if self.log_handle:
                        self.log_handle.close()
                        self.log_handle = None

    async def stop(self):
        self._cancel_idle_timer()
        async with self._lock:
            proc=self.process
            self.process=None
            self.running_profile = ''
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
