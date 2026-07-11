# ALONE-CODER
import os
import re
import aiohttp
import random
import asyncio
import yt_dlp
from yt_dlp.utils import DownloadError
from py_yt import VideosSearch, Playlist
from AloneX import logger, config
from AloneX.helpers import Track, utils

API_URL = config.RAILWAY_YT_API_URL if config.RAILWAY_YT_API_URL else os.environ.get(
    "RAILWAY_YT_API_URL", "https://youtube-api-music-production-824b.up.railway.app"
)
API_KEY = config.RAILWAY_YT_API_KEY if config.RAILWAY_YT_API_KEY else os.environ.get(
    "RAILWAY_YT_API_KEY", ""
)

DOWNLOAD_DIR = "downloads"

# Prefer broadly available single-file formats. YouTube increasingly hides some
# DASH formats behind PO tokens, so strict bestaudio/bestvideo selectors can
# report "Requested format is not available" even when playable formats exist.
AUDIO_FORMAT = "bestaudio[ext=m4a]/bestaudio/best[acodec!=none]/best"
VIDEO_FORMAT = "best[height<=720][acodec!=none]/best[acodec!=none]/best"

# Extensions yt-dlp/ffmpeg may produce for media downloads.
MEDIA_EXTS = {".mp3", ".m4a", ".webm", ".mp4", ".ogg", ".opus", ".aac", ".flac"}


def _find_downloaded_file(video_id: str) -> str | None:
    """Return the actual media file produced for video_id (extension-agnostic).

    yt-dlp may write .webm/.m4a/etc. depending on the selected format, so we
    must not assume a fixed .mp3/.mp4 extension when checking for success.
    """
    if not os.path.isdir(DOWNLOAD_DIR):
        return None
    candidates = []
    for f in os.listdir(DOWNLOAD_DIR):
        if f.startswith(video_id) and os.path.splitext(f)[1].lower() in MEDIA_EXTS:
            full = os.path.join(DOWNLOAD_DIR, f)
            size = os.path.getsize(full)
            if size > 0:
                candidates.append((size, full))
    if not candidates:
        return None
    # Largest matching file is the completed download.
    candidates.sort(reverse=True)
    return candidates[0][1]


def _yt_dlp_options(video: bool, cookie_file: str | None = None) -> dict:
    options = {
        "format": VIDEO_FORMAT if video else AUDIO_FORMAT,
        "quiet": True,
        "no_warnings": True,
        "nocheckcertificate": True,
        "noplaylist": True,
        "retries": 3,
        "fragment_retries": 3,
        "extractor_args": {
            "youtube": {
                # When cookies are present yt-dlp authenticates and should use the
                # same clients it would normally pick while logged in. These
                # clients (tv_downgraded / web_safari) expose real, playable,
                # token-free formats — so songs actually stream/play instead of
                # failing with "Requested format is not available" or 403ing at
                # playback time. Without cookies we fall back to public clients,
                # but YouTube usually blocks those with a bot check, so cookies
                # are required for reliable playback.
                "player_client": (
                    ["tv_downgraded", "web_safari"]
                    if cookie_file
                    else ["web", "web_safari", "android", "ios"]
                ),
            }
        },
    }
    if cookie_file:
        options["cookiefile"] = cookie_file
    return options


async def download_local_ytdlp(video_id: str, video: bool = False, use_cookies: bool = True) -> str | None:
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    ext = "mp4" if video else "mp3"
    file_path = os.path.join(DOWNLOAD_DIR, f"{video_id}.{ext}")

    # A previous successful run may have left a usable file already.
    cached = _find_downloaded_file(video_id)
    if cached:
        return cached
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

    ydl_opts = _yt_dlp_options(video, cookie_file)
    ydl_opts["outtmpl"] = os.path.join(DOWNLOAD_DIR, f"{video_id}.%(ext)s")
    if cookie_file:
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

        # yt-dlp may have written a different extension (e.g. .webm/.m4a);
        # detect the actual produced file rather than assuming .mp3/.mp4.
        produced = _find_downloaded_file(video_id)
        if produced:
            return produced
    except Exception as e:
        logger.error(f"Local yt-dlp download (use_cookies={use_cookies}) failed for {video_id}: {e}")
        # Clean up partial files if any
        if os.path.isdir(DOWNLOAD_DIR):
            for f in os.listdir(DOWNLOAD_DIR):
                if f.startswith(video_id) and not f.endswith(f".{ext}"):
                    try:
                        os.remove(os.path.join(DOWNLOAD_DIR, f))
                    except Exception:
                        pass
    return None


