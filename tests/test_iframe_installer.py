"""v0.3.1 regression tests for AstrBot sandboxed plugin views and NAS install state."""
from pathlib import Path
import json

import pytest

from steam_freebies.manager import ManagedASF

ROOT = Path(__file__).resolve().parents[1]


def test_plugin_view_never_depends_on_browser_modals():
    js = (ROOT / 'views/steam-freebies/app.js').read_text(encoding='utf-8')
    assert 'window.confirm(' not in js
    assert 'window.prompt(' not in js
    assert 'if(confirm(' not in js
    assert "apiPost('asf/install',{})" in js
    assert "$('install-asf').addEventListener('click',installASF)" in js
    html = (ROOT / 'views/steam-freebies/index.html').read_text(encoding='utf-8')
    assert 'id="asf-operation"' in html
    assert 'id="action-overlay"' in html


def test_install_error_persists_across_plugin_reload(tmp_path):
    a = ManagedASF(tmp_path / 'runtime')
    a.install_state = 'error'
    a.last_error = 'Download timeout while using mirror'
    a._write_install_state()
    b = ManagedASF(tmp_path / 'runtime')
    assert b.status()['install_state'] == 'error'
    assert 'Download timeout' in b.status()['error']
    assert 'IPCPassword' not in (tmp_path / 'runtime' / 'install-state.json').read_text()


def test_install_preflight_reports_synology_storage_problem(tmp_path, monkeypatch):
    m = ManagedASF(tmp_path / 'asf')
    monkeypatch.setattr(m, 'environment', lambda: {'container': True, 'writable': False, 'free_mb': 900})
    with pytest.raises(ValueError, match='群晖 Container Manager'):
        m.install()
    monkeypatch.setattr(m, 'environment', lambda: {'container': True, 'writable': True, 'free_mb': 150})
    with pytest.raises(ValueError, match='350 MB'):
        m.install()


def test_interrupted_install_is_visible_on_reload(tmp_path):
    m = ManagedASF(tmp_path / 'asf')
    m.install_state = 'downloading'
    m._write_install_state()
    assert ManagedASF(tmp_path / 'asf').status()['install_state'] == 'interrupted'
