from __future__ import annotations

import os

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


BUTTON_STYLE = os.getenv("BUTTON_STYLE", "1")
# Custom-emoji icons need the bot owner to have Premium/Fragment username; a wrong id
# makes Telegram reject the WHOLE message, so it is opt-in only.
BUTTON_ICON_CUSTOM_EMOJI_ID = os.getenv("BUTTON_ICON_CUSTOM_EMOJI_ID", "")
DEFAULT_BUTTON_STYLE = os.getenv("DEFAULT_BUTTON_STYLE", "primary")

_SUPPORTED_FIELDS = getattr(InlineKeyboardButton, "model_fields", {}) or {}


def button(text: str, *, callback_data: str | None = None, url: str | None = None,
           icon_custom_emoji_id: str | None = BUTTON_ICON_CUSTOM_EMOJI_ID,
           style: str | None = None) -> InlineKeyboardButton:
    """Build a Telegram button with optional newer custom-emoji/style fields.

    Optional fields are added only when the installed Telegram/aiogram model
    exposes them; otherwise the button remains a standard compatible button.
    """
    kwargs = {"text": text, "callback_data": callback_data, "url": url}
    if icon_custom_emoji_id and "icon_custom_emoji_id" in _SUPPORTED_FIELDS:
        kwargs["icon_custom_emoji_id"] = icon_custom_emoji_id
    effective_style = style or DEFAULT_BUTTON_STYLE
    if effective_style and BUTTON_STYLE and "style" in _SUPPORTED_FIELDS:
        kwargs["style"] = effective_style
    return InlineKeyboardButton(**kwargs)


