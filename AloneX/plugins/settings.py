# Copyright (c) 2025 TheHamkerAlone
# Licensed under the MIT License.
# This file is part of AloneXMusic

from pyrogram import filters, types
from pyrogram.enums import ButtonStyle
from AloneX import app, db, lang
from AloneX.helpers import admin_check

# MongoDB collection for chat-level feature settings
settings_db = db.db.settings

async def get_chat_settings(chat_id: int) -> dict:
    """Get all feature settings for a chat (defaults to True)."""
    doc = await settings_db.find_one({"chat_id": chat_id})
    if not doc:
        return {
            "chatbot": True,
            "lyrics": True,
            "cleanup": True,
            "quickplay": True
        }
    return {
        "chatbot": doc.get("chatbot", True),
        "lyrics": doc.get("lyrics", True),
        "cleanup": doc.get("cleanup", True),
        "quickplay": doc.get("quickplay", True)
    }

async def toggle_chat_setting(chat_id: int, feature: str) -> dict:
    """Toggle a feature setting and return updated settings."""
    settings = await get_chat_settings(chat_id)
    new_val = not settings.get(feature, True)
    
    await settings_db.update_one(
        {"chat_id": chat_id},
        {"$set": {feature: new_val}},
        upsert=True
    )
    settings[feature] = new_val
    return settings

def build_settings_keyboard(chat_id: int, settings: dict) -> types.InlineKeyboardMarkup:
    """Build the settings dashboard with Green/Red colored buttons."""
    # Enums style config
    btn_chatbot = types.InlineKeyboardButton(
        text=f"🤖 Chatbot: {'ON (Green)' if settings['chatbot'] else 'OFF (Red)'}",
        callback_data=f"set_toggle {chat_id} chatbot",
        style=ButtonStyle.SUCCESS if settings["chatbot"] else ButtonStyle.DANGER
    )
    
    btn_lyrics = types.InlineKeyboardButton(
        text=f"🎙️ Live Lyrics: {'ON (Green)' if settings['lyrics'] else 'OFF (Red)'}",
        callback_data=f"set_toggle {chat_id} lyrics",
        style=ButtonStyle.SUCCESS if settings["lyrics"] else ButtonStyle.DANGER
    )
    
    btn_cleanup = types.InlineKeyboardButton(
        text=f"🗑️ Auto Cleanup: {'ON (Green)' if settings['cleanup'] else 'OFF (Red)'}",
        callback_data=f"set_toggle {chat_id} cleanup",
        style=ButtonStyle.SUCCESS if settings["cleanup"] else ButtonStyle.DANGER
    )
    
    btn_quickplay = types.InlineKeyboardButton(
        text=f"⚡ Quick Play: {'ON (Green)' if settings['quickplay'] else 'OFF (Red)'}",
        callback_data=f"set_toggle {chat_id} quickplay",
        style=ButtonStyle.SUCCESS if settings["quickplay"] else ButtonStyle.DANGER
    )
    
    btn_close = types.InlineKeyboardButton(
        text="❌ Close Menu",
        callback_data="set_close"
    )
    
    keyboard = [
        [btn_chatbot],
        [btn_lyrics],
        [btn_cleanup],
        [btn_quickplay],
        [btn_close]
    ]
    return types.InlineKeyboardMarkup(keyboard)

@app.on_message(filters.command(["settings"]) & filters.group & ~app.bl_users)
@lang.language()
@admin_check
async def settings_menu(_, m: types.Message):
    chat_id = m.chat.id
    settings = await get_chat_settings(chat_id)
    keyboard = build_settings_keyboard(chat_id, settings)
    
    await m.reply_text(
        f"⚙️ **AloneX Group Settings for {m.chat.title}**\n\n"
        "Configure features directly from here. Active features are marked green, disabled features are marked red.",
        reply_markup=keyboard
    )

@app.on_callback_query(filters.regex("^set_toggle") & ~app.bl_users)
@admin_check
async def toggle_setting_callback(_, query: types.CallbackQuery):
    args = query.data.split()
    chat_id = int(args[1])
    feature = args[2]
    
    # Toggle setting
    settings = await toggle_chat_setting(chat_id, feature)
    keyboard = build_settings_keyboard(chat_id, settings)
    
    await query.message.edit_reply_markup(reply_markup=keyboard)
    await query.answer(f"Updated {feature} setting!")

@app.on_callback_query(filters.regex("^set_close") & ~app.bl_users)
async def close_settings_callback(_, query: types.CallbackQuery):
    try:
        await query.message.delete()
    except Exception:
        pass
