# ALONE-CODER
import os
import re
import aiohttp
import random
import asyncio
import yt_dlp
from py_yt import VideosSearch, Playlist
from AloneX import logger, config
from AloneX.helpers import Track, utils

API_URL = config.RAILWAY_YT_API_URL if config.RAILWAY_YT_API_URL else os.environ.get(
    "RAILWAY_YT_API_URL", "https://youtube-api-music-production-77fb.up.railway.app"
)
API_KEY = config.RAILWAY_YT_API_KEY if config.RAILWAY_YT_API_KEY else os.environ.get(
    "RAILWAY_YT_API_KEY", ""
)

DOWNLOAD_DIR = "downloads"


async def download_local_ytdlp(video_id: str, video: bool = False, use_cookies: bool = True) -> str | None:
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    ext = "mp4" if video else "mp3"
    file_path = os.path.join(DOWNLOAD_DIR, f"{video_id}.{ext}")
    if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
        return file_path

    cookie_file = None
    if use_cookies:
        cookie_dir = "AloneX/cookies"
        if os.path.exists(cookie_dir):
            cookies_files = [f for f in os.listdir(cookie_dir) if f.endswith(".txt")]
            if cookies_files:
                cookie_file = os.path.join(cookie_dir, random.choice(cookies_files))
        if not cookie_file and os.path.exists("cookies.txt"):
            cookie_file = "cookies.txt"

        # If use_cookies is requested but no cookie file is found, skip this step
        if not cookie_file:
            logger.info("Skipping local cookie download step (no cookie files found).")
            return None

    ydl_opts = {
        "format": "bestvideo+bestaudio/best" if video else "bestaudio/best",
        "outtmpl": os.path.join(DOWNLOAD_DIR, f"{video_id}.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "nocheckcertificate": True,
    }
    if cookie_file:
        ydl_opts["cookiefile"] = cookie_file
        logger.info(f"Using cookies file: {cookie_file} for local yt-dlp download")
    else:
        logger.info("Attempting local yt-dlp download without cookies.")

    if not video:
        ydl_opts["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }]

    try:
        loop = asyncio.get_event_loop()
        def _download():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([f"https://www.youtube.com/watch?v={video_id}"])
        await loop.run_in_executor(None, _download)

        if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
            return file_path
    except Exception as e:
        logger.error(f"Local yt-dlp download (use_cookies={use_cookies}) failed for {video_id}: {e}")
        # Clean up partial files if any
        for f in os.listdir(DOWNLOAD_DIR):
            if f.startswith(video_id) and f != f"{video_id}.{ext}":
                try:
                    os.remove(os.path.join(DOWNLOAD_DIR, f))
                except:
                    pass
    return None


async def download_song_remote(video_id: str) -> str | None:
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    file_path = os.path.join(DOWNLOAD_DIR, f"{video_id}.mp3")
    try:
        headers = {"X-API-Key": API_KEY} if API_KEY else {}
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{API_URL}/download",
                params={"id": video_id, "type": "audio"},
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=60)
            ) as resp:
                if resp.status != 200:
                    logger.error(f"Railway API download info failed: {resp.status}")
                    return None
                data = await resp.json()
                if not data.get("success"):
                    logger.error(f"Railway API returned failure: {data}")
                    return None

                download_info = data.get("download", {})
                audio_url = download_info.get("best_audio_url") or download_info.get("best_video_url")

                if not audio_url:
                    async with session.get(
                        f"{API_URL}/stream",
                        params={"id": video_id},
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=60)
                    ) as stream_resp:
                        if stream_resp.status == 200:
                            stream_data = await stream_resp.json()
                            if stream_data.get("success"):
                                stream_info = stream_data.get("stream", {})
                                audio_url = stream_info.get("url") or stream_info.get("audio_url")

                if not audio_url:
                    logger.error("No audio URL found from Railway API")
                    return None

            async with session.get(
                audio_url,
                timeout=aiohttp.ClientTimeout(total=300)
            ) as dl_resp:
                if dl_resp.status != 200:
                    logger.error(f"Audio download failed: {dl_resp.status}")
                    return None
                with open(file_path, "wb") as f:
                    async for chunk in dl_resp.content.iter_chunked(131072):
                        f.write(chunk)

        if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
            return file_path
        return None
    except Exception as e:
        logger.error(f"Download song remote error: {e}")
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                pass
        return None


