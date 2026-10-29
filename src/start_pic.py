"""Start pic is stored INSIDE MAIN_DATA (pinned, tagged #START_PIC) so it survives
reboots even if MongoDB/SQLite state is lost."""
from __future__ import annotations

import logging

import config
from db import db

TAG = "#START_PIC"


async def save_start_pic(bot, photo) -> str:
    """Upload `photo` (file_id or URL) to MAIN_DATA, pin it, return the durable file_id."""
    sent = await bot.send_photo(config.MAIN_DATA, photo=photo, caption=TAG, disable_notification=True)
    file_id = sent.photo[-1].file_id
    old = int((await db.get("start_pic_msg", "0")) or 0)
    try:
        await bot.pin_chat_message(config.MAIN_DATA, sent.message_id, disable_notification=True)
    except Exception as exc:
        logging.warning("Start pic pin failed (bot needs pin permission): %s", exc)
    if old and old != sent.message_id:
        try:
            await bot.delete_message(config.MAIN_DATA, old)
        except Exception:
            pass
    await db.set("start_pic", file_id)
    await db.set("start_pic_msg", str(sent.message_id))
    return file_id


async def restore_start_pic(bot) -> bool:
    """Called at boot: if the local setting is empty, recover it from MAIN_DATA."""
    if (await db.get("start_pic", "") or "").strip() and (await db.get("start_pic_msg", "0")) != "0":
        return False
    file_id = ""
    msg_id = 0
    try:
        chat = await bot.get_chat(config.MAIN_DATA)
        pinned = chat.pinned_message
        if pinned and pinned.photo and (pinned.caption or "").strip() == TAG:
            file_id, msg_id = pinned.photo[-1].file_id, pinned.message_id
    except Exception as exc:
        logging.warning("Start pic pinned lookup failed: %s", exc)
    if not file_id:
        # Pinned slot reused by something else: search MAIN_DATA via the user session.
        try:
            from mtproto_importer import _get_client
            client = await _get_client()
            if client is not None:
                async for m in client.iter_messages(config.MAIN_DATA, search=TAG, limit=5):
                    if m.photo and (m.message or "").strip() == TAG:
                        msg_id = m.id
                        fw = await bot.forward_message(config.MAIN_DATA, config.MAIN_DATA, m.id,
                                                       disable_notification=True)
                        file_id = fw.photo[-1].file_id if fw.photo else ""
                        try:
                            await bot.delete_message(config.MAIN_DATA, fw.message_id)
                        except Exception:
                            pass
                        break
        except Exception as exc:
            logging.warning("Start pic search failed: %s", exc)
    if file_id:
        await db.set("start_pic", file_id)
        await db.set("start_pic_msg", str(msg_id))
        logging.info("Start pic restored from MAIN_DATA (msg %s)", msg_id)
        return True
    # Existing db pic (e.g. URL) without a MAIN_DATA copy: back it up now.
    current = (await db.get("start_pic", "") or "").strip()
    if current:
        try:
            await save_start_pic(bot, current)
            logging.info("Start pic backed up into MAIN_DATA")
        except Exception as exc:
            logging.warning("Start pic backup failed: %s", exc)
    return False
