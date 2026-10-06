"""Команды бота и приём нового schedule.json."""

from __future__ import annotations

import logging
import secrets
from collections.abc import Awaitable, Callable
from datetime import date, datetime, timedelta
from typing import Any

from aiogram import BaseMiddleware, Bot, F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    TelegramObject,
    User,
)

from . import diff as diff_mod
from . import formatter
from .config import Config
from .schedule import ScheduleError, ScheduleStore, dumps, parse
from .weeks import apply_setweek, monday_of, week_number_for

log = logging.getLogger(__name__)
router = Router(name="schedule")

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_PENDING = 5


def today(config: Config) -> date:
    return datetime.now(config.tz).date()


async def notify_error(bot: Bot, config: Config, text: str) -> None:
    try:
        await bot.send_message(config.admin_id, "⚠️ " + formatter.esc(text))
    except Exception:
        log.exception("Не удалось отправить сообщение об ошибке")


async def refresh_and_notify(bot: Bot, config: Config, store: ScheduleStore) -> dict | None:
    """Перечитывает файл при изменении mtime и сообщает о новой ошибке."""
    error = store.refresh()
    if error:
        await notify_error(bot, config, error)
    return store.data


class AdminOnlyMiddleware(BaseMiddleware):
    """Пропускает только ADMIN_ID; перед обработкой проверяет mtime расписания."""

    def __init__(self, config: Config, store: ScheduleStore):
        self.config = config
        self.store = store

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user: User | None = data.get("event_from_user")
        if user is None or user.id != self.config.admin_id:
            if user is not None:
                log.info("Игнорирую пользователя %s (@%s)", user.id, user.username)
            return None
        await refresh_and_notify(data["bot"], self.config, self.store)
        return await handler(event, data)


async def no_schedule(message: Message, store: ScheduleStore) -> None:
    text = "Валидного расписания нет. Пришлите мне schedule.json файлом."
    if store.last_error:
        text += "\n\n" + formatter.esc(store.last_error)
    await message.answer(text)


async def send_many(message: Message, parts: list[str]) -> None:
    for part in parts:
        await message.answer(part)


# --------------------------------------------------------------------------- команды


@router.message(CommandStart())
@router.message(Command("help"))
async def cmd_start(message: Message, store: ScheduleStore) -> None:
    await message.answer(formatter.format_help(store.data))
    if store.data is None:
        await no_schedule(message, store)


async def _send_day(message: Message, config: Config, store: ScheduleStore, d: date, label: str) -> None:
    data = store.data
    if data is None:
        await no_schedule(message, store)
        return
    text = formatter.format_date(data, d, config.subgroup)
    if text is None:
        week = week_number_for(data, d)
        text = f"{label} ({formatter.fmt_date(d)}, {week} неделя) пар нет 🎉"
    await message.answer(text)


@router.message(Command("today"))
async def cmd_today(message: Message, config: Config, store: ScheduleStore) -> None:
    await _send_day(message, config, store, today(config), "Сегодня")


@router.message(Command("tomorrow"))
async def cmd_tomorrow(message: Message, config: Config, store: ScheduleStore) -> None:
    await _send_day(message, config, store, today(config) + timedelta(days=1), "Завтра")


@router.message(Command("week"))
async def cmd_week(message: Message, config: Config, store: ScheduleStore) -> None:
    if store.data is None:
        await no_schedule(message, store)
        return
    await send_many(message, formatter.format_week(store.data, today(config), config.subgroup))


@router.message(Command("next"))
async def cmd_next(message: Message, config: Config, store: ScheduleStore) -> None:
    if store.data is None:
        await no_schedule(message, store)
        return
    next_monday = monday_of(today(config)) + timedelta(days=7)
    await send_many(message, formatter.format_week(store.data, next_monday, config.subgroup))


@router.message(Command("info"))
async def cmd_info(message: Message, config: Config, store: ScheduleStore) -> None:
    if store.data is None:
        await no_schedule(message, store)
        return
    mtime = store.file_mtime()
    mtime_text = mtime.strftime("%d.%m.%Y %H:%M:%S") + " (время сервера)" if mtime else None
    await message.answer(
        formatter.format_info(store.data, today(config), config.subgroup, mtime_text, store.last_error)
    )


@router.message(Command("json"))
async def cmd_json(message: Message, store: ScheduleStore) -> None:
    if store.path.exists():
        caption = None
        if store.last_error:
            caption = "⚠️ Файл на диске невалидный, бот работает на последней валидной версии (пришлю её следом)."
        await message.answer_document(FSInputFile(store.path, filename=store.path.name), caption=caption)
        if store.last_error and store.data is not None:
            await message.answer_document(
                BufferedInputFile(dumps(store.data).encode("utf-8"), filename="schedule_last_valid.json"),
                caption="Последняя валидная версия",
            )
    elif store.data is not None:
        await message.answer_document(
            BufferedInputFile(dumps(store.data).encode("utf-8"), filename=store.path.name),
            caption="⚠️ Файла на диске нет, это последняя валидная версия из памяти.",
        )
    else:
        await no_schedule(message, store)


