import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote_plus

import aiohttp
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramUnauthorizedError
from aiogram.filters import CommandStart, Command
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
MARKET_BUSINESS_ID = os.getenv("MARKET_BUSINESS_ID")  # "176784099"
API_BASE = "https://api.partner.market.yandex.ru"

# Хиты (ручная настройка, самый стабильный вариант)
HIT_OFFER_IDS = [x.strip() for x in (os.getenv("HIT_OFFER_IDS", "")).split(",") if x.strip()]

# Админ (опционально): только админ видит кнопку "Добавить в хиты"
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))  # поставь свой tg id, чтобы включить админ-кнопку

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "forward_map.json")

WELCOME_IMG = "welcome.png"
MAIN_MENU_IMG = "banner_main.png"

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
    return "https://" + url.lstrip("/")

def store_search_url(query: str) -> str:
    """
    Поиск ВНУТРИ твоего магазина (по businessId), а не общий поиск Маркета.
    """
    bid = MARKET_BUSINESS_ID or "176784099"
    return f"https://market.yandex.ru/search?text={quote_plus(query)}&businessId={bid}"

# ================== КАТЕГОРИИ (расширено, чтобы не было пусто) ==================
def detect_category(name: str) -> str:
    n = name.lower()

    if any(w in n for w in ["аэрогрил", "air fryer"]):
        return "aerogrill"

    if any(w in n for w in ["пылесос", "vacuum"]):
        return "vacuum"

    if any(w in n for w in [
        "пароочист", "пароочиститель", "пароген", "паровая швабра", "парошвабр",
        "steam", "steam mop", "steam cleaner", "отпаривател", "паровой"
    ]):
        return "steam"

    return "other"

CAT_TITLES = {
    "aerogrill": "🍗 Аэрогрили",
    "vacuum": "🧹 Пылесосы",
    "steam": "💨 Пароочистители",
    "other": "📦 Другое",
}

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

def kb_shop_categories() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🍗 Аэрогрили", callback_data="cat:aerogrill")],
        [InlineKeyboardButton(text="🧹 Пылесосы", callback_data="cat:vacuum")],
        [InlineKeyboardButton(text="💨 Пароочистители", callback_data="cat:steam")],
        [InlineKeyboardButton(text="📦 Другое", callback_data="cat:other")],
        [InlineKeyboardButton(text="🔥 Хиты", callback_data="shop_hits")],
        [InlineKeyboardButton(text="🔎 Поиск товара", callback_data="shop_search")],
        [InlineKeyboardButton(text="🛍 Открыть магазин", url=SHOP_URL)],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back")],
    ])

