import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import aiohttp
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramUnauthorizedError
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

# ================== НАСТРОЙКИ ==================
TOKEN = os.getenv("TOKEN")
if not TOKEN:
    raise RuntimeError("TOKEN not found in Railway Variables")

SUPPORT_CHAT_ID = int(os.getenv("SUPPORT_CHAT_ID", "-5255685384"))

CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "@techno_recept")
CHANNEL_URL = os.getenv("CHANNEL_URL", "https://t.me/techno_recept")
SHOP_URL = os.getenv("SHOP_URL", "https://market.yandex.ru/business--tekhno-olimp/176784099")
PROMO_CODE = os.getenv("PROMO_CODE", "W39AMMMC")

# Яндекс Маркет (Partner API)
MARKET_API_KEY = os.getenv("MARKET_API_KEY")
MARKET_BUSINESS_ID = os.getenv("MARKET_BUSINESS_ID")  # строка ок
API_BASE = "https://api.partner.market.yandex.ru"

# Хиты (лучше задать руками через env)
# пример: HIT_OFFER_IDS="ag-8l,steam-01,vac-3l"
HIT_OFFER_IDS = [x.strip() for x in (os.getenv("HIT_OFFER_IDS", "")).split(",") if x.strip()]

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "forward_map.json")

WELCOME_IMG = "welcome.png"
MAIN_MENU_IMG = "banner_main.png"

# Кэш офферов (чтобы стабильно и быстро)
OFFERS_CACHE_TTL_SEC = int(os.getenv("OFFERS_CACHE_TTL_SEC", "300"))  # 5 минут

bot = Bot(TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

# ================== FSM ==================
class SupportFlow(StatesGroup):
    waiting_message = State()

class ShopSearchFlow(StatesGroup):
    waiting_query = State()

# ================== МОДЕЛЬ ТОВАРА ==================
@dataclass
class Offer:
    offer_id: str
    name: str
    photo_url: Optional[str]
    url: Optional[str]

# ================== DB (reply map) ==================
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

# ================== УТИЛИТЫ ==================
def photo_file(filename: str) -> FSInputFile:
    return FSInputFile(os.path.join(BASE_DIR, filename))

def safe_https(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    url = url.strip()
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("http://") or url.startswith("https://"):
        return url
    # иногда API может отдавать без схемы
    return "https://" + url.lstrip("/")

# ================== КЛАВИАТУРЫ ==================
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
        [InlineKeyboardButton(text="🆘 Поддержка", callback_data="support")],
    ])

def kb_back() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back")]
    ])

def kb_shop_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔥 Хиты", callback_data="shop_hits")],
        [InlineKeyboardButton(text="🔎 Поиск товара", callback_data="shop_search")],
        [InlineKeyboardButton(text="🛍 Открыть магазин", url=SHOP_URL)],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back")],
    ])

