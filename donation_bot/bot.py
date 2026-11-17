"""Telegram adapter. No handler accepts payment confirmations."""
import asyncio
import os
from pathlib import Path

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from .store import Store

router = Router()
store: Store


class Donation(StatesGroup):
    amount = State()


def keyboard(*rows):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=label, callback_data=data) for label, data in row]
        for row in rows
    ])


MENU = keyboard([('👤 Профиль', 'b:profile'), ('❤️ Поддержать', 'b:donate')],
                [('🏆 Рейтинг', 'b:top')])
BACK = keyboard([('← В меню', 'b:menu')])
GROUP_MENU = keyboard([('🏆 Рейтинг', 'b:top')])
AMOUNTS = keyboard([('100 ₽', 'b:amount:100'), ('500 ₽', 'b:amount:500'), ('1000 ₽', 'b:amount:1000')],
                   [('Другая сумма', 'b:custom')], [('← В меню', 'b:menu')])
TOP_TEXT = 'Рейтинг пока пуст: подтверждённых платежей нет, провайдер не подключён.'
SAVED = 'Запрос сохранён, но оплата недоступна: провайдер не подключён. Деньги не списаны и донат не подтверждён.'


def private(message: Message) -> bool:
    return message.chat.type == 'private' and message.from_user is not None


def register(user):
    store.upsert_user(user.id, user.full_name)


def valid_amount(text: str):
    if not text.isascii() or not text.isdigit() or len(text) > 7:
        return None
    value = int(text)
    return value if 1 <= value <= 1_000_000 else None


def profile_view(user):
    register(user)
    p = store.profile(user.id)
    text = (f"Подтверждённые донаты: {p['confirmed_total_minor'] // 100} RUB\n"
            f"Участие в рейтинге: {'да' if p['ranking_opt_in'] else 'нет'}\nПлатежи пока не подключены.")
    return text, keyboard([('Скрыть из рейтинга' if p['ranking_opt_in'] else 'Участвовать в рейтинге',
                            'b:visibility:off' if p['ranking_opt_in'] else 'b:visibility:on')],
                          [('← В меню', 'b:menu')])


@router.message(CommandStart())
async def start(message: Message, state: FSMContext):
    await state.clear()
    if private(message):
        register(message.from_user)
        await message.answer('Личный кабинет. Выберите действие:', reply_markup=MENU)
    elif message.chat.type in ('group', 'supergroup'):
        await message.answer('Рейтинг доступен здесь. Личный кабинет и намерение поддержать — в личном чате с ботом.', reply_markup=GROUP_MENU)


@router.message(Command('profile'))
async def profile(message: Message, state: FSMContext):
    if not private(message):
        return
    await state.clear()
    text, markup = profile_view(message.from_user)
    await message.answer(text, reply_markup=markup)


@router.message(Command('visibility'))
async def visibility(message: Message, state: FSMContext):
    if not private(message):
        return
    await state.clear()
    register(message.from_user)
    parts = (message.text or '').split()
    if len(parts) != 2 or parts[1] not in ('on', 'off'):
        await message.answer('Выберите настройку в профиле или используйте /visibility on или /visibility off', reply_markup=BACK)
        return
    store.set_visibility(message.from_user.id, parts[1] == 'on')
    text, markup = profile_view(message.from_user)
    await message.answer(text, reply_markup=markup)


@router.message(Command('donate'))
async def donate(message: Message, state: FSMContext):
    if not private(message):
        return
    await state.clear()
    register(message.from_user)
    parts = (message.text or '').split()
    if len(parts) == 1:
        await message.answer('Выберите сумму намерения. Оплата не подключена.', reply_markup=AMOUNTS)
        return
    amount = valid_amount(parts[1]) if len(parts) == 2 else None
    if amount is None:
        await message.answer('Допустима целая сумма от 1 до 1 000 000 RUB.', reply_markup=AMOUNTS)
        return
    store.create_intent(message.from_user.id, amount * 100)
    await message.answer(SAVED, reply_markup=BACK)


@router.message(Command('top'))
async def top(message: Message):
    if message.chat.type in ('private', 'group', 'supergroup'):
        await message.answer(TOP_TEXT, reply_markup=BACK if private(message) else GROUP_MENU)


@router.callback_query(F.data.startswith('b:'))
async def buttons(query: CallbackQuery, state: FSMContext):
    message = query.message
    if not isinstance(message, Message) or message.chat.type not in ('private', 'group', 'supergroup'):
        await query.answer('Меню недоступно.', show_alert=True)
        return
    action = query.data
    if message.chat.type != 'private':
        if action == 'b:top':
            # A new answer inherits the originating message's topic via reply parameters.
            await message.answer(TOP_TEXT, message_thread_id=message.message_thread_id, reply_markup=GROUP_MENU)
            await query.answer()
        else:
            await query.answer('Откройте личный чат с ботом.', show_alert=True)
        return
    register(query.from_user)
    await state.clear()
    if action == 'b:menu':
        text, markup = 'Личный кабинет. Выберите действие:', MENU
    elif action == 'b:profile':
        text, markup = profile_view(query.from_user)
    elif action in ('b:visibility:on', 'b:visibility:off'):
        store.set_visibility(query.from_user.id, action.endswith(':on'))
        text, markup = profile_view(query.from_user)
    elif action == 'b:donate':
        text, markup = 'Выберите сумму намерения. Оплата не подключена.', AMOUNTS
    elif action == 'b:custom':
        await state.set_state(Donation.amount)
        text, markup = 'Отправьте целую сумму от 1 до 1 000 000 RUB. Оплата не подключена.', BACK
    elif action.startswith('b:amount:') and valid_amount(action.removeprefix('b:amount:')) is not None:
        store.create_intent(query.from_user.id, valid_amount(action.removeprefix('b:amount:')) * 100)
        text, markup = SAVED, BACK
    elif action == 'b:top':
        text, markup = TOP_TEXT, BACK
    else:
        await query.answer('Неизвестное действие.', show_alert=True)
        return
    await query.answer()
    # Send a new message instead of editing: repeated taps never trigger Telegram's
    # "message is not modified" error, including after a client reconnects.
    await message.answer(text, reply_markup=markup)


@router.message(StateFilter(Donation.amount))
async def custom_amount(message: Message, state: FSMContext):
    if not private(message):
        return
    amount = valid_amount(message.text or '')
    if amount is None:
        await message.answer('Допустима целая сумма от 1 до 1 000 000 RUB. Попробуйте ещё раз.', reply_markup=BACK)
        return
    register(message.from_user)
    store.create_intent(message.from_user.id, amount * 100)
    await state.clear()
    await message.answer(SAVED, reply_markup=BACK)


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
