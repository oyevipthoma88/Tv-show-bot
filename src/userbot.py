"""Owner user-account (Telethon) login + instant live mirror.

The bot cannot read channels where it is not admin. The owner logs in a
normal Telegram account from Owner Panel → 🔐 Login Account; that account
(which has joined the source channels) watches every new upload and shares
it into MAIN_DATA immediately, then indexes it so users get the latest
episode on top of their search results.
"""
from __future__ import annotations

import asyncio
import logging
import os
import tempfile
import time

import config
from db import db
from movie_catalog import detect_content_type
from utils import parse_caption

log = logging.getLogger("userbot")

_pending: dict[int, dict] = {}       # owner_id -> login-in-progress state
_live_client = None
_live_bot = None
_queue: asyncio.Queue | None = None
_worker: asyncio.Task | None = None
_catchup: asyncio.Task | None = None
_me_label = ""
_watchdog: asyncio.Task | None = None
_bot_admin_cache: dict[int, tuple[bool, float]] = {}
_last_alert: dict[str, float] = {}
_workers: list[asyncio.Task] = []
_inflight: set[str] = set()
LIVE_WORKERS = max(1, int(os.getenv("LIVE_WORKERS", "6")))
CATCHUP_PARALLEL = max(1, int(os.getenv("CATCHUP_PARALLEL", "5")))


# ---------------- credentials ----------------
async def load_saved_credentials() -> None:
    """Restore API id/hash/session saved by the panel login (Mongo-backed settings)."""
    saved_id = (await db.get("tg_api_id", "")).strip()
    saved_hash = (await db.get("tg_api_hash", "")).strip()
    saved_session = (await db.get("tg_session", "")).strip()
    if not config.TG_API_ID and saved_id.isdigit():
        config.TG_API_ID = int(saved_id)
    if not config.TG_API_HASH and saved_hash:
        config.TG_API_HASH = saved_hash
    if saved_session:
        config.TG_SESSION = saved_session


def has_api() -> bool:
    return bool(config.TG_API_ID and config.TG_API_HASH)


async def set_api(api_id: int, api_hash: str) -> None:
    config.TG_API_ID = int(api_id)
    config.TG_API_HASH = api_hash.strip()
    await db.set("tg_api_id", str(api_id))
    await db.set("tg_api_hash", api_hash.strip())


def _new_client(session: str = ""):
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    return TelegramClient(StringSession(session), int(config.TG_API_ID), config.TG_API_HASH,
                          device_model="TV Show Bot", system_version="Linux", app_version="1.0")


async def _persist() -> None:
    try:
        from mongo_store import save_non_movie_state
        await save_non_movie_state()
    except Exception as exc:
        log.warning("Session save to Mongo failed: %s", exc)


async def _reset_shared_clients() -> None:
    """Old clients cache the previous session; drop them so they reconnect."""
    try:
        from mtproto_importer import close_mtproto
        await close_mtproto()
    except Exception:
        pass
    try:
        import channel_search
        if channel_search._client is not None:
            try:
                await channel_search._client.disconnect()
            except Exception:
                pass
        channel_search._client = None
    except Exception:
        pass


# ---------------- login flow ----------------
async def start_login(owner_id: int, phone: str) -> str:
    await cancel_login(owner_id)
    client = _new_client()
    await client.connect()
    sent = await client.send_code_request(phone)
    _pending[owner_id] = {"client": client, "phone": phone, "hash": sent.phone_code_hash}
    return "code"


async def submit_code(owner_id: int, code: str) -> str:
    """Returns 'ok', 'password' (2FA needed) or raises."""
    from telethon.errors import SessionPasswordNeededError
    state = _pending.get(owner_id)
    if not state:
        raise RuntimeError("Login session expire ho gaya, dobara Login dabao.")
    digits = "".join(ch for ch in code if ch.isdigit())
    try:
        await state["client"].sign_in(state["phone"], digits, phone_code_hash=state["hash"])
    except SessionPasswordNeededError:
        return "password"
    return await _finish(owner_id)


