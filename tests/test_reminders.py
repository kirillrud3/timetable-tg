import json
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from bot.reminders import due, plan
from bot.settings import Settings, SettingsStore

TZ = ZoneInfo("Asia/Krasnoyarsk")
WED = date(2026, 10, 7)  # среда, 2-я неделя: 11:30, 13:30, 15:10, 16:50


def at(d, hhmm):
    h, m = map(int, hhmm.split(":"))
    return datetime(d.year, d.month, d.day, h, m, tzinfo=TZ)


def test_plan_default_offset(schedule):
    rs = plan(schedule, WED, 1, None, TZ)
    assert [r.at for r in rs] == [at(WED, "13:01"), at(WED, "15:01"), at(WED, "16:41"), at(WED, "18:21")]
    first = rs[0].text
    assert first.startswith("🔔 <b>Следующая пара в 13:30</b> — через 29 мин")
    assert "Математический анализ (Практика)" in first
    assert "📍 корп. Н, каб. 304 · 👤 Вишневская С. Р." in first
    assert "🏢 пр. им. газеты Красноярский рабочий, 31, стр. 5" in first


def test_last_lesson_shows_tomorrow(schedule):
    last = plan(schedule, WED, 1, None, TZ)[-1].text
    assert "Пары на сегодня закончились" in last
    assert "Завтра (08.10) первая пара: <b>11:30</b> Иностранный язык" in last


def test_offset_clamped_to_next_start(schedule):
    # перерыв 15:00→15:10, напоминание через 30 мин сдвигается к началу пары
    rs = plan(schedule, WED, 30, None, TZ)
    assert rs[1].at == at(WED, "15:10")
    assert "начинается сейчас" in rs[1].text
    assert rs[0].at == at(WED, "13:30")


def test_subgroup_filter(schedule):
    # вторник 2-й недели — пары только у 2 подгруппы
    tue = date(2026, 10, 6)
    assert plan(schedule, tue, 1, 1, TZ) == []
    assert len(plan(schedule, tue, 1, 2, TZ)) == 3


def test_no_lessons(schedule):
    assert plan(schedule, date(2026, 10, 11), 1, None, TZ) == []  # воскресенье


def test_due_once_and_grace(schedule):
    rs = plan(schedule, WED, 1, None, TZ)
    sent = set()
    assert due(rs, at(WED, "13:00"), sent) == []
    hit = due(rs, at(WED, "13:01"), sent)
    assert [r.key for r in hit] == ["2026-10-07 13:00"]
    sent.update(r.key for r in hit)
    assert due(rs, at(WED, "13:02"), sent) == []
    # бот лежал, но поднялся в пределах 10 минут — напоминание всё равно придёт
    assert len(due(rs, at(WED, "15:09"), set())) == 1
    assert due(rs, at(WED, "15:12"), set()) == []


def test_settings_store(tmp_path):
    path = tmp_path / "settings.json"
    store = SettingsStore(path)
    assert store.settings == Settings(reminders_enabled=True, reminder_offset_min=1)
    store.update(reminder_offset_min=5)
    assert json.loads(path.read_text())["reminder_offset_min"] == 5
    assert SettingsStore(path).settings.reminder_offset_min == 5
    path.write_text("{broken")
    assert SettingsStore(path).settings.reminder_offset_min == 1
