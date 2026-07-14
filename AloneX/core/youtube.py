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
    "RAILWAY_YT_API_URL", "https://youtube-api-saas-backend.onrender.com"
)
API_KEY = config.RAILWAY_YT_API_KEY if config.RAILWAY_YT_API_KEY else os.environ.get(
    "RAILWAY_YT_API_KEY", "lily_If5GeswRaQESaifBoBxMHlYZVqhJF1Y"
)

DOWNLOAD_DIR = "downloads"

# Prefer broadly available single-file formats. YouTube increasingly hides some
# DASH formats behind PO tokens, so strict bestaudio/bestvideo selectors can
# report "Requested format is not available" even when playable formats exist.
# Don't lead with ext=m4a — the FFmpegExtractAudio postprocessor converts to mp3
# regardless of the source container, so the leading filter only ever causes
# spurious "Requested format is not available" failures.
AUDIO_FORMAT = "bestaudio/best[acodec!=none]/best"
VIDEO_FORMAT = "best[height<=720][acodec!=none]/best[acodec!=none]/best"

# Extensions yt-dlp/ffmpeg may produce for media downloads.
MEDIA_EXTS = {".mp3", ".m4a", ".webm", ".mp4", ".ogg", ".opus", ".aac", ".flac"}

# Per-video-id asyncio locks. Multiple concurrent callers of YouTube.download()
# for the same video (e.g. a background prefetch scheduled at queue.add() time
# racing with a direct yt.download() from _play_track / play_next) all wait on
# the same lock. The first caller downloads; subsequent waiters see the file
# on disk after acquiring the lock and return the cached path without hitting
# the SaaS API again. We never delete entries from this dict — each lock is
# ~50 bytes, and the number of unique ids over the bot's lifetime is bounded.
_download_locks: dict[str, asyncio.Lock] = {}


def _get_download_lock(key: str) -> asyncio.Lock:
    lock = _download_locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _download_locks[key] = lock
    return lock

# yt-dlp 2026.x solved YouTube's n-signature challenge with a JS runtime.
# Default/deno is unreliable in containers and silently falls back to a broken
# runtime, producing "Sign in to confirm you're a bot". We require Node (>= 23.5
# must be installed in the image — see Dockerfile) and select it explicitly.
# NOTE: the option is a DICT {"node": {}}, not a list; a list raises ValueError.
JS_RUNTIMES = {"node": {}}


