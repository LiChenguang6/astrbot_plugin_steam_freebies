"""Optional Bilibili QR and human-verified SMS login (public endpoints).

A browser completes the real GeeTest challenge; the plugin never computes or
bypasses it. QR/session keys and SMS tokens stay in server memory. Cookies are
stored in the AstrBot private data directory, never echoed in a WebUI response.
"""
import asyncio
import base64
import json
import os
import re
import time
from pathlib import Path
from urllib.parse import urlsplit, urlencode, parse_qs

import aiohttp

from ._qr_vendor import QRCode, constants  # Matrix-only QR generator bundled under BSD-3-Clause

PASSPORT = 'https://passport.bilibili.com'
ALLOWED = ('SESSDATA', 'bili_jct', 'DedeUserID', 'DedeUserID__ckMd5')
QRCODE_RE = re.compile(r'^[a-zA-Z0-9]{16,80}$')
PHONE_RE = re.compile(r'^\d{6,20}$')
OTP_RE = re.compile(r'^\d{4,8}$')
CHALLENGE_RE = re.compile(r'^[a-zA-Z0-9_-]{20,150}$')
CAPTCHA_ANSWER_RE = re.compile(r'^[a-zA-Z0-9_\-|]{15,512}$')


def is_official_scan_url(value):
    if not isinstance(value, str) or len(value) > 500:
        return False
    url = urlsplit(value)
    return url.scheme == 'https' and url.hostname == 'passport.bilibili.com' and not url.username and not url.password


def _safe_scan_url(url, key):
    """Use Bilibili's supplied official URL if it matches key, else canonical URL.

    Never send users to arbitrary hosts and never expose a QR login key in diagnostics.
    The key comes from an authenticated, code=0 Bilibili response.
    """
    canonical = PASSPORT + '/h5-app/passport/login/scan?' + urlencode({'navhide': '1', 'qrcode_key': key})
    if not is_official_scan_url(url):
        return canonical
    parts = urlsplit(url)
    if parts.path != '/h5-app/passport/login/scan':
        return canonical
    embedded = parse_qs(parts.query).get('qrcode_key', [])
    return url if embedded == [key] else canonical


def _api_data(payload, operation):
    if not isinstance(payload, dict):
        raise ValueError(f'B站{operation}返回数据无效')
    if payload.get('code') != 0:
        code = payload.get('code')
        # Only the numeric error code is propagated; no sensitive server text.
        raise ValueError(f'B站{operation}被拒绝（code={code if type(code) is int else "unknown"}）；请稍后重试或查看验证状态')
    data = payload.get('data')
    return data if isinstance(data, dict) else {}


