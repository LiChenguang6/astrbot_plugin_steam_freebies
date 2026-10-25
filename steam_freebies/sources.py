"""Candidates only: neither the store HTML nor GamerPower certifies ownership."""
import asyncio
import re
from html import unescape
from urllib.parse import urlparse

import aiohttp
from bs4 import BeautifulSoup

SEARCH_URL = "https://store.steampowered.com/search/results/"
GIVEAWAYS_URL = "https://www.gamerpower.com/api/giveaways"
APP_RE = re.compile(r"/app/(\d+)")


def parse_steam_html(html):
    soup = BeautifulSoup(html, "html.parser")
    games = []
    for row in soup.select("a.search_result_row"):
        href = row.get("href", "")
        match = APP_RE.search(href)
        if not match:
            continue
        discount = row.select_one(".discount_pct")
        # A genuine 100% sale is a *candidate*, not proof of Free-to-Keep.
        if discount is None or "-100%" not in discount.get_text(" ", strip=True):
            continue
        name = row.select_one(".title")
        if name is None:
            continue
        price = row.select_one(".discount_original_price")
        appid = match.group(1)
        games.append({
            "key": f"steam:{appid}", "source": "Steam 商店", "kind": "steam_candidate",
            "appid": int(appid), "name": unescape(name.get_text(" ", strip=True))[:180],
            "url": f"https://store.steampowered.com/app/{appid}/",
            "original_price": price.get_text(" ", strip=True)[:40] if price else "未知",
            "end_date": "", "confidence": "仅检测到 100% 折扣，尚未确认永久入库",
        })
    return games


def parse_gamerpower(data):
    if not isinstance(data, list):
        return []
    games = []
    for item in data:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()[:180]
        url = str(item.get("open_giveaway_url") or item.get("gamerpower_url") or "")
        if not title or urlparse(url).scheme not in ("https", "http"):
            continue
        gid = str(item.get("id") or "")
        if not gid.isdigit():
            continue
        match = APP_RE.search(str(item.get("description") or "") + " " + url)
        games.append({
            "key": f"gamerpower:{gid}", "source": "GamerPower", "kind": "third_party",
            "appid": int(match.group(1)) if match else 0, "name": title, "url": url,
            "original_price": str(item.get("worth") or "未知")[:40],
            "end_date": str(item.get("end_date") or "")[:80],
            "confidence": "第三方赠送活动，可能需要领取 Key，不一定能直接 Steam 入库",
        })
    return games


async def fetch_candidates():
    timeout = aiohttp.ClientTimeout(total=24)
    headers = {"User-Agent": "Mozilla/5.0 SteamFreebiesAstrBot/0.1"}
    output, errors = [], []
    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        try:
            params = {"maxprice": "free", "specials": "1", "infinite": "1", "start": "0", "count": "100", "category1": "998", "l": "schinese"}
            async with session.get(SEARCH_URL, params=params) as resp:
                resp.raise_for_status()
                payload = await resp.json(content_type=None)
            output.extend(parse_steam_html(str(payload.get("results_html", ""))))
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, TypeError) as exc:
            errors.append(f"Steam 搜索: {type(exc).__name__}: {str(exc)[:90]}")
        try:
            async with session.get(GIVEAWAYS_URL, params={"platform": "steam", "type": "game"}) as resp:
                if resp.status == 201:
                    data = []
                else:
                    resp.raise_for_status()
                    data = await resp.json(content_type=None)
            output.extend(parse_gamerpower(data))
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, TypeError) as exc:
            errors.append(f"GamerPower: {type(exc).__name__}: {str(exc)[:90]}")
    return output, errors
