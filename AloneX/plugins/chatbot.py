# Copyright (c) 2025 TheHamkerAlone
# Licensed under the MIT License.
# This file is part of AloneXMusic

import aiohttp
import re
from pyrogram import filters, types, enums
from AloneX import app, db, lang, config, anon
from AloneX.helpers import admin_check, can_manage_vc

# MongoDB collection for chat context
chatbot_history = db.db.chatbot_history

async def is_chatbot_enabled(chat_id: int) -> bool:
    """Check if chatbot is enabled for a specific group."""
    if chat_id > 0:
        return True
    from AloneX.plugins.settings import get_chat_settings
    settings = await get_chat_settings(chat_id)
    return settings.get("chatbot", True)

async def set_chatbot(chat_id: int, enabled: bool) -> None:
    """Enable or disable chatbot for a specific group."""
    await db.db.settings.update_one(
        {"chat_id": chat_id},
        {"$set": {"chatbot": enabled}},
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
    await m.reply_text("🤖 Please configure chatbot settings directly using `/settings`!")

@app.on_message(
    filters.text & ~app.bl_users
)
async def chatbot_reply_handler(client, m: types.Message):
    # Ignore commands starting with slash
    if m.text and m.text.startswith("/"):
        return
        
    chat_id = m.chat.id
    is_pm = (m.chat.type == enums.ChatType.PRIVATE)
    
    bot_user = await app.get_me()
    
    should_reply = False
    if is_pm:
        should_reply = True
    else:
        # Check if chatbot is enabled for this group
        if await is_chatbot_enabled(chat_id):
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
            f"You are {bot_user.first_name}, a friendly, cute, and helpful girl character replying to users. "
            "You must reply in character, speaking warmly and cutely like a girl. "
            "Reply concisely and directly to user messages. "
            "Additionally, you can control music playback. If the user requests to pause, resume, skip, or stop the playing music, "
            "you MUST start your reply with '[CONTROL: pause]', '[CONTROL: resume]', '[CONTROL: skip]', or '[CONTROL: stop]' accordingly. "
            "Example: '[CONTROL: skip] Skipping the track for you!'"
        )
    }
    
    # Format messages payload including any existing reasoning_details
    messages = [system_prompt]
    for msg in history:
        item = {
            "role": msg.get("role"),
            "content": msg.get("content")
        }
        if "reasoning_details" in msg:
            item["reasoning_details"] = msg["reasoning_details"]
        messages.append(item)
        
    messages.append({"role": "user", "content": query_text})

    # Call OpenRouter API with reasoning enabled
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {config.OPENROUTER_API_KEY.strip()}",
        "Content-Type": "application/json",
    }
    
    # Try active free models on OpenRouter (never consumes paid credits)
    for model_name in [
        "qwen/qwen3-next-80b-a3b-instruct:free", 
        "google/gemma-4-31b-it:free", 
        "qwen/qwen3-coder:free", 
        "meta-llama/llama-3.2-3b-instruct:free"
    ]:
        payload = {
            "model": model_name,
            "messages": messages,
            "reasoning": {"enabled": True}
        }

        try:
            from AloneX import logger
            logger.info(f"[Chatbot] Querying model {model_name} with reasoning...")
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json=payload, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        choices = data.get("choices", [])
                        if choices:
                            message_obj = choices[0].get("message", {})
                            reply_content = message_obj.get("content")
                            reasoning_details = message_obj.get("reasoning_details")
                            
                            if reply_content:
                                reply_content = reply_content.strip()
                                
                                # Check for control directives
                                control_match = re.match(r"^\[CONTROL:\s*(\w+)\]\s*(.*)$", reply_content, re.IGNORECASE)
                                if control_match:
                                    action = control_match.group(1).lower()
                                    friendly_reply = control_match.group(2).strip()
                                    
                                    # Execute corresponding control function
                                    if action == "pause":
                                        if await db.playing(chat_id):
                                            await anon.pause(chat_id)
                                    elif action == "resume":
                                        if not await db.playing(chat_id):
                                            await anon.resume(chat_id)
                                    elif action == "skip":
                                        await anon.play_next(chat_id)
                                    elif action == "stop":
                                        await anon.stop(chat_id)
                                        
                                    await m.reply_text(friendly_reply)
                                    return

                                # Reply to user normally
                                await m.reply_text(reply_content)
                                
                                # Append to history preserving reasoning_details unmodified
                                history.append({"role": "user", "content": query_text})
                                history.append({
                                    "role": "assistant",
                                    "content": reply_content,
                                    "reasoning_details": reasoning_details
                                })
                                await save_history(chat_id, history)
                                return
                    else:
                        logger.error(f"[Chatbot] Model {model_name} status {resp.status}: {await resp.text()}")
        except Exception as e:
            from AloneX import logger
            logger.error(f"[Chatbot] Model {model_name} failed: {e}")
            continue
