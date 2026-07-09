# ALONE-CODER
import os
import re
import aiohttp
import random
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


async def download_song(link: str) -> str:
    video_id = link.split("v=")[-1].split("&")[0] if "v=" in link else link
    if not video_id or len(video_id) < 3:
        return None

    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    file_path = os.path.join(DOWNLOAD_DIR, f"{video_id}.mp3")
    if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
        return file_path

    try:
        headers = {"X-API-Key": API_KEY} if API_KEY else {}
        async with aiohttp.ClientSession() as session:
            # First get the download URL from Railway API
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
                    # Fallback: try /stream endpoint
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

            # Download the actual audio file
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
        logger.error(f"Download song error: {e}")
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                pass
        return None


async def download_video(link: str) -> str:
    video_id = link.split("v=")[-1].split("&")[0] if "v=" in link else link
    if not video_id or len(video_id) < 3:
        return None

    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    file_path = os.path.join(DOWNLOAD_DIR, f"{video_id}.mp4")
    if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
        return file_path

    try:
        headers = {"X-API-Key": API_KEY} if API_KEY else {}
        async with aiohttp.ClientSession() as session:
            # Try /video/hq for best quality video
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
                    # Fallback: try /download endpoint
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

            # Download the actual video file
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
        logger.error(f"Download video error: {e}")
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                pass
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
