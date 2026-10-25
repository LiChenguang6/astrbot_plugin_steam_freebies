"""Regression tests for paying->free, cold-start false positives, ITAD corroboration."""
from datetime import datetime, timedelta, timezone

import pytest

from steam_freebies.price_monitor import (
    parse_appdetails, parse_search_ids, itad_paid_history, pick_appids,
)
from steam_freebies.store import Store


def observation(appid, state, amount=0, currency='CNY'):
    return dict(appid=appid,name=f'Game {appid}',state=state,amount=amount,
                currency=currency if state=='paid' else '', url=f'https://store.steampowered.com/app/{appid}/')


def test_steam_details_distinguishes_free_paid_and_100pct_sale():
    appid=850170
    assert parse_appdetails({str(appid):{'success':True,'data':{
        'type':'game','name':'EMERGENCY','is_free':True}}},appid)['state']=='free'
    assert parse_appdetails({str(appid):{'success':True,'data':{
        'type':'game','name':'EMERGENCY','is_free':False,
        'price_overview':{'final':990,'initial':1190,'currency':'CNY'}}}},appid)['amount']==990
    assert parse_appdetails({str(appid):{'success':True,'data':{
        'type':'game','name':'Weekend','is_free':False,
        'price_overview':{'final':0,'initial':1990,'currency':'CNY'}}}},appid) is None
    assert parse_appdetails({str(appid):{'success':True,'data':{
        'type':'dlc','name':'DLC','is_free':True}}},appid) is None
    assert parse_appdetails({'unknown':{}},appid) is None


def test_search_discovery_and_budget():
    html='''<a class="search_result_row" href="https://store.steampowered.com/app/123/A"></a>
    <a class="search_result_row" href="https://store.steampowered.com/app/123/B"></a>
    <a class="search_result_row" href="https://store.steampowered.com/app/456/C"></a>'''
    assert parse_search_ids(html)==[123,456]
    assert pick_appids([1,2],[3,4],[2,5],4)==[1,2,5,3]


def test_itad_only_positive_real_steam_prices():
    assert itad_paid_history([{'shop':{'name':'Steam'},'deal':{'price':{'amountInt':1999}}}])
    assert not itad_paid_history([{'shop':{'name':'GOG'},'deal':{'price':{'amountInt':1999}}}])
    assert not itad_paid_history([{'shop':{'name':'Steam'},'deal':{'price':{'amountInt':0}}}])
    assert not itad_paid_history({'unexpected':'object'})


def test_cold_start_does_not_report_paid_to_free(tmp_path):
    db=Store(tmp_path/'database.db')
    db.record_price_observations([observation(850170,'free')])
    assert not db.games()
    assert db.price_overview()['free']==1
    db.add_price_watch(123)
    assert db.price_overview()['total']==2
    db.record_price_observations([observation(123,'free')])
    assert not db.games()
    db.db.close()


def test_paid_to_free_creates_single_queued_notification(tmp_path):
    db=Store(tmp_path/'database.db')
    db.bind(platform_id='p',bot_id='b',group_id='g',session='s',official=False)
    assert db.record_price_observations([observation(42,'paid',1500)])==[]
    results=db.record_price_observations([observation(42,'free')])
    assert len(results)==1 and results[0]['kind']=='paid_to_free'
    target=db.targets()[0]['id']
    assert [e['kind'] for e in db.pending_pushes(target)]==['paid_to_free']
    db.marked(target,results[0]['key'])
    assert db.pending_pushes(target)==[]
    assert db.record_price_observations([observation(42,'free')])==[]
    with pytest.raises(ValueError): db.approve('price-free:42',1234)
    db.db.close()


def test_price_monitor_toggle_and_legacy_settings(tmp_path):
    db=Store(tmp_path/'database.db')
    assert db.settings()['price_monitor_enabled'] is True
    assert db.settings()['push_paid_to_free'] is True
    db.update_settings({'push_paid_to_free':False, 'price_checks_per_scan':12})
    db.record_price_observations([observation(42,'paid',1500)])
    db.record_price_observations([observation(42,'free')])
    db.bind(platform_id='p',bot_id='b',group_id='g',session='s',official=False)
    assert db.pending_pushes(db.targets()[0]['id'])==[]
    for value in [2, True, 1000]:
        with pytest.raises(ValueError): db.update_settings({'price_checks_per_scan':value})
    db.db.close()


def test_no_old_paid_to_free_transition(tmp_path):
    db=Store(tmp_path/'database.db')
    db.record_price_observations([observation(42,'paid',1500)])
    outdated=(datetime.now(timezone.utc)-timedelta(days=100)).isoformat(timespec='seconds')
    with db.db:
        db.db.execute('UPDATE price_watch SET last_paid_at=? WHERE appid=42',(outdated,))
    assert db.record_price_observations([observation(42,'free')])==[]
    db.db.close()


def test_watch_validation(tmp_path):
    db=Store(tmp_path/'database.db')
    for bad in [0,-1,True,'42',2_147_483_648]:
        with pytest.raises(ValueError): db.add_price_watch(bad)
    db.add_price_watch(850170)
    db.add_price_watch(850170)
    assert db.price_watch_ids()==[850170]
    db.db.close()