def force_join_kb(channels: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for title, link in channels:
        kb.row(button(f"📢 Join {title}", url=link))
    kb.row(button("✅ Verify", callback_data="verify", style="success"))
    return kb.as_markup()


def main_menu(is_owner: bool, is_admin: bool = False) -> InlineKeyboardMarkup:
    """Simple home for new users: one big action, then plain-language buttons."""
    kb = InlineKeyboardBuilder()
    kb.row(button("🔎 Show Dhundho", callback_data="get_show", style="success"))
    kb.row(
        button("🆕 Naye Episode", callback_data="latest:0", style="primary"),
        button("🔔 Mere Shows", callback_data="myshows", style="primary"),
    )
    kb.row(
        button("💎 Premium", callback_data="plans", style="success"),
        button("➕ Aur Options", callback_data="more", style="primary"),
    )
    if is_owner:
        kb.row(button("🛠 Owner Panel", callback_data="op:home", style="danger"))
    elif is_admin:
        kb.row(button("➕ Add Video", callback_data="admin:addvideo", style="danger"))
    return kb.as_markup()


def more_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(
        button("🔥 Popular Shows", callback_data="trending", style="primary"),
        button("🕘 Meri History", callback_data="history", style="primary"),
    )
    kb.row(
        button("🎁 Dosto Ko Bulao", callback_data="refer", style="success"),
        button("🎟 Coupon Lagao", callback_data="coupon", style="success"),
    )
    kb.row(
        button("❓ Kaise Use Kare", callback_data="tutorial", style="primary"),
        button("🎥 Online Dekho", callback_data="online_player", style="primary"),
    )
    kb.row(button("🏠 Home", callback_data="home", style="danger"))
    return kb.as_markup()


def _field(row, key: str, default=""):
    """Read a column from sqlite Row / dict safely (Row has no .get)."""
    try:
        value = row[key]
    except (KeyError, IndexError, TypeError):
        return default
    return default if value is None else value


def _short_date(row) -> str:
    try:
        ts = int(_field(row, "added_at", 0) or 0)
    except (TypeError, ValueError):
        return ""
    if ts <= 0:
        return ""
    import datetime
    # IST display (UTC+5:30)
    d = datetime.datetime.fromtimestamp(ts + 19800, datetime.timezone.utc)
    return d.strftime("%d %b")


def episode_text(row) -> str:
    from episode import episode_label
    return episode_label(_field(row, "season", 0), _field(row, "episode", 0))


def episode_button_label(row, with_title: bool = True) -> str:
    """📅 29 Oct • Anupamaa • E1234 • 720p • 350MB  (fits Telegram's 64 chars)."""
    day = _short_date(row)
    parts = []
    ep = episode_text(row)
    if ep:
        parts.append(ep)
    quality = str(_field(row, "quality", "") or "")
    if quality and quality.lower() != "unknown":
        parts.append(quality.split()[0])
    size = str(_field(row, "size", "") or "")
    if size:
        parts.append(size)
    prefix = f"📅 {day} • " if day else "📺 "
    tail = (" • " + " • ".join(parts)) if parts else ""
    if not with_title:
        return (prefix + " • ".join(parts or ["Episode"]))[:64]
    title = str(_field(row, "title", "") or "Episode")
    year = str(_field(row, "year", "") or "")
    if year and not ep:
        title += f" ({year})"
    room = 64 - len(prefix) - len(tail)
    if room < 8:
        tail, room = "", 64 - len(prefix)
    if len(title) > room:
        title = title[: max(1, room - 1)] + "…"
    return (prefix + title + tail)[:64]


def results_kb(movies: list, query: str, extra_rows: list | None = None) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for m in movies:
        kb.row(button(episode_button_label(m), callback_data=f"send:{m['msg_id']}", style="success"))
    for row in extra_rows or []:
        kb.row(*row)
    kb.row(button("🏠 Home", callback_data="home", style="danger"))
    return kb.as_markup()


def _plan_field(plan, name: str, default: str = "") -> str:
    try:
        value = plan[name]
    except (KeyError, IndexError, TypeError):
        return default
    return str(value) if value not in (None, "") else default


def plan_label(plan) -> str:
    """Single source of truth for how a plan is shown to owner AND users."""
    emoji = _plan_field(plan, "emoji", "🎟️")
    text = f"{emoji} {plan['label']} — ₹{plan['price']}"
    tag = _plan_field(plan, "tag")
    if tag:
        text += f" — {tag}"
    return text


def plans_text(plans: list, title: str = "💰 <b>CURRENT PLANS</b>") -> str:
    """One message with every plan — exactly what the owner set."""
    lines = "\n\n".join(plan_label(p) for p in plans)
    return f"{title}\n\n{lines}"


def plans_kb(plans: list) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for p in plans:
        kb.row(button(plan_label(p)[:64], callback_data=f"buy:{p['code']}", style="success"))
    kb.row(button("🎟 Coupon Code", callback_data="coupon"))
    kb.row(button("🏠 Home", callback_data="home"))
    return kb.as_markup()


def paid_kb(code: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(button("📸 Payment Screenshot Bhejo", callback_data=f"ss:{code}"))
    kb.row(button("🏠 Home", callback_data="home"))
    return kb.as_markup()


def approve_kb(pid: int, user_id: int, code: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(
        button("✅ Approve", callback_data=f"appr:{pid}:{user_id}:{code}"),
        button("❌ Reject", callback_data=f"rej:{pid}:{user_id}", style="danger"),
    )
    return kb.as_markup()


def admin_panel_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(button("➕ Add Video", callback_data="admin:addvideo"))
    kb.row(button("🏠 Home", callback_data="home"))
    return kb.as_markup()


def owner_panel_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    # 📡 Live TV mirror (most used) on top
    kb.row(
        button("🔐 Login Account", callback_data="op:login", style="success"),
        button("📡 Live Mirror", callback_data="op:live", style="success"),
    )
    kb.row(
        button("🎞 Source Channels", callback_data="op:setchannel"),
        button("🔍 Scan Channel", callback_data="op:scan"),
    )
    kb.row(
        button("⚡ Auto-Transfer", callback_data="op:autotransfer"),
        button("🤖 Helper Bots", callback_data="op:helpers"),
    )
    kb.row(
        button("📢 Broadcast", callback_data="op:broadcast"),
        button("📊 Stats", callback_data="op:stats"),
    )
    # 💰 Money
    kb.row(
        button("💰 Plan Price", callback_data="op:price"),
        button("🎁 Gift Premium", callback_data="op:gift"),
    )
    kb.row(
        button("🎟 Create Coupon", callback_data="op:coupon"),
        button("💎 Premium Users", callback_data="op:premlist"),
    )
    kb.row(
        button("💳 QR Set", callback_data="op:qr"),
        button("🖼 Start Pic Set", callback_data="op:startpic"),
    )
    # 🎨 Look & delivery
    kb.row(
        button("📝 Caption Style", callback_data="op:caption"),
        button("🗑 Auto Delete", callback_data="op:autodelete"),
    )
    kb.row(
        button("📢 Join Channel", callback_data="op:setjoin"),
        button("🌐 Visit Channel", callback_data="op:setvisit"),
    )
    # 👥 Access
    kb.row(
        button("🔗 Verify URLs (max 5)", callback_data="op:force"),
        button("👮 Manage Admin", callback_data="op:admin"),
    )
    kb.row(
        button("📘 Set Tutorial", callback_data="op:tutorial"),
        button("🎥 Watch Online Bot", callback_data="op:online"),
    )
    kb.row(
        button("👥 Group Mode", callback_data="op:groupmode"),
        button("🏠 Home", callback_data="home"),
    )
    return kb.as_markup()


def back_panel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[button("⬅️ Owner Panel", callback_data="op:home")]]
    )


def source_approval_kb(source_chat_id: int, source_message_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(
        button("✅ Add to MAIN_DATA", callback_data=f"srcappr:{source_chat_id}:{source_message_id}", style="success"),
        button("❌ Decline", callback_data=f"srcdecl:{source_chat_id}:{source_message_id}", style="danger"),
    )
    return kb.as_markup()


def movie_link_kb(link: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(button("⬇️ Episode Kholo / Download", url=link))
    kb.row(button("🏠 Home", callback_data="home"))
    return kb.as_markup()


def browse_kb(movies: list, page: int = 0, per_page: int = 10, callback_prefix: str = "browse") -> InlineKeyboardMarkup:
    """Paginated list (trending / latest) with 📅 date + episode on every button."""
    kb = InlineKeyboardBuilder()
    start = max(0, page) * per_page
    end = min(start + per_page, len(movies))
    for m in movies[start:end]:
        kb.row(button(episode_button_label(m), callback_data=f"send:{m['msg_id']}", style="success"))
    nav = []
    if page > 0:
        nav.append(button("⬅️ Prev", callback_data=f"{callback_prefix}:{page - 1}"))
    if end < len(movies):
        nav.append(button("Next ➡️", callback_data=f"{callback_prefix}:{page + 1}"))
    if nav:
        kb.row(*nav)
    kb.row(button("🏠 Home", callback_data="home"))
    return kb.as_markup()
