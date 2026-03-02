import asyncio
import json
import os
from typing import Dict

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import CommandStart
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    FSInputFile,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

TOKEN = os.getenv("8794517675:AAF1fTbFwwzK2cJe-pvU7floH5FmOdI9TPs")
SUPPORT_CHAT_ID = -5255685384

CHANNEL_USERNAME = "@techno_recept"
CHANNEL_URL = "https://t.me/techno_recept"
SHOP_URL = "https://market.yandex.ru/business--tekhno-olimp/176784099"
PROMO_CODE = "W39AMMMC"

DB_PATH = "forward_map.json"

if not TOKEN:
    raise RuntimeError("TOKEN not found in Railway Variables")

bot = Bot(TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

# ================== БАЗА ==================

def load_db() -> Dict[str, int]:
    if not os.path.exists(DB_PATH):
        return {}
    with open(DB_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def save_db(db: Dict[str, int]):
    with open(DB_PATH, "w", encoding="utf-8") as f:
        json.dump(db, f)

FORWARD_MAP = load_db()

# ================== FSM ==================

class SupportFlow(StatesGroup):
    waiting_message = State()

# ================== КНОПКИ ==================

def kb_main():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🛒 Наши товары", callback_data="shop"),
            InlineKeyboardButton(text="🍗 Книга рецептов", callback_data="recipes"),
        ],
        [
            InlineKeyboardButton(text="🎁 Промокод -5%", callback_data="promo"),
            InlineKeyboardButton(text="📘 Памятка", callback_data="memo"),
        ],
        [
            InlineKeyboardButton(text="🆘 Поддержка", callback_data="support"),
        ],
    ])

# ================== START ==================

@dp.message(CommandStart())
async def start(m: Message):
    photo = FSInputFile("welcome.png")
    await m.answer_photo(
        photo=photo,
        caption="🤖 <b>Техно Олимп Бот v2</b>\n\nВыберите раздел ниже 👇",
        reply_markup=kb_main()
    )

# ================== НАШИ ТОВАРЫ ==================

@dp.callback_query(F.data == "shop")
async def shop(c: CallbackQuery):
    photo = FSInputFile("banner_shop.png")
    await c.message.answer_photo(
        photo=photo,
        caption="🛒 <b>Техника для дома и кухни</b>\n\nПерейдите в магазин 👇",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🛍 Открыть магазин", url=SHOP_URL)],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back")]
        ])
    )
    await c.answer()

# ================== РЕЦЕПТЫ ==================

@dp.callback_query(F.data == "recipes")
async def recipes(c: CallbackQuery):
    photo = FSInputFile("banner_recipes.png")
    await c.message.answer_photo(
        photo=photo,
        caption="🍗 <b>Книга рецептов для аэрогриля</b>\n\nПодписывайтесь 👇",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📲 Открыть канал", url=CHANNEL_URL)],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back")]
        ])
    )
    await c.answer()

# ================== ПРОМО ==================

@dp.callback_query(F.data == "promo")
async def promo(c: CallbackQuery):
    photo = FSInputFile("banner_promo.png")
    await c.message.answer_photo(
        photo=photo,
        caption="🎁 <b>Получите скидку -5%</b>\n\nПодпишитесь и нажмите «Я подписался» 👇",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📲 Подписаться", url=CHANNEL_URL)],
            [InlineKeyboardButton(text="✅ Я подписался", callback_data="promo_check")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back")]
        ])
    )
    await c.answer()

@dp.callback_query(F.data == "promo_check")
async def promo_check(c: CallbackQuery):
    member = await bot.get_chat_member(CHANNEL_USERNAME, c.from_user.id)
    if member.status not in ("member", "administrator", "creator"):
        await c.message.answer("❌ Подписка не найдена.")
        await c.answer()
        return

    await c.message.answer(
        f"✅ Ваш персональный промокод:\n<b>{PROMO_CODE}</b>\n\n"
        "⏳ Действует 1 месяц\n"
        "⚠️ Не суммируется с другими промокодами"
    )
    await c.answer()

# ================== ПАМЯТКА ==================

@dp.callback_query(F.data == "memo")
async def memo(c: CallbackQuery):
    photo = FSInputFile("banner_memo.png")
    await c.message.answer_photo(
        photo=photo,
        caption="📘 <b>Памятка по аэрогрилю</b>\n\n"
                "• Не заполняйте чашу более 70%\n"
                "• Прогрейте перед первым использованием\n"
                "• Переворачивайте продукты\n",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🆘 Поддержка", callback_data="support")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back")]
        ])
    )
    await c.answer()

# ================== ПОДДЕРЖКА ==================

@dp.callback_query(F.data == "support")
async def support(c: CallbackQuery, state: FSMContext):
    photo = FSInputFile("banner_support.png")
    await state.set_state(SupportFlow.waiting_message)
    await c.message.answer_photo(
        photo=photo,
        caption="✍️ Напишите сообщение в поддержку.\n\n"
                "Укажите номер заказа и описание проблемы.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back")]
        ])
    )
    await c.answer()

@dp.message(SupportFlow.waiting_message)
async def support_message(m: Message, state: FSMContext):
    header = f"📩 Обращение от {m.from_user.full_name} | id:{m.from_user.id}"
    header_msg = await bot.send_message(SUPPORT_CHAT_ID, header)
    forwarded = await bot.forward_message(SUPPORT_CHAT_ID, m.chat.id, m.message_id)

    FORWARD_MAP[str(header_msg.message_id)] = m.from_user.id
    FORWARD_MAP[str(forwarded.message_id)] = m.from_user.id
    save_db(FORWARD_MAP)

    await m.answer("✅ Сообщение отправлено в поддержку.")
    await state.clear()

# ================== НАЗАД ==================

@dp.callback_query(F.data == "back")
async def back(c: CallbackQuery):
    await c.message.answer("Главное меню:", reply_markup=kb_main())
    await c.answer()

# ================== RUN ==================

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())


