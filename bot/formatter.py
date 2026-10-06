"""Оформление сообщений (parse_mode=HTML, все данные из JSON экранируются)."""

from __future__ import annotations

from datetime import date, timedelta
from html import escape

from .diff import Change, ScheduleDiff, place_text, teacher_text
from .schedule import count_lessons
from .weeks import DAY_RU, DAYS, monday_of, week_dates, week_number_for

TG_LIMIT = 4096


def esc(value: object) -> str:
    return escape(str(value), quote=False)


def subject_case(subject: str) -> str:
    """«ЛИНЕЙНАЯ АЛГЕБРА» → «Линейная алгебра»."""
    s = " ".join(subject.split()).lower()
    return s[:1].upper() + s[1:]


def fmt_date(d: date) -> str:
    return d.strftime("%d.%m")


def visible(lesson: dict, subgroup: int | None) -> bool:
    return subgroup is None or lesson.get("subgroup") in (None, subgroup)


def day_lessons(data: dict, week: int, day: str, subgroup: int | None) -> list[dict]:
    for entry in data["weeks"].get(str(week), []):
        if entry["day"] == day:
            lessons = [l for l in entry["lessons"] if visible(l, subgroup)]
            return sorted(lessons, key=lambda l: l["start"])
    return []


def format_lesson(lesson: dict) -> str:
    title = f"<b>{esc(lesson['start'])}–{esc(lesson['end'])}</b> {esc(subject_case(lesson['subject']))}"
    if lesson.get("type"):
        title += f" ({esc(lesson['type'])})"
    if lesson.get("subgroup") is not None:
        title += f" · {esc(lesson['subgroup'])} подгр."

    details = []
    if lesson.get("place"):
        details.append(f"📍 {esc(place_text(lesson['place']))}")
    if lesson.get("teacher") and lesson["teacher"].get("name"):
        details.append(f"👤 {esc(teacher_text(lesson['teacher']))}")
    if details:
        return f"{title}\n{' · '.join(details)}"
    return title


def format_day(day: str, d: date, week: int, lessons: list[dict]) -> str:
    header = f"📅 <b>{DAY_RU[day]}, {fmt_date(d)}</b> · {week} неделя"
    return "\n".join([header, *(format_lesson(l) for l in lessons)])


def format_date(data: dict, d: date, subgroup: int | None) -> str | None:
    """Пары на конкретную дату или None, если пар нет."""
    week = week_number_for(data, d)
    day = DAYS[d.weekday()]
    lessons = day_lessons(data, week, day, subgroup)
    if not lessons:
        return None
    return format_day(day, d, week, lessons)


def week_blocks(data: dict, any_date: date, subgroup: int | None) -> list[str]:
    """Заголовок + по блоку на каждый день с парами."""
    monday = monday_of(any_date)
    week = week_number_for(data, monday)
    dates = week_dates(monday)
    days = []
    for day in DAYS:
        lessons = day_lessons(data, week, day, subgroup)
        if lessons:
            days.append(format_day(day, dates[day], week, lessons))
    last = dates["sunday"] if day_lessons(data, week, "sunday", subgroup) else dates["saturday"]
    header = f"🗓 <b>Расписание {fmt_date(monday)}–{fmt_date(last)}</b> · {week} неделя"
    if subgroup is not None:
        header += f" · {subgroup} подгр."
    if not days:
        return [header + "\n\nПар нет 🎉"]
    return [header, *days]


def split_messages(blocks: list[str], limit: int = TG_LIMIT, sep: str = "\n\n") -> list[str]:
    """Склеивает блоки через sep так, чтобы каждое сообщение было не длиннее limit.

    Блок длиннее лимита режется по строкам.
    """
    pieces: list[str] = []
    for block in blocks:
        if len(block) <= limit:
            pieces.append(block)
            continue
        current = ""
        for line in block.split("\n"):
            while len(line) > limit:
                if current:
                    pieces.append(current)
                    current = ""
                pieces.append(line[:limit])
                line = line[limit:]
            candidate = f"{current}\n{line}" if current else line
            if len(candidate) > limit:
                pieces.append(current)
                current = line
            else:
                current = candidate
        if current:
            pieces.append(current)

    messages: list[str] = []
    current = ""
    for piece in pieces:
        candidate = f"{current}{sep}{piece}" if current else piece
        if len(candidate) > limit:
            messages.append(current)
            current = piece
        else:
            current = candidate
    if current:
        messages.append(current)
    return messages


def format_week(data: dict, any_date: date, subgroup: int | None) -> list[str]:
    return split_messages(week_blocks(data, any_date, subgroup))


# --------------------------------------------------------------------------- /info, /start


HELP = (
    "👋 Я присылаю расписание группы <b>{group}</b>.\n\n"
    "Каждый день в 07:00 — пары на сегодня, по воскресеньям в 18:00 — расписание "
    "на следующую неделю.\n\n"
    "<b>Команды</b>\n"
    "/today — пары на сегодня\n"
    "/tomorrow — пары на завтра\n"
    "/week — текущая неделя\n"
    "/next — следующая неделя\n"
    "/info — номер недели и сведения о расписании\n"
    "/json — прислать текущий schedule.json\n"
    "/setweek 1|2 — указать, какая неделя идёт сейчас\n\n"
    "Чтобы обновить расписание, пришлите мне .json файлом: я покажу изменения "
    "и спрошу подтверждение."
)


