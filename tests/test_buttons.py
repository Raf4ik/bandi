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
             'aiogram.fsm.state', 'aiogram.types']
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
        self.bot.store = Store(':memory:')
        self.user = types.SimpleNamespace(id=12, full_name='Tester')
        self.state = types.SimpleNamespace(clear=AsyncMock(), set_state=AsyncMock())
        self.msg = self.Message()
        self.msg.chat = types.SimpleNamespace(type='private')
        self.msg.from_user = self.user
        self.msg.message_thread_id = None
        self.msg.answer = AsyncMock()

    async def asyncTearDown(self):
        self.bot.store.close()

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
        self.assertIn('Деньги не списаны', self.msg.answer.await_args.args[0])

    async def test_custom_amount_validation_and_back(self):
        await self.bot.buttons(self.query('b:custom'), self.state)
        self.state.set_state.assert_awaited_once()
        self.msg.text = '1000001'
        await self.bot.custom_amount(self.msg, self.state)
        self.assertEqual(self.bot.store.db.execute('SELECT count(*) FROM donation_intents').fetchone()[0], 0)
        self.msg.text = '42'
        await self.bot.custom_amount(self.msg, self.state)
        self.assertEqual(self.bot.store.db.execute('SELECT amount_minor FROM donation_intents').fetchone()[0], 4200)
        await self.bot.buttons(self.query('b:menu'), self.state)
        self.assertIn('Выберите действие', self.msg.answer.await_args.args[0])

    async def test_group_topic_and_private_actions_blocked(self):
        self.msg.chat.type = 'supergroup'
        self.msg.message_thread_id = 999
        q = self.query('b:top')
        await self.bot.buttons(q, self.state)
        self.assertEqual(self.msg.answer.await_args.kwargs['message_thread_id'], 999)
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


if __name__ == '__main__':
    unittest.main()
