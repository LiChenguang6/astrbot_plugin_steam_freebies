"""Bounded Steam price-change monitor. Free status is a candidate, not ownership proof.

Price observations are persisted before emitting paid->free events. ITAD is optional,
lookup-only corroboration and never used to fabricate a recent change on a cold start.
"""
import asyncio
import os
import re
from datetime import datetime, timezone, timedelta

import aiohttp
from bs4 import BeautifulSoup

SEARCH = "https://store.steampowered.com/search/results/"
DETAILS = "https://store.steampowered.com/api/appdetails"
ITAD = "https://api.isthereanydeal.com"
APP = re.compile(r"/app/(\d+)")


def parse_search_ids(html, limit=120):
    """List discovered Steam app IDs without deciding paid/free from search markup."""
    found = []
    seen = set()
    for row in BeautifulSoup(html, 'html.parser').select('a.search_result_row'):
        match = APP.search(row.get('href', ''))
        if not match:
            continue
        appid = int(match.group(1))
        if appid > 0 and appid not in seen:
            seen.add(appid)
            found.append(appid)
        if len(found) >= limit:
            break
    return found


def parse_appdetails(data, appid):
    """Strict: do not infer free from absent price or zero discount final price."""
    wrapper = data.get(str(appid)) if isinstance(data, dict) else None
    if not isinstance(wrapper, dict) or wrapper.get('success') is not True:
        return None
    item = wrapper.get('data')
    if not isinstance(item, dict) or item.get('type') != 'game':
        return None
    name = str(item.get('name') or '').strip()[:180]
    if not name:
        return None
    if item.get('is_free') is True:
        return {'appid': appid, 'name': name, 'state': 'free', 'amount': 0, 'currency': '',
                'url': f'https://store.steampowered.com/app/{appid}/'}
    price = item.get('price_overview')
    if not isinstance(price, dict):
        return None
    final = price.get('final')
    if type(final) is not int or final <= 0:
        # Promotional 100%-discount and unknown prices are NOT a permanent-free transition.
        return None
    currency = str(price.get('currency') or '')[:8]
    return {'appid': appid, 'name': name, 'state': 'paid', 'amount': final,
            'currency': currency, 'url': f'https://store.steampowered.com/app/{appid}/'}


def itad_paid_history(records):
    """Only positive *actual* Steam price history counts; other shops don't prove Steam was paid."""
    if not isinstance(records, list):
        return False
    for event in records:
        if not isinstance(event, dict) or not isinstance(event.get('shop'), dict):
            continue
        if str(event['shop'].get('name') or '').lower() != 'steam':
            continue
        deal = event.get('deal')
        price = deal.get('price') if isinstance(deal, dict) else None
        if isinstance(price, dict) and isinstance(price.get('amountInt'), int) and price['amountInt'] > 0:
            return True
    return False


async def check_itad_paid_history(session, appid, api_key):
    """API key is sent as an HTTP header, never stored in SQLite or returned to UI."""
    headers = {'ITAD-API-Key': api_key}
    async with session.get(ITAD + '/games/lookup/v1', params={'appid': appid}, headers=headers,
                           timeout=aiohttp.ClientTimeout(total=9)) as response:
        response.raise_for_status()
        result = await response.json(content_type=None)
    if not isinstance(result, dict) or result.get('found') is not True:
        return False
    game = result.get('game')
    game_id = game.get('id') if isinstance(game, dict) else None
    if not isinstance(game_id, str) or not re.fullmatch(r'[0-9a-fA-F-]{36}', game_id):
        return False
    # Bounded history, so 'not found' means 'not corroborated', not 'never paid'.
    since = (datetime.now(timezone.utc) - timedelta(days=365 * 2)).isoformat(timespec='seconds')
    async with session.get(ITAD + '/games/history/v2', params={'id': game_id, 'country': 'US', 'since': since},
                           headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as response:
        response.raise_for_status()
        return itad_paid_history(await response.json(content_type=None))


def pick_appids(tracked, recent, free, budget=18):
    """Give room to long-term tracked paid games, fresh catalog, and free listings."""
    groups = (list(tracked)[:9], list(free)[:5], list(recent)[:8])
    ids = []
    for group in groups:
        for appid in group:
            if appid not in ids and type(appid) is int and 0 < appid <= 2147483647:
                ids.append(appid)
            if len(ids) >= budget:
                return ids
    return ids


async def monitor_prices(store, *, api_key=None):
    """Returns (new conversion events, provider errors). Never reads the entire app catalog."""
    api_key = api_key if api_key is not None else os.environ.get('ASTR_STEAM_ITAD_API_KEY', '')
    budget = store.settings()['price_checks_per_scan']
    headers = {'User-Agent': 'Mozilla/5.0 SteamFreebiesAstrBot/0.5'}
    # Rotate search pages hourly instead of sampling the same first page forever.
    page_start = (int(datetime.now(timezone.utc).timestamp()) // 3600 % 6) * 80
    found = {'recent': [], 'free': []}
    errors = []
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=17), headers=headers) as session:
        async def search(name, params):
            try:
                async with session.get(SEARCH, params=params) as response:
                    response.raise_for_status()
                    payload = await response.json(content_type=None)
                found[name] = parse_search_ids(payload.get('results_html', ''))
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, TypeError) as exc:
                errors.append(f'Steam 价格发现 {name}: {type(exc).__name__}')
        await asyncio.gather(
            search('recent', {'sort_by': 'Released_DESC', 'category1': '998', 'infinite': 1,
                              'start': page_start, 'count': 80, 'l': 'schinese'}),
            search('free', {'maxprice': 'free', 'sort_by': 'Released_DESC', 'category1': '998',
                            'infinite': 1, 'start': page_start, 'count': 80, 'l': 'schinese'}),
        )
        tracked = store.price_watch_ids(limit=9)
        appids = pick_appids(tracked, found['recent'], found['free'], budget)
        semaphore = asyncio.Semaphore(3)
        async def get_detail(appid):
            async with semaphore:
                try:
                    async with session.get(DETAILS, params={'appids': appid, 'cc': 'cn', 'l': 'schinese'}) as response:
                        response.raise_for_status()
                        return parse_appdetails(await response.json(content_type=None), appid)
                except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, TypeError):
                    return None
        observations = [x for x in await asyncio.gather(*(get_detail(x) for x in appids)) if x]
        # Only after a real, *local* paid->free transition, optionally annotate ITAD evidence.
        transitions = store.record_price_observations(observations)
        if api_key and transitions:
            for row in transitions[:2]:
                try:
                    confirmed = await check_itad_paid_history(session, row['appid'], api_key)
                    if confirmed:
                        row['confidence'] += '；ITAD 近两年 Steam 历史价格存在收费记录'
                    else:
                        row['confidence'] += '；ITAD 未能补充收费历史（不表示从未收费）'
                except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, TypeError):
                    errors.append('ITAD 历史查询失败：请检查 API Key 或网络')
    if transitions:
        store.upsert_games(transitions)  # persist optional historical annotation
    return transitions, errors