async def submit_password(owner_id: int, password: str) -> str:
    state = _pending.get(owner_id)
    if not state:
        raise RuntimeError("Login session expire ho gaya, dobara Login dabao.")
    await state["client"].sign_in(password=password)
    return await _finish(owner_id)


async def _finish(owner_id: int) -> str:
    state = _pending.pop(owner_id)
    client = state["client"]
    session = client.session.save()
    await client.disconnect()
    config.TG_SESSION = session
    await db.set("tg_session", session)
    await _persist()
    await _reset_shared_clients()
    await stop_live()
    if _live_bot is not None:
        await start_live(_live_bot)
    return "ok"


async def cancel_login(owner_id: int) -> None:
    state = _pending.pop(owner_id, None)
    if state:
        try:
            await state["client"].disconnect()
        except Exception:
            pass


async def logout() -> None:
    session = config.TG_SESSION
    await stop_live()
    if session and has_api():
        try:
            client = _new_client(session)
            await client.connect()
            await client.log_out()
        except Exception as exc:
            log.warning("Telegram log_out failed: %s", exc)
    config.TG_SESSION = ""
    await db.set("tg_session", "")
    await _persist()
    await _reset_shared_clients()


async def status_text() -> str:
    if not has_api():
        return "❌ API ID / API HASH set nahi hai."
    if not config.TG_SESSION:
        return "❌ Koi account login nahi hai."
    live = "🟢 Live Mirror chal raha hai" if is_live() else "🔴 Live Mirror band hai"
    who = _me_label or "connected account"
    return f"✅ Logged in: <b>{who}</b>\n{live}"


def is_live() -> bool:
    return _live_client is not None and _live_client.is_connected()


async def resolve_chat(value: str):
    """(chat_id, title) of a channel the logged-in account can see, else None."""
    if not (has_api() and config.TG_SESSION):
        return None
    from telethon import utils as tg_utils
    client = _live_client if is_live() else None
    temp = None
    try:
        if client is None:
            temp = client = _new_client(config.TG_SESSION)
            await client.connect()
            if not await client.is_user_authorized():
                return None
        target = int(value) if value.lstrip("-").isdigit() else value
        if isinstance(target, int):
            await client.get_dialogs(limit=None)
        entity = await client.get_entity(target)
        return tg_utils.get_peer_id(entity), getattr(entity, "title", "") or str(value)
    except Exception as exc:
        log.warning("resolve_chat %s failed: %s", value, exc)
        return None
    finally:
        if temp is not None:
            await temp.disconnect()


# ---------------- live mirror ----------------
async def _source_ids() -> tuple[set[int], set[str]]:
    raw = await db.get("movie_channels", "")
    ids, names = set(), set()
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        if item.lstrip("-").isdigit():
            ids.add(int(item))
        else:
            names.add(item.lstrip("@").lower())
    ids.discard(int(config.MAIN_DATA))
    return ids, names


def _format_duration(seconds) -> str:
    seconds = int(seconds or 0)
    if seconds <= 0:
        return ""
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _doc_meta(document, caption: str) -> dict:
    attrs = getattr(document, "attributes", []) or []
    file_name = next((getattr(a, "file_name", "") for a in attrs if getattr(a, "file_name", "")), "")
    duration = next((getattr(a, "duration", 0) for a in attrs if getattr(a, "duration", 0)), 0)
    meta = parse_caption(caption or file_name)
    meta["duration"] = _format_duration(duration)
    if not meta.get("size"):
        mb = (getattr(document, "size", 0) or 0) / 1048576
        meta["size"] = f"{mb / 1024:.1f}GB" if mb > 1024 else f"{mb:.0f}MB"
    mime = getattr(document, "mime_type", "") or ""
    meta["file_type"] = "video" if mime.startswith("video/") else "audio" if mime.startswith("audio/") else "document"
    return meta


