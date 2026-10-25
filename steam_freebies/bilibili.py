"""Opt-in Bilibili metadata with optional private QR-login session; never bypass -412.

Headlines are third-party tips, not proof that a game is free. AI is optional and
strictly limited per scan; no Steam credentials or IPC tokens are sent to AI.
"""
import asyncio
import hashlib
import html
import json
import os
import re
import time
from urllib.parse import urlencode, urlparse

import aiohttp

API = 'https://api.bilibili.com'
BV = re.compile(r'BV[0-9a-zA-Z]{10}')
STEAM_ID = re.compile(r'store\.steampowered\.com/app/(\d{1,10})')
FREE_WORDS = ('喜加一', '限免', '免费领', '免费送', '免费入库', '永久免费', '免费游戏', '0元入库', '零元入库')
NEGATIVE = ('免费周末', '免费试玩', '非免费', '不是免费', '已结束', '活动结束', '骗局', '小心被骗')
MIXIN = (46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
         27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
         37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
         22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52)
PROVIDERS = {
    'openai': 'https://api.openai.com/v1/chat/completions',
    'deepseek': 'https://api.deepseek.com/chat/completions',
    'siliconflow': 'https://api.siliconflow.cn/v1/chat/completions',
    'dashscope': 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions',
}


def extract_bvid(value):
    if not isinstance(value, str):
        return ''
    m = BV.search(value[:350])
    return m.group() if m else ''


def video_tip(item):
    """B站线索仅根据标题/简介初筛；不会自动当作免费许可证。"""
    if not isinstance(item, dict):
        return None
    bvid = extract_bvid(str(item.get('bvid') or item.get('arcurl') or ''))
    title = html.unescape(re.sub(r'<[^>]+>', '', str(item.get('title') or ''))).strip()[:180]
    desc = html.unescape(str(item.get('description') or item.get('desc') or ''))[:800]
    if not bvid or not title:
        return None
    text = title + ' ' + desc
    if not any(word in text for word in FREE_WORDS) or any(word in title for word in NEGATIVE):
        return None
    owner = item.get('owner') or {}
    uid = owner.get('mid') if isinstance(owner, dict) else item.get('mid')
    pubdate = item.get('pubdate') or item.get('created') or 0
    if type(pubdate) is not int or pubdate <= 0 or time.time() - pubdate > 7 * 86400 or pubdate > time.time() + 3600:
        return None
    match = STEAM_ID.search(text)
    return {'bvid': bvid, 'mid': int(uid) if str(uid).isdigit() else 0,
            'name': title, 'description': desc, 'appid': int(match.group(1)) if match else 0,
            'pubdate': pubdate, 'url': f'https://www.bilibili.com/video/{bvid}/'}


def wbi_signed(params, image_url, sub_url, now=None):
    parts = [urlparse(x).path.rsplit('/', 1)[-1].split('.')[0] for x in (image_url, sub_url)]
    key = ''.join(parts)
    if len(key) < 64:
        raise ValueError('B站 WBI 签名密钥不可用')
    mixin = ''.join(key[i] for i in MIXIN)[:32]
    values = {k: ''.join(ch for ch in str(v) if ch not in "!'()*") for k, v in params.items()}
    values['wts'] = int(time.time() if now is None else now)
    query = urlencode(sorted(values.items()))
    values['w_rid'] = hashlib.md5((query + mixin).encode('utf-8')).hexdigest()
    return values


async def _bili_json(session, path, params):
    async with session.get(API + path, params=params, timeout=aiohttp.ClientTimeout(total=12)) as response:
        response.raise_for_status()
        payload = await response.json(content_type=None)
    if not isinstance(payload, dict):
        raise ValueError('B站返回数据格式无效')
    if payload.get('code') != 0:
        # Rate limits and login verification are not bypassed.
        code = payload.get('code')
        notice = '需要登录：请使用面板的官方二维码扫码' if code in (-101,-111) else '可能遇到访问频率限制，请稍后重试' if code in (-412,-352) else '可能接口变更或权限不足'
        raise ValueError(f'B站接口拒绝请求（code={code}，{notice}）')
    return payload.get('data') or {}


async def resolve_video_owner(bvid, auth=None):
    if not BV.fullmatch(bvid):
        raise ValueError('请填写有效的 B站 BV 号或视频链接')
    headers = auth.headers() if auth else {'User-Agent': 'Mozilla/5.0 SteamFreebiesAstrBot/0.6',
               'Referer': 'https://www.bilibili.com/'}
    async with aiohttp.ClientSession(headers=headers) as session:
        data = await _bili_json(session, '/x/web-interface/view', {'bvid': bvid})
    owner = data.get('owner') or {}
    mid = owner.get('mid') if isinstance(owner, dict) else None
    name = str(owner.get('name') or '')[:80] if isinstance(owner, dict) else ''
    if type(mid) is not int or not 0 < mid < 10**15:
        raise ValueError('B站视频中未找到有效的 UP 主 UID')
    return mid, name or f'UP {mid}'


async def _wbi_keys(session):
    data = await _bili_json(session, '/x/web-interface/nav', {})
    image = data.get('wbi_img') or {}
    return str(image.get('img_url') or ''), str(image.get('sub_url') or '')


def _parse_search(payload):
    return payload.get('result') if isinstance(payload.get('result'), list) else []


def _parse_space(payload):
    listing = payload.get('list') if isinstance(payload, dict) else None
    return listing.get('vlist') if isinstance(listing, dict) and isinstance(listing.get('vlist'), list) else []


