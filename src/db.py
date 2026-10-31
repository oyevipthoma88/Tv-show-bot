from __future__ import annotations

import time
from pathlib import Path

import aiosqlite
from typing import Any, Optional

from config import (DB_PATH, DEFAULT_PLANS, MONGO_CAPTION_LIMIT, PLAN_PRICING_REVISION,
                    DEFAULT_FORCE_CHANNELS, DEFAULT_START_PIC, DEFAULT_QR, DEFAULT_UPI,
                    DEFAULT_AUTO_DELETE_MINUTES)
from movie_catalog import detect_content_type
from episode import parse_episode, show_key as make_show_key

LEGACY_TUTORIAL = "📘 <b>Movie Bot Tutorial</b>\n\n1. Pehle required channels join karke <b>Verify</b> dabao.\n2. <b>🎬 Movies</b> par tap karo ya DM/group me movie ka naam bhejo. Spelling thodi galat ho to bhi bot closest result dhoond lega.\n3. Result me quality aur size dekhkar movie button tap karo.\n4. Movie milte hi use save ya forward kar lo, kyunki security ke liye owner ke set kiye hue time ke baad message automatically delete ho sakta hai.\n5. Movie available na ho to bot available suggestions dikhayega.\n6. Premium, coupon aur payment ke liye menu ke respective buttons use karo.\n\n⚠️ Sirf legal aur authorised content ka use karo."
DEFAULT_TUTORIAL = (
    "📺 <b>TV Show Bot — Kaise use kare</b>\n\n"
    "1️⃣ Required channels join karke <b>✅ Verify</b> dabao.\n"
    "2️⃣ Show ka naam seedha bhejo — jaise <code>Anupamaa</code>. Spelling thodi galat bhi chalega.\n"
    "3️⃣ Specific episode chahiye? <code>Anupamaa episode 1234</code> ya <code>Mirzapur S2E3</code> bhejo.\n"
    "4️⃣ Results me sabse <b>naya episode sabse upar</b> 📅 date ke saath hota hai — tap karo, file turant aayegi.\n"
    "5️⃣ <b>🆕 Latest Uploads</b> me aaj ke saare naye episodes milte hain.\n"
    "6️⃣ <b>🔔 Follow</b> dabao — us show ka naya episode aate hi bot khud message karega.\n"
    "7️⃣ File milte hi save/forward kar lo, kuch der baad auto-delete ho sakti hai.\n\n"
    "⚠️ Sirf legal aur authorised content ka use karo."
)
LEGACY_CAPTION_TEMPLATE = "🎬 <b>𝐌𝐨𝐯𝐢𝐞 :</b> {movie_name}\n\n🎥 <b>𝐐𝐮𝐚𝐥𝐢𝐭𝐲 :</b> {quality}\n⏱️ <b>𝐃𝐮𝐫𝐚𝐭𝐢𝐨𝐧 :</b> {duration}\n\n📢 <b>𝐉𝐨𝐢𝐧 :</b> {join}\n🌐 <b>𝐕𝐢𝐬𝐢𝐭 :</b> {username}\n\n⚡ <b>𝐄𝐧𝐣𝐨𝐲 𝐘𝐨𝐮𝐫 𝐌𝐨𝐯𝐢𝐞!</b> 🍿"
DEFAULT_CAPTION_TEMPLATE = (
    "📺 <b>𝐒𝐡𝐨𝐰 :</b> {movie_name}\n"
    "🎞 <b>𝐄𝐩𝐢𝐬𝐨𝐝𝐞 :</b> {episode}\n"
    "📅 <b>𝐃𝐚𝐭𝐞 :</b> {date}\n\n"
    "🎥 <b>𝐐𝐮𝐚𝐥𝐢𝐭𝐲 :</b> {quality}\n"
    "⏱️ <b>𝐃𝐮𝐫𝐚𝐭𝐢𝐨𝐧 :</b> {duration}\n\n"
    "📢 <b>𝐉𝐨𝐢𝐧 :</b> {join}\n"
    "🌐 <b>𝐕𝐢𝐬𝐢𝐭 :</b> {username}\n\n"
    "⚡ <b>𝐄𝐧𝐣𝐨𝐲 𝐘𝐨𝐮𝐫 𝐒𝐡𝐨𝐰!</b> 🍿"
)
# Newest episode first: air date (else upload day), then episode number.
EPISODE_ORDER = ("COALESCE(NULLIF(air_date,''), date(added_at,'unixepoch')) DESC, "
                 "season DESC, episode DESC, added_at DESC, msg_id DESC")
MOVIE_COLUMNS = "msg_id,title,year,quality,language,size,duration,caption,file_id,file_type,storage_msg_id,content_type,added_at,season,episode,air_date,show_key"


