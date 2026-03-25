"""
bot.py — Telegram бот с РЕАЛЬНОЙ оплатой через Telegram Stars
═══════════════════════════════════════════════════════════════
Telegram Stars — встроенная платёжная система Telegram.
• Не нужна регистрация ИП или компании
• Не нужны API-ключи платёжных систем
• Деньги приходят прямо в твой бот
• Работает во всех странах мира

Как вывести Stars в деньги:
  @BotFather → выбери бота → Bot Payments → Withdraw Stars
"""

import asyncio
import logging
import os
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    LabeledPrice,
)

from database.db import Database
from ai_service import generate_workout_plan

load_dotenv()

# ─── Логирование ────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

# ─── Конфиг ─────────────────────────────────────────────────────────────────────
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")

# Цена в Telegram Stars (1 Star ≈ $0.013)
# 350 Stars ≈ $4.5
PRICE_IN_STARS = 350

# ─── FSM состояния ──────────────────────────────────────────────────────────────
class UserForm(StatesGroup):
    age    = State()
    height = State()
    weight = State()
    goal   = State()


# ─── Инициализация ───────────────────────────────────────────────────────────────
bot = Bot(token=BOT_TOKEN)
dp  = Dispatcher(storage=MemoryStorage())
db  = Database()


# ══════════════════════════════════════════════════════════════════════════════════
#  ШАГ 1-4: Сбор данных пользователя
# ══════════════════════════════════════════════════════════════════════════════════

@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()

    await db.upsert_user(
        user_id=message.from_user.id,
        username=message.from_user.username,
        full_name=message.from_user.full_name,
    )

    await message.answer(
        "👋 Привет! Я — твой персональный фитнес-тренер.\n\n"
        "Составлю индивидуальную программу тренировок специально под тебя.\n\n"
        "Для начала ответь на 4 вопроса. Начнём!\n\n"
        "📅 <b>Сколько тебе лет?</b>",
        parse_mode="HTML"
    )
    await state.set_state(UserForm.age)


@dp.message(UserForm.age)
async def process_age(message: types.Message, state: FSMContext):
    if not message.text.isdigit() or not (5 <= int(message.text) <= 100):
        await message.answer("⚠️ Введи корректный возраст (число от 5 до 100):")
        return
    await state.update_data(age=int(message.text))
    await message.answer("📏 <b>Твой рост (в см)?</b>", parse_mode="HTML")
    await state.set_state(UserForm.height)


@dp.message(UserForm.height)
async def process_height(message: types.Message, state: FSMContext):
    if not message.text.isdigit() or not (100 <= int(message.text) <= 250):
        await message.answer("⚠️ Введи корректный рост (от 100 до 250 см):")
        return
    await state.update_data(height=int(message.text))
    await message.answer("⚖️ <b>Твой вес (в кг)?</b>", parse_mode="HTML")
    await state.set_state(UserForm.weight)


@dp.message(UserForm.weight)
async def process_weight(message: types.Message, state: FSMContext):
    try:
        weight = float(message.text.replace(",", "."))
        assert 20 <= weight <= 300
    except (ValueError, AssertionError):
        await message.answer("⚠️ Введи корректный вес (от 20 до 300 кг):")
        return

    await state.update_data(weight=weight)

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏋️ Набор мышечной массы",   callback_data="goal_muscle")],
        [InlineKeyboardButton(text="🔥 Похудение",              callback_data="goal_weight_loss")],
        [InlineKeyboardButton(text="💪 Поддержание формы",      callback_data="goal_maintenance")],
        [InlineKeyboardButton(text="🏃 Улучшение выносливости", callback_data="goal_endurance")],
    ])
    await message.answer("🎯 <b>Какова твоя цель?</b>", reply_markup=keyboard, parse_mode="HTML")
    await state.set_state(UserForm.goal)


# ══════════════════════════════════════════════════════════════════════════════════
#  ШАГ 5: Создание заказа и отправка инвойса Telegram Stars
# ══════════════════════════════════════════════════════════════════════════════════

@dp.callback_query(UserForm.goal, F.data.startswith("goal_"))
async def process_goal(callback: types.CallbackQuery, state: FSMContext):
    goal_map = {
        "goal_muscle":      "Набор мышечной массы",
        "goal_weight_loss": "Похудение",
        "goal_maintenance": "Поддержание формы",
        "goal_endurance":   "Улучшение выносливости",
    }
    goal = goal_map[callback.data]
    data = await state.get_data()
    await state.clear()

    # ─── Сохраняем заказ в БД (статус: pending) ────────────────────────────────
    order_id = await db.create_order(
        user_id=callback.from_user.id,
        age=data["age"],
        height=data["height"],
        weight=data["weight"],
        goal=goal,
        amount=PRICE_IN_STARS,
        currency="XTR",   # XTR = официальный код Telegram Stars
    )

    await callback.message.edit_text(
        f"✅ <b>Отлично! Твои данные записаны:</b>\n\n"
        f"• Возраст: {data['age']} лет\n"
        f"• Рост: {data['height']} см\n"
        f"• Вес: {data['weight']} кг\n"
        f"• Цель: {goal}\n\n"
        f"⏳ Отправляю счёт на оплату...",
        parse_mode="HTML"
    )

    # ─── Отправляем РЕАЛЬНЫЙ инвойс Telegram Stars ─────────────────────────────
    # Никакого redirect, никакого внешнего сайта —
    # окно оплаты открывается прямо внутри Telegram!
    await bot.send_invoice(
        chat_id=callback.from_user.id,
        title="🏋️ Персональная программа тренировок",
        description=(
            f"Индивидуальный план на 4 недели\n"
            f"Цель: {goal}\n"
            f"Составлен специально под твои параметры"
        ),
        payload=str(order_id),   # вернётся в successful_payment
        currency="XTR",          # XTR = Telegram Stars
        prices=[
            LabeledPrice(
                label="Программа тренировок",
                amount=PRICE_IN_STARS
            )
        ],
    )


