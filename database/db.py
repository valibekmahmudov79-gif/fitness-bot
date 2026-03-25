"""
database/db.py — SQLite база данных
Таблицы: users, orders
"""

import aiosqlite
import logging

logger = logging.getLogger(__name__)
DB_PATH = "fitness_bot.db"


class Database:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path

    async def init(self):
        """Создаёт таблицы при первом запуске"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    id         INTEGER PRIMARY KEY,
                    username   TEXT,
                    full_name  TEXT,
                    created_at TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS orders (
                    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id             INTEGER NOT NULL,
                    age                 INTEGER NOT NULL,
                    height              INTEGER NOT NULL,
                    weight              REAL    NOT NULL,
                    goal                TEXT    NOT NULL,
                    amount              INTEGER NOT NULL,
                    currency            TEXT    NOT NULL DEFAULT 'XTR',
                    status              TEXT    DEFAULT 'pending',
                    plan_sent           INTEGER DEFAULT 0,
                    telegram_charge_id  TEXT,
                    created_at          TEXT    DEFAULT (datetime('now')),
                    paid_at             TEXT,
                    FOREIGN KEY (user_id) REFERENCES users(id)
                );

                CREATE INDEX IF NOT EXISTS idx_orders_user_id ON orders(user_id);
            """)
            await db.commit()
        logger.info("Database initialized")

    async def upsert_user(self, user_id: int, username: str | None, full_name: str | None):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO users (id, username, full_name)
                VALUES (?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    username  = excluded.username,
                    full_name = excluded.full_name
            """, (user_id, username, full_name))
            await db.commit()

    async def create_order(
        self, user_id: int, age: int, height: int,
        weight: float, goal: str, amount: int, currency: str
    ) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("""
                INSERT INTO orders (user_id, age, height, weight, goal, amount, currency)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (user_id, age, height, weight, goal, amount, currency))
            await db.commit()
            order_id = cursor.lastrowid
            logger.info(f"Order created: id={order_id} user_id={user_id}")
            return order_id

    async def get_order(self, order_id: int) -> dict | None:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM orders WHERE id = ?", (order_id,))
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def get_user_orders(self, user_id: int) -> list[dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM orders WHERE user_id = ? ORDER BY created_at DESC",
                (user_id,)
            )
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    async def mark_order_paid(self, order_id: int, telegram_charge_id: str = ""):
        """
        Обновляет статус на paid.
        telegram_charge_id — уникальный ID транзакции от Telegram (для возвратов).
        """
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                UPDATE orders
                SET status = 'paid',
                    paid_at = datetime('now'),
                    telegram_charge_id = ?
                WHERE id = ? AND status = 'pending'
            """, (telegram_charge_id, order_id))
            await db.commit()
            logger.info(f"Order {order_id} marked as PAID | charge_id={telegram_charge_id}")

    async def mark_plan_sent(self, order_id: int):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("UPDATE orders SET plan_sent = 1 WHERE id = ?", (order_id,))
            await db.commit()

    async def get_paid_unsent_orders(self) -> list[dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM orders WHERE status = 'paid' AND plan_sent = 0"
            )
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]
