"""v0.6: only user-selected games, no automatic random sampling."""
from datetime import datetime, timedelta, timezone
import pytest
from steam_freebies.price_monitor import parse_appdetails, itad_paid_history
from steam_freebies.store import Store


def sample(appid,state,amount=0,currency='CNY'):
    return {'appid':appid,'name':f'Game {appid}','state':state,'amount':amount,
            'currency':currency if state=='paid' else '', 'url':f'https://store.steampowered.com/app/{appid}/'}


def test_steam_free_paid_sale_unknown():
    appid=850170
    assert parse_appdetails({str(appid):{'success':True,'data':{'type':'game','name':'EMERGENCY','is_free':True}}},appid)['state']=='free'
    assert parse_appdetails({str(appid):{'success':True,'data':{'type':'game','name':'Paid','is_free':False,'price_overview':{'final':1000,'currency':'CNY'}}}},appid)['amount']==1000
    assert parse_appdetails({str(appid):{'success':True,'data':{'type':'game','name':'Promo','is_free':False,'price_overview':{'final':0,'initial':5000}}}},appid) is None
    assert parse_appdetails({str(appid):{'success':True,'data':{'type':'dlc','name':'DLC','is_free':True}}},appid) is None


def test_itad_history_only_steam():
    assert itad_paid_history([{'shop':{'id':61,'name':'Steam'},'deal':{'price':{'amountInt':1000}}}])
    assert not itad_paid_history([{'shop':{'id':35,'name':'GOG'},'deal':{'price':{'amountInt':1000}}}])
    assert not itad_paid_history([{'shop':{'name':'Steam'},'deal':{'price':{'amountInt':0}}}])


def test_only_manual_ids_checked(tmp_path):
    db=Store(tmp_path/'db.sqlite')
    db.add_price_watch(42)
    db.record_price_observations([sample(99,'paid',1200),sample(42,'paid',3500)])
    assert db.price_watch_ids(manual_only=True)==[42]
    db.remove_price_watch(42)
    assert db.price_watch_ids(manual_only=True)==[]
    db.db.close()


def test_cold_start_no_alert(tmp_path):
    db=Store(tmp_path/'db.sqlite')
    db.add_price_watch(42)
    assert db.record_price_observations([sample(42,'free')])==[]
    db.db.close()


def test_favorite_price_change_generates_notice(tmp_path):
    db=Store(tmp_path/'db.sqlite')
    db.add_price_watch(42)
    db.bind(platform_id='p',bot_id='b',group_id='g',session='s',official=False)
    assert db.record_price_observations([sample(42,'paid',2000)])==[]
    events=db.record_price_observations([sample(42,'paid',1500)])
    assert len(events)==1 and events[0]['kind']=='watch_price'
    assert '20.00' in events[0]['original_price'] and '15.00' in events[0]['original_price']
    assert any(x['kind']=='watch_price' for x in db.pending_pushes(db.targets()[0]['id']))
    db.update_settings({'push_watch_prices':False})
    assert not db.pending_pushes(db.targets()[0]['id'])
    db.db.close()


def test_paid_to_free_only_manual(tmp_path):
    db=Store(tmp_path/'db.sqlite')
    db.record_price_observations([sample(777,'paid',1200)])
    assert not db.record_price_observations([sample(777,'free')])
    db.add_price_watch(42)
    db.record_price_observations([sample(42,'paid',1200)])
    events=db.record_price_observations([sample(42,'free')])
    assert len(events)==1 and events[0]['kind']=='paid_to_free'
    assert not db.record_price_observations([sample(42,'free')])
    db.db.close()


def test_invalid_watch_add(tmp_path):
    db=Store(tmp_path/'db.sqlite')
    for bad in [0,-1,True,'1',2**31]:
        with pytest.raises(ValueError): db.add_price_watch(bad)
    for bad in ['1', True, 0]:
        with pytest.raises(ValueError):db.remove_price_watch(bad)
    db.db.close()


def test_bili_settings_and_author_state(tmp_path):
    db=Store(tmp_path/'db.sqlite')
    assert not db.settings()['bili_enabled']
    assert not db.settings()['bili_ai_enabled']
    for payload in [{'bili_ai_calls':100},{'bili_ai_calls':True},{'bili_keywords':'X'*200}, {'bili_keywords':''}]:
        with pytest.raises(ValueError):db.update_settings(payload)
    db.update_settings({'bili_enabled':True,'push_bilibili':True,'bili_keywords':'Steam 喜加一,Steam 限免', 'bili_ai_calls':0})
    db.add_bili_creator(123456,'UP')
    assert db.bili_creators()[0]['mid']==123456
    db.mark_bili_seen('BV16mnt6iEiZ')
    assert db.bili_seen('BV16mnt6iEiZ')
    db.remove_bili_creator(123456)
    assert db.bili_creators()==[]
    db.db.close()