def kb_offer_nav(mode: str, index: int, total: int, url: str, offer_id: str, is_admin: bool) -> InlineKeyboardMarkup:
    prev_i = max(index - 1, 0)
    next_i = min(index + 1, max(total - 1, 0))

    nav_row = []
    if total > 1 and index > 0:
        nav_row.append(InlineKeyboardButton(text="◀️", callback_data=f"shop_show:{mode}:{prev_i}"))
    nav_row.append(InlineKeyboardButton(text=f"{index+1}/{total}", callback_data="noop"))
    if total > 1 and index < total - 1:
        nav_row.append(InlineKeyboardButton(text="▶️", callback_data=f"shop_show:{mode}:{next_i}"))

    rows = [
        [InlineKeyboardButton(text="🛒 Открыть", url=url)],
        nav_row,
    ]

    # Админская кнопка: добавить в хиты (покупателю не показываем)
    if is_admin:
        rows.append([InlineKeyboardButton(text="⭐ Добавить в хиты", callback_data=f"hit_add:{offer_id}")])

    rows.extend([
        [InlineKeyboardButton(text="⬅️ К категориям", callback_data="shop")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back")],
    ])

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

# ================== СЕССИИ ТОВАРОВ (для листания) ==================
USER_SHOP_SESSION: dict[int, dict] = {}

# ================== ЯНДЕКС API ==================
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
    Парсер сделан "живучим", т.к. поля могут отличаться.
    """
    offer = item.get("offer") or item.get("mappedOffer") or {}
    if not isinstance(offer, dict):
        offer = {}

    offer_id = item.get("offerId") or offer.get("offerId") or offer.get("shopSku") or offer.get("id") or ""
    offer_id = str(offer_id).strip()
    if not offer_id:
        return None

    name = offer.get("name") or item.get("name") or f"Товар {offer_id}"

    photo_url = None
    pics = offer.get("pictures") or offer.get("images") or []
    if isinstance(pics, list) and pics:
        p0 = pics[0]
        if isinstance(p0, dict):
            photo_url = p0.get("url") or p0.get("original") or p0.get("preview")
        elif isinstance(p0, str):
            photo_url = p0

    url = None
    urls = offer.get("urls") or []
    if isinstance(urls, list) and urls:
        u0 = urls[0]
        if isinstance(u0, dict):
            url = u0.get("directUrl") or u0.get("url")
        elif isinstance(u0, str):
            url = u0
    if not url:
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

    data = await market_request(
        f"/v2/businesses/{MARKET_BUSINESS_ID}/offer-mappings",
        {"limit": 200}
    )

    result = data.get("result", {})
    raw_items = result.get("offerMappings") or result.get("offerMappingEntries") or []

    offers: List[Offer] = []
    if isinstance(raw_items, list):
        for it in raw_items:
            if isinstance(it, dict):
                o = _parse_offer_item(it)
                if o:
                    offers.append(o)

    uniq: Dict[str, Offer] = {}
    for o in offers:
        uniq[o.offer_id] = o

    offers = list(uniq.values())
    offers.sort(key=lambda x: x.name.lower())

    _OFFERS_CACHE = (now, offers)
    return offers

# ================== ТОВАР: отправка карточки ==================
async def send_offer(msg: Message, offer: Offer, mode: str, index: int, total: int, user_id: int):
    # ссылка либо из API, либо поиск ВНУТРИ магазина
    url = offer.url or store_search_url(offer.name)

    # ID не показываем покупателю
    caption = f"<b>{offer.name}</b>"

    is_admin = (ADMIN_ID != 0 and user_id == ADMIN_ID)
    kb = kb_offer_nav(mode=mode, index=index, total=total, url=url, offer_id=offer.offer_id, is_admin=is_admin)

    if offer.photo_url:
        await msg.answer_photo(photo=offer.photo_url, caption=caption, reply_markup=kb)
    else:
        await msg.answer(text=caption, reply_markup=kb)

# ================== СЛУЖЕБНОЕ ==================
@dp.callback_query(F.data == "noop")
async def noop(c: CallbackQuery):
    await c.answer()

@dp.message(Command("getid"))
async def getid(m: Message):
    await m.answer(f"Ваш id: <code>{m.from_user.id}</code>")

# ================== START ==================
@dp.message(CommandStart())
async def start(m: Message, state: FSMContext):
    await state.clear()
    await show_welcome(m)

# ================== НАВИГАЦИЯ ==================
@dp.callback_query(F.data == "back")
async def back(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await show_main_menu(c.message)
    await c.answer()

# ================== НАШИ ТОВАРЫ ==================
@dp.callback_query(F.data == "shop")
async def shop_menu(c: CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        await c.message.answer_photo(
            photo=photo_file("banner_shop.png"),
            caption="🛒 <b>Наши товары</b>\n\nВыберите категорию или действие 👇",
            reply_markup=kb_shop_categories()
        )
    except Exception:
        await c.message.answer("🛒 <b>Наши товары</b>\n\nВыберите категорию или действие 👇", reply_markup=kb_shop_categories())
    await c.answer()

@dp.callback_query(F.data.startswith("cat:"))
async def shop_category(c: CallbackQuery):
    cat = c.data.split(":", 1)[1]
    try:
        offers = await get_offers()
    except Exception as e:
        await c.message.answer(f"⚠️ Не удалось загрузить товары из Маркета.\n{e}")
        await c.answer()
        return

    filtered = [o for o in offers if detect_category(o.name) == cat]
    if not filtered:
        await c.message.answer("В этой категории пока нет товаров. Попробуйте «Другое» или поиск.")
        await c.answer()
        return

    title = CAT_TITLES.get(cat, "Категория")

    top = filtered[:10]
    lines = "\n".join([f"{i+1}. {o.name}" for i, o in enumerate(top)])

    await c.message.answer(
        f"<b>{title}</b>\n\n<b>Подборка:</b>\n{lines}\n\n"
        f"Найдено: <b>{len(filtered)}</b>\n"
        "Листай карточки ◀️▶️ ниже 👇"
    )

    mode = f"cat_{cat}"
    USER_SHOP_SESSION[c.from_user.id] = {"mode": mode, "offers": filtered}

    await send_offer(c.message, filtered[0], mode=mode, index=0, total=len(filtered), user_id=c.from_user.id)
    await c.answer()

@dp.callback_query(F.data == "shop_hits")
async def shop_hits(c: CallbackQuery):
    try:
        offers = await get_offers()
    except Exception as e:
        await c.message.answer(f"⚠️ Не удалось загрузить товары из Маркета.\n{e}")
        await c.answer()
        return

    if HIT_OFFER_IDS:
        hits = [o for o in offers if o.offer_id in HIT_OFFER_IDS]
    else:
        hits = offers[:10]

    if not hits:
        await c.message.answer("🔥 Хиты пока пустые.")
        await c.answer()
        return

    USER_SHOP_SESSION[c.from_user.id] = {"mode": "hits", "offers": hits}

    if HIT_OFFER_IDS:
        await c.message.answer("🔥 <b>Хиты</b>\n\nЛистай карточки ◀️▶️ ниже 👇")
    else:
        await c.message.answer(
            "🔥 <b>Хиты</b>\n\n"
            "Пока не настроены — показываю 10 товаров. "
            "Если включишь ADMIN_ID, сможешь добавлять хиты кнопкой ⭐."
        )

    await send_offer(c.message, hits[0], mode="hits", index=0, total=len(hits), user_id=c.from_user.id)
    await c.answer()

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
        await m.answer("Ничего не найдено. Попробуйте другое слово.")
        await state.clear()
        return

    USER_SHOP_SESSION[m.from_user.id] = {"mode": "search", "offers": found}
    await state.clear()

    await m.answer(f"Найдено: <b>{len(found)}</b>. Листай карточки ◀️▶️ ниже 👇")
    await send_offer(m, found[0], mode="search", index=0, total=len(found), user_id=m.from_user.id)

@dp.callback_query(F.data.startswith("shop_show:"))
async def shop_show(c: CallbackQuery):
    # shop_show:{mode}:{index}
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

    session = USER_SHOP_SESSION.get(c.from_user.id)
    if not session or session.get("mode") != mode:
        await c.message.answer("Список товаров устарел. Открой «Наши товары» заново.")
        await c.answer()
        return

    offers = session.get("offers", [])
    if not offers:
        await c.message.answer("Список пуст. Открой «Наши товары» заново.")
        await c.answer()
        return

    index = max(0, min(index, len(offers) - 1))
    await send_offer(c.message, offers[index], mode=mode, index=index, total=len(offers), user_id=c.from_user.id)
    await c.answer()

# ================== АДМИН: добавить в хиты ==================
@dp.callback_query(F.data.startswith("hit_add:"))
async def hit_add(c: CallbackQuery):
    if ADMIN_ID == 0 or c.from_user.id != ADMIN_ID:
        await c.answer("Недоступно", show_alert=True)
        return

    offer_id = c.data.split(":", 1)[1].strip()
    if not offer_id:
        await c.answer()
        return

    # сохраняем в hits.json рядом с bot.py (в Railway может сбрасываться при перезапуске)
    # лучше потом перевести на БД/Redis, но для начала работает.
    hits_path = os.path.join(BASE_DIR, "hits.json")
    try:
        if os.path.exists(hits_path):
            with open(hits_path, "r", encoding="utf-8") as f:
                hits = json.load(f)
            if not isinstance(hits, list):
                hits = []
        else:
            hits = []
        if offer_id not in hits:
            hits.append(offer_id)
            with open(hits_path, "w", encoding="utf-8") as f:
                json.dump(hits, f, ensure_ascii=False, indent=2)
        await c.answer("Добавлено в хиты ✅", show_alert=True)
    except Exception:
        logging.exception("Failed to write hits.json")
        await c.answer("Не удалось сохранить (Railway может очищать файлы). Лучше задать HIT_OFFER_IDS.", show_alert=True)

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

    try:
        me = await bot.get_me()
        logging.info("Bot started as @%s (id=%s)", me.username, me.id)
    except TelegramUnauthorizedError:
        logging.error("Invalid TOKEN. Check Railway Variables.")
        raise

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
