"""Offline adapter tests with a lightweight aiogram double; no network or bot token."""
import asyncio
import importlib
import sys
import types
import unittest
from unittest.mock import AsyncMock
from donation_bot.store import Store


def load_adapter():
    names = ['aiogram', 'aiogram.filters', 'aiogram.fsm', 'aiogram.fsm.context',
             'aiogram.fsm.state', 'aiogram.types', 'aiogram.exceptions']
    modules = {name: types.ModuleType(name) for name in names}
    class Router:
        def message(self, *args): return lambda fn: fn
        def callback_query(self, *args): return lambda fn: fn
    class Filter:
        def __getattr__(self, name): return self
        def __call__(self, *args, **kwargs): return self
    class Markup:
        def __init__(self, **kwargs): self.__dict__.update(kwargs)
    class Message: pass
    root = modules['aiogram']
    root.Bot = root.Dispatcher = object
    root.Router, root.F = Router, Filter()
    modules['aiogram.filters'].Command = modules['aiogram.filters'].CommandStart = lambda *a: None
    modules['aiogram.filters'].StateFilter = lambda *a: None
    modules['aiogram.fsm.context'].FSMContext = object
    modules['aiogram.fsm.state'].State = type('State', (), {})
    modules['aiogram.fsm.state'].StatesGroup = type('StatesGroup', (), {})
    modules['aiogram.exceptions'].TelegramBadRequest = type('TelegramBadRequest', (Exception,), {})
    t = modules['aiogram.types']
    t.CallbackQuery, t.Message = object, Message
    t.InlineKeyboardButton = t.InlineKeyboardMarkup = Markup
    old = {name: sys.modules.get(name) for name in names}
    sys.modules.update(modules)
    try:
        sys.modules.pop('donation_bot.bot', None)
        return importlib.import_module('donation_bot.bot'), Message
    finally:
        for name, module in old.items():
            if module is None: sys.modules.pop(name, None)
            else: sys.modules[name] = module


class ButtonTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.bot, self.Message = load_adapter()
        self.exception_patch = unittest.mock.patch.dict(sys.modules, {'aiogram.exceptions': types.SimpleNamespace(TelegramBadRequest=type('TelegramBadRequest', (Exception,), {}))})
        self.exception_patch.start()
        self.bot.store = Store(':memory:')
        self.user = types.SimpleNamespace(id=12, full_name='Tester')
        self.state = types.SimpleNamespace(clear=AsyncMock(), set_state=AsyncMock())
        self.msg = self.Message()
        self.msg.chat = types.SimpleNamespace(type='private')
        self.msg.from_user = self.user
        self.msg.message_thread_id = None
        self.msg.answer = AsyncMock()
        self.msg.edit_text = AsyncMock()

    async def asyncTearDown(self):
        self.bot.store.close()
        self.exception_patch.stop()

    def query(self, action):
        return types.SimpleNamespace(data=action, message=self.msg, from_user=self.user, answer=AsyncMock())

    async def test_navigation_visibility_and_intent(self):
        for action in ('b:menu', 'b:profile', 'b:visibility:on', 'b:donate', 'b:amount:500'):
            q = self.query(action)
            await self.bot.buttons(q, self.state)
            q.answer.assert_awaited_once()
        self.assertTrue(self.bot.store.profile(12)['ranking_opt_in'])
        self.assertEqual(self.bot.store.db.execute('SELECT amount_minor,status FROM donation_intents').fetchone(), (50000, 'unavailable'))
        self.assertEqual(self.bot.store.profile(12)['confirmed_total_minor'], 0)
        self.assertIn('Деньги не списаны', self.msg.edit_text.await_args.args[0])

    async def test_custom_amount_validation_and_back(self):
        await self.bot.buttons(self.query('b:custom'), self.state)
        self.state.set_state.assert_awaited_once()
        self.msg.text = '1000001'
        await self.bot.custom_amount(self.msg, self.state)
        self.assertEqual(self.bot.store.db.execute('SELECT count(*) FROM donation_intents').fetchone()[0], 0)
        self.msg.text = '142'
        await self.bot.custom_amount(self.msg, self.state)
        self.assertEqual(self.bot.store.db.execute('SELECT amount_minor FROM donation_intents').fetchone()[0], 14200)
        await self.bot.buttons(self.query('b:menu'), self.state)
        self.assertIn('Выберите действие', self.msg.edit_text.await_args.args[0])

    async def test_group_topic_and_private_actions_blocked(self):
        self.msg.chat.type = 'supergroup'
        self.msg.message_thread_id = 999
        q = self.query('b:top')
        await self.bot.buttons(q, self.state)
        self.msg.answer.assert_awaited_once()
        # Real aiogram shortcut topic propagation is checked by test_real_adapter.py.
        self.msg.answer.reset_mock()
        q = self.query('b:visibility:on')
        await self.bot.buttons(q, self.state)
        self.msg.answer.assert_not_awaited()
        self.assertTrue(q.answer.await_args.kwargs['show_alert'])
        self.assertEqual(self.bot.store.db.execute('SELECT count(*) FROM users').fetchone()[0], 0)

    async def test_amount_validation(self):
        for value in ('', '0', '-1', '1.5', '１２', '1000001', '99999999'):
            self.assertIsNone(self.bot.valid_amount(value))
        self.assertEqual(self.bot.valid_amount('1000000'), 1000000)


