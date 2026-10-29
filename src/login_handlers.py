"""Owner Panel → 🔐 Login Account / 📡 Live Mirror."""
from __future__ import annotations

import logging
from html import escape

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

import userbot
from config import OWNER_IDS
from db import db
from keyboards import button

router = Router()


class Login(StatesGroup):
    api = State()
    phone = State()
    code = State()
    password = State()


def _login_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [button("🔑 Login New Account", callback_data="lg:start", style="success")],
        [button("🔄 Restart Live Mirror", callback_data="lg:restart"),
         button("🚪 Logout", callback_data="lg:logout", style="danger")],
        [button("⚙️ Change API ID/HASH", callback_data="lg:api")],
        [button("⬅️ Owner Panel", callback_data="op:home")],
    ])


def _cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[button("❌ Cancel", callback_data="lg:cancel", style="danger")]])


async def _owner(cb: CallbackQuery) -> bool:
    if cb.from_user.id not in OWNER_IDS:
        await cb.answer("Only owner", show_alert=True)
        return False
    await cb.answer()
    return True


@router.callback_query(F.data == "op:login")
async def login_home(cb: CallbackQuery, state: FSMContext):
    if not await _owner(cb):
        return
    await state.clear()
    await cb.message.answer(
        "🔐 <b>Login Account</b>\n\n" + await userbot.status_text() +
        "\n\nJis account ne source channel (non-admin) join kiya hai usse login karo. "
        "Wo account MAIN_DATA channel me admin (post permission) hona chahiye — "
        "naye uploads turant MAIN_DATA me share honge.",
        reply_markup=_login_kb(),
    )


@router.callback_query(F.data == "lg:start")
async def login_start(cb: CallbackQuery, state: FSMContext):
    if not await _owner(cb):
        return
    if not userbot.has_api():
        await state.set_state(Login.api)
        return await cb.message.answer(
            "Step 1/3: <b>API ID aur API HASH</b> bhejo (my.telegram.org → API development tools):\n"
            "<code>1234567 abcdef0123456789abcdef0123456789</code>", reply_markup=_cancel_kb())
    await state.set_state(Login.phone)
    await cb.message.answer("📱 Phone number country code ke saath bhejo:\n<code>+919876543210</code>",
                            reply_markup=_cancel_kb())


@router.callback_query(F.data == "lg:api")
async def login_api(cb: CallbackQuery, state: FSMContext):
    if not await _owner(cb):
        return
    await state.set_state(Login.api)
    await cb.message.answer("API ID aur API HASH bhejo:\n<code>1234567 abcdef0123456789abcdef0123456789</code>",
                            reply_markup=_cancel_kb())


@router.message(Login.api, F.from_user.id.in_(OWNER_IDS))
async def got_api(message: Message, state: FSMContext):
    parts = (message.text or "").replace(",", " ").split()
    if len(parts) != 2 or not parts[0].isdigit() or len(parts[1]) < 20:
        return await message.answer("❌ Format: <code>API_ID API_HASH</code>")
    await userbot.set_api(int(parts[0]), parts[1])
    try:
        await message.delete()
    except Exception:
        pass
    await state.set_state(Login.phone)
    await message.answer("✅ API saved.\n📱 Ab phone number bhejo:\n<code>+919876543210</code>", reply_markup=_cancel_kb())


@router.message(Login.phone, F.from_user.id.in_(OWNER_IDS))
async def got_phone(message: Message, state: FSMContext):
    phone = "".join(ch for ch in (message.text or "") if ch.isdigit() or ch == "+")
    if len(phone) < 8:
        return await message.answer("❌ Sahi phone number bhejo, jaise <code>+919876543210</code>")
    try:
        await userbot.start_login(message.from_user.id, phone)
    except Exception as exc:
        await state.clear()
        return await message.answer(f"❌ OTP nahi gaya: <code>{escape(str(exc))}</code>", reply_markup=_login_kb())
    await state.set_state(Login.code)
    await message.answer(
        "📩 Telegram ne OTP bheja hai.\n\n⚠️ OTP <b>spaces ke saath</b> bhejo warna Telegram code expire kar deta hai:\n"
        "<code>1 2 3 4 5</code>", reply_markup=_cancel_kb())


