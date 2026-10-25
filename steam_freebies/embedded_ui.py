"""Constrained ASF IPC management inside an authenticated AstrBot plugin page.

Not an ASF-ui reverse proxy. Do not return raw ASF config, reply bodies, Steam
passwords, Steam Guard codes, or the IPC secret to browser clients or logs.
"""
import json
import re

import aiohttp

BOT = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
# ASF.EUserInputType in upstream Core/ASF.cs (byte enum). ASP.NET JSON model
# binding accepts its numeric representation across ASF versions.
INPUT_TYPE_IDS = {
    'Password': 2,
    'SteamGuard': 3,
    'SteamParentalCode': 4,
    'TwoFactorAuthentication': 5,
    'DeviceConfirmation': 7,
}
INPUT_TYPES_BY_ID = {number: label for label, number in INPUT_TYPE_IDS.items()}
INPUT_TYPES = frozenset(INPUT_TYPE_IDS)


def chosen_bot(manager, name=None):
    if manager.settings().get('mode') != 'managed':
        raise ValueError('请将 ASF 连接模式设置为「插件托管 ASF」，点击保存')
    bot = manager.settings().get('bot_name')
    if not isinstance(bot, str) or not BOT.fullmatch(bot) or bot.lower() == 'asf':
        raise ValueError('请先创建并配置 ASF Bot 名称')
    if name is not None and name != bot:
        raise ValueError('只能管理当前已配置的本地 ASF Bot')
    return bot


def config_file(manager):
    return manager.path / 'config' / (chosen_bot(manager) + '.json')


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


def _safe_api_hint(status, operation, payload=None):
    """Summarize an ASF error without reflecting arbitrary response/user input."""
    text = ''
    if isinstance(payload, dict):
        try:
            text = json.dumps(payload, ensure_ascii=False).lower()[:8192]
        except (TypeError, ValueError):
            pass
    if status in (401, 403):
        return 'ASF IPC 身份验证失败，请检查容器内的私有 IPCPassword 是否与运行中的 ASF 一致'
    if status == 404:
        return 'ASF 接口不存在或当前 ASF 版本不支持，请检查版本及是否连接了正确的本机 ASF'
    if status == 400:
        if 'botnotfound' in text or 'bot not found' in text or 'could not find bot' in text or 'not defined' in text:
            return 'ASF 尚未加载该 Bot：请确认已创建配置、启用 Bot，并重启 ASF 后刷新'
        if operation == 'input':
            if 'type' in text or 'json' in text or 'convert' in text:
                return 'ASF 拒绝验证输入的 Type/JSON 格式；新版插件已改用官方枚举数值，请重新提交一次'
            return 'ASF 拒绝本次验证输入：请先启动 Bot，按账号状态选择对应验证码类型，然后再次提交'
        if operation == 'enable':
            return 'ASF 拒绝 Bot 配置：核对 Steam 登录名与 Bot 配置内容；若刚创建 Bot，可重启 ASF 再尝试'
        if operation == 'start':
            return 'ASF 拒绝启动 Bot：确认 Bot 已启用且已被 ASF 加载；必要时重启 ASF 后刷新'
        if operation == 'stop':
            return 'ASF 拒绝停止 Bot：确认 Bot 已被 ASF 加载且正在运行'
        if operation == 'status':
            return 'ASF 未识别该 Bot：刚创建/启用 Bot 时可重启 ASF，再刷新账号状态'
        return 'ASF 拒绝请求：请先检查 Bot 配置和 ASF 运行状态'
    if status >= 500:
        return 'ASF 内部服务异常，请检查本地 ASF 日志（不要分享包含账号凭据的完整日志）'
    return 'ASF 拒绝了此次操作，请核对账号状态'


