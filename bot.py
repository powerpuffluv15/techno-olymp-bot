import asyncio
import json
import os
from typing import Dict

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

# ===================== НАСТРОЙКИ =====================
TOKEN = "8794517675:AAF1fTbFwwzK2cJe-pvU7floH5FmOdI9TPs"
SUPPORT_CHAT_ID = -5255685384  # chat_id твоей группы поддержки

CHANNEL_USERNAME = "@techno_recept"
CHANNEL_URL = "https://t.me/techno_recept"

SHOP_URL = "https://market.yandex.ru/business--tekhno-olimp/176784099"

PROMO_CODE = "W39AMMMC"
PROMO_TEXT = (
    f"✅ <b>Подписка подтверждена!</b>\n\n"
    f"Ваш персональный промокод:\n<b>{PROMO_CODE}</b>\n\n"
    "Скидка 5% на товары магазина <b>Техно Олимп</b> на Яндекс Маркете.\n"
    "⏳ Действует 1 месяц\n"
    "⚠️ Не суммируется с другими промокодами"
)

DB_PATH = "forward_map.json"  # чтобы Reply работал даже после перезапуска
# =====================================================

# =============== ССЫЛКИ НА ХИТЫ (3 позиции) ===========
HIT_AEROGRILL = "https://market.yandex.ru/card/aerogril-elektricheskiy-8-litrov-dlya-doma-s-reshetkoy-moshchnost-2000vt/5074928950"
HIT_STEAM = "https://market.yandex.ru/card/paroochistitel-dlya-uborki-doma-moshchnyy/4416657303"
HIT_VACUUM = "https://market.yandex.ru/card/pylesos-dlya-doma-s-konteynerom-3l-3000-vt-bytovoy-provodnoy-krasnyy/103639696941"
# ======================================================


# =================== DB: message_id -> user_id ===================
def load_db() -> Dict[str, int]:
    if not os.path.exists(DB_PATH):
        return {}
    try:
        with open(DB_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {str(k): int(v) for k, v in data.items()}
    except Exception:
        return {}


def save_db(db: Dict[str, int]) -> None:
    with open(DB_PATH, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)


FORWARD_MAP: Dict[str, int] = load_db()
# =================================================================


# ========================== FSM ==========================
class SupportFlow(StatesGroup):
    waiting_message = State()
# ========================================================


bot = Bot(
    TOKEN,
    default=DefaultBotProperties(parse_mode="HTML")
)
dp = Dispatcher()


# ====================== КЛАВИАТУРЫ ======================
def kb_main() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 Наши товары", callback_data="shop")],
        [InlineKeyboardButton(text="🍗 Рецепты для аэрогриля", callback_data="recipes")],
        [InlineKeyboardButton(text="🎁 Получить промокод -5%", callback_data="promo")],
        [InlineKeyboardButton(text="📘 Памятка по аэрогрилю", callback_data="memo")],
        [InlineKeyboardButton(text="🆘 Обращение в поддержку", callback_data="support")],
    ])


def kb_shop() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔥 Хиты продаж", callback_data="hits")],
        [InlineKeyboardButton(text="🍗 Аэрогрили", callback_data="cat_aerogrill")],
        [InlineKeyboardButton(text="🧹 Пылесосы", callback_data="cat_vacuum")],
        [InlineKeyboardButton(text="💨 Пароочистители", callback_data="cat_steam")],
        [InlineKeyboardButton(text="🍴 Кухонная техника", url=SHOP_URL)],
        [InlineKeyboardButton(text="🌿 Садовая техника", url=SHOP_URL)],
        [InlineKeyboardButton(text="🛍 Весь ассортимент магазина", url=SHOP_URL)],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_main")],
    ])


def kb_hits() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🍗 Аэрогриль 8 л (2000 Вт)", callback_data="hit_aerogrill")],
        [InlineKeyboardButton(text="💨 Пароочиститель мощный", callback_data="hit_steam")],
        [InlineKeyboardButton(text="🧹 Пылесос с контейнером 3 л", callback_data="hit_vacuum")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="shop")],
    ])


def kb_hit_item(url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 Смотреть на Яндекс Маркете", url=url)],
        [InlineKeyboardButton(text="🎁 Получить промокод -5%", callback_data="promo")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="hits")],
    ])


