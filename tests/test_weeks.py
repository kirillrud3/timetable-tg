from datetime import date, timedelta

import pytest

from bot.weeks import (
    apply_setweek,
    day_date,
    make_anchor,
    monday_of,
    week_dates,
    week_number,
    week_number_for,
)

ANCHOR = date(2026, 10, 5)


@pytest.mark.parametrize("offset", range(7))
def test_anchor_week_is_2(offset):
    assert week_number(ANCHOR + timedelta(days=offset), ANCHOR, 2) == 2


@pytest.mark.parametrize(
    "d, expected",
    [
        (date(2026, 10, 11), 2),
        (date(2026, 10, 12), 1),
        (date(2026, 10, 17), 1),
        (date(2026, 10, 18), 1),
        (date(2026, 10, 19), 2),
        (date(2026, 9, 28), 1),   # до якоря
        (date(2026, 9, 21), 2),
    ],
)
def test_alternation(d, expected):
    assert week_number(d, ANCHOR, 2) == expected


def test_from_json(schedule):
    assert week_number_for(schedule, date(2026, 10, 6)) == 2
    assert week_number_for(schedule, date(2026, 10, 12)) == 1
    assert week_number_for(schedule, date(2026, 10, 19)) == 2


def test_dates():
    assert monday_of(date(2026, 10, 11)) == ANCHOR
    assert day_date(date(2026, 10, 12), "saturday") == date(2026, 10, 17)
    dates = week_dates(ANCHOR)
    assert dates["monday"] == ANCHOR and dates["sunday"] == date(2026, 10, 11)


def test_setweek(schedule):
    today = date(2026, 10, 14)  # среда 1-й недели
    assert make_anchor(today, 2) == {"monday": "2026-10-12", "week": 2}
    new = apply_setweek(schedule, today, 2)
    assert new["week_anchor"]["monday"] == "2026-10-12"
    assert new["week_anchor"]["week"] == 2
    assert new["week_anchor"]["comment"] == schedule["week_anchor"]["comment"]
    assert week_number_for(new, today) == 2
    assert week_number_for(new, date(2026, 10, 19)) == 1
    assert schedule["week_anchor"]["monday"] == "2026-10-05"  # оригинал не тронут


def test_setweek_bad_value():
    with pytest.raises(ValueError):
        make_anchor(date(2026, 10, 6), 3)
