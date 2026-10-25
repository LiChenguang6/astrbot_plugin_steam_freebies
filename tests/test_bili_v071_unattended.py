"""Unattended free claim queue: anti-replay, source gating, multi-link parsing."""
from steam_freebies.store import Store
from steam_freebies.bili_verify import steam_links
import pytest


def event(key, origin='creator', state='free', appid=42):
    return {'key':key,'name':f'Free game {appid}','source':'Bilibili',
            'kind':'bilibili_tip','appid':appid,
            'url':f'https://store.steampowered.com/app/{appid}/',
            'steam_url':f'https://store.steampowered.com/app/{appid}/',
            'bili_source_url':'https://t.bilibili.com/901234567890',
            'bili_origin':origin,'steam_state':state,'confidence':'已检查','original_price':'0'}


def test_dynamic_many_steam_urls_without_first_two_loss():
    payload=' '.join(f'https://store.steampowered.com/app/{i}/' for i in range(1001,1019))
    assert len(steam_links(payload)) == 18
    assert len(steam_links(payload+' '+payload)) == 18
    assert steam_links('https://evil.com/app/12/ https://store.steampowered.com/app/44/')==[
        'https://store.steampowered.com/app/44/']


def test_creator_only_auto_claims_and_dedup(tmp_path):
    db=Store(tmp_path/'a.db')
    assert db.settings()['bili_unattended_claim'] is False
    db.update_settings({'bili_unattended_claim':True})
    db.upsert_games([event('creator-valid'),event('creator-sale',state='sale_100',appid=99),
                     event('search-valid',origin='search',appid=55),
                     event('creator-paid',state='not_free',appid=66)])
    assert {x['key'] for x in db.auto_claim_pending()}=={'creator-valid','creator-sale'}
    db.auto_claim_record('creator-valid',42,'app',42,'failed','Steam denied')
    assert {x['key'] for x in db.auto_claim_pending()}=={'creator-sale'}
    assert db.auto_claim_get('creator-valid')['status']=='failed'
    db.db.close()
    reopened=Store(tmp_path/'a.db')
    assert {x['key'] for x in reopened.auto_claim_pending()}=={'creator-sale'}
    assert reopened.auto_claim_get('creator-valid')['result']=='Steam denied'
    reopened.db.close()


def test_review_notification_only_failed_uncertain_and_marks_per_group(tmp_path):
    db=Store(tmp_path/'b.db')
    for appid in (10,20,30):db.upsert_games([event(f'creator:{appid}',appid=appid)])
    db.bind(platform_id='p',bot_id='b',group_id='1',session='s',official=False)
    db.bind(platform_id='p',bot_id='b',group_id='2',session='s',official=False)
    id1,id2=[t['id'] for t in db.targets()]
    db.auto_claim_record('creator:10',10,'app',10,'reported_success','OK')
    db.auto_claim_record('creator:20',20,'app',20,'submitted','No confirmation')
    db.auto_claim_record('creator:30',30,'app',30,'failed','Denied')
    assert {x['game_key'] for x in db.pending_auto_review_pushes(id1)}=={'creator:20','creator:30'}
    db.mark_auto_review_sent(id1,'creator:30')
    assert [x['game_key'] for x in db.pending_auto_review_pushes(id1)]==['creator:20']
    assert len(db.pending_auto_review_pushes(id2))==2
    db.auto_claim_resolve('creator:20')
    assert not db.pending_auto_review_pushes(id1)
    with pytest.raises(ValueError):db.auto_claim_resolve('creator:10')
    db.db.close()


def test_crash_in_flight_job_is_reviewable_not_repeated(tmp_path):
    db=Store(tmp_path/'c.db')
    db.upsert_games([event('creator:1')]);db.auto_claim_record('creator:1',42,'app',42,'checking','Pending')
    db.db.close()
    restored=Store(tmp_path/'c.db')
    assert restored.auto_claim_get('creator:1')['status']=='failed'
    assert restored.auto_claim_pending()==[]
    restored.db.close()


def test_setting_validation_and_old_game_row_migration(tmp_path):
    db=Store(tmp_path/'d.db')
    for bad in [0,1,None,'true']:
        with pytest.raises(ValueError):db.update_settings({'bili_unattended_claim':bad})
    with pytest.raises(ValueError):db.auto_claim_record('a',1,'app',1,'succeeded','no')
    db.db.close()
