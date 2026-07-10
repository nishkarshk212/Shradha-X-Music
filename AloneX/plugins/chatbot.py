# Copyright (c) 2025 AloneX Music Bot
# Chatbot plugin - Shradha (NVIDIA Nemotron Ultra 550B)

import aiohttp
import re
from pyrogram import filters, types, enums
from AloneX import app, db, config

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

@app.on_message(filters.text & ~app.bl_users)
async def ananya_chatbot(client, m: types.Message):
    # Ignore all commands (messages starting with /)
    if m.text and m.text.startswith("/"):
        return

    chat_id = m.chat.id

    # Get clean query
    bot_user = await app.get_me()
    query_text = m.text
    if bot_user.username:
        query_text = query_text.replace(f"@{bot_user.username}", "").strip()
    if not query_text:
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

    # Fallback list: try primary first, then rotate through active free models
    fallback_models = [
        "nvidia/nemotron-3-ultra-550b-a55b:free",
        "tencent/hy3:free",
        "liquid/lfm-2.5-1.2b-instruct:free",
        "google/gemma-4-31b-it:free",
        "qwen/qwen3-coder:free",
        "meta-llama/llama-3.2-3b-instruct:free",
    ]

    from AloneX import logger

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
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url, headers=headers, json=payload,
                    timeout=aiohttp.ClientTimeout(total=20)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        choices = data.get("choices", [])
                        if choices:
                            message_obj = choices[0].get("message", {})
                            reply_content = (message_obj.get("content") or "").strip()
                            reasoning_details = message_obj.get("reasoning_details")

                            if reply_content:
                                await m.reply_text(reply_content)
                                # Save history with reasoning_details preserved
                                history.append({"role": "user", "content": query_text})
                                history.append({
                                    "role": "assistant",
                                    "content": reply_content,
                                    "reasoning_details": reasoning_details
                                })
                                await save_history(chat_id, history)
                                return  # success — stop trying further models
                        logger.warning(f"[Shradha] Empty content from {model_name}, trying next...")
                    else:
                        body = await resp.text()
                        logger.error(f"[Shradha] {model_name} status {resp.status}: {body}")
        except Exception as e:
            logger.error(f"[Shradha] {model_name} failed: {e}")

