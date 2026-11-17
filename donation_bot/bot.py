"""Bandi's button-driven prototype. No payment or paid group action is implemented."""
import asyncio
from html import escape
import os
from pathlib import Path

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

router = Router()
store: "Store"
from .store import Store


class Donation(StatesGroup):
    amount = State()


class Topup(StatesGroup):
    amount = State()


def keyboard(*rows):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=item[0], callback_data=item[1],
                              **({'style': item[2]} if len(item) > 2 else {})) for item in row]
        for row in rows
    ])


HOME = keyboard([('🗃 Личный кабинет', 'b:menu')])
MENU = keyboard([('🗃 Пополнить баланс', 'b:topup', 'primary')],
                [('🐸 Задонатить', 'b:donate', 'success')],
                [('📌 Купить закреп', 'b:pin')], [('🎖 Купить тег', 'b:tag')],
                [('🧾 История операций', 'b:history'), ('⚙️ Как это работает', 'b:help')],
                [('👤 Профиль', 'b:profile'), ('🏆 Рейтинг', 'b:top')],
                [('Закрыть', 'b:close')])
BACK = keyboard([('Назад', 'b:menu')])
GROUP_MENU = keyboard([('🏆 Рейтинг', 'b:top')])
AMOUNTS = keyboard([('300 ₽', 'b:amount:300'), ('500 ₽', 'b:amount:500'), ('1000 ₽', 'b:amount:1000')],
                   [('Другая сумма', 'b:custom')], [('Личный кабинет', 'b:menu')])
TOPUP_AMOUNTS = keyboard(
    [('50 ₽', 'b:topup:50'), ('100 ₽', 'b:topup:100'), ('150 ₽', 'b:topup:150')],
    [('200 ₽', 'b:topup:200'), ('300 ₽', 'b:topup:300'), ('500 ₽', 'b:topup:500')],
    [('1000 ₽', 'b:topup:1000'), ('5000 ₽', 'b:topup:5000'), ('10000 ₽', 'b:topup:10000')],
    [('50000 ₽', 'b:topup:50000'), ('100000 ₽', 'b:topup:100000')],
    [('🐸 Другая сумма', 'b:topup-custom')], [('Назад', 'b:menu')])
PIN_TOPICS = keyboard([('MARKET (#Продам/#Куплю)', 'b:pin:market')],
                      [('Вакансии / Поиск работы', 'b:pin:jobs')], [('Личный кабинет', 'b:menu')])
TAG_TERMS = keyboard(*[[(label, f'b:tag:{months}')] for months, label in (
    (1, '1 месяц — 499 ₽'), (2, '2 месяца — 849 ₽'), (3, '3 месяца — 1149 ₽'),
    (6, '6 месяцев — 1990 ₽'), (12, '1 год — 2990 ₽'))], [('Личный кабинет', 'b:menu')])
TOP_TEXT = '🏆 <b>Рейтинг</b>\n\nРейтинг пока пуст: подтверждённых платежей нет, провайдер не подключён.'
SAVED = 'Запрос сохранён, но оплата недоступна: провайдер не подключён. Деньги не списаны и донат не подтверждён.'
UNAVAILABLE = 'Оплата пока недоступна: провайдер не подключён. Деньги не списаны, услуга не активирована.'
HELP = ('⚙️ <b>Как это работает</b>\n\n'
        'Bandi — помощник сообщества. В кабинете доступны профиль, настройка участия в рейтинге и раздел донатов.\n\n'
        'Сейчас работает прототип: пополнение, оплата донатов, покупка закрепов и тегов ещё не подключены. '
        'Выбор суммы доната сохраняет только намерение, без списания денег. '
        'В рейтинг попадут только подтверждённые платежи после подключения провайдера.\n\n'
        'Кнопки «Назад» возвращают в кабинет.')


def private(message: Message) -> bool:
    return message.chat.type == 'private' and message.from_user is not None


def register(user):
    store.upsert_user(user.id, user.full_name)


def valid_amount(text: str):
    if not text.isascii() or not text.isdigit() or len(text) > 7:
        return None
    value = int(text)
    return value if 1 <= value <= 1_000_000 else None


def donation_amount(text):
    value = valid_amount(text)
    return value if value is not None and 100 <= value <= 500_000 else None


def topup_amount(text):
    value = valid_amount(text)
    return value if value is not None and 50 <= value <= 100_000 else None


