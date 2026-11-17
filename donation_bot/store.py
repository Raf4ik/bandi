"""Local prototype storage. No payment event ingestion exists in this version."""
import sqlite3
from pathlib import Path


class Store:
    def __init__(self, path: str | Path):
        self.db = sqlite3.connect(path)
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS users (
          telegram_id INTEGER PRIMARY KEY, display_name TEXT NOT NULL,
          ranking_opt_in INTEGER NOT NULL DEFAULT 0 CHECK(ranking_opt_in IN (0,1))
        );
        CREATE TABLE IF NOT EXISTS donation_intents (
          id INTEGER PRIMARY KEY, telegram_id INTEGER NOT NULL REFERENCES users(telegram_id),
          amount_minor INTEGER NOT NULL CHECK(amount_minor > 0),
          currency TEXT NOT NULL CHECK(currency = 'RUB'),
          status TEXT NOT NULL DEFAULT 'unavailable' CHECK(status = 'unavailable'),
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        ''')
        self.db.commit()

    def upsert_user(self, user_id: int, name: str):
        if user_id <= 0:
            raise ValueError('invalid user')
        name = ' '.join(name.split())[:80] or 'Участник'
        with self.db:
            self.db.execute('INSERT INTO users(telegram_id,display_name) VALUES(?,?) '
                            'ON CONFLICT(telegram_id) DO UPDATE SET display_name=excluded.display_name',
                            (user_id, name))

    def set_visibility(self, user_id: int, enabled: bool):
        with self.db:
            cur = self.db.execute('UPDATE users SET ranking_opt_in=? WHERE telegram_id=?', (int(enabled), user_id))
            if cur.rowcount != 1:
                raise ValueError('unknown user')

    def profile(self, user_id: int):
        row = self.db.execute('SELECT display_name, ranking_opt_in FROM users WHERE telegram_id=?', (user_id,)).fetchone()
        if row is None:
            raise ValueError('unknown user')
        return {'name': row[0], 'ranking_opt_in': bool(row[1]), 'confirmed_total_minor': 0, 'currency': 'RUB'}

    def create_intent(self, user_id: int, amount_minor: int):
        if type(amount_minor) is not int or not 100 <= amount_minor <= 100_000_000:
            raise ValueError('amount outside supported range')
        with self.db:
            cur = self.db.execute('INSERT INTO donation_intents(telegram_id,amount_minor,currency) VALUES(?,?,?)',
                                  (user_id, amount_minor, 'RUB'))
            return cur.lastrowid

    def leaderboard(self):
        # No verified provider events/ledger are implemented: never invent totals.
        return []

    def close(self):
        self.db.close()
