"""B站扫码申请与 AstrBot HTTP 网关的异步化回归测试。"""
import asyncio
import time
from urllib.parse import urlsplit, parse_qs

import pytest

from steam_freebies.bili_auth import BiliAuth, _safe_scan_url


def test_safe_url_uses_only_unmodified_official_domain_and_the_supplied_key():
    key = 'f' * 32
    good = f'https://passport.bilibili.com/h5-app/passport/login/scan?navhide=1&qrcode_key={key}&from='
    assert _safe_scan_url(good, key) == good
    # An unexpected/modified URL must fail closed rather than be silently replaced.
    for link in ('https://attacker.com/?qrcode_key='+key,
                 'http://passport.bilibili.com/h5-app/passport/login/scan?qrcode_key='+key,
                 'https://passport.bilibili.com.evil.com',
                 'https://passport.bilibili.com:8080/h5-app/passport/login/scan?qrcode_key='+key,
                 f'https://passport.bilibili.com/h5-app/passport/login/scan?qrcode_key=wrong',
                 f'https://passport.bilibili.com/h5-app/passport/login/scan?navhide=1',
                 f'https://passport.bilibili.com/h5-app/passport/login/scan?qrcode_key={key}&qrcode_key={key}',
                 f'https://passport.bilibili.com/anyotherpath?qrcode_key={key}',
                 '', None):
        with pytest.raises(ValueError):
            _safe_scan_url(link, key)


def test_scan_preparation_returns_instantly_before_network_finishes(tmp_path,monkeypatch):
    auth=BiliAuth(tmp_path)
    async def scenario():
        event=asyncio.Event()
        async def pretend_qr_start():
            await event.wait()
            auth._qr_started=time.monotonic()
            return {'matrix':['0'*29 for _ in range(29)],'ok':True}
        monkeypatch.setattr(auth,'qr_start',pretend_qr_start)
        assert auth.qr_begin()['state']=='preparing'
        assert auth.qr_prepare_status()['state']=='preparing'
        event.set()
        await auth._qr_prepare_task
        result=auth.qr_prepare_status()
        assert result['state']=='ready' and result['ok']
        assert 'key' not in result
        auth.cancel_qr_preparation()
        assert auth.qr_prepare_status()['state']=='idle'
    asyncio.run(scenario())


def test_scan_preparation_shows_safe_failure_without_qr(tmp_path,monkeypatch):
    auth=BiliAuth(tmp_path)
    async def scenario():
        async def rejected():
            raise ValueError('B站二维码接口成功，但未发放有效扫码密钥（URL：有，密钥：无）')
        monkeypatch.setattr(auth,'qr_start',rejected)
        auth.qr_begin()
        await auth._qr_prepare_task
        info=auth.qr_prepare_status()
        assert info['state']=='failed' and '密钥' in info['notice']
        assert 'matrix' not in info
    asyncio.run(scenario())


def test_cancelled_preparation_never_produces_qr(tmp_path,monkeypatch):
    auth=BiliAuth(tmp_path)
    async def scenario():
        async def slow():
            await asyncio.sleep(1000)
        monkeypatch.setattr(auth,'qr_start',slow)
        auth.qr_begin()
        await asyncio.sleep(0)
        auth.logout()
        await asyncio.sleep(0)
        assert auth.qr_prepare_status()['state']=='idle'
        assert auth._qr_key == ''
    asyncio.run(scenario())