# ══════════════════════════════════════════════════════════════════════════════════
#  ШАГ 6: Pre-checkout — Telegram требует ответа в течение 10 секунд!
# ══════════════════════════════════════════════════════════════════════════════════

@dp.pre_checkout_query()
async def pre_checkout(query: types.PreCheckoutQuery):
    """
    Telegram отправляет этот запрос ПЕРЕД списанием Stars.
    Нужно ответить ok=True в течение 10 секунд.
    Здесь проверяем что заказ актуален.
    """
    order_id = int(query.invoice_payload)
    order = await db.get_order(order_id)

    if not order:
        await query.answer(ok=False, error_message="Заказ не найден. Начни заново: /start")
        return

    if order["status"] == "paid":
        await query.answer(ok=False, error_message="Этот заказ уже оплачен!")
        return

    # Всё ок — разрешаем списание Stars
    await query.answer(ok=True)
    logger.info(f"Pre-checkout OK for order {order_id}")


# ══════════════════════════════════════════════════════════════════════════════════
#  ШАГ 7: Оплата прошла — Stars списаны, выдаём программу автоматически!
# ══════════════════════════════════════════════════════════════════════════════════

@dp.message(F.successful_payment)
async def payment_received(message: types.Message):
    """
    Вызывается АВТОМАТИЧЕСКИ после успешной оплаты.
    Никакого webhook, ngrok или внешнего сервера не нужно —
    всё работает через Telegram напрямую.
    """
    payment = message.successful_payment
    order_id = int(payment.invoice_payload)

    logger.info(
        f"PAYMENT RECEIVED: order={order_id} "
        f"stars={payment.total_amount} "
        f"charge_id={payment.telegram_payment_charge_id}"
    )

    # ─── 1. Обновляем статус заказа ────────────────────────────────────────────
    await db.mark_order_paid(
        order_id=order_id,
        telegram_charge_id=payment.telegram_payment_charge_id
    )

    # ─── 2. Подтверждаем оплату пользователю ───────────────────────────────────
    await message.answer(
        f"🎉 <b>Оплата прошла успешно!</b>\n\n"
        f"Получено: <b>{payment.total_amount} ⭐️</b>\n\n"
        f"⏳ Генерирую твою персональную программу...\n"
        f"Это займёт несколько секунд.",
        parse_mode="HTML"
    )

    # ─── 3. Генерируем программу тренировок ────────────────────────────────────
    order = await db.get_order(order_id)

    try:
        plan = await generate_workout_plan(
            age=order["age"],
            height=order["height"],
            weight=order["weight"],
            goal=order["goal"],
        )

        await message.answer(
            f"🏋️ <b>ТВОЯ ПЕРСОНАЛЬНАЯ ПРОГРАММА ТРЕНИРОВОК</b>\n\n{plan}",
            parse_mode="HTML"
        )

        await db.mark_plan_sent(order_id)
        logger.info(f"Plan sent for order {order_id}")

    except Exception as e:
        logger.error(f"Error generating plan for order {order_id}: {e}")
        await message.answer(
            "⚠️ Ошибка при генерации программы.\n"
            "Напиши нам — вышлем вручную: @support"
        )


# ══════════════════════════════════════════════════════════════════════════════════
#  ДОПОЛНИТЕЛЬНЫЕ КОМАНДЫ
# ══════════════════════════════════════════════════════════════════════════════════

@dp.message(F.text == "/myorders")
async def cmd_myorders(message: types.Message):
    orders = await db.get_user_orders(message.from_user.id)
    if not orders:
        await message.answer("У тебя пока нет заказов. Начни с /start")
        return

    text = "📋 <b>Твои заказы:</b>\n\n"
    for o in orders[-5:]:
        emoji = "✅" if o["status"] == "paid" else "⏳"
        text += f"{emoji} #{o['id']} — {o['goal']} — {o['status']}\n"

    await message.answer(text, parse_mode="HTML")


@dp.message(F.text == "/help")
async def cmd_help(message: types.Message):
    await message.answer(
        "ℹ️ <b>Команды бота:</b>\n\n"
        "/start — начать и получить программу\n"
        "/myorders — мои заказы\n"
        "/help — справка\n\n"
        "💳 Оплата через Telegram Stars — безопасно и мгновенно.",
        parse_mode="HTML"
    )


# ══════════════════════════════════════════════════════════════════════════════════
#  ЗАПУСК
# ══════════════════════════════════════════════════════════════════════════════════

async def main():
    await db.init()
    logger.info("Bot started with Telegram Stars payment")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
