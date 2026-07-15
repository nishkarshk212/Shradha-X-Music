# Copyright (c) 2025 TheHamkerAlone
# Licensed under the MIT License.
# This file is part of AloneXMusic
# ALONE-CODER

import asyncio
import os
from ntgcalls import (ConnectionNotFound, TelegramServerError,
                      RTMPStreamingUnsupported)
from pyrogram.errors import MessageIdInvalid, MessageNotModified
from pyrogram.errors.exceptions.bad_request_400 import ChannelPrivate
from pyrogram.types import InputMediaPhoto, Message
from pytgcalls import PyTgCalls, exceptions, types
from pytgcalls.pytgcalls_session import PyTgCallsSession

from AloneX import app, config, db, lang, logger, queue, userbot, yt
from AloneX.helpers import Media, Track, buttons, thumb


async def delete_file(file_path: str, chat_id: int, video_id: str | None = None) -> None:
    """Remove downloaded media for a finished track (honours per-chat cleanup).

    ``file_path`` may be a local ``downloads/...`` path, an ``https://`` stream
    URL, or ``None``. When ``video_id`` is provided we ALSO sweep any
    ``downloads/{video_id}.*`` files a background prefetch may have written
    even if the track itself played from a live stream URL — otherwise
    completed background downloads would leak to disk indefinitely for every
    stream-played song.
    """
    try:
        from AloneX.plugins.settings import get_chat_settings
        settings = await get_chat_settings(chat_id)
        if not settings.get("cleanup", True):
            return
    except Exception:
        pass
    # 1. Delete the exact path if it points at a local file.
    if file_path and os.path.exists(file_path) and "downloads" in file_path:
        try:
            os.remove(file_path)
        except Exception:
            pass
    # 2. Sweep any leftover downloads/{video_id}.* files (bg-fetch may have
    #    completed after we started playing via a stream URL, or the file may
    #    have a different extension than we assumed).
    if video_id and os.path.isdir("downloads"):
        try:
            for name in os.listdir("downloads"):
                if name.startswith(f"{video_id}."):
                    try:
                        os.remove(os.path.join("downloads", name))
                    except Exception:
                        pass
        except Exception:
            pass


# Tracks currently being downloaded in the background so we never start a
# duplicate download for the same video id.
_bg_fetching: set[str] = set()


async def bg_fetch(media) -> None:
    """Download a track in the background if it isn't already cached.

    Used to prefetch the next queued song (so the user doesn't wait) and to
    download AutoPlay tracks (which otherwise only get a flaky live stream URL).
    """
    if not media or media.file_path:
        return
    vid = getattr(media, "id", None)
    if not vid or vid in _bg_fetching:
        return
    _bg_fetching.add(vid)
    try:
        path = await yt.download(vid, video=media.video)
        if path:
            media.file_path = path
    except Exception as e:
        logger.error(f"bg_fetch failed for {vid}: {e}")
    finally:
        _bg_fetching.discard(vid)


def schedule_bg_fetch(media) -> None:
    """Fire-and-forget a background download for a track."""
    if media and not media.file_path:
        asyncio.create_task(bg_fetch(media))