def kb_recipes() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📲 Открыть канал", url=CHANNEL_URL)],
        [InlineKeyboardButton(text="🎁 Получить промокод -5%", callback_data="promo")],
        [InlineKeyboardButton(text="📘 Памятка по аэрогрилю", callback_data="memo")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_main")],
    ])


def kb_promo_step1() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📲 Подписаться на канал", url=CHANNEL_URL)],
        [InlineKeyboardButton(text="✅ Я подписался", callback_data="promo_check")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_main")],
    ])


def kb_promo_given() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 Перейти в магазин", url=SHOP_URL)],
        [InlineKeyboardButton(text="🔥 Хиты продаж", callback_data="hits")],
        [InlineKeyboardButton(text="◀️ Главная", callback_data="back_main")],
    ])


def kb_memo() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🆘 Обращение в поддержку", callback_data="support")],
        [InlineKeyboardButton(text="🍗 Смотреть рецепты", callback_data="recipes")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_main")],
    ])


def kb_support_topics() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📦 Доставка / комплектация", callback_data="spt_delivery")],
        [InlineKeyboardButton(text="🔧 Неисправность / брак", callback_data="spt_defect")],
        [InlineKeyboardButton(text="🔁 Возврат / обмен", callback_data="spt_return")],
        [InlineKeyboardButton(text="💬 Другое (вопрос перед покупкой)", callback_data="spt_other")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_main")],
    ])


def kb_support_write(back_to: str = "support") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✍️ Написать", callback_data="spt_write")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data=back_to)],
    ])


def kb_support_other() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✍️ Задать вопрос", callback_data="spt_write")],
        [InlineKeyboardButton(text="🎁 Получить промокод -5%", callback_data="promo")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="support")],
    ])
# ======================================================


# ====================== КОМАНДЫ =======================
@dp.message(CommandStart())
async def cmd_start(m: Message, state: FSMContext):
    await state.clear()
    await m.answer(
        "Добро пожаловать в <b>Техно Олимп</b> 🤖\n\n"
        "Выберите раздел:",
        reply_markup=kb_main()
    )


@dp.message(Command("cancel"))
async def cmd_cancel(m: Message, state: FSMContext):
    await state.clear()
    await m.answer("Ок, отменил. Главное меню:", reply_markup=kb_main())


@dp.message(Command("getid"))
async def cmd_getid(m: Message):
    await m.answer(f"chat_id: {m.chat.id}")
# ======================================================


# ====================== НАВИГАЦИЯ ======================
@dp.callback_query(F.data == "back_main")
async def cb_back_main(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await c.message.answer("Главное меню:", reply_markup=kb_main())
    await c.answer()
# ======================================================


# ====================== НАШИ ТОВАРЫ ===================
@dp.callback_query(F.data == "shop")
async def cb_shop(c: CallbackQuery):
    await c.message.answer(
        "🛒 <b>Наши товары — Техно Олимп</b>\n\n"
        "Выберите категорию 👇",
        reply_markup=kb_shop()
    )
    await c.answer()


@dp.callback_query(F.data == "hits")
async def cb_hits(c: CallbackQuery):
    await c.message.answer(
        "🔥 <b>Хиты продаж</b>\n"
        "3 самых популярных товара 👇",
        reply_markup=kb_hits()
    )
    await c.answer()


@dp.callback_query(F.data == "hit_aerogrill")
async def cb_hit_aerogrill(c: CallbackQuery):
    await c.message.answer(
        "🍗 <b>Аэрогриль 8 л (2000 Вт)</b>\n"
        "• Для семьи 4–6 человек\n"
        "• Готовит без масла, хрустящая корочка\n"
        "• Съёмная чаша + решётка",
        reply_markup=kb_hit_item(HIT_AEROGRILL)
    )
    await c.answer()


@dp.callback_query(F.data == "hit_steam")
async def cb_hit_steam(c: CallbackQuery):
    await c.message.answer(
        "💨 <b>Пароочиститель для дома</b>\n"
        "• Уборка без химии\n"
        "• Помогает убрать жир и налёт\n"
        "• Для швов, углов и трудных мест",
        reply_markup=kb_hit_item(HIT_STEAM)
    )
    await c.answer()


@dp.callback_query(F.data == "hit_vacuum")
async def cb_hit_vacuum(c: CallbackQuery):
    await c.message.answer(
        "🧹 <b>Пылесос с контейнером 3 л</b>\n"
        "• Без мешков — контейнер удобно очищать\n"
        "• Для ковров и твёрдых покрытий\n"
        "• На каждый день",
        reply_markup=kb_hit_item(HIT_VACUUM)
    )
    await c.answer()


@dp.callback_query(F.data.in_(["cat_aerogrill", "cat_vacuum", "cat_steam"]))
async def cb_categories(c: CallbackQuery):
    if c.data == "cat_aerogrill":
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🍗 Хит: 8 л (2000 Вт)", callback_data="hit_aerogrill")],
            [InlineKeyboardButton(text="🛍 Весь ассортимент", url=SHOP_URL)],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="shop")],
        ])
        await c.message.answer("🍗 <b>Аэрогрили</b>\nПодборка популярных вариантов 👇", reply_markup=kb)

    if c.data == "cat_vacuum":
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🧹 Хит: контейнер 3 л", callback_data="hit_vacuum")],
            [InlineKeyboardButton(text="🛍 Весь ассортимент", url=SHOP_URL)],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="shop")],
        ])
        await c.message.answer("🧹 <b>Пылесосы</b>\nПодборка популярных вариантов 👇", reply_markup=kb)

    if c.data == "cat_steam":
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💨 Хит: пароочиститель", callback_data="hit_steam")],
            [InlineKeyboardButton(text="🛍 Весь ассортимент", url=SHOP_URL)],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="shop")],
        ])
        await c.message.answer("💨 <b>Пароочистители</b>\nПодборка популярных вариантов 👇", reply_markup=kb)

    await c.answer()
