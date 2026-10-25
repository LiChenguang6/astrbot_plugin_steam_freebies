"""SQLite state. Claim attempts are recorded without asserting license success."""
import json
import sqlite3
from datetime import datetime, timezone


def utcnow():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


DEFAULT_SETTINGS = {"scan_minutes": 60, "push_enabled": True, "auto_claim_enabled": False}


class Store:
    def __init__(self, filename):
        filename.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(filename), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY, v TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS targets(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          platform_id TEXT NOT NULL, bot_id TEXT NOT NULL, group_id TEXT NOT NULL,
          session TEXT NOT NULL, official INTEGER NOT NULL DEFAULT 0,
          enabled INTEGER NOT NULL DEFAULT 1,
          UNIQUE(platform_id, bot_id, group_id)
        );
        CREATE TABLE IF NOT EXISTS games(
          key TEXT PRIMARY KEY, name TEXT NOT NULL, source TEXT NOT NULL,
          kind TEXT NOT NULL, appid INTEGER NOT NULL, url TEXT NOT NULL,
          original_price TEXT, end_date TEXT, confidence TEXT,
          first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
          approved_subid INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS sent(
          target_id INTEGER NOT NULL, game_key TEXT NOT NULL,
          sent_at TEXT NOT NULL, PRIMARY KEY(target_id, game_key)
        );
        CREATE TABLE IF NOT EXISTS claims(
          game_key TEXT PRIMARY KEY, subid INTEGER NOT NULL, at TEXT NOT NULL,
          status TEXT NOT NULL, result TEXT NOT NULL
        );
        """)
        self.db.commit()

    def settings(self):
        rows = self.db.execute("SELECT k,v FROM settings").fetchall()
        s = dict(DEFAULT_SETTINGS)
        for r in rows:
            if r["k"] in s:
                s[r["k"]] = json.loads(r["v"])
        return s

    def update_settings(self, values):
        if not isinstance(values, dict):
            raise ValueError("设置必须是 JSON 对象")
        permitted = set(DEFAULT_SETTINGS)
        if set(values) - permitted:
            raise ValueError("存在不支持的设置字段")
        if "scan_minutes" in values and (type(values["scan_minutes"]) is not int or not 30 <= values["scan_minutes"] <= 360):
            raise ValueError("扫描间隔须为 30–360 分钟")
        for k in ("push_enabled", "auto_claim_enabled"):
            if k in values and type(values[k]) is not bool:
                raise ValueError(f"{k} 必须是布尔值")
        with self.db:
            for k, v in values.items():
                self.db.execute("INSERT INTO settings(k,v) VALUES (?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, json.dumps(v)))
        return self.settings()

    def bind(self, *, platform_id, bot_id, group_id, session, official):
        with self.db:
            self.db.execute("""INSERT INTO targets(platform_id,bot_id,group_id,session,official,enabled)
                 VALUES (?,?,?,?,?,1) ON CONFLICT(platform_id,bot_id,group_id)
                 DO UPDATE SET session=excluded.session, official=excluded.official,enabled=1""",
                 (str(platform_id), str(bot_id), str(group_id), str(session), int(official)))

    def disable_target(self, *, platform_id, bot_id, group_id):
        with self.db:
            self.db.execute("UPDATE targets SET enabled=0 WHERE platform_id=? AND bot_id=? AND group_id=?",
                            (str(platform_id), str(bot_id), str(group_id)))

    def targets(self):
        return [dict(r) for r in self.db.execute("SELECT * FROM targets ORDER BY id")]

    def games(self, limit=150):
        return [dict(r) for r in self.db.execute("SELECT g.*,c.status AS claim_status,c.result AS claim_result FROM games g LEFT JOIN claims c ON c.game_key=g.key ORDER BY g.last_seen DESC LIMIT ?", (limit,))]

    def upsert_games(self, games):
        added = 0
        now = utcnow()
        with self.db:
            for g in games:
                if not g.get("key") or not g.get("name"):
                    continue
                cursor = self.db.execute("""
                  INSERT INTO games(key,name,source,kind,appid,url,original_price,end_date,confidence,first_seen,last_seen)
                  VALUES (?,?,?,?,?,?,?,?,?,?,?)
                  ON CONFLICT(key) DO UPDATE SET name=excluded.name,url=excluded.url,
                    original_price=excluded.original_price,end_date=excluded.end_date,
                    confidence=excluded.confidence,last_seen=excluded.last_seen
                  """, (g["key"],g["name"],g["source"],g["kind"],int(g.get("appid") or 0),g["url"],
                          g.get("original_price",""),g.get("end_date",""),g.get("confidence",""),now,now))
                added += int(cursor.rowcount > 0)  # SQL upsert count, not "new" count
        return added

    def approve(self, key, subid):
        game = self.db.execute("SELECT * FROM games WHERE key=?", (key,)).fetchone()
        if not game:
            raise ValueError("活动不存在")
        if game["kind"] != "steam_candidate":
            raise ValueError("第三方赠送活动不允许直接调用 Steam addlicense")
        if type(subid) is not int or not 1 <= subid <= 2_147_483_647:
            raise ValueError("请填写正确的免费领取包 SubID")
        with self.db:
            self.db.execute("UPDATE games SET approved_subid=? WHERE key=?", (subid, key))
            # A different approved package must be allowed to run even if an earlier attempt exists.
            self.db.execute("DELETE FROM claims WHERE game_key=? AND subid<>?", (key, subid))

    def pending_pushes(self, target_id, max_rows=10):
        return [dict(r) for r in self.db.execute("""
         SELECT g.* FROM games g LEFT JOIN sent s ON s.game_key=g.key AND s.target_id=?
         WHERE s.game_key IS NULL AND g.last_seen>=datetime('now','-14 days')
         ORDER BY g.first_seen DESC LIMIT ?""", (target_id,max_rows))]

    def marked(self, target_id, key):
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO sent VALUES (?,?,?)", (target_id,key,utcnow()))

    def pending_claims(self):
        return [dict(r) for r in self.db.execute("""
          SELECT g.* FROM games g LEFT JOIN claims c ON c.game_key=g.key
          WHERE g.kind='steam_candidate' AND g.approved_subid>0 AND c.game_key IS NULL
          ORDER BY g.first_seen ASC LIMIT 5""")]

    def claim_record(self, key, subid, status, result):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO claims VALUES (?,?,?,?,?)", (key,subid,utcnow(),status,result[:700]))

    def get_game(self, key):
        row = self.db.execute("SELECT * FROM games WHERE key=?", (key,)).fetchone()
        return dict(row) if row else None
