"""Price checks for explicitly watched Steam AppIDs only.

No random catalog samples. First observation is a baseline; a later change is an
alert. `is_free=true` is a candidate, not a permanent license guarantee.
"""
import asyncio
import os
import re
from datetime import datetime, timezone, timedelta

import aiohttp
from .steam_network import SteamNetwork

DETAILS = 'https://store.steampowered.com/api/appdetails'
ITAD = 'https://api.isthereanydeal.com'


def parse_appdetails(data, appid):
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
        # Temporary zero-price sale is not paid->permanent-free, handle promotions elsewhere.
        return None
    return {'appid': appid, 'name': name, 'state': 'paid', 'amount': final,
            'currency': str(price.get('currency') or '')[:8],
            'url': f'https://store.steampowered.com/app/{appid}/'}


def itad_paid_history(records):
    if not isinstance(records, list):
        return False
    for event in records:
        if not isinstance(event, dict) or not isinstance(event.get('shop'), dict):
            continue
        if event['shop'].get('id') != 61 and str(event['shop'].get('name') or '').lower() != 'steam':
            continue
        deal = event.get('deal')
        price = deal.get('price') if isinstance(deal, dict) else None
        if isinstance(price, dict) and type(price.get('amountInt')) is int and price['amountInt'] > 0:
            return True
    return False


async def check_itad_paid_history(session, appid, api_key):
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
    since = (datetime.now(timezone.utc) - timedelta(days=365 * 2)).isoformat(timespec='seconds')
    async with session.get(ITAD + '/games/history/v2', params={'id': game_id, 'country': 'US', 'since': since},
                           headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as response:
        response.raise_for_status()
        return itad_paid_history(await response.json(content_type=None))


async def monitor_prices(store, *, api_key=None, network=None):
    """Only explicit manual watchlist; bounded parallelism and API calls."""
    api_key = api_key if api_key is not None else os.environ.get('ASTR_STEAM_ITAD_API_KEY', '')
    network = network or SteamNetwork(store.settings())
    ids = store.price_watch_ids(manual_only=True, limit=120)
    if not ids:
        return [], []
    errors, observations = [], []
    async with network.session() as session:
        gate = asyncio.Semaphore(3)
        async def fetch_one(appid):
            async with gate:
                try:
                    data = await network.get_json(session, DETAILS, params={'appids': appid, 'cc': 'cn', 'l': 'schinese'})
                    return parse_appdetails(data, appid)
                except (aiohttp.ClientError, TimeoutError, ValueError, TypeError):
                    errors.append(f'Steam App {appid} 价格读取失败')
                    return None
        observations = [row for row in await asyncio.gather(*(fetch_one(x) for x in ids)) if row]
        transitions = store.record_price_observations(observations)
        if api_key:
            for event in [x for x in transitions if x['kind'] == 'paid_to_free'][:2]:
                try:
                    if await check_itad_paid_history(session, event['appid'], api_key):
                        event['confidence'] += '；ITAD 历史也有 Steam 收费记录'
                    else:
                        event['confidence'] += '；ITAD 未补充到历史（不代表从未收费）'
                except (aiohttp.ClientError, TimeoutError, ValueError, TypeError):
                    errors.append('ITAD 历史价格查询失败')
    if transitions:
        store.upsert_games(transitions)
    return transitions, errors
