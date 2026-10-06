import copy

from bot.diff import compare
from bot.formatter import format_diff


def lessons(data, week, day):
    return next(d for d in data["weeks"][week] if d["day"] == day)["lessons"]


def test_no_changes(schedule):
    d = compare(schedule, schedule)
    assert d.empty
    assert format_diff(d, None) == ["✅ Изменений нет"]


def test_added(schedule):
    new = copy.deepcopy(schedule)
    lessons(new, "1", "monday").append({
        "start": "15:10", "end": "16:40", "subject": "НОВЫЙ ПРЕДМЕТ", "type": "Лекция",
        "teacher": None, "place": None, "subgroup": None,
    })
    d = compare(schedule, new)
    assert [r.lesson["subject"] for r in d.added] == ["НОВЫЙ ПРЕДМЕТ"]
    assert not d.removed and not d.changed
    text = "\n".join(format_diff(d, None))
    assert "Добавлено (1)" in text and "Новый предмет" in text and "1 нед., Понедельник" in text


def test_removed(schedule):
    new = copy.deepcopy(schedule)
    removed = lessons(new, "2", "saturday").pop()  # 20:10 Введение в проф. деятельность
    d = compare(schedule, new)
    assert len(d.removed) == 1 and d.removed[0].lesson == removed
    assert d.removed[0].week == "2" and d.removed[0].day == "saturday"
    assert not d.added and not d.changed
    assert "Удалено (1)" in "\n".join(format_diff(d, None))


def test_room_changed(schedule):
    new = copy.deepcopy(schedule)
    lesson = lessons(new, "2", "monday")[0]
    lesson["place"]["room"] = "915"
    lesson["place"]["raw"] = 'корп. "Л" каб. "915"'
    d = compare(schedule, new)
    assert not d.added and not d.removed
    assert len(d.changed) == 1
    ch = d.changed[0]
    assert (ch.week, ch.day) == ("2", "monday")
    assert ch.fields == [("аудитория", "корп. Л, каб. 913", "корп. Л, каб. 915")]
    text = "\n".join(format_diff(d, None))
    assert "Изменения в расписании" in text
    assert "аудитория: корп. Л, каб. 913 → <b>корп. Л, каб. 915</b>" in text


def test_subgroup_changed_is_change(schedule):
    new = copy.deepcopy(schedule)
    lessons(new, "2", "tuesday")[2]["subgroup"] = 1
    d = compare(schedule, new)
    assert not d.added and not d.removed
    assert d.changed[0].fields[0] == ("подгруппа", "2 подгр.", "1 подгр.")


def test_teacher_end_type_changed(schedule):
    new = copy.deepcopy(schedule)
    lesson = lessons(new, "1", "friday")[0]
    lesson["end"] = "09:20"
    lesson["type"] = "Практика"
    lesson["teacher"] = None
    d = compare(schedule, new)
    titles = [f[0] for f in d.changed[0].fields]
    assert titles == ["окончание", "тип", "преподаватель"]
    assert d.changed[0].fields[2] == ("преподаватель", "Беляева О. В.", "—")


def test_other_subgroup_marked(schedule):
    new = copy.deepcopy(schedule)
    lessons(new, "2", "tuesday").pop(0)  # 2 подгруппа
    text = "\n".join(format_diff(compare(schedule, new), subgroup=1))
    assert "не ваша подгруппа" in text
    text = "\n".join(format_diff(compare(schedule, new), subgroup=2))
    assert "не ваша подгруппа" not in text


def test_from_nothing(schedule):
    d = compare(None, schedule)
    assert len(d.added) == 33
    assert not d.removed


def test_anchor_equivalent_shift_is_not_change(schedule):
    new = copy.deepcopy(schedule)
    new["week_anchor"] = {"monday": "2026-10-12", "week": 1}
    assert compare(schedule, new).empty
    new["week_anchor"] = {"monday": "2026-10-12", "week": 2}
    assert compare(schedule, new).anchor_changed