@router.message(Login.code, F.from_user.id.in_(OWNER_IDS))
async def got_code(message: Message, state: FSMContext):
    try:
        result = await userbot.submit_code(message.from_user.id, message.text or "")
    except Exception as exc:
        await state.clear()
        await userbot.cancel_login(message.from_user.id)
        return await message.answer(f"❌ Login fail: <code>{escape(str(exc))}</code>\nDobara try karo.",
                                    reply_markup=_login_kb())
    if result == "password":
        await state.set_state(Login.password)
        return await message.answer("🔒 Is account pe 2-Step Verification hai. Password bhejo:", reply_markup=_cancel_kb())
    await _done(message, state)


@router.message(Login.password, F.from_user.id.in_(OWNER_IDS))
async def got_password(message: Message, state: FSMContext):
    try:
        await message.delete()
    except Exception:
        pass
    try:
        await userbot.submit_password(message.from_user.id, message.text or "")
    except Exception as exc:
        await state.clear()
        await userbot.cancel_login(message.from_user.id)
        return await message.answer(f"❌ Password galat / login fail: <code>{escape(str(exc))}</code>",
                                    reply_markup=_login_kb())
    await _done(message, state)


async def _done(message: Message, state: FSMContext):
    await state.clear()
    sources = await db.get("movie_channels", "")
    hint = "" if sources else "\n\n➡️ Ab Owner Panel → 🎞 Source Channels me source channel ID/username set karo."
    await message.answer("✅ <b>Login successful!</b>\n" + await userbot.status_text() + hint, reply_markup=_login_kb())


@router.callback_query(F.data == "lg:cancel")
async def login_cancel(cb: CallbackQuery, state: FSMContext):
    if not await _owner(cb):
        return
    await state.clear()
    await userbot.cancel_login(cb.from_user.id)
    await cb.message.answer("❌ Cancelled.", reply_markup=_login_kb())


@router.callback_query(F.data == "lg:logout")
async def login_logout(cb: CallbackQuery, state: FSMContext):
    if not await _owner(cb):
        return
    await state.clear()
    await userbot.logout()
    await cb.message.answer("🚪 Logout ho gaya. Live mirror band.", reply_markup=_login_kb())


@router.callback_query(F.data == "lg:restart")
async def login_restart(cb: CallbackQuery, bot: Bot):
    if not await _owner(cb):
        return
    await userbot.stop_live()
    ok = await userbot.start_live(bot)
    await cb.message.answer(("🟢 Live mirror restarted." if ok else "❌ Start nahi hua — pehle login karo.") +
                            "\n" + await userbot.status_text(), reply_markup=_login_kb())


def _live_kb(enabled: bool) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [button("🔴 Turn OFF" if enabled else "🟢 Turn ON", callback_data="lv:toggle",
                style="danger" if enabled else "success")],
        [button("🔐 Login Account", callback_data="op:login"), button("⬅️ Owner Panel", callback_data="op:home")],
    ])


async def _live_text() -> str:
    enabled = await db.get("live_mirror_enabled", "1") != "0"
    sources = await db.get("movie_channels", "") or "not set"
    return (
        "📡 <b>Live Mirror</b>\n\n"
        f"Status: <b>{'ON' if enabled else 'OFF'}</b>\n"
        f"Sources: <code>{escape(sources)}</code>\n"
        f"{await userbot.status_text()}\n\n"
        "Source channel me jaise hi naya show/episode upload hoga, logged-in account usse turant "
        "MAIN_DATA me share karega aur users ke search me sabse upar date ke saath dikhega."
    )


@router.callback_query(F.data == "op:live")
async def live_home(cb: CallbackQuery):
    if not await _owner(cb):
        return
    enabled = await db.get("live_mirror_enabled", "1") != "0"
    await cb.message.answer(await _live_text(), reply_markup=_live_kb(enabled))


@router.callback_query(F.data == "lv:toggle")
async def live_toggle(cb: CallbackQuery):
    if not await _owner(cb):
        return
    enabled = await db.get("live_mirror_enabled", "1") != "0"
    await db.set("live_mirror_enabled", "0" if enabled else "1")
    logging.info("Live mirror toggled -> %s", not enabled)
    await cb.message.answer(await _live_text(), reply_markup=_live_kb(not enabled))
