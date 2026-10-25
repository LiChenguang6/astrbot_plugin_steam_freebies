"""Bilibili tips are never ownership proofs: extract allowlisted Steam links and verify public store sale.

Never call ASF here. A Steam AppID, a Steam SubID link and a giveaway are different objects.
"""
import html
import re

import aiohttp

APP = re.compile(r'(?:(?:https?://)?(?:store\.steampowered\.com|store\.steamchina\.com)/app/)(\d{1,10})(?:/|\b)', re.I)
SUB = re.compile(r'(?:(?:https?://)?store\.steampowered\.com/sub/)(\d{1,10})(?:/|\b)', re.I)
STRONG_FALSE = ('免费周末', '免费试玩', '限时试玩', '非免费', '并非免费', '已结束', '活动结束', '抽奖', '送粉丝', '关注后', '私信领取', '进群领取')


def steam_links(text):
    """Only official store URLs. Normalizes Markdown/HTML text; never follows unknown redirectors."""
    if not isinstance(text, str):
        return []
    text = html.unescape(text.replace('\\/', '/'))[:10000]
    results = []
    for match in APP.finditer(text):
        value = int(match.group(1))
        if value > 0:
            link = f'https://store.steampowered.com/app/{value}/'
            if link not in results:
                results.append(link)
    return results[:30]


def linked_subids(text):
    """For display/triage only, NEVER trust as an approved free-to-keep license."""
    if not isinstance(text, str):
        return []
    return list(dict.fromkeys(int(m.group(1)) for m in SUB.finditer(html.unescape(text[:10000])) if int(m.group(1))>0))[:5]


def classify_store_details(payload, appid):
    entry = payload.get(str(appid), {}) if isinstance(payload, dict) else {}
    item = entry.get('data') if isinstance(entry, dict) and entry.get('success') is True else None
    if not isinstance(item, dict) or item.get('type') != 'game':
        return 'unknown', 'Steam 官方未返回游戏详情'
    price = item.get('price_overview')
    if isinstance(price, dict) and (type(price.get('initial')) is int and price['initial']>0
            and price.get('final') == 0 and price.get('discount_percent') == 100):
        return 'sale_100', 'Steam 当前显示原价大于 0 且折扣 100%（不等于许可证已入库）'
    if item.get('is_free') is True:
        return 'free', 'Steam 仅返回 is_free=true：可能是普通永久免费/F2P；未确认限时免费永久领取，已排除自动领取和 QQ 推送'
    return 'not_free', 'Steam 未确认当前免费/100% 折扣'


async def verify_steam(session, appid, network=None):
    """Public Steam observation; NO Steam credentials / no license claims."""
    if type(appid) is not int or not 0<appid<=2147483647:
        return 'unknown', 'Steam AppID 无效'
    try:
        url='https://store.steampowered.com/api/appdetails'
        params={'appids':appid,'cc':'cn','l':'schinese'}
        if network is not None:
            # Steam transport owns proxy settings: do not reuse the Bilibili session.
            async with network.session(timeout=12) as steam_session:
                data=await network.get_json(steam_session,url,params=params,timeout=9,attempts=2)
        else:
            async with session.get(url,params=params,timeout=aiohttp.ClientTimeout(total=9)) as response:
                response.raise_for_status();data=await response.json(content_type=None)
        return classify_store_details(data,appid)
    except (aiohttp.ClientError,TimeoutError,TypeError,ValueError):
        return 'unknown', 'Steam 商店查询失败，未通过核验'



def permit_notification(origin, steam_state, *, corroborated=False, blocked=False):
    """Search needs both a strong Steam sale and an independent API corroboration."""
    if blocked:
        return False
    if origin=='creator':
        # is_free alone commonly describes free-to-play; never promote it as Free-to-Keep.
        return steam_state == 'sale_100'
    if origin=='search':
        return steam_state == 'sale_100' and bool(corroborated)
    return False
