"""API-first Steam giveaway discovery. Each source remains independent on failure.

Never claim that a third-party offer grants an owned Steam license. Original ITAD
and GamerPower destination URLs are retained (including attribution tags).
"""
import re
import asyncio
import aiohttp
from .steam_network import SteamNetwork

ITAD_BASE = 'https://api.isthereanydeal.com'
STEAM_APP = re.compile(r'(?:store\.steampowered\.com/app/|steamcommunity\.com/app/)(\d{1,10})(?:/|\b)', re.I)


def game_id_from_url(value):
    if not isinstance(value, str):
        return 0
    match = STEAM_APP.search(value)
    return int(match.group(1)) if match else 0


def parse_itad_giveaways(data):
    """ITAD /giveaways/v1: named shop must be Steam; uncertain license type."""
    result = []
    if not isinstance(data, list):
        return result
    for item in data[:100]:
        if not isinstance(item, dict) or not isinstance(item.get('shop'), dict):
            continue
        if item['shop'].get('id') != 61 and str(item['shop'].get('name', '')).lower() != 'steam':
            continue
        ident = item.get('id')
        link = str(item.get('url') or item.get('details') or '')
        if not (str(ident).isdigit() and link.startswith('https://')):
            continue
        games = item.get('games')
        if not isinstance(games, list) or not games:
            continue
        for game in games[:4]:
            if not isinstance(game, dict) or game.get('type') != 'game':
                continue
            title = str(game.get('title') or item.get('title') or '').strip()[:180]
            if not title:
                continue
            result.append({'key': f'itad-giveaway:{ident}:{str(game.get("id") or "game")[:50]}',
                'name': title, 'kind': 'promo_api', 'source': 'IsThereAnyDeal / Steam 赠送',
                'appid': game_id_from_url(link), 'url': link, 'original_price': 'Steam 活动免费',
                'end_date': str(item.get('expiry') or '')[:80],
                'confidence': 'ITAD 记录的 Steam 赠送活动；未验证永久许可证，保留原始来源链接'})
    return result


def parse_itad_deals(data):
    """ITAD /deals/v2: require Steam, original paid and exactly 100% reduction."""
    result = []
    items = data.get('list') if isinstance(data, dict) else None
    if not isinstance(items, list):
        return result
    for game in items[:200]:
        if not isinstance(game, dict) or game.get('type') != 'game':
            continue
        deal = game.get('deal') or {}
        if not isinstance(deal, dict) or not isinstance(deal.get('shop'), dict):
            continue
        if deal['shop'].get('id') != 61 and str(deal['shop'].get('name') or '').lower() != 'steam':
            continue
        price = deal.get('price') or {}
        regular = deal.get('regular') or {}
        if (not isinstance(price, dict) or not isinstance(regular, dict) or
            type(price.get('amountInt')) is not int or price['amountInt'] != 0 or
            type(regular.get('amountInt')) is not int or regular['amountInt'] <= 0 or
            deal.get('cut') != 100):
            continue
        title = str(game.get('title') or '').strip()[:180]
        link = str(deal.get('url') or '')
        game_id = str(game.get('id') or '')[:60]
        if not title or not game_id or not link.startswith('https://'):
            # Don't fabricate an affiliate-free Steam destination.
            continue
        result.append({'key': f'itad-deal:{game_id}', 'name': title,
            'kind': 'promo_api', 'source': 'IsThereAnyDeal / Steam 100% 折扣',
            'appid': game_id_from_url(link), 'url': link,
            'original_price': f'{regular["amountInt"]/100:.2f} {regular.get("currency", "")}'[:40],
            'end_date': str(deal.get('expiry') or '')[:80],
            'confidence': 'ITAD 标记 Steam 100% 折扣；需核实优惠有效及能否永久入库'})
    return result


async def fetch_itad_promotions(api_key, network=None):
    if not api_key:
        return [], []
    network = network or SteamNetwork()
    result, errors = [], []
    headers = {'ITAD-API-Key': api_key, 'User-Agent': 'AstrBot-Steam-Freebies/0.6'}
    timeout = aiohttp.ClientTimeout(total=18)
    async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
        for label, endpoint, params, parser in [
            ('ITAD Steam 赠送', '/giveaways/v1', {'limit': 50}, parse_itad_giveaways),
            ('ITAD Steam 折扣', '/deals/v2', {'country': 'US', 'limit': 200, 'shops': '61',
                                             'sort': '-cut', 'filter': '{"cut":{"min":100,"max":100}}'}, parse_itad_deals),
        ]:
            try:
                async with session.get(ITAD_BASE + endpoint, params=params) as resp:
                    resp.raise_for_status()
                    content = await resp.json(content_type=None)
                result.extend(parser(content))
            except (aiohttp.ClientError, TimeoutError, ValueError, TypeError) as exc:
                errors.append(f'{label} API: {type(exc).__name__}')
        # ITAD game UUID -> Steam shop app/ID (single batch request).
        gids = []
        for row in result:
            if row['key'].startswith('itad-deal:'):
                gids.append(row['key'].split(':', 1)[1])
            elif row['key'].startswith('itad-giveaway:'):
                gid = row['key'].split(':', 2)[2]
                if re.fullmatch(r'[0-9a-fA-F-]{36}', gid):
                    gids.append(gid)
        if gids:
            try:
                async with session.post(ITAD_BASE + '/lookup/shop/61/id/v1',
                        json=list(dict.fromkeys(gids))[:80]) as resp:
                    resp.raise_for_status()
                    mapping = await resp.json(content_type=None)
                if isinstance(mapping, dict):
                    for row in result:
                        gid = row['key'].split(':')[-1]
                        for shopid in mapping.get(gid) or []:
                            if isinstance(shopid, str) and re.fullmatch(r'app/\d{1,10}', shopid):
                                row['appid'] = int(shopid.split('/')[1])
                                break
            except (aiohttp.ClientError, TimeoutError, ValueError, TypeError):
                errors.append('ITAD Steam AppID 映射查询不可用')
        # Explicit cross-source check: only verifiable Steam IDs, max 12 per scan.
        checked = 0
        for row in result:
            if not row['appid'] or checked >= 12:
                continue
            checked += 1
            try:
                async with network.session() as steam_session:
                    details = await network.get_json(steam_session,
                        'https://store.steampowered.com/api/appdetails',
                        params={'appids': row['appid'], 'cc': 'cn', 'l': 'schinese'}, timeout=9)
                wrapper = details.get(str(row['appid'])) if isinstance(details, dict) else None
                entry = wrapper.get('data') if isinstance(wrapper, dict) else None
                if isinstance(entry, dict) and entry.get('type') == 'game':
                    if entry.get('is_free') is True:
                        row['confidence'] += '；Steam 当前 is_free=true（不代表永久许可证）'
                    elif isinstance(entry.get('price_overview'), dict) and entry['price_overview'].get('discount_percent') == 100:
                        row['confidence'] += '；Steam 当前商店显示 100% 折扣'
                    else:
                        row['confidence'] += '；Steam 商店未确认同一区域免费，请人工复核'
            except (aiohttp.ClientError, TimeoutError, ValueError, TypeError):
                pass
    return result, errors
