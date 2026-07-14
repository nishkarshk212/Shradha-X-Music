# ALONE-CODER
from os import getenv
from dotenv import load_dotenv

load_dotenv()

class Config:
    def __init__(self):
        self.API_ID = int(getenv("API_ID", "31390854"))
        self.API_HASH = getenv("API_HASH", "eeeefbc0f02b727c67fbdb0c3aeb2b36")

        self.BOT_TOKEN = getenv("BOT_TOKEN", "")
        self.MONGO_URL = getenv("MONGO_URL", "")

        self.LOGGER_ID = int(getenv("LOGGER_ID", "-1004304855875"))
        self.OWNER_ID = int(getenv("OWNER_ID", "8784193595"))
        
        self.SESSION1 = getenv("SESSION", "")
        self.SESSION2 = getenv("SESSION2", None)
        self.SESSION3 = getenv("SESSION3", None)

        self.SUPPORT_CHANNEL = getenv("SUPPORT_CHANNEL", "https://t.me/titanic_network")
        self.SUPPORT_CHAT = getenv("SUPPORT_CHAT", "https://t.me/+WAOT47P-70QwOTBl")

        self.AUTO_END: bool = getenv("AUTO_END", False)
        self.AUTO_LEAVE: bool = getenv("AUTO_LEAVE", False)
        self.VIDEO_PLAY: bool = getenv("VIDEO_PLAY", True)

        # Master kill-switch for the AutoPlay (related-tracks) feature.
        _autoplay = getenv("AUTO_PLAY", "True")
        self.AUTO_PLAY: bool = str(_autoplay).lower() in ("1", "true", "yes", "on")

        self.QUEUE_LIMIT = int(getenv("QUEUE_LIMIT", "50"))
        self.DURATION_LIMIT = int(getenv("DURATION_LIMIT", "5400"))
        self.PLAYLIST_LIMIT = int(getenv("PLAYLIST_LIMIT", "20"))
        self.COOKIES_DATA = getenv("COOKIES_DATA", "")
        self.COOKIES_URL = [
            url for url in getenv("COOKIES_URL", "").split(" ")
            if url and "batbin.me" in url
        ]
        self.DEFAULT_THUMB = getenv("DEFAULT_THUMB", "https://te.legra.ph/file/3e40a408286d4eda24191.jpg")
        self.PING_IMG = getenv("PING_IMG", "https://files.catbox.moe/haagg2.png")
        self.START_IMG = getenv("START_IMG", "https://i.ibb.co/DgLg4swX/2026-07-09-18-50-06.jpg")

        # Railway YouTube API
        self.RAILWAY_YT_API_KEY = getenv("RAILWAY_YT_API_KEY", "lily_If5GeswRaQESaifBoBxMHlYZVqhJF1Y")
        self.RAILWAY_YT_API_URL = getenv("RAILWAY_YT_API_URL", "https://youtube-api-saas-backend.onrender.com")

    def check(self):
        missing = [
            var
            for var in ["API_ID", "API_HASH", "BOT_TOKEN", "MONGO_URL", "LOGGER_ID", "OWNER_ID", "SESSION1"]
            if not getattr(self, var)
        ]
        if missing:
            raise SystemExit(f"Missing required environment variables: {', '.join(missing)}")
