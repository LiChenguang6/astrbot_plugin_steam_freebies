"""ASF IPC 400 and enum integration security regressions."""
import asyncio
import json

import pytest

from steam_freebies.embedded_ui import EmbeddedUI, INPUT_TYPE_IDS, _safe_api_hint
from steam_freebies.manager import ManagedASF


def make_manager(tmp_path):
    manager = ManagedASF(tmp_path)
    manager.path.mkdir()
    manager.binary().write_bytes(b'fake')
    (manager.path / 'config').mkdir()
    (manager.path / 'config' / 'ASF.json').write_text(json.dumps({'IPCPassword': 'private-ipc-token'}))
    (manager.path / 'config' / 'MyBot.json').write_text(json.dumps({'Enabled': True, 'SteamLogin': 'private-steam-login'}))
    manager.save_settings({'mode': 'managed', 'bot_name': 'MyBot'})
    manager.process = type('Proc', (), {'returncode': None})()
    return manager


class FakeResponse:
    def __init__(self, status, payload):
        self.status = status
        self.content = type('Data', (), {'read': lambda self, n: self._read(n)})()
        async def _read(n):
            return json.dumps(payload).encode('utf-8')[:n]
        self.content._read = _read
    async def __aenter__(self): return self
    async def __aexit__(self, *_): pass


class FakeSession:
    def __init__(self, captures, status, payload, **kwargs):
        self.captures = captures
        self.status = status
        self.payload = payload
        captures['session_headers'] = kwargs.get('headers')
    async def __aenter__(self): return self
    async def __aexit__(self, *_): pass
    def request(self, method, url, *, json=None, allow_redirects=None):
        self.captures.update(method=method, url=url, body=json, redirects=allow_redirects)
        return FakeResponse(self.status, self.payload)


def test_enum_types_match_current_asf_source():
    assert INPUT_TYPE_IDS == {
        'Password': 2, 'SteamGuard': 3, 'SteamParentalCode': 4,
        'TwoFactorAuthentication': 5, 'DeviceConfirmation': 7,
    }


def test_account_input_sends_numeric_enum_not_strings(tmp_path, monkeypatch):
    mgr = make_manager(tmp_path)
    captures = {}
    monkeypatch.setattr('steam_freebies.embedded_ui.aiohttp.ClientSession',
                        lambda **kwargs: FakeSession(captures, 200, {'Success': True}, **kwargs))
    ui = EmbeddedUI(mgr)
    r = asyncio.run(ui.input_secret('SteamGuard', 'secret-guard-code'))
    assert r['ok'] and 'secret-guard-code' not in str(r)
    assert captures['body'] == {'Type': 3, 'Value': 'secret-guard-code'}
    assert captures['url'] == 'http://127.0.0.1:1242/Api/Bot/MyBot/Input'
    assert captures['session_headers'] == {'Authentication': 'private-ipc-token'}
    assert captures['redirects'] is False


def test_http400_shows_operation_without_leaking_password(tmp_path, monkeypatch):
    mgr = make_manager(tmp_path)
    captures = {}
    body = {'Success': False, 'Message': 'Type invalid; Password secret-password-xyz'}
    monkeypatch.setattr('steam_freebies.embedded_ui.aiohttp.ClientSession',
                        lambda **kwargs: FakeSession(captures, 400, body, **kwargs))
    with pytest.raises(ValueError, match='HTTP 400') as exc:
        asyncio.run(EmbeddedUI(mgr).input_secret('Password', 'secret-password-xyz'))
    assert 'input' in str(exc.value)
    assert 'secret-password-xyz' not in str(exc.value)
    assert 'private-ipc-token' not in str(exc.value)


def test_status_numeric_input_and_no_config_disclosure(tmp_path, monkeypatch):
    mgr = make_manager(tmp_path)
    captures={}
    raw = {'Success':True,'Result':{'MyBot':{'RequiredInput': 5, 'SteamID':'123',
           'IsConnectedAndLoggedOn':False, 'SteamPassword':'do-not-show'}}}
    monkeypatch.setattr('steam_freebies.embedded_ui.aiohttp.ClientSession',
                        lambda **kwargs: FakeSession(captures, 200, raw, **kwargs))
    info = asyncio.run(EmbeddedUI(mgr).status())
    assert info['loaded'] is True
    assert info['required_input'] == 'TwoFactorAuthentication'
    assert 'do-not-show' not in str(info)


def test_safe_hints_for_status_and_bot_not_found():
    assert '未加载' in _safe_api_hint(400,'start',{'Message':'Bot not found'})
    assert '配置' in _safe_api_hint(400,'enable',{})
    assert '验证' in _safe_api_hint(400,'input',{})
    assert 'IPCPassword' in _safe_api_hint(401,'input',{})


def test_invalid_device_confirmation_not_forwarded(tmp_path):
    ui=EmbeddedUI(make_manager(tmp_path))
    with pytest.raises(ValueError, match='Y'):
        asyncio.run(ui.input_secret('DeviceConfirmation','1234'))
