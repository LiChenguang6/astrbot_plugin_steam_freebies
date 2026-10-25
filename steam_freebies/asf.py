"""Authenticated loopback ASF IPC bridge. A command's execution != an owned license."""
import os
import re
from urllib.parse import urlparse
import aiohttp

BOT_RE = re.compile(r'^[A-Za-z0-9_-]{1,64}$')


def config(manager=None):
    if manager and manager.settings()['mode'] == 'managed':
        url, bot, password = manager.ipc()
    else:
        url = os.getenv('ASTR_STEAM_ASF_URL','http://127.0.0.1:1242').rstrip('/')
        bot = os.getenv('ASTR_STEAM_ASF_BOT','')
        password = os.getenv('ASTR_STEAM_ASF_PASSWORD','')
    parsed = urlparse(url)
    if parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1','localhost','::1') or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
        raise ValueError('ASF IPC 仅允许本机 loopback HTTP 访问')
    if not BOT_RE.fullmatch(bot):
        raise ValueError('需要配置 ASF Bot 名称，或设置 ASTR_STEAM_ASF_BOT')
    return url,bot,password


def classify_result(value):
    """Conservative label: ASF Success means IPC command accepted, not owned license."""
    txt=str(value).lower()
    failures=('accessdenied','access denied','failed','failure','error','denied','invalid',
              'not eligible','not successful','not granted','no license','nolicense','region restricted','timeout','已拒绝','失败','错误','受限','无法领取')
    if any(x in txt for x in failures): return 'failed'
    positives=('已添加','已拥有','成功','alreadyowned')
    if any(x in txt for x in positives) or re.search(r'\b(?:ok|success(?:ful(?:ly)?)?|added|granted|already[ -]owned)\b',txt):
        return 'reported_success'
    return 'submitted'


async def claim_sub(subid, manager=None):
    if type(subid) is not int or not 0 < subid <= 2_147_483_647:
        raise ValueError('不合法的 SubID')
    url, bot, password = config(manager)
    headers = {'Authentication':password} if password else {}
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=25),headers=headers) as session:
        async with session.post(f'{url}/Api/Command',json={'Command':f'addlicense {bot} sub/{subid}'}) as resp:
            resp.raise_for_status()
            data=await resp.json(content_type=None)
    if not isinstance(data,dict): raise ValueError('ASF 响应不是 JSON 对象')
    result=str(data.get('Result') or data.get('Message') or '')[:700]
    if not data.get('Success'): raise ValueError(f'ASF 拒绝执行：{result[:180]}')
    return classify_result(result), (result or 'ASF 已接收命令，等待 Steam 许可证核验')
