"""📺 TV-show screens: Latest Uploads, All Episodes, Follow / My Shows."""
from __future__ import annotations

import datetime as _dt
from html import escape

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from db import db
from keyboards import _short_date, button, episode_button_label, episode_text

router = Router()
PER_PAGE = 10
LINE = "━━━━━━━━━━━━━━"


def _today_start_ts() -> int:
    """Midnight IST as a UTC timestamp."""
    ist = _dt.timezone(_dt.timedelta(hours=5, minutes=30))
    now = _dt.datetime.now(ist)
    return int(now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())


def _page(data: str, index: int) -> int:
    try:
        return max(0, int(data.split(":")[index]))
    except (IndexError, ValueError):
        return 0


async def _show(target, text: str, markup: InlineKeyboardMarkup, edit: bool) -> None:
    """Edit in place when paging (clean chat), otherwise send a new message."""
    message = target.message if isinstance(target, CallbackQuery) else target
    if edit and message and message.text:
        try:
            await message.edit_text(text, reply_markup=markup, disable_web_page_preview=True)
            return
        except Exception as exc:
            if "not modified" in str(exc):
                return
    await message.answer(text, reply_markup=markup, disable_web_page_preview=True)


def _nav(prefix: str, page: int, has_next: bool) -> list:
    row = []
    if page > 0:
        row.append(button("⬅️ Prev", callback_data=f"{prefix}:{page - 1}"))
    if has_next:
        row.append(button("Next ➡️", callback_data=f"{prefix}:{page + 1}"))
    return row


# ---------------- 🆕 Latest Uploads ----------------
async def latest_view(page: int) -> tuple[str, InlineKeyboardMarkup]:
    total = await db.movie_count(storage_only=True)
    today = await db.uploads_since(_today_start_ts())
    rows = await db.latest_uploads(page * PER_PAGE, PER_PAGE)
    pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    if not rows:
        text = ("🆕 <b>Latest Uploads</b>\n" + LINE + "\n\nAbhi koi episode upload nahi hua.\n"
                "Jaise hi source channel me naya episode aayega, yahan sabse upar dikhega. ⏳")
        return text, InlineKeyboardMarkup(inline_keyboard=[[button("🏠 Home", callback_data="home")]])
    text = (
        "🆕 <b>Latest Uploads</b>\n" + LINE + "\n"
        f"📅 Aaj: <b>{today}</b> naye episodes\n"
        f"📚 Total: <b>{total}</b>  •  Page {page + 1}/{pages}\n\n"
        "👇 Sabse naya sabse upar — tap karo, file turant aayegi"
    )
    keyboard = [[button(episode_button_label(r), callback_data=f"send:{r['msg_id']}", style="success")] for r in rows]
    nav = _nav("latestp", page, (page + 1) * PER_PAGE < total)
    if nav:
        keyboard.append(nav)
    keyboard.append([button("🔄 Refresh", callback_data="latestp:0"), button("🏠 Home", callback_data="home")])
    return text, InlineKeyboardMarkup(inline_keyboard=keyboard)


@router.callback_query(F.data.startswith("latest") | F.data.startswith("recent"))
async def latest_cb(cb: CallbackQuery):
    page = _page(cb.data, 1) if ":" in cb.data else 0
    await cb.answer()
    text, markup = await latest_view(page)
    # Home → new message; Prev/Next/Refresh → edit the same message.
    await _show(cb, text, markup, edit=cb.data.startswith(("latestp:", "recent:")))


@router.message(Command("latest"))
async def latest_cmd(message: Message):
    text, markup = await latest_view(0)
    await message.answer(text, reply_markup=markup, disable_web_page_preview=True)


# ---------------- 📂 All Episodes of a show ----------------
async def episodes_view(user_id: int, ref_msg_id: int, page: int) -> tuple[str, InlineKeyboardMarkup] | None:
    ref = await db.movie(ref_msg_id)
    if not ref or not ref["show_key"]:
        return None
    key = ref["show_key"]
    total = await db.show_episode_count(key)
    rows = await db.show_episodes(key, page * PER_PAGE, PER_PAGE)
    if not rows:
        return None
    newest = rows[0] if page == 0 else (await db.show_episodes(key, 0, 1))[0]
    following = await db.is_following(user_id, key)
    pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    latest_bits = " • ".join(x for x in [episode_text(newest), f"📅 {_short_date(newest)}" if _short_date(newest) else ""] if x)
    text = (
        f"📺 <b>{escape(str(newest['title'] or 'Show'))}</b>\n" + LINE + "\n"
        f"🎞 Total episodes: <b>{total}</b>\n"
        + (f"🆕 Latest: {latest_bits}\n" if latest_bits else "")
        + f"🔔 Alerts: <b>{'ON' if following else 'OFF'}</b>  •  Page {page + 1}/{pages}\n\n"
        "👇 Episode tap karo"
    )
    keyboard = [[button(episode_button_label(r, with_title=False), callback_data=f"send:{r['msg_id']}", style="success")]
                for r in rows]
    nav = _nav(f"eps:{ref_msg_id}", page, (page + 1) * PER_PAGE < total)
    if nav:
        keyboard.append(nav)
    keyboard.append([button("🔕 Unfollow" if following else "🔔 Follow — naye episode ka alert",
                            callback_data=f"fl:{ref_msg_id}", style="danger" if following else "success")])
    keyboard.append([button("🆕 Latest Uploads", callback_data="latest:0"), button("🏠 Home", callback_data="home")])
    return text, InlineKeyboardMarkup(inline_keyboard=keyboard)


