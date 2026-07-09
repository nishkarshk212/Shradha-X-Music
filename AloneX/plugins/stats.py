# Copyright (c) 2025 TheHamkerAlone
# Licensed under the MIT License.
# This file is part of AloneXMusic


import os
import platform
import sys

import psutil
from pyrogram import __version__, filters, types
from pytgcalls import __version__ as pytgver

from AloneX import app, config, db, lang, userbot
from AloneX.plugins import all_modules


@app.on_message(filters.command(["stats"]) & filters.group & ~app.bl_users)
@lang.language()
async def _stats(_, m: types.Message):
    sent = await m.reply_photo(
        photo=config.PING_IMG,
        caption=m.lang["stats_fetching"],
    )

    pid = os.getpid()
    _utext = m.lang["stats_user"].format(
        app.name,
        len(userbot.clients),
        config.AUTO_LEAVE,
        len(db.blacklisted),
        len(app.bl_users),
        len(app.sudoers),
        len(await db.get_chats()),
        len(await db.get_users()),
    )
    if m.from_user.id in app.sudoers:
        process = psutil.Process(pid)
        storage = psutil.disk_usage("/")
        _utext += m.lang["stats_sudo"].format(
            len(all_modules),
            platform.system(),
            f"{process.memory_info().rss / 1024**2:.2f}",
            round(psutil.virtual_memory().total / (1024.0**3)),
            process.cpu_percent(interval=1.0),
            psutil.cpu_count(logical=False),
            f"{storage.used / (1024.0**3):.2f}",
            f"{storage.total / (1024.0**3):.2f}",
            sys.version.split()[0],
            __version__,
            pytgver,
        )
    await sent.edit_caption(_utext)


@app.on_message(filters.command(["usage"]) & ~app.bl_users)
async def _usage(_, m: types.Message):
    if m.from_user.id != config.OWNER_ID and m.from_user.id not in app.sudoers:
        return await m.reply_text("This command is only for the bot Owner.")

    sent = await m.reply_text("⚡ Fetching bot usage statistics...")

    total_played = await db.get_total_played()
    total_groups = len(await db.get_chats())
    total_users = len(await db.get_users())

    pid = os.getpid()
    process = psutil.Process(pid)
    storage = psutil.disk_usage("/")

    usage_text = (
        "📊 <b>Shradha-X-Music Usage Statistics</b>\n\n"
        f"🎵 <b>Total Songs Played:</b> {total_played}\n"
        f"👥 <b>Total Users (in DB):</b> {total_users}\n"
        f"🏘️ <b>Total Groups (in DB):</b> {total_groups}\n\n"
        "💻 <b>System Information:</b>\n"
        f"• <b>OS:</b> {platform.system()}\n"
        f"• <b>Memory Usage:</b> {process.memory_info().rss / 1024**2:.2f} MB / {round(psutil.virtual_memory().total / (1024.0**3))} GB\n"
        f"• <b>CPU Usage:</b> {process.cpu_percent(interval=0.5)}%\n"
        f"• <b>Cores:</b> {psutil.cpu_count(logical=False)}\n"
        f"• <b>Storage:</b> {storage.used / (1024.0**3):.2f} GB / {storage.total / (1024.0**3):.2f} GB\n\n"
        "🛠️ <b>Software Versions:</b>\n"
        f"• <b>Python:</b> {sys.version.split()[0]}\n"
        f"• <b>Pyrogram:</b> {__version__}\n"
        f"• <b>Py-TgCalls:</b> {pytgver}"
    )

    await sent.edit_text(usage_text)


@app.on_message(filters.command(["groups"]) & ~app.bl_users)
async def _groups(_, m: types.Message):
    if m.from_user.id != config.OWNER_ID and m.from_user.id not in app.sudoers:
        return await m.reply_text("This command is only for the bot Owner.")

    sent = await m.reply_text("🔍 Fetching groups list...")

    chats = await db.get_chats()
    if not chats:
        return await sent.edit_text("Bot is not in any groups yet.")

    text = f"🏘️ <b>Active Groups ({len(chats)} total):</b>\n\n"
    for i, chat_id in enumerate(chats, 1):
        try:
            chat = await app.get_chat(chat_id)
            text += f"{i}. <b>{chat.title}</b> (<code>{chat_id}</code>)\n"
        except Exception:
            text += f"{i}. Group (<code>{chat_id}</code>)\n"

    # Split text if it exceeds Telegram character limit
    if len(text) > 4096:
        for x in range(0, len(text), 4096):
            await m.reply_text(text[x : x + 4096])
        await sent.delete()
    else:
        await sent.edit_text(text)
