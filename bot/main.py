"""Запуск бота и планировщика рассылок."""

from __future__ import annotations

import asyncio
import logging
import sys
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from . import formatter, reminders
from .config import PROJECT_ROOT, Config, ConfigError, load_config
from .handlers import AdminOnlyMiddleware, refresh_and_notify, router, today
from .schedule import ScheduleStore
from .settings import SettingsStore
from .weeks import monday_of

log = logging.getLogger("bot")

COMMANDS = [
    BotCommand(command="today", description="Пары на сегодня"),
    BotCommand(command="tomorrow", description="Пары на завтра"),
    BotCommand(command="week", description="Текущая неделя"),
    BotCommand(command="next", description="Следующая неделя"),
    BotCommand(command="info", description="Номер недели и сведения о расписании"),
    BotCommand(command="json", description="Прислать schedule.json"),
    BotCommand(command="setweek", description="Указать текущую неделю: /setweek 1|2"),
    BotCommand(command="reminder_time", description="Напоминание после пары: /reminder_time 5 | off"),
    BotCommand(command="start", description="Справка"),
]


def setup_logging() -> None:
    logs_dir = PROJECT_ROOT / "logs"
    logs_dir.mkdir(exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    file = RotatingFileHandler(logs_dir / "bot.log", maxBytes=1_000_000, backupCount=5, encoding="utf-8")
    file.setFormatter(fmt)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers[:] = [console, file]
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)
    logging.getLogger("apscheduler.executors").setLevel(logging.WARNING)


async def send_today(bot: Bot, config: Config, store: ScheduleStore) -> None:
    data = await refresh_and_notify(bot, config, store)
    if data is None:
        log.warning("Утренняя рассылка пропущена: нет валидного расписания")
        return
    text = formatter.format_date(data, today(config), config.subgroup)
    if text is None:
        log.info("Утренняя рассылка: сегодня пар нет")
        return
    await bot.send_message(config.admin_id, "☀️ Доброе утро! Пары на сегодня:\n\n" + text)


async def send_next_week(bot: Bot, config: Config, store: ScheduleStore) -> None:
    data = await refresh_and_notify(bot, config, store)
    if data is None:
        await bot.send_message(
            config.admin_id, "Не могу прислать расписание на неделю: нет валидного schedule.json."
        )
        return
    next_monday = monday_of(today(config)) + timedelta(days=7)
    for part in formatter.format_week(data, next_monday, config.subgroup):
        await bot.send_message(config.admin_id, part)


async def watch_file(bot: Bot, config: Config, store: ScheduleStore) -> None:
    """Раз в минуту проверяет mtime, чтобы сообщить о сломанном файле сразу, а не при следующей команде."""
    await refresh_and_notify(bot, config, store)


class ReminderSender:
    """Раз в минуту отправляет напоминания о следующей паре, каждое — один раз."""

    def __init__(self, bot: Bot, config: Config, store: ScheduleStore, settings: SettingsStore):
        self.bot, self.config, self.store, self.settings = bot, config, store, settings
        self.sent: set[str] = set()

    async def __call__(self) -> None:
        s = self.settings.settings
        if not s.reminders_enabled:
            return
        data = await refresh_and_notify(self.bot, self.config, self.store)
        if data is None:
            return
        now = datetime.now(self.config.tz)
        d = now.date()
        todays = reminders.plan(data, d, s.reminder_offset_min, self.config.subgroup, self.config.tz)
        # пара могла закончиться вчера поздно, а напоминание — уже после полуночи
        yesterday = reminders.plan(
            data, d - timedelta(days=1), s.reminder_offset_min, self.config.subgroup, self.config.tz
        )
        plan = yesterday + todays
        keys = {r.key for r in plan}
        self.sent &= keys
        for r in reminders.due(plan, now, self.sent):
            self.sent.add(r.key)
            await self.bot.send_message(self.config.admin_id, r.text)
            log.info("Напоминание отправлено: %s", r.key)


def build_scheduler(
    bot: Bot, config: Config, store: ScheduleStore, settings: SettingsStore
) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=config.tz)
    args = [bot, config, store]
    common = {"args": args, "misfire_grace_time": 3600, "coalesce": True}
    scheduler.add_job(send_today, CronTrigger(hour=7, minute=0, timezone=config.tz),
                      id="morning", **common)
    scheduler.add_job(send_next_week, CronTrigger(day_of_week="sun", hour=18, minute=0, timezone=config.tz),
                      id="sunday", **common)
    scheduler.add_job(watch_file, "interval", minutes=1, id="watch_file", **common)
    scheduler.add_job(ReminderSender(bot, config, store, settings),
                      CronTrigger(minute="*", second=5, timezone=config.tz),
                      id="reminders", misfire_grace_time=60, coalesce=True, max_instances=1)
    return scheduler


async def run() -> None:
    setup_logging()
    try:
        config = load_config()
    except ConfigError as e:
        log.error("Ошибка конфигурации: %s", e)
        raise SystemExit(1) from None

    store = ScheduleStore(config.schedule_path, config.history_dir)
    bot = Bot(config.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    settings = SettingsStore(config.schedule_path.parent / "settings.json")
    dp = Dispatcher(config=config, store=store, settings=settings)
    dp.update.outer_middleware(AdminOnlyMiddleware(config, store))
    dp.include_router(router)

    startup_error = store.refresh()
    if startup_error:
        await refresh_notify_startup(bot, config, startup_error)

    await bot.set_my_commands(COMMANDS)
    scheduler = build_scheduler(bot, config, store, settings)
    scheduler.start()
    log.info("Бот запущен. Подгруппа: %s, TZ: %s", config.subgroup or "все", config.tz.key)
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        scheduler.shutdown(wait=False)
        await bot.session.close()


async def refresh_notify_startup(bot: Bot, config: Config, error: str) -> None:
    try:
        await bot.send_message(
            config.admin_id, "⚠️ Бот запущен, но расписание не загружено.\n\n" + formatter.esc(error)
        )
    except Exception:
        log.exception("Не удалось отправить сообщение администратору (он писал боту /start?)")


def main() -> None:
    try:
        asyncio.run(run())
    except (KeyboardInterrupt, SystemExit) as e:
        if isinstance(e, SystemExit) and e.code:
            raise


if __name__ == "__main__":
    main()
