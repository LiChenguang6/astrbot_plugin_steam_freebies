"""Native ASF-control security and behavior. No real Steam account or IPC required."""
import asyncio
import json
from pathlib import Path

import pytest

from steam_freebies.manager import ManagedASF
from steam_freebies.embedded_ui import EmbeddedUI, chosen_bot, local_bot_view


def manager(tmp_path):
    m = ManagedASF(tmp_path / 'asf')
    m.path.mkdir(exist_ok=True)
    (m.path / 'config').mkdir(exist_ok=True)
    m.binary().write_bytes(b'executable')
    m.save_settings({'mode': 'managed', 'bot_name': 'MyBot'})
    (m.path / 'config' / 'MyBot.json').write_text(
        json.dumps({'Enabled': False, 'SteamLogin': 'secret_login', 'SteamPassword': 'super_secret'}), encoding='utf-8')
    return m


def test_local_status_redacts_bot_credentials(tmp_path):
    m = manager(tmp_path)
    result = local_bot_view(m)
    assert result['bot_name'] == 'MyBot'
    assert result['steam_password_saved'] is True
    assert 'secret_login' not in str(result)
    assert 'super_secret' not in str(result)


def test_path_validation_and_current_bot_only(tmp_path):
    m = manager(tmp_path)
    assert chosen_bot(m, 'MyBot') == 'MyBot'
    with pytest.raises(ValueError): chosen_bot(m, 'OtherBot')
    m.save_settings({'mode':'external'})
    with pytest.raises(ValueError): chosen_bot(m)


def test_reject_invalid_auth_input_before_http(tmp_path):
    ui = EmbeddedUI(manager(tmp_path))
    for kind, value in [('Arbitrary','pw'),('Password',''),('Password','x'*129),('SteamGuard','abc\nxyz')]:
        with pytest.raises(ValueError): asyncio.run(ui.input_secret(kind,value))


def test_enable_uses_official_endpoint_without_returning_config(tmp_path,monkeypatch):
    m = manager(tmp_path)
    ui = EmbeddedUI(m)
    sent = {}
    async def fake_api(method,path,*,body=None,operation=None):
        sent.update(method=method,path=path,body=body)
        return {'Success':True, 'Result': {'SteamPassword': 'super_secret'}}
    monkeypatch.setattr(ui,'_api',fake_api)
    result = asyncio.run(ui.set_enabled(True))
    assert result['ok'] is True
    assert 'super_secret' not in str(result)
    assert sent['method']=='POST' and sent['path']=='/Api/Bot/MyBot'
    assert sent['body']['BotConfig']['Enabled'] is True
    with pytest.raises(ValueError): asyncio.run(ui.set_enabled('yes'))


def test_bot_control_only_start_stop(tmp_path,monkeypatch):
    ui=EmbeddedUI(manager(tmp_path))
    calls=[]
    async def fake_api(method,path,*,body=None,operation=None):
        calls.append((method,path))
        return {'Success':True}
    monkeypatch.setattr(ui,'_api',fake_api)
    asyncio.run(ui.control('Start'))
    asyncio.run(ui.control('Stop'))
    assert calls==[('POST','/Api/Bot/MyBot/Start'),('POST','/Api/Bot/MyBot/Stop')]
    with pytest.raises(ValueError): asyncio.run(ui.control('Delete'))


def test_transient_credential_input_never_echoed(tmp_path,monkeypatch):
    ui=EmbeddedUI(manager(tmp_path))
    sent=[]
    async def fake_api(method,path,*,body=None,operation=None):
        sent.append((method,path,body))
        return {'Success':True,'Result': {'SteamPassword': 'do_not_echo'}}
    monkeypatch.setattr(ui,'_api',fake_api)
    result=asyncio.run(ui.input_secret('Password','super_secret'))
    assert sent==[('POST','/Api/Bot/MyBot/Input',{'Type':2,'Value':'super_secret'})]
    assert 'super_secret' not in str(result) and 'do_not_echo' not in str(result)


def test_status_only_returns_allowlisted_fields(tmp_path,monkeypatch):
    m=manager(tmp_path)
    m.process=type('FakeProcess',(),{'returncode':None})()
    ui=EmbeddedUI(m)
    async def fake_api(method,path,*,body=None,operation=None):
        assert method == 'GET' and path == '/Api/Bot/MyBot'
        return {'Success':True,'Result':{'MyBot':{'IsConnectedAndLoggedOn':True,
             'RequiredInput':'SteamGuard','SteamID':'1234','SteamPassword':'raw-secret',
             'BotConfig':{'SteamPassword':'raw-secret'}}}}
    monkeypatch.setattr(ui,'_api',fake_api)
    result=asyncio.run(ui.status())
    assert result['connected'] and result['required_input']=='SteamGuard'
    assert 'raw-secret' not in str(result) and 'BotConfig' not in str(result)
