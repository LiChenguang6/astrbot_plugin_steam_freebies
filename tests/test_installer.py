import asyncio
import hashlib
import io
import zipfile

import aiohttp
import pytest
from yarl import URL

from steam_freebies.asf_release import PINNED_SHA256, PINNED_VERSION
from steam_freebies.manager import ManagedASF


def test_download_source_policies_and_config(tmp_path):
    manager = ManagedASF(tmp_path / 'asf')
    url = f'https://github.com/JustArchiNET/ArchiSteamFarm/releases/download/{PINNED_VERSION}/ASF-linux-x64.zip'
    names = lambda mode: [n for n, _ in manager.download_urls(url, mode)]
    assert names('auto') == ['GH-Proxy', 'GHProxy', 'GitHub 官方']
    assert names('mirror') == ['GH-Proxy', 'GHProxy']
    assert names('official') == ['GitHub 官方']
    assert manager.settings()['download_mode'] == 'auto'
    assert manager.save_settings({'download_mode': 'mirror'})['download_mode'] == 'mirror'
    assert ManagedASF(tmp_path / 'asf').settings()['download_mode'] == 'mirror'
    for broken in ('https://evil.invalid/foo', 'http://github.com/JustArchiNET/ArchiSteamFarm/releases/download/1/a.zip'):
        with pytest.raises(ValueError): manager.download_urls(broken, 'auto')
    with pytest.raises(ValueError): manager.save_settings({'download_mode': 'https://internal/evil'})


def test_release_metadata_validation(tmp_path):
    manager = ManagedASF(tmp_path / 'asf')
    name = 'ASF-linux-x64.zip'
    version = PINNED_VERSION
    url = f'https://github.com/JustArchiNET/ArchiSteamFarm/releases/download/{version}/{name}'
    release = {'tag_name': version, 'draft': False, 'prerelease': False, 'assets': [
        {'name': name, 'browser_download_url': url, 'digest': 'sha256:' + PINNED_SHA256[name], 'size': 19_000_000}]}
    assert manager.official_asset(release, name) == (version, url, PINNED_SHA256[name], 19_000_000)
    release['assets'][0]['browser_download_url'] = 'https://evil.invalid/download.zip'
    with pytest.raises(ValueError): manager.official_asset(release, name)
    release['assets'][0]['browser_download_url'] = url
    release['assets'][0]['digest'] = 'sha256:not-a-valid-hash'
    with pytest.raises(ValueError): manager.official_asset(release, name)


class AsyncResponse:
    def __init__(self, url, payload, content_type='application/zip'):
        self.url = URL(url)
        self.headers = {'Content-Length': str(len(payload)), 'Content-Type': content_type}
        self.content = self
        self.payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def raise_for_status(self):
        return None

    async def iter_chunked(self, size):
        yield self.payload


class OfflineMetadataSession:
    def get(self, url, **kwargs):
        raise aiohttp.ClientError('network blocked')


def test_pinned_fallback_when_github_api_blocked(tmp_path):
    manager = ManagedASF(tmp_path / 'asf')
    value = asyncio.run(manager._release_metadata(OfflineMetadataSession(), 'ASF-linux-x64.zip'))
    assert value[0] == PINNED_VERSION
    assert value[2] == PINNED_SHA256['ASF-linux-x64.zip']
    assert '固定官方校验' in manager.metadata_source


def test_mirror_corruption_auto_switch_to_official(tmp_path):
    archive = b'good official zip bytes'
    digest = hashlib.sha256(archive).hexdigest()
    url = f'https://github.com/JustArchiNET/ArchiSteamFarm/releases/download/{PINNED_VERSION}/ASF-linux-x64.zip'
    urls = ManagedASF.download_urls(url, 'auto')

    class Session:
        def __init__(self):
            self.visited = []

        def get(self, address, **kwargs):
            self.visited.append(address)
            return AsyncResponse(address, b'bad data' if len(self.visited) < 3 else archive)

    manager = ManagedASF(tmp_path / 'asf')
    session = Session()
    got = asyncio.run(manager._download_verified(session, url, digest, len(archive), 'auto'))
    assert got == archive
    assert len(session.visited) == 3
    assert manager.download_source == 'GitHub 官方'
    assert manager.download_bytes == len(archive)


def test_all_sources_with_wrong_hash_are_rejected(tmp_path):
    manager = ManagedASF(tmp_path / 'asf')
    url = f'https://github.com/JustArchiNET/ArchiSteamFarm/releases/download/{PINNED_VERSION}/ASF-linux-x64.zip'

    class Session:
        def get(self, address, **kwargs):
            return AsyncResponse(address, b'mirror sent unverified binary')

    with pytest.raises(RuntimeError, match='所有下载源均失败'):
        asyncio.run(manager._download_verified(Session(), url, 'a' * 64, 0, 'auto'))


def test_official_zip_only_extracted_after_validation(tmp_path):
    from steam_freebies.manager import verify_and_extract
    mem = io.BytesIO()
    with zipfile.ZipFile(mem, 'w') as z:
        z.writestr('ArchiSteamFarm', 'dummy executable')
        z.writestr('config/example.txt', 'file')
    payload = mem.getvalue()
    check = hashlib.sha256(payload).hexdigest()
    exe = verify_and_extract(payload, check, tmp_path / 'install')
    assert exe.is_file()
    assert (tmp_path / 'install' / 'config' / 'example.txt').exists()
