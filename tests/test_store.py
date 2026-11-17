import sqlite3
import unittest
from donation_bot.store import Store


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.s = Store(':memory:')
        self.s.upsert_user(123, ' Test  User ')

    def tearDown(self):
        self.s.close()

    def test_profile_and_consent_default(self):
        p = self.s.profile(123)
        self.assertEqual(p['name'], 'Test User')
        self.assertFalse(p['ranking_opt_in'])
        self.s.set_visibility(123, True)
        self.assertTrue(self.s.profile(123)['ranking_opt_in'])
        self.s.upsert_user(123, 'New name')
        self.assertTrue(self.s.profile(123)['ranking_opt_in'])
        self.s.set_visibility(123, False)
        self.assertFalse(self.s.profile(123)['ranking_opt_in'])

    def test_intent_is_not_payment(self):
        self.s.create_intent(123, 10000)
        self.assertEqual(self.s.db.execute('SELECT status FROM donation_intents').fetchone()[0], 'unavailable')
        self.assertEqual(self.s.profile(123)['confirmed_total_minor'], 0)
        self.assertEqual(self.s.leaderboard(), [])
        with self.assertRaises(sqlite3.IntegrityError):
            self.s.db.execute("UPDATE donation_intents SET status='paid'")

    def test_amounts(self):
        for amount in (0, 99, -1, 100_000_001, True, 100.0):
            with self.subTest(amount=amount), self.assertRaises(ValueError):
                self.s.create_intent(123, amount)
        self.s.create_intent(123, 100)
        self.s.create_intent(123, 100_000_000)

    def test_unknown_user_rejected(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.s.create_intent(999, 100)
        with self.assertRaises(ValueError):
            self.s.set_visibility(999, True)

if __name__ == '__main__':
    unittest.main()
