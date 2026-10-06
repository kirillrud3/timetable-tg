"""Номер недели по дате, даты дней недели, пересчёт week_anchor."""

from __future__ import annotations

from datetime import date, timedelta

DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

DAY_RU = {
    "monday": "Понедельник",
    "tuesday": "Вторник",
    "wednesday": "Среда",
    "thursday": "Четверг",
    "friday": "Пятница",
    "saturday": "Суббота",
    "sunday": "Воскресенье",
}


def monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def other_week(week: int) -> int:
    return 2 if week == 1 else 1


def anchor_of(data: dict) -> tuple[date, int]:
    anchor = data["week_anchor"]
    return date.fromisoformat(anchor["monday"]), int(anchor["week"])


def week_number(d: date, anchor_monday: date, anchor_week: int) -> int:
    """Номер недели (1 или 2) для даты d.

    Чётное число недель от понедельника-якоря — тот же номер, нечётное — другой.
    Работает и для дат раньше якоря.
    """
    weeks_between = (monday_of(d) - monday_of(anchor_monday)).days // 7
    return anchor_week if weeks_between % 2 == 0 else other_week(anchor_week)


def week_number_for(data: dict, d: date) -> int:
    return week_number(d, *anchor_of(data))


def day_date(monday: date, day: str) -> date:
    return monday + timedelta(days=DAYS.index(day))


def week_dates(monday: date) -> dict[str, date]:
    return {day: day_date(monday, day) for day in DAYS}


def day_name(d: date) -> str:
    return DAYS[d.weekday()]


def make_anchor(today: date, current_week: int) -> dict:
    """week_anchor для /setweek: «сейчас идёт неделя current_week»."""
    if current_week not in (1, 2):
        raise ValueError("Номер недели должен быть 1 или 2")
    return {"monday": monday_of(today).isoformat(), "week": current_week}


def apply_setweek(data: dict, today: date, current_week: int) -> dict:
    """Возвращает копию data с пересчитанным week_anchor (comment сохраняется)."""
    new = dict(data)
    anchor = dict(data.get("week_anchor") or {})
    anchor.update(make_anchor(today, current_week))
    new["week_anchor"] = anchor
    return new
