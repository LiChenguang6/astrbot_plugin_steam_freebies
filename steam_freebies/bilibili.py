"""Bilibili discovery: subscribed creators (videos + dynamics) and strictly filtered search.

No scraping of logged-in pages, no CAPTCHA bypass, no automatic SubID guessing.
Only qualified Steam links become QQ push candidates. Preview never marks content seen.
"""
import asyncio
import hashlib
import html
import os
import re
import time
from urllib.parse import urlencode, urlparse

import aiohttp
from .bili_verify import steam_links, linked_subids, verify_steam, permit_notification, STRONG_FALSE

API = 'https://api.bilibili.com'
BV = re.compile(r'BV[0-9a-zA-Z]{10}')
FREE_WORDS = ('喜加一', '限免', '免费领', '免费送', '免费入库', '永久免费', '免费游戏', '0元入库', '零元入库', '100%折扣', '100% 折扣')
NEGATIVE = STRONG_FALSE
MIXIN = (46,47,18,2,53,8,23,32,15,50,10,31,58,3,45,35,27,43,5,49,33,9,42,19,29,28,14,39,12,38,41,13,37,48,7,16,24,55,40,61,26,17,0,1,60,51,30,4,22,25,54,21,56,59,6,63,57,62,11,36,20,34,44,52)
PROVIDERS = {'openai':'https://api.openai.com/v1/chat/completions','deepseek':'https://api.deepseek.com/chat/completions',
             'siliconflow':'https://api.siliconflow.cn/v1/chat/completions',
             'dashscope':'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions'}


def extract_bvid(value):
    if not isinstance(value,str): return ''
    m=BV.search(value[:350])
    return m.group() if m else ''


def video_tip(item, *, require_words=True):
    if not isinstance(item,dict): return None
    bvid=extract_bvid(str(item.get('bvid') or item.get('arcurl') or ''))
    name=html.unescape(re.sub(r'<[^>]+>','',str(item.get('title') or ''))).strip()[:180]
    desc=html.unescape(str(item.get('description') or item.get('desc') or ''))[:2000]
    if not bvid or not name:return None
    text=name+' '+desc
    if (require_words and not any(w in text for w in FREE_WORDS)) or any(w in text for w in NEGATIVE): return None
    owner=item.get('owner') or {}
    uid=owner.get('mid') if isinstance(owner,dict) else item.get('mid')
    published=item.get('pubdate') or item.get('created') or 0
    if type(published) is not int or published<=0 or time.time()-published>7*86400 or published>time.time()+3600:return None
    urls=steam_links(text)
    return {'ref':bvid,'bvid':bvid,'mid':int(uid) if str(uid).isdigit() else 0,'name':name,'description':desc,
            'appid':int(urls[0].split('/app/')[1].split('/')[0]) if urls else 0,
            'pubdate':published,'url':f'https://www.bilibili.com/video/{bvid}/','type':'video', 'text':text}


def dynamic_tip(item):
    """Normalize text, repost/video cards and rich-link nodes from creator feed."""
    if not isinstance(item,dict):return None
    mid=int((item.get('modules') or {}).get('module_author',{}).get('mid') or 0)
    did=str(item.get('id_str') or '')
    if not did.isdigit() or len(did)>25:return None
    modules=item.get('modules') or {}
    author=modules.get('module_author') or {}
    pub=author.get('pub_ts') or 0
    if type(pub) is not int or pub<=0 or time.time()-pub>7*86400 or pub>time.time()+3600:return None
    dynamic=modules.get('module_dynamic') or {}
    desc=dynamic.get('desc') or {}
    major=dynamic.get('major') or {}
    archive=major.get('archive') or {}
    opus=major.get('opus') or {}
    if not isinstance(desc,dict):desc={}
    if not isinstance(archive,dict):archive={}
    if not isinstance(opus,dict):opus={}
    texts=[str(desc.get('text') or ''),str(archive.get('title') or ''),str(archive.get('desc') or '')]
    for node in (desc.get('rich_text_nodes') or [])[:35]:
        if isinstance(node,dict):texts.extend([str(node.get('orig_text') or ''),str(node.get('jump_url') or '')])
    for paragraph in (opus.get('summary') or {}).get('rich_text_nodes',[])[:35]:
        if isinstance(paragraph,dict):texts.extend([str(paragraph.get('text') or ''),str(paragraph.get('jump_url') or '')])
    # Forward dynamics can contain quoted original posts, but only preserve the subscribed author's source.
    combined=html.unescape(' '.join(texts))[:7000]
    if not any(w in combined for w in FREE_WORDS) or any(w in combined for w in NEGATIVE):return None
    bvid=extract_bvid(str(archive.get('bvid') or ''))
    title=str(archive.get('title') or desc.get('text') or 'B站动态').strip()[:180]
    url=f'https://t.bilibili.com/{did}'
    links=steam_links(combined)
    return {'ref':'dynamic:'+did,'bvid':bvid,'mid':mid,'name':title,'description':combined[:2200],
            'appid':int(links[0].split('/app/')[1].split('/')[0]) if links else 0,
            'pubdate':pub,'url':url,'type':'dynamic','text':combined}


