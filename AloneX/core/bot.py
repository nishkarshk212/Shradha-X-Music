# Copyright (c) 2025 TheHamkerAlone 
# Licensed under the MIT License.
# This file is part of AloneXMusic


import pyrogram

from AloneX import config, logger


class Bot(pyrogram.Client):
    def __init__(self):
        super().__init__(
            name="AloneX",
            api_id=config.API_ID,
            api_hash=config.API_HASH,
            bot_token=config.BOT_TOKEN,
            parse_mode=pyrogram.enums.ParseMode.HTML,
            max_concurrent_transmissions=7,
            link_preview_options=pyrogram.types.LinkPreviewOptions(is_disabled=True),
        )
        self.owner = config.OWNER_ID
        self.logger = config.LOGGER_ID
        self.bl_users = pyrogram.filters.user()
        self.sudoers = pyrogram.filters.user(self.owner)

    async def boot(self):
        """
        Starts the bot and performs initial setup.

        Raises:
            SystemExit: If the bot fails to access the log group or is not an administrator in the logger group.
        """
        await super().start()
        self.id = self.me.id
        self.name = self.me.first_name
        self.username = self.me.username
        self.mention = self.me.mention

        try:
            await self.send_message(self.logger, "Bot Started")
            get = await self.get_chat_member(self.logger, self.id)
        except Exception as ex:
            raise SystemExit(f"Bot has failed to access the log group: {self.logger}\nReason: {ex}")

        if get.status != pyrogram.enums.ChatMemberStatus.ADMINISTRATOR:
            raise SystemExit("Please promote the bot as an admin in logger group.")
        logger.info(f"Bot started as @{self.username}")

    async def set_commands(self):
        """Register the / command menu shown by Telegram clients.

        Only user-facing (group) commands are listed so the suggestion menu
        stays clean. Privileged/sudo commands are intentionally omitted.
        """
        from pyrogram.types import BotCommand, BotCommandScopeDefault

        commands = [
            BotCommand("play", "Play a song / YouTube URL / playlist"),
            BotCommand("vplay", "Play a video in the voice chat"),
            BotCommand("playlist", "Search & play a YouTube playlist by name"),
            BotCommand("suggest", "Show top songs with one-tap play buttons"),
            BotCommand("queue", "Show the current queue"),
            BotCommand("skip", "Skip to the next track"),
            BotCommand("pause", "Pause the stream"),
            BotCommand("resume", "Resume the stream"),
            BotCommand("seek", "Seek the stream (seconds)"),
            BotCommand("stop", "Stop the stream and leave VC"),
            BotCommand("autoplay", "Toggle autoplay of related tracks"),
            BotCommand("settings", "Open chat settings"),
            BotCommand("playmode", "Toggle admin-only play mode"),
            BotCommand("chatbot", "Toggle chat replies"),
            BotCommand("lang", "Change language"),
            BotCommand("ping", "Check bot latency"),
            BotCommand("stats", "Show bot stats"),
            BotCommand("help", "Show help menu"),
        ]
        try:
            await self.set_bot_commands(commands, scope=BotCommandScopeDefault())
            logger.info("Bot commands registered.")
        except Exception as e:
            logger.error(f"Failed to set bot commands: {e}")

    async def exit(self):
        """
        Asynchronously stops the bot.
        """
        await super().stop()
        logger.info("Bot stopped.")