def episode_columns(title: str, caption: str) -> tuple[int, int, str, str]:
    """(season, episode, air_date, show_key) for a catalog row."""
    info = parse_episode(caption or "")
    if not (info["season"] or info["episode"] or info["air_date"]):
        info = parse_episode(title or "")
    return info["season"], info["episode"], info["air_date"], make_show_key(title or "")


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    name TEXT,
    joined_at INTEGER,
    premium_until INTEGER DEFAULT 0,
    free_used_today INTEGER DEFAULT 0,
    last_free_day TEXT DEFAULT '',
    first_bonus_used INTEGER DEFAULT 0,
    referred_by INTEGER DEFAULT 0,
    referrals INTEGER DEFAULT 0,
    rewarded_upto INTEGER DEFAULT 0,
    banned INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS movies (
    msg_id INTEGER PRIMARY KEY,
    title TEXT,
    year TEXT,
    quality TEXT,
    language TEXT,
    size TEXT,
    duration TEXT DEFAULT '',
    caption TEXT,
    file_id TEXT,
    file_type TEXT,
    storage_msg_id INTEGER DEFAULT 0,
    content_type TEXT DEFAULT 'movie',
    added_at INTEGER
);
CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    query TEXT,
    title TEXT,
    msg_id INTEGER,
    at INTEGER
);
CREATE TABLE IF NOT EXISTS plans (
    code TEXT PRIMARY KEY,
    label TEXT,
    price INTEGER,
    days INTEGER
);
CREATE TABLE IF NOT EXISTS coupons (
    code TEXT PRIMARY KEY,
    days INTEGER,
    max_uses INTEGER DEFAULT 1,
    used INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS coupon_uses (
    code TEXT, user_id INTEGER, PRIMARY KEY (code, user_id)
);
CREATE TABLE IF NOT EXISTS admins (user_id INTEGER PRIMARY KEY);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS stats (key TEXT PRIMARY KEY, count INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    plan TEXT,
    status TEXT DEFAULT 'pending',
    at INTEGER
);
CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    event TEXT,
    details TEXT,
    at INTEGER
);
CREATE TABLE IF NOT EXISTS delivery_expiry (
    chat_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    delete_at INTEGER NOT NULL,
    PRIMARY KEY (chat_id, message_id)
);
CREATE TABLE IF NOT EXISTS follows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    show_key TEXT NOT NULL,
    show_title TEXT,
    at INTEGER,
    UNIQUE (user_id, show_key)
);
CREATE TABLE IF NOT EXISTS episode_alerts (msg_id INTEGER PRIMARY KEY, at INTEGER);
CREATE TABLE IF NOT EXISTS limit_reminders (user_id INTEGER PRIMARY KEY, remind_at INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS idx_follows_show ON follows (show_key);
CREATE INDEX IF NOT EXISTS idx_history_msg_id_at ON history (msg_id, at DESC);
CREATE INDEX IF NOT EXISTS idx_delivery_expiry_delete_at ON delivery_expiry (delete_at);
"""


class DB:
    conn: aiosqlite.Connection
    _USER_UPDATE_FIELDS = frozenset({
        "username", "name", "premium_until", "free_used_today", "last_free_day",
        "first_bonus_used", "referred_by", "referrals", "rewarded_upto", "banned",
    })

    async def init(self) -> None:
        Path(DB_PATH).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        self.conn = await aiosqlite.connect(DB_PATH)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.execute("PRAGMA journal_mode=WAL")
        await self.conn.execute("PRAGMA synchronous=NORMAL")
        await self.conn.execute("PRAGMA busy_timeout=10000")
        await self.conn.executescript(SCHEMA)
        await self._migrate()
        for code, label, price, days, emoji, tag, sort in DEFAULT_PLANS:
            await self.conn.execute(
                "INSERT OR IGNORE INTO plans (code,label,price,days,emoji,tag,sort) VALUES (?,?,?,?,?,?,?)",
                (code, label, price, days, emoji, tag, sort),
            )
        await self.conn.commit()
        await self.sync_plan_catalog()
        await self.set_default("force_channels", ",".join(DEFAULT_FORCE_CHANNELS))
        await self.set_default("start_pic", DEFAULT_START_PIC)
        await self.set_default("qr", DEFAULT_QR)
        await self.set_default("upi", DEFAULT_UPI)
        await self.set_default("tutorial", DEFAULT_TUTORIAL)
        if (await self.get("tutorial", "")) == LEGACY_TUTORIAL:
            await self.set("tutorial", DEFAULT_TUTORIAL)
        await self.set_default("online_player_bot", "")
        await self.set_default("verify_channels_limit", "5")
        await self.set_default("caption_template", DEFAULT_CAPTION_TEMPLATE)
        if (await self.get("caption_template", "")) == LEGACY_CAPTION_TEMPLATE:
            await self.set("caption_template", DEFAULT_CAPTION_TEMPLATE)
        await self.set_default("caption_join", "")
        await self.set_default("caption_visit", "")
        current_delete = await self.get("auto_delete_minutes", "")
        if not await self.get("auto_delete_default_v2", "") and current_delete in {"", "0"}:
            await self.set("auto_delete_minutes", str(DEFAULT_AUTO_DELETE_MINUTES))
        await self.set_default("auto_delete_minutes", str(DEFAULT_AUTO_DELETE_MINUTES))
        await self.set_default("support_url", "")
        await self.set_default("auto_delete_default_v2", "1")

    async def _migrate(self) -> None:
        cur = await self.conn.execute("PRAGMA table_info(plans)")
        plan_cols = {r["name"] for r in await cur.fetchall()}
        if plan_cols:
            for col, ddl in (("emoji", "TEXT DEFAULT ''"), ("tag", "TEXT DEFAULT ''"),
                             ("sort", "INTEGER DEFAULT 0")):
                if col not in plan_cols:
                    await self.conn.execute(f"ALTER TABLE plans ADD COLUMN {col} {ddl}")
        cur = await self.conn.execute("PRAGMA table_info(movies)")
        cols = {r["name"] for r in await cur.fetchall()}
        for col in ("file_id", "file_type", "duration"):
            if col not in cols:
                await self.conn.execute(f"ALTER TABLE movies ADD COLUMN {col} TEXT")
        if "storage_msg_id" not in cols:
            await self.conn.execute("ALTER TABLE movies ADD COLUMN storage_msg_id INTEGER DEFAULT 0")
        if "content_type" not in cols:
            await self.conn.execute("ALTER TABLE movies ADD COLUMN content_type TEXT DEFAULT 'movie'")
            cur = await self.conn.execute("SELECT msg_id, title, caption FROM movies")
            rows = await cur.fetchall()
            await self.conn.executemany(
                "UPDATE movies SET content_type=? WHERE msg_id=?",
                [
                    (detect_content_type(f"{row['title'] or ''} {row['caption'] or ''}"), row["msg_id"])
                    for row in rows
                ],
            )
        for col, ddl in (("season", "INTEGER DEFAULT 0"), ("episode", "INTEGER DEFAULT 0"),
                         ("air_date", "TEXT DEFAULT ''"), ("show_key", "TEXT DEFAULT ''")):
            if col not in cols:
                await self.conn.execute(f"ALTER TABLE movies ADD COLUMN {col} {ddl}")
        await self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_movies_show_added ON movies (show_key, added_at DESC)"
        )
        await self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_movies_added_at ON movies (added_at DESC)"
        )
        await self.backfill_show_keys(commit=False)
        await self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_movies_content_type_added_at ON movies (content_type, added_at DESC)"
        )
        await self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_movies_storage_title ON movies (storage_msg_id, title)"
        )
        await self.conn.commit()

    async def schedule_expiry(self, chat_id: int, message_id: int, delete_at: int) -> None:
        await self.conn.execute(
            "INSERT OR REPLACE INTO delivery_expiry (chat_id,message_id,delete_at) VALUES (?,?,?)",
            (chat_id, message_id, delete_at),
        )
        await self.conn.commit()

    async def expired_deliveries(self, now: int, limit: int = 100) -> list[aiosqlite.Row]:
        cur = await self.conn.execute(
            "SELECT chat_id,message_id FROM delivery_expiry WHERE delete_at<=? ORDER BY delete_at LIMIT ?",
            (now, limit),
        )
        return await cur.fetchall()

    async def remove_expiry(self, chat_id: int, message_id: int) -> None:
        await self.conn.execute(
            "DELETE FROM delivery_expiry WHERE chat_id=? AND message_id=?",
            (chat_id, message_id),
        )
        await self.conn.commit()

    # ---------- settings ----------
    async def get(self, key: str, default: str = "") -> str:
        cur = await self.conn.execute("SELECT value FROM settings WHERE key=?", (key,))
        row = await cur.fetchone()
        return row["value"] if row else default

    async def set(self, key: str, value: str) -> None:
        await self.conn.execute(
            "INSERT INTO settings (key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        await self.conn.commit()

    async def commit(self) -> None:
        await self.conn.commit()

    async def rollback(self) -> None:
        await self.conn.rollback()

    async def close(self) -> None:
        conn = getattr(self, "conn", None)
        if conn is not None:
            await conn.close()

    async def export_state(self) -> dict:
        tables = ("users", "movies", "history", "plans", "coupons", "coupon_uses", "admins", "settings", "stats", "payments", "audit_logs", "delivery_expiry", "follows")
        state = {"version": 1, "tables": {}}
        for table in tables:
            cur = await self.conn.execute(f"SELECT * FROM {table}")
            state["tables"][table] = [dict(row) for row in await cur.fetchall()]
        return state

    async def export_tables(self, table_names: tuple[str, ...]) -> dict:
        state = {"version": 1, "tables": {}}
        for table in table_names:
            if table not in {"users", "movies", "history", "plans", "coupons", "coupon_uses", "admins", "settings", "stats", "payments", "audit_logs", "delivery_expiry", "follows"}:
                continue
            cur = await self.conn.execute(f"SELECT * FROM {table}")
            state["tables"][table] = [dict(row) for row in await cur.fetchall()]
        return state

    async def export_movie_catalog(self, batch_size: int = 5000) -> list[dict]:
        rows = []
        offset = 0
        while True:
            cur = await self.conn.execute(
                "SELECT * FROM movies ORDER BY msg_id LIMIT ? OFFSET ?", (batch_size, offset)
            )
            batch = [dict(row) for row in await cur.fetchall()]
            if not batch:
                break
            rows.extend(batch)
            offset += batch_size
        return rows

    async def export_movie_catalog_batch(self, after_msg_id: int = 0, limit: int = 5000) -> list[dict]:
        cur = await self.conn.execute(
            "SELECT * FROM movies WHERE msg_id > ? ORDER BY msg_id LIMIT ?",
            (after_msg_id, limit),
        )
        rows = []
        for row in await cur.fetchall():
            item = dict(row)
            if MONGO_CAPTION_LIMIT and isinstance(item.get("caption"), str):
                item["caption"] = item["caption"][:MONGO_CAPTION_LIMIT]
            rows.append(item)
        return rows

    async def bulk_upsert_movies(self, rows: list[tuple]) -> int:
        if not rows:
            return 0
        # rows: (msg_id,title,year,quality,language,size,duration,caption,file_id,file_type,storage_msg_id,content_type,added_at)
        rows = [tuple(row[:13]) + episode_columns(row[1], row[7]) for row in rows]
        await self.conn.executemany(
            f"""INSERT INTO movies ({MOVIE_COLUMNS})
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(msg_id) DO UPDATE SET title=excluded.title, year=excluded.year,
                 quality=excluded.quality, language=excluded.language, size=excluded.size,
                 caption=excluded.caption, season=excluded.season, episode=excluded.episode,
                 air_date=excluded.air_date, show_key=excluded.show_key,
                 duration=CASE WHEN excluded.duration != '' THEN excluded.duration ELSE movies.duration END,
                 file_id=CASE WHEN excluded.file_id != '' THEN excluded.file_id ELSE movies.file_id END,
                 file_type=CASE WHEN excluded.file_type != '' THEN excluded.file_type ELSE movies.file_type END,
                 storage_msg_id=CASE WHEN excluded.storage_msg_id > 0 THEN excluded.storage_msg_id ELSE movies.storage_msg_id END,
                 content_type=excluded.content_type""",
            rows,
        )
        return len(rows)

    async def import_state(self, state: dict) -> None:
        tables = state.get("tables", {}) if isinstance(state, dict) else {}
        try:
            await self.conn.execute("BEGIN")
            for table, rows in tables.items():
                if table not in {"users", "movies", "history", "plans", "coupons", "coupon_uses", "admins", "settings", "stats", "payments", "audit_logs", "delivery_expiry", "follows"}:
                    continue
                cur = await self.conn.execute(f"PRAGMA table_info({table})")
                columns = {row["name"] for row in await cur.fetchall()}
                for row in rows:
                    values = {key: value for key, value in row.items() if key in columns}
                    if not values:
                        continue
                    names = list(values)
                    placeholders = ",".join("?" for _ in names)
                    await self.conn.execute(
                        f"INSERT OR REPLACE INTO {table} ({','.join(names)}) VALUES ({placeholders})",
                        tuple(values[name] for name in names),
                    )
            await self.conn.commit()
        except Exception:
            await self.conn.rollback()
            raise

    async def is_empty_index(self) -> bool:
        return (await self.movie_count()) == 0

    async def set_default(self, key: str, value: str) -> None:
        cur = await self.conn.execute("SELECT 1 FROM settings WHERE key=?", (key,))
        if not await cur.fetchone():
            await self.set(key, value)

    # ---------- users ----------
    async def add_user(self, user_id: int, username: str, name: str, referred_by: int = 0) -> bool:
        cur = await self.conn.execute("SELECT 1 FROM users WHERE user_id=?", (user_id,))
        if await cur.fetchone():
            return False
        await self.conn.execute(
            "INSERT INTO users (user_id,username,name,joined_at,referred_by) VALUES (?,?,?,?,?)",
            (user_id, username, name, int(time.time()), referred_by),
        )
        if referred_by:
            await self.conn.execute("UPDATE users SET referrals=referrals+1 WHERE user_id=?", (referred_by,))
        await self.conn.commit()
        return True

    async def user(self, user_id: int) -> Optional[aiosqlite.Row]:
        cur = await self.conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
        return await cur.fetchone()

    async def update_user(self, user_id: int, **fields: Any) -> None:
        if not fields:
            return
        unknown = set(fields) - self._USER_UPDATE_FIELDS
        if unknown:
            raise ValueError(f"Unsupported user fields: {', '.join(sorted(unknown))}")
        cols = ",".join(f"{k}=?" for k in fields)
        await self.conn.execute(f"UPDATE users SET {cols} WHERE user_id=?", (*fields.values(), user_id))
        await self.conn.commit()

    async def all_user_ids(self) -> list[int]:
        cur = await self.conn.execute("SELECT user_id FROM users WHERE banned=0")
        return [r["user_id"] for r in await cur.fetchall()]

    async def user_count(self, include_banned: bool = False) -> int:
        query = "SELECT COUNT(*) c FROM users" if include_banned else "SELECT COUNT(*) c FROM users WHERE banned=0"
        cur = await self.conn.execute(query)
        return (await cur.fetchone())["c"]

    async def premium_users(self) -> list[aiosqlite.Row]:
        cur = await self.conn.execute(
            "SELECT * FROM users WHERE premium_until > ? ORDER BY premium_until DESC", (int(time.time()),)
        )
        return await cur.fetchall()

    async def add_premium(self, user_id: int, days: float) -> int:
        row = await self.user(user_id)
        now = int(time.time())
        base = max(now, row["premium_until"] if row else 0)
        until = int(base + days * 86400)
        await self.conn.execute("UPDATE users SET premium_until=? WHERE user_id=?", (until, user_id))
        await self.conn.commit()
        return until

    # ---------- movies ----------
    async def upsert_movie(self, msg_id: int, title: str, year: str, quality: str,
                           language: str, size: str, caption: str,
                           file_id: str = "", file_type: str = "", content_type: str = "movie",
                           duration: str = "",
                           storage_msg_id: int = 0, commit: bool = True, added_at: int = 0) -> bool:
        safe_type = content_type if content_type in {"movie", "series", "anime"} else "movie"
        season, episode, air_date, key = episode_columns(title, caption)
        if file_id:
            cur = await self.conn.execute(
                "SELECT msg_id, storage_msg_id FROM movies WHERE file_id=? AND msg_id<>? LIMIT 1",
                (file_id, msg_id),
            )
            duplicate = await cur.fetchone()
            if duplicate:
                if storage_msg_id > 0 and not duplicate["storage_msg_id"]:
                    await self.conn.execute(
                        "UPDATE movies SET msg_id=?, storage_msg_id=?, title=?, year=?, quality=?, language=?, size=?, duration=?, caption=?, file_type=?, content_type=?, season=?, episode=?, air_date=?, show_key=? WHERE msg_id=?",
                        (msg_id, storage_msg_id, title, year, quality, language, size, duration, caption, file_type, safe_type, season, episode, air_date, key, duplicate["msg_id"]),
                    )
                    if commit:
                        await self.conn.commit()
                    return True
                return False
        await self.conn.execute(
            f"""INSERT INTO movies ({MOVIE_COLUMNS})
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(msg_id) DO UPDATE SET title=excluded.title, year=excluded.year,
                 quality=excluded.quality, language=excluded.language, size=excluded.size,
                 caption=excluded.caption, season=excluded.season, episode=excluded.episode,
                 air_date=excluded.air_date, show_key=excluded.show_key,
                 duration=CASE WHEN excluded.duration != '' THEN excluded.duration ELSE movies.duration END,
                 file_id=CASE WHEN excluded.file_id != '' THEN excluded.file_id ELSE movies.file_id END,
                 file_type=CASE WHEN excluded.file_type != '' THEN excluded.file_type ELSE movies.file_type END,
                 storage_msg_id=CASE WHEN excluded.storage_msg_id > 0 THEN excluded.storage_msg_id ELSE movies.storage_msg_id END,
                 content_type=excluded.content_type""",
            (msg_id, title, year, quality, language, size, duration, caption, file_id, file_type, storage_msg_id, safe_type,
             int(added_at or time.time()), season, episode, air_date, key),
        )
        if commit:
            await self.conn.commit()
        return True

    async def has_duplicate_movie(self, file_id: str = "", caption: str = "") -> bool:
        file_id = (file_id or "").strip()
        caption_norm = " ".join((caption or "").split()).strip().casefold()
        if file_id:
            cur = await self.conn.execute(
                "SELECT 1 FROM movies WHERE storage_msg_id > 0 AND file_id=? LIMIT 1", (file_id,)
            )
            if await cur.fetchone():
                return True
        if caption_norm:
            cur = await self.conn.execute(
                "SELECT caption FROM movies WHERE storage_msg_id > 0 AND caption IS NOT NULL"
            )
            async for row in cur:
                stored = " ".join(str(row["caption"]).split()).strip().casefold()
                if stored == caption_norm:
                    return True
        return False

    async def search_movies_sql(self, query: str, content_type: str = "", limit: int = 20) -> list[aiosqlite.Row]:
        safe_type = content_type if content_type in {"movie", "series", "anime"} else ""
        q = f"%{query}%"
        if safe_type:
            cur = await self.conn.execute(
                "SELECT * FROM movies WHERE storage_msg_id > 0 AND content_type=? AND (LOWER(title) LIKE LOWER(?) OR show_key LIKE LOWER(?)) ORDER BY added_at DESC, msg_id DESC LIMIT ?",
                (safe_type, q, q, limit * 3),
            )
        else:
            cur = await self.conn.execute(
                "SELECT * FROM movies WHERE storage_msg_id > 0 AND (LOWER(title) LIKE LOWER(?) OR show_key LIKE LOWER(?)) ORDER BY added_at DESC, msg_id DESC LIMIT ?",
                (q, q, limit * 3),
            )
        return await cur.fetchall()

    async def search_titles_for_spelling(self, query: str, limit: int = 200) -> list[str]:
        q = f"%{query[:3]}%" if len(query) >= 3 else f"%{query}%"
        cur = await self.conn.execute(
            "SELECT title FROM movies WHERE storage_msg_id > 0 AND LOWER(title) LIKE LOWER(?) LIMIT ?",
            (q, limit),
        )
        return [str(row["title"] or "") for row in await cur.fetchall() if row["title"]]

    async def ban_user(self, user_id: int) -> bool:
        cur = await self.conn.execute("SELECT 1 FROM users WHERE user_id=?", (user_id,))
        if not await cur.fetchone():
            return False
        await self.conn.execute("UPDATE users SET banned=1 WHERE user_id=?", (user_id,))
        await self.conn.commit()
        return True

    async def unban_user(self, user_id: int) -> bool:
        cur = await self.conn.execute("SELECT 1 FROM users WHERE user_id=?", (user_id,))
        if not await cur.fetchone():
            return False
        await self.conn.execute("UPDATE users SET banned=0 WHERE user_id=?", (user_id,))
        await self.conn.commit()
        return True

    async def all_movies(self, storage_only: bool = False) -> list[aiosqlite.Row]:
        query = "SELECT * FROM movies WHERE storage_msg_id > 0" if storage_only else "SELECT * FROM movies"
        cur = await self.conn.execute(query)
        return await cur.fetchall()

    async def get_dedup_sets(self) -> tuple[set[str], set[str]]:
        cur = await self.conn.execute(
            "SELECT file_id, caption FROM movies WHERE storage_msg_id > 0"
        )
        files: set[str] = set()
        captions: set[str] = set()
        async for row in cur:
            fid = row["file_id"]
            if fid:
                files.add(str(fid))
            cap = row["caption"]
            if cap:
                captions.add(" ".join(str(cap).split()).strip().casefold())
        return files, captions

    async def bulk_check_duplicates(self, items: list[dict]) -> list[dict]:
        if not items:
            return []
        file_keys = [i["file_key"] for i in items if i.get("file_key")]
        existing_files: set[str] = set()
        if file_keys:
            placeholders = ",".join("?" * len(file_keys))
            cur = await self.conn.execute(
                f"SELECT file_id FROM movies WHERE storage_msg_id > 0 AND file_id IN ({placeholders})",
                file_keys,
            )
            existing_files = {str(row["file_id"]) for row in await cur.fetchall()}

        caption_keys = [i["caption_key"] for i in items if i.get("caption_key")]
        existing_captions: set[str] = set()
        if caption_keys:
            cur = await self.conn.execute(
                "SELECT caption FROM movies WHERE storage_msg_id > 0 AND caption IS NOT NULL"
            )
            async for row in cur:
                cap = row["caption"]
                if cap:
                    existing_captions.add(" ".join(str(cap).split()).strip().casefold())

        result = []
        for item in items:
            fk = item.get("file_key", "")
            ck = item.get("caption_key", "")
            if fk and fk in existing_files:
                continue
            if ck and ck in existing_captions:
                continue
            result.append(item)
        return result

    async def movie(self, msg_id: int) -> Optional[aiosqlite.Row]:
        cur = await self.conn.execute("SELECT * FROM movies WHERE msg_id=?", (msg_id,))
        return await cur.fetchone()

    async def movie_count(self, storage_only: bool = False) -> int:
        query = "SELECT COUNT(*) c FROM movies WHERE storage_msg_id > 0" if storage_only else "SELECT COUNT(*) c FROM movies"
        cur = await self.conn.execute(query)
        return (await cur.fetchone())["c"]

    async def delete_movie(self, msg_id: int) -> None:
        await self.conn.execute("DELETE FROM movies WHERE msg_id=?", (msg_id,))
        await self.conn.commit()

    async def delete_movie_by_storage_id(self, storage_msg_id: int) -> None:
        await self.conn.execute("DELETE FROM movies WHERE storage_msg_id=? OR msg_id=?", (storage_msg_id, storage_msg_id))
        await self.conn.commit()

    async def add_audit(self, user_id: int, event: str, details: str = "") -> None:
        await self.conn.execute(
            "INSERT INTO audit_logs (user_id,event,details,at) VALUES (?,?,?,?)",
            (user_id, event, details[:1000], int(time.time())),
        )
        await self.conn.commit()

    async def popular_movies(self, content_type: str = "", limit: int = 10) -> list[aiosqlite.Row]:
        safe_limit = max(1, min(int(limit), 50))
        safe_type = content_type if content_type in {"movie", "series", "anime"} else ""
        type_clause = " AND m.content_type=?" if safe_type else ""
        params = (safe_type, safe_limit) if safe_type else (safe_limit,)
        cur = await self.conn.execute(
            f"""SELECT m.*, COUNT(h.id) AS request_count,
                         COUNT(DISTINCT h.user_id) AS unique_users,
                         MAX(h.at) AS last_requested_at
               FROM movies AS m
               INNER JOIN history AS h ON h.msg_id = m.msg_id
               WHERE m.storage_msg_id > 0{type_clause}
               GROUP BY m.msg_id
               ORDER BY request_count DESC, unique_users DESC,
                        last_requested_at DESC, m.added_at DESC, m.msg_id DESC
               LIMIT ?""",
            params,
        )
        return await cur.fetchall()

    async def recent_movies(self, content_type: str = "", limit: int = 10,
                            storage_only: bool = False) -> list[aiosqlite.Row]:
        safe_limit = max(1, min(int(limit), 15))
        safe_type = content_type if content_type in {"movie", "series", "anime"} else ""
        filter_sql = "WHERE m.storage_msg_id > 0" if storage_only else "WHERE 1=1"
        if safe_type:
            filter_sql += " AND m.content_type=?"
        params = (safe_type, safe_limit) if safe_type else (safe_limit,)
        cur = await self.conn.execute(
            f"""SELECT m.*, 0 AS request_count
               FROM movies AS m
               {filter_sql}
               ORDER BY m.added_at DESC, m.msg_id DESC
               LIMIT ?""",
            params,
        )
        return await cur.fetchall()

    # ---------- TV shows: episodes / latest / follows ----------
    async def show_rows(self, key: str, content_type: str = "", limit: int = 40) -> list[aiosqlite.Row]:
        """Deliverable rows of one show (all caption variants share the key)."""
        sql = "SELECT * FROM movies WHERE storage_msg_id > 0 AND show_key=?"
        args: list = [key]
        if content_type in {"movie", "series", "anime"}:
            sql += " AND content_type=?"
            args.append(content_type)
        sql += " ORDER BY " + EPISODE_ORDER + " LIMIT ?"
        args.append(max(1, min(int(limit), 500)))
        cur = await self.conn.execute(sql, tuple(args))
        return await cur.fetchall()

    async def recanonicalize_show_keys(self) -> int:
        """Collapse old show keys ("taarak mehta", "tmkoc", "bigg boss 19") into one
        canonical key, for catalog rows AND follows. Cheap: works per distinct key."""
        changed = 0
        cur = await self.conn.execute("SELECT DISTINCT show_key FROM movies WHERE show_key<>''")
        for row in await cur.fetchall():
            old = row["show_key"]
            new = make_show_key(old)
            if new and new != old:
                await self.conn.execute("UPDATE movies SET show_key=? WHERE show_key=?", (new, old))
                changed += 1
        cur = await self.conn.execute("SELECT DISTINCT show_key FROM follows")
        for row in await cur.fetchall():
            old = row["show_key"]
            new = make_show_key(old)
            if new and new != old:
                # keep one follow per (user, show): duplicates are dropped
                await self.conn.execute("UPDATE OR IGNORE follows SET show_key=? WHERE show_key=?", (new, old))
                await self.conn.execute("DELETE FROM follows WHERE show_key=?", (old,))
                changed += 1
        await self.conn.commit()
        return changed

    async def rekey_all_shows(self, version: str = "sep-v2") -> int:
        """One-time full regroup after show-name parsing improved (underscore /
        dot file names, episode title no longer part of the show). Runs once per
        version, in chunks, then rewrites old follows to the new keys."""
        if await self.get("show_rekey_version", "") == version:
            return 0
        changed, last = 0, 0
        remap: dict[str, str] = {}
        while True:
            cur = await self.conn.execute(
                "SELECT msg_id, title, caption, show_key FROM movies WHERE msg_id>? ORDER BY msg_id LIMIT 2000",
                (last,),
            )
            rows = await cur.fetchall()
            if not rows:
                break
            updates = []
            for r in rows:
                last = r["msg_id"]
                season, episode, air, _ = episode_columns(r["title"], r["caption"])
                cap = (r["caption"] or "").strip()
                # single-line caption = usually the original file name, which
                # still has S02E17 that the old title parser stripped away
                one_line = cap and "\n" not in cap and len(cap) < 300
                key = (make_show_key(cap) if one_line else "") or make_show_key(r["title"] or "")
                if key and key != (r["show_key"] or ""):
                    if r["show_key"]:
                        remap[r["show_key"]] = key
                    updates.append((season, episode, air, key, r["msg_id"]))
            if updates:
                await self.conn.executemany(
                    "UPDATE movies SET season=?, episode=?, air_date=?, show_key=? WHERE msg_id=?", updates)
                changed += len(updates)
            await self.conn.commit()
        for old, new in remap.items():
            await self.conn.execute("UPDATE OR IGNORE follows SET show_key=? WHERE show_key=?", (new, old))
            await self.conn.execute("DELETE FROM follows WHERE show_key=?", (old,))
        await self.conn.commit()
        await self.set("show_rekey_version", version)
        return changed

    async def backfill_show_keys(self, commit: bool = True) -> int:
        """Fill season/episode/show_key for rows restored from older backups."""
        cur = await self.conn.execute(
            "SELECT msg_id, title, caption FROM movies WHERE show_key IS NULL OR show_key=''"
        )
        rows = await cur.fetchall()
        if rows:
            await self.conn.executemany(
                "UPDATE movies SET season=?, episode=?, air_date=?, show_key=? WHERE msg_id=?",
                [(*episode_columns(r["title"], r["caption"]), r["msg_id"]) for r in rows],
            )
            if commit:
                await self.conn.commit()
        return len(rows)

    async def has_duplicate_upload(self, file_id: str, caption: str, size: str) -> bool:
        """Same file, or same caption + same size (re-post). Generic captions alone never match."""
        if file_id:
            cur = await self.conn.execute(
                "SELECT 1 FROM movies WHERE storage_msg_id > 0 AND file_id=? LIMIT 1", (file_id,)
            )
            if await cur.fetchone():
                return True
        caption_norm = " ".join((caption or "").split()).strip().casefold()
        if not caption_norm or not size:
            return False
        cur = await self.conn.execute(
            "SELECT caption FROM movies WHERE storage_msg_id > 0 AND size=? ORDER BY added_at DESC LIMIT 500",
            (size,),
        )
        for row in await cur.fetchall():
            if " ".join(str(row["caption"] or "").split()).strip().casefold() == caption_norm:
                return True
        return False

    async def latest_uploads(self, offset: int = 0, limit: int = 10) -> list[aiosqlite.Row]:
        cur = await self.conn.execute(
            "SELECT * FROM movies WHERE storage_msg_id > 0 ORDER BY added_at DESC, msg_id DESC LIMIT ? OFFSET ?",
            (max(1, min(int(limit), 50)), max(0, int(offset))),
        )
        return await cur.fetchall()

    async def uploads_since(self, since_ts: int) -> int:
        cur = await self.conn.execute(
            "SELECT COUNT(*) c FROM movies WHERE storage_msg_id > 0 AND added_at >= ?", (int(since_ts),)
        )
        return (await cur.fetchone())["c"]

    async def latest_show_titles(self, limit: int = 3) -> list[str]:
        cur = await self.conn.execute(
            "SELECT title, show_key FROM movies WHERE storage_msg_id > 0 ORDER BY added_at DESC, msg_id DESC LIMIT 60"
        )
        seen, titles = set(), []
        for row in await cur.fetchall():
            key = row["show_key"] or str(row["title"] or "").lower()
            if key and key not in seen:
                seen.add(key)
                titles.append(str(row["title"] or ""))
            if len(titles) >= limit:
                break
        return titles

    async def show_episodes(self, key: str, offset: int = 0, limit: int = 10) -> list[aiosqlite.Row]:
        cur = await self.conn.execute(
            "SELECT * FROM movies WHERE storage_msg_id > 0 AND show_key=? ORDER BY "
            + EPISODE_ORDER + " LIMIT ? OFFSET ?",
            (key, max(1, min(int(limit), 50)), max(0, int(offset))),
        )
        return await cur.fetchall()

    async def show_episode_count(self, key: str) -> int:
        if not key:
            return 0
        cur = await self.conn.execute(
            "SELECT COUNT(*) c FROM movies WHERE storage_msg_id > 0 AND show_key=?", (key,)
        )
        return (await cur.fetchone())["c"]

    async def latest_episode_id(self, key: str) -> int:
        cur = await self.conn.execute(
            "SELECT msg_id FROM movies WHERE storage_msg_id > 0 AND show_key=? ORDER BY " + EPISODE_ORDER + " LIMIT 1",
            (key,),
        )
        row = await cur.fetchone()
        return int(row["msg_id"]) if row else 0

    async def follow(self, user_id: int, key: str, title: str) -> bool:
        if not key:
            return False
        cur = await self.conn.execute(
            "INSERT OR IGNORE INTO follows (user_id, show_key, show_title, at) VALUES (?,?,?,?)",
            (user_id, key, title[:120], int(time.time())),
        )
        await self.conn.commit()
        return cur.rowcount > 0

    async def unfollow(self, user_id: int, key: str) -> bool:
        cur = await self.conn.execute("DELETE FROM follows WHERE user_id=? AND show_key=?", (user_id, key))
        await self.conn.commit()
        return cur.rowcount > 0

    async def unfollow_id(self, user_id: int, follow_id: int) -> bool:
        cur = await self.conn.execute("DELETE FROM follows WHERE user_id=? AND id=?", (user_id, follow_id))
        await self.conn.commit()
        return cur.rowcount > 0

    async def is_following(self, user_id: int, key: str) -> bool:
        cur = await self.conn.execute("SELECT 1 FROM follows WHERE user_id=? AND show_key=?", (user_id, key))
        return await cur.fetchone() is not None

    async def follows(self, user_id: int) -> list[aiosqlite.Row]:
        cur = await self.conn.execute(
            "SELECT * FROM follows WHERE user_id=? ORDER BY at DESC LIMIT 50", (user_id,)
        )
        return await cur.fetchall()

    async def followers(self, key: str) -> list[int]:
        cur = await self.conn.execute(
            """SELECT f.user_id FROM follows AS f LEFT JOIN users AS u ON u.user_id = f.user_id
               WHERE f.show_key=? AND COALESCE(u.banned, 0)=0""",
            (key,),
        )
        return [int(r["user_id"]) for r in await cur.fetchall()]

    async def mark_alert_sent(self, msg_id: int) -> bool:
        """True only the first time an episode alert is claimed."""
        cur = await self.conn.execute(
            "INSERT OR IGNORE INTO episode_alerts (msg_id, at) VALUES (?, ?)", (msg_id, int(time.time()))
        )
        await self.conn.commit()
        return cur.rowcount > 0

    # ---------- history ----------
    async def add_history(self, user_id: int, query: str, title: str, msg_id: int) -> None:
        await self.conn.execute(
            "INSERT INTO history (user_id,query,title,msg_id,at) VALUES (?,?,?,?,?)",
            (user_id, query, title, msg_id, int(time.time())),
        )
        await self.conn.commit()

    async def history(self, user_id: int, limit: int = 10) -> list[aiosqlite.Row]:
        cur = await self.conn.execute(
            "SELECT * FROM history WHERE user_id=? ORDER BY id DESC LIMIT ?", (user_id, limit)
        )
        return await cur.fetchall()

    # ---------- plans / coupons / admins ----------
    async def plans(self) -> list[aiosqlite.Row]:
        cur = await self.conn.execute(
            "SELECT * FROM plans ORDER BY CASE WHEN COALESCE(sort,0)=0 THEN 1 ELSE 0 END, sort, days"
        )
        return await cur.fetchall()

    async def sync_plan_catalog(self) -> None:
        reset_prices = (await self.get("plan_pricing_revision", "")) != PLAN_PRICING_REVISION
        for code, label, price, days, emoji, tag, sort in DEFAULT_PLANS:
            cur = await self.conn.execute("SELECT price FROM plans WHERE code=?", (code,))
            row = await cur.fetchone()
            if row is None:
                await self.conn.execute(
                    "INSERT INTO plans (code,label,price,days,emoji,tag,sort) VALUES (?,?,?,?,?,?,?)",
                    (code, label, price, days, emoji, tag, sort),
                )
                continue
            keep_price = price if reset_prices else row["price"]
            await self.conn.execute(
                "UPDATE plans SET label=?, price=?, days=?, emoji=?, tag=?, sort=? WHERE code=?",
                (label, keep_price, days, emoji, tag, sort, code),
            )
        await self.conn.commit()
        if reset_prices:
            await self.set("plan_pricing_revision", PLAN_PRICING_REVISION)

    async def set_plan_tag(self, code: str, tag: str) -> None:
        await self.conn.execute("UPDATE plans SET tag=? WHERE code=?", (tag, code))
        await self.conn.commit()

    async def plan(self, code: str) -> Optional[aiosqlite.Row]:
        cur = await self.conn.execute("SELECT * FROM plans WHERE code=?", (code,))
        return await cur.fetchone()

    async def set_plan_price(self, code: str, price: int) -> None:
        await self.conn.execute("UPDATE plans SET price=? WHERE code=?", (price, code))
        await self.conn.commit()

    async def add_coupon(self, code: str, days: int, max_uses: int) -> None:
        await self.conn.execute(
            "INSERT OR REPLACE INTO coupons (code,days,max_uses,used) VALUES (?,?,?,0)",
            (code.upper(), days, max_uses),
        )
        await self.conn.commit()

    async def redeem_coupon(self, code: str, user_id: int) -> Optional[int]:
        code = "".join((code or "").upper().split())
        if not code:
            return None
        try:
            await self.conn.execute("BEGIN IMMEDIATE")
            cur = await self.conn.execute("SELECT days FROM coupons WHERE code=? AND used < max_uses", (code,))
            row = await cur.fetchone()
            if not row:
                await self.conn.rollback()
                return None
            cur = await self.conn.execute("SELECT 1 FROM coupon_uses WHERE code=? AND user_id=?", (code, user_id))
            if await cur.fetchone():
                await self.conn.rollback()
                return None
            await self.conn.execute("UPDATE coupons SET used=used+1 WHERE code=? AND used < max_uses", (code,))
            await self.conn.execute("INSERT INTO coupon_uses (code,user_id) VALUES (?,?)", (code, user_id))
            await self.conn.commit()
            return row["days"]
        except Exception:
            await self.conn.rollback()
            return None

    # ---------- extra owners (/addowner) ----------
    async def extra_owners(self) -> list[int]:
        raw = await self.get("extra_owners", "")
        out = []
        for part in raw.split(","):
            try:
                out.append(int(part.strip()))
            except ValueError:
                pass
        return out

    async def add_extra_owner(self, user_id: int) -> None:
        owners = await self.extra_owners()
        if user_id not in owners:
            owners.append(user_id)
        await self.set("extra_owners", ",".join(str(o) for o in owners))

    async def remove_extra_owner(self, user_id: int) -> None:
        owners = [o for o in await self.extra_owners() if o != user_id]
        await self.set("extra_owners", ",".join(str(o) for o in owners))

    # ---------- limit-over reminders ----------
    async def set_limit_reminder(self, user_id: int, remind_at: int) -> None:
        await self.conn.execute(
            "INSERT INTO limit_reminders (user_id, remind_at) VALUES (?,?) "
            "ON CONFLICT(user_id) DO UPDATE SET remind_at=excluded.remind_at",
            (user_id, int(remind_at)),
        )
        await self.conn.commit()

    async def due_limit_reminders(self, now: int, limit: int = 200) -> list[int]:
        cur = await self.conn.execute(
            "SELECT user_id FROM limit_reminders WHERE remind_at <= ? LIMIT ?", (int(now), limit)
        )
        return [int(r["user_id"]) for r in await cur.fetchall()]

    async def clear_limit_reminder(self, user_id: int) -> None:
        await self.conn.execute("DELETE FROM limit_reminders WHERE user_id=?", (user_id,))
        await self.conn.commit()

    # ---------- spelling + stale rows ----------
    async def distinct_show_titles(self, limit: int = 5000) -> list[str]:
        """One title per show (newest first) — the vocabulary for spelling fixes."""
        cur = await self.conn.execute(
            """SELECT title FROM movies WHERE storage_msg_id > 0 AND title IS NOT NULL
               GROUP BY COALESCE(NULLIF(show_key, ''), LOWER(title))
               ORDER BY MAX(added_at) DESC LIMIT ?""",
            (limit,),
        )
        return [str(r["title"]) for r in await cur.fetchall() if r["title"]]

    async def mark_stale(self, msg_id: int) -> None:
        """MAIN_DATA post is gone: hide the row so it is never offered again."""
        await self.conn.execute("UPDATE movies SET storage_msg_id=0 WHERE msg_id=? OR storage_msg_id=?",
                                (msg_id, msg_id))
        await self.conn.commit()

    async def alternate_copy(self, movie, exclude: set[int]) -> Optional[object]:
        """Another live MAIN_DATA post of the same file / same episode."""
        keys = movie.keys()
        file_id = movie["file_id"] if "file_id" in keys else ""
        if file_id:
            cur = await self.conn.execute(
                "SELECT * FROM movies WHERE storage_msg_id > 0 AND file_id=? ORDER BY added_at DESC", (file_id,)
            )
            for row in await cur.fetchall():
                if int(row["storage_msg_id"] or row["msg_id"]) not in exclude:
                    return row
        show = movie["show_key"] if "show_key" in keys else ""
        ep = int(movie["episode"] or 0) if "episode" in keys else 0
        air = (movie["air_date"] or "") if "air_date" in keys else ""
        season = int(movie["season"] or 0) if "season" in keys else 0
        if show and (ep or air):
            # same season too, so S01E01 is never replaced by S02E01
            cur = await self.conn.execute(
                """SELECT * FROM movies WHERE storage_msg_id > 0 AND show_key=?
                   AND ((? > 0 AND episode=? AND COALESCE(season,0)=?) OR (? <> '' AND air_date=?))
                   ORDER BY added_at DESC""",
                (show, ep, ep, season, air, air),
            )
            for row in await cur.fetchall():
                if int(row["storage_msg_id"] or row["msg_id"]) not in exclude:
                    return row
        return None

    async def admins(self) -> list[int]:
        cur = await self.conn.execute("SELECT user_id FROM admins")
        return [r["user_id"] for r in await cur.fetchall()]

    async def add_admin(self, user_id: int) -> None:
        await self.conn.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (user_id,))
        await self.conn.commit()

    async def remove_admin(self, user_id: int) -> None:
        await self.conn.execute("DELETE FROM admins WHERE user_id=?", (user_id,))
        await self.conn.commit()

    async def add_payment(self, user_id: int, plan: str) -> int:
        cur = await self.conn.execute(
            "INSERT INTO payments (user_id,plan,at) VALUES (?,?,?)", (user_id, plan, int(time.time()))
        )
        await self.conn.commit()
        return cur.lastrowid or 0

    async def payment(self, pid: int) -> Optional[aiosqlite.Row]:
        cur = await self.conn.execute("SELECT * FROM payments WHERE id=?", (pid,))
        return await cur.fetchone()

    async def set_payment_status(self, pid: int, status: str) -> None:
        await self.conn.execute("UPDATE payments SET status=? WHERE id=?", (status, pid))
        await self.conn.commit()

    async def approve_payment(self, pid: int, user_id: int, days: float) -> Optional[int]:
        try:
            await self.conn.execute("BEGIN IMMEDIATE")
            payment_cur = await self.conn.execute(
                "SELECT status, user_id FROM payments WHERE id=?", (pid,)
            )
            payment = await payment_cur.fetchone()
            if not payment or payment["status"] != "pending" or int(payment["user_id"]) != int(user_id):
                await self.conn.rollback()
                return None
            user_cur = await self.conn.execute(
                "SELECT premium_until FROM users WHERE user_id=?", (user_id,)
            )
            user = await user_cur.fetchone()
            if not user:
                await self.conn.rollback()
                return None
            now = int(time.time())
            until = int(max(now, user["premium_until"] or 0) + float(days) * 86400)
            await self.conn.execute(
                "UPDATE users SET premium_until=? WHERE user_id=?", (until, user_id)
            )
            await self.conn.execute(
                "UPDATE payments SET status='approved' WHERE id=? AND status='pending'", (pid,)
            )
            await self.conn.commit()
            return until
        except Exception:
            await self.conn.rollback()
            return None


    async def ensure_stats(self):
        await self.conn.execute("CREATE TABLE IF NOT EXISTS stats(key TEXT PRIMARY KEY, count INTEGER)")
        await self.conn.commit()

    async def incr_stat(self, key: str) -> int:
        try:
            await self.conn.execute(
                "INSERT INTO stats(key, count) VALUES(?, 1) ON CONFLICT(key) DO UPDATE SET count = count + 1",
                (key,)
            )
            await self.conn.commit()
            cur = await self.conn.execute("SELECT count FROM stats WHERE key = ?", (key,))
            row = await cur.fetchone()
            return int(row[0]) if row else 1
        except Exception:
            return 0

db = DB()
