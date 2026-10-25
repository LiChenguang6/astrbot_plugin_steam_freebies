"""v0.7.2: do not mistake F2P for temporary Free-to-Keep; dynamic diagnostics."""
import asyncio
import time
from unittest.mock import patch
import aiohttp

from steam_freebies.bili_verify import classify_store_details, permit_notification
from steam_freebies.store import Store
from steam_freebies.bilibili import fetch_bilibili_tips


def sample(key, *, state, origin='creator', appid=850170):
    return {
        'key': key, 'kind':'bilibili_tip', 'source':'Bilibili',
        'name':'Steam 限免专题', 'appid':appid,
        'url': f'https://store.steampowered.com/app/{appid}/',
        'steam_url': f'https://store.steampowered.com/app/{appid}/',
        'bili_source_url': 'https://www.bilibili.com/video/BV16mnt6iEiZ/',
        'bili_origin': origin, 'steam_state': state,
        'confidence': 'Steam 商店当前价格状态', 'original_price': '0',
    }


def test_plain_is_free_never_implies_giveaway():
    data = {'850170': {'success':True, 'data': {'type':'game','is_free':True}}}
    state,why = classify_store_details(data, 850170)
    assert state == 'free' and 'F2P' in why
    assert not permit_notification('creator',state)
    assert not permit_notification('search',state,corroborated=True)
    assert permit_notification('creator','sale_100')
    assert permit_notification('search','sale_100',corroborated=True)


def test_cached_f2p_never_pushed_or_autoclaimed(tmp_path):
    db=Store(tmp_path/'db')
    db.bind(platform_id='p',bot_id='b',group_id='1',session='s',official=False)
    db.update_settings({'push_enabled':True,'push_bilibili':True,'bili_push_creators':True,
                        'bili_enabled':True,'bili_unattended_claim':True})
    db.upsert_games([sample('f2p-850170',state='free'),sample('f2p-2818260',state='free',appid=2818260),
                     sample('sale',state='sale_100',appid=123456)])
    target=db.targets()[0]['id']
    assert [x['key'] for x in db.pending_pushes(target)]==['sale']
    assert [x['key'] for x in db.auto_claim_pending()]==['sale']
    assert [x['key'] for x in db.games()]==['sale']
    db.db.close()


class FakeResp:
    def __init__(self, data):self.data=data
    async def __aenter__(self):return self
    async def __aexit__(self,*args):pass
    def raise_for_status(self):pass
    async def json(self, content_type=None):return self.data


class FakeSession:
    def __init__(self,*args,**kwargs):pass
    async def __aenter__(self):return self
    async def __aexit__(self,*args):pass
    def get(self,url,params=None,**kwargs):
        if url.endswith('/feed/space'):
            # Raise a real aiohttp response error with only public HTTP status.
            raise aiohttp.ClientResponseError(None,(),status=412,message='Blocked',headers=None)
        if url.endswith('/nav'):
            return FakeResp({'code':0,'data':{'wbi_img':{'img_url':'https://i0.hdslb.com/bfs/wbi/'+'a'*32+'.png',
                                              'sub_url':'https://i0.hdslb.com/bfs/wbi/'+'b'*32+'.png'}}})
        if url.endswith('/arc/search'):
            return FakeResp({'code':0,'data':{'list':{'vlist':[{
                'bvid':'BV16mnt6iEiZ','title':'Steam 喜加一合集',
                'description':'Steam 限时免费 https://store.steampowered.com/app/850170/ '
                              'https://store.steampowered.com/app/2818260/ '
                              'https://store.steampowered.com/app/123456/',
                'created':int(time.time())-150,'mid':17213620}]}}})
        if url.endswith('/view'):
            return FakeResp({'code':0,'data':{'desc':''}})
        raise AssertionError(url)


def test_f2p_skipped_even_if_creator_video_has_multiple_links(tmp_path):
    db=Store(tmp_path/'db')
    db.add_bili_creator(17213620,'Test UP')
    async def verify(session,appid,network=None):
        return ('sale_100','100% 折扣') if appid==123456 else ('free','F2P 没有促销证据')
    notes=[]
    with patch('steam_freebies.bilibili.aiohttp.ClientSession',FakeSession),patch('steam_freebies.bilibili.verify_steam',verify):
        events,errors=asyncio.run(fetch_bilibili_tips(db,preview=True,creator_mid=17213620,report=notes))
    assert [x['appid'] for x in events]==[123456]
    assert any(x['kind']=='error' and 'HTTP 412' in x['detail'] for x in notes)
    assert any('HTTP 412' in x for x in errors)
    assert sum(x['kind']=='skipped' and 'F2P' in x['detail'] for x in notes)==2
    assert all(x['kind']!='eligible' or 'AppID 123456' in x['detail'] for x in notes)
    assert not db.bili_seen('BV16mnt6iEiZ')
    db.db.close()
