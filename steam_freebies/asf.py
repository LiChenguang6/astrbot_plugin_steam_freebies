"""Strict loopback-only optional ASF bridge, no Steam credentials in AstrBot."""
import asyncio
import os
import re
from urllib.parse import urlparse

import aiohttp

BOT_RE = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")


def config():
    url = os.getenv("ASTR_STEAM_ASF_URL", "http://127.0.0.1:1242").rstrip("/")
    parsed = urlparse(url)
    if parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "localhost", "::1") or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
        raise ValueError("ASF IPC 只能使用本机 http://127.0.0.1:1242 类型地址")
    bot = os.getenv("ASTR_STEAM_ASF_BOT", "")
    if not BOT_RE.fullmatch(bot):
        raise ValueError("先通过 ASTR_STEAM_ASF_BOT 设置要领取的 ASF 机器人名称")
    return url, bot, os.getenv("ASTR_STEAM_ASF_PASSWORD", "")


async def claim_sub(subid):
    if type(subid) is not int or subid <= 0 or subid > 2_147_483_647:
        raise ValueError("不合法的 SubID")
    url, bot, password = config()
    headers = {"Authentication": password} if password else {}
    cmd = f"addlicense {bot} sub/{subid}"
    timeout = aiohttp.ClientTimeout(total=25)
    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        async with session.post(f"{url}/Api/Command", json={"Command": cmd}) as resp:
            resp.raise_for_status()
            data = await resp.json(content_type=None)
    if not isinstance(data, dict):
        raise ValueError("ASF 响应不是 JSON 对象")
    result = str(data.get("Result") or data.get("Message") or "")[:700]
    if not data.get("Success"):
        raise ValueError(f"ASF 拒绝执行: {result[:150]}")
    # Success means the command ran, NOT that Steam irrevocably granted a license.
    return result or "命令已被 ASF 接收；请在 Steam 账号中核验许可证"
