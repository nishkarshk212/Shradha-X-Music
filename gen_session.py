"""
Shradha-X-Music - Session String Generator
Uses kurigram (Pyrogram fork) to generate a session string.
Run this script and follow the prompts.
"""

import asyncio
from pyrogram import Client

API_ID = 31390854
API_HASH = "eeeefbc0f02b727c67fbdb0c3aeb2b36"


async def main():
    print("=" * 50)
    print("  Shradha-X-Music Session Generator")
    print("=" * 50)
    print()
    print("You will be asked to enter your phone number")
    print("and the OTP sent to your Telegram app.")
    print()

    async with Client(
        name="session_gen",
        api_id=API_ID,
        api_hash=API_HASH,
        in_memory=True,
    ) as app:
        session_string = await app.export_session_string()
        print()
        print("=" * 50)
        print("  YOUR SESSION STRING (copy everything below)")
        print("=" * 50)
        print()
        print(session_string)
        print()
        print("=" * 50)
        print("  Paste this into your .env file as SESSION=")
        print("=" * 50)


if __name__ == "__main__":
    asyncio.run(main())
