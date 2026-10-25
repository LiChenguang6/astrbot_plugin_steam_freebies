"""v0.7.0 Bili UP videos+dynamics and high-integrity QQ/ASF routing."""
import asyncio
import time
from unittest.mock import patch
import pytest

from steam_freebies.bilibili import dynamic_tip, video_tip, fetch_bilibili_tips
from steam_freebies.bili_verify import steam_links, linked_subids, classify_store_details, permit_notification
from steam_freebies.store import Store

RECENT=int(time.time())-1200

def video(bv='BV16mnt6iEiZ',desc='Steam 限时免费 https://store.steampowered.com/app/42/'):
    return {'bvid':bv,'title':'Steam喜加一 免费领取','description':desc,'pubdate':RECENT,'mid':321}

def dynamic(did='123456789012345678',text='Steam喜加一 https://store.steampowered.com/app/42/'):
    return {'id_str':did,'modules':{'module_author':{'mid':321,'pub_ts':RECENT},
       'module_dynamic':{'desc':{'text':text,'rich_text_nodes':[{'orig_text':text}]},
                         'major':{'archive':{'bvid':'BV16mnt6iEiZ','title':'Steam 喜加一'}}}}}

def test_extract_only_official_links_no_unsafe_redirect():
    assert steam_links('免费 https://store.steampowered.com/app/42/?x=1 + https://store.steampowered.com/app/42/') == [
        'https://store.steampowered.com/app/42/']
    assert steam_links('https://store.steampowered.com.evil.com/app/42/') == []
    assert steam_links('https://evil.invalid/?redirect=https%3A%2F%2Fstore.steampowered.com%2Fapp%2F42') == []
    assert linked_subids('https://store.steampowered.com/sub/54321') == [54321]
    assert linked_subids('https://evil.example/sub/54321') == []


def test_video_dynamic_normalization():
    assert video_tip(video())['url'].endswith('BV16mnt6iEiZ/')
    tip=dynamic_tip(dynamic())
    assert tip['type']=='dynamic' and tip['url']=='https://t.bilibili.com/123456789012345678'
    assert tip['appid']==42 and tip['bvid']=='BV16mnt6iEiZ'
    assert dynamic_tip(dynamic(text='Steam 免费周末试玩 https://store.steampowered.com/app/42/')) is None
    assert dynamic_tip(dynamic(did='invalid')) is None


def test_steam_free_check_strict_and_no_license_proof():
    details=lambda x: {'42':{'success':True,'data':x}}
    assert classify_store_details(details({'type':'game','is_free':False,'price_overview':{'initial':1000,'final':0,'discount_percent':100}}),42)[0]=='sale_100'
    assert classify_store_details(details({'type':'game','is_free':True}),42)[0]=='free'
    assert classify_store_details(details({'type':'game','is_free':False,'price_overview':{'initial':1000,'final':0,'discount_percent':0}}),42)[0]=='not_free'
    assert classify_store_details(details({'type':'dlc','is_free':True}),42)[0]=='unknown'
    assert permit_notification('creator','free')
    assert permit_notification('creator','sale_100')
    assert not permit_notification('creator','not_free')
    assert not permit_notification('search','free',corroborated=True)
    assert not permit_notification('search','sale_100',corroborated=False)
    assert permit_notification('search','sale_100',corroborated=True)
    assert not permit_notification('search','sale_100',corroborated=True,blocked=True)


def test_v066_migration_store_push_source_gates_and_both_links(tmp_path):
    db=Store(tmp_path/'sqlite.db')
    db.bind(platform_id='p',bot_id='b',group_id='1',session='x',official=False)
    db.update_settings({'bili_enabled':True,'push_bilibili':True,'bili_discovery_mode':'both'})
    base={'name':'Steam 喜加一','source':'Bilibili','kind':'bilibili_tip','appid':42,
          'url':'https://store.steampowered.com/app/42/','steam_url':'https://store.steampowered.com/app/42/',
          'bili_source_url':'https://t.bilibili.com/123456789','confidence':'核验','original_price':'免费'}
    db.upsert_games([{**base,'key':'bili:creator:1','bili_origin':'creator'},
                    {**base,'key':'bili:search:2','bili_origin':'search'},
                    {**base,'key':'bili:old:3','bili_origin':''}])
    target=db.targets()[0]['id']
    assert [x['key'] for x in db.pending_pushes(target)]==['bili:creator:1']
    db.update_settings({'bili_push_search_verified':True})
    assert {x['key'] for x in db.pending_pushes(target)}=={'bili:creator:1','bili:search:2'}
    db.update_settings({'bili_push_creators':False})
    assert [x['key'] for x in db.pending_pushes(target)]==['bili:search:2']
    db.db.close()
    db=Store(tmp_path/'sqlite.db')
    assert db.get_game('bili:creator:1')['bili_source_url'].startswith('https://t.bilibili.com/')
    db.db.close()