def _with_js_runtime(opts: dict) -> dict:
    """Return a copy of yt-dlp options with the Node JS runtime selected.

    Used by every YoutubeDL() construction so YouTube's n-signature challenge is
    solved reliably (the container image installs Node >= 23.5 for this).
    """
    merged = dict(opts)
    merged["js_runtimes"] = JS_RUNTIMES
    return merged


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
                # Prefer the public web-based clients (web_safari/web/android/ios)
                # which reliably return playable audio formats. tv_downgraded is
                # kept only as a trailing last resort: it now frequently returns
                # formats that don't satisfy the audio selector, raising
                # "Requested format is not available". Cookies are still passed
                # through (cookiefile) when available for authenticated fetches,
                # but we no longer lead with the client that causes the failure.
                "player_client": (
                    ["web_safari", "web", "android", "ios", "tv_downgraded"]
                    if cookie_file
                    else ["web_safari", "web", "android", "ios"]
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
            with yt_dlp.YoutubeDL(_with_js_runtime(ydl_opts)) as ydl:
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
                if f.startswith(video_id):
                    try:
                        os.remove(os.path.join(DOWNLOAD_DIR, f))
                    except Exception:
                        pass
    return None


def _pick_audio_stream(streams: list[dict]) -> dict | None:
    """Choose the best audio-only stream from /api/youtube/audio results.

    itag 140 (m4a, ~128 kbps AAC) is the widely-compatible sweet spot for
    pytgcalls/ffmpeg. Falls back to any opus/webm audio, then anything.
    """
    if not streams:
        return None
    for fmt in streams:
        if str(fmt.get("format_id")) == "140":
            return fmt
    for fmt in streams:
        if fmt.get("ext") in ("m4a", "webm", "opus", "ogg"):
            return fmt
    return streams[0]


async def _download_from_proxy(
    session: aiohttp.ClientSession,
    url: str,
    file_path: str,
    total_timeout: int = 300,
) -> bool:
    """Stream bytes from a SaaS-proxy URL to `file_path`. Returns True on success.

    On non-2xx the response body is logged (truncated) so the caller can tell
    a rate-limit (429) apart from a genuine miss (404).
    """
    headers = {"X-API-Key": API_KEY} if API_KEY else {}
    async with session.get(
        url,
        headers=headers,
        timeout=aiohttp.ClientTimeout(total=total_timeout),
    ) as resp:
        if resp.status not in (200, 206):
            body = (await resp.text())[:300]
            logger.error(f"SaaS proxy {url} status {resp.status}: {body}")
            return False
        with open(file_path, "wb") as f:
            async for chunk in resp.content.iter_chunked(131072):
                f.write(chunk)
    return os.path.exists(file_path) and os.path.getsize(file_path) > 0


async def download_song_remote(video_id: str) -> str | None:
    """Download the audio track via the SaaS YouTube API.

    Primary: GET /api/youtube/play/audio — the API re-fetches googlevideo bytes
    server-side and streams them back as audio/mpeg. This bypasses the
    ip=<api-egress> lock on signed googlevideo URLs (the bot container has a
    different egress and would otherwise get 403).
    Fallback: GET /api/youtube/audio — pick itag 140 and fetch the signed URL
    directly (only works if the bot happens to share an egress-ASN the URL
    tolerates; kept for self-hosted deployments where that's true).
    """
    if not API_KEY:
        return None
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    # Keep the .mp3 filename convention the rest of the codebase expects; the
    # proxy already delivers audio/mpeg, and ffmpeg reads by container magic
    # regardless.
    file_path = os.path.join(DOWNLOAD_DIR, f"{video_id}.mp3")
    try:
        async with aiohttp.ClientSession() as session:
            # Tier 1: byte-proxy.
            if await _download_from_proxy(
                session,
                f"{API_URL}/api/youtube/play/audio?id={video_id}",
                file_path,
                total_timeout=300,
            ):
                logger.info(f"SaaS proxy /api/youtube/play/audio download successful: {file_path}")
                return file_path
            # Wipe any partial write before falling back.
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except Exception:
                    pass

            # Tier 2: JSON + signed URL (IP-locked; may 403 from a different egress).
            headers = {"X-API-Key": API_KEY}
            async with session.get(
                f"{API_URL}/api/youtube/audio",
                params={"id": video_id},
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=60),
            ) as resp:
                if resp.status != 200:
                    body = (await resp.text())[:300]
                    logger.error(f"SaaS API /api/youtube/audio status {resp.status}: {body}")
                    return None
                data = await resp.json()

            if not data.get("success"):
                logger.error(f"SaaS API /api/youtube/audio returned failure: {data}")
                return None

            audio_streams = data.get("audio", {}).get("audio_streams") or []
            fmt = _pick_audio_stream(audio_streams)
            audio_url = fmt.get("url") if fmt else None
            if not audio_url:
                logger.error("SaaS API /api/youtube/audio returned no audio_streams")
                return None

            async with session.get(
                audio_url,
                timeout=aiohttp.ClientTimeout(total=300),
                headers={"Range": "bytes=0-"},
            ) as dl_resp:
                if dl_resp.status not in (200, 206):
                    logger.error(f"Signed googlevideo fetch failed: {dl_resp.status} (likely IP-lock)")
                    return None
                with open(file_path, "wb") as f:
                    async for chunk in dl_resp.content.iter_chunked(131072):
                        f.write(chunk)

        if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
            logger.info(
                f"SaaS API audio (signed URL) download successful (itag={fmt.get('format_id') if fmt else '?'}): {file_path}"
            )
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
    """Download a muxed mp4 via the SaaS YouTube API.

    Primary: GET /api/youtube/play/video/hq (byte-proxy) with
    /api/youtube/play/video as a secondary proxy path.
    Fallback: GET /api/youtube/stream — signed itag=18 mp4 URL (IP-locked).
    """
    if not API_KEY:
        return None
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    file_path = os.path.join(DOWNLOAD_DIR, f"{video_id}.mp4")
    try:
        async with aiohttp.ClientSession() as session:
            # Tier 1: byte-proxy variants (hq preferred, plain video fallback).
            for proxy_path in ("/api/youtube/play/video/hq", "/api/youtube/play/video"):
                if await _download_from_proxy(
                    session,
                    f"{API_URL}{proxy_path}?id={video_id}",
                    file_path,
                    total_timeout=600,
                ):
                    logger.info(f"SaaS proxy {proxy_path} download successful: {file_path}")
                    return file_path
                if os.path.exists(file_path):
                    try:
                        os.remove(file_path)
                    except Exception:
                        pass

            # Tier 2: signed googlevideo URL (IP-locked).
            headers = {"X-API-Key": API_KEY}
            async with session.get(
                f"{API_URL}/api/youtube/stream",
                params={"id": video_id},
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=60),
            ) as resp:
                if resp.status != 200:
                    body = (await resp.text())[:300]
                    logger.error(f"SaaS API /api/youtube/stream status {resp.status}: {body}")
                    return None
                data = await resp.json()

            if not data.get("success"):
                logger.error(f"SaaS API /api/youtube/stream returned failure: {data}")
                return None

            video_url = data.get("stream", {}).get("url")
            if not video_url:
                logger.error("SaaS API /api/youtube/stream returned no url")
                return None

            async with session.get(
                video_url,
                timeout=aiohttp.ClientTimeout(total=600),
                headers={"Range": "bytes=0-"},
            ) as dl_resp:
                if dl_resp.status not in (200, 206):
                    logger.error(f"Signed googlevideo video fetch failed: {dl_resp.status} (likely IP-lock)")
                    return None
                with open(file_path, "wb") as f:
                    async for chunk in dl_resp.content.iter_chunked(131072):
                        f.write(chunk)

        if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
            logger.info(f"SaaS API video (signed URL) download successful: {file_path}")
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
    # API-only mode: the bot NEVER falls back to local yt-dlp. Every download
    # goes through the SaaS API (RAILWAY_YT_API_KEY / RAILWAY_YT_API_URL) so
    # anti-bot / cookie / IP-lock problems are centralised on the API side and
    # the bot's VPS IP is never exposed to YouTube. If the API can't deliver
    # the track, we fail cleanly rather than tripping YouTube's bot-check from
    # the bot's own egress.
    video_id = link.split("v=")[-1].split("&")[0] if "v=" in link else link
    if not video_id or len(video_id) < 3:
        return None

    if not API_KEY:
        logger.error(
            "RAILWAY_YT_API_KEY not configured; API-only download disabled."
        )
        return None

    logger.info(f"[API] Attempting SaaS API audio download: {video_id}")
    file_path = await download_song_remote(video_id)
    if file_path:
        logger.info(f"SaaS API audio download successful: {file_path}")
        return file_path

    logger.error(f"SaaS API audio download failed for song: {video_id}")
    return None


