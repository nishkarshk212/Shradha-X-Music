# Copyright (c) 2025 TheHamkerAlone 
# Licensed under the MIT License.
# This file is make by @XoDrk
# ALONE-CODER 
# Redesigned thumbnail matching premium style with dynamic theme coloring

import os
import aiohttp
import random
import re
import hashlib

from PIL import (
    Image,
    ImageDraw,
    ImageEnhance,
    ImageFilter,
    ImageFont,
)

from AloneX import app, config, logger
from AloneX.helpers import Track


class Thumbnail:
    def __init__(self):
        self.width = 1280
        self.height = 720

        self.album_size = 350
        self.radius = 30

        self.font_title = ImageFont.truetype(
            "AloneX/helpers/Raleway-Bold.ttf",
            52,
        )

        self.font_label = ImageFont.truetype(
            "AloneX/helpers/Raleway-Bold.ttf",
            32,
        )

        self.font_value = ImageFont.truetype(
            "AloneX/helpers/Inter-Light.ttf",
            32,
        )

        self.font_small = ImageFont.truetype(
            "AloneX/helpers/Inter-Light.ttf",
            26,
        )

    async def save_thumb(
        self,
        output_path: str,
        url: str,
    ) -> str:
        if not url or not isinstance(url, str):
            # No valid thumbnail URL — nothing to download.
            return None
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                open(output_path, "wb").write(
                    await resp.read()
                )
        return output_path

    def trim_text(
        self,
        text,
        font,
        max_width,
    ):
        if font.getlength(text) <= max_width:
            return text

        dots = "..."

        for i in range(len(text), 0, -1):
            temp = text[:i] + dots

            if font.getlength(temp) <= max_width:
                return temp

        return dots

    async def generate(
        self,
        song: Track,
        user: str = None,
    ) -> str:

        try:
            # Clean HTML tags from requester name (e.g. from pyrogram mention)
            req_by = user or song.user or "Unknown"
            req_by = re.sub(r'<[^>]+>', '', req_by).strip()
            
            # Cache file names (include hash of requester to avoid stale cache for same song)
            user_hash = hashlib.md5(req_by.encode('utf-8')).hexdigest()[:6]
            temp = f"cache/raw_{song.id}.jpg"
            output = f"cache/{song.id}_{user_hash}.png"

            if os.path.exists(output):
                return output

            # Download the source thumbnail. If it's missing/invalid, we still
            # render a premium themed card (title/duration/requester) instead of
            # bailing to DEFAULT_THUMB — so now-playing always shows the info.
            temp_thumb = await self.save_thumb(temp, song.thumbnail)
            img = None

            if temp_thumb and os.path.exists(temp_thumb):
                img = Image.open(temp_thumb).convert("RGBA")

                # Create blurred background from thumbnail
                bg = img.resize(
                    (
                        self.width,
                        self.height,
                    ),
                    Image.Resampling.LANCZOS,
                )

                bg = bg.filter(
                    ImageFilter.GaussianBlur(50)
                )

                bg = ImageEnhance.Brightness(
                    bg
                ).enhance(0.35)
            else:
                # No thumbnail available — start from a dark base so the text
                # and theme tint are still drawn.
                logger.warning(
                    f"No thumbnail for {song.id}; rendering text card only."
                )
                bg = Image.new(
                    "RGBA",
                    (self.width, self.height),
                    (18, 18, 24, 255),
                )

            # Premium dynamic color themes: (R, G, B)
            THEMES = [
                (30, 144, 255),   # Neon Blue
                (50, 205, 50),    # Lime/Neon Green
                (255, 20, 147),   # Deep Pink/Magenta
                (138, 43, 226),   # Blue Violet
                (255, 69, 0),     # Red Orange
                (0, 206, 209),    # Dark Turquoise
                (255, 165, 0),    # Orange
            ]
            
            # Select consistent dynamic theme color based on song.id
            theme_idx = sum(ord(c) for c in (song.id or "theme")) % len(THEMES)
            theme_color = THEMES[theme_idx]

            # Add theme tint overlay
            theme_overlay = Image.new(
                "RGBA",
                (self.width, self.height),
                (theme_color[0], theme_color[1], theme_color[2], 50),
            )
            bg = Image.alpha_composite(bg, theme_overlay)

            draw = ImageDraw.Draw(bg)

            # ─── Album Art (Left Side) ───
            frame_x = 70
            frame_y = (
                self.height
                - self.album_size
            ) // 2 - 20

            if img is not None:
                album = img.resize(
                    (
                        self.album_size,
                        self.album_size,
                    ),
                    Image.Resampling.LANCZOS,
                )

                # Rounded mask for album
                mask = Image.new(
                    "L",
                    (
                        self.album_size,
                        self.album_size,
                    ),
                    0,
                )

                ImageDraw.Draw(mask).rounded_rectangle(
                    (
                        0,
                        0,
                        self.album_size,
                        self.album_size,
                    ),
                    radius=self.radius,
                    fill=255,
                )

                # Theme glow shadow behind album
                glow_size = self.album_size + 50
                glow = Image.new(
                    "RGBA",
                    (glow_size, glow_size),
                    (0, 0, 0, 0),
                )

                ImageDraw.Draw(glow).rounded_rectangle(
                    (
                        15,
                        15,
                        glow_size - 15,
                        glow_size - 15,
                    ),
                    radius=self.radius + 10,
                    fill=(theme_color[0], theme_color[1], theme_color[2], 130),
                )

                glow = glow.filter(
                    ImageFilter.GaussianBlur(25)
                )

                bg.paste(
                    glow,
                    (
                        frame_x - 25,
                        frame_y - 25,
                    ),
                    glow,
                )

                # Paste album art
                bg.paste(
                    album,
                    (
                        frame_x,
                        frame_y,
                    ),
                    mask,
                )

                # White border around album
                draw.rounded_rectangle(
                    (
                        frame_x - 3,
                        frame_y - 3,
                        frame_x + self.album_size + 3,
                        frame_y + self.album_size + 3,
                    ),
                    radius=self.radius + 2,
                    outline=(255, 255, 255, 200),
                    width=4,
                )

            # ─── Text Info (Right Side) ───
            text_x = frame_x + self.album_size + 80
            max_text_width = self.width - text_x - 60

            # Song Title (Bold, White)
            title = self.trim_text(
                song.title,
                self.font_title,
                max_text_width,
            )

            draw.text(
                (text_x, frame_y + 10),
                title,
                font=self.font_title,
                fill=(255, 255, 255),
            )

            # Info lines with "Label | Value" format
            info_y = frame_y + 85
            line_spacing = 50

            # Channel
            channel_name = self.trim_text(
                song.channel_name or "Unknown",
                self.font_value,
                max_text_width - self.font_label.getlength("Channel | "),
            )
            draw.text(
                (text_x, info_y),
                "Channel | ",
                font=self.font_label,
                fill=(200, 200, 200),
            )
            draw.text(
                (text_x + self.font_label.getlength("Channel | "), info_y),
                channel_name,
                font=self.font_value,
                fill=(180, 180, 180),
            )

            # Views
            info_y += line_spacing
            views = song.view_count or "N/A"
            draw.text(
                (text_x, info_y),
                "Views | ",
                font=self.font_label,
                fill=(200, 200, 200),
            )
            draw.text(
                (text_x + self.font_label.getlength("Views | "), info_y),
                views,
                font=self.font_value,
                fill=(180, 180, 180),
            )

            # Player (bot name)
            info_y += line_spacing
            player_name = f"@{app.username}" if hasattr(app, "username") and app.username else app.name if hasattr(app, "name") else "Music Bot"
            draw.text(
                (text_x, info_y),
                "Player | ",
                font=self.font_label,
                fill=(200, 200, 200),
            )
            draw.text(
                (text_x + self.font_label.getlength("Player | "), info_y),
                player_name,
                font=self.font_value,
                fill=(180, 180, 180),
            )

            # Requested By
            info_y += line_spacing
            req_by_trimmed = self.trim_text(
                req_by,
                self.font_value,
                max_text_width - self.font_label.getlength("Requested By | "),
            )
            draw.text(
                (text_x, info_y),
                "Requested By | ",
                font=self.font_label,
                fill=(200, 200, 200),
            )
            draw.text(
                (text_x + self.font_label.getlength("Requested By | "), info_y),
                req_by_trimmed,
                font=self.font_value,
                fill=(theme_color[0], theme_color[1], theme_color[2]),
            )

            # ─── Progress Bar ───
            bar_x = text_x
            bar_y = info_y + 80
            bar_width = max_text_width
            bar_height = 8

            # Background bar (gray)
            draw.rounded_rectangle(
                (
                    bar_x,
                    bar_y,
                    bar_x + bar_width,
                    bar_y + bar_height,
                ),
                radius=4,
                fill=(100, 100, 100, 120),
            )

            # Progress fill (theme color)
            progress = 0.05
            draw.rounded_rectangle(
                (
                    bar_x,
                    bar_y,
                    bar_x + int(bar_width * progress),
                    bar_y + bar_height,
                ),
                radius=4,
                fill=(theme_color[0], theme_color[1], theme_color[2], 255),
            )

            # Progress dot (white)
            dot_radius = 8
            dot_x = bar_x + int(bar_width * progress)
            draw.ellipse(
                (
                    dot_x - dot_radius,
                    bar_y - (dot_radius - bar_height // 2),
                    dot_x + dot_radius,
                    bar_y + bar_height + (dot_radius - bar_height // 2),
                ),
                fill=(255, 255, 255),
            )

            # Time labels
            draw.text(
                (bar_x, bar_y + 20),
                "0:00",
                font=self.font_small,
                fill=(200, 200, 200),
            )

            duration_text = song.duration or "0:00"
            dur_width = self.font_small.getlength(duration_text)
            draw.text(
                (bar_x + bar_width - dur_width, bar_y + 20),
                duration_text,
                font=self.font_small,
                fill=(200, 200, 200),
            )

            # ─── Dynamic theme accent border at top and bottom ───
            draw.rectangle(
                (0, 0, self.width, 5),
                fill=(theme_color[0], theme_color[1], theme_color[2], 200),
            )
            draw.rectangle(
                (0, self.height - 5, self.width, self.height),
                fill=(theme_color[0], theme_color[1], theme_color[2], 200),
            )

            bg = bg.convert("RGB")

            bg.save(
                output,
                quality=95,
            )

            try:
                os.remove(temp)
            except Exception:
                pass

            return output

        except Exception as e:
            import traceback
            print(f"[Thumbnail Error] {e}")
            traceback.print_exc()
            return config.DEFAULT_THUMB