class ReferenceScreenTests(ButtonTests):
    async def test_reference_cabinet_buttons(self):
        await self.bot.buttons(self.query('b:menu'), self.state)
        markup = self.msg.edit_text.await_args.kwargs['reply_markup']
        labels = [[button.text for button in row] for row in markup.inline_keyboard]
        self.assertEqual(labels[:5], [['🗃 Пополнить баланс'], ['🐸 Задонатить'], ['📌 Купить закреп'], ['🎖 Купить тег'], ['🧾 История операций', '⚙️ Как это работает']])
        self.assertEqual(labels[-1], ['Закрыть'])
        self.msg.answer.assert_not_awaited()

    async def test_all_reference_sections_and_back(self):
        for action in ('b:topup', 'b:donate', 'b:pin', 'b:tag', 'b:history', 'b:help', 'b:close'):
            await self.bot.buttons(self.query(action), self.state)
            self.assertIsNotNone(self.msg.edit_text.await_args.kwargs['reply_markup'])
            await self.bot.buttons(self.query('b:menu'), self.state)
            self.assertIn('Личный кабинет', self.msg.edit_text.await_args.args[0])

    async def test_unavailable_actions_never_change_money(self):
        for action in ('b:topup:100', 'b:pin:market', 'b:pin:jobs', 'b:tag:1', 'b:tag:12'):
            await self.bot.buttons(self.query(action), self.state)
            self.assertIn('не', self.msg.edit_text.await_args.args[0])
        self.assertEqual(self.bot.store.db.execute('SELECT count(*) FROM donation_intents').fetchone()[0], 0)
        self.assertEqual(self.bot.store.profile(12)['confirmed_total_minor'], 0)

    async def test_names_escaped_and_close_reopens(self):
        self.user.full_name = '<b>Tester</b>'
        await self.bot.start(self.msg, self.state)
        self.assertIn('&lt;b&gt;', self.msg.answer.await_args.args[0])
        await self.bot.buttons(self.query('b:close'), self.state)
        markup = self.msg.edit_text.await_args.kwargs['reply_markup']
        self.assertEqual(markup.inline_keyboard[0][0].callback_data, 'b:menu')

    async def test_repeated_edit_only_ignores_identical_message(self):
        # load_adapter restores modules; inject only this exception module for the call.
        exc_module = types.ModuleType('aiogram.exceptions')
        exc_module.TelegramBadRequest = type('TelegramBadRequest', (Exception,), {})
        old = sys.modules.get('aiogram.exceptions')
        sys.modules['aiogram.exceptions'] = exc_module
        try:
            self.msg.edit_text.side_effect = exc_module.TelegramBadRequest('Bad Request: message is not modified')
            await self.bot.buttons(self.query('b:menu'), self.state)
            self.msg.edit_text.side_effect = exc_module.TelegramBadRequest('Bad Request: chat not found')
            with self.assertRaises(exc_module.TelegramBadRequest):
                await self.bot.buttons(self.query('b:menu'), self.state)
        finally:
            if old is None: sys.modules.pop('aiogram.exceptions', None)
            else: sys.modules['aiogram.exceptions'] = old

    async def test_history_excludes_other_users(self):
        self.bot.store.upsert_user(99, 'Other')
        self.bot.store.create_intent(99, 99900)
        self.bot.store.upsert_user(12, 'Tester')
        self.bot.store.create_intent(12, 30000)
        text, _ = self.bot.history_view(self.user)
        self.assertIn('300 ₽', text)
        self.assertNotIn('999 ₽', text)
        self.assertIn('не являются платежами', text)

    async def test_amount_ranges(self):
        self.assertIsNone(self.bot.donation_amount('99'))
        self.assertEqual(self.bot.donation_amount('500000'), 500000)
        self.assertIsNone(self.bot.donation_amount('500001'))
        self.assertIsNone(self.bot.topup_amount('49'))
        self.assertEqual(self.bot.topup_amount('100000'), 100000)
        self.assertIsNone(self.bot.topup_amount('100001'))


if __name__ == '__main__':
    unittest.main()
