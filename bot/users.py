"""User registry with an in-memory cache over storage.

Both the Telegram handlers (auto-registration, /settings) and the event
fan-out in main.py go through this service, so a settings change is visible
to the notification pipeline immediately.
"""
from __future__ import annotations

from typing import Any, Optional

import config
from bot.i18n import norm_lang
from database.storage import Storage, User


class UserService:
    def __init__(self, storage: Storage):
        self.storage = storage
        self._cache: dict[int, User] = {}

    async def ensure(self, chat_id: int,
                     tg_lang_code: str | None = None) -> User:
        """Return the user, creating them on first contact."""
        user = self._cache.get(chat_id)
        if user:
            return user
        user = await self.storage.get_user(chat_id)
        if not user:
            user = await self.storage.upsert_user(
                chat_id,
                lang=norm_lang(tg_lang_code),
                min_position_usd=config.DEFAULT_MIN_POSITION_USD,
                fill_agg_threshold=config.DEFAULT_FILL_AGG_THRESHOLD,
            )
        self._cache[chat_id] = user
        return user

    async def get(self, chat_id: int) -> Optional[User]:
        user = self._cache.get(chat_id)
        if user:
            return user
        user = await self.storage.get_user(chat_id)
        if user:
            self._cache[chat_id] = user
        return user

    async def set_setting(self, chat_id: int, field: str, value: Any) -> None:
        await self.storage.update_user_setting(chat_id, field, value)
        user = await self.storage.get_user(chat_id)
        if user:
            self._cache[chat_id] = user
