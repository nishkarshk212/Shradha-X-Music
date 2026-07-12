# Copyright (c) 2025 TheHamkerAlone
# Licensed under the MIT License.
# This file is part of AloneXMusic
# ALONE-CODER

from pyrogram import filters, types

from AloneX import app, config, lang, yt
from AloneX.helpers import buttons
from AloneX.helpers._dataclass import Track

# Short-lived cache of the full Track objects returned by /suggest, keyed by
# video id. The one-tap Play callback reuses the cached Track so the song
# starts with real metadata (title / duration / channel) instead of an empty
# placeholder that would render as a blank now-playing card. Cleared on each
# new /suggest; stale buttons fall back to a fresh search in the callback.
_SUGGEST_CACHE: dict[str, Track] = {}


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

    # Cache the full Track objects (with title/duration/channel/thumbnail) so
    # the one-tap Play callback can hand the shared play body a complete Track
    # instead of an empty one. Cleared each call; only the latest 5 matter.
    _SUGGEST_CACHE.clear()
    for t in results:
        _SUGGEST_CACHE[t.id] = t

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
    video_id = str(args[2])

    if query.message.chat.id != chat_id:
        return await query.answer(
            "This button isn't for this chat.", show_alert=True
        )

    await query.answer("Playing...", show_alert=False)

    # Reuse the full Track captured at /suggest time (carries title, duration,
    # channel, thumbnail). If the cache was cleared (e.g. an older suggestion
    # button after a newer /suggest), fall back to a fresh search by id.
    from AloneX.plugins.play import _play_track

    track = _SUGGEST_CACHE.get(video_id)
    if track is None:
        track = await yt.search(
            f"https://www.youtube.com/watch?v={video_id}",
            query.message.id,
            video=False,
        )
    if track is None:
        return await query.answer(
            "Couldn't load that song — try /play instead.", show_alert=True
        )

    # Normalise the bits the shared play body relies on.
    track.video = False
    track.user = query.from_user.mention
    if not track.url:
        track.url = f"https://www.youtube.com/watch?v={video_id}"

    # The shared body edits the (bot-sent) message; expose chat/lang on it.
    msg = query.message
    setattr(msg, "chat", query.message.chat)
    setattr(msg, "lang", query.lang)
    await _play_track(msg, track, video=False)