def profile_view(user):
    register(user)
    p = store.profile(user.id)
    text = (f"👤 <b>Профиль</b>\n\n{escape(p['name'])}\n"
            f"Подтверждённые донаты: {p['confirmed_total_minor'] // 100} ₽\n"
            f"Участие в рейтинге: {'да' if p['ranking_opt_in'] else 'нет'}\n\nПлатежи пока не подключены.")
    return text, keyboard([('Скрыть из рейтинга' if p['ranking_opt_in'] else 'Участвовать в рейтинге',
                            'b:visibility:off' if p['ranking_opt_in'] else 'b:visibility:on')],
                          [('Назад', 'b:menu')])


def cabinet_view():
    # No balance/ledger exists yet; never show donation intentions as credited funds.
    return ('🗃 <b>Личный кабинет</b>\n\nБаланс: <b>0 ₽</b>\n\n'
            'Выберите действие:\n\nПлатежи пока не подключены.', MENU)


def history_view(user):
    rows = store.intent_history(user.id)
    if not rows:
        return '🧾 <b>История операций</b>\n\nОпераций пока нет. Оплата не подключена.', BACK
    lines = ['🧾 <b>История операций</b>', '', 'Подтверждённых операций нет.', '', 'Неоплаченные запросы на донат:']
    for row in rows:
        lines.append(f"• {row[1] // 100} ₽ — оплата недоступна")
    lines.extend(['', 'Эти запросы не являются платежами и не увеличивают баланс или рейтинг.'])
    return '\n'.join(lines), BACK


async def render(message, text, markup, *, edit=False):
    if edit:
        # Telegram rejects an identical edit on a repeated tap; this is harmless.
        from aiogram.exceptions import TelegramBadRequest
        try:
            await message.edit_text(text, reply_markup=markup, parse_mode='HTML')
        except TelegramBadRequest as error:
            if 'message is not modified' not in str(error).lower():
                raise
    else:
        # aiogram 3.32's answer() already inherits the message's topic.
        await message.answer(text, reply_markup=markup, parse_mode='HTML')


@router.message(CommandStart())
async def start(message: Message, state: FSMContext):
    await state.clear()
    if private(message):
        register(message.from_user)
        name = escape(message.from_user.full_name)
        await render(message, f'👋 Привет, {name}!\n\n🗃 Откройте личный кабинет: баланс, донаты, история и настройки.', HOME)
    elif message.chat.type in ('group', 'supergroup'):
        await render(message, '🏆 Рейтинг доступен здесь. Личный кабинет — в личном чате с Bandi.', GROUP_MENU)


@router.message(Command('profile'))
async def profile(message: Message, state: FSMContext):
    if private(message):
        await state.clear()
        await render(message, *profile_view(message.from_user))


@router.message(Command('visibility'))
async def visibility(message: Message, state: FSMContext):
    if not private(message):
        return
    await state.clear()
    register(message.from_user)
    parts = (message.text or '').split()
    if len(parts) != 2 or parts[1] not in ('on', 'off'):
        await render(message, *profile_view(message.from_user))
        return
    store.set_visibility(message.from_user.id, parts[1] == 'on')
    await render(message, *profile_view(message.from_user))


@router.message(Command('donate'))
async def donate(message: Message, state: FSMContext):
    if not private(message):
        return
    await state.clear()
    register(message.from_user)
    parts = (message.text or '').split()
    if len(parts) == 1:
        await render(message, '💝 <b>Донат</b>\n\nВыберите сумму или введите свою — от 100 до 500000 ₽.\n\nОплата пока не подключена.', AMOUNTS)
        return
    amount = donation_amount(parts[1]) if len(parts) == 2 else None
    if amount is None:
        await render(message, 'Допустима целая сумма от 100 до 500000 ₽.', AMOUNTS)
        return
    store.create_intent(message.from_user.id, amount * 100)
    await render(message, SAVED, BACK)


@router.message(Command('top'))
async def top(message: Message):
    if message.chat.type in ('private', 'group', 'supergroup'):
        await render(message, TOP_TEXT, BACK if private(message) else GROUP_MENU)