async def classify_with_ai(session, video, provider, key, model):
    """Opt-in single small text completion, max 170 tokens output, no retries."""
    url = PROVIDERS.get(provider)
    if not url or not key or not re.fullmatch(r'[\w./:-]{1,100}', model):
        raise ValueError('AI 提供商、模型或 API Key 未正确配置')
    prompt = ('判断此 B站视频是否在介绍当前可以免费领取或永久转免费的 Steam 游戏。'
              '注意免费试玩/周末/纯 F2P 推荐不算。只输出 JSON：'
              '{"result":"yes|no|uncertain","reason":"20字以内"}。'
              '无法确认请用 uncertain，不要编造 Steam AppID、限免日期、优惠信息。\n'
              f'标题：{video["name"][:150]}\n简介：{video["description"][:450]}')
    body = {'model': model, 'temperature': 0, 'max_tokens': 170,
            'messages': [{'role': 'user', 'content': prompt}]}
    async with session.post(url, headers={'Authorization': f'Bearer {key}'}, json=body,
                            timeout=aiohttp.ClientTimeout(total=14)) as resp:
        resp.raise_for_status()
        answer = await resp.json(content_type=None)
    content = answer['choices'][0]['message']['content']
    if not isinstance(content, str):
        return 'uncertain'
    m = re.search(r'\b(yes|no|uncertain)\b', content[:300])
    return m.group(1) if m else 'uncertain'


async def fetch_bilibili_tips(store, ai_config=None, auth=None):
    settings = store.settings()
    if not settings['bili_enabled']:
        return [], []
    errors, raw = [], []
    headers = auth.headers() if auth else {'User-Agent': 'Mozilla/5.0 SteamFreebiesAstrBot/0.6',
               'Referer': 'https://www.bilibili.com/'}
    async with aiohttp.ClientSession(headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as session:
        try:
            img, sub = await _wbi_keys(session)
        except ValueError as exc:
            # Only locally authored validation messages are surfaced; never raw headers/cookies.
            return [], [f'B站 WBI 初始化失败：{str(exc)[:150]}；可扫码登录或稍后重试']
        except (aiohttp.ClientError, TimeoutError, TypeError) as exc:
            return [], [f'B站 WBI 连接失败：{type(exc).__name__}；请检查容器到 api.bilibili.com 的网络']
        creators = store.bili_creators()[:3]
        for creator in creators:
            try:
                params = wbi_signed({'mid': creator['mid'], 'pn': 1, 'ps': 12, 'order': 'pubdate'}, img, sub)
                data = await _bili_json(session, '/x/space/wbi/arc/search', params)
                raw.extend(_parse_space(data))
            except (aiohttp.ClientError, TimeoutError, ValueError, TypeError) as exc:
                errors.append(f'B站 UP {creator["mid"]}：{type(exc).__name__}（可能限流/风控）')
            await asyncio.sleep(.8)
        kws = [x.strip() for x in re.split('[,，\n]', settings['bili_keywords']) if x.strip()]
        for term in kws[:2]:
            try:
                params = wbi_signed({'search_type': 'video', 'keyword': term, 'order': 'pubdate', 'page': 1}, img, sub)
                data = await _bili_json(session, '/x/web-interface/wbi/search/type', params)
                raw.extend(_parse_search(data))
            except (aiohttp.ClientError, TimeoutError, ValueError, TypeError):
                errors.append(f'B站关键词「{term[:14]}」搜索不可用（可能风控）')
            await asyncio.sleep(.8)
        result = []
        used = set()
        ai_budget = settings['bili_ai_calls'] if settings['bili_ai_enabled'] else 0
        supplied = ai_config if isinstance(ai_config, dict) else {}
        api_key = supplied.get('api_key') or os.environ.get('ASTR_STEAM_AI_API_KEY', '')
        provider = (supplied.get('provider') or os.environ.get('ASTR_STEAM_AI_PROVIDER', 'openai')).lower()
        model = supplied.get('model') or os.environ.get('ASTR_STEAM_AI_MODEL', 'gpt-4o-mini')
        if ai_budget and not api_key:
            errors.append('B站 AI 已开启但缺少 ASTR_STEAM_AI_API_KEY，改用本地关键词识别')
            ai_budget = 0
        for video in raw:
            item = video_tip(video)
            if not item or item['bvid'] in used or store.bili_seen(item['bvid']):
                continue
            used.add(item['bvid'])
            if ai_budget:
                ai_budget -= 1
                try:
                    verdict = await classify_with_ai(session, item, provider, api_key, model)
                    if verdict == 'no':
                        store.mark_bili_seen(item['bvid'])
                        continue
                    item['verdict'] = verdict
                except (aiohttp.ClientError, TimeoutError, ValueError, KeyError, TypeError, IndexError):
                    errors.append('B站 AI 辅助识别失败，改用本地规则（本轮不重试）')
            store.mark_bili_seen(item['bvid'])
            result.append({'key': f'bilibili:{item["bvid"]}', 'name': item['name'],
                'kind': 'bilibili_tip', 'source': 'Bilibili UP主 / 关键词',
                'appid': item['appid'], 'url': item['url'], 'original_price': '视频线索',
                'end_date': '', 'confidence': ('B站视频线索；' + ('AI 认为可能相关；' if item.get('verdict') == 'yes' else '')
                     + '尚未经 Steam 官方验证，非实际限免凭证')})
            if len(result) >= 10:
                break
        return result, errors
