"""Actual aiogram shortcut contract: no network/token required."""
import importlib
import sys
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock

try:
    from aiogram import Bot
    from aiogram.types import Message, Chat
    HAS_AIOGRAM = True
except ImportError:
    HAS_AIOGRAM = False


@unittest.skipUnless(HAS_AIOGRAM, 'requires installed aiogram')
class RealAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_render_uses_actual_topic_inheritance(self):
        # Earlier offline suites deliberately import an adapter with fake types.
        sys.modules.pop('donation_bot.bot', None)
        app = importlib.import_module('donation_bot.bot')
        bot = Bot('123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijk')
        bot.session.make_request = AsyncMock(return_value=True)
        try:
            for chat_type, topic in [('private', None), ('supergroup', 999)]:
                msg = Message(message_id=1, date=datetime.now(timezone.utc),
                              chat=Chat(id=12 if topic is None else -100123, type=chat_type),
                              message_thread_id=topic, is_topic_message=topic is not None).as_(bot)
                await app.render(msg, 'Test', app.BACK)
                method = bot.session.make_request.await_args.args[1]
                self.assertEqual(method.message_thread_id, topic)
                self.assertEqual(method.parse_mode, 'HTML')
            await app.render(msg, 'Edited', app.BACK, edit=True)
            self.assertEqual(bot.session.make_request.await_args.args[1].message_id, 1)
        finally:
            await bot.session.close()
