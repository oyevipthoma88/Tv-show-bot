"""🔔 New-episode alerts for users who follow a show.

New uploads are collected for a few seconds and then sent as ONE message per
follower per show, so a burst of uploads (or a restart catch-up) never spams.
"""
from __future__ import annotations

import asyncio
import logging
from html import escape

from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import InlineKeyboardMarkup

from db import db
from keyboards import button, episode_button_label, episode_text

log = logging.getLogger("alerts")

BATCH_DELAY_SECONDS = 20
SEND_GAP_SECONDS = 0.05      # ~20 messages/second, under Telegram's broadcast limit
MAX_EPISODE_BUTTONS = 5

_pending: dict[str, list[int]] = {}
_flush_task: asyncio.Task | None = None


async def queue_new_episode(bot, msg_id: int) -> None:
    """Call right after a NEW live upload is indexed (never for historical scans)."""
    global _flush_task
    try:
        if await db.get("episode_alerts_enabled", "1") == "0":
            return
        row = await db.movie(msg_id)
        if not row or not row["show_key"]:
            return
        if not await db.mark_alert_sent(msg_id):
            return
        _pending.setdefault(row["show_key"], []).append(msg_id)
        if _flush_task is None or _flush_task.done():
            _flush_task = asyncio.create_task(_flush_later(bot), name="episode-alerts")
    except Exception:
        log.exception("Could not queue episode alert for %s", msg_id)


async def _flush_later(bot) -> None:
    await asyncio.sleep(BATCH_DELAY_SECONDS)
    batch = dict(_pending)
    _pending.clear()
    for key, ids in batch.items():
        try:
            await _send_show_alert(bot, key, ids)
        except Exception:
            log.exception("Episode alert failed for show %s", key)


def _alert_markup(rows: list) -> InlineKeyboardMarkup:
    keyboard = [[button("▶️ " + episode_button_label(r, with_title=False)[:60],
                        callback_data=f"send:{r['msg_id']}", style="success")]
                for r in rows[:MAX_EPISODE_BUTTONS]]
    newest = rows[0]["msg_id"]
    keyboard.append([
        button("📂 All Episodes", callback_data=f"eps:{newest}:0"),
        button("🔕 Unfollow", callback_data=f"fl:{newest}", style="danger"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def alert_text(rows: list) -> str:
    top = rows[0]
    title = escape(str(top["title"] or "Show"))
    if len(rows) == 1:
        ep = episode_text(top)
        details = " • ".join(x for x in [
            f"🎞 {ep}" if ep else "",
            f"🎥 {top['quality']}" if top["quality"] and top["quality"] != "Unknown" else "",
            f"💾 {top['size']}" if top["size"] else "",
        ] if x)
        return (
            "🔔 <b>Naya Episode Aa Gaya!</b>\n\n"
            f"📺 <b>{title}</b>\n"
            + (f"{details}\n" if details else "")
            + "\n👇 Tap karke abhi dekho"
        )
    return (
        f"🔔 <b>{len(rows)} Naye Episodes Aa Gaye!</b>\n\n"
        f"📺 <b>{title}</b>\n\n👇 Jo chahiye tap karo (sabse naya upar)"
    )


async def _send_show_alert(bot, key: str, ids: list[int]) -> None:
    rows = [r for r in [await db.movie(i) for i in ids] if r]
    if not rows:
        return
    rows.sort(key=lambda r: (int(r["added_at"] or 0), int(r["msg_id"])), reverse=True)
    followers = await db.followers(key)
    if not followers:
        return
    text, markup = alert_text(rows), _alert_markup(rows)
    sent = 0
    for user_id in followers:
        for attempt in range(2):
            try:
                await bot.send_message(user_id, text, reply_markup=markup)
                sent += 1
                break
            except TelegramRetryAfter as exc:
                await asyncio.sleep(exc.retry_after + 1)
            except TelegramForbiddenError:
                break  # user blocked the bot
            except Exception as exc:
                log.debug("Alert to %s failed: %s", user_id, exc)
                break
        await asyncio.sleep(SEND_GAP_SECONDS)
    log.info("Episode alert '%s': %s/%s followers notified", rows[0]["title"], sent, len(followers))


__all__ = ["queue_new_episode", "alert_text"]
