"""Known-good ASF release metadata copied from the official GitHub release API.

This is a *fallback* when GitHub API itself is unreachable, not an unchecked
mirror manifest. Update only using official JustArchiNET release metadata.
See: https://api.github.com/repos/JustArchiNET/ArchiSteamFarm/releases/latest
"""

PINNED_VERSION = '6.3.10.6'
PINNED_SHA256 = {
    'ASF-linux-x64.zip': '2db476c63ca340e6990aa0d6d39cee2c5a0fa7efaa47cd099d1c0c63651de6bc',
    'ASF-linux-arm64.zip': '14de17f62615e8a8f28d9bde462aa401cc04c56a8808f0a7d4e76be07fc3832a',
    'ASF-win-x64.zip': '2f620f48a8a0fd35f16f0b190be4f03e1b8a46cb7a81a463a6156762fabc6295',
    'ASF-win-arm64.zip': 'ca4977c2c16043074cf5b2c86c1d84f446ce159c9f84f5a50f8fb7baae1a9c16',
    'ASF-osx-x64.zip': '0041dfac9d4ade7b451f54971128a573165375e3caff2a8cd9ce621464f58fe6',
    'ASF-osx-arm64.zip': 'c6e23e5a31f7ee1691db35533dd10e9761f43c456ebc6fb83d4001e736cb11bd',
}

# These third-party HTTPS download relays have no trust of their own:
# every returned archive must match a SHA256 from GitHub metadata or PINNED_SHA256.
# Their uptime, speed and data handling are not guaranteed.
DOWNLOAD_RELAYS = (
    ('GH-Proxy', 'https://gh-proxy.org/'),
    ('GHProxy', 'https://ghproxy.net/'),
)