async def _send_to_main(client, message):
    """Share into MAIN_DATA without re-upload; protected channels fall back to download+upload."""
    from telethon.errors import FloodWaitError
    caption = message.message or ""
    for attempt in range(3):
        try:
            try:
                return await client.send_file(config.MAIN_DATA, message.media, caption=caption,
                                              formatting_entities=message.entities, silent=True)
            except FloodWaitError:
                raise
            except Exception as exc:
                log.info("Direct share blocked (%s); downloading and re-uploading", exc)
                with tempfile.TemporaryDirectory() as tmp:
                    path = await client.download_media(message, file=tmp + os.sep)
                    if not path:
                        raise
                    return await client.send_file(
                        config.MAIN_DATA, path, caption=caption, formatting_entities=message.entities,
                        attributes=getattr(message.document, "attributes", None),
                        supports_streaming=True, silent=True,
                    )
        except FloodWaitError as exc:
            await asyncio.sleep(exc.seconds + 1)
    return None


async def _notify_owner(reason_key: str, text: str) -> None:
    """Tell the owner about live-mirror problems (max once per 10 min per reason)."""
    if _live_bot is None or time.time() - _last_alert.get(reason_key, 0) < 600:
        return
    _last_alert[reason_key] = time.time()
    for owner in config.OWNER_IDS:
        try:
            await _live_bot.send_message(owner, text)
        except Exception:
            pass


async def _bot_handles(chat_id: int) -> bool:
    """Skip channels where the bot itself is admin — the bot's own auto-transfer
    already copies those, so mirroring them here would create duplicates."""
    if _live_bot is None:
        return False
    cached = _bot_admin_cache.get(chat_id)
    if cached and time.time() - cached[1] < 600:
        return cached[0]
    try:
        member = await _live_bot.get_chat_member(chat_id, _live_bot.id)
        admin = getattr(member, "status", "") in ("administrator", "creator")
    except Exception:
        admin = False
    _bot_admin_cache[chat_id] = (admin, time.time())
    return admin


async def _process(message) -> None:
    client = _live_client
    document = getattr(message, "document", None)
    if client is None or not document:
        return
    caption = message.message or ""
    key = f"tg:{document.id}:{getattr(document, 'access_hash', 0) or 0}"
    chat_id = message.chat_id
    source_meta = _doc_meta(document, caption)
    if key in _inflight:
        return
    _inflight.add(key)
    try:
        await _process_locked(message, client, document, caption, key, chat_id, source_meta)
    finally:
        _inflight.discard(key)


async def _process_locked(message, client, document, caption, key, chat_id, source_meta):
    if await db.has_duplicate_upload(key, caption, source_meta.get("size", "")):
        log.info("Live mirror: duplicate %s/%s skipped", chat_id, message.id)
        await _bump_last(chat_id, message.id)
        return
    try:
        sent = await _send_to_main(client, message)
    except Exception as exc:
        log.error("Live mirror: share %s/%s failed: %s", chat_id, message.id, exc)
        await _notify_owner(
            "share_failed",
            "⚠️ <b>Live Mirror: upload MAIN_DATA me nahi gaya</b>\n\n"
            f"Error: <code>{str(exc)[:300]}</code>\n\n"
            "Check karo: login wala account MAIN_DATA channel me <b>admin</b> ho (post permission) "
            "aur source channel join kiya ho.",
        )
        return
    if not sent:
        log.error("Live mirror: failed to share %s/%s", chat_id, message.id)
        return
    sent_doc = getattr(sent, "document", None) or document
    file_key = f"tg:{sent_doc.id}:{getattr(sent_doc, 'access_hash', 0) or 0}"
    meta = _doc_meta(sent_doc, caption)
    posted_at = int(message.date.timestamp()) if getattr(message, "date", None) else int(time.time())
    inserted = await db.upsert_movie(
        sent.id, meta["title"], meta["year"], meta["quality"], meta["language"], meta["size"],
        caption, file_key, meta["file_type"], detect_content_type(caption),
        duration=meta["duration"], storage_msg_id=sent.id, added_at=posted_at,
    )
    await _bump_last(chat_id, message.id)
    if inserted and _live_bot is not None:
        try:
            from snapshot import request_catalog_save, request_snapshot
            await request_snapshot(_live_bot)
            await request_catalog_save()
            import alerts
            await alerts.queue_new_episode(_live_bot, sent.id)
            from log_helper import log_new_movie_added
            await log_new_movie_added(_live_bot, meta["title"], meta["quality"], chat_id, sent.id,
                                      "live mirror (user account)", await db.movie_count(storage_only=True))
        except Exception as exc:
            log.warning("Live mirror post-index step failed: %s", exc)
    log.info("Live mirror: %s/%s -> MAIN_DATA %s (%s)", chat_id, message.id, sent.id, meta["title"])


