"""Promotion sources, video filtering, no-token defaults and WBI signatures."""
import asyncio
import time
from unittest.mock import patch
import pytest
from steam_freebies.promotions import parse_itad_giveaways, parse_itad_deals
from steam_freebies.bilibili import extract_bvid, video_tip, wbi_signed, classify_with_ai, fetch_bilibili_tips
from steam_freebies.store import Store


def test_itad_steam_giveaway_no_gog():
    offers=[{'id':18,'shop':{'id':61,'name':'Steam'},'url':'https://example.com/giveaway',
        'games':[{'id':'abc','title':'Steam Title','type':'game'}], 'expiry':'2026-11-01'},
        {'id':19,'shop':{'id':35,'name':'GOG'},'url':'https://example.com/giveaway',
        'games':[{'id':'xyz','title':'GOG Title','type':'game'}]}]
    events=parse_itad_giveaways(offers)
    assert len(events)==1 and events[0]['kind']=='promo_api'
    assert 'Steam' in events[0]['source']


def test_itad_100pct_only_and_no_dlc():
    data={'list':[{'id':'abc','type':'game','title':'Game','deal':{'shop':{'id':61},
          'price':{'amountInt':0},'regular':{'amountInt':2000,'currency':'USD'},'cut':100,
          'url':'https://itad.link/abc/'}},
          {'id':'cde','type':'game','title':'Not free','deal':{'shop':{'id':61},
          'price':{'amountInt':500},'regular':{'amountInt':2000},'cut':75,'url':'https://itad.link/x/'}},
          {'id':'gg','type':'dlc','title':'DLC','deal':{'shop':{'id':61},
          'price':{'amountInt':0},'regular':{'amountInt':2000},'cut':100,'url':'https://itad.link/z/'}}]}
    assert len(parse_itad_deals(data))==1


def test_bv_parse_from_url():
    assert extract_bvid('https://www.bilibili.com/video/BV16mnt6iEiZ/?spm_id_from=123')=='BV16mnt6iEiZ'
    assert extract_bvid('https://evil.com/no-video')==''


def test_video_tip_strict_and_recent():
    recent=int(time.time())-3600
    item={'bvid':'BV16mnt6iEiZ','title':'Steam喜加一免费领取游戏','description':'商店 https://store.steampowered.com/app/42/',
          'pubdate':recent, 'mid':123}
    tip=video_tip(item)
    assert tip and tip['appid']==42
    assert video_tip({**item,'pubdate':recent-10*86400}) is None
    assert video_tip({**item,'title':'Steam 免费周末游戏'}) is None
    assert video_tip({**item,'title':'Steam 促销 8 折'}) is None


def test_wbi_sign_deterministic():
    img='https://i0.hdslb.com/bfs/wbi/' + 'a'*32 + '.png'
    sub='https://i0.hdslb.com/bfs/wbi/' + 'b'*32 + '.png'
    result=wbi_signed({'keyword':'Steam 限免','page':1},img,sub,now=1234567)
    assert len(result['w_rid'])==32 and result['wts']==1234567
    assert wbi_signed({'keyword':'Steam 限免','page':1},img,sub,now=1234567)==result
    with pytest.raises(ValueError):wbi_signed({},'','')


def test_no_bili_fetch_when_disabled(tmp_path):
    store=Store(tmp_path/'db')
    with patch('steam_freebies.bilibili.aiohttp.ClientSession',side_effect=AssertionError('no fetch expected')):
        assert asyncio.run(fetch_bilibili_tips(store))==([],[])
    store.db.close()


def test_ai_refuses_arbitrary_endpoint():
    from steam_freebies.bilibili import PROVIDERS
    assert all(u.startswith('https://') for u in PROVIDERS.values())
    with pytest.raises(ValueError): asyncio.run(classify_with_ai(None,{'name':'Hello','description':''},'arbitrary','key','model'))


def test_saved_ai_private_key_not_echoed(tmp_path):
    from steam_freebies.ai_config import AIConfig
    c=AIConfig(tmp_path)
    view=c.save({'provider':'deepseek','model':'deepseek-chat','api_key':'example-test-secret'})
    assert view['configured'] and view['provider']=='deepseek'
    assert 'example-test-secret' not in str(view)
    assert c.effective()['api_key']=='example-test-secret'
    assert 'example-test-secret' not in str(c.public())
    c.save({'clear_key':True})
    assert not c.get()['api_key']


def test_ai_private_settings_validate(tmp_path):
    from steam_freebies.ai_config import AIConfig
    c=AIConfig(tmp_path)
    for inp in [{'provider':'http://127.0.0.1'}, {'model':'m ; os.system()'}, {'api_key':'X'*1000}, {'clear_key':'yes'}]:
        with pytest.raises(ValueError):c.save(inp)


def test_price_watch_legacy_migration(tmp_path):
    db=Store(tmp_path/'db')
    db.add_price_watch(42)
    db.record_price_observations([{'appid':99,'name':'Old automatically found','state':'paid','amount':1000,'currency':'CNY'}])
    db.record_price_observations([{'appid':42,'name':'Manual','state':'paid','amount':1000,'currency':'CNY'}])
    db.db.close()
    db=Store(tmp_path/'db')
    assert db.price_watch_ids()==[42]
    assert db.db.execute('SELECT COUNT(*) FROM price_history WHERE appid=42').fetchone()[0]==1
    assert 'price_checks_per_scan' not in db.settings()
    db.db.close()
