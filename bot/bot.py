```python
import asyncio
import logging
import os
from dotenv import load_dotenv

from aiohttp import web  # ← ДОБАВИЛ

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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
PRICE_IN_STARS = 350


class UserForm(StatesGroup):
    age    = State()
    height = State()
    weight = State()
    goal   = State()


bot = Bot(token=BOT_TOKEN)
dp  = Dispatcher(storage=MemoryStorage())
db  = Database()


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

    order_id = await db.create_order(
        user_id=callback.from_user.id,
        age=data["age"],
        height=data["height"],
        weight=data["weight"],
        goal=goal,
        amount=PRICE_IN_STARS,
        currency="XTR",
    )

    await callback.message.edit_text(
        f"✅ Данные сохранены. Отправляю счёт...",
        parse_mode="HTML"
    )

    await bot.send_invoice(
        chat_id=callback.from_user.id,
        title="Программа",
        description=f"Цель: {goal}",
        payload=str(order_id),
        currency="XTR",
        prices=[LabeledPrice(label="Программа", amount=PRICE_IN_STARS)],
    )


@dp.pre_checkout_query()
async def pre_checkout(query: types.PreCheckoutQuery):
    await query.answer(ok=True)


@dp.message(F.successful_payment)
async def payment_received(message: types.Message):
    order_id = int(message.successful_payment.invoice_payload)

    await db.mark_order_paid(order_id)
    order = await db.get_order(order_id)

    plan = await generate_workout_plan(
        age=order["age"],
        height=order["height"],
        weight=order["weight"],
        goal=order["goal"],
    )

    await message.answer(plan)


# ===== RENDER SERVER (ДОБАВИЛ) =====
async def handle(request):
    return web.Response(text="Bot is running")

async def start_web():
    app = web.Application()
    app.router.add_get('/', handle)

    runner = web.AppRunner(app)
    await runner.setup()

    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()


# ===== ЗАПУСК =====
async def main():
    await db.init()
    logger.info("Bot started")

    asyncio.create_task(start_web())  # ← КЛЮЧЕВОЕ

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
```
