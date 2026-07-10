# Copyright (c) 2025 TheHamkerAlone
# Licensed under the MIT License.
# This file is part of AloneXMusic

import aiohttp
from pyrogram import filters, types, enums
from AloneX import app, db, lang, config
from AloneX.helpers import admin_check, can_manage_vc

# MongoDB collections for chatbot configuration and chat context
chatbot_db = db.db.chatbot_chats
chatbot_history = db.db.chatbot_history

async def is_chatbot_enabled(chat_id: int) -> bool:
    """Check if chatbot is enabled for a specific group."""
    # Private chats (PM) always have chatbot enabled
    if chat_id > 0:
        return True
    doc = await chatbot_db.find_one({"chat_id": chat_id})
    return doc.get("enabled", True) if doc else True

async def set_chatbot(chat_id: int, enabled: bool) -> None:
    """Enable or disable chatbot for a specific group."""
    await chatbot_db.update_one(
        {"chat_id": chat_id},
        {"$set": {"enabled": enabled}},
        upsert=True
    )

async def get_history(chat_id: int) -> list:
    """Get recent conversation history for a chat."""
    doc = await chatbot_history.find_one({"chat_id": chat_id})
    if doc:
        return doc.get("messages", [])[-15:] # Keep last 15 messages for context
    return []

async def save_history(chat_id: int, messages: list) -> None:
    """Save conversation history for a chat."""
    await chatbot_history.update_one(
        {"chat_id": chat_id},
        {"$set": {"messages": messages[-30:]}}, # Keep maximum 30 messages in DB
        upsert=True
    )

@app.on_message(filters.command(["chatbot"]) & filters.group & ~app.bl_users)
@lang.language()
@admin_check
async def toggle_chatbot(_, m: types.Message):
    if len(m.command) < 2:
        enabled = await is_chatbot_enabled(m.chat.id)
        status_str = "Enabled" if enabled else "Disabled"
        return await m.reply_text(f"🤖 Chatbot is currently **{status_str}** in this chat.\nUse `/chatbot on` or `/chatbot off` to toggle.")

    action = m.command[1].strip().lower()
    if action == "on":
        await set_chatbot(m.chat.id, True)
        return await m.reply_text("🤖 Chatbot has been **Enabled** for this group!")
    elif action == "off":
        await set_chatbot(m.chat.id, False)
        return await m.reply_text("🤖 Chatbot has been **Disabled** for this group.")
    else:
        return await m.reply_text("Invalid argument. Use `/chatbot on` or `/chatbot off`.")

@app.on_message(
    (filters.text & ~filters.command(["chatbot", "play", "vplay", "skip", "stop", "pause", "resume", "queue"]))
    & ~app.bl_users
)
async def chatbot_reply_handler(client, m: types.Message):
    chat_id = m.chat.id
    is_pm = (m.chat.type == enums.ChatType.PRIVATE)
    
    # In groups, only reply if chatbot is enabled AND:
    # 1. User replied to a message sent by the bot
    # 2. Or user mentioned the bot's username/name
    # In PMs, always reply
    bot_user = await app.get_me()
    
    should_reply = False
    if is_pm:
        should_reply = True
    else:
        # Check if chatbot is enabled for this group
        if await is_chatbot_enabled(chat_id):
            if m.reply_to_message and m.reply_to_message.from_user and m.reply_to_message.from_user.id == bot_user.id:
                should_reply = True
            elif bot_user.username and f"@{bot_user.username}" in m.text:
                should_reply = True
            elif bot_user.mention and bot_user.mention in m.text:
                should_reply = True
            elif bot_user.first_name and bot_user.first_name.lower() in m.text.lower():
                should_reply = True

    if not should_reply:
        return

    # Indicate typing while fetching response
    await client.send_chat_action(chat_id, enums.ChatAction.TYPING)

    # Clean query text (remove bot mention if any)
    query_text = m.text
    if bot_user.username:
        query_text = query_text.replace(f"@{bot_user.username}", "")
    query_text = query_text.strip()

    if not query_text:
        return

    # Build chat messages context
    history = await get_history(chat_id)
    system_prompt = {
        "role": "system", 
        "content": (
            f"You are {bot_user.first_name}, a friendly, intelligent, and helpful AI assistant and music companion for Telegram. "
            "Reply concisely and directly to user messages."
        )
    }
    
    # Format messages payload
    messages = [system_prompt]
    for msg in history:
        messages.append(msg)
    messages.append({"role": "user", "content": query_text})

    # Call OpenRouter API
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "meta-llama/llama-3.1-8b-instruct",
        "messages": messages,
        "max_tokens": 150
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    choices = data.get("choices", [])
                    if choices:
                        reply_content = choices[0].get("message", {}).get("content", "").strip()
                        if reply_content:
                            # Reply to user
                            await m.reply_text(reply_content)
                            
                            # Append to history
                            history.append({"role": "user", "content": query_text})
                            history.append({"role": "assistant", "content": reply_content})
                            await save_history(chat_id, history)
                            return
    except Exception as e:
        pass
