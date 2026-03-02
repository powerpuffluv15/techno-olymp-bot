import asyncio
import json
import logging
import os
from typing import Dict

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramUnauthorizedError
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

# ================== НАСТРОЙКИ ==================
TOKEN = os.getenv("TOKEN")  # Railway Variables
SUPPORT_CHAT_ID = int(os.getenv("SUPPORT_CHAT_ID", "-5255685384"))

CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "@techno_recept")
CHANNEL_URL = os.getenv("CHANNEL_URL", "https://t.me/techno_recept")
SHOP_URL = os.getenv("SHOP_URL", "https://market.yandex.ru/business--tekhno-olimp/176784099")
PROMO_CODE = os.getenv("PROMO_CODE", "W39AMMMC")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "forward_map.json")

WELCOME_IMG = "welcome.png"          # приветствие (/start)
MAIN_MENU_IMG = "banner_main.png"    # главное меню (по кнопке Назад)

if not TOKEN:
    raise RuntimeError("TOKEN not found in Railway Variables")

bot = Bot(TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

# ================== БАЗА (reply map) ==================
def load_db() -> Dict[str, int]:
    if not os.path.exists(DB_PATH):
        return {}
    try:
        with open(DB_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {}
        return {str(k): int(v) for k, v in data.items()}
    except Exception:
        logging.exception("Failed to read %s, starting empty", DB_PATH)
        return {}

def save_db(db: Dict[str, int]) -> None:
    tmp = DB_PATH + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(db, f, ensure_ascii=False)
        os.replace(tmp, DB_PATH)
    except Exception:
        logging.exception("Failed to write %s", DB_PATH)

FORWARD_MAP = load_db()

# ================== FSM ==================
class SupportFlow(StatesGroup):
    waiting_message = State()

# ================== УТИЛИТЫ ==================
def photo_file(filename: str) -> FSInputFile:
    path = os.path.join(BASE_DIR, filename)
    return FSInputFile(path)

# ================== КНОПКИ ==================
def kb_main() -> InlineKeyboardMarkup:
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

def kb_back() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back")]
    ])

# ================== ВЫВОД ЭКРАНОВ ==================
async def show_welcome(m: Message):
    """Приветствие /start"""
    try:
        await m.answer_photo(
            photo=photo_file(WELCOME_IMG),
            caption="🤖 <b>Техно Олимп Бот</b>\n\nВыберите раздел ниже 👇",
            reply_markup=kb_main()
        )
    except Exception:
        # если вдруг картинка не найдется — бот всё равно отвечает
        await m.answer(
            "🤖 <b>Техно Олимп Бот</b>\n\nВыберите раздел ниже 👇",
            reply_markup=kb_main()
        )

async def show_main_menu(msg: Message):
    """Главное меню (banner_main.png)"""
    try:
        await msg.answer_photo(
            photo=photo_file(MAIN_MENU_IMG),
            caption="🏠 <b>Главное меню</b>\n\nВыберите раздел 👇",
            reply_markup=kb_main()
        )
    except Exception:
        await msg.answer(
            "🏠 <b>Главное меню</b>\n\nВыберите раздел 👇",
            reply_markup=kb_main()
        )

# ================== START ==================
@dp.message(CommandStart())
async def start(m: Message, state: FSMContext):
    await state.clear()
    await show_welcome(m)

# ================== НАШИ ТОВАРЫ ==================
@dp.callback_query(F.data == "shop")
async def shop(c: CallbackQuery):
    await c.message.answer_photo(
        photo=photo_file("banner_shop.png"),
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
    await c.message.answer_photo(
        photo=photo_file("banner_recipes.png"),
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
    await c.message.answer_photo(
        photo=photo_file("banner_promo.png"),
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
    try:
        member = await bot.get_chat_member(CHANNEL_USERNAME, c.from_user.id)
        if member.status not in ("member", "administrator", "creator"):
            await c.message.answer("❌ Подписка не найдена. Подпишитесь и попробуйте ещё раз.")
            await c.answer()
            return
    except Exception:
        await c.message.answer(
            "⚠️ Не удалось проверить подписку.\n\n"
            "Проверьте, что бот добавлен в канал (часто нужно дать права админа), и попробуйте ещё раз."
        )
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
    await c.message.answer_photo(
        photo=photo_file("banner_memo.png"),
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
    await state.set_state(SupportFlow.waiting_message)
    await c.message.answer_photo(
        photo=photo_file("banner_support.png"),
        caption="✍️ Напишите сообщение в поддержку.\n\n"
                "Укажите номер заказа и описание проблемы.",
        reply_markup=kb_back()
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

# ================== НАЗАД (ГЛАВНОЕ МЕНЮ С КАРТИНКОЙ) ==================
@dp.callback_query(F.data == "back")
async def back(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await show_main_menu(c.message)
    await c.answer()

# ================== RUN ==================
async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    # важно для polling на Railway
    await bot.delete_webhook(drop_pending_updates=True)

    # проверка токена
    try:
        me = await bot.get_me()
        logging.info("Bot started as @%s (id=%s)", me.username, me.id)
    except TelegramUnauthorizedError:
        logging.error("Invalid TOKEN. Check Railway Variables.")
        raise

    await dp.start_polling(
        bot,
        allowed_updates=dp.resolve_used_update_types(),
        polling_timeout=30,
        close_bot_session=True,
    )

if __name__ == "__main__":
    asyncio.run(main())
