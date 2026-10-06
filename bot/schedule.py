"""Загрузка, валидация, автоперечитывание по mtime, атомарная запись, история версий."""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import tempfile
from datetime import date, datetime
from pathlib import Path

from .weeks import DAY_RU, DAYS

log = logging.getLogger(__name__)

TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
MAX_ERRORS = 20


class ScheduleError(Exception):
    """JSON не прочитался или не прошёл валидацию."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("; ".join(errors))

    def human(self) -> str:
        shown = self.errors[:MAX_ERRORS]
        lines = [f"• {e}" for e in shown]
        if len(self.errors) > MAX_ERRORS:
            lines.append(f"… и ещё {len(self.errors) - MAX_ERRORS}")
        return "\n".join(lines)


# --------------------------------------------------------------------------- валидация


def validate(data: object) -> list[str]:
    """Проверяет структуру расписания. Пустой список — всё хорошо."""
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["корень JSON должен быть объектом {…}"]

    anchor = data.get("week_anchor")
    if not isinstance(anchor, dict):
        errors.append("нет объекта week_anchor")
    else:
        monday = anchor.get("monday")
        try:
            if not isinstance(monday, str):
                raise ValueError
            m = date.fromisoformat(monday)
            if m.weekday() != 0:
                errors.append(f"week_anchor.monday ({monday}) — не понедельник")
        except ValueError:
            errors.append(f"week_anchor.monday должен быть датой ГГГГ-ММ-ДД, получено: {monday!r}")
        if anchor.get("week") not in (1, 2) or isinstance(anchor.get("week"), bool):
            errors.append(f"week_anchor.week должен быть 1 или 2, получено: {anchor.get('week')!r}")

    weeks = data.get("weeks")
    if not isinstance(weeks, dict):
        errors.append("нет объекта weeks")
        return errors

    for key in ("1", "2"):
        if key not in weeks:
            errors.append(f'в weeks нет ключа "{key}"')
    extra = sorted(set(weeks) - {"1", "2"})
    if extra:
        errors.append(f"в weeks лишние ключи: {', '.join(extra)} (допустимы только \"1\" и \"2\")")

    for wk in ("1", "2"):
        days = weeks.get(wk)
        if wk not in weeks:
            continue
        if not isinstance(days, list):
            errors.append(f"weeks.{wk} должен быть списком дней")
            continue
        seen: set[str] = set()
        for di, day in enumerate(days, 1):
            where = f"неделя {wk}, день №{di}"
            if not isinstance(day, dict):
                errors.append(f"{where}: должен быть объектом")
                continue
            name = day.get("day")
            if name not in DAYS:
                errors.append(f"{where}: поле day={name!r}, ожидается одно из {', '.join(DAYS)}")
                continue
            where = f"неделя {wk}, {DAY_RU[name]}"
            if name in seen:
                errors.append(f"{where}: день указан дважды")
            seen.add(name)
            lessons = day.get("lessons")
            if not isinstance(lessons, list):
                errors.append(f"{where}: поле lessons должно быть списком")
                continue
            for li, lesson in enumerate(lessons, 1):
                errors.extend(_validate_lesson(lesson, f"{where}, пара №{li}"))
    return errors


def _validate_lesson(lesson: object, where: str) -> list[str]:
    if not isinstance(lesson, dict):
        return [f"{where}: должна быть объектом"]
    errors = []
    subject = lesson.get("subject")
    if not isinstance(subject, str) or not subject.strip():
        errors.append(f"{where}: нет subject")
    else:
        where = f"{where} ({subject})"
    for field in ("start", "end"):
        value = lesson.get(field)
        if not isinstance(value, str) or not TIME_RE.match(value):
            errors.append(f"{where}: {field}={value!r}, нужен формат HH:MM (например 08:00)")
    start, end = lesson.get("start"), lesson.get("end")
    if (
        isinstance(start, str) and isinstance(end, str)
        and TIME_RE.match(start) and TIME_RE.match(end) and end <= start
    ):
        errors.append(f"{where}: end ({end}) не позже start ({start})")
    for field in ("teacher", "place"):
        value = lesson.get(field)
        if value is not None and not isinstance(value, dict):
            errors.append(f"{where}: {field} должен быть объектом или null")
    sub = lesson.get("subgroup")
    if sub is not None and (isinstance(sub, bool) or not isinstance(sub, int)):
        errors.append(f"{where}: subgroup должен быть числом или null, получено {sub!r}")
    for field in ("type",):
        value = lesson.get(field)
        if value is not None and not isinstance(value, str):
            errors.append(f"{where}: {field} должен быть строкой")
    return errors


def parse(raw: bytes | str) -> dict:
    """Разбирает и валидирует JSON. Бросает ScheduleError."""
    try:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8-sig")
        data = json.loads(raw)
    except UnicodeDecodeError:
        raise ScheduleError(["файл не в кодировке UTF-8"]) from None
    except json.JSONDecodeError as e:
        raise ScheduleError([f"это не JSON: {e.msg} (строка {e.lineno}, столбец {e.colno})"]) from None
    errors = validate(data)
    if errors:
        raise ScheduleError(errors)
    return data


# --------------------------------------------------------------------------- запись


def dumps(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def atomic_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(dumps(data))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def count_lessons(data: dict, subgroup: int | None = None) -> int:
    total = 0
    for days in data["weeks"].values():
        for day in days:
            for lesson in day["lessons"]:
                if subgroup is None or lesson.get("subgroup") in (None, subgroup):
                    total += 1
    return total


# --------------------------------------------------------------------------- хранилище


class ScheduleStore:
    """Держит последнюю валидную версию и перечитывает файл, когда меняется его mtime."""

    def __init__(self, path: Path, history_dir: Path | None = None):
        self.path = Path(path)
        self.history_dir = Path(history_dir) if history_dir else self.path.parent / "history"
        self.data: dict | None = None
        self.loaded_at: datetime | None = None
        self.last_error: str | None = None
        self._stamp: tuple[int, int] | None | str = "never"

    def _file_stamp(self) -> tuple[int, int] | None:
        try:
            st = self.path.stat()
        except FileNotFoundError:
            return None
        return (st.st_mtime_ns, st.st_size)

    def refresh(self) -> str | None:
        """Перечитывает файл, если он изменился.

        Возвращает текст ошибки, только если она появилась именно сейчас
        (чтобы уведомлять об одной поломке один раз). Последняя валидная
        версия при ошибке остаётся в self.data.
        """
        stamp = self._file_stamp()
        if stamp == self._stamp:
            return None
        self._stamp = stamp

        if stamp is None:
            msg = f"Файл расписания не найден: {self.path}"
            return self._fail(msg)
        try:
            data = parse(self.path.read_bytes())
        except ScheduleError as e:
            return self._fail(f"Файл {self.path.name} невалидный:\n{e.human()}")
        except OSError as e:
            return self._fail(f"Не удалось прочитать {self.path}: {e}")

        first = self.data is None
        self.data = data
        self.last_error = None
        self.loaded_at = datetime.now()
        log.info("Расписание %s: %s, пар: %d", "загружено" if first else "перечитано",
                 self.path, count_lessons(data))
        return None

    def _fail(self, msg: str) -> str:
        self.last_error = msg
        if self.data is not None:
            msg += "\n\nБот продолжает работать на последней валидной версии."
        else:
            msg += "\n\nВалидного расписания нет. Пришлите боту .json файлом."
        log.error(msg)
        return msg

    def get(self) -> dict | None:
        self.refresh()
        return self.data

    def backup(self) -> Path | None:
        """Копирует текущий файл в history/schedule_<таймстемп>.json."""
        if not self.path.exists():
            return None
        self.history_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        dest = self.history_dir / f"schedule_{ts}.json"
        shutil.copy2(self.path, dest)
        log.info("Старая версия сохранена: %s", dest)
        return dest

    def save(self, data: dict, backup: bool = True) -> Path | None:
        errors = validate(data)
        if errors:
            raise ScheduleError(errors)
        backup_path = self.backup() if backup else None
        atomic_write_json(self.path, data)
        self.data = data
        self.last_error = None
        self.loaded_at = datetime.now()
        self._stamp = self._file_stamp()
        log.info("Расписание записано: %s, пар: %d", self.path, count_lessons(data))
        return backup_path

    def file_mtime(self) -> datetime | None:
        try:
            return datetime.fromtimestamp(self.path.stat().st_mtime)
        except FileNotFoundError:
            return None
