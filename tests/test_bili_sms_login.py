"""Bilibili official SMS/Geetest path: no CAPTCHA bypass or credential disclosure."""
import asyncio
import json
import time

import pytest

from steam_freebies.bili_auth import BiliAuth, _api_data, is_official_scan_url


def test_credential_validation_and_no_login_without_real_session(tmp_path):
    auth = BiliAuth(tmp_path)
    with pytest.raises(ValueError, match='验证码'):
        asyncio.run(auth.sms_login('bad'))
    with pytest.raises(ValueError, match='过期'):
        asyncio.run(auth.sms_login('123456'))
    with pytest.raises(ValueError, match='没有返回有效'):
        auth._save({'bili_jct': 'x'})
    assert not auth.path.exists()
    assert not auth.status()['configured']


def test_sms_send_requires_real_captcha_and_does_not_store_phone(tmp_path):
    auth = BiliAuth(tmp_path)
    params = ('13800000000', 1, 'x' * 32, 'y' * 32, 'y' * 32 + '|jordan')
    with pytest.raises(ValueError, match='人机验证'):
        asyncio.run(auth.sms_send(*params))
    auth._captcha = {'token': 'z'*32, 'challenge': 'x'*32, 'at': time.monotonic()}
    with pytest.raises(ValueError, match='人机验证'):
        asyncio.run(auth.sms_send('13800000000', 1, 'wrong', 'y'*32, 'y'*32+'|jordan'))
    assert not auth.path.exists()
    assert '13800000000' not in str(auth.status())


def test_sms_save_allows_only_known_cookie_names_and_redacts(tmp_path):
    auth = BiliAuth(tmp_path)
    auth._save({'SESSDATA':'demo-valid-session','DedeUserID':'123',
                'unexpected_cookie':'must_not_persist', 'bili_jct':'csrf_token'})
    assert auth.status()['configured']
    assert 'demo-valid-session' not in str(auth.status())
    assert 'demo-valid-session' in auth.cookie_header()
    stored=json.loads(auth.path.read_text())
    assert set(stored)=={'SESSDATA','DedeUserID','bili_jct'}
    auth.logout()
    assert not auth.path.exists()


def test_bilibili_status_and_official_domain_restrictions(tmp_path):
    auth=BiliAuth(tmp_path)
    assert auth.status()['qr_pending'] is False
    assert auth.status()['sms_pending'] is False
    assert is_official_scan_url('https://passport.bilibili.com/h5-app/passport/login/scan')
    assert not is_official_scan_url('https://passport.bilibili.com.evil.test/x')
    assert not is_official_scan_url('http://passport.bilibili.com/x')
    with pytest.raises(ValueError, match='code=412'):
        _api_data({'code': 412, 'message': 'could include credentials'}, '登录')

class _Reply:
    def __init__(self, body, cookies=None):
        from http.cookies import SimpleCookie
        self.body=body
        self.cookies=SimpleCookie()
        for k, v in (cookies or {}).items():
            self.cookies[k]=v
    async def __aenter__(self): return self
    async def __aexit__(self, *args): pass
    def raise_for_status(self): pass
    async def json(self, content_type=None): return self.body


class _Session:
    responses=[]
    calls=[]
    def __init__(self, *args, **kwargs): pass
    async def __aenter__(self): return self
    async def __aexit__(self, *args): pass
    def get(self, url, **kwargs):
        self.calls.append(('GET',url,kwargs))
        return self.responses.pop(0)
    def post(self, url, **kwargs):
        self.calls.append(('POST',url,kwargs))
        return self.responses.pop(0)


def test_official_sms_flow_with_real_geetest_proof_and_no_credential_echo(tmp_path, monkeypatch):
    import steam_freebies.bili_auth as m
    monkeypatch.setattr(m.aiohttp, 'ClientSession', _Session)
    auth=BiliAuth(tmp_path)
    _Session.calls=[]
    _Session.responses=[
        _Reply({'code':0,'data':{'type':'geetest','token':'a'*32,
             'geetest':{'gt':'b'*32,'challenge':'c'*32}}}),
        _Reply({'code':0,'data':{'captcha_key':'d'*32}}),
        _Reply({'code':0,'data':{'status':0}}, cookies={
            'SESSDATA':'private-cookie', 'bili_jct':'private-csrf'})
    ]
    challenge=asyncio.run(auth.sms_captcha())
    assert challenge['gt']=='b'*32
    assert 'a'*32 not in str(challenge)  # Bili login token never reaches browser
    sent=asyncio.run(auth.sms_send('13800000000',1,'c'*32,'e'*32,'e'*32+'|jordan'))
    assert sent['ok'] and '13800000000' not in str(sent)
    assert _Session.calls[1][0]=='POST'
    assert _Session.calls[1][2]['data']['token']=='a'*32
    success=asyncio.run(auth.sms_login('123456'))
    assert success['ok']
    assert '123456' not in str(success) and 'private-cookie' not in str(success)
    assert auth.status()['configured'] and not auth.status()['sms_pending']
    assert '13800000000' not in auth.path.read_text()
    assert '123456' not in auth.path.read_text()
    assert 'private-cookie' in auth.path.read_text()


def test_sms_code_failure_does_not_persist_session(tmp_path, monkeypatch):
    import steam_freebies.bili_auth as m
    monkeypatch.setattr(m.aiohttp, 'ClientSession', _Session)
    auth=BiliAuth(tmp_path)
    auth._sms={'tel':'13800000000','cid':1,'key':'k'*32,'at':time.monotonic()}
    _Session.responses=[_Reply({'code':1006, 'message':'bad code'})]
    with pytest.raises(ValueError,match='1006'):
        asyncio.run(auth.sms_login('123456'))
    assert not auth.path.exists()
