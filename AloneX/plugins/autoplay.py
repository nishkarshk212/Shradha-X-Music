# Copyright (c) 2025 TheHamkerAlone
# Licensed under the MIT License.
# This file is part of AloneXMusic
# ALONE-CODER

from pyrogram import filters, types

from AloneX import app, config, db, lang
from AloneX.helpers import can_manage_vc


@app.on_message(
    filters.command(["autoplay", "auto", "ap"]) & filters.group & ~app.bl_users
)
@lang.language()
@can_manage_vc
async def _autoplay(_, m: types.Message):
    if not config.AUTO_PLAY:
        return await m.reply_text(
            "AutoPlay is disabled globally by the owner (set <code>AUTO_PLAY=True</code> to enable)."
        )

    setting = await db.get_autoplay(m.chat.id)
    setting = not setting
    await db.set_autoplay(m.chat.id, setting)

    await m.reply_text(m.lang["autoplay_on" if setting else "autoplay_off"])
