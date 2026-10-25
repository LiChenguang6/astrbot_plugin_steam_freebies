"""Small ASF management UI backend: tightly scoped loopback IPC only.

This is NOT a reverse proxy for the full ASF API or upstream ASF-ui. Never return raw
Bot/Config response objects (they can contain sensitive Steam account details).
"""
import json
import re
from pathlib import Path

import aiohttp

BOT = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
INPUT_TYPES = frozenset({'Password', 'SteamGuard', 'TwoFactorAuthentication', 'DeviceConfirmation', 'SteamParentalCode'})


def chosen_bot(manager, name=None):
    if manager.settings().get('mode') != 'managed':
        raise ValueError('请将 ASF 连接模式设置为「插件托管 ASF」')
    bot = manager.settings().get('bot_name')
    if not isinstance(bot, str) or not BOT.fullmatch(bot) or bot.lower() == 'asf':
        raise ValueError('请先创建并配置一个 ASF Bot 名称')
    if name is not None and name != bot:
        raise ValueError('只能管理当前已配置的本地 ASF Bot')
    return bot


def config_file(manager):
    bot = chosen_bot(manager)
    # Fixed directory and strict one-segment bot name prevent path traversal.
    return manager.path / 'config' / (bot + '.json')


def local_bot_view(manager):
    bot = chosen_bot(manager)
    path = config_file(manager)
    result = {'bot_name': bot, 'configured': path.is_file(), 'enabled': False,
              'steam_login_configured': False, 'steam_password_saved': False}
    if not path.is_file():
        return result
    try:
        obj = json.loads(path.read_text(encoding='utf-8'))
        if isinstance(obj, dict):
            result['enabled'] = obj.get('Enabled') is True
            result['steam_login_configured'] = bool(obj.get('SteamLogin'))
            result['steam_password_saved'] = bool(obj.get('SteamPassword'))
    except (OSError, ValueError):
        pass
    return result


class EmbeddedUI:
    def __init__(self, manager):
        self.manager = manager

    async def _api(self, method, path, *, body=None):
        if not self.manager.running():
            raise ValueError('ASF 尚未启动，请先点击「启动 ASF」')
        url, bot, password = self.manager.ipc()
        # Never follow arbitrary user-provided URLs; bot name is single-segment validated.
        if url != 'http://127.0.0.1:1242':
            raise ValueError('当前 ASF 地址不是受信任的本地 IPC')
        timeout = aiohttp.ClientTimeout(total=15)
        try:
            async with aiohttp.ClientSession(timeout=timeout, headers={'Authentication': password}) as session:
                async with session.request(method, url + path, json=body, allow_redirects=False) as response:
                    if response.status != 200:
                        raise ValueError(f'ASF API 请求未成功（HTTP {response.status}），请查看 ASF 日志')
                    payload = await response.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError) as exc:
            # Do not forward exception text containing HTTP request bodies or secrets.
            raise ValueError(f'ASF 本地 IPC 连接失败（{type(exc).__name__}）') from exc
        if not isinstance(payload, dict) or payload.get('Success') is not True:
            raise ValueError('ASF 未接受该操作，请检查账号是否存在、是否已启用及 ASF 日志')
        return payload

    async def status(self):
        try:
            local = local_bot_view(self.manager)
        except ValueError as exc:
            return {'available': False, 'message': str(exc), 'running': self.manager.running()}
        local.update({'running': self.manager.running(), 'connected': False,
                      'required_input': '', 'steam_id_present': False})
        if not self.manager.running() or not local['configured']:
            return local
        bot = local['bot_name']
        try:
            raw = await self._api('GET', '/Api/Bot/' + bot)
            obj = (raw.get('Result') or {}).get(bot) if isinstance(raw.get('Result'), dict) else None
            if isinstance(obj, dict):
                local['connected'] = obj.get('IsConnectedAndLoggedOn') is True
                required = str(obj.get('RequiredInput') or '')
                if required in INPUT_TYPES:
                    local['required_input'] = required
                local['steam_id_present'] = bool(obj.get('SteamID'))
        except ValueError:
            # A still-starting bot is not necessarily an API error.
            local['status_note'] = 'Bot 状态暂不可用，可稍后刷新或查看 ASF 本地日志'
        return local

    async def set_enabled(self, enabled):
        if type(enabled) is not bool:
            raise ValueError('启用状态必须是布尔值')
        path = config_file(self.manager)
        if not path.is_file():
            raise ValueError('请先在面板创建 Bot 配置')
        try:
            config = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError) as exc:
            raise ValueError('本地 Bot 配置无法读取') from exc
        if not isinstance(config, dict):
            raise ValueError('Bot 配置不是 JSON 对象')
        config['Enabled'] = enabled
        # ASF handles the file write and bot reload. We only return an acknowledgement,
        # never config data or ASF response, which may contain credentials.
        bot = chosen_bot(self.manager)
        await self._api('POST', '/Api/Bot/' + bot, body={'BotConfig': config})
        return {'ok': True, 'notice': 'Bot 已启用，可点击「启动 Bot」' if enabled else 'Bot 已停用'}

    async def control(self, action):
        if action not in ('Start', 'Stop'):
            raise ValueError('只允许启动或停止当前 Bot')
        bot = chosen_bot(self.manager)
        await self._api('POST', f'/Api/Bot/{bot}/{action}')
        return {'ok': True, 'notice': 'Bot 启动命令已提交' if action == 'Start' else 'Bot 停止命令已提交'}

    async def input_secret(self, kind, value):
        if kind not in INPUT_TYPES:
            raise ValueError('不支持这种身份验证输入')
        if type(value) is not str or not value or len(value) > 128 or any(ord(c) < 32 for c in value):
            raise ValueError('输入必须是 1–128 位且不能包含控制字符')
        bot = chosen_bot(self.manager)
        # Only transient loopback IPC; never write, log, cache, or echo this value.
        await self._api('POST', f'/Api/Bot/{bot}/Input', body={'Type': kind, 'Value': value})
        return {'ok': True, 'notice': '一次性验证输入已传递给 ASF，未在插件中保存；请按需要再次启动 Bot'}
