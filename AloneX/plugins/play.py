import asyncio
from pathlib import Path

from pyrogram import filters, types

from AloneX import anon, app, config, db, lang, queue, tg, yt
from AloneX.core.calls import schedule_bg_fetch
from AloneX.helpers import buttons, utils
from AloneX.helpers._play import checkUB


async def bg_download_task(track):
    # Delegated to the shared, dedup-guarded background fetcher in core.calls
    # so queued + prefetched downloads never run twice for the same video.
    schedule_bg_fetch(track)


def playlist_to_queue(chat_id: int, tracks: list) -> str:
    text = "<blockquote expandable>"
    for track in tracks:
        pos = queue.add(chat_id, track)
        text += f"<b>{pos}.</b> {track.title}\n"
        asyncio.create_task(bg_download_task(track))
    text = text[:1948] + "</blockquote>"
    return text


async def _play_track(
    msg: types.Message,
    file,
    video: bool,
    tracks: list = None,
    force: bool = False,
    sent: types.Message = None,
) -> None:
    """Shared play body used by /play, /playlist and the /suggest callback.

    `msg` is the originating command/callback message (source of chat id,
    sender mention, and language). `sent` is the bot-owned reply message that
    gets edited as the track progresses. They differ when cmd_delete is on
    (the command message is deleted) — never edit `msg` directly.
    """
    tracks = tracks or []
    if sent is None:
        sent = msg
    chat_id = msg.chat.id
    mention = (msg.from_user.mention if getattr(msg, "from_user", None) else "ᴜsᴇʀ")

    if file.duration_sec > config.DURATION_LIMIT:
        return await sent.edit_text(
            msg.lang["play_duration_limit"].format(config.DURATION_LIMIT // 60)
        )

    if await db.is_logger():
        await utils.play_log(msg, file.title, file.duration)

    file.user = mention
    if force:
        queue.force_add(chat_id, file)
    else:
        position = queue.add(chat_id, file)

        if position != 0 or await db.get_call(chat_id):
            asyncio.create_task(bg_download_task(file))
            await sent.edit_text(
                msg.lang["play_queued"].format(
                    position,
                    file.url,
                    file.title,
                    file.duration,
                    mention,
                ),
                reply_markup=buttons.play_queued(
                    chat_id, file.id, msg.lang["play_now"]
                ),
            )
            if tracks:
                added = playlist_to_queue(chat_id, tracks)
                await app.send_message(
                    chat_id=chat_id,
                    text=msg.lang["playlist_queued"].format(len(tracks)) + added,
                )
            return

    if not file.file_path:
        # Look for any already-downloaded file for this id. Extensions vary by
        # source — the SaaS API writes .mp3 for audio and .mp4 for video; older
        # yt-dlp-era files may still be .webm/.m4a/.opus/.ogg. We accept any
        # non-empty match so a repeat play of the same track reuses the local
        # file instead of re-hitting the API.
        cached = None
        exts = ("mp4", "webm") if video else ("mp3", "m4a", "webm", "opus", "ogg")
        for ext in exts:
            cand = f"downloads/{file.id}.{ext}"
            p = Path(cand)
            if p.exists() and p.stat().st_size > 0:
                cached = cand
                break
        if cached:
            file.file_path = cached
        else:
            # Straight to download — no live-stream attempt.
            #
            # The SaaS API is neither progressive nor cached: measured
            # time-to-first-byte is ~13-17 s for *every* request (it runs the
            # full yt-dlp resolve, buffers the whole file, then dumps it in
            # ~1.5 s), and re-resolves even the same id seconds later. So a
            # stream URL can never start playing before its bytes exist, and
            # handing one to ffmpeg only makes ffmpeg trigger its OWN 17 s
            # resolve (which then trips its check_stream timeout). Downloading
            # once is strictly faster and reliable. Instant playback is only
            # possible when the file is already on local disk (the `cached`
            # branch above) — keep cleanup off if you want popular songs to
            # replay instantly.
            await sent.edit_text(msg.lang["play_downloading"])
            file.file_path = await yt.download(file.id, video=video)

    await anon.play_media(chat_id=chat_id, message=sent, media=file)
    if not tracks:
        return
    added = playlist_to_queue(chat_id, tracks)
    await app.send_message(
        chat_id=chat_id,
        text=msg.lang["playlist_queued"].format(len(tracks)) + added,
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

    await _play_track(m, file, video, tracks, force, sent=sent)


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

    # Reuse the shared play body (it edits `sent`); pass both msg and sent.
    setattr(sent, "chat", m.chat)
    setattr(sent, "lang", m.lang)
    await _play_track(m, file, video, tracks, force, sent=sent)