async def download_video_remote(video_id: str) -> str | None:
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    file_path = os.path.join(DOWNLOAD_DIR, f"{video_id}.mp4")
    try:
        headers = {"X-API-Key": API_KEY} if API_KEY else {}
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{API_URL}/video/hq",
                params={"id": video_id},
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=60)
            ) as resp:
                video_url = None
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("success"):
                        stream_info = data.get("stream", {})
                        video_url = stream_info.get("url") or stream_info.get("video_url")

                if not video_url:
                    async with session.get(
                        f"{API_URL}/download",
                        params={"id": video_id, "type": "video"},
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=60)
                    ) as dl_resp:
                        if dl_resp.status == 200:
                            dl_data = await dl_resp.json()
                            if dl_data.get("success"):
                                download_info = dl_data.get("download", {})
                                video_url = download_info.get("best_video_url")

                if not video_url:
                    logger.error("No video URL found from Railway API")
                    return None

            async with session.get(
                video_url,
                timeout=aiohttp.ClientTimeout(total=600)
            ) as dl_resp:
                if dl_resp.status != 200:
                    logger.error(f"Video download failed: {dl_resp.status}")
                    return None
                with open(file_path, "wb") as f:
                    async for chunk in dl_resp.content.iter_chunked(131072):
                        f.write(chunk)

        if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
            return file_path
        return None
    except Exception as e:
        logger.error(f"Download video remote error: {e}")
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                pass
        return None


async def download_song(link: str) -> str:
    video_id = link.split("v=")[-1].split("&")[0] if "v=" in link else link
    if not video_id or len(video_id) < 3:
        return None

    # Step 1: Try local yt-dlp with cookies first
    logger.info(f"[Step 1] Attempting local yt-dlp download WITH cookies: {video_id}")
    file_path = await download_local_ytdlp(video_id, video=False, use_cookies=True)
    if file_path:
        logger.info(f"Local cookie download successful: {file_path}")
        return file_path

    # Step 2: Try remote Railway API
    logger.info(f"[Step 2] Local cookie download skipped/failed. Trying Railway API: {video_id}")
    file_path = await download_song_remote(video_id)
    if file_path:
        logger.info(f"Railway API download successful: {file_path}")
        return file_path

    # Step 3: Try local yt-dlp without cookies
    logger.info(f"[Step 3] Railway API download failed. Trying local yt-dlp WITHOUT cookies: {video_id}")
    file_path = await download_local_ytdlp(video_id, video=False, use_cookies=False)
    if file_path:
        logger.info(f"Local download without cookies successful: {file_path}")
        return file_path

    logger.error(f"All download methods failed for song: {video_id}")
    return None


async def download_video(link: str) -> str:
    video_id = link.split("v=")[-1].split("&")[0] if "v=" in link else link
    if not video_id or len(video_id) < 3:
        return None

    # Step 1: Try local yt-dlp with cookies first
    logger.info(f"[Step 1] Attempting local yt-dlp download WITH cookies: {video_id}")
    file_path = await download_local_ytdlp(video_id, video=True, use_cookies=True)
    if file_path:
        logger.info(f"Local cookie download successful: {file_path}")
        return file_path

    # Step 2: Try remote Railway API
    logger.info(f"[Step 2] Local cookie download skipped/failed. Trying Railway API: {video_id}")
    file_path = await download_video_remote(video_id)
    if file_path:
        logger.info(f"Railway API download successful: {file_path}")
        return file_path

    # Step 3: Try local yt-dlp without cookies
    logger.info(f"[Step 3] Railway API download failed. Trying local yt-dlp WITHOUT cookies: {video_id}")
    file_path = await download_local_ytdlp(video_id, video=True, use_cookies=False)
    if file_path:
        logger.info(f"Local download without cookies successful: {file_path}")
        return file_path

    logger.error(f"All download methods failed for video: {video_id}")
    return None