def format_help(data: dict | None) -> str:
    group = data.get("group", "—") if data else "—"
    return HELP.format(group=esc(group))


def format_info(
    data: dict, today: date, subgroup: int | None, file_mtime: str | None, error: str | None
) -> str:
    monday = monday_of(today)
    week = week_number_for(data, today)
    anchor = data["week_anchor"]
    per_week = {
        wk: sum(len(d["lessons"]) for d in data["weeks"][wk]) for wk in ("1", "2")
    }
    lines = [
        f"ℹ️ <b>{esc(data.get('group', '—'))}</b>",
        f"Сегодня {fmt_date(today)}, {DAY_RU[DAYS[today.weekday()]].lower()} — <b>{week} неделя</b>",
        f"Текущая неделя: {fmt_date(monday)}–{fmt_date(monday + timedelta(days=6))}",
        f"Следующая: {fmt_date(monday + timedelta(days=7))}–{fmt_date(monday + timedelta(days=13))}"
        f" · {2 if week == 1 else 1} неделя",
        "",
        f"Обновлено (updated_at): {esc(data.get('updated_at', '—'))}",
    ]
    if file_mtime:
        lines.append(f"Файл изменён: {esc(file_mtime)}")
    lines += [
        f"Пар в JSON: {count_lessons(data)} (1 нед. — {per_week['1']}, 2 нед. — {per_week['2']})",
    ]
    if subgroup is not None:
        lines.append(f"Подгруппа: {subgroup}, ваших пар: {count_lessons(data, subgroup)}")
    else:
        lines.append("Подгруппа: не задана, показываю все пары")
    lines.append(f"Якорь: {esc(anchor['monday'])} — {esc(anchor['week'])} неделя")
    if error:
        lines += ["", f"⚠️ Последняя ошибка файла:\n{esc(error)}"]
    return "\n".join(lines)


# --------------------------------------------------------------------------- сводка изменений


def _lesson_line(week: str, day: str, lesson: dict, subgroup: int | None) -> str:
    parts = [
        f"{esc(week)} нед., {DAY_RU[day]}, <b>{esc(lesson.get('start', ''))}–{esc(lesson.get('end', ''))}</b>",
        esc(subject_case(lesson.get("subject", ""))),
    ]
    line = " ".join(parts)
    if lesson.get("type"):
        line += f" ({esc(lesson['type'])})"
    if lesson.get("subgroup") is not None:
        line += f" · {esc(lesson['subgroup'])} подгр."
    extra = []
    if lesson.get("place"):
        extra.append(f"📍 {esc(place_text(lesson['place']))}")
    if lesson.get("teacher"):
        extra.append(f"👤 {esc(teacher_text(lesson['teacher']))}")
    if extra:
        line += "\n   " + " · ".join(extra)
    if not visible(lesson, subgroup):
        line += "\n   <i>(не ваша подгруппа)</i>"
    return f"• {line}"


def _change_line(change: Change, subgroup: int | None) -> str:
    lesson = change.new
    head = (
        f"• {esc(change.week)} нед., {DAY_RU[change.day]}, <b>{esc(lesson.get('start', ''))}</b> "
        f"{esc(subject_case(lesson.get('subject', '')))}"
    )
    if lesson.get("subgroup") is not None:
        head += f" · {esc(lesson['subgroup'])} подгр."
    rows = [head]
    for title, old, new in change.fields:
        rows.append(f"   {esc(title)}: {esc(old)} → <b>{esc(new)}</b>")
    if not visible(change.old, subgroup) and not visible(change.new, subgroup):
        rows.append("   <i>(не ваша подгруппа)</i>")
    return "\n".join(rows)


def diff_blocks(diff: ScheduleDiff, subgroup: int | None) -> list[str]:
    if diff.empty:
        return ["✅ Изменений нет"]
    blocks = ["⚠️ <b>Изменения в расписании</b>"]
    if diff.added:
        blocks.append(
            f"➕ <b>Добавлено ({len(diff.added)}):</b>\n"
            + "\n".join(_lesson_line(r.week, r.day, r.lesson, subgroup) for r in diff.added)
        )
    if diff.removed:
        blocks.append(
            f"➖ <b>Удалено ({len(diff.removed)}):</b>\n"
            + "\n".join(_lesson_line(r.week, r.day, r.lesson, subgroup) for r in diff.removed)
        )
    if diff.changed:
        blocks.append(
            f"✏️ <b>Изменено ({len(diff.changed)}):</b>\n"
            + "\n".join(_change_line(c, subgroup) for c in diff.changed)
        )
    if diff.anchor_changed:
        old, new = diff.anchor_changed
        blocks.append(
            "🔁 <b>Чередование недель:</b> "
            f"{esc(old.get('monday'))} — {esc(old.get('week'))} нед. → "
            f"<b>{esc(new.get('monday'))} — {esc(new.get('week'))} нед.</b>"
        )
    return blocks


def format_diff(diff: ScheduleDiff, subgroup: int | None) -> list[str]:
    return split_messages(diff_blocks(diff, subgroup))

