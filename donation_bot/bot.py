"""Telegram adapter. Commands deliberately do not accept payment confirmations."""
import asyncio
import os
from pathlib import Path

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from .store import Store

router = Router()
store: Store


def private(message: Message) -> bool:
    return message.chat.type == 'private' and message.from_user is not None


def register(message: Message):
    u = message.from_user
    store.upsert_user(u.id, u.full_name)


@router.message(CommandStart())
async def start(message: Message):
    if not private(message):
        return
    register(message)
    await message.answer('Личный кабинет: /profile\nПоддержать: /donate СУММА (RUB)\nВидимость в рейтинге: /visibility on или /visibility off\nРейтинг: /top')


@router.message(Command('profile'))
async def profile(message: Message):
    if not private(message):
        return
    register(message)
    p = store.profile(message.from_user.id)
    await message.answer(f"Подтверждённые донаты: {p['confirmed_total_minor'] // 100} RUB\nУчастие в рейтинге: {'да' if p['ranking_opt_in'] else 'нет'}\nПлатежи пока не подключены.")


@router.message(Command('visibility'))
async def visibility(message: Message):
    if not private(message):
        return
    register(message)
    parts = (message.text or '').split()
    if len(parts) != 2 or parts[1] not in ('on', 'off'):
        await message.answer('Используйте /visibility on или /visibility off')
        return
    store.set_visibility(message.from_user.id, parts[1] == 'on')
    await message.answer('Настройка сохранена. Рейтинг пока не работает: платежи не подключены.')


@router.message(Command('donate'))
async def donate(message: Message):
    if not private(message):
        return
    register(message)
    parts = (message.text or '').split()
    if len(parts) != 2 or not parts[1].isascii() or not parts[1].isdigit() or len(parts[1]) > 7:
        await message.answer('Укажите целую сумму в рублях: /donate 100')
        return
    try:
        store.create_intent(message.from_user.id, int(parts[1]) * 100)
    except ValueError:
        await message.answer('Допустимая сумма: от 1 до 1 000 000 RUB.')
        return
    await message.answer('Запрос сохранён, но оплата недоступна: провайдер не подключён. Деньги не списаны и донат не подтверждён.')


@router.message(Command('top'))
async def top(message: Message):
    # Responds in the same chat/topic in which the command was received.
    if message.chat.type not in ('private', 'group', 'supergroup'):
        return
    await message.answer('Рейтинг пока пуст: подтверждённых платежей нет, провайдер не подключён.')


async def main():
    global store
    token = os.environ.get('BOT_TOKEN')
    if not token:
        raise SystemExit('Set BOT_TOKEN in a secure environment; no connection started.')
    db_path = Path(os.environ.get('BOT_DB', 'data/bot.sqlite3'))
    db_path.parent.mkdir(parents=True, exist_ok=True)
    store = Store(db_path)
    bot = Bot(token)
    dp = Dispatcher()
    dp.include_router(router)
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()
        store.close()


if __name__ == '__main__':
    asyncio.run(main())
