"""Bilibili QR-login for opt-in, read-only metadata requests.

The QR token is ephemeral. Session cookies are written only to the private
AstrBot data directory; the browser never sees SESSDATA, bili_jct or a poll key.
No bypass of anti-bot challenges and no Bilibili password collection.
"""
import base64
import io
import json
import os
import re
import time
from pathlib import Path
from urllib.parse import urlsplit

import aiohttp

PASSPORT = 'https://passport.bilibili.com'
ALLOWED = ('SESSDATA', 'bili_jct', 'DedeUserID', 'DedeUserID__ckMd5')
QRCODE_RE = re.compile(r'^[a-zA-Z0-9]{16,80}$')


def is_official_scan_url(value):
    if not isinstance(value, str) or len(value) > 500:
        return False
    url = urlsplit(value)
    return url.scheme == 'https' and url.hostname == 'passport.bilibili.com' and not url.username and not url.password


class BiliAuth:
    def __init__(self, data_dir):
        self.path = Path(data_dir) / 'bili-session.json'
        self._qr_key = ''
        self._qr_started = 0
        self._qr_last_poll = 0

    def _read(self):
        try:
            raw = json.loads(self.path.read_text(encoding='utf-8'))
            if isinstance(raw, dict):
                return {k:v for k,v in raw.items() if k in ALLOWED and type(v) is str and v and len(v)<1024 and '\n' not in v and '\r' not in v}
        except (OSError, ValueError):
            pass
        return {}

    def status(self):
        saved = self._read()
        return {'configured': bool(saved.get('SESSDATA')), 'status': '已保存登录会话（不代表永不过期）' if saved.get('SESSDATA') else '未登录',
                'qr_pending': bool(self._qr_key) and time.monotonic()-self._qr_started < 180}

    def cookie_header(self):
        cookies = self._read()
        return '; '.join(f'{k}={v}' for k, v in cookies.items())

    def headers(self):
        headers = {'User-Agent':'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/122.0 Safari/537.36',
                   'Referer':'https://www.bilibili.com/'}
        cookie = self.cookie_header()
        if cookie:
            headers['Cookie'] = cookie
        return headers

    async def qr_start(self):
        import qrcode
        from qrcode.image.svg import SvgPathImage
        async with aiohttp.ClientSession(headers=self.headers(), timeout=aiohttp.ClientTimeout(total=12)) as session:
            async with session.get(PASSPORT+'/x/passport-login/web/qrcode/generate',allow_redirects=False) as response:
                response.raise_for_status()
                body = await response.json(content_type=None)
        info = body.get('data') if isinstance(body, dict) and body.get('code') == 0 else None
        url = info.get('url') if isinstance(info, dict) else None
        key = info.get('qrcode_key') if isinstance(info, dict) else None
        if not is_official_scan_url(url) or not isinstance(key,str) or not QRCODE_RE.fullmatch(key):
            raise ValueError('B站没有返回有效的官方登录二维码')
        self._qr_key, self._qr_started, self._qr_last_poll = key, time.monotonic(), 0
        qr = qrcode.QRCode(border=2, box_size=6)
        qr.add_data(url)
        qr.make(fit=True)
        image = qr.make_image(image_factory=SvgPathImage)
        content = image.to_string()
        return {'ok':True, 'image':'data:image/svg+xml;base64,'+base64.b64encode(content).decode('ascii'),
                'expires_seconds':180, 'notice':'请使用哔哩哔哩手机 App 扫码并在 App 内确认；二维码 180 秒后失效'}

    async def qr_poll(self):
        if not self._qr_key or time.monotonic()-self._qr_started > 180:
            self._qr_key = ''
            return {'state':'expired','notice':'二维码已失效，请重新生成'}
        if time.monotonic() - self._qr_last_poll < 2:
            return {'state':'pending','notice':'请在手机 B站 App 中扫码确认'}
        self._qr_last_poll = time.monotonic()
        async with aiohttp.ClientSession(headers=self.headers(),timeout=aiohttp.ClientTimeout(total=12)) as session:
            async with session.get(PASSPORT+'/x/passport-login/web/qrcode/poll',
                                   params={'qrcode_key':self._qr_key},allow_redirects=False) as response:
                response.raise_for_status()
                body = await response.json(content_type=None)
                cookies = {k:v.value for k,v in response.cookies.items() if k in ALLOWED}
        info = body.get('data') if isinstance(body,dict) and body.get('code')==0 else {}
        code = info.get('code') if isinstance(info,dict) else -1
        if code == 86101:
            return {'state':'pending','notice':'等待扫描二维码'}
        if code == 86090:
            return {'state':'scanned','notice':'已扫码，等待手机确认授权'}
        if code == 86038:
            self._qr_key = ''
            return {'state':'expired','notice':'二维码过期，请重新生成'}
        if code != 0 or not cookies.get('SESSDATA'):
            raise ValueError('B站登录未成功；服务器没有收到有效会话，请重新扫码')
        # Don't trust any arbitrary response cookies: fixed whitelist only.
        self.path.parent.mkdir(parents=True,exist_ok=True)
        temp = self.path.with_suffix('.tmp')
        temp.write_text(json.dumps(cookies,ensure_ascii=False),encoding='utf-8')
        if os.name != 'nt':temp.chmod(0o600)
        temp.replace(self.path)
        self._qr_key = ''
        return {'state':'success','notice':'B站已扫码登录，会话仅保存于 AstrBot 私有目录'}

    def logout(self):
        self._qr_key = ''
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
        return {'ok':True,'notice':'已清除插件本地 B站登录会话（不会撤销其他设备登录）'}
