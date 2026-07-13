# Copyright (c) 2025 TheHamkerAlone
# Licensed under the MIT License.
# This file is part of AloneXMusic
# ALONE-CODER
# POWERED BY ALONE

from pyrogram import enums, types
from pyrogram.enums import ButtonStyle

from AloneX import app, config, db, lang
from AloneX.core.lang import lang_codes


class Inline:
    def __init__(self):
        self.ikm = types.InlineKeyboardMarkup
        self.ikb = types.InlineKeyboardButton

    def cancel_dl(self, text) -> types.InlineKeyboardMarkup:
        return self.ikm([[self.ikb(text=text, callback_data="cancel_dl")]])

    async def controls(
        self,
        chat_id: int,
        status: str = None,
        timer: str = None,
        remove: bool = False,
        _lang: dict = None,
        style_offset: int = 0,
    ) -> types.InlineKeyboardMarkup:
        keyboard = []
        styles = [
            ButtonStyle.SUCCESS,
            ButtonStyle.PRIMARY,
            ButtonStyle.DANGER,
        ]

        if status:
            keyboard.append(
                [self.ikb(text=status, callback_data=f"controls status {chat_id}")]
            )
        elif timer:
            btn_style_timer = styles[(style_offset + 1) % len(styles)]
            keyboard.append(
                [self.ikb(text=timer, callback_data=f"controls status {chat_id}", style=btn_style_timer)]
            )

        if not remove:
            btn_style_1 = styles[(style_offset) % len(styles)]
            btn_style_2 = styles[(style_offset + 1) % len(styles)]
            btn_style_3 = styles[(style_offset + 2) % len(styles)]
            btn_style_4 = styles[(style_offset + 1) % len(styles)]
            btn_style_5 = styles[(style_offset) % len(styles)]

            keyboard.append(
                [
                    self.ikb(text="▷", callback_data=f"controls resume {chat_id}", style=btn_style_1),
                    self.ikb(text="II", callback_data=f"controls pause {chat_id}", style=btn_style_2),
                    self.ikb(text="⥁", callback_data=f"controls replay {chat_id}", style=btn_style_3),
                    self.ikb(text="‣‣I", callback_data=f"controls skip {chat_id}", style=btn_style_4),
                    self.ikb(text="▢", callback_data=f"controls stop {chat_id}", style=btn_style_5),
                ]
            )
            if not _lang:
                _lang = lang.languages["en"]

            # AutoPlay toggle button — green (SUCCESS) when enabled, red
            # (DANGER) when disabled. Clickable: flips the per-chat setting.
            ap_on = await db.get_autoplay(chat_id)
            ap_text = "AutoPlay: ON" if ap_on else "AutoPlay: OFF"
            ap_style = ButtonStyle.SUCCESS if ap_on else ButtonStyle.DANGER
            keyboard.append(
                [
                    self.ikb(
                        text=ap_text,
                        callback_data=f"ap_toggle {chat_id}",
                        style=ap_style,
                    ),
                ]
            )

            btn_style_add = styles[(style_offset + 2) % len(styles)]
            keyboard.append(
                [
                    self.ikb(
                        text=_lang.get("add_me", "✙ 𝐀ᴅᴅ 𝐌є 𝐈η 𝐘συʀ 𝐆ʀσυᴘ ✙"),
                        url=f"https://t.me/{app.username}?startgroup=true",
                        style=btn_style_add,
                    ),
                ]
            )

            btn_style_channel = styles[(style_offset + 1) % len(styles)]
            btn_style_close = styles[(style_offset) % len(styles)]
            keyboard.append(
                [
                    self.ikb(
                        text=_lang.get("channel", "˹ 𝐔ᴘᴅᴧᴛєs ˼"),
                        url=config.SUPPORT_CHANNEL,
                        style=btn_style_channel,
                    ),
                    self.ikb(
                        text=_lang.get("close", "⌯ 𝐂ʟσsє ⌯"),
                        callback_data="help close",
                        style=btn_style_close,
                    ),
                ]
            )
        return self.ikm(keyboard)

    async def edit(self, query, text, reply_markup=None) -> None:
        """Edit the message that triggered the callback.

        The start message is sent as a *photo* (reply_photo in start.py), so its
        text lives in the caption. ``editMessageText`` only works on text
        messages and raises a BadRequest on a photo, which silently broke the
        Help / Language buttons on the start image. This picks
        edit_message_caption vs edit_message_text based on the message type.
        """
        if query.message and query.message.photo:
            return await query.edit_message_caption(
                caption=text, reply_markup=reply_markup
            )
        return await query.edit_message_text(text=text, reply_markup=reply_markup)

    def help_markup(
        self, _lang: dict, back: bool = False
    ) -> types.InlineKeyboardMarkup:
        if back:
            rows = [
                [
                    self.ikb(text=_lang["back"], callback_data="help back", style=ButtonStyle.PRIMARY),
                    self.ikb(text=_lang["close"], callback_data="help close", style=ButtonStyle.DANGER),
                ]
            ]
        else:
            # Map each callback to its (correct) label key. Using positional
            # f"help_{i}" was wrong: there are 10 categories but only help_0..help_8
            # labels exist (plus help_autoplay), so the 10th button raised
            # KeyError and crashed the callback. The callback handler itself
            # reads f"help_{cb}" for the body (help_admins, help_autoplay, ...),
            # so the label keys below must match those.
            label_map = {
                "admins": "help_0",
                "auth": "help_1",
                "blist": "help_2",
                "lang": "help_3",
                "ping": "help_4",
                "play": "help_5",
                "autoplay": "help_autoplay_lbl",
                "queue": "help_6",
                "stats": "help_7",
                "sudo": "help_8",
            }
            cbs = list(label_map.keys())
            buttons = [
                self.ikb(
                    text=_lang[label_map[cb]],
                    callback_data=f"help {cb}",
                    style=ButtonStyle.PRIMARY,
                )
                for cb in cbs
            ]
            rows = [buttons[i : i + 3] for i in range(0, len(buttons), 3)]
            rows.append(
                [
                    self.ikb(text=_lang["back"], callback_data="help_back_start", style=ButtonStyle.PRIMARY),
                    self.ikb(text=_lang["close"], callback_data="help close", style=ButtonStyle.DANGER),
                ]
            )

        return self.ikm(rows)

    def lang_markup(self, _lang: str) -> types.InlineKeyboardMarkup:
        langs = lang.get_languages()

        buttons = [
            self.ikb(
                text=f"{name} ({code}) {'✔️' if code == _lang else ''}",
                callback_data=f"lang_change {code}",
            )
            for code, name in langs.items()
        ]
        rows = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
        return self.ikm(rows)

    def ping_markup(self, text: str) -> types.InlineKeyboardMarkup:
        return self.ikm([[self.ikb(text=text, url=config.SUPPORT_CHAT)]])

    def play_queued(
        self, chat_id: int, item_id: str, _text: str
    ) -> types.InlineKeyboardMarkup:
        return self.ikm(
            [
                [
                    self.ikb(
                        text=_text,
                        callback_data=f"controls force {chat_id} {item_id}",
                        style=ButtonStyle.SUCCESS,
                    )
                ]
            ]
        )

    def queue_markup(
        self, chat_id: int, _text: str, playing: bool
    ) -> types.InlineKeyboardMarkup:
        _action = "pause" if playing else "resume"
        return self.ikm(
            [
                [
                    self.ikb(
                        text=_text,
                        callback_data=f"controls {_action} {chat_id} q",
                        style=ButtonStyle.SUCCESS,
                    )
                ]
            ]
        )

    def settings_markup(
        self, lang: dict, admin_only: bool, cmd_delete: bool, language: str, chat_id: int
    ) -> types.InlineKeyboardMarkup:
        return self.ikm(
            [
                [
                    self.ikb(
                        text=lang["play_mode"] + " ➜",
                        callback_data="settings",
                    ),
                    self.ikb(text=admin_only, callback_data="settings play"),
                ],
                [
                    self.ikb(
                        text=lang["cmd_delete"] + " ➜",
                        callback_data="settings",
                    ),
                    self.ikb(text=cmd_delete, callback_data="settings delete"),
                ],
                [
                    self.ikb(
                        text=lang["language"] + " ➜",
                        callback_data="settings",
                    ),
                    self.ikb(text=lang_codes[language], callback_data="language"),
                ],
            ]
        )

    def start_key(
        self, lang: dict, private: bool = False
    ) -> types.InlineKeyboardMarkup:
        rows = [
            [
                self.ikb(
                    text=lang["add_me"],
                    url=f"https://t.me/{app.username}?startgroup=true", style=ButtonStyle.PRIMARY
                )
            ],
            [self.ikb(text=lang["help"], callback_data="help", style=ButtonStyle.PRIMARY)],
            [
                self.ikb(text=lang["support"], url=config.SUPPORT_CHAT, style=ButtonStyle.SUCCESS),
                self.ikb(text=lang["channel"], url=config.SUPPORT_CHANNEL, style=ButtonStyle.SUCCESS),
            ],
        ]
        if private:
            rows += [
                [
                    self.ikb(text=lang["aloneowner"], url=f"tg://openmessage?user_id={config.OWNER_ID}", style=ButtonStyle.DANGER),
                    self.ikb(
                        text=lang["source"],
                        url="https://github.com/nishkarshk212/Shradha-X-Music", style=ButtonStyle.DANGER
                    )
                ]
            ]
        else:
            rows += [[self.ikb(text=lang["language"], callback_data="language")]]
        return self.ikm(rows)

    def yt_key(self, link: str) -> types.InlineKeyboardMarkup:
        return self.ikm(
            [
                [
                    self.ikb(text="❐", copy_text=link),
                    self.ikb(text="Youtube", url=link),
                ],
            ]
        )

    def suggest_markup(
        self, chat_id: int, items: list
    ) -> types.InlineKeyboardMarkup:
        """Per-result Play buttons for /suggest, styled blue (ButtonStyle.PRIMARY).

        `items` is a list of (title, video_id) tuples.
        """
        rows = [
            [
                self.ikb(
                    text=f"{i + 1}. {title[:40]}",
                    callback_data=f"suggest_play {chat_id} {vid}",
                    style=ButtonStyle.PRIMARY,
                )
            ]
            for i, (title, vid) in enumerate(items)
        ]
        return self.ikm(rows)