async def _bump_last(chat_id: int, msg_id: int) -> None:
    """Parallel workers may finish out of order — only move the cursor forward."""
    current = int((await db.get(f"live_last:{chat_id}", "0")) or 0)
    if int(msg_id) > current:
        await db.set(f"live_last:{chat_id}", str(msg_id))


async def import_to_main(chat_id: int, msg_id: int):
    """On-demand: pull one file from a joined (non-admin) source into MAIN_DATA and
    return the MAIN_DATA message id, so the bot can deliver it to a user."""
    client = _live_client
    if client is None:
        return None
    try:
        message = await client.get_messages(chat_id, ids=msg_id)
        if not message or not getattr(message, "document", None):
            return None
        sent = await _send_to_main(client, message)
        if not sent:
            return None
        sent_doc = getattr(sent, "document", None) or message.document
        caption = message.message or ""
        meta = _doc_meta(sent_doc, caption)
        await db.upsert_movie(
            sent.id, meta["title"], meta["year"], meta["quality"], meta["language"], meta["size"],
            caption, f"tg:{sent_doc.id}:{getattr(sent_doc, 'access_hash', 0) or 0}", meta["file_type"],
            detect_content_type(caption), duration=meta["duration"], storage_msg_id=sent.id,
            added_at=int(time.time()),
        )
        try:
            from snapshot import request_catalog_save
            await request_catalog_save()
        except Exception:
            pass
        return sent.id
    except Exception as exc:
        log.warning("import_to_main %s/%s failed: %s", chat_id, msg_id, exc)
        return None


async def search_sources(query: str, limit: int = 10) -> list[dict]:
    """Search every source channel the logged-in account has joined, in parallel."""
    client = _live_client
    if client is None or not query.strip():
        return []
    ids, names = await _source_ids()
    sem = asyncio.Semaphore(CATCHUP_PARALLEL)

    async def one(target):
        out = []
        async with sem:
            try:
                entity = await client.get_entity(target)
                from telethon import utils as tg_utils
                peer = tg_utils.get_peer_id(entity)
                async for m in client.iter_messages(entity, search=query.strip()[:100], limit=limit):
                    if getattr(m, "document", None):
                        cap = m.message or ""
                        title = (cap.split("\n")[0][:200].strip() if cap else "") or _doc_meta(m.document, cap).get("title") or f"Episode {m.id}"
                        out.append({"msg_id": m.id, "channel_id": peer, "title": title,
                                    "caption": cap, "source": True})
            except Exception as exc:
                log.debug("source search %s failed: %s", target, exc)
        return out

    results = await asyncio.wait_for(asyncio.gather(*(one(t) for t in [*ids, *names])), timeout=20)
    flat = [r for chunk in results for r in chunk]
    flat.sort(key=lambda r: r["msg_id"], reverse=True)
    return flat[: limit * 2]


async def _run_worker() -> None:
    while True:
        message = await _queue.get()
        try:
            if await db.get("live_mirror_enabled", "1") != "0":
                await _process(message)
        except Exception:
            log.exception("Live mirror failed for %s", getattr(message, "id", "?"))
        finally:
            _queue.task_done()


async def _is_source(chat_id: int, username: str) -> bool:
    ids, names = await _source_ids()
    return chat_id in ids or (bool(username) and username.lower() in names)


async def _catch_up() -> None:
    """Pick up uploads that happened while the bot was offline (newest 200/source)."""
    client = _live_client
    ids, names = await _source_ids()
    sem = asyncio.Semaphore(CATCHUP_PARALLEL)
    await asyncio.gather(*(_catch_up_one(client, t, sem) for t in [*ids, *names]))