async def download_video(link: str) -> str:
    # API-only mode: same rationale as download_song — every fetch goes
    # through the SaaS API. No local yt-dlp fallback.
    video_id = link.split("v=")[-1].split("&")[0] if "v=" in link else link
    if not video_id or len(video_id) < 3:
        return None

    if not API_KEY:
        logger.error(
            "RAILWAY_YT_API_KEY not configured; API-only download disabled."
        )
        return None

    logger.info(f"[API] Attempting SaaS API video download: {video_id}")
    file_path = await download_video_remote(video_id)
    if file_path:
        logger.info(f"SaaS API video download successful: {file_path}")
        return file_path

    logger.error(f"SaaS API video download failed: {video_id}")
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
                import gzip as _gzip
                cookies_data = cookies_data.strip()
                missing_padding = len(cookies_data) % 4
                if missing_padding:
                    cookies_data += '=' * (4 - missing_padding)
                decoded_bytes = base64.b64decode(cookies_data)
                # Handle gzip-compressed cookies (magic bytes \x1f\x8b)
                if decoded_bytes[:2] == b'\x1f\x8b':
                    decoded_bytes = _gzip.decompress(decoded_bytes)
                decoded = decoded_bytes.decode("utf-8")
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
                        ["web_safari", "web", "android", "ios", "tv_downgraded"]
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
            with yt_dlp.YoutubeDL(_with_js_runtime(opts)) as ydl:
                info = ydl.extract_info(url, download=False)
            entries = info.get("entries") or []
            return [e for e in entries if e.get("id")][:limit]

        return await loop.run_in_executor(None, _extract)

    def _track_from_entry(self, e: dict, user: str, video: bool) -> Track:
        vid = e.get("id")
        # Duration from flat extraction is usually a display string
        # ("3:45") or a seconds int — normalise so the now-playing card shows
        # a real "Duration : X" instead of a blank field.
        raw_dur = e.get("duration")
        if isinstance(raw_dur, int):
            duration = (
                f"{raw_dur // 60}:{raw_dur % 60:02d}"
                if raw_dur >= 60
                else f"0:{raw_dur:02d}"
            )
            duration_sec = raw_dur
        elif isinstance(raw_dur, str) and raw_dur.strip():
            duration = raw_dur.strip()
            duration_sec = utils.to_seconds(duration)
        else:
            duration = ""
            duration_sec = 0
        title = (e.get("title") or "Unknown")[:60]
        thumb = (
            e.get("thumbnails", [{}])[-1].get("url", "").split("?")[0]
            if e.get("thumbnails")
            else ""
        )
        return Track(
            id=vid,
            channel_name=e.get("channel") or e.get("uploader") or "",
            duration=duration,
            duration_sec=duration_sec,
            title=title,
            thumbnail=thumb,
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

    async def playlist_by_name(
        self, name: str, user: str, video: bool, limit: int
    ) -> list[Track]:
        """Search YouTube for a playlist by NAME and return its tracks.

        Used by the /playlist command. Prefers py_yt PlaylistSearch; the
        resulting playlist URL is then resolved by the normal playlist()
        path (which itself has a yt-dlp flat fallback).
        """
        url = None
        try:
            # NOTE: the class is `PlaylistsSearch` (plural) in py_yt, and each
            # result item exposes the playlist URL under the `link` key (there is
            # no `url` key). Importing `PlaylistSearch` raised
            # "cannot import name 'PlaylistSearch' from 'py_yt'".
            from py_yt import PlaylistsSearch

            res = await PlaylistsSearch(name, limit=1).next()
            items = res.get("result") or []
            if items:
                url = items[0].get("link") or items[0].get("url")
        except Exception as e:
            logger.error(f"PlaylistsSearch error: {e}")

        if not url:
            return []
        return await self.playlist(limit, user, url, video)

    async def suggestions(
        self, query: str, limit: int = 5, video: bool = False
    ) -> list[Track]:
        """Return top-N video search results as Track objects (for /suggest)."""
        out: list[Track] = []
        try:
            res = await VideosSearch(query, limit=limit).next()
            for d in res.get("result", []):
                out.append(
                    Track(
                        id=d.get("id"),
                        channel_name=d.get("channel", {}).get("name", ""),
                        duration=d.get("duration"),
                        duration_sec=utils.to_seconds(d.get("duration")) if d.get("duration") else 0,
                        title=d.get("title")[:60],
                        thumbnail=d.get("thumbnails", [{}])[-1].get("url", "").split("?")[0],
                        url=d.get("link"),
                        view_count=d.get("viewCount", {}).get("short"),
                        video=video,
                    )
                )
        except Exception as e:
            logger.error(f"Suggestions error: {e}")
        return out

    async def download(self, video_id: str, video: bool = False) -> str | None:
        if not video_id or len(video_id) < 3:
            return None

        # Coalesce concurrent downloads of the same track under a per-id
        # lock. Prevents the SaaS API from being hit twice when a background
        # prefetch (scheduled at queue.add() time) races with a direct
        # yt.download() call from _play_track or play_next.
        key = f"{'v' if video else 'a'}:{video_id}"
        async with _get_download_lock(key):
            # If a peer download for the same id just finished while we were
            # waiting for the lock, reuse the file it produced instead of
            # re-fetching. Filenames follow the .mp3/.mp4 convention set by
            # download_song_remote / download_video_remote.
            ext = "mp4" if video else "mp3"
            cached = os.path.join(DOWNLOAD_DIR, f"{video_id}.{ext}")
            if os.path.exists(cached) and os.path.getsize(cached) > 0:
                logger.info(f"Download coalesced (cache hit): {cached}")
                return cached

            if video:
                return await download_video(video_id)
            else:
                return await download_song(video_id)

    async def get_stream_url(self, video_id: str, video: bool = False) -> str | None:
        """Resolve a stream URL via the SaaS API (API-only, fast path).

        We return the SaaS byte-proxy URL immediately without probing. A HEAD /
        Range=0-1023 GET probe previously ran here to validate the endpoint
        before handing to ffmpeg, but the probe itself was the latency bottleneck
        (~15–20 s on Onrender per fresh video id) — exactly the same processing
        the API would do anyway when ffmpeg later opens the URL. Skipping the
        probe moves that wait from a bot-blocking phase to ffmpeg's opportunistic
        buffering phase, so the Telegram "now playing" message and pytgcalls
        setup complete in <1 s.

        The api_key rides in the query string because pytgcalls/ffmpeg cannot be
        told to send custom headers here. If the API is misconfigured or the
        video is unavailable, pytgcalls fails at open time and the caller can
        retry via yt.download() next time.
        """
        if not video_id or len(video_id) < 3:
            return None

        if not API_KEY:
            logger.error(
                "[Stream] RAILWAY_YT_API_KEY not configured; API-only stream disabled."
            )
            return None

        # High-quality video first, then regular; audio is single-endpoint.
        path = (
            "/api/youtube/play/video/hq"
            if video
            else "/api/youtube/play/audio"
        )
        proxy_url = f"{API_URL}{path}?id={video_id}&api_key={API_KEY}"
        logger.info(f"[Stream API] Fast-path proxy URL {path} for {video_id}")
        return proxy_url

    async def _keepalive_ping(self) -> None:
        """Send one lightweight ping to the SaaS API so its Onrender container
        stays warm. Onrender free tier spins the dyno down after ~15 min idle
        and the next request cold-starts (+5–10 s). We hit /api/youtube/details
        for a well-known short video id which returns cached metadata quickly
        without triggering a full googlevideo fetch.
        """
        if not API_KEY or not API_URL:
            return
        ping_url = (
            f"{API_URL}/api/youtube/details?id=dQw4w9WgXcQ&api_key={API_KEY}"
        )
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    ping_url,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status == 200:
                        logger.info("[Keepalive] SaaS API warm.")
                    else:
                        logger.warning(
                            f"[Keepalive] SaaS API returned status {resp.status}"
                        )
        except Exception as e:
            logger.warning(
                f"[Keepalive] SaaS API ping failed: {type(e).__name__}: {e}"
            )

    async def start_keepalive(self, interval: int = 240) -> None:
        """Background loop: fire an immediate warmup, then ping every `interval`
        seconds (default 4 min, well under Onrender's ~15 min spin-down).
        Never raises — all errors are swallowed inside _keepalive_ping.
        """
        while True:
            await self._keepalive_ping()
            await asyncio.sleep(interval)

    async def _extract_stream_url(self, url: str, video: bool, cookie_file: str | None) -> str | None:
        """Use yt-dlp extract_info (no download) to get the direct media URL."""
        ydl_opts = _yt_dlp_options(video, cookie_file)
        ydl_opts["skip_download"] = True

        loop = asyncio.get_event_loop()

        def _extract():
            with yt_dlp.YoutubeDL(_with_js_runtime(ydl_opts)) as ydl:
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

