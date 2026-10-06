"""Настройки из .env."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Config:
    bot_token: str
    admin_id: int
    subgroup: int | None
    tz: ZoneInfo
    schedule_path: Path

    @property
    def history_dir(self) -> Path:
        return self.schedule_path.parent / "history"


def parse_subgroup(value: str | None) -> int | None:
    value = (value or "").strip()
    if not value:
        return None
    if value not in ("1", "2"):
        raise ConfigError(f"SUBGROUP должен быть 1, 2 или пустым, получено: {value!r}")
    return int(value)


def load_config() -> Config:
    load_dotenv(PROJECT_ROOT / ".env")

    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise ConfigError("BOT_TOKEN не задан в .env")

    admin_raw = os.getenv("ADMIN_ID", "").strip()
    if not admin_raw.lstrip("-").isdigit():
        raise ConfigError("ADMIN_ID должен быть числом (свой ID можно узнать у @userinfobot)")

    tz_name = os.getenv("TZ", "Asia/Krasnoyarsk").strip() or "Asia/Krasnoyarsk"

    path = Path(os.getenv("SCHEDULE_PATH", "data/schedule.json").strip() or "data/schedule.json")
    if not path.is_absolute():
        path = PROJECT_ROOT / path

    return Config(
        bot_token=token,
        admin_id=int(admin_raw),
        subgroup=parse_subgroup(os.getenv("SUBGROUP")),
        tz=ZoneInfo(tz_name),
        schedule_path=path,
    )
