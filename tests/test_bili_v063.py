"""Bilibili v0.6.3 login robustness: bundled QR and safe handling of SMS denials."""
import asyncio
import time
from http.cookies import SimpleCookie

import pytest

from steam_freebies.bili_auth import BiliAuth


class Reply:
    def __init__(self, body):
        self.body = body
        self.cookies = SimpleCookie()
    async def __aenter__(self): return self
    async def __aexit__(self, *args): pass
    def raise_for_status(self): pass
    async def json(self, content_type=None): return self.body


class Session:
    reply = None
    def __init__(self, *args, **kwargs): pass
    async def __aenter__(self): return self
    async def __aexit__(self, *args): pass
    def get(self, *args, **kwargs): return self.reply
    def post(self, *args, **kwargs): return self.reply


def test_qr_matrix_is_generated_locally_without_external_python_qrcode(tmp_path, monkeypatch):
    import steam_freebies.bili_auth as module
    monkeypatch.setattr(module.aiohttp, 'ClientSession', Session)
    key = 'a' * 32
    Session.reply = Reply({'code': 0, 'data': {'qrcode_key': key,
        'url': f'https://passport.bilibili.com/h5-app/passport/login/scan?qrcode_key={key}'}})
    result = asyncio.run(BiliAuth(tmp_path).qr_start())
    matrix = result['matrix']
    assert len(matrix) >= 29
    assert all(len(row) == len(matrix) and set(row) <= {'0', '1'} for row in matrix)
    assert not any(key in str(value) for value in result.values())
    # Full white quiet zone: compliant QR codes need four modules.
    assert all(x == '0' for row in matrix[:4] for x in row)
    assert all(row[:4] == '0000' for row in matrix)


def test_bili_qr_denial_has_actionable_no_secret_error(tmp_path, monkeypatch):
    import steam_freebies.bili_auth as module
    monkeypatch.setattr(module.aiohttp, 'ClientSession', Session)
    Session.reply = Reply({'code': -412, 'message': 'secret server detail'})
    with pytest.raises(ValueError, match='code=-412') as error:
        asyncio.run(BiliAuth(tmp_path).qr_start())
    assert 'secret' not in str(error.value)


def test_sms_86005_no_guess_and_rate_limit(tmp_path, monkeypatch):
    import steam_freebies.bili_auth as module
    monkeypatch.setattr(module.aiohttp, 'ClientSession', Session)
    auth = BiliAuth(tmp_path)
    auth._captcha={'token': 'z'*32, 'challenge': 'x'*32, 'at': time.monotonic()}
    Session.reply=Reply({'code': 86005, 'message': 'potentially sensitive message'})
    with pytest.raises(ValueError, match='86005') as error:
        asyncio.run(auth.sms_send('13800000000',1,'x'*32,'y'*32,'y'*32+'|jordan'))
    assert 'potentially sensitive' not in str(error.value)
    assert auth._captcha is None
    auth._captcha={'token': 'z'*32, 'challenge': 'x'*32, 'at': time.monotonic()}
    with pytest.raises(ValueError, match='60 秒'):
        asyncio.run(auth.sms_send('13800000000',1,'x'*32,'y'*32,'y'*32+'|jordan'))