# ======================================================


# ====================== РЕЦЕПТЫ =======================
@dp.callback_query(F.data == "recipes")
async def cb_recipes(c: CallbackQuery):
    await c.message.answer(
        "🍗 <b>Рецепты для аэрогриля — Techno Рецепт</b>\n\n"
        "Простые рецепты с температурой и временем приготовления.\n\n"
        "Подпишитесь на канал и получите персональный промокод -5% на товары магазина <b>Техно Олимп</b> 👇",
        reply_markup=kb_recipes()
    )
    await c.answer()
# ======================================================


# ====================== ПРОМОКОД (проверка) ===========
@dp.callback_query(F.data == "promo")
async def cb_promo(c: CallbackQuery):
    await c.message.answer(
        "🎁 <b>Персональная скидка -5%</b>\n\n"
        "Подпишитесь на канал и нажмите «Я подписался» 👇",
        reply_markup=kb_promo_step1()
    )
    await c.answer()


async def is_subscribed(user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(CHANNEL_USERNAME, user_id)
        return member.status in ("creator", "administrator", "member", "restricted")
    except Exception:
        return False


@dp.callback_query(F.data == "promo_check")
async def cb_promo_check(c: CallbackQuery):
    if not await is_subscribed(c.from_user.id):
        await c.message.answer(
            "❌ Подписка не найдена.\n\n"
            "Пожалуйста, подпишитесь на канал и нажмите «Я подписался» ещё раз 👇",
            reply_markup=kb_promo_step1()
        )
        await c.answer()
        return

    await c.message.answer(PROMO_TEXT, reply_markup=kb_promo_given())
    await c.answer()
# ======================================================


# ====================== ПАМЯТКА =======================
@dp.callback_query(F.data == "memo")
async def cb_memo(c: CallbackQuery):
    await c.message.answer(
        "📘 <b>Памятка по использованию аэрогриля</b>\n\n"
        "🔥 <b>Запах пластика при первом включении — это нормально</b>\n"
        "Это следы заводских смазок/покрытий, со временем исчезает.\n\n"
        "✅ <b>Что сделать:</b>\n"
        "1) Вымойте съёмные элементы\n"
        "2) Протрите внутри влажной тканью и высушите\n"
        "3) Прогрейте 15–20 минут при 200–220°C без продуктов и проветрите помещение\n\n"
        "🍋 Лимон/уксус (по желанию): прогреть 10–15 минут.\n\n"
        "⚙️ <b>Правила:</b>\n"
        "• Не заполняйте чашу более чем на 70%\n"
        "• Воздух должен циркулировать\n"
        "• Переворачивайте/перемешивайте для равномерной готовки\n\n"
        "Если остались вопросы — нажмите «Обращение в поддержку».",
        reply_markup=kb_memo()
    )
    await c.answer()
# ======================================================


# ====================== ПОДДЕРЖКА =====================
TOPIC_LABELS = {
    "spt_delivery": "📦 Доставка / комплектация",
    "spt_defect": "🔧 Неисправность / брак",
    "spt_return": "🔁 Возврат / обмен",
    "spt_other": "💬 Другое (вопрос перед покупкой)",
}

@dp.callback_query(F.data == "support")
async def cb_support(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await c.message.answer(
        "🆘 <b>Обращение в поддержку</b>\n\n"
        "Выберите тему обращения:",
        reply_markup=kb_support_topics()
    )
    await c.answer()


@dp.callback_query(F.data.in_(["spt_delivery", "spt_defect", "spt_return"]))
async def cb_support_order_topics(c: CallbackQuery, state: FSMContext):
    await state.update_data(ticket_topic=c.data)
    await c.message.answer(
        "Чтобы мы быстрее помогли, отправьте одним сообщением:\n\n"
        "1) <b>Номер заказа</b> (Яндекс Маркет / Ozon)\n"
        "2) <b>Описание проблемы</b>\n"
        "3) <b>Фото/видео</b> (если есть)\n\n"
        "После этого нажмите «Написать».",
        reply_markup=kb_support_write()
    )
    await c.answer()


@dp.callback_query(F.data == "spt_other")
async def cb_support_other(c: CallbackQuery, state: FSMContext):
    await state.update_data(ticket_topic=c.data)
    await c.message.answer(
        "💬 <b>Консультация перед покупкой</b>\n\n"
        "Напишите ваш вопрос — поможем подобрать товар.\n"
        "Можно указать: задача / бюджет / для кого.\n\n"
        "Нажмите «Задать вопрос» 👇",
        reply_markup=kb_support_other()
    )
    await c.answer()


@dp.callback_query(F.data == "spt_write")
async def cb_support_write(c: CallbackQuery, state: FSMContext):
    await state.set_state(SupportFlow.waiting_message)
    await c.message.answer(
        "✍️ Напишите сообщение (можно прикрепить фото/видео).\n"
        "Отмена: /cancel"
    )
    await c.answer()


@dp.message(SupportFlow.waiting_message)
async def support_receive(m: Message, state: FSMContext):
    data = await state.get_data()
    topic_key = data.get("ticket_topic", "spt_other")
    topic = TOPIC_LABELS.get(topic_key, "💬 Обращение")

    user = m.from_user
    header = (
        "📩 <b>Новое обращение</b>\n"
        f"Тема: <b>{topic}</b>\n\n"
        f"👤 {user.full_name}\n"
        f"@{user.username or 'нет username'} | id:{user.id}\n\n"
        "Сообщение клиента ниже ⬇️"
    )

    header_msg = await bot.send_message(SUPPORT_CHAT_ID, header)
    forwarded = await bot.forward_message(SUPPORT_CHAT_ID, m.chat.id, m.message_id)

    FORWARD_MAP[str(header_msg.message_id)] = user.id
    FORWARD_MAP[str(forwarded.message_id)] = user.id
    save_db(FORWARD_MAP)

    await m.answer("✅ Обращение отправлено. Оператор ответит вам в этом чате.")
    await state.clear()
# ======================================================


# ========= ОТВЕТЫ ИЗ ГРУППЫ КЛИЕНТУ (Reply) ============
@dp.message(F.chat.id == SUPPORT_CHAT_ID)
async def group_reply_router(m: Message):
    if not m.reply_to_message:
        return

    replied_id = str(m.reply_to_message.message_id)
    user_id = FORWARD_MAP.get(replied_id)
    if not user_id:
        return

    if m.content_type != "text":
        await bot.forward_message(user_id, SUPPORT_CHAT_ID, m.message_id)
        await m.reply("✅ Ответ отправлен клиенту.")
        return

    text = (m.text or "").strip()
    if not text:
        return

    await bot.send_message(user_id, f"💬 <b>Ответ поддержки:</b>\n{text}")
    await m.reply("✅ Ответ отправлен клиенту.")
# ======================================================


async def main():
    print("✅ БОТ ЗАПУЩЕН. Ожидаю сообщения...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    print("🚀 Запуск...")
    asyncio.run(main())