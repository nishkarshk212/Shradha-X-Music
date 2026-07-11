import asyncio
from pathlib import Path

from pyrogram import filters, types

from AloneX import anon, app, config, db, lang, queue, tg, yt
from AloneX.helpers import buttons, utils
from AloneX.helpers._play import checkUB


async def bg_download_task(track):
    if not track.file_path:
        try:
            path = await yt.download(track.id, video=track.video)
            if path:
                track.file_path = path
        except Exception:
            pass


def playlist_to_queue(chat_id: int, tracks: list) -> str:
    text = "<blockquote expandable>"
    for track in tracks:
        pos = queue.add(chat_id, track)
        text += f"<b>{pos}.</b> {track.title}\n"
        asyncio.create_task(bg_download_task(track))
    text = text[:1948] + "</blockquote>"
    return text


async def _play_track(
    m: types.Message,
    file,
    video: bool,
    tracks: list = None,
    force: bool = False,
) -> None:
    """Shared play body used by /play, /playlist and the /suggest callback."""
    tracks = tracks or []
    sent = m
    mention = (m.from_user.mention if getattr(m, "from_user", None) else "ᴜsᴇʀ")

    if file.duration_sec > config.DURATION_LIMIT:
        return await sent.edit_text(
            m.lang["play_duration_limit"].format(config.DURATION_LIMIT // 60)
        )

    if await db.is_logger():
        await utils.play_log(m, file.title, file.duration)

    file.user = mention
    if force:
        queue.force_add(m.chat.id, file)
    else:
        position = queue.add(m.chat.id, file)

        if position != 0 or await db.get_call(m.chat.id):
            asyncio.create_task(bg_download_task(file))
            await sent.edit_text(
                m.lang["play_queued"].format(
                    position,
                    file.url,
                    file.title,
                    file.duration,
                    mention,
                ),
                reply_markup=buttons.play_queued(
                    m.chat.id, file.id, m.lang["play_now"]
                ),
            )
            if tracks:
                added = playlist_to_queue(m.chat.id, tracks)
                await app.send_message(
                    chat_id=m.chat.id,
                    text=m.lang["playlist_queued"].format(len(tracks)) + added,
                )
            return

    if not file.file_path:
        fname = f"downloads/{file.id}.{'mp4' if video else 'webm'}"
        if Path(fname).exists():
            file.file_path = fname
        else:
            from AloneX.plugins.settings import get_chat_settings
            settings = await get_chat_settings(m.chat.id)

            await sent.edit_text(m.lang["play_downloading"])
            stream_url = None
            if settings.get("quickplay", True):
                stream_url = await yt.get_stream_url(file.id, video=video)

            if stream_url:
                file.file_path = stream_url
            else:
                file.file_path = await yt.download(file.id, video=video)

    await anon.play_media(chat_id=m.chat.id, message=sent, media=file)
    if not tracks:
        return
    added = playlist_to_queue(m.chat.id, tracks)
    await app.send_message(
        chat_id=m.chat.id,
        text=m.lang["playlist_queued"].format(len(tracks)) + added,
    )


@app.on_message(
    filters.command(["play", "playforce", "vplay", "vplayforce"])
    & filters.group
    & ~app.bl_users
)
@lang.language()
@checkUB
async def play_hndlr(
    _,
    m: types.Message,
    force: bool = False,
    m3u8: bool = False,
    video: bool = False,
    url: str = None,
) -> None:
    sent = await m.reply_text(m.lang["play_searching"])
    # The shared body edits `sent`; give it the message-like object it expects.
    setattr(sent, "chat", m.chat)
    setattr(sent, "lang", m.lang)
    file = None
    mention = m.from_user.mention
    media = tg.get_media(m.reply_to_message) if m.reply_to_message else None
    tracks = []

    if url:
        if "playlist" in url:
            await sent.edit_text(m.lang["playlist_fetch"])
            tracks = await yt.playlist(
                config.PLAYLIST_LIMIT, mention, url, video
            )

            if not tracks:
                return await sent.edit_text(m.lang["playlist_error"])

            file = tracks[0]
            tracks.remove(file)
            file.message_id = sent.id
        else:
            file = await yt.search(url, sent.id, video=video)

        if not file:
            return await sent.edit_text(
                m.lang["play_not_found"].format(config.SUPPORT_CHAT)
            )

    elif len(m.command) >= 2:
        query = " ".join(m.command[1:])
        file = await yt.search(query, sent.id, video=video)
        if not file:
            return await sent.edit_text(
                m.lang["play_not_found"].format(config.SUPPORT_CHAT)
            )

    elif media:
        setattr(sent, "lang", m.lang)
        file = await tg.download(m.reply_to_message, sent)

    if not file:
        return await sent.edit_text(m.lang["play_usage"])

    await _play_track(m, file, video, tracks, force)


@app.on_message(
    filters.command(["playlist"]) & filters.group & ~app.bl_users
)
@lang.language()
@checkUB
async def playlist_hndlr(
    _,
    m: types.Message,
    force: bool = False,
    m3u8: bool = False,
    video: bool = False,
    url: str = None,
) -> None:
    if len(m.command) < 2:
        return await m.reply_text(m.lang["playlist_name_usage"])

    name = " ".join(m.command[1:])
    sent = await m.reply_text(m.lang["playlist_fetch"])

    tracks = await yt.playlist_by_name(
        name, m.from_user.mention, video, config.PLAYLIST_LIMIT
    )
    if not tracks:
        return await sent.edit_text(m.lang["playlist_error"])

    file = tracks[0]
    tracks.remove(file)
    file.message_id = sent.id

    # Reuse the shared play body (it edits `sent`); expose lang/chat on it.
    setattr(sent, "chat", m.chat)
    setattr(sent, "lang", m.lang)
    await _play_track(sent, file, video, tracks, force)