def wbi_signed(params,image_url,sub_url,now=None):
    parts=[urlparse(x).path.rsplit('/',1)[-1].split('.')[0] for x in (image_url,sub_url)]
    key=''.join(parts)
    if len(key)<64:raise ValueError('B站 WBI 签名密钥不可用')
    mixin=''.join(key[i] for i in MIXIN)[:32]
    values={k:''.join(ch for ch in str(v) if ch not in "!'()*") for k,v in params.items()}
    values['wts']=int(time.time() if now is None else now)
    values['w_rid']=hashlib.md5((urlencode(sorted(values.items()))+mixin).encode()).hexdigest()
    return values


async def _bili_json(session,path,params):
    async with session.get(API+path,params=params,timeout=aiohttp.ClientTimeout(total=12)) as resp:
        resp.raise_for_status();payload=await resp.json(content_type=None)
    if not isinstance(payload,dict):raise ValueError('B站返回格式无效')
    if payload.get('code')!=0:
        code=payload.get('code')
        raise ValueError(f'B站请求受限 code={code}（登录/限流/接口变更），不尝试绕过')
    return payload.get('data') or {}


async def resolve_video_owner(bvid,auth=None):
    if not BV.fullmatch(bvid):raise ValueError('请填写有效的 BV 号或视频链接')
    headers=auth.headers() if auth else {'User-Agent':'Mozilla/5.0','Referer':'https://www.bilibili.com/'}
    async with aiohttp.ClientSession(headers=headers) as session:
        data=await _bili_json(session,'/x/web-interface/view',{'bvid':bvid})
    owner=data.get('owner') or {};mid=owner.get('mid')
    if type(mid) is not int or not 0<mid<10**15:raise ValueError('B站没有返回有效 UP UID')
    return mid, str(owner.get('name') or f'UP {mid}')[:80]


async def _wbi_keys(session):
    data=await _bili_json(session,'/x/web-interface/nav',{})
    image=data.get('wbi_img') or {}
    return str(image.get('img_url') or ''),str(image.get('sub_url') or '')


def _parse_search(data):
    return data.get('result') if isinstance(data.get('result'),list) else []


def _parse_space(data):
    listing=data.get('list') if isinstance(data,dict) else None
    return listing.get('vlist') if isinstance(listing,dict) and isinstance(listing.get('vlist'),list) else []


async def classify_with_ai(session,video,provider,key,model):
    url=PROVIDERS.get(provider)
    if not url or not key or not re.fullmatch(r'[\w./:-]{1,100}',model):raise ValueError('AI 配置无效')
    prompt=('判断此B站内容是否报道当前真正免费领取的Steam游戏。非试玩、抽奖、纯F2P推荐。只答JSON：'
            '{"result":"yes|no|uncertain"}，不确定使用uncertain。'
            f'标题：{video["name"][:150]}\n文字：{video["description"][:600]}')
    body={'model':model,'temperature':0,'max_tokens':120,'messages':[{'role':'user','content':prompt}]}
    async with session.post(url,headers={'Authorization':f'Bearer {key}'},json=body,
                             timeout=aiohttp.ClientTimeout(total=14)) as resp:
        resp.raise_for_status();response=await resp.json(content_type=None)
    content=response['choices'][0]['message']['content']
    match=re.search(r'\b(yes|no|uncertain)\b',content[:300]) if isinstance(content,str) else None
    return match.group(1) if match else 'uncertain'


