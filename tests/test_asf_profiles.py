"""ASF selectable runtime profile and on-demand low-memory NAS policy."""
import asyncio
import json
from pathlib import Path

import pytest

from steam_freebies.manager import ManagedASF


def installed(tmp_path):
    manager=ManagedASF(tmp_path/'asf')
    manager.path.mkdir()
    manager.binary().write_bytes(b'fake binary')
    config=manager.path/'config'
    config.mkdir()
    (config/'ASF.json').write_text(json.dumps({'IPC':True,'IPCPassword':'local_test_secret','OptimizationMode':1,'Headless':True}))
    return manager


def test_profile_choices_validate_and_persist(tmp_path):
    manager=installed(tmp_path)
    assert manager.settings()['profile']=='compatible'
    assert manager.settings()['on_demand'] is True
    assert manager.settings()['idle_minutes']==10
    new=manager.save_settings({'mode':'managed','profile':'performance','on_demand':False,'idle_minutes':15})
    assert new['profile']=='performance' and new['idle_minutes']==15
    assert ManagedASF(manager.root).settings()['profile']=='performance'
    for invalid in ({'profile':'ultra'},{'on_demand':1},{'idle_minutes':0},{'idle_minutes':60},{'idle_minutes':10.0}):
        with pytest.raises(ValueError): manager.save_settings(invalid)


def test_optimization_keeps_local_ipc_secret(tmp_path):
    manager=installed(tmp_path)
    f=manager.path/'config'/'ASF.json'
    manager._configure_optimization('performance')
    assert json.loads(f.read_text())=={'IPC':True,'IPCPassword':'local_test_secret','OptimizationMode':0,'Headless':True}
    manager._configure_optimization('compatible')
    assert json.loads(f.read_text())['OptimizationMode']==1
    assert json.loads(f.read_text())['IPCPassword']=='local_test_secret'
    f.write_text('{corrupt')
    with pytest.raises(ValueError,match='未覆盖'):manager._configure_optimization('performance')
    assert f.read_text()=='{corrupt'


def test_child_env_only_and_mode_does_not_modify_global_environment(tmp_path, monkeypatch):
    manager=installed(tmp_path)
    monkeypatch.setenv('DOTNET_SYSTEM_GLOBALIZATION_INVARIANT','original')
    env=manager._runtime_environment('compatible')
    assert env['DOTNET_SYSTEM_GLOBALIZATION_INVARIANT']=='1'
    assert env['DOTNET_SYSTEM_GLOBALIZATION_PREDEFINED_CULTURES_ONLY']=='0'
    assert manager._runtime_environment('performance')['DOTNET_SYSTEM_GLOBALIZATION_INVARIANT']=='0'
    assert 'DOTNET_SYSTEM_GLOBALIZATION_PREDEFINED_CULTURES_ONLY' not in manager._runtime_environment('performance')
    import os
    assert os.environ['DOTNET_SYSTEM_GLOBALIZATION_INVARIANT']=='original'


def test_actual_start_passes_selected_env_and_profile(tmp_path, monkeypatch):
    manager=installed(tmp_path)
    manager.save_settings({'mode':'managed','profile':'compatible'})
    observed={}
    class Proc:
        returncode=None
        pid=0
    async def spawn(*args,**kwargs):
        observed['env']=kwargs['env']
        observed['args']=args
        return Proc()
    async def no_sleep(_): pass
    monkeypatch.setattr('steam_freebies.manager.asyncio.create_subprocess_exec',spawn)
    monkeypatch.setattr('steam_freebies.manager.asyncio.sleep',no_sleep)
    asyncio.run(manager.start())
    assert observed['env']['DOTNET_SYSTEM_GLOBALIZATION_INVARIANT']=='1'
    assert '--process-required' in observed['args']
    assert manager.status()['running_profile']=='compatible'
    manager.log_handle.close()


def test_on_demand_starts_only_when_managed_and_stops_at_idle(tmp_path, monkeypatch):
    manager=installed(tmp_path)
    manager.save_settings({'mode':'managed','on_demand':True,'idle_minutes':5})
    events=[]
    class FakeProc:
        returncode=None
        pid=0
    async def fake_start():
        events.append('start')
        manager.process=FakeProc()
    async def fake_stop():
        events.append('stop')
        manager.process=None
    async def immediate_sleep(_):pass
    monkeypatch.setattr(manager,'start',fake_start)
    monkeypatch.setattr(manager,'stop',fake_stop)
    monkeypatch.setattr('steam_freebies.manager.asyncio.sleep',immediate_sleep)
    async def run():
        assert await manager.prepare_for_claim() is True
        assert events==['start']
        assert manager._active_claims==1
        manager.finish_claim()
        await manager._idle_task
        assert events==['start','stop']
    asyncio.run(run())


def test_on_demand_does_not_touch_external_asf(tmp_path):
    manager=installed(tmp_path)
    async def run():
        assert await manager.prepare_for_claim() is False
        assert manager.process is None
    asyncio.run(run())


def test_low_memory_profile_needs_no_root_or_libicu_install(tmp_path):
    manager=installed(tmp_path)
    # Explicit non-invasive compatibility setting, no package manager or system-wide change.
    env=manager._runtime_environment('compatible')
    assert env['DOTNET_SYSTEM_GLOBALIZATION_INVARIANT']=='1'
    assert (manager.root/'runtime'/'config'/'ASF.json').is_file()
