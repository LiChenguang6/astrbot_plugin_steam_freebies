import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from steam_freebies.sources import parse_gamerpower, parse_steam_html
from steam_freebies.store import Store


def test_parser_only_100_percent():
    html = '''<a class="search_result_row" href="https://store.steampowered.com/app/123/Test">
      <span class="title">A Game</span><span class="discount_pct">-100%</span>
      <span class="discount_original_price">¥ 49</span></a>
      <a class="search_result_row" href="https://store.steampowered.com/app/456/Test">
      <span class="title">Another</span><span class="discount_pct">-50%</span></a>'''
    rows = parse_steam_html(html)
    assert len(rows) == 1
    assert rows[0]["appid"] == 123
    assert rows[0]["kind"] == "steam_candidate"


def test_gamerpower_key_not_auto_claim():
    rows = parse_gamerpower([{"id": 11, "title": "Free Key", "open_giveaway_url": "https://www.gamerpower.com/open/11"}])
    assert len(rows) == 1 and rows[0]["kind"] == "third_party"


def test_store_approval_dedup(tmp_path):
    db = Store(tmp_path / "test.db")
    db.upsert_games([dict(key="steam:1",name="Some game",source="Steam",kind="steam_candidate",appid=1,url="https://store.steampowered.com/app/1",original_price="",end_date="",confidence="")])
    db.bind(platform_id="p",bot_id="b",group_id="g",session="s",official=False)
    group = db.targets()[0]
    assert len(db.pending_pushes(group["id"])) == 1
    db.marked(group["id"], "steam:1")
    assert db.pending_pushes(group["id"]) == []
    try:
        db.approve("steam:1", "123")
    except ValueError:
        pass
    else:
        assert False, "SubID must be integer"
    db.approve("steam:1", 123)
    assert len(db.pending_claims()) == 1
    db.claim_record("steam:1",123,"submitted","test")
    assert db.pending_claims() == []
    db.db.close()


def test_settings_validate(tmp_path):
    db=Store(tmp_path / "x.sqlite")
    try:
        db.update_settings({"scan_minutes": 2})
    except ValueError:
        pass
    else:
        assert False
    assert db.settings()["auto_claim_enabled"] is False
    db.db.close()