def test_only_approved_creator_bili_may_claim(tmp_path):
    db=Store(tmp_path/'db')
    def item(origin,key):return dict(key=key,name='n',source='Bili',kind='bilibili_tip',appid=42,
          url='https://store.steampowered.com/app/42/',steam_url='https://store.steampowered.com/app/42/',
          bili_source_url='https://www.bilibili.com/video/BV16mnt6iEiZ/',bili_origin=origin)
    db.upsert_games([item('creator','bili:up:1'),item('search','bili:search:1')])
    with pytest.raises(ValueError):db.approve('bili:search:1',321)
    db.approve('bili:up:1',321)
    assert len(db.pending_bili_claims())==1
    db.claim_record('bili:up:1',321,'reported_success','ASF says added')
    assert not db.pending_bili_claims()
    db.approve('bili:up:1',444)
    assert len(db.pending_bili_claims())==1
    db.db.close()


def test_config_validation(tmp_path):
    db=Store(tmp_path/'db')
    assert db.settings()['bili_discovery_mode']=='creators'
    assert not db.settings()['bili_auto_claim_creators']
    assert not db.settings()['bili_push_search_verified']
    for x in ('all','anything',''):
        with pytest.raises(ValueError):db.update_settings({'bili_discovery_mode':x})
    with pytest.raises(ValueError):db.update_settings({'bili_auto_claim_creators':'yes'})
    db.db.close()


class Response:
    def __init__(self,data):self.data=data
    async def __aenter__(self):return self
    async def __aexit__(self,*args):pass
    def raise_for_status(self):pass
    async def json(self,content_type=None):return self.data
class Session:
    endpoints={}
    def __init__(self,*args,**kwargs):pass
    async def __aenter__(self):return self
    async def __aexit__(self,*args):pass
    def get(self,url,params=None,**kwargs):
        path=url.split('api.bilibili.com')[-1]
        if path=='/x/web-interface/view':
            return Response({'code':0,'data':{'desc':'Steam 100%折扣 https://store.steampowered.com/app/42/'}})
        if path.endswith('/nav'):
            return Response({'code':0,'data':{'wbi_img':{'img_url':'https://i0.hdslb.com/bfs/wbi/'+'a'*32+'.png','sub_url':'https://i0.hdslb.com/bfs/wbi/'+'b'*32+'.png'}}})
        if path.endswith('/feed/space'):
            return Response({'code':0,'data':{'items':[dynamic()]}})
        if path.endswith('/arc/search'):
            return Response({'code':0,'data':{'list':{'vlist':[video()]}}})
        if path.endswith('/search/type'):
            return Response({'code':0,'data':{'result':[video()]}})
        raise RuntimeError('unexpected endpoint '+url)


def test_bili_preview_does_not_mark_seen_or_push_and_has_source(tmp_path):
    db=Store(tmp_path/'db');db.add_bili_creator(321,'test')
    notes=[]
    async def fake_verify(*args,**kwargs):return 'sale_100','Steam 100%'
    with patch('steam_freebies.bilibili.aiohttp.ClientSession',Session),patch('steam_freebies.bilibili.verify_steam',fake_verify):
        events,errors=asyncio.run(fetch_bilibili_tips(db,preview=True,creator_mid=321,report=notes))
    assert not errors and events
    assert all(e['bili_origin']=='creator' and e['steam_url'].endswith('/42/') for e in events)
    assert not db.bili_seen('dynamic:123456789012345678')
    assert db.games()==[]
    assert any(n.get('kind')=='eligible' for n in notes)
    db.db.close()


def test_bili_search_does_not_push_without_api_corroboration(tmp_path):
    db=Store(tmp_path/'db');db.update_settings({'bili_enabled':True,'bili_discovery_mode':'search'})
    async def fake_verify(*args,**kwargs):return 'sale_100','Steam 100%'
    with patch('steam_freebies.bilibili.aiohttp.ClientSession',Session),patch('steam_freebies.bilibili.verify_steam',fake_verify):
        none,errors=asyncio.run(fetch_bilibili_tips(db,corroborated_appids=set()))
        found,_=asyncio.run(fetch_bilibili_tips(db,corroborated_appids={42}))
    assert not errors and none==[]
    assert len(found)==1 and found[0]['bili_origin']=='search'
    db.db.close()