class YouTube:
    def __init__(self):
        self.base = "https://www.youtube.com/watch?v="
        self.regex = re.compile(
            r"(https?://)?(www\.|m\.|music\.)?"
            r"(youtube\.com/(watch\?v=|shorts/|playlist\?list=)|youtu\.be/)"
            r"([A-Za-z0-9_-]{11}|PL[A-Za-z0-9_-]+)([&?][^\s]*)?"
        )
        self.cookie_dir = "AloneX/cookies"

        # Dynamically load COOKIES_DATA env var if present (base64 cookies helper)
        cookies_data = os.environ.get("COOKIES_DATA")
        if cookies_data:
            try:
                import base64
                cookies_data = cookies_data.strip()
                missing_padding = len(cookies_data) % 4
                if missing_padding:
                    cookies_data += '=' * (4 - missing_padding)
                decoded = base64.b64decode(cookies_data).decode("utf-8")
                os.makedirs(self.cookie_dir, exist_ok=True)
                with open(os.path.join(self.cookie_dir, "cookie_0.txt"), "w") as f:
                    f.write(decoded)
                logger.info("Successfully loaded cookies from COOKIES_DATA environment variable.")
            except Exception as e:
                logger.error(f"Error decoding COOKIES_DATA environment variable: {e}")

    def get_cookies(self):
        if not os.path.exists(self.cookie_dir):
            return None
        cookies_files = [f for f in os.listdir(self.cookie_dir) if f.endswith(".txt")]
        if not cookies_files:
            return None
        return os.path.join(self.cookie_dir, random.choice(cookies_files))

    async def save_cookies(self, urls: list[str]) -> None:
        logger.info("Saving cookies from urls...")
        if not os.path.exists(self.cookie_dir):
            os.makedirs(self.cookie_dir)
        async with aiohttp.ClientSession() as session:
            for i, url in enumerate(urls):
                path = f"{self.cookie_dir}/cookie_{i}.txt"
                link = "https://batbin.me/api/v2/paste/" + url.split("/")[-1]
                async with session.get(link) as resp:
                    resp.raise_for_status()
                    with open(path, "wb") as fw:
                        fw.write(await resp.read())
        logger.info(f"Cookies saved in {self.cookie_dir}.")

    def valid(self, url: str) -> bool:
        return bool(re.match(self.regex, url))

    async def search(self, query: str, m_id: int, video: bool = False) -> Track | None:
        try:
            _search = VideosSearch(query, limit=1)
            results = await _search.next()
            if results and results["result"]:
                data = results["result"][0]
                return Track(
                    id=data.get("id"),
                    channel_name=data.get("channel", {}).get("name"),
                    duration=data.get("duration"),
                    duration_sec=utils.to_seconds(data.get("duration")) if data.get("duration") else 0,
                    message_id=m_id,
                    title=data.get("title")[:25],
                    thumbnail=data.get("thumbnails", [{}])[-1].get("url").split("?")[0],
                    url=data.get("link"),
                    view_count=data.get("viewCount", {}).get("short"),
                    video=video,
                )
        except Exception as e:
            logger.error(f"Search error: {e}")
        return None

    async def playlist(self, limit: int, user: str, url: str, video: bool) -> list[Track]:
        tracks = []
        try:
            plist = await Playlist.get(url)
            for data in plist.get("videos", [])[:limit]:
                track = Track(
                    id=data.get("id"),
                    channel_name=data.get("channel", {}).get("name", ""),
                    duration=data.get("duration"),
                    duration_sec=utils.to_seconds(data.get("duration")) if data.get("duration") else 0,
                    title=data.get("title")[:25],
                    thumbnail=data.get("thumbnails", [{}])[-1].get("url").split("?")[0],
                    url=data.get("link").split("&list=")[0],
                    user=user,
                    view_count="",
                    video=video,
                )
                tracks.append(track)
        except Exception as e:
            logger.error(f"Playlist error: {e}")
        return tracks

    async def download(self, video_id: str, video: bool = False) -> str | None:
        if not video_id or len(video_id) < 3:
            return None

        if video:
            return await download_video(video_id)
        else:
            return await download_song(video_id)

    async def get_stream_url(self, video_id: str, video: bool = False) -> str | None:
        """Quickly resolve a direct stream URL without downloading the file.
        Used for instant playback — pytgcalls/ffmpeg can stream directly from URLs.

        Priority:
        1. yt-dlp with cookies (extract_info, no download)
        2. Railway API /stream endpoint
        3. yt-dlp without cookies (extract_info, no download)
        """
        if not video_id or len(video_id) < 3:
            return None

        url = f"https://www.youtube.com/watch?v={video_id}"

        # Step 1: yt-dlp with cookies — just extract URL, no download
        cookie_file = self.get_cookies()
        if cookie_file:
            try:
                logger.info(f"[Stream Step 1] Resolving stream URL with cookies: {video_id}")
                stream_url = await self._extract_stream_url(url, video, cookie_file)
                if stream_url:
                    logger.info(f"[Stream] Got stream URL via cookies for {video_id}")
                    return stream_url
            except Exception as e:
                logger.error(f"[Stream Step 1] Cookie extract failed: {e}")

        # Step 2: Railway API /stream endpoint
        if API_KEY:
            try:
                logger.info(f"[Stream Step 2] Trying Railway API /stream: {video_id}")
                headers = {"X-API-Key": API_KEY}
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        f"{API_URL}/stream",
                        params={"id": video_id},
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=15),
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            if data.get("success"):
                                stream_info = data.get("stream", {})
                                stream_url = stream_info.get("url") or stream_info.get("audio_url")
                                if stream_url:
                                    logger.info(f"[Stream] Got stream URL via Railway API for {video_id}")
                                    return stream_url
            except Exception as e:
                logger.error(f"[Stream Step 2] Railway API failed: {e}")

        # Step 3: yt-dlp without cookies — just extract URL
        try:
            logger.info(f"[Stream Step 3] Resolving stream URL without cookies: {video_id}")
            stream_url = await self._extract_stream_url(url, video, None)
            if stream_url:
                logger.info(f"[Stream] Got stream URL without cookies for {video_id}")
                return stream_url
        except Exception as e:
            logger.error(f"[Stream Step 3] No-cookie extract failed: {e}")

        logger.error(f"[Stream] All stream URL methods failed for {video_id}")
        return None

    async def _extract_stream_url(self, url: str, video: bool, cookie_file: str | None) -> str | None:
        """Use yt-dlp extract_info (no download) to get the direct media URL."""
        ydl_opts = {
            "format": "bestvideo+bestaudio/best" if video else "bestaudio/best",
            "quiet": True,
            "no_warnings": True,
            "nocheckcertificate": True,
            "skip_download": True,
        }
        if cookie_file:
            ydl_opts["cookiefile"] = cookie_file

        loop = asyncio.get_event_loop()

        def _extract():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if not info:
                    return None
                # For format with separate audio/video, get the audio URL
                if not video and info.get("url"):
                    return info["url"]
                # Try requested_formats (when bestvideo+bestaudio merges)
                formats = info.get("requested_formats", [])
                if formats:
                    # For audio, pick the audio stream; for video pick the first (video)
                    if not video:
                        for fmt in formats:
                            if fmt.get("acodec") != "none" and fmt.get("vcodec") == "none":
                                return fmt.get("url")
                        return formats[-1].get("url")
                    else:
                        return formats[0].get("url")
                return info.get("url")

        return await loop.run_in_executor(None, _extract)