async def _catch_up_one(client, target, sem) -> None:
    async with sem:
        try:
            entity = await client.get_entity(target)
            from telethon import utils as tg_utils
            peer_id = tg_utils.get_peer_id(entity)
            last = int((await db.get(f"live_last:{peer_id}", "0")) or 0)
            if not last:
                newest = await client.get_messages(entity, limit=1)
                if newest:
                    await db.set(f"live_last:{peer_id}", str(newest[0].id))
                return
            missed = [m async for m in client.iter_messages(entity, min_id=last, limit=200) if m.document]
            for m in reversed(missed):
                await _queue.put(m)
        except Exception as exc:
            log.warning("Catch-up for %s failed: %s", target, exc)
            return


async def start_live(bot) -> bool:
    global _live_client, _live_bot, _queue, _worker, _catchup, _me_label
    _live_bot = bot
    if _live_client is not None or not (has_api() and config.TG_SESSION):
        return is_live()
    _ensure_watchdog()  # keeps retrying even if this first connect fails
    from telethon import events
    client = _new_client(config.TG_SESSION)
    try:
        await client.connect()
        if not await client.is_user_authorized():
            log.warning("Live mirror: session not authorized; owner must login again")
            await client.disconnect()
            return False
        me = await client.get_me()
        _me_label = " ".join(x for x in [me.first_name, me.last_name] if x) + (f" (@{me.username})" if me.username else "")
        await client.get_dialogs(limit=None)  # subscribe to channel updates
    except Exception as exc:
        log.error("Live mirror start failed: %s", exc)
        try:
            await client.disconnect()
        except Exception:
            pass
        return False

    async def on_new(event):
        msg = event.message
        if not getattr(msg, "document", None):
            return
        chat = await event.get_chat()
        if not await _is_source(event.chat_id, getattr(chat, "username", "") or ""):
            return
        if await _bot_handles(event.chat_id):
            return
        await _queue.put(msg)

    client.add_event_handler(on_new, events.NewMessage())
    _live_client = client
    _queue = asyncio.Queue()
    _workers[:] = [asyncio.create_task(_run_worker(), name=f"live-mirror-worker-{i}") for i in range(LIVE_WORKERS)]
    _worker = _workers[0]
    _catchup = asyncio.create_task(_catch_up(), name="live-mirror-catchup")
    _ensure_watchdog()
    log.info("Live mirror started as %s", _me_label)
    return True


def _ensure_watchdog() -> None:
    global _watchdog
    if _watchdog is None or _watchdog.done():
        _watchdog = asyncio.create_task(_watch(), name="live-mirror-watchdog")


async def _watch() -> None:
    """Reconnect the live account automatically if Telegram drops the connection."""
    while True:
        await asyncio.sleep(60)
        try:
            if _live_bot is None or not (has_api() and config.TG_SESSION):
                continue
            if _live_client is not None and _live_client.is_connected():
                continue
            log.warning("Live mirror disconnected — reconnecting")
            await stop_live(keep_watchdog=True)
            if not await start_live(_live_bot):
                await _notify_owner("reconnect_failed",
                                    "⚠️ <b>Live Mirror band ho gaya</b>\nAccount reconnect nahi hua. "
                                    "Owner Panel → 🔐 Login Account se dobara login karo.")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("Live mirror watchdog error: %s", exc)


async def stop_live(keep_watchdog: bool = False) -> None:
    global _live_client, _worker, _catchup, _watchdog
    tasks = [_catchup, _worker, *_workers] + ([] if keep_watchdog else [_watchdog])
    _workers.clear()
    if not keep_watchdog:
        _watchdog = None
    for task in tasks:
        if task is not None and not task.done():
            task.cancel()
    _worker = _catchup = None
    if _live_client is not None:
        try:
            await _live_client.disconnect()
        except Exception:
            pass
    _live_client = None


__all__ = ["load_saved_credentials", "start_login", "submit_code", "submit_password", "cancel_login",
           "logout", "status_text", "start_live", "stop_live", "is_live", "resolve_chat", "set_api", "has_api",
           "import_to_main", "search_sources"]
