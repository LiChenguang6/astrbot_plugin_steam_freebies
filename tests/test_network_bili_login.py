"""v0.6.1 regression tests: proxy safety, persisted Bili login privacy, repeated QQ tests."""
import asyncio
import json
from http.cookies import SimpleCookie

import pytest

from steam_freebies.steam_network import SteamNetwork, validate_proxy_url, proxy_status
from steam_freebies.bili_auth import BiliAuth, is_official_scan_url
from steam_freebies.store import Store


def test_steam_proxy_validation(tmp_path):
    assert validate_proxy_url('http://192.168.1.100:7890')=='http://192.168.1.100:7890'
    assert validate_proxy_url('http://localhost:7890/') == 'http://localhost:7890'
    for bad in ['https://host:443','http://u:p@host:7890','http://host','file:///etc/passwd',
                'http://host:0','http://host:7890/a','http://host:7890?secret=x','http://host:7890#x']:
        with pytest.raises(ValueError): validate_proxy_url(bad)
    store=Store(tmp_path/'data.db')
    with pytest.raises(ValueError):store.update_settings({'steam_proxy_mode':'proxy'})
    with pytest.raises(ValueError):store.update_settings({'steam_proxy_url':'http://admin:secret@proxy:8888'})
    store.update_settings({'steam_proxy_mode':'proxy','steam_proxy_url':'http://proxy.local:7890'})
    assert SteamNetwork(store.settings()).options()=={'trust_env':False,'proxy':'http://proxy.local:7890'}
    assert proxy_status(store.settings())['configured']
    assert store.settings()['steam_search_fallback'] is False
    store.db.close()


def test_proxy_env_only_in_auto(monkeypatch):
    monkeypatch.setenv('HTTPS_PROXY','http://127.0.0.1:7777')
    assert SteamNetwork({'steam_proxy_mode':'auto'}).options()['trust_env']
    assert SteamNetwork({'steam_proxy_mode':'direct'}).options()['trust_env'] is False


def test_bili_official_login_url_allowlist_and_local_secrets(tmp_path):
    assert is_official_scan_url('https://passport.bilibili.com/h5-app/passport/login/scan?qrcode_key=test')
    assert not is_official_scan_url('https://passport.bilibili.com.evil.com/path')
    assert not is_official_scan_url('http://passport.bilibili.com/path')
    b=BiliAuth(tmp_path)
    assert b.status()['configured'] is False
    b.path.write_text(json.dumps({'SESSDATA':'secret','bili_jct':'csrf','EXTRA':'shouldnot','DedeUserID':'123'}))
    assert 'SESSDATA=secret' in b.cookie_header()
    assert 'EXTRA' not in b.cookie_header()
    public = b.status()
    assert public['configured'] and 'secret' not in str(public) and 'csrf' not in str(public)
    assert b.logout()['ok'] and b.cookie_header()==''


class FakeResponse:
    def __init__(self, payload, cookies=None):
        self.payload=payload
        self.cookies=SimpleCookie()
        for k,v in (cookies or {}).items():self.cookies[k]=v
    async def __aenter__(self): return self
    async def __aexit__(self,*args): pass
    def raise_for_status(self):pass
    async def json(self,content_type=None):return self.payload


class FakeSession:
    response = None
    def __init__(self,*a,**kw):pass
    async def __aenter__(self):return self
    async def __aexit__(self,*args):pass
    def get(self,*args,**kwargs):return type(self).response


def test_bili_qr_poll_never_returns_cookie_to_browser(tmp_path,monkeypatch):
    import steam_freebies.bili_auth as module
    b=BiliAuth(tmp_path)
    b._qr_key='a'*32
    b._qr_started=__import__('time').monotonic()
    FakeSession.response=FakeResponse({'code':0,'data':{'code':0,'url':'https://evil.invalid','refresh_token':'secret-refresh'}},
                                      {'SESSDATA':'sensitive-session','bili_jct':'sensitive-csrf','DedeUserID':'42'})
    monkeypatch.setattr(module.aiohttp,'ClientSession',FakeSession)
    result=asyncio.run(b.qr_poll())
    assert result['state']=='success'
    assert 'sensitive' not in str(result) and 'secret-refresh' not in str(result)
    assert 'sensitive-session' in b.cookie_header()
    assert 'sensitive' not in str(b.status())
    assert b.path.stat().st_mode & 0o077 == 0


def test_bili_qr_pending_not_saved(tmp_path,monkeypatch):
    import steam_freebies.bili_auth as module
    b=BiliAuth(tmp_path)
    b._qr_key='b'*32
    b._qr_started=__import__('time').monotonic()
    FakeSession.response=FakeResponse({'code':0,'data':{'code':86090}})
    monkeypatch.setattr(module.aiohttp,'ClientSession',FakeSession)
    assert asyncio.run(b.qr_poll())['state']=='scanned'
    assert not b.path.exists()
