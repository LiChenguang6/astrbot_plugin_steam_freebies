"""v0.6.6 manual Bilibili login session import privacy and fail-closed regressions."""
import asyncio
import json
from pathlib import Path

import pytest
from steam_freebies.bili_auth import BiliAuth, parse_manual_session, public_nav_identity


SESS = 'exampleBiliSessValueSecret123456789'


def test_cookie_parser_accepts_only_relevant_keys():
    a = parse_manual_session('Cookie: buvid3=ignore; SESSDATA='+SESS+'; bili_jct=abc123; DedeUserID=42')
    assert a == {'SESSDATA':SESS, 'bili_jct':'abc123', 'DedeUserID':'42'}
    assert parse_manual_session(SESS) == {'SESSDATA': SESS}
    assert parse_manual_session('SESSDATA='+SESS)=={'SESSDATA':SESS}


@pytest.mark.parametrize('bad', [
    '', 'foo=bar', 'Authorization: Bearer BAD-SECRET', 'https://bilibili.com',
    'SESSDATA=a', f'SESSDATA={SESS}; SESSDATA=another',
    f'SESSDATA={SESS}\r\nHeader: injected', f'SESSDATA={SESS}; DedeUserID=abc',
    f'SESSDATA={SESS}; bili_jct=one\nother',
])
def test_import_rejects_bad_tokens_and_injection(bad):
    with pytest.raises(ValueError): parse_manual_session(bad)


def test_official_nav_requires_explicit_login():
    good={'code':0,'data':{'isLogin':True,'mid':12345,'uname':'昵称','email':'private@example.com'}}
    assert public_nav_identity(good)=={'verified':True,'mid':12345,'uname':'昵称'}
    for bad in [None, {}, {'code':-101}, {'code':0, 'data':{}}, {'code':0,'data':{'isLogin':False,'mid':12}}, {'code':0,'data':{'isLogin':True,'mid':0}}]:
        with pytest.raises(ValueError):public_nav_identity(bad)


def test_import_saves_only_after_success_and_not_return_secrets(tmp_path,monkeypatch):
    b=BiliAuth(tmp_path)
    async def verified(cookies):
        assert cookies == {'SESSDATA':SESS,'bili_jct':'csrf-secret'}
        return {'verified':True,'mid':8527,'uname':'已登录用户'}
    monkeypatch.setattr(b,'_verify_cookies',verified)
    reply=asyncio.run(b.import_session(f'SESSDATA={SESS}; bili_jct=csrf-secret'))
    assert reply['ok'] and reply['verified'] and reply['mid']==8527
    assert 'csrf-secret' not in str(reply) and SESS not in str(reply)
    assert b.cookie_header()==f'SESSDATA={SESS}; bili_jct=csrf-secret'
    assert b.path.stat().st_mode & 0o077 == 0
    assert 'csrf-secret' not in str(b.status()) and SESS not in str(b.status())
    check=asyncio.run(b.verify_session())
    assert check['verified']
    b.logout()
    assert not b.path.exists()


def test_failed_import_never_replaces_existing_session(tmp_path,monkeypatch):
    b=BiliAuth(tmp_path)
    old='previousSessionSecret0000'
    b._save({'SESSDATA':old})
    async def invalid(cookies):
        raise ValueError('会话验证失败')
    monkeypatch.setattr(b,'_verify_cookies',invalid)
    with pytest.raises(ValueError):
        asyncio.run(b.import_session(SESS))
    assert b.cookie_header()=='SESSDATA='+old


def test_not_logged_in_on_bili_verification(tmp_path,monkeypatch):
    import steam_freebies.bili_auth as module
    b=BiliAuth(tmp_path)
    class Response:
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        def raise_for_status(self):pass
        async def json(self,content_type=None):return {'code':0,'data':{'isLogin':False}}
    class Session:
        def __init__(self,*a,**kwargs):
            assert kwargs.get('trust_env') is False
            assert kwargs['headers']['Cookie']=='SESSDATA='+SESS
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        def get(self, url, **kwargs):
            assert url=='https://api.bilibili.com/x/web-interface/nav'
            assert kwargs['allow_redirects'] is False
            return Response()
    monkeypatch.setattr(module.aiohttp,'ClientSession',Session)
    with pytest.raises(ValueError,match='未登录'):
        asyncio.run(b.import_session(SESS))
    assert not b.path.exists()
