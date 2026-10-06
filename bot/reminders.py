"""Напоминания после пары: какая следующая, где и с кем.

Напоминание приходит через reminder_offset_min минут после конца пары
(но не позже начала следующей). После последней пары дня — «на сегодня всё»
и первая пара завтра, если она есть.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from . import formatter
from .formatter import day_lessons, esc, subject_case
from .diff import place_text, teacher_text
from .weeks import DAYS, week_number_for

# если бот был выключен/завис, напоминание ещё отправится в течение этого окна
GRACE = timedelta(minutes=10)


@dataclass(frozen=True)
class Reminder:
    key: str
    at: datetime
    text: str


def _at(d: date, hhmm: str, tz: ZoneInfo) -> datetime:
    h, m = map(int, hhmm.split(":"))
    return datetime.combine(d, time(h, m), tzinfo=tz)


def lessons_on(data: dict, d: date, subgroup: int | None) -> list[dict]:
    return day_lessons(data, week_number_for(data, d), DAYS[d.weekday()], subgroup)


def _minutes(delta: timedelta) -> int:
    return max(0, round(delta.total_seconds() / 60))


def format_next(lessons: list[dict], minutes_left: int) -> str:
    start = lessons[0]["start"]
    if minutes_left <= 0:
        head = f"🔔 <b>Следующая пара начинается сейчас</b> ({esc(start)})"
    else:
        head = f"🔔 <b>Следующая пара в {esc(start)}</b> — через {minutes_left} мин"
    rows = [head]
    for lesson in lessons:
        rows.append(formatter.format_lesson(lesson))
        address = (lesson.get("place") or {}).get("address")
        if address:
            rows.append(f"🏢 {esc(address)}")
    return "\n".join(rows)


def format_day_over(tomorrow: date, first: list[dict]) -> str:
    text = "✅ <b>Пары на сегодня закончились.</b>"
    if first:
        lesson = first[0]
        parts = [f"<b>{esc(lesson['start'])}</b> {esc(subject_case(lesson['subject']))}"]
        if lesson.get("place"):
            parts.append(f"📍 {esc(place_text(lesson['place']))}")
        if lesson.get("teacher") and lesson["teacher"].get("name"):
            parts.append(f"👤 {esc(teacher_text(lesson['teacher']))}")
        text += f"\nЗавтра ({formatter.fmt_date(tomorrow)}) первая пара: " + " · ".join(parts)
    else:
        text += f"\nЗавтра ({formatter.fmt_date(tomorrow)}) пар нет 🎉"
    return text


def plan(data: dict, d: date, offset_min: int, subgroup: int | None, tz: ZoneInfo) -> list[Reminder]:
    """Все напоминания на день d."""
    lessons = lessons_on(data, d, subgroup)
    offset = timedelta(minutes=offset_min)
    result = []
    for end in sorted({l["end"] for l in lessons}):
        ended = _at(d, end, tz)
        later = [l for l in lessons if l["start"] >= end]
        if later:
            next_start = min(l["start"] for l in later)
            starts = _at(d, next_start, tz)
            at = min(ended + offset, starts)
            text = format_next([l for l in later if l["start"] == next_start], _minutes(starts - at))
        elif any(l["end"] > end for l in lessons):
            continue  # параллельная пара другой подгруппы ещё идёт
        else:
            at = ended + offset
            tomorrow = d + timedelta(days=1)
            text = format_day_over(tomorrow, lessons_on(data, tomorrow, subgroup))
        result.append(Reminder(f"{d.isoformat()} {end}", at, text))
    return result


def due(reminders: list[Reminder], now: datetime, sent: set[str]) -> list[Reminder]:
    return [r for r in reminders if r.key not in sent and r.at <= now < r.at + GRACE]