async def fetch_bilibili_tips(store,ai_config=None,auth=None,network=None,corroborated_appids=None,preview=False,creator_mid=None,report=None):
    """Scan selected channels. Preview is read-only: no seen writes, no QQ, no ASF.

    `corroborated_appids` contains AppIDs reported by an *independent Steam promotion API*,
    never raw Bilibili claims. Search needs cross-source corroboration AND Steam 100% sale.
    """
    settings=store.settings()
    if not settings['bili_enabled'] and not preview:return [],[]
    if report is None:report=[]
    errors=[];raw=[]
    mode='creators' if preview else settings['bili_discovery_mode']
    headers=auth.headers() if auth else {'User-Agent':'Mozilla/5.0 SteamFreebiesAstrBot/0.7','Referer':'https://www.bilibili.com/'}
    async with aiohttp.ClientSession(headers=headers,timeout=aiohttp.ClientTimeout(total=15)) as session:
        image=sub=''
        # Public creator dynamics don't need WBI; only videos and search use nav signature.
        if mode in ('creators','both'):
            creators=store.bili_creators()
            if creator_mid is not None:
                creators=[x for x in creators if x['mid']==creator_mid]
            if creator_mid is None and len(creators)>3:
                start=int(time.time()//3600)%len(creators)
                creators=(creators[start:]+creators[:start])[:3]
            else:
                creators=creators[:3]
            for creator in creators:
                mid=creator['mid']
                try:
                    data=await _bili_json(session,'/x/polymer/web-dynamic/v1/feed/space',
                        {'host_mid':mid,'timezone_offset':-480,'platform':'web'})
                    for dynamic in (data.get('items') or [])[:4]:
                        tip=dynamic_tip(dynamic)
                        if tip:
                            tip['mid']=mid
                            raw.append((tip,'creator'))
                    report.append({'kind':'source','name':f'UP {mid} 动态','detail':'读取成功（仅表示接口可用，未保证发现活动）'})
                except aiohttp.ClientResponseError as exc:
                    message=f'UP {mid} 动态：HTTP {exc.status}（B站返回拒绝或异常响应；视频仍会独立检查）'
                    errors.append(message)
                    report.append({'kind':'error','name':f'UP {mid} 动态','detail':message})
                except (aiohttp.ClientError,TimeoutError,ValueError,TypeError) as exc:
                    # ValueError contains only a numeric B站 API code from _bili_json.
                    reason=str(exc)[:100] if isinstance(exc,ValueError) else type(exc).__name__
                    message=f'UP {mid} 动态：{reason}（视频仍会独立检查）'
                    errors.append(message)
                    report.append({'kind':'error','name':f'UP {mid} 动态','detail':message})
                await asyncio.sleep(.25)
            if creators or mode=='both':
                try:image,sub=await _wbi_keys(session)
                except (aiohttp.ClientError,TimeoutError,ValueError,TypeError):
                    errors.append('B站视频 WBI 初始化失败，动态接口不受影响')
                if image and sub:
                    for creator in creators:
                        try:
                            params=wbi_signed({'mid':creator['mid'],'pn':1,'ps':4,'order':'pubdate'},image,sub)
                            data=await _bili_json(session,'/x/space/wbi/arc/search',params)
                            for video in _parse_space(data):
                                tip=video_tip(video, require_words=False)
                                if tip:
                                    tip['mid']=creator['mid'];raw.append((tip,'creator'))
                            report.append({'kind':'source','name':f'UP {creator["mid"]} 视频','detail':'读取成功'})
                        except (aiohttp.ClientError,TimeoutError,ValueError,TypeError):
                            errors.append(f'UP {creator["mid"]} 视频列表受限')
                        await asyncio.sleep(.25)
        if mode in ('search','both') and not preview:
            if not image or not sub:
                try:image,sub=await _wbi_keys(session)
                except (aiohttp.ClientError,TimeoutError,ValueError,TypeError):
                    errors.append('B站搜索 WBI 初始化失败；已跳过搜索，不影响指定 UP')
            if image and sub:
                kws=[x.strip() for x in re.split('[,，\n]',settings['bili_keywords']) if x.strip()]
                for term in kws[:2]:
                    try:
                        params=wbi_signed({'search_type':'video','keyword':term,'order':'pubdate','page':1},image,sub)
                        data=await _bili_json(session,'/x/web-interface/wbi/search/type',params)
                        for video in _parse_search(data):
                            tip=video_tip(video)
                            if tip:raw.append((tip,'search'))
                    except (aiohttp.ClientError,TimeoutError,ValueError,TypeError):
                        errors.append(f'搜索「{term[:15]}」不可用（可能风控）')
                    await asyncio.sleep(.25)
        seen=set();result=[];detail_cache={}
        ai_budget=settings['bili_ai_calls'] if settings['bili_ai_enabled'] and not preview else 0
        supplied=ai_config if isinstance(ai_config,dict) else {}
        ai_key=supplied.get('api_key') or os.environ.get('ASTR_STEAM_AI_API_KEY','')
        provider=(supplied.get('provider') or os.environ.get('ASTR_STEAM_AI_PROVIDER','openai')).lower()
        model=supplied.get('model') or os.environ.get('ASTR_STEAM_AI_MODEL','gpt-4o-mini')
        if ai_budget and not ai_key:errors.append('AI 已启用但未配置 Key；本轮不调用 AI');ai_budget=0
        for tip,origin in raw[:36]:
            ident=tip['ref']
            if ident in seen or (not preview and store.bili_seen(ident)):continue
            seen.add(ident)
            content=tip['text']
            if tip.get('bvid') and tip['bvid'] not in detail_cache:
                # Video detail may contain Steam links absent from search cards/dynamic titles.
                try:
                    detail=await _bili_json(session,'/x/web-interface/view',{'bvid':tip['bvid']})
                    detail_cache[tip['bvid']]=str(detail.get('desc') or '')[:4500]
                except (aiohttp.ClientError,TimeoutError,ValueError,TypeError):
                    detail_cache[tip['bvid']]=''
            content+=' '+detail_cache.get(tip.get('bvid'),'')
            if not any(w in content for w in FREE_WORDS) or any(w in content for w in NEGATIVE):
                report.append({'kind':'skipped','name':tip['name'][:90],
                               'detail':'未检测到有效限免关键词，或属于免费试玩/引流/抽奖', 'url':tip['url']})
                continue
            links=steam_links(content)
            if not links:
                report.append({'kind':'skipped','name':tip['name'][:90],'detail':'未发现明确 Steam 商店游戏链接','url':tip['url']})
                continue
            if ai_budget:
                ai_budget-=1
                try:
                    verdict=await classify_with_ai(session,tip,provider,ai_key,model)
                    if verdict!='yes':
                        report.append({'kind':'skipped','name':tip['name'][:90],'detail':'AI 未确定为正在领取的活动','url':tip['url']})
                        continue
                except (aiohttp.ClientError,TimeoutError,ValueError,KeyError,TypeError,IndexError):
                    errors.append('AI 识别失败：本轮保守跳过该条，避免误推送')
                    continue
            # Bound Steam queries; only officially validated game links may be emitted.
            if len(links) >= 30:
                report.append({'kind':'source','name':tip['name'][:90],
                               'detail':'本条最多检测 30 个 Steam AppID，若更多请拆分动态', 'url':tip['url']})
            for link in links:
                appid=int(link.split('/app/')[1].split('/')[0])
                state,reason=await verify_steam(session,appid,network)
                corroborated=appid in (corroborated_appids or set())
                allowed=permit_notification(origin,state,corroborated=corroborated,
                                             blocked=any(x in content for x in NEGATIVE))
                detail=f'AppID {appid}：{reason}；'+('促销 API 也证实该 AppID' if corroborated else '未发现独立 API 佐证')
                if not allowed:
                    report.append({'kind':'skipped','name':tip['name'][:90],'detail':detail,'url':tip['url'],'steam_url':link})
                    continue
                event={'key':f'bilibili:{origin}:{ident}:{appid}','name':tip['name'][:180],
                       'kind':'bilibili_tip','source':'Bilibili 关注 UP' if origin=='creator' else 'Bilibili 搜索 · 严格核验',
                       'appid':appid,'url':link,'steam_url':link,'bili_source_url':tip['url'],'bili_origin':origin, 'steam_state':state,
                       'original_price':'Steam 当前免费' if state=='free' else 'Steam 100% 折扣',
                       'end_date':'','confidence':detail+('；已通过双来源筛选，仍需核实永久许可证' if origin=='search' else '；订阅 UP 可信来源，非入库凭证')}
                result.append(event)
                report.append({'kind':'eligible','name':tip['name'][:90],'detail':detail,'url':tip['url'],'steam_url':link})
                if len(result)>=72:break
            if not preview and any(r['key'].startswith(f'bilibili:{origin}:{ident}:') for r in result):
                store.mark_bili_seen(ident)
            if len(result)>=72:break
    return result,errors