class BiliAuth:
    def __init__(self, data_dir):
        self.path = Path(data_dir) / 'bili-session.json'
        self._qr_key = ''
        self._qr_started = 0
        self._qr_last_poll = 0
        self._qr_prepare_task = None
        self._qr_prepared_data = None
        self._qr_prepare_error = ''
        self._qr_generation = 0
        self._captcha = None
        self._sms = None
        self._sms_last_sent = 0
        self._sms_last_attempt = 0

    def _read(self):
        try:
            raw = json.loads(self.path.read_text(encoding='utf-8'))
            if isinstance(raw, dict):
                return {k: v for k, v in raw.items() if k in ALLOWED and type(v) is str and v and len(v) < 1024 and '\n' not in v and '\r' not in v}
        except (OSError, ValueError):
            pass
        return {}

    def _save(self, cookies):
        clean = {k: v for k, v in cookies.items() if k in ALLOWED and type(v) is str and v and len(v) < 1024 and not any(c in v for c in '\r\n;')}
        if not clean.get('SESSDATA'):
            raise ValueError('B站没有返回有效登录会话，未保存 Cookie')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix('.tmp')
        try:
            temp.write_text(json.dumps(clean, ensure_ascii=False), encoding='utf-8')
            if os.name != 'nt':
                temp.chmod(0o600)
            temp.replace(self.path)
        finally:
            if temp.exists():
                temp.unlink()

    def status(self):
        saved = self._read()
        return {'configured': bool(saved.get('SESSDATA')),
                'status': '已保存登录会话（可能过期）' if saved.get('SESSDATA') else '未登录',
                'qr_pending': bool(self._qr_key) and time.monotonic() - self._qr_started < 180,
                'sms_pending': bool(self._sms) and time.monotonic() - self._sms['at'] < 300}

    def cookie_header(self):
        return '; '.join(f'{k}={v}' for k, v in self._read().items())

    def headers(self):
        headers = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/122.0 Safari/537.36',
                   'Referer': 'https://www.bilibili.com/'}
        cookie = self.cookie_header()
        if cookie:
            headers['Cookie'] = cookie
        return headers

    async def qr_start(self):
        try:
            async with aiohttp.ClientSession(headers=self.headers(), timeout=aiohttp.ClientTimeout(total=12)) as session:
                async with session.get(PASSPORT + '/x/passport-login/web/qrcode/generate', allow_redirects=False) as response:
                    response.raise_for_status()
                    body = await response.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError) as exc:
            raise ValueError(f'B站二维码接口连接失败（{type(exc).__name__}）；请检查 NAS 到 passport.bilibili.com 的网络') from None
        info = _api_data(body, '二维码初始化')
        url, key = info.get('url'), info.get('qrcode_key')
        if not isinstance(key, str) or not QRCODE_RE.fullmatch(key):
            url_present = isinstance(url, str) and bool(url)
            key_present = isinstance(key, str) and bool(key)
            raise ValueError('B站二维码接口成功，但未发放有效扫码密钥'
                             f'（URL：{"有" if url_present else "无"}，密钥：{"有但格式异常" if key_present else "无"}）。'
                             '请检查 NAS 的 B站访问环境，无法通过本地生成二维码解决')
        url = _safe_scan_url(url, key)
        qr = QRCode(border=4, box_size=6, error_correction=constants.ERROR_CORRECT_M)
        qr.add_data(url)
        qr.make(fit=True)
        # Render as native DOM/SVG in the iframe: avoids blocked data: images, popups and navigation.
        matrix = [''.join('1' if bit else '0' for bit in row) for row in qr.get_matrix()]
        self._qr_key, self._qr_started, self._qr_last_poll = key, time.monotonic(), 0
        return {'ok': True, 'matrix': matrix, 'expires_seconds': 180,
                'notice': '手机 B站 App 扫描下方二维码并确认。页面不需要跳转；180 秒内有效。'}

    def qr_begin(self):
        """Return instantly to AstrBot's WebUI; remote Bilibili may stall or time out.

        The actual HTTPS call executes as an asyncio task; polling never waits on it.
        """
        import asyncio
        task = self._qr_prepare_task
        if task is not None and not task.done():
            return {'state': 'preparing', 'notice': 'B站二维码仍在申请中，请稍后查看'}
        self._qr_generation += 1
        generation = self._qr_generation
        self._qr_key = ''
        self._qr_prepared_data = None
        self._qr_prepare_error = ''
        self._qr_prepare_task = asyncio.create_task(self._qr_prepare(generation), name='bili-qr-prepare')
        return {'state': 'preparing', 'notice': '已提交申请；页面将自动显示二维码或接口错误'}

    async def _qr_prepare(self, generation):
        try:
            result = await self.qr_start()
        except asyncio.CancelledError:
            return
        except ValueError as exc:
            if generation == self._qr_generation:
                self._qr_prepare_error = str(exc)[:240]
            return
        except Exception as exc:
            if generation == self._qr_generation:
                self._qr_prepare_error = f'二维码初始化失败（{type(exc).__name__}）；检查 AstrBot 容器日志'
            return
        if generation == self._qr_generation:
            self._qr_prepared_data = result

    def qr_prepare_status(self):
        if self._qr_prepared_data:
            if time.monotonic() - self._qr_started >= 180:
                self._qr_prepared_data = None
                return {'state': 'expired', 'notice': '二维码准备完成但已过期，请重新生成'}
            return {'state': 'ready', **self._qr_prepared_data}
        if self._qr_prepare_error:
            return {'state': 'failed', 'notice': self._qr_prepare_error}
        if self._qr_prepare_task is not None and not self._qr_prepare_task.done():
            return {'state': 'preparing', 'notice': '正在连接 B站二维码服务…'}
        return {'state': 'idle', 'notice': '请点击生成 B站登录二维码'}

    async def qr_poll(self):
        if not self._qr_key or time.monotonic() - self._qr_started > 180:
            self._qr_key = ''
            return {'state': 'expired', 'notice': '二维码已失效，请重新生成'}
        if time.monotonic() - self._qr_last_poll < 2:
            return {'state': 'pending', 'notice': '请在手机 B站 App 中扫码确认'}
        self._qr_last_poll = time.monotonic()
        async with aiohttp.ClientSession(headers=self.headers(), timeout=aiohttp.ClientTimeout(total=12)) as session:
            async with session.get(PASSPORT + '/x/passport-login/web/qrcode/poll',
                                   params={'qrcode_key': self._qr_key}, allow_redirects=False) as response:
                response.raise_for_status()
                body = await response.json(content_type=None)
                cookies = {k: v.value for k, v in response.cookies.items() if k in ALLOWED}
        info = _api_data(body, '扫码登录')
        code = info.get('code')
        if code == 86101:
            return {'state': 'pending', 'notice': '等待扫描二维码'}
        if code == 86090:
            return {'state': 'scanned', 'notice': '已扫码，等待手机确认授权'}
        if code == 86038:
            self._qr_key = ''
            return {'state': 'expired', 'notice': '二维码已过期，请重新生成'}
        if code != 0:
            raise ValueError('B站扫码登录未成功，请重新扫码')
        self._save(cookies)
        self._qr_key = ''
        return {'state': 'success', 'notice': 'B站已扫码登录，私有会话已保存'}

    async def sms_captcha(self):
        """Fetch official captcha challenge; real GeeTest is solved by the user in-browser."""
        async with aiohttp.ClientSession(headers=self.headers(), timeout=aiohttp.ClientTimeout(total=12)) as session:
            async with session.get(PASSPORT + '/x/passport-login/captcha',
                                   params={'source': 'main_web'}, allow_redirects=False) as response:
                response.raise_for_status()
                body = await response.json(content_type=None)
        data = _api_data(body, '人机验证初始化')
        geetest = data.get('geetest')
        token = data.get('token')
        if (data.get('type') != 'geetest' or not isinstance(geetest, dict) or
                not isinstance(token, str) or not CHALLENGE_RE.fullmatch(token)):
            raise ValueError('B站未提供支持的极验挑战，请使用扫码登录')
        gt, challenge = geetest.get('gt'), geetest.get('challenge')
        if (not isinstance(gt, str) or not CHALLENGE_RE.fullmatch(gt) or
                not isinstance(challenge, str) or not CHALLENGE_RE.fullmatch(challenge)):
            raise ValueError('B站极验挑战数据无效')
        self._captcha = {'token': token, 'challenge': challenge, 'at': time.monotonic()}
        return {'ok': True, 'gt': gt, 'challenge': challenge,
                'notice': '请完成人机验证；验证成功后才能申请短信验证码'}

    async def sms_send(self, tel, cid, challenge, validate, seccode):
        if not isinstance(tel, str) or not PHONE_RE.fullmatch(tel):
            raise ValueError('请输入有效的手机号码（只填数字）')
        if type(cid) is not int or not 1 <= cid <= 999:
            raise ValueError('国家/地区代码无效')
        c = self._captcha
        if not c or time.monotonic() - c['at'] > 180:
            raise ValueError('人机验证已失效，请重新完成验证')
        if challenge != c['challenge'] or not isinstance(validate, str) or not CAPTCHA_ANSWER_RE.fullmatch(validate) or not isinstance(seccode, str) or not CAPTCHA_ANSWER_RE.fullmatch(seccode):
            raise ValueError('请先完成 B站官方人机验证')
        if time.monotonic() - max(self._sms_last_sent, self._sms_last_attempt) < 60:
            raise ValueError('短信发送需间隔至少 60 秒；先等待，再重新完成新的极验，不要频繁尝试')
        fields = {'tel': tel, 'cid': str(cid), 'source': 'main_web',
                  'token': c['token'], 'challenge': challenge,
                  'validate': validate, 'seccode': seccode}
        self._captcha = None  # Reuse of a GeeTest solution is not allowed.
        self._sms_last_attempt = time.monotonic()
        async with aiohttp.ClientSession(headers=self.headers(), timeout=aiohttp.ClientTimeout(total=15)) as session:
            async with session.post(PASSPORT + '/x/passport-login/web/sms/send',
                                    data=fields, allow_redirects=False) as response:
                response.raise_for_status()
                body = await response.json(content_type=None)
        if isinstance(body, dict) and body.get('code') == 86005:
            # Undocumented by the public endpoint references. Don't mislabel it as bad SMS code.
            raise ValueError('B站短信发送被拒绝（code=86005）。B站未公开明确原因，可能是登录环境或人机验证风险；请勿连续重试，建议先用扫码登录')
        data = _api_data(body, '发送短信验证码')
        key = data.get('captcha_key')
        if not isinstance(key, str) or not QRCODE_RE.fullmatch(key):
            raise ValueError('B站没有返回有效短信登录令牌')
        self._sms_last_sent = time.monotonic()
        self._sms = {'tel': tel, 'cid': cid, 'key': key, 'at': time.monotonic()}
        return {'ok': True, 'notice': '验证码发送请求已成功；请在 5 分钟内填写短信验证码'}

    async def sms_login(self, code):
        if not isinstance(code, str) or not OTP_RE.fullmatch(code):
            raise ValueError('请输入收到的 4–8 位数字短信验证码')
        s = self._sms
        if not s or time.monotonic() - s['at'] > 300:
            self._sms = None
            raise ValueError('验证码已过期，请重新申请')
        async with aiohttp.ClientSession(headers=self.headers(), timeout=aiohttp.ClientTimeout(total=15)) as session:
            async with session.post(PASSPORT + '/x/passport-login/web/login/sms', data={
                'tel': s['tel'], 'cid': str(s['cid']), 'source': 'main_web',
                'captcha_key': s['key'], 'code': code, 'keep': 'true'},
                allow_redirects=False) as response:
                response.raise_for_status()
                body = await response.json(content_type=None)
                cookies = {k: v.value for k, v in response.cookies.items() if k in ALLOWED}
        _api_data(body, '短信验证码登录')
        # Never claim login if the actual authorized session cookie was not returned.
        self._save(cookies)
        self._sms = None
        return {'ok': True, 'notice': 'B站短信验证码登录成功，私有会话已保存'}

    def cancel_qr_preparation(self):
        self._qr_generation += 1
        if self._qr_prepare_task is not None and not self._qr_prepare_task.done():
            self._qr_prepare_task.cancel()
        self._qr_prepare_task = None
        self._qr_prepared_data = None
        self._qr_prepare_error = ''
        self._qr_key = ''

    def logout(self):
        self.cancel_qr_preparation()
        self._captcha = None
        self._sms = None
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
        return {'ok': True, 'notice': '已清除插件本地 B站会话（不会影响手机 App 登录）'}