class TgCall(PyTgCalls):
    def __init__(self):
        self.clients = []
        # Per-chat consecutive AutoPlay-failure counter. When YouTube is
        # blocked (bot-check / format errors), AutoPlay would otherwise keep
        # queuing a related track that also fails and recurse forever, hammering
        # YouTube in a tight loop. We cap it and stop cleanly instead.
        self._autoplay_failures: dict[int, int] = {}

    def _autoplay_ok(self, chat_id: int) -> bool:
        return self._autoplay_failures.get(chat_id, 0) < 3

    def _note_autoplay_failure(self, chat_id: int) -> None:
        self._autoplay_failures[chat_id] = self._autoplay_failures.get(chat_id, 0) + 1

    def _reset_autoplay(self, chat_id: int) -> None:
        self._autoplay_failures[chat_id] = 0

    async def pause(self, chat_id: int) -> bool:
        client = await db.get_assistant(chat_id)
        await db.playing(chat_id, paused=True)
        return await client.pause(chat_id)

    async def resume(self, chat_id: int) -> bool:
        client = await db.get_assistant(chat_id)
        await db.playing(chat_id, paused=False)
        return await client.resume(chat_id)

    async def stop(self, chat_id: int) -> None:
        client = await db.get_assistant(chat_id)
        try:
            for item in queue.get_queue(chat_id):
                await delete_file(item.file_path, chat_id, video_id=item.id)
            queue.clear(chat_id)
            await db.remove_call(chat_id)
        except:
            pass

        try:
            await client.leave_call(chat_id, close=False)
        except:
            pass


    async def play_media(
        self,
        chat_id: int,
        message: Message,
        media: Media | Track,
        seek_time: int = 0,
    ) -> None:
        client = await db.get_assistant(chat_id)
        _lang = await lang.get_lang(chat_id)
        _thumb = (
            await thumb.generate(media)
            if isinstance(media, Track)
            else config.DEFAULT_THUMB
        )

        if not media.file_path:
            try:
                await message.edit_text(_lang["error_no_file"].format(config.SUPPORT_CHAT))
            except MessageNotModified:
                pass
            return await self.stop(chat_id)

        stream = types.MediaStream(
            media_path=media.file_path,
            audio_parameters=types.AudioQuality.HIGH,
            video_parameters=types.VideoQuality.HD_720p,
            audio_flags=types.MediaStream.Flags.REQUIRED,
            video_flags=(
                types.MediaStream.Flags.AUTO_DETECT
                if media.video
                else types.MediaStream.Flags.IGNORE
            ),
            ffmpeg_parameters=f"-ss {seek_time}" if seek_time > 1 else None,
        )
        try:
            await client.play(
                chat_id=chat_id,
                stream=stream,
                config=types.GroupCallConfig(auto_start=False),
            )
            if not seek_time:
                media.time = 1
                await db.add_call(chat_id)
                await db.increment_played()
                text = _lang["play_media"].format(
                    media.url,
                    media.title,
                    media.duration,
                    media.user,
                )
                keyboard = await buttons.controls(chat_id)
                try:
                    try:
                        await message.edit_media(
                            media=InputMediaPhoto(
                                media=_thumb,
                                caption=text,
                            ),
                            reply_markup=keyboard,
                        )
                        media.message_id = message.id
                    except MessageIdInvalid:
                        media.message_id = (await app.send_photo(
                            chat_id=chat_id,
                            photo=_thumb,
                            caption=text,
                            reply_markup=keyboard,
                        )).id
                except MessageNotModified:
                    pass
            # Prefetch the next queued track so it's ready when this ends.
            await self._prefetch_next(chat_id)
        except FileNotFoundError:
            try:
                await message.edit_text(_lang["error_no_file"].format(config.SUPPORT_CHAT))
            except MessageNotModified:
                pass
            await self.play_next(chat_id)
        except exceptions.NoActiveGroupCall:
            await self.stop(chat_id)
            try:
                await message.edit_text(_lang["error_no_call"])
            except MessageNotModified:
                pass
        except exceptions.NoAudioSourceFound:
            # If we were using a stream URL, try downloading the file and play again
            if media.id and not media.file_path.startswith("downloads/"):
                try:
                    await message.edit_text(_lang["play_downloading"])
                except MessageNotModified:
                    pass
                media.file_path = await yt.download(media.id, video=media.video)
                if media.file_path:
                    return await self.play_media(chat_id, message, media, seek_time)
            
            try:
                await message.edit_text(_lang["error_no_audio"])
            except MessageNotModified:
                pass
            await self.play_next(chat_id)
        except asyncio.TimeoutError:
            # pytgcalls probes the media with ffmpeg (check_stream) before it
            # opens the call. When we hand it a live SaaS stream URL (Quick
            # Play fast-path) and the API is slow to send its first bytes, that
            # probe times out and — without this handler — bubbles up as an
            # uncaught "Unexpected exception raised in MessageHandler", killing
            # playback entirely. Recover the same way as NoAudioSourceFound: if
            # we were streaming a URL, download the full file and replay it from
            # disk (slower, but reliable). Only genuinely fails if the download
            # itself can't produce a file.
            if (
                media.id
                and media.file_path
                and not media.file_path.startswith("downloads/")
            ):
                logger.warning(
                    f"[Stream] ffmpeg probe timed out for {media.id}; "
                    "falling back to full download."
                )
                try:
                    await message.edit_text(_lang["play_downloading"])
                except MessageNotModified:
                    pass
                media.file_path = await yt.download(media.id, video=media.video)
                if media.file_path:
                    return await self.play_media(chat_id, message, media, seek_time)

            try:
                await message.edit_text(_lang["error_no_audio"])
            except MessageNotModified:
                pass
            await self.play_next(chat_id)
        except (ConnectionNotFound, TelegramServerError):
            await self.stop(chat_id)
            try:
                await message.edit_text(_lang["error_tg_server"])
            except MessageNotModified:
                pass
        except RTMPStreamingUnsupported:
            await self.stop(chat_id)
            try:
                await message.edit_text(_lang["error_rtmp"])
            except MessageNotModified:
                pass
        except MessageIdInvalid:
            # The card message we tried to edit is already gone (user deleted it
            # or our reply was removed) — nothing to edit, just keep playing.
            pass
        except ChannelPrivate:
            # Bot was removed from the chat (kicked/left) or the chat became
            # private between play and the card update. Don't crash the handler —
            # tear down and return. Without this, the uncaught ChannelPrivate
            # bubbles up as "Unexpected exception raised in MessageHandler".
            await self.stop(chat_id)


    async def _prefetch_next(self, chat_id: int) -> None:
        """Background-download the next queued track so playback is instant.

        Only prefetches one track ahead; the download runs in the background
        without blocking the current stream.
        """
        try:
            nxt = queue.get_next(chat_id, check=True)
            if nxt and not nxt.file_path:
                schedule_bg_fetch(nxt)
        except Exception as e:
            logger.error(f"prefetch_next error: {e}")


    async def replay(self, chat_id: int) -> None:
        if not await db.get_call(chat_id):
            return

        media = queue.get_current(chat_id)
        _lang = await lang.get_lang(chat_id)
        msg = await app.send_message(chat_id=chat_id, text=_lang["play_again"])
        await self.play_media(chat_id, msg, media)


    async def play_next(self, chat_id: int) -> None:
        # Delete previous song file immediately after it ends. Pass the video
        # id so we also mop up any bg-fetched downloads/{id}.* files that
        # completed while the track was actually streaming from a URL.
        current_media = queue.get_current(chat_id)
        if current_media:
            await delete_file(
                current_media.file_path,
                chat_id,
                video_id=current_media.id,
            )

        media = queue.get_next(chat_id)
        # A real (user-requested or queued) track is available — clear any
        # prior AutoPlay-block counter so a future empty queue can retry.
        if media:
            self._reset_autoplay(chat_id)
        try:
            if media and media.message_id:
                await app.delete_messages(
                    chat_id=chat_id,
                    message_ids=media.message_id,
                    revoke=True,
                )
                media.message_id = 0
        except:
            pass

        if not media:
            # Queue empty — try AutoPlay (related tracks) if enabled and we
            # haven't already exhausted the failed-attempt budget. When YouTube
            # is blocked this prevents an infinite queue→fail→queue loop.
            if await db.get_autoplay(chat_id) and self._autoplay_ok(chat_id):
                played_ids = {t.id for t in queue.get_queue(chat_id)}
                if current_media and current_media.id:
                    played_ids.add(current_media.id)
                last = current_media
                candidates = []
                try:
                    if last and last.id:
                        # Ask for a few candidates so we can skip any that are
                        # duplicates of what's already played/queued.
                        candidates = await yt.related(
                            last.id,
                            last.title,
                            last.user or (await app.get_me()).mention,
                            last.video,
                            limit=5,
                            exclude_ids=played_ids,
                        )
                except Exception as e:
                    logger.error(f"AutoPlay fetch error: {e}")

                # Pick the first candidate that isn't already played/queued.
                chosen = next(
                    (c for c in candidates if c.id not in played_ids),
                    None,
                )
                if chosen:
                    logger.info(f"AutoPlay: queuing related track in {chat_id}")
                    self._reset_autoplay(chat_id)
                    queue.add(chat_id, chosen)
                    # Download the AutoPlay track in the background instead of
                    # relying on a flaky live stream URL at play time.
                    schedule_bg_fetch(chosen)
                    media = chosen
                else:
                    # No candidate found — note failure and stop.
                    logger.warning(f"AutoPlay: no candidate, stopping in {chat_id}")
                    self._note_autoplay_failure(chat_id)
                    return await self.stop(chat_id)

        # A real or AutoPlay-chosen track is now in `media`; fall through to
        # the playback path below. If we get here with no track (queue empty,
        # autoplay off, or capped after repeated failures), stop cleanly
        # instead of falling through to a media=None path.
        if not media:
            return await self.stop(chat_id)

        _lang = await lang.get_lang(chat_id)
        msg = await app.send_message(chat_id=chat_id, text=_lang["play_next"])
        if not media.file_path:
            media.file_path = await yt.get_stream_url(media.id, video=media.video)
            if not media.file_path:
                media.file_path = await yt.download(media.id, video=media.video)
            if not media.file_path:
                self._note_autoplay_failure(chat_id)
                await self.stop(chat_id)
                return await msg.edit_text(
                    _lang["error_no_file"].format(config.SUPPORT_CHAT)
                )

        media.message_id = msg.id
        await self.play_media(chat_id, msg, media)


    async def ping(self) -> float:
        pings = [client.ping for client in self.clients]
        return round(sum(pings) / len(pings), 2)


    async def decorators(self, client: PyTgCalls) -> None:
        @client.on_update()
        async def update_handler(_, update: types.Update) -> None:
            if isinstance(update, types.StreamEnded):
                await self.play_next(update.chat_id)
            elif isinstance(update, types.ChatUpdate):
                if update.status in [
                    types.ChatUpdate.Status.KICKED,
                    types.ChatUpdate.Status.LEFT_GROUP,
                    types.ChatUpdate.Status.CLOSED_VOICE_CHAT,
                ]:
                    await self.stop(update.chat_id)


    async def boot(self) -> None:
        PyTgCallsSession.notice_displayed = True
        for ub in userbot.clients:
            client = PyTgCalls(ub, cache_duration=100)
            await client.start()
            self.clients.append(client)
            await self.decorators(client)
        logger.info("PyTgCalls client(s) started.")
