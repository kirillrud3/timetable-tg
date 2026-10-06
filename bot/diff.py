"""Сравнение двух версий расписания.

Ключ занятия: (неделя, день, время начала, предмет, подгруппа).
Если пара пропала и тут же появилась с тем же ключом, но другой подгруппой,
это считается изменением подгруппы, а не удалением + добавлением.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .weeks import DAYS, week_number

Key = tuple[str, str, str, str, int | None]

# поле → человекочитаемое название
COMPARED_FIELDS = {
    "end": "окончание",
    "type": "тип",
    "place": "аудитория",
    "teacher": "преподаватель",
}


@dataclass
class LessonRef:
    week: str
    day: str
    lesson: dict

    @property
    def key(self) -> Key:
        return lesson_key(self.week, self.day, self.lesson)


@dataclass
class Change:
    week: str
    day: str
    old: dict
    new: dict
    fields: list[tuple[str, str, str]]  # (название поля, было, стало)


@dataclass
class ScheduleDiff:
    added: list[LessonRef] = field(default_factory=list)
    removed: list[LessonRef] = field(default_factory=list)
    changed: list[Change] = field(default_factory=list)
    anchor_changed: tuple[dict, dict] | None = None

    @property
    def empty(self) -> bool:
        return not (self.added or self.removed or self.changed or self.anchor_changed)


def lesson_key(week: str, day: str, lesson: dict) -> Key:
    return (week, day, lesson.get("start", ""), lesson.get("subject", ""), lesson.get("subgroup"))


def place_text(place: dict | None) -> str:
    if not place:
        return "—"
    building, room = place.get("building"), place.get("room")
    if building and room:
        return f"корп. {building}, каб. {room}"
    if room:
        return f"каб. {room}"
    return place.get("raw") or "—"


def teacher_text(teacher: dict | None) -> str:
    if not teacher:
        return "—"
    return teacher.get("name") or "—"


def _field_text(name: str, lesson: dict) -> str:
    value = lesson.get(name)
    if name == "place":
        return place_text(value)
    if name == "teacher":
        return teacher_text(value)
    if name == "subgroup":
        return "вся группа" if value is None else f"{value} подгр."
    return "—" if value in (None, "") else str(value)


def _field_value(name: str, lesson: dict) -> object:
    value = lesson.get(name)
    if name == "place" and value:
        # адрес/raw могут переформатироваться — сравниваем по смыслу
        return (value.get("building"), value.get("room"), value.get("address"), value.get("raw"))
    if name == "teacher" and value:
        return (value.get("name"), value.get("id"))
    return value


def _sort_key(item: LessonRef | Change) -> tuple:
    lesson = item.lesson if isinstance(item, LessonRef) else item.new
    return (item.week, DAYS.index(item.day), lesson.get("start", ""), lesson.get("subject", ""))


def _index(data: dict | None) -> dict[Key, LessonRef]:
    result: dict[Key, LessonRef] = {}
    if not data:
        return result
    for week, days in data.get("weeks", {}).items():
        for day in days:
            for lesson in day.get("lessons", []):
                ref = LessonRef(week, day["day"], lesson)
                result[ref.key] = ref
    return result


def compare(old: dict | None, new: dict) -> ScheduleDiff:
    old_idx, new_idx = _index(old), _index(new)
    diff = ScheduleDiff()

    for key in old_idx.keys() & new_idx.keys():
        o, n = old_idx[key].lesson, new_idx[key].lesson
        fields = [
            (title, _field_text(name, o), _field_text(name, n))
            for name, title in COMPARED_FIELDS.items()
            if _field_value(name, o) != _field_value(name, n)
        ]
        if fields:
            diff.changed.append(Change(key[0], key[1], o, n, fields))

    removed = [old_idx[k] for k in old_idx.keys() - new_idx.keys()]
    added = [new_idx[k] for k in new_idx.keys() - old_idx.keys()]

    # пара та же, поменялась только подгруппа → изменение
    for r in list(removed):
        match = next(
            (a for a in added if a.key[:4] == r.key[:4] and a.key[4] != r.key[4]),
            None,
        )
        if match is None:
            continue
        removed.remove(r)
        added.remove(match)
        fields = [("подгруппа", _field_text("subgroup", r.lesson), _field_text("subgroup", match.lesson))]
        fields += [
            (title, _field_text(name, r.lesson), _field_text(name, match.lesson))
            for name, title in COMPARED_FIELDS.items()
            if _field_value(name, r.lesson) != _field_value(name, match.lesson)
        ]
        diff.changed.append(Change(r.week, r.day, r.lesson, match.lesson, fields))

    diff.added = sorted(added, key=_sort_key)
    diff.removed = sorted(removed, key=_sort_key)
    diff.changed.sort(key=_sort_key)

    if old and old.get("week_anchor") and new.get("week_anchor"):
        oa, na = old["week_anchor"], new["week_anchor"]
        # якоря эквивалентны, если дают одинаковое чередование
        same = week_number(
            date.fromisoformat(na["monday"]), date.fromisoformat(oa["monday"]), int(oa["week"])
        ) == int(na["week"])
        if not same:
            diff.anchor_changed = (oa, na)
    return diff
