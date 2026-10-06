import copy
from datetime import date

from bot.formatter import (
    format_date,
    format_info,
    format_lesson,
    format_week,
    split_messages,
    subject_case,
)


def test_subject_case():
    assert subject_case("ЛИНЕЙНАЯ АЛГЕБРА И АНАЛИТИЧЕСКАЯ ГЕОМЕТРИЯ") == "Линейная алгебра и аналитическая геометрия"
    assert subject_case("") == ""


def test_lesson_line(schedule):
    lesson = schedule["weeks"]["2"][0]["lessons"][0]
    assert format_lesson(lesson) == (
        "<b>08:00–09:30</b> Линейная алгебра и аналитическая геометрия (Лекция)\n"
        "📍 корп. Л, каб. 913 · 👤 Мыльников А. Л."
    )


def test_subgroup_suffix(schedule):
    lesson = schedule["weeks"]["2"][1]["lessons"][2]
    assert "(Лабораторная работа) · 2 подгр." in format_lesson(lesson)


def test_escaping_and_nulls():
    lesson = {
        "start": "08:00", "end": "09:30", "subject": "A<B & C", "type": "<i>x</i>",
        "teacher": None, "place": None, "subgroup": None,
    }
    assert format_lesson(lesson) == "<b>08:00–09:30</b> A&lt;b &amp; c (&lt;i&gt;x&lt;/i&gt;)"
    lesson["place"] = {"raw": "Онлайн", "building": None, "room": None}
    lesson["teacher"] = {"name": "Иванов & Ко"}
    assert format_lesson(lesson).endswith("📍 Онлайн · 👤 Иванов &amp; Ко")


def test_day_header(schedule):
    text = format_date(schedule, date(2026, 10, 12), None)
    assert text.startswith("📅 <b>Понедельник, 12.10</b> · 1 неделя\n<b>11:30–13:00</b> Иностранный язык")


def test_no_lessons(schedule):
    assert format_date(schedule, date(2026, 10, 13), None) is None  # вторник 1-й недели
    assert format_date(schedule, date(2026, 10, 11), None) is None  # воскресенье


def test_subgroup_filter(schedule):
    # понедельник 1-й недели — только 1 подгруппа
    assert format_date(schedule, date(2026, 10, 12), 2) is None
    assert format_date(schedule, date(2026, 10, 12), 1) is not None
    # вторник 2-й недели: у 1 подгруппы пар нет
    assert format_date(schedule, date(2026, 10, 6), 1) is None
    tue = format_date(schedule, date(2026, 10, 6), 2)
    assert tue.count("2 подгр.") == 3


def test_week(schedule):
    parts = format_week(schedule, date(2026, 10, 14), None)
    assert len(parts) == 1
    text = parts[0]
    assert text.startswith("🗓 <b>Расписание 12.10–17.10</b> · 1 неделя\n\n📅 <b>Понедельник, 12.10</b>")
    assert "Вторник" not in text  # дня без пар нет
    assert "\n\n📅 <b>Суббота, 17.10</b> · 1 неделя" in text
    assert "ОСНОВЫ" not in text and "Основы российской государственности" in text


def test_split_by_days():
    blocks = ["H"] + [("x" * 99 + "\n") * 15 for _ in range(10)]
    parts = split_messages(blocks, limit=4096)
    assert all(len(p) <= 4096 for p in parts)
    assert len(parts) > 1
    assert "\n\n".join(parts) == "\n\n".join(blocks)


def test_split_huge_block():
    block = "\n".join(["y" * 100] * 100)
    parts = split_messages([block], limit=1000)
    assert all(len(p) <= 1000 for p in parts)
    assert "\n".join(parts) == block


def test_info(schedule):
    text = format_info(schedule, date(2026, 10, 6), 2, None, None)
    assert "<b>2 неделя</b>" in text
    assert "05.10–11.10" in text
    assert "Пар в JSON: 33" in text
    assert "2026-10-06" in text


def test_null_subgroup_shown_for_any(schedule):
    data = copy.deepcopy(schedule)
    assert format_date(data, date(2026, 10, 7), 1).count("подгр.") == 0  # среда 2 нед., вся группа
