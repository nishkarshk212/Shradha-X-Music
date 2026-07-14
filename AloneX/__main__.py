# Copyright (c) 2025 TheHamkerAlone
# Licensed under the MIT License.
# This file is part of AloneXMusic


import asyncio
import importlib

from pyrogram import idle

from AloneX import (anon, app, config, db,
                   logger, stop, userbot, yt)
from AloneX.plugins import all_modules


async def main():
    await db.connect()
    await app.boot()
    await app.set_commands()
    await userbot.boot()
    await anon.boot()

    for module in all_modules:
        importlib.import_module(f"AloneX.plugins.{module}")
    logger.info(f"Loaded {len(all_modules)} modules.")

    if config.COOKIES_URL:
        await yt.save_cookies(config.COOKIES_URL)

    sudoers = await db.get_sudoers()
    app.sudoers.update(sudoers)
    app.bl_users.update(await db.get_blacklisted())
    logger.info(f"Loaded {len(app.sudoers)} sudo users.")

    # Keep the SaaS YouTube API's Onrender container warm so the first-song
    # stream URL and every subsequent request finds a hot API. Onrender free
    # tier spins the dyno down after ~15 min idle; this loops every 4 min.
    asyncio.create_task(yt.start_keepalive())

    await idle()
    await stop()


if __name__ == "__main__":
    try:
        asyncio.get_event_loop().run_until_complete(main())
    except KeyboardInterrupt:
        pass
