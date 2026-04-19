#ALONE CODER
from os import getenv
from dotenv import load_dotenv

load_dotenv()

class Config:
    def __init__(self):
        self.API_ID = int(getenv("API_ID", "17596251"))
        self.API_HASH = getenv("API_HASH", "e58343b4c0193e293e391daf97603fcd")

        self.BOT_TOKEN = getenv("BOT_TOKEN", "8752619857:AAGVYdNdOkHfBE5PLjMd2xf519PFVhGAJxc")
        self.MONGO_URL = getenv("MONGO_URL", "mongodb+srv://public:abishnoimf@cluster0.rqk6ihd.mongodb.net/?retryWrites=true&w=majority")

        self.LOGGER_ID = int(getenv("LOGGER_ID", "-1001603822916"))
        self.OWNER_ID = int(getenv("OWNER_ID", "8458947967"))
        
        self.SESSION1 = getenv("SESSION", "BQCkcAYAmG6StbYHVF60O4IZiI0VsMVL-oLNLHL2NzXqw2xvpw3jmxQPgStcTf9NvkWgEltO3f_rkuPYXoz1I_COZASoUxixu8VhMjgEsMDmWSlrEa0mj1oHXEOnBnkHtHLgurSWoicbbQbSKf543Guxk-qpPHAwzT7dMTskdsI21ZYVyR5Z_PLs1FjhPTqJpzHjHcbWucKrta0ApYEC3zgD1I87qsXnfMOK46QUMB1JWJnH2T33uBbN9iOKC2y7u5ZKJjwllA-b7-s8n_FNuS3oKjvr5NY4QmndGVqYTD8CSlXUBg0L_z5wGlmSsn_zQ9XWcGfQqm2OOvADay2_mspJsZd84wAAAAHa-fyIAA")
        self.SESSION2 = getenv("SESSION2", None)
        self.SESSION3 = getenv("SESSION3", None)

        self.SUPPORT_CHANNEL = getenv("SUPPORT_CHANNEL", "https://t.me/AloneUpdates")
        self.SUPPORT_CHAT = getenv("SUPPORT_CHAT", "https://t.me/AloneBotSupport")

        self.AUTO_END: bool = getenv("AUTO_END", False)
        self.AUTO_LEAVE: bool = getenv("AUTO_LEAVE", False)
        self.VIDEO_PLAY: bool = getenv("VIDEO_PLAY", True)

        self.QUEUE_LIMIT = int(getenv("QUEUE_LIMIT", "50"))
        self.DURATION_LIMIT = int(getenv("DURATION_LIMIT", "5400"))
        self.PLAYLIST_LIMIT = int(getenv("PLAYLIST_LIMIT", "20"))
        self.COOKIES_URL = [
            url for url in getenv("COOKIES_URL", "").split(" ")
            if url and "batbin.me" in url
        ]
        self.DEFAULT_THUMB = getenv("DEFAULT_THUMB", "https://te.legra.ph/file/3e40a408286d4eda24191.jpg")
        self.PING_IMG = getenv("PING_IMG", "https://files.catbox.moe/haagg2.png")
        self.START_IMG = getenv("START_IMG", "https://files.catbox.moe/zvziwk.jpg")

    def check(self):
        missing = [
            var
            for var in ["API_ID", "API_HASH", "BOT_TOKEN", "MONGO_URL", "LOGGER_ID", "OWNER_ID", "SESSION1"]
            if not getattr(self, var)
        ]
        if missing:
            raise SystemExit(f"Missing required environment variables: {', '.join(missing)}")