async def download_song_remote(video_id: str) -> str | None:
    if not API_KEY:
        return None
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    file_path = os.path.join(DOWNLOAD_DIR, f"{video_id}.mp3")
    try:
        headers = {"X-API-Key": API_KEY}
        async with aiohttp.ClientSession() as session:
            # Prefer the /stream endpoint: it returns a single, directly
            # playable URL. The /download?type=audio endpoint currently only
            # populates best_video_url (best_audio_url is null), so we don't
            # rely on it for audio.
            async with session.get(
                f"{API_URL}/stream",
                params={"id": video_id},
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=60),
            ) as resp:
                if resp.status != 200:
                    logger.error(f"Railway API stream info failed: {resp.status}")
                    return None
                data = await resp.json()
                if not data.get("success"):
                    logger.error(f"Railway API returned failure: {data}")
                    return None

                stream_info = data.get("stream", {})
                audio_url = (
                    stream_info.get("url")
                    or stream_info.get("audio_url")
                    or stream_info.get("best_audio_url")
                    or stream_info.get("best_video_url")
                )

                if not audio_url:
                    logger.error("No audio URL found from Railway API")
                    return None

            async with session.get(
                audio_url,
                timeout=aiohttp.ClientTimeout(total=300),
                headers={"Range": "bytes=0-"},
            ) as dl_resp:
                if dl_resp.status not in (200, 206):
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

    # Step 1: Railway API (most reliable when RAILWAY_YT_API_KEY is set)
    if API_KEY:
        logger.info(f"[Step 1] Attempting Railway API download: {video_id}")
        file_path = await download_song_remote(video_id)
        if file_path:
            logger.info(f"Railway API download successful: {file_path}")
            return file_path

    # Step 2: Local yt-dlp with cookies (base64 COOKIES_DATA)
    logger.info(f"[Step 2] Railway API skipped/failed. Trying local yt-dlp WITH cookies: {video_id}")
    file_path = await download_local_ytdlp(video_id, video=False, use_cookies=True)
    if file_path:
        logger.info(f"Local cookie download successful: {file_path}")
        return file_path

    # Step 3: Local yt-dlp without cookies (last resort; YouTube often bot-blocks)
    logger.info(f"[Step 3] Cookie download failed. Trying local yt-dlp WITHOUT cookies: {video_id}")
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
        # Primary: py_yt (gives duration/channel metadata).
        try:
            plist = await Playlist.get(url)
            for data in plist.get("videos", [])[:limit]:
                track = Track(
                    id=data.get("id"),
                    channel_name=data.get("channel", {}).get("name", ""),
                    duration=data.get("duration"),
                    duration_sec=utils.to_seconds(data.get("duration")) if data.get("duration") else 0,
                    title=data.get("title")[:60],
                    thumbnail=data.get("thumbnails", [{}])[-1].get("url").split("?")[0],
                    url=data.get("link").split("&list=")[0],
                    user=user,
                    view_count="",
                    video=video,
                )
                tracks.append(track)
        except Exception as e:
            logger.error(f"Playlist error (py_yt): {e}")

        # Fallback: yt-dlp flat-playlist (no n-challenge, just lists IDs).
        if not tracks:
            try:
                entries = await self._flat_entries(url, limit, self.get_cookies())
                for e in entries:
                    tracks.append(self._track_from_entry(e, user, video))
            except Exception as e:
                logger.error(f"Playlist fallback error: {e}")

        return tracks[:limit]

    async def _flat_entries(self, url: str, limit: int, cookie_file: str | None = None) -> list[dict]:
        """List playlist entries cheaply via yt-dlp extract_flat (no download).

        extract_flat only scrapes the page metadata — it never solves the
        n-signature challenge, so it is far more reliable than full extraction
        and works without Node/PO tokens.
        """
        opts = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": True,
            "skip_download": True,
            "noplaylist": False,
            "extractor_args": {
                "youtube": {
                    "player_client": (
                        ["tv_downgraded", "web_safari"]
                        if cookie_file
                        else ["web_safari", "web"]
                    )
                }
            },
        }
        if cookie_file:
            opts["cookiefile"] = cookie_file

        loop = asyncio.get_event_loop()

        def _extract():
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
            entries = info.get("entries") or []
            return [e for e in entries if e.get("id")][:limit]

        return await loop.run_in_executor(None, _extract)

    def _track_from_entry(self, e: dict, user: str, video: bool) -> Track:
        vid = e.get("id")
        return Track(
            id=vid,
            channel_name=e.get("channel") or e.get("uploader") or "",
            duration="",
            duration_sec=0,
            title=(e.get("title") or "Unknown")[:60],
            thumbnail=e.get("thumbnails", [{}])[-1].get("url", "").split("?")[0]
            if e.get("thumbnails")
            else "",
            url=f"https://www.youtube.com/watch?v={vid}",
            user=user,
            view_count="",
            video=video,
        )

    async def related(
        self,
        video_id: str,
        title: str,
        user: str,
        video: bool,
        limit: int = 1,
        exclude_ids: set[str] = None,
    ) -> list[Track]:
        """Fetch related/autoplay tracks for a given video.

        Tries YouTube's autoplay mix (RD playlist) first, then falls back to a
        title search. Excludes the source id and any ids in exclude_ids to
        avoid immediate repeats.
        """
        exclude_ids = exclude_ids or set()
        exclude_ids.add(video_id)
        tracks: list[Track] = []

        # 1. YouTube autoplay mix (RD<video_id>) via flat extraction.
        try:
            mix_url = f"https://www.youtube.com/watch?v={video_id}&list=RD{video_id}"
            entries = await self._flat_entries(
                mix_url, limit + len(exclude_ids), self.get_cookies()
            )
            for e in entries:
                if e.get("id") and e["id"] not in exclude_ids:
                    tracks.append(self._track_from_entry(e, user, video))
                if len(tracks) >= limit:
                    break
        except Exception as e:
            logger.error(f"Related mix error: {e}")

        # 2. Fallback: search by title.
        if not tracks and title:
            try:
                _search = VideosSearch(f"{title} official audio", limit=1)
                results = await _search.next()
                if results and results["result"]:
                    data = results["result"][0]
                    rid = data.get("id")
                    if rid and rid not in exclude_ids:
                        tracks.append(
                            Track(
                                id=rid,
                                channel_name=data.get("channel", {}).get("name", ""),
                                duration=data.get("duration"),
                                duration_sec=utils.to_seconds(data.get("duration")) if data.get("duration") else 0,
                                title=data.get("title")[:60],
                                thumbnail=data.get("thumbnails", [{}])[-1].get("url", "").split("?")[0],
                                url=data.get("link"),
                                user=user,
                                view_count="",
                                video=video,
                            )
                        )
            except Exception as e:
                logger.error(f"Related search fallback error: {e}")

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
        1. Railway API /stream endpoint (most reliable when key is set)
        2. yt-dlp with cookies (extract_info, no download)
        3. yt-dlp without cookies (extract_info, no download)
        """
        if not video_id or len(video_id) < 3:
            return None

        url = f"https://www.youtube.com/watch?v={video_id}"

        # Step 1: Railway API /stream endpoint
        if API_KEY:
            try:
                logger.info(f"[Stream Step 1] Trying Railway API /stream: {video_id}")
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
                                stream_url = (
                                    stream_info.get("url")
                                    or stream_info.get("audio_url")
                                    or stream_info.get("best_video_url")
                                )
                                if stream_url:
                                    logger.info(f"[Stream] Got stream URL via Railway API for {video_id}")
                                    return stream_url
                        else:
                            body = (await resp.text())[:500]
                            logger.error(
                                f"[Stream Step 1] Railway API status {resp.status}: {body}"
                            )
            except Exception as e:
                logger.error(f"[Stream Step 1] Railway API failed: {e}")

        # Step 2: yt-dlp with cookies — just extract URL, no download
        cookie_file = self.get_cookies()
        if cookie_file:
            try:
                logger.info(f"[Stream Step 2] Resolving stream URL with cookies: {video_id}")
                stream_url = await self._extract_stream_url(url, video, cookie_file)
                if stream_url:
                    logger.info(f"[Stream] Got stream URL via cookies for {video_id}")
                    return stream_url
            except Exception as e:
                logger.error(f"[Stream Step 2] Cookie extract failed: {e}")

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
        ydl_opts = _yt_dlp_options(video, cookie_file)
        ydl_opts["skip_download"] = True

        loop = asyncio.get_event_loop()

        def _extract():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                try:
                    info = ydl.extract_info(url, download=False)
                except DownloadError:
                    # The format selector may still fail on some videos (e.g. all
                    # progressive formats need a PO token). Fall back to a broad
                    # scan so we can still hand back a usable stream URL.
                    ydl.params["format"] = "best" if video else "bestaudio/best"
                    info = ydl.extract_info(url, download=False)
                if not info:
                    return None

                # For audio, prefer a direct audio-only URL so pytgcalls gets a
                # clean stream instead of a merged container.
                if not video and info.get("acodec") != "none" and info.get("url"):
                    return info["url"]

                # Try requested_formats (when bestvideo+bestaudio merges)
                formats = info.get("requested_formats", [])
                if formats:
                    if not video:
                        for fmt in formats:
                            if fmt.get("acodec") != "none" and fmt.get("vcodec") == "none":
                                return fmt.get("url")
                        # No pure-audio stream in the merge; return the audio side.
                        for fmt in formats:
                            if fmt.get("acodec") != "none":
                                return fmt.get("url")
                        return formats[-1].get("url")
                    else:
                        return formats[0].get("url")

                return info.get("url")

        return await loop.run_in_executor(None, _extract)

