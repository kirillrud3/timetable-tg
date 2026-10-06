import json
import os

import pytest

from bot.schedule import ScheduleError, ScheduleStore, parse, validate


def test_real_file_valid(schedule):
    assert validate(schedule) == []


def test_errors(schedule):
    schedule["weeks"]["2"][0]["lessons"][0]["start"] = "8:00"
    del schedule["weeks"]["1"][0]["lessons"][0]["subject"]
    del schedule["weeks"]["2"][1]
    errors = validate(schedule)
    assert any("start='8:00'" in e and "HH:MM" in e for e in errors)
    assert any("нет subject" in e for e in errors)
    del schedule["weeks"]["1"]
    assert any('нет ключа "1"' in e for e in validate(schedule))


def test_not_json():
    with pytest.raises(ScheduleError) as e:
        parse(b"{oops")
    assert "не JSON" in e.value.human()


def test_store_reload_and_broken(tmp_path, schedule):
    path = tmp_path / "schedule.json"
    path.write_text(json.dumps(schedule, ensure_ascii=False), encoding="utf-8")
    store = ScheduleStore(path)
    assert store.refresh() is None and store.data["group"] == "БСЦ26-01"

    schedule["group"] = "ТЕСТ"
    path.write_text(json.dumps(schedule, ensure_ascii=False), encoding="utf-8")
    os.utime(path, ns=(1, 1))
    assert store.get()["group"] == "ТЕСТ"

    path.write_text("{broken", encoding="utf-8")
    err = store.refresh()
    assert err and "последней валидной" in err
    assert store.refresh() is None  # об одной поломке — одно сообщение
    assert store.data["group"] == "ТЕСТ"


def test_store_missing(tmp_path):
    store = ScheduleStore(tmp_path / "nope.json")
    assert "не найден" in store.refresh()
    assert store.data is None


def test_save_atomic_with_history(tmp_path, schedule):
    path = tmp_path / "schedule.json"
    path.write_text(json.dumps(schedule, ensure_ascii=False), encoding="utf-8")
    store = ScheduleStore(path)
    store.refresh()
    schedule["updated_at"] = "2026-10-07"
    backup = store.save(schedule)
    assert backup.parent == tmp_path / "history" and backup.name.startswith("schedule_")
    assert json.loads(backup.read_text(encoding="utf-8"))["updated_at"] == "2026-10-06"
    raw = path.read_text(encoding="utf-8")
    assert '"group": "БСЦ26-01"' in raw and raw.startswith('{\n  "group"')
    assert store.refresh() is None
    assert [p.name for p in tmp_path.iterdir() if p.suffix == ".tmp"] == []
