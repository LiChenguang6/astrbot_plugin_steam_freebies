"""Steam-only transport: explicit HTTP proxy or container HTTPS_PROXY + bounded retries.

No third-party Steam API mirrors or disabling TLS validation. A proxy URL is
administrator-controlled and may observe destination hostnames; never accept
proxy credentials through the dashboard.
"""
import asyncio
import os
from urllib.parse import urlsplit

import aiohttp


def validate_proxy_url(value):
    if value == '':
        return ''
    if type(value) is not str or len(value) > 220:
        raise ValueError('Steam HTTP 代理地址不合法')
    try:
        url = urlsplit(value)
        port = url.port
    except ValueError as exc:
        raise ValueError('Steam HTTP 代理地址不合法') from exc
    if (url.scheme != 'http' or not url.hostname or not port or
        url.username or url.password or url.path not in ('', '/') or url.query or url.fragment):
        raise ValueError('仅支持 http://主机:端口 的 HTTP 代理，不允许账号密码、路径或查询参数')
    return value.rstrip('/')


class SteamNetwork:
    def __init__(self, settings=None):
        settings = settings or {}
        self.mode = settings.get('steam_proxy_mode', 'auto')
        self.proxy = validate_proxy_url(settings.get('steam_proxy_url', ''))
        if self.mode not in ('auto', 'direct', 'proxy'):
            raise ValueError('Steam 加速模式无效')
        if self.mode == 'proxy' and not self.proxy:
            raise ValueError('强制代理模式必须先设置代理地址')

    def options(self):
        if self.mode == 'direct':
            return {'trust_env': False, 'proxy': None}
        if self.proxy:
            return {'trust_env': False, 'proxy': self.proxy}
        return {'trust_env': self.mode == 'auto', 'proxy': None}

    def session(self, *, timeout=14):
        opts = self.options()
        return aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=timeout), trust_env=opts['trust_env'],
            headers={'User-Agent':'Mozilla/5.0 AstrBot-Steam-Freebies/0.6.1'})

    async def get_json(self, session, url, *, params=None, timeout=12, attempts=2):
        if not url.startswith('https://store.steampowered.com/'):
            raise ValueError('Steam 加速仅允许访问固定 Steam 商店域名')
        opts = self.options()
        failure = None
        for attempt in range(attempts):
            try:
                kwargs = {'params': params, 'timeout':aiohttp.ClientTimeout(total=timeout)}
                if opts['proxy']:
                    kwargs['proxy'] = opts['proxy']
                async with session.get(url, **kwargs) as response:
                    response.raise_for_status()
                    return await response.json(content_type=None)
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, TypeError) as exc:
                failure = exc
                if attempt + 1 < attempts:
                    await asyncio.sleep(.5)
        raise failure


def proxy_status(settings):
    cfg = SteamNetwork(settings)
    options = cfg.options()
    return {'mode':cfg.mode, 'configured':bool(cfg.proxy),
            'active': bool(cfg.proxy) or (options['trust_env'] and bool(os.environ.get('HTTPS_PROXY') or os.environ.get('https_proxy'))),
            'via':'指定 HTTP 代理' if cfg.proxy else '容器 HTTPS_PROXY' if options['trust_env'] and (os.environ.get('HTTPS_PROXY') or os.environ.get('https_proxy')) else '直连'}