@router.message(Command("setweek"))
async def cmd_setweek(
    message: Message, command: CommandObject, config: Config, store: ScheduleStore
) -> None:
    arg = (command.args or "").strip()
    if arg not in ("1", "2"):
        await message.answer("Использование: <code>/setweek 1</code> или <code>/setweek 2</code> — какая неделя идёт сейчас.")
        return
    if store.data is None:
        await no_schedule(message, store)
        return
    now = today(config)
    new = apply_setweek(store.data, now, int(arg))
    backup = store.save(new)
    monday = monday_of(now)
    text = (
        f"✅ Сейчас <b>{arg} неделя</b> ({formatter.fmt_date(monday)}–"
        f"{formatter.fmt_date(monday + timedelta(days=6))}).\n"
        f"Следующая — {2 if arg == '1' else 1} неделя."
    )
    if backup:
        text += f"\nСтарая версия: <code>{formatter.esc(backup.relative_to(store.path.parent))}</code>"
    await message.answer(text)


# --------------------------------------------------------------------------- загрузка JSON

# token -> новая версия расписания, ожидающая подтверждения
pending: dict[str, dict] = {}


def confirm_keyboard(token: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="✅ Применить", callback_data=f"apply:{token}"),
            InlineKeyboardButton(text="❌ Отмена", callback_data=f"cancel:{token}"),
        ]]
    )


@router.message(F.document)
async def on_document(message: Message, bot: Bot, config: Config, store: ScheduleStore) -> None:
    doc = message.document
    name = doc.file_name or ""
    if not name.lower().endswith(".json") and doc.mime_type != "application/json":
        await message.answer("Пришлите расписание файлом с расширением <code>.json</code>.")
        return
    if doc.file_size and doc.file_size > MAX_UPLOAD_BYTES:
        await message.answer("Файл слишком большой (больше 5 МБ) — это точно расписание?")
        return

    buf = await bot.download(doc)
    try:
        new = parse(buf.read())
    except ScheduleError as e:
        await message.answer(
            "❌ Файл не подошёл, расписание не изменено:\n" + formatter.esc(e.human())
        )
        return

    changes = diff_mod.compare(store.data, new)
    parts = formatter.format_diff(changes, config.subgroup)
    if store.data is None:
        parts[0] = "ℹ️ Текущего валидного расписания нет — все пары будут новыми.\n\n" + parts[0]

    while len(pending) >= MAX_PENDING:
        pending.pop(next(iter(pending)))
    token = secrets.token_hex(6)
    pending[token] = new

    for part in parts[:-1]:
        await message.answer(part)
    await message.answer(parts[-1] + "\n\nПрименить это расписание?", reply_markup=confirm_keyboard(token))


@router.callback_query(F.data.startswith("apply:"))
async def on_apply(call: CallbackQuery, config: Config, store: ScheduleStore) -> None:
    token = call.data.split(":", 1)[1]
    new = pending.pop(token, None)
    if new is None:
        await call.answer("Эта загрузка устарела, пришлите файл ещё раз.", show_alert=True)
        await _drop_keyboard(call)
        return
    new = dict(new)
    new["updated_at"] = today(config).isoformat()
    try:
        backup = store.save(new)
    except (ScheduleError, OSError) as e:
        log.exception("Не удалось сохранить расписание")
        await call.answer("Ошибка при сохранении", show_alert=True)
        await call.message.answer(f"❌ Не удалось сохранить: {formatter.esc(e)}")
        return
    await call.answer("Применено")
    await _drop_keyboard(call, "✅ <b>Применено.</b>")
    text = f"Расписание обновлено, updated_at = {new['updated_at']}."
    if backup:
        text += f"\nСтарая версия: <code>{formatter.esc(backup.relative_to(store.path.parent))}</code>"
    await call.message.answer(text)


@router.callback_query(F.data.startswith("cancel:"))
async def on_cancel(call: CallbackQuery) -> None:
    pending.pop(call.data.split(":", 1)[1], None)
    await call.answer("Отменено")
    await _drop_keyboard(call, "❌ <b>Отменено</b>, расписание не изменено.")


async def _drop_keyboard(call: CallbackQuery, suffix: str | None = None) -> None:
    msg = call.message
    if not isinstance(msg, Message):
        return
    try:
        if suffix and msg.html_text:
            text = msg.html_text.removesuffix("\n\nПрименить это расписание?")
            await msg.edit_text(f"{text}\n\n{suffix}", reply_markup=None)
        else:
            await msg.edit_reply_markup(reply_markup=None)
    except Exception:
        log.debug("Не удалось отредактировать сообщение", exc_info=True)


@router.message()
async def fallback(message: Message) -> None:
    await message.answer("Не понял. Список команд — /start. Новое расписание — пришлите .json файлом.")