@router.callback_query(F.data.startswith("eps:"))
async def episodes_cb(cb: CallbackQuery):
    try:
        ref_msg_id = int(cb.data.split(":")[1])
    except (IndexError, ValueError):
        return await cb.answer("Invalid show", show_alert=True)
    page = _page(cb.data, 2)
    view = await episodes_view(cb.from_user.id, ref_msg_id, page)
    if not view:
        return await cb.answer("Is show ke episodes abhi available nahi hain.", show_alert=True)
    await cb.answer()
    await _show(cb, view[0], view[1], edit=True)


# ---------------- 🔔 Follow / My Shows ----------------
@router.callback_query(F.data.startswith("fl:"))
async def follow_toggle(cb: CallbackQuery):
    try:
        ref = await db.movie(int(cb.data.split(":")[1]))
    except (IndexError, ValueError):
        ref = None
    if not ref or not ref["show_key"]:
        return await cb.answer("Ye show follow nahi ho sakta.", show_alert=True)
    if not await db.user(cb.from_user.id):
        await db.add_user(cb.from_user.id, cb.from_user.username or "", cb.from_user.full_name)
    title = str(ref["title"] or "Show")
    if await db.is_following(cb.from_user.id, ref["show_key"]):
        await db.unfollow(cb.from_user.id, ref["show_key"])
        await cb.answer(f"🔕 {title[:40]} unfollow ho gaya. Ab alert nahi aayega.", show_alert=True)
    else:
        await db.follow(cb.from_user.id, ref["show_key"], title)
        await cb.answer(f"🔔 {title[:40]} follow ho gaya!\nNaya episode aate hi message milega.", show_alert=True)
    try:
        from snapshot import request_snapshot
        await request_snapshot(cb.bot)
    except Exception:
        pass
    # Refresh the All Episodes screen if that is where the button was pressed.
    if cb.message and cb.message.text and cb.message.text.startswith("📺"):
        view = await episodes_view(cb.from_user.id, int(ref["msg_id"]), 0)
        if view:
            await _show(cb, view[0], view[1], edit=True)


async def my_shows_view(user_id: int) -> tuple[str, InlineKeyboardMarkup]:
    rows = await db.follows(user_id)
    if not rows:
        text = ("🔔 <b>My Shows</b>\n" + LINE + "\n\nAbhi koi show follow nahi kiya.\n\n"
                "👉 Show ka naam bhejo, results me <b>🔔 Follow</b> dabao — "
                "naya episode aate hi bot khud message karega.")
        return text, InlineKeyboardMarkup(inline_keyboard=[
            [button("🆕 Latest Uploads", callback_data="latest:0")],
            [button("🏠 Home", callback_data="home")],
        ])
    keyboard = []
    for f in rows[:30]:
        latest = await db.latest_episode_id(f["show_key"])
        count = await db.show_episode_count(f["show_key"])
        label = f"📺 {f['show_title'] or f['show_key']} ({count})"[:56]
        open_btn = button(label, callback_data=f"eps:{latest}:0" if latest else "myshows", style="success")
        keyboard.append([open_btn, button("🔕", callback_data=f"ufk:{f['id']}", style="danger")])
    keyboard.append([button("🏠 Home", callback_data="home")])
    text = ("🔔 <b>My Shows</b>\n" + LINE + "\n"
            f"Tum <b>{len(rows)}</b> show(s) follow kar rahe ho.\n"
            "Naya episode aate hi alert milega. 🔕 se unfollow karo.")
    return text, InlineKeyboardMarkup(inline_keyboard=keyboard)


@router.callback_query(F.data == "myshows")
async def my_shows_cb(cb: CallbackQuery):
    await cb.answer()
    text, markup = await my_shows_view(cb.from_user.id)
    await _show(cb, text, markup, edit=False)


@router.message(Command("myshows"))
async def my_shows_cmd(message: Message):
    text, markup = await my_shows_view(message.from_user.id)
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data.startswith("ufk:"))
async def unfollow_from_list(cb: CallbackQuery):
    try:
        follow_id = int(cb.data.split(":")[1])
    except (IndexError, ValueError):
        return await cb.answer()
    await db.unfollow_id(cb.from_user.id, follow_id)
    await cb.answer("🔕 Unfollow ho gaya")
    text, markup = await my_shows_view(cb.from_user.id)
    await _show(cb, text, markup, edit=True)


def follow_rows(top, following: bool, total: int, shown: int) -> list:
    """Extra buttons under search results for the top show."""
    if not top or not top["show_key"]:
        return []
    rows = []
    if total > 1:
        rows.append([button(f"📂 Saare Episodes ({total})", callback_data=f"eps:{top['msg_id']}:0")])
    rows.append([button("🔕 Unfollow" if following else "🔔 Follow — naye episode ka alert",
                        callback_data=f"fl:{top['msg_id']}", style="danger" if following else "success")])
    return rows


__all__ = ["router", "latest_view", "episodes_view", "my_shows_view", "follow_rows"]
