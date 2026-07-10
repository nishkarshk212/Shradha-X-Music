# Copyright (c) 2025 TheHamkerAlone
# Licensed under the MIT License.
# This file is part of AloneXMusic

import asyncio
import aiohttp
import json
import re
from pyrogram import filters, types
from AloneX import app, db, lang, config, queue, anon
from AloneX.helpers import admin_check, buttons

lyrics_tasks = {}

async def fetch_lyrics_ai(song_title: str, artist: str, duration_sec: int) -> list:
    """Fetch structured lyrics with estimated timestamps via OpenRouter AI."""
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {config.OPENROUTER_API_KEY.strip()}",
        "Content-Type": "application/json",
    }
    
    prompt = (
        f"Provide the lyrics for the song '{song_title}' by '{artist}'. "
        f"The song is exactly {duration_sec} seconds long. "
        "Distribute the lyrics lines evenly across this duration. "
        "Each line MUST start with a timestamp in [MM:SS] format. "
        "Example:\n[00:00] (Instrumental Intro)\n[00:15] First line of lyrics\n"
        "Do not write any introductory or concluding text, only the timestamped lyrics."
    )
    
    # Step 1: Try preferred google/lyria-3-pro-preview model with a short timeout
    for model_name in ["google/lyria-3-pro-preview", "openrouter/free"]:
        payload = {
            "model": model_name,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 1000
        }
        
        try:
            logger.info(f"[Lyrics] Querying model {model_name}...")
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json=payload, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        choices = data.get("choices", [])
                        if choices:
                            content = choices[0]["message"]["content"]
                            if content and len(content.strip()) > 30:
                                # Parse timestamp lines: [MM:SS] Lyric Text
                                parsed_lyrics = []
                                for line in content.split("\n"):
                                    match = re.match(r"^\[(\d+):(\d+)\]\s*(.*)$", line.strip())
                                    if match:
                                        m, s = int(match.group(1)), int(match.group(2))
                                        timestamp_sec = m * 60 + s
                                        lyric_text = match.group(3).strip()
                                        parsed_lyrics.append((timestamp_sec, lyric_text))
                                
                                if parsed_lyrics:
                                    # Sort by time
                                    parsed_lyrics.sort(key=lambda x: x[0])
                                    logger.info(f"[Lyrics] Successfully fetched using {model_name}")
                                    return parsed_lyrics
        except Exception as e:
            logger.error(f"[Lyrics] Model {model_name} failed: {e}")
            
    # Fallback/Dummy lyrics distributed evenly if all AI calls fail
    interval = max(5, duration_sec // 10)
    return [(i * interval, f"🎵 Playing line {i+1}...") for i in range(10)]

def build_lyrics_display(parsed_lyrics: list, current_time: int, duration_sec: int, song_title: str) -> str:
    """Build the string showing live highlighted lyrics and progress bar."""
    display_lines = []
    active_index = -1
    
    # Find current active lyric line
    for idx, (time_sec, text) in enumerate(parsed_lyrics):
        if current_time >= time_sec:
            active_index = idx
        else:
            break
            
    # Show window of lyrics (e.g. 2 lines before, active line, 3 lines after)
    start = max(0, active_index - 2) if active_index != -1 else 0
    end = min(len(parsed_lyrics), start + 6)
    
    for idx in range(start, end):
        time_sec, text = parsed_lyrics[idx]
        m, s = divmod(time_sec, 60)
        time_str = f"{m:02d}:{s:02d}"
        
        if idx == active_index:
            display_lines.append(f"▶️ **[{time_str}] {text}** ◀️")
        else:
            display_lines.append(f"   [{time_str}] {text}")
            
    lyrics_block = "\n".join(display_lines)
    
    # Add a visual progress slider
    pos = min(int((current_time / duration_sec) * 15), 14)
    slider = "━" * pos + "◉" + "━" * (14 - pos)
    
    curr_str = f"{current_time // 60:02d}:{current_time % 60:02d}"
    tot_str = f"{duration_sec // 60:02d}:{duration_sec % 60:02d}"
    
    return (
        f"🎙️ **Live Lyrics: {song_title}**\n\n"
        f"{lyrics_block}\n\n"
        f"⏱️ `{curr_str}` {slider} `{tot_str}`"
    )

async def lyrics_live_tracker(chat_id: int, message: types.Message, parsed_lyrics: list, duration_sec: int, song_title: str):
    """Send each lyric line as a new message when it starts playing."""
    try:
        # Delete the initial loading message to keep group clean
        try:
            await message.delete()
        except Exception:
            pass
            
        last_active_index = -1
        while chat_id in db.active_calls:
            # Check if active song changed
            media = queue.get_current(chat_id)
            if not media or media.title != song_title:
                break
                
            current_time = media.time
            if current_time > duration_sec:
                break
                
            # Find current active lyric line
            active_index = -1
            for idx, (time_sec, text) in enumerate(parsed_lyrics):
                if current_time >= time_sec:
                    active_index = idx
                else:
                    break
            
            # Send new lyric line as a separate message when active line changes
            if active_index != -1 and active_index != last_active_index:
                last_active_index = active_index
                time_sec, lyric_text = parsed_lyrics[active_index]
                if lyric_text.strip():
                    try:
                        await app.send_message(chat_id, f"🎙️ **{lyric_text}**")
                    except Exception:
                        pass
                        
            await asyncio.sleep(2)
            
    except asyncio.CancelledError:
        pass
    finally:
        lyrics_tasks.pop(chat_id, None)

@app.on_message(filters.command(["lyrics"]) & filters.group & ~app.bl_users)
@lang.language()
async def show_live_lyrics(_, m: types.Message):
    chat_id = m.chat.id
    from AloneX.plugins.settings import get_chat_settings
    settings = await get_chat_settings(chat_id)
    if not settings.get("lyrics", True):
        return await m.reply_text("❌ Lyrics feature is disabled in settings. Enable it using `/settings` first!")

    if not await db.get_call(chat_id):
        return await m.reply_text("❌ No music is playing right now.")
        
    media = queue.get_current(m.chat.id)
    if not media:
        return await m.reply_text("❌ No music is playing right now.")
        
    sent = await m.reply_text("🔍 Fetching lyrics and syncing timeline...")
    
    # Cancel previous lyrics task for this chat if exists
    if chat_id in lyrics_tasks:
        lyrics_tasks[chat_id].cancel()
        
    parsed_lyrics = await fetch_lyrics_ai(media.title, media.channel_name or "", media.duration_sec)
    
    task = asyncio.create_task(
        lyrics_live_tracker(chat_id, sent, parsed_lyrics, media.duration_sec, media.title)
    )
    lyrics_tasks[chat_id] = task


async def trigger_auto_lyrics(chat_id: int, media) -> None:
    """Automatically fetch and track lyrics for a new song if enabled."""
    from AloneX.plugins.settings import get_chat_settings
    settings = await get_chat_settings(chat_id)
    if not settings.get("lyrics", True):
        return
        
    # Cancel previous lyrics task for this chat if exists
    if chat_id in lyrics_tasks:
        try:
            lyrics_tasks[chat_id].cancel()
        except Exception:
            pass
        
    try:
        sent = await app.send_message(chat_id, "🔍 Fetching auto lyrics...")
        parsed_lyrics = await fetch_lyrics_ai(media.title, media.channel_name or "", media.duration_sec)
        
        task = asyncio.create_task(
            lyrics_live_tracker(chat_id, sent, parsed_lyrics, media.duration_sec, media.title)
        )
        lyrics_tasks[chat_id] = task
    except Exception:
        pass

