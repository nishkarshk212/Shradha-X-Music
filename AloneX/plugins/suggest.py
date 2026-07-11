# Copyright (c) 2025 TheHamkerAlone
# Licensed under the MIT License.
# This file is part of AloneXMusic
# ALONE-CODER

from pyrogram import filters, types

from AloneX import app, config, lang, yt
from AloneX.helpers import buttons
from AloneX.helpers._dataclass import Track


@app.on_message(
    filters.command(["suggest", "sg"]) & filters.group & ~app.bl_users
)
@lang.language()
async def _suggest(_, m: types.Message):
    if len(m.command) < 2:
        return await m.reply_text(m.lang["suggest_usage"])

    query = " ".join(m.command[1:])
    sent = await m.reply_text(m.lang["play_searching"])

    results = await yt.suggestions(query, limit=5, video=False)
    if not results:
        return await sent.edit_text(
            m.lang["play_not_found"].format(config.SUPPORT_CHAT)
        )

    _text = f"<b>🔎 Suggestions for:</b> <code>{query}</code>\n\n"
    _text += "<i>Tap a song to play it in the voice chat.</i>"

    items = [(t.title, t.id) for t in results]

    try:
        await sent.edit_text(_text, reply_markup=buttons.suggest_markup(m.chat.id, items))
    except Exception:
        await sent.delete()
        await m.reply_text(_text, reply_markup=buttons.suggest_markup(m.chat.id, items))


@app.on_callback_query(filters.regex(r"^suggest_play") & ~app.bl_users)
@lang.language()
async def _suggest_play(_, query: types.CallbackQuery):
    args = query.data.split()
    chat_id = int(args[1])
    video_id = args[2]

    if query.message.chat.id != chat_id:
        return await query.answer(
            "This button isn't for this chat.", show_alert=True
        )

    await query.answer("Playing...", show_alert=False)

    # Turn the chosen suggestion into a Track and hand it to the shared play body.
    from AloneX.plugins.play import _play_track

    track = Track(
        id=video_id,
        channel_name="",
        duration="",
        duration_sec=0,
        title="",
        url=f"https://www.youtube.com/watch?v={video_id}",
        user=query.from_user.mention,
        video=False,
    )

    # The shared body edits the (bot-sent) message; expose chat/lang on it.
    msg = query.message
    setattr(msg, "chat", query.message.chat)
    setattr(msg, "lang", query.lang)
    await _play_track(msg, track, video=False)
