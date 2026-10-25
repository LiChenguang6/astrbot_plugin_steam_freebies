import io
import json
import zipfile
from pathlib import Path
import pytest

from steam_freebies.asf import classify_result
from steam_freebies.manager import ManagedASF, archive_variant, verify_and_extract
from steam_freebies.store import Store


def game(key='steam:42', kind='steam_candidate'):
    return {'key': key,'name':'Sample Game','source':'Steam' if kind=='steam_candidate' else 'GamerPower',
            'kind':kind,'appid':42,'url':'https://store.steampowered.com/app/42/' if kind=='steam_candidate' else 'https://gamerpower.com/42',
            'original_price':'100','end_date':'','confidence':'待核验'}


def test_third_party_and_steam_push_enabled(tmp_path):
    store=Store(tmp_path/'db.sqlite3')
    store.bind(platform_id='p',bot_id='b',group_id='g',session='s',official=False)
    store.upsert_games([game(),game('gamerpower:42','third_party')])
    target=store.targets()[0]['id']
    assert {x['kind'] for x in store.pending_pushes(target)} == {'steam_candidate','third_party'}
    store.update_settings({'push_third_party':False})
    assert [x['kind'] for x in store.pending_pushes(target)]==['steam_candidate']
    store.update_settings({'push_steam':False,'push_third_party':True})
    assert [x['kind'] for x in store.pending_pushes(target)]==['third_party']
    store.db.close()


def test_claim_notification_queue(tmp_path):
    store=Store(tmp_path/'db.sqlite3')
    store.upsert_games([game()])
    store.bind(platform_id='p',bot_id='b',group_id='g1',session='s',official=False)
    store.bind(platform_id='p',bot_id='b',group_id='g2',session='s',official=False)
    e1=store.claim_record('steam:42',123,'failed','AccessDenied')
    e2=store.claim_record('steam:42',123,'reported_success','OK')
    a,b=[x['id'] for x in store.targets()]
    assert [x['id'] for x in store.pending_claim_events(a)]==[e1,e2]
    store.mark_claim_event(a,e1)
    assert [x['id'] for x in store.pending_claim_events(a)]==[e2]
    assert [x['id'] for x in store.pending_claim_events(b)]==[e1,e2]
    assert len(store.latest_claim_events())==2
    store.db.close()


def test_asf_response_classification():
    assert classify_result('AccessDenied. Failed')=='failed'
    assert classify_result('OK')=='reported_success'
    assert classify_result('Command accepted')=='submitted'
    assert classify_result('not successful')=='failed'  # never treat negation as success
    assert classify_result('token accepted')=='submitted'  # 'ok' substring must not produce false positive


def test_managed_install_security_and_settings(tmp_path):
    manager=ManagedASF(tmp_path/'managed')
    assert manager.settings()['mode']=='external'
    with pytest.raises(ValueError): manager.save_settings({'mode':'managed'})
    with pytest.raises(ValueError): manager.save_settings({'bot_name':'a; rm -rf /'})
    assert manager.save_settings({'bot_name':'MyBot','start_on_boot':True})['bot_name']=='MyBot'
    assert archive_variant('Linux','x86_64')=='ASF-linux-x64.zip'
    assert archive_variant('Windows','ARM64')=='ASF-win-arm64.zip'
    with pytest.raises(ValueError): archive_variant('Unknown','mips')
    mem=io.BytesIO()
    with zipfile.ZipFile(mem,'w') as z:z.writestr('../outside','evil')
    import hashlib
    with pytest.raises(ValueError): verify_and_extract(mem.getvalue(),hashlib.sha256(mem.getvalue()).hexdigest(),tmp_path/'unzipped')
    with pytest.raises(ValueError): verify_and_extract(b'untrusted','not-digest',tmp_path/'unzipped')


def test_bot_bootstrap_is_non_secret_and_does_not_overwrite(tmp_path):
    manager=ManagedASF(tmp_path/'managed')
    manager.path.mkdir()
    (manager.path/'ArchiSteamFarm').write_bytes(b'dummy')
    (manager.path/'config').mkdir()
    created=manager.prepare_bot('MyBot','steamlogin_123')
    cfg=json.loads((manager.path/'config'/'MyBot.json').read_text())
    assert created['bot_name']=='MyBot'
    assert cfg['Enabled'] is False
    assert cfg['FarmingPreferences']==1
    assert 'SteamPassword' not in cfg
    with pytest.raises(ValueError): manager.prepare_bot('MyBot','steamlogin_456')
    assert json.loads((manager.path/'config'/'MyBot.json').read_text())==cfg
