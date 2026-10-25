"""SQLite state. Claim attempts are recorded without asserting license success."""
import json
import sqlite3
from datetime import datetime, timezone


def utcnow():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


DEFAULT_SETTINGS = {
    "scan_minutes": 60,
    "push_enabled": True,
    "push_steam": True,
    "push_third_party": True,
    "push_claim_results": True,
    "auto_claim_enabled": False,
    "price_monitor_enabled": True,
    "push_paid_to_free": True,
    "push_watch_prices": True,
    "bili_enabled": False,
    "push_bilibili": False,
    "bili_discovery_mode": "creators",  # creators, search, both
    "bili_push_creators": True,
    "bili_push_search_verified": False,  # strict multi-source gate; opt in
    "bili_auto_claim_creators": False,  # legacy approved SubID path
    "bili_unattended_claim": False,  # opt-in: free games from subscribed UP -> app/<AppID>

    "bili_keywords": "Steam 喜加一,Steam 永久免费,Steam 限时免费",
    "bili_ai_enabled": False,
    "bili_ai_calls": 2,
    "steam_proxy_mode": "auto",
    "steam_proxy_url": "",
    "steam_search_fallback": False,
}


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
          approved_subid INTEGER NOT NULL DEFAULT 0,
          steam_url TEXT NOT NULL DEFAULT '', bili_source_url TEXT NOT NULL DEFAULT '',
          steam_state TEXT NOT NULL DEFAULT '',
          bili_origin TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS auto_claims(
          game_key TEXT PRIMARY KEY, appid INTEGER NOT NULL, license_type TEXT NOT NULL,
          license_id INTEGER NOT NULL, at TEXT NOT NULL, status TEXT NOT NULL,
          result TEXT NOT NULL, ai_note TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS auto_claim_review_sent(
          target_id INTEGER NOT NULL, game_key TEXT NOT NULL, at TEXT NOT NULL,
          PRIMARY KEY(target_id,game_key)
        );
        CREATE TABLE IF NOT EXISTS sent(
          target_id INTEGER NOT NULL, game_key TEXT NOT NULL,
          sent_at TEXT NOT NULL, PRIMARY KEY(target_id, game_key)
        );
        CREATE TABLE IF NOT EXISTS claims(
          game_key TEXT PRIMARY KEY, subid INTEGER NOT NULL, at TEXT NOT NULL,
          status TEXT NOT NULL, result TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS claim_events(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          game_key TEXT NOT NULL, subid INTEGER NOT NULL,
          at TEXT NOT NULL, status TEXT NOT NULL, result TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS claim_event_sent(
          target_id INTEGER NOT NULL, event_id INTEGER NOT NULL,
          sent_at TEXT NOT NULL, PRIMARY KEY(target_id,event_id)
        );
        CREATE TABLE IF NOT EXISTS price_watch(
          appid INTEGER PRIMARY KEY, name TEXT NOT NULL DEFAULT '',
          state TEXT NOT NULL DEFAULT 'unknown', amount INTEGER NOT NULL DEFAULT 0,
          currency TEXT NOT NULL DEFAULT '', first_seen TEXT NOT NULL,
          last_checked TEXT NOT NULL DEFAULT '', last_paid_at TEXT NOT NULL DEFAULT '',
          manual INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS price_watch_checked ON price_watch(last_checked);
        CREATE TABLE IF NOT EXISTS price_history(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          appid INTEGER NOT NULL, seen_at TEXT NOT NULL,
          state TEXT NOT NULL, amount INTEGER NOT NULL, currency TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS bili_creators(
          mid INTEGER PRIMARY KEY, name TEXT NOT NULL DEFAULT '', added_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS bili_seen(
          bvid TEXT PRIMARY KEY, seen_at TEXT NOT NULL
        );
        """)
        # Non-destructive schema upgrade on existing NAS SQLite files.
        columns={r[1] for r in self.db.execute('PRAGMA table_info(games)')}
        for name in ('steam_url','bili_source_url','bili_origin','steam_state'):
            if name not in columns:
                self.db.execute(f"ALTER TABLE games ADD COLUMN {name} TEXT NOT NULL DEFAULT ''")
        # Interrupted in-flight claims are reviewable after a restart, never automatically resent.
        with self.db:
            self.db.execute("""UPDATE auto_claims SET status='failed',
                result='上一次 ASF 请求中断，无法确认是否获得许可；请检查账户后再手动重试'
                WHERE status='checking'""")
        # v0.6 migration: old auto-sampled rows must not remain in the watchlist.
        # Manual watches and their price history are preserved.
        with self.db:
            self.db.execute('DELETE FROM price_watch WHERE manual=0')
            self.db.execute('DELETE FROM price_history WHERE appid NOT IN (SELECT appid FROM price_watch)')

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
        for k in ("push_enabled", "push_steam", "push_third_party", "push_claim_results", "auto_claim_enabled", "price_monitor_enabled", "push_paid_to_free",
                  "push_watch_prices", "bili_enabled", "push_bilibili", "bili_push_creators", "bili_push_search_verified", "bili_auto_claim_creators", "bili_unattended_claim", "bili_ai_enabled", "steam_search_fallback"):
            if k in values and type(values[k]) is not bool:
                raise ValueError(f"{k} 必须是布尔值")
        if 'bili_discovery_mode' in values and values['bili_discovery_mode'] not in ('creators','search','both'):
            raise ValueError('请选择指定 UP 主、搜索或两者同时监控')
        if 'steam_proxy_mode' in values and values['steam_proxy_mode'] not in ('auto','direct','proxy'):
            raise ValueError('Steam 加速模式无效')
        if 'steam_proxy_url' in values:
            from .steam_network import validate_proxy_url
            validate_proxy_url(values['steam_proxy_url'])
        proposed = {**self.settings(), **values}
        if proposed['steam_proxy_mode'] == 'proxy' and not proposed['steam_proxy_url']:
            raise ValueError('请先输入 Steam HTTP 代理地址')
        if 'bili_ai_calls' in values and (type(values['bili_ai_calls']) is not int or values['bili_ai_calls'] not in (0, 1, 2, 3)):
            raise ValueError('AI 每轮调用数仅允许 0–3')
        if 'bili_keywords' in values:
            import re
            words = values['bili_keywords']
            if type(words) is not str or len(words) > 140 or not words.strip() or len([x for x in re.split('[,，\n]', words) if x.strip()]) > 5:
                raise ValueError('B站关键词总长度最多 140 字，1–5 个词')
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
                  INSERT INTO games(key,name,source,kind,appid,url,original_price,end_date,confidence,first_seen,last_seen,steam_url,bili_source_url,bili_origin,steam_state)
                  VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                  ON CONFLICT(key) DO UPDATE SET name=excluded.name,url=excluded.url,
                    original_price=excluded.original_price,end_date=excluded.end_date,
                    confidence=excluded.confidence,last_seen=excluded.last_seen,
                    steam_url=excluded.steam_url,bili_source_url=excluded.bili_source_url,
                    bili_origin=excluded.bili_origin,steam_state=excluded.steam_state
                  """, (g["key"],g["name"],g["source"],g["kind"],int(g.get("appid") or 0),g["url"],
                          g.get("original_price",""),g.get("end_date",""),g.get("confidence",""),now,now,
                          g.get('steam_url',''),g.get('bili_source_url',''),g.get('bili_origin',''),g.get('steam_state','')))
                added += int(cursor.rowcount > 0)  # SQL upsert count, not "new" count
        return added

    def approve(self, key, subid):
        game = self.db.execute("SELECT * FROM games WHERE key=?", (key,)).fetchone()
        if not game:
            raise ValueError("活动不存在")
        trusted_bili = (game['kind'] == 'bilibili_tip' and game['bili_origin'] == 'creator'
                        and game['steam_url'] == f'https://store.steampowered.com/app/{game["appid"]}/')
        if game['kind'] != 'steam_candidate' and not trusted_bili:
            raise ValueError('仅 Steam 官方候选或你订阅 UP 的 Steam 已核查游戏可批准 SubID')
        if type(subid) is not int or not 1 <= subid <= 2_147_483_647:
            raise ValueError("请填写正确的免费领取包 SubID")
        with self.db:
            self.db.execute("UPDATE games SET approved_subid=? WHERE key=?", (subid, key))
            # A different approved package must be allowed to run even if an earlier attempt exists.
            self.db.execute("DELETE FROM claims WHERE game_key=? AND subid<>?", (key, subid))

    def delivery_overview(self):
        now = utcnow()
        rows = self.db.execute("SELECT target_id,MAX(sent_at) last_sent FROM sent WHERE game_key NOT LIKE '__test__:%' GROUP BY target_id").fetchall()
        return {str(r["target_id"]):r["last_sent"] for r in rows}

    def pending_pushes(self, target_id, max_rows=10):
        opts=self.settings()
        if not opts['push_enabled']: return []
        # Old notifications are not replayed weeks later after a service recovery.
        query = """
         SELECT g.* FROM games g LEFT JOIN sent s ON s.game_key=g.key AND s.target_id=?
         WHERE s.game_key IS NULL AND g.last_seen>=?
           AND ((g.kind='steam_candidate' AND ?=1) OR (g.kind='third_party' AND ?=1) OR (g.kind='paid_to_free' AND ?=1) OR (g.kind='watch_price' AND ?=1) OR (g.kind='bilibili_tip' AND ?=1 AND ((g.bili_origin='creator' AND ?=1) OR (g.bili_origin='search' AND ?=1 AND (EXISTS (SELECT 1 FROM auto_claims ac WHERE ac.game_key=g.key AND ac.status='reported_success') OR EXISTS (SELECT 1 FROM claims c WHERE c.game_key=g.key AND c.status='reported_success'))))) OR (g.kind='promo_api' AND ?=1))
         ORDER BY g.first_seen DESC LIMIT ?"""
        from datetime import timedelta
        since=(datetime.now(timezone.utc)-timedelta(hours=48)).isoformat(timespec='seconds')
        return [dict(r) for r in self.db.execute(query, (target_id,since,int(opts['push_steam']),int(opts['push_third_party']),int(opts['push_paid_to_free']),int(opts['push_watch_prices']),int(opts['push_bilibili']),int(opts['bili_push_creators']),int(opts['bili_push_search_verified']),int(opts['push_steam']),max_rows))]

    def marked(self, target_id, key):
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO sent VALUES (?,?,?)", (target_id,key,utcnow()))

    def pending_claims(self):
        return [dict(r) for r in self.db.execute("""
          SELECT g.* FROM games g LEFT JOIN claims c ON c.game_key=g.key
          WHERE g.kind='steam_candidate' AND g.approved_subid>0 AND c.game_key IS NULL
          ORDER BY g.first_seen ASC LIMIT 5""")]

    def pending_bili_claims(self):
        """Only administrator-approved creator items, bounded to recent promotions."""
        from datetime import timedelta
        since=(datetime.now(timezone.utc)-timedelta(hours=48)).isoformat(timespec='seconds')
        return [dict(x) for x in self.db.execute("""SELECT g.* FROM games g
            LEFT JOIN claims c ON c.game_key=g.key AND c.subid=g.approved_subid
            WHERE g.kind='bilibili_tip' AND g.bili_origin='creator'
            AND g.approved_subid>0 AND g.last_seen>=? AND c.game_key IS NULL
            ORDER BY g.first_seen DESC LIMIT 3""", (since,))]

    def claim_record(self, key, subid, status, result):
        now=utcnow()
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO claims VALUES (?,?,?,?,?)", (key,subid,now,status,result[:700]))
            return self.db.execute("""INSERT INTO claim_events(game_key,subid,at,status,result)
                         VALUES (?,?,?,?,?)""",(key,subid,now,status,result[:700])).lastrowid

    def pending_claim_events(self, target_id, limit=20):
        return [dict(x) for x in self.db.execute("""
            SELECT e.*,g.name,g.url,g.steam_url,g.bili_source_url FROM claim_events e JOIN games g ON g.key=e.game_key
            LEFT JOIN claim_event_sent s ON s.event_id=e.id AND s.target_id=?
            WHERE s.event_id IS NULL AND e.at>=? ORDER BY e.id ASC LIMIT ?""",
            (target_id,(datetime.now(timezone.utc)-__import__('datetime').timedelta(days=2)).isoformat(timespec='seconds'),limit))]

    def mark_claim_event(self,target_id,event_id):
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO claim_event_sent VALUES (?,?,?)",(target_id,event_id,utcnow()))

    def latest_claim_events(self,limit=30):
        return [dict(x) for x in self.db.execute("""
            SELECT e.*,g.name FROM claim_events e JOIN games g ON g.key=e.game_key
            ORDER BY e.id DESC LIMIT ?""",(limit,))]

    def get_game(self, key):
        row = self.db.execute("SELECT * FROM games WHERE key=?", (key,)).fetchone()
        return dict(row) if row else None

    def auto_claim_record(self, key, appid, license_type, license_id, status, result):
        if status not in ('failed', 'submitted', 'reported_success', 'checking', 'handled'):
            raise ValueError('自动领取状态无效')
        if license_type not in ('app', 'sub') or type(license_id) is not int or license_id <= 0:
            raise ValueError('自动领取许可证参数无效')
        with self.db:
            self.db.execute("""INSERT INTO auto_claims(game_key,appid,license_type,license_id,at,status,result)
             VALUES(?,?,?,?,?,?,?) ON CONFLICT(game_key) DO UPDATE SET
             appid=excluded.appid,license_type=excluded.license_type,license_id=excluded.license_id,
             at=excluded.at,status=excluded.status,result=excluded.result,ai_note=''""",
             (key,appid,license_type,license_id,utcnow(),status,str(result)[:500]))

    def auto_claim_get(self, key):
        r=self.db.execute('SELECT * FROM auto_claims WHERE game_key=?',(key,)).fetchone()
        return dict(r) if r else None

    def auto_claim_pending(self, limit=6):
        from datetime import timedelta
        since=(datetime.now(timezone.utc)-timedelta(hours=48)).isoformat(timespec='seconds')
        return [dict(r) for r in self.db.execute("""SELECT g.* FROM games g LEFT JOIN auto_claims a ON a.game_key=g.key
          WHERE g.kind='bilibili_tip' AND g.bili_origin='creator' AND g.last_seen>=?
          AND g.appid>0 AND g.steam_url=('https://store.steampowered.com/app/' || g.appid || '/')
          AND g.steam_state IN ('free','sale_100') AND a.game_key IS NULL
          ORDER BY g.last_seen DESC LIMIT ?""",(since,limit))]

    def auto_claim_overview(self, limit=70):
        return [dict(r) for r in self.db.execute("""SELECT a.*,g.name,g.steam_url,g.bili_source_url,
          g.steam_state,g.approved_subid FROM auto_claims a JOIN games g ON g.key=a.game_key
          ORDER BY CASE WHEN a.status IN ('failed','submitted') THEN 0 ELSE 1 END,a.at DESC LIMIT ?""",(limit,))]

    def auto_claim_set_note(self, key, note):
        with self.db:
            self.db.execute('UPDATE auto_claims SET ai_note=? WHERE game_key=?',(str(note)[:500],key))

    def pending_auto_review_pushes(self, target_id, limit=5):
        if not self.settings()['push_claim_results']:
            return []
        return [dict(r) for r in self.db.execute("""SELECT a.*,g.name,g.steam_url,g.bili_source_url
            FROM auto_claims a JOIN games g ON g.key=a.game_key
            LEFT JOIN auto_claim_review_sent s ON s.target_id=? AND s.game_key=a.game_key
            WHERE a.status IN ('failed','submitted') AND s.game_key IS NULL
            ORDER BY a.at DESC LIMIT ?""",(target_id,limit))]

    def mark_auto_review_sent(self, target_id, key):
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO auto_claim_review_sent VALUES(?,?,?)',(target_id,key,utcnow()))

    def auto_claim_resolve(self, key):
        r=self.auto_claim_get(key)
        if not r or r['status'] not in ('failed','submitted'):
            raise ValueError('此项目无需人工接管')
        with self.db:
            self.db.execute("UPDATE auto_claims SET status='handled' WHERE game_key=?",(key,))
        return {'ok':True,'notice':'已标记为人工处理，历史仍保留'}

    def add_price_watch(self, appid):
        '''Manual watch adds a baseline, never sends a fake historical conversion.'''
        if type(appid) is not int or not 0 < appid <= 2_147_483_647:
            raise ValueError('请输入有效的 Steam 游戏 AppID')
        if self.db.execute('SELECT COUNT(*) FROM price_watch WHERE manual=1').fetchone()[0] >= 120 and not self.db.execute(
                'SELECT 1 FROM price_watch WHERE appid=?', (appid,)).fetchone():
            raise ValueError('监控池已达 500 个游戏上限')
        now = utcnow()
        with self.db:
            self.db.execute('''INSERT INTO price_watch(appid,name,first_seen,manual) VALUES(?,?,?,1)
                ON CONFLICT(appid) DO UPDATE SET manual=1''', (appid, f'Steam App {appid}', now))
        return {'appid': appid, 'notice': '已加入价格监控，首次扫描只建立基线，不误报历史转免费'}

    def remove_price_watch(self, appid):
        if type(appid) is not int or appid <= 0:
            raise ValueError('无效 AppID')
        with self.db:
            self.db.execute('DELETE FROM price_watch WHERE appid=? AND manual=1', (appid,))
            self.db.execute('DELETE FROM price_history WHERE appid=?', (appid,))
        return {'ok': True, 'notice': f'已移除 AppID {appid} 监控'}

    def price_watch_ids(self, limit=120, manual_only=False):
        return [r[0] for r in self.db.execute('''SELECT appid FROM price_watch
             WHERE (?=0 OR manual=1)
             ORDER BY manual DESC, last_checked ASC, appid ASC LIMIT ?''', (int(manual_only), limit))]

    def bili_creators(self):
        return [dict(row) for row in self.db.execute('SELECT * FROM bili_creators ORDER BY added_at DESC LIMIT 10')]

    def add_bili_creator(self, mid, name):
        if type(mid) is not int or not 0 < mid < 10**15:
            raise ValueError('UP 主 UID 无效')
        if type(name) is not str or len(name) > 80:
            raise ValueError('UP 主名称无效')
        if self.db.execute('SELECT COUNT(*) FROM bili_creators').fetchone()[0] >= 10 and not self.db.execute('SELECT 1 FROM bili_creators WHERE mid=?', (mid,)).fetchone():
            raise ValueError('最多关注 10 位 UP 主')
        with self.db:
            self.db.execute('INSERT INTO bili_creators(mid,name,added_at) VALUES (?,?,?) ON CONFLICT(mid) DO UPDATE SET name=excluded.name', (mid,name,utcnow()))
        return {'ok': True, 'notice': f'已添加 B站 UP 主 {name}（UID {mid}）'}

    def remove_bili_creator(self, mid):
        if type(mid) is not int or mid <= 0:
            raise ValueError('UP 主 UID 无效')
        with self.db:
            self.db.execute('DELETE FROM bili_creators WHERE mid=?', (mid,))
        return {'ok': True, 'notice': f'已移除 UP 主 {mid}'}

    def bili_seen(self, bvid):
        return self.db.execute('SELECT 1 FROM bili_seen WHERE bvid=?', (bvid,)).fetchone() is not None

    def mark_bili_seen(self, bvid):
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO bili_seen VALUES (?,?)', (bvid, utcnow()))
            # Bound cache size on a small NAS.
            self.db.execute('DELETE FROM bili_seen WHERE bvid IN (SELECT bvid FROM bili_seen ORDER BY seen_at DESC LIMIT -1 OFFSET 2500)')


    def price_overview(self):
        summary = self.db.execute('''SELECT COUNT(*) AS total,
            SUM(CASE WHEN state='paid' THEN 1 ELSE 0 END) AS paid,
            SUM(CASE WHEN state='free' THEN 1 ELSE 0 END) AS free
            FROM price_watch''').fetchone()
        recent = [dict(x) for x in self.db.execute('''SELECT appid,name,state,amount,currency,
            first_seen,last_checked,last_paid_at,manual FROM price_watch
            WHERE manual=1 ORDER BY last_checked DESC LIMIT 120''')]
        return {'total': summary['total'], 'paid': summary['paid'] or 0,
                'free': summary['free'] or 0, 'watch': recent}

    def record_price_observations(self, observations):
        '''A conversion needs a previously observed positive Steam price in the same currency.

        A cold-start free game (even one with an ITAD historical paid price) is not a *new*
        paid-to-free event. We save only actual state changes to limit SQLite growth.
        '''
        now = utcnow()
        events = []
        seen = set()
        with self.db:
            for item in observations:
                appid = item.get('appid')
                state = item.get('state')
                amount = item.get('amount')
                currency = str(item.get('currency') or '')[:8]
                name = str(item.get('name') or '')[:180]
                if (type(appid) is not int or appid <= 0 or appid in seen or not name
                    or state not in ('paid', 'free') or type(amount) is not int
                    or (state == 'paid' and (amount <= 0 or not currency))
                    or (state == 'free' and amount != 0)):
                    continue
                seen.add(appid)
                existing = self.db.execute('SELECT * FROM price_watch WHERE appid=?', (appid,)).fetchone()
                if existing is not None and existing['state'] != state:
                    self.db.execute('''INSERT INTO price_history(appid,seen_at,state,amount,currency)
                        VALUES(?,?,?,?,?)''', (appid, now, state, amount, currency))
                elif existing is None:
                    self.db.execute('''INSERT INTO price_history(appid,seen_at,state,amount,currency)
                        VALUES(?,?,?,?,?)''', (appid, now, state, amount, currency))
                last_paid_at = now if state == 'paid' else (existing['last_paid_at'] if existing else '')
                if existing is None:
                    self.db.execute('''INSERT INTO price_watch(appid,name,state,amount,currency,
                        first_seen,last_checked,last_paid_at) VALUES(?,?,?,?,?,?,?,?)''',
                        (appid,name,state,amount,currency,now,now,last_paid_at))
                else:
                    self.db.execute('''UPDATE price_watch SET name=?,state=?,amount=?,
                        currency=?,last_checked=?,last_paid_at=? WHERE appid=?''',
                        (name,state,amount,currency,now,last_paid_at,appid))
                # Watchlist notifications: only user-chosen items, never initial baseline.
                if existing and existing['manual'] and existing['state'] in ('paid', 'free') and (existing['state'] != state or
                        (state == 'paid' and (existing['amount'] != amount or existing['currency'] != currency))):
                    from datetime import timedelta
                    paid_before = bool(existing['state'] == 'paid' and existing['amount'] > 0 and
                        existing['last_paid_at'] >= (datetime.now(timezone.utc) - timedelta(days=90)).isoformat(timespec='seconds'))
                    if not (state == 'free' and paid_before):
                        before = ('免费' if existing['state'] == 'free' else
                                  f'{existing["amount"]/100:.2f} {existing["currency"]}' if existing['state'] == 'paid' else '未知')
                        after = ('免费' if state == 'free' else f'{amount/100:.2f} {currency}')
                        events.append({'key': f'watch-price:{appid}:{now.replace(":", "").replace("-", "")}',
                            'name': name, 'kind': 'watch_price', 'source': 'Steam 关注价格变化',
                            'appid': appid, 'url': f'https://store.steampowered.com/app/{appid}/',
                            'original_price': f'{before} → {after}', 'end_date': '',
                            'confidence': '你关注的游戏价格已变化；具体价格以 Steam 商店所在区域为准'})
                # Date gap protects against very old data being mistaken for a recent change.
                from datetime import timedelta
                recently_paid = bool(existing and existing['last_paid_at'] and
                    existing['last_paid_at'] >= (datetime.now(timezone.utc)-timedelta(days=90)).isoformat(timespec='seconds'))
                if existing and existing['manual'] and existing['state'] == 'paid' and existing['amount'] > 0 and state == 'free' and recently_paid:
                    currency_label = existing['currency'] or currency
                    old_amount = existing['amount']
                    event = {
                        'key': f'price-free:{appid}', 'name': name,
                        'kind': 'paid_to_free', 'source': 'Steam 商店 / 本地价格观测',
                        'appid': appid, 'url': f'https://store.steampowered.com/app/{appid}/',
                        'original_price': f'{old_amount / 100:.2f} {currency_label}',
                        'end_date': '',
                        'confidence': '本地记录到之前收费、当前 Steam is_free=true；是否永久免费仍需商店确认',
                    }
                    events.append(event)
            if events:
                self.upsert_games(events)
            # Clean up historical auto-sampling rows; retain only user watches after migration.
            self.db.execute('DELETE FROM price_watch WHERE manual=0')
            self.db.execute('DELETE FROM price_history WHERE appid NOT IN (SELECT appid FROM price_watch)')
            # Old auto-sampled rows have been removed during migration.
            count = self.db.execute('SELECT COUNT(*) FROM price_watch').fetchone()[0]
            if count > 1500:
                self.db.execute('''DELETE FROM price_watch WHERE appid IN (
                    SELECT appid FROM price_watch WHERE manual=0
                    ORDER BY last_checked ASC LIMIT ?)''', (count - 1500,))
                self.db.execute('''DELETE FROM price_history WHERE appid NOT IN
                    (SELECT appid FROM price_watch)''')
        return events