def kb_offer_nav(mode: str, index: int, total: int, url: Optional[str]) -> InlineKeyboardMarkup:
    # mode: "all" | "hits" | "search"
    prev_i = max(index - 1, 0)
    next_i = min(index + 1, max(total - 1, 0))
    row1 = []
    if total > 1 and index > 0:
        row1.append(InlineKeyboardButton(text="◀️", callback_data=f"shop_show:{mode}:{prev_i}"))
    row1.append(InlineKeyboardButton(text=f"{index+1}/{total}", callback_data="noop"))
    if total > 1 and index < total - 1:
        row1.append(InlineKeyboardButton(text="▶️", callback_data=f"shop_show:{mode}:{next_i}"))

    rows = []
    if url:
        rows.append([InlineKeyboardButton(text="🛒 Открыть", url=url)])
    if row1:
        rows.append(row1)
    rows.append([InlineKeyboardButton(text="⬅️ К меню товаров", callback_data="shop")])
    rows.append([InlineKeyboardButton(text="🏠 Главное меню", callback_data="back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

# ================== ЭКРАНЫ ==================
async def show_welcome(m: Message):
    try:
        await m.answer_photo(
            photo=photo_file(WELCOME_IMG),
            caption="🤖 <b>Техно Олимп Бот</b>\n\nВыберите раздел ниже 👇",
            reply_markup=kb_main()
        )
    except Exception:
        await m.answer("🤖 <b>Техно Олимп Бот</b>\n\nВыберите раздел ниже 👇", reply_markup=kb_main())

async def show_main_menu(msg: Message):
    try:
        await msg.answer_photo(
            photo=photo_file(MAIN_MENU_IMG),
            caption="🏠 <b>Главное меню</b>\n\nВыберите раздел 👇",
            reply_markup=kb_main()
        )
    except Exception:
        await msg.answer("🏠 <b>Главное меню</b>\n\nВыберите раздел 👇", reply_markup=kb_main())

# ================== ЯНДЕКС API: загрузка товаров ==================
_OFFERS_CACHE: Tuple[float, List[Offer]] = (0.0, [])

async def market_request(path: str, body: Dict[str, Any]) -> Dict[str, Any]:
    if not MARKET_API_KEY or not MARKET_BUSINESS_ID:
        raise RuntimeError("MARKET_API_KEY / MARKET_BUSINESS_ID not set in Railway Variables")

    headers = {"Api-Key": MARKET_API_KEY, "Content-Type": "application/json"}
    url = f"{API_BASE}{path}"

    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.post(url, json=body, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            data = await resp.json(content_type=None)
            if resp.status >= 400:
                raise RuntimeError(f"Market API error {resp.status}: {data}")
            return data

def _parse_offer_item(item: Dict[str, Any]) -> Optional[Offer]:
    """
    Стараемся быть устойчивыми к разным форматам ответа.
    """
    offer = item.get("offer") or item.get("mappedOffer") or item.get("marketSku") or {}
    if not isinstance(offer, dict):
        offer = {}

    offer_id = (
        item.get("offerId")
        or offer.get("offerId")
        or offer.get("id")
        or offer.get("shopSku")
        or ""
    )
    offer_id = str(offer_id).strip()
    if not offer_id:
        return None

    name = (
        offer.get("name")
        or offer.get("title")
        or item.get("name")
        or f"Товар {offer_id}"
    )

    # pictures может быть list[str] или list[dict]
    photo_url = None
    pics = offer.get("pictures") or offer.get("images") or []
    if isinstance(pics, list) and pics:
        p0 = pics[0]
        if isinstance(p0, dict):
            photo_url = p0.get("url") or p0.get("original") or p0.get("preview")
        elif isinstance(p0, str):
            photo_url = p0

    # urls может быть list[dict] с directUrl, либо строка
    url = None
    urls = offer.get("urls") or []
    if isinstance(urls, list) and urls:
        u0 = urls[0]
        if isinstance(u0, dict):
            url = u0.get("directUrl") or u0.get("url")
        elif isinstance(u0, str):
            url = u0
    if not url:
        # иногда бывает в другом месте
        url = offer.get("url") or item.get("url")

    return Offer(
        offer_id=offer_id,
        name=str(name),
        photo_url=safe_https(photo_url),
        url=safe_https(url),
    )

async def get_offers(force: bool = False) -> List[Offer]:
    global _OFFERS_CACHE
    ts, cached = _OFFERS_CACHE
    now = time.time()

    if (not force) and cached and (now - ts) < OFFERS_CACHE_TTL_SEC:
        return cached

    body = {"limit": 200}  # можно увеличить при необходимости
    data = await market_request(
        f"/v2/businesses/{MARKET_BUSINESS_ID}/offer-mappings",
        body
    )

    # разные ключи у разных версий/ответов
    result = data.get("result", {})
    raw_items = (
        result.get("offerMappings")
        or result.get("offerMappingEntries")
        or result.get("offerMappingEntryList")
        or []
    )

    offers: List[Offer] = []
    if isinstance(raw_items, list):
        for it in raw_items:
            if isinstance(it, dict):
                o = _parse_offer_item(it)
                if o:
                    offers.append(o)

    # уберём дубликаты по offer_id
    uniq: Dict[str, Offer] = {}
    for o in offers:
        uniq[o.offer_id] = o

    offers = list(uniq.values())
    offers.sort(key=lambda x: x.name.lower())

    _OFFERS_CACHE = (now, offers)
    return offers

# ================== START ==================
@dp.message(CommandStart())
async def start(m: Message, state: FSMContext):
    await state.clear()
    await show_welcome(m)

# ================== НАЗАД -> ГЛАВНОЕ МЕНЮ ==================
@dp.callback_query(F.data == "back")
async def back(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await show_main_menu(c.message)
    await c.answer()

@dp.callback_query(F.data == "noop")
async def noop(c: CallbackQuery):
    await c.answer()

# ================== НАШИ ТОВАРЫ (меню) ==================
@dp.callback_query(F.data == "shop")
async def shop_menu(c: CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        await c.message.answer_photo(
            photo=photo_file("banner_shop.png"),
            caption="🛒 <b>Наши товары</b>\n\nВыберите действие 👇",
            reply_markup=kb_shop_menu()
        )
    except Exception:
        await c.message.answer("🛒 <b>Наши товары</b>\n\nВыберите действие 👇", reply_markup=kb_shop_menu())
    await c.answer()

# ------------------ показать конкретный товар ------------------
async def send_offer(msg: Message, offer: Offer, mode: str, index: int, total: int):
    caption = f"<b>{offer.name}</b>\n\nID: <code>{offer.offer_id}</code>"
    kb = kb_offer_nav(mode=mode, index=index, total=total, url=offer.url)

    if offer.photo_url:
        await msg.answer_photo(photo=offer.photo_url, caption=caption, reply_markup=kb)
    else:
        await msg.answer(text=caption, reply_markup=kb)

@dp.callback_query(F.data.startswith("shop_show:"))
async def shop_show(c: CallbackQuery, state: FSMContext):
    # callback: shop_show:{mode}:{index}
    parts = c.data.split(":")
    if len(parts) != 3:
        await c.answer()
        return
    mode = parts[1]
    try:
        index = int(parts[2])
    except ValueError:
        await c.answer()
        return

    data = await state.get_data()
    offers: List[Offer] = data.get("shop_offers", [])
    if not offers:
        await c.message.answer("Список товаров пуст. Откройте «Наши товары» заново.")
        await c.answer()
        return

    index = max(0, min(index, len(offers) - 1))
    await send_offer(c.message, offers[index], mode=mode, index=index, total=len(offers))
    await c.answer()

# ------------------ ХИТЫ ------------------
@dp.callback_query(F.data == "shop_hits")
async def shop_hits(c: CallbackQuery, state: FSMContext):
    try:
        offers = await get_offers()
    except Exception as e:
        await c.message.answer(f"⚠️ Не удалось загрузить товары из Маркета.\n{e}")
        await c.answer()
        return

    if HIT_OFFER_IDS:
        hits = [o for o in offers if o.offer_id in HIT_OFFER_IDS]
    else:
        # если хиты не заданы — берём первые 10 по алфавиту (лучше задать вручную!)
        hits = offers[:10]

    if not hits:
        await c.message.answer("🔥 Хиты пока не настроены. Добавьте HIT_OFFER_IDS в Railway Variables.")
        await c.answer()
        return

    await state.update_data(shop_offers=hits)
    await send_offer(c.message, hits[0], mode="hits", index=0, total=len(hits))
    await c.answer()

# ------------------ ПОИСК ------------------
@dp.callback_query(F.data == "shop_search")
async def shop_search_start(c: CallbackQuery, state: FSMContext):
    await state.set_state(ShopSearchFlow.waiting_query)
    await c.message.answer("🔎 Введите название товара или часть названия (например: «аэрогриль»).")
    await c.answer()

@dp.message(ShopSearchFlow.waiting_query)
async def shop_search_query(m: Message, state: FSMContext):
    query = (m.text or "").strip()
    if len(query) < 2:
        await m.answer("Введите хотя бы 2 символа для поиска.")
        return

    try:
        offers = await get_offers()
    except Exception as e:
        await m.answer(f"⚠️ Не удалось загрузить товары из Маркета.\n{e}")
        await state.clear()
        return

    q = query.lower()
    found = [o for o in offers if q in o.name.lower() or q in o.offer_id.lower()]

    if not found:
        await m.answer("Ничего не найдено. Попробуйте другое слово или откройте «Наши товары».")
        await state.clear()
        return

    await state.update_data(shop_offers=found)
    await state.clear()
    await send_offer(m, found[0], mode="search", index=0, total=len(found))

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
        caption="✍️ Напишите сообщение в поддержку.\n\nУкажите номер заказа и описание проблемы.",
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

# ================== RUN ==================
async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    # важно для polling: убрать возможный webhook
    await bot.delete_webhook(drop_pending_updates=True)

    # проверка токена Telegram
    try:
        me = await bot.get_me()
        logging.info("Bot started as @%s (id=%s)", me.username, me.id)
    except TelegramUnauthorizedError:
        logging.error("Invalid TOKEN. Check Railway Variables.")
        raise

    # optional: проверим наличие market env (чтобы в логах было понятно)
    if not MARKET_API_KEY or not MARKET_BUSINESS_ID:
        logging.warning("Market API env not set: MARKET_API_KEY / MARKET_BUSINESS_ID")

    await dp.start_polling(
        bot,
        allowed_updates=dp.resolve_used_update_types(),
        polling_timeout=30,
        close_bot_session=True,
    )

if __name__ == "__main__":
    asyncio.run(main())