class EmbeddedUI:
    def __init__(self, manager):
        self.manager = manager

    async def _api(self, method, path, *, body=None, operation='operation'):
        if not self.manager.running():
            raise ValueError('ASF 尚未启动，请先点击「启动 ASF」')
        url, _, password = self.manager.ipc()
        if url != 'http://127.0.0.1:1242':
            raise ValueError('ASF IPC 必须是受信任的本地地址')
        if not password:
            raise ValueError('ASF IPC 未配置认证密码，拒绝透传管理请求')
        timeout = aiohttp.ClientTimeout(total=15)
        try:
            async with aiohttp.ClientSession(timeout=timeout, headers={'Authentication': password}) as session:
                async with session.request(method, url + path, json=body, allow_redirects=False) as response:
                    # Cap incoming JSON so a misconfigured service cannot return unbounded data.
                    raw = await response.content.read(65537)
                    if len(raw) > 65536:
                        raise ValueError('ASF 返回内容超过管理界面安全上限')
                    try:
                        payload = json.loads(raw) if raw else None
                    except (UnicodeError, ValueError):
                        payload = None
                    if response.status != 200:
                        hint = _safe_api_hint(response.status, operation, payload)
                        raise ValueError(f'ASF {operation} 请求失败（HTTP {response.status}）：{hint}')
        except (aiohttp.ClientError, TimeoutError) as exc:
            raise ValueError(f'ASF 本地 IPC 连接失败（{type(exc).__name__}）') from exc
        if not isinstance(payload, dict) or payload.get('Success') is not True:
            hint = _safe_api_hint(400, operation, payload)
            raise ValueError(f'ASF {operation} 操作未成功：{hint}')
        return payload

    async def status(self):
        try:
            local = local_bot_view(self.manager)
        except ValueError as exc:
            return {'available': False, 'message': str(exc), 'running': self.manager.running()}
        local.update({'running': self.manager.running(), 'connected': False,
                      'required_input': '', 'steam_id_present': False,
                      'loaded': False})
        if not self.manager.running() or not local['configured']:
            return local
        bot = local['bot_name']
        try:
            raw = await self._api('GET', '/Api/Bot/' + bot, operation='status')
            obj = (raw.get('Result') or {}).get(bot) if isinstance(raw.get('Result'), dict) else None
            if isinstance(obj, dict):
                local['loaded'] = True
                local['connected'] = obj.get('IsConnectedAndLoggedOn') is True
                required = obj.get('RequiredInput')
                if isinstance(required, str) and required in INPUT_TYPES:
                    local['required_input'] = required
                elif type(required) is int and required in INPUT_TYPES_BY_ID:
                    local['required_input'] = INPUT_TYPES_BY_ID[required]
                local['steam_id_present'] = bool(obj.get('SteamID'))
            else:
                local['status_note'] = 'ASF 没有返回此 Bot，可能尚未加载。可重启 ASF 并刷新。'
        except ValueError as exc:
            local['status_note'] = str(exc)  # Sanitized by _safe_api_hint; no raw ASF response.
        return local

    async def set_enabled(self, enabled):
        if type(enabled) is not bool:
            raise ValueError('启用状态必须是布尔值')
        path = config_file(self.manager)
        if not path.is_file():
            raise ValueError('请先在面板创建 Bot 配置')
        try:
            cfg = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError) as exc:
            raise ValueError('本地 Bot 配置无法读取或格式错误') from exc
        if not isinstance(cfg, dict):
            raise ValueError('Bot 配置不是 JSON 对象')
        if enabled and not cfg.get('SteamLogin'):
            raise ValueError('Bot 尚未配置 Steam 登录名，请先创建账号配置')
        cfg['Enabled'] = enabled
        bot = chosen_bot(self.manager)
        await self._api('POST', '/Api/Bot/' + bot, body={'BotConfig': cfg}, operation='enable')
        return {'ok': True, 'notice': 'Bot 配置已提交。若状态未变化，请重启 ASF 后刷新。' if enabled else 'Bot 停用请求已提交'}

    async def control(self, action):
        if action not in ('Start', 'Stop'):
            raise ValueError('只允许启动或停止当前 Bot')
        bot = chosen_bot(self.manager)
        await self._api('POST', f'/Api/Bot/{bot}/{action}', operation=action.lower())
        return {'ok': True, 'notice': 'Bot 启动命令已提交' if action == 'Start' else 'Bot 停止命令已提交'}

    async def input_secret(self, kind, value):
        if not isinstance(kind, str) or kind not in INPUT_TYPE_IDS:
            raise ValueError('不支持这种身份验证输入')
        if type(value) is not str or not value or len(value) > 128 or any(ord(c) < 32 for c in value):
            raise ValueError('输入必须是 1–128 位且不能包含控制字符')
        if kind == 'DeviceConfirmation' and value.upper() not in ('Y', 'N'):
            raise ValueError('Steam App 登录确认只能输入 Y（已批准）或 N（改用验证码）')
        bot = chosen_bot(self.manager)
        # Numeric EUserInputType avoids the ASP.NET enum-JSON 400 on some ASF builds.
        await self._api('POST', f'/Api/Bot/{bot}/Input',
                        body={'Type': INPUT_TYPE_IDS[kind], 'Value': value}, operation='input')
        return {'ok': True, 'notice': '验证信息已传递给 ASF（插件未保存）。请点击「启动 Bot」并刷新连接状态'}
