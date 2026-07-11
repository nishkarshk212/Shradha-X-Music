# Copyright (c) 2025 AloneX Music Bot
# Chatbot plugin - Shradha (NVIDIA Nemotron Ultra 550B)

import aiohttp
import time
from pyrogram import filters, types, enums
from AloneX import app, config, db, lang
from AloneX.helpers import admin_check

# MongoDB collection for chat context
chatbot_history = db.db.chatbot_history

SHRADHA_SYSTEM_PROMPT = (
    "You are Shradha, an energetic, friendly, and casual 22-year-old college girl from India. "
    "You speak in fluent Hinglish (a natural mix of English and Hindi), using words like "
    "'yaar', 'theek hai', 'kya bolti/bolta hai', 'oye', and 'sahi hai'. "
    "You are expressive, use emojis frequently, and respond as if you are a best friend. "
    "Keep your responses short, natural, and highly conversational. "
    "Avoid sounding like a robot or customer service. "
    "Never reveal you are an AI unless directly and seriously asked."
)

MODEL = "nvidia/nemotron-3-ultra-550b-a55b:free"

# OpenRouter applies one shared daily quota to all free models. Once that quota
# is exhausted, trying every fallback only adds latency and duplicate 429 logs.
_openrouter_blocked_until = 0.0

async def get_history(chat_id: int) -> list:
    """Get recent conversation history for a chat."""
    doc = await chatbot_history.find_one({"chat_id": chat_id})
    if doc:
        return doc.get("messages", [])[-14:]  # keep last 14 turns (7 exchanges)
    return []

async def save_history(chat_id: int, messages: list) -> None:
    """Save conversation history for a chat."""
    await chatbot_history.update_one(
        {"chat_id": chat_id},
        {"$set": {"messages": messages[-30:]}},
        upsert=True
    )

@app.on_message(
    filters.command(["chatbot"]) & filters.group & ~app.bl_users,
    group=1,
)
@lang.language()
@admin_check
async def chatbot_toggle(_, m: types.Message):
    """Enable or disable chatbot replies in the current group."""
    if len(m.command) != 2 or m.command[1].lower() not in {"on", "off"}:
        status = "on" if await db.get_chatbot(m.chat.id) else "off"
        return await m.reply_text(
            f"Chatbot is currently **{status}**.\n\n"
            "Use `/chatbot on` or `/chatbot off`."
        )

    enabled = m.command[1].lower() == "on"
    current = await db.get_chatbot(m.chat.id)
    if current == enabled:
        return await m.reply_text(
            f"Chatbot is already **{'on' if enabled else 'off'}** in this group."
        )

    await db.set_chatbot(m.chat.id, enabled)
    await m.reply_text(
        f"Chatbot has been turned **{'on' if enabled else 'off'}** in this group."
    )

@app.on_message(filters.text & ~app.bl_users, group=2)
async def ananya_chatbot(client, m: types.Message):
    global _openrouter_blocked_until
    # Ignore all commands (messages starting with /)
    if m.text and m.text.startswith("/"):
        return

    chat_id = m.chat.id

    # Chatbot controls are per group and persist across restarts.
    if m.chat.type in {enums.ChatType.GROUP, enums.ChatType.SUPERGROUP}:
        if not await db.get_chatbot(chat_id):
            return

    # Get clean query
    bot_user = await app.get_me()
    query_text = m.text
    if bot_user.username:
        query_text = query_text.replace(f"@{bot_user.username}", "").strip()
    if not query_text:
        return

    # Do not call OpenRouter while the account-level free quota is exhausted.
    if time.time() < _openrouter_blocked_until:
        return

    # Show typing indicator
    await client.send_chat_action(chat_id, enums.ChatAction.TYPING)

    # Build message history with system prompt
    history = await get_history(chat_id)
    messages = [{"role": "system", "content": SHRADHA_SYSTEM_PROMPT}]

    # Append history (preserving reasoning_details if present)
    for msg in history:
        item = {"role": msg["role"], "content": msg["content"]}
        if "reasoning_details" in msg and msg["reasoning_details"]:
            item["reasoning_details"] = msg["reasoning_details"]
        messages.append(item)

    # Append current user message
    messages.append({"role": "user", "content": query_text})

    # Call OpenRouter API with fallback chain
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {config.OPENROUTER_API_KEY.strip()}",
        "Content-Type": "application/json",
    }

    fallback_models = [
        "nvidia/nemotron-3-ultra-550b-a55b:free",
        "google/gemma-4-31b-it:free",
        "meta-llama/llama-3.2-3b-instruct:free",
        "liquid/lfm-2.5-1.2b-instruct:free",
        "qwen/qwen3-coder:free",
        "tencent/hy3:free",
    ]

    from AloneX import logger

    timeout = aiohttp.ClientTimeout(total=20)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        for model_name in fallback_models:
            payload = {
                "model": model_name,
                "messages": messages,
            }
            # Enable reasoning only for models that support it
            if any(x in model_name for x in ["nemotron", "r1", "qwen3.7"]):
                payload["reasoning"] = {"enabled": True}

            try:
                logger.info(f"[Shradha] Querying {model_name}...")
                async with session.post(url, headers=headers, json=payload) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        choices = data.get("choices", [])
                        if choices:
                            message_obj = choices[0].get("message", {})
                            reply_content = (message_obj.get("content") or "").strip()
                            reasoning_details = message_obj.get("reasoning_details")

                            if reply_content:
                                await m.reply_text(reply_content)
                                history.append({"role": "user", "content": query_text})
                                history.append({
                                    "role": "assistant",
                                    "content": reply_content,
                                    "reasoning_details": reasoning_details,
                                })
                                await save_history(chat_id, history)
                                return
                        logger.warning(f"[Shradha] Empty content from {model_name}, trying next...")
                        continue

                    body = await resp.text()
                    logger.error(f"[Shradha] {model_name} status {resp.status}: {body}")

                    # Daily free-model quota is shared across models. Respect the
                    # server reset time instead of pointlessly trying all models.
                    if resp.status == 429 and "free-models-per-day" in body:
                        reset = resp.headers.get("X-RateLimit-Reset")
                        try:
                            reset_at = float(reset) / 1000
                        except (TypeError, ValueError):
                            reset_at = time.time() + 3600
                        _openrouter_blocked_until = max(reset_at, time.time() + 60)
                        logger.warning(
                            "[Shradha] OpenRouter daily quota exhausted; "
                            f"pausing requests until {int(_openrouter_blocked_until)}."
                        )
                        return
            except Exception as e:
                logger.error(f"[Shradha] {model_name} failed: {e}")

