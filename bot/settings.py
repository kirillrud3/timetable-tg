"""Пользовательские настройки, которые меняются командами (хранятся в data/settings.json)."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

from .schedule import atomic_write_json

log = logging.getLogger(__name__)

DEFAULT_REMINDER_OFFSET = 1
MAX_REMINDER_OFFSET = 180


@dataclass
class Settings:
    reminders_enabled: bool = True
    reminder_offset_min: int = DEFAULT_REMINDER_OFFSET


class SettingsStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.settings = self._load()

    def _load(self) -> Settings:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return Settings()
        except (OSError, ValueError) as e:
            log.error("Не удалось прочитать %s, беру настройки по умолчанию: %s", self.path, e)
            return Settings()
        s = Settings()
        if isinstance(raw.get("reminders_enabled"), bool):
            s.reminders_enabled = raw["reminders_enabled"]
        offset = raw.get("reminder_offset_min")
        if isinstance(offset, int) and not isinstance(offset, bool) and 0 <= offset <= MAX_REMINDER_OFFSET:
            s.reminder_offset_min = offset
        return s

    def update(self, **changes) -> Settings:
        for key, value in changes.items():
            setattr(self.settings, key, value)
        atomic_write_json(self.path, asdict(self.settings))
        return self.settings