@router.callback_query(F.data.startswith('b:'))
async def buttons(query: CallbackQuery, state: FSMContext):
    message = query.message
    if not isinstance(message, Message) or message.chat.type not in ('private', 'group', 'supergroup'):
        await query.answer('Меню недоступно.', show_alert=True)
        return
    action = query.data
    if message.chat.type != 'private':
        if action == 'b:top':
            await query.answer()
            await render(message, TOP_TEXT, GROUP_MENU)
        else:
            await query.answer('Откройте личный чат с ботом.', show_alert=True)
        return
    # No slow network or DB operation before acknowledging the callback.
    await query.answer()
    register(query.from_user)
    await state.clear()
    if action == 'b:menu':
        text, markup = cabinet_view()
    elif action == 'b:close':
        text, markup = '👋 Кабинет закрыт. Открыть его снова можно кнопкой ниже.', HOME
    elif action == 'b:profile':
        text, markup = profile_view(query.from_user)
    elif action in ('b:visibility:on', 'b:visibility:off'):
        store.set_visibility(query.from_user.id, action.endswith(':on'))
        text, markup = profile_view(query.from_user)
    elif action == 'b:history':
        text, markup = history_view(query.from_user)
    elif action == 'b:help':
        text, markup = HELP, BACK
    elif action == 'b:topup':
        text, markup = '🗃 Выберите сумму пополнения или введите свою:\n\nПополнение пока недоступно: провайдер не подключён.', TOPUP_AMOUNTS
    elif action == 'b:topup-custom':
        await state.set_state(Topup.amount)
        text, markup = '🗃 Отправьте целую сумму от 50 до 100000 ₽.\n\nПополнение пока недоступно.', BACK
    elif action.startswith('b:topup:') and topup_amount(action.removeprefix('b:topup:')) is not None:
        text, markup = UNAVAILABLE, BACK
    elif action == 'b:pin':
        text, markup = ('📌 Выберите топик, в котором нужно закрепить сообщение.\n\n'
                        'Это пример раздела: группа и топики ещё не подключены. Покупка закрепов недоступна.'), PIN_TOPICS
    elif action in ('b:pin:market', 'b:pin:jobs'):
        text, markup = '📌 Закрепы пока недоступны: группа, топики и оплата не подключены.\n\nДеньги не списаны.', BACK
    elif action == 'b:tag':
        text, markup = ('🎖 <b>Тег рядом с именем</b>\n\nКороткая подпись рядом с именем в чате, без дополнительных прав.\n\n'
                        'Сроки и цены ниже — образец из референса. Покупка и установка тегов пока недоступны.'), TAG_TERMS
    elif action in ('b:tag:1', 'b:tag:2', 'b:tag:3', 'b:tag:6', 'b:tag:12'):
        text, markup = UNAVAILABLE, BACK
    elif action == 'b:donate':
        text, markup = '💝 <b>Донат</b>\n\nВыберите сумму или введите свою — от 100 до 500000 ₽.\n\nОплата пока не подключена.', AMOUNTS
    elif action == 'b:custom':
        await state.set_state(Donation.amount)
        text, markup = '💝 Отправьте целую сумму от 100 до 500000 ₽.\n\nОплата пока не подключена.', BACK
    elif action.startswith('b:amount:') and donation_amount(action.removeprefix('b:amount:')) is not None:
        store.create_intent(query.from_user.id, donation_amount(action.removeprefix('b:amount:')) * 100)
        text, markup = SAVED, BACK
    elif action == 'b:top':
        text, markup = TOP_TEXT, BACK
    else:
        text, markup = 'Кнопка устарела. Выберите действие в личном кабинете.', MENU
    await render(message, text, markup, edit=True)


@router.message(StateFilter(Donation.amount))
async def custom_amount(message: Message, state: FSMContext):
    if not private(message):
        return
    amount = donation_amount(message.text or '')
    if amount is None:
        await render(message, 'Допустима целая сумма от 100 до 500000 ₽. Попробуйте ещё раз.', BACK)
        return
    register(message.from_user)
    store.create_intent(message.from_user.id, amount * 100)
    await state.clear()
    await render(message, SAVED, BACK)


@router.message(StateFilter(Topup.amount))
async def custom_topup(message: Message, state: FSMContext):
    if not private(message):
        return
    if topup_amount(message.text or '') is None:
        await render(message, 'Допустима целая сумма от 50 до 100000 ₽. Попробуйте ещё раз.', BACK)
        return
    await state.clear()
    await render(message, UNAVAILABLE, BACK)


async def main():
    from aiogram.client.session.aiohttp import AiohttpSession
    token = os.environ.get('BOT_TOKEN')
    if not token:
        raise SystemExit('Set BOT_TOKEN in a secure environment; no connection started.')
    global store
    db_path = Path(os.environ.get('BOT_DB', 'data/bot.sqlite3'))
    db_path.parent.mkdir(parents=True, exist_ok=True)
    store = Store(db_path)
    proxy = os.environ.get('BOT_PROXY')
    session = AiohttpSession(proxy=proxy) if proxy else AiohttpSession()
    bot = Bot(token, session=session)
    dp = Dispatcher()
    dp.include_router(router)
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()
        store.close()


if __name__ == '__main__':
    asyncio.run(main())
