import asyncio
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote_plus

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

# ================== BASE / PATHS ==================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ================== ENV / SETTINGS ==================
TOKEN = os.getenv("TOKEN")
if not TOKEN:
    raise RuntimeError("TOKEN not found in Railway Variables")

SUPPORT_CHAT_ID = int(os.getenv("SUPPORT_CHAT_ID", "-5255685384"))

# Канал рецептов
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "@techno_recept")
CHANNEL_URL = os.getenv("CHANNEL_URL", "https://t.me/techno_recept")

# Магазин
SHOP_URL = os.getenv("SHOP_URL", "https://market.yandex.ru/business--tekhno-olimp/176784099")

# Промокод -5% (за канал рецептов)
PROMO_CODE = os.getenv("PROMO_CODE", "W39AMMMC")

# Акционный товар (ваш канал)
SALE_CHANNEL_USERNAME = os.getenv("SALE_CHANNEL_USERNAME", "@techno_Olymp_sale")
SALE_CHANNEL_URL = os.getenv("SALE_CHANNEL_URL", "https://t.me/techno_Olymp_sale")

# Промокод -10% (за акционный канал)
SALE_BONUS_PROMO = os.getenv("SALE_BONUS_PROMO", "ОЛИМП10")

# Яндекс Маркет (Partner API)
MARKET_API_KEY = os.getenv("MARKET_API_KEY")
MARKET_BUSINESS_ID = os.getenv("MARKET_BUSINESS_ID")  # "176784099"
MARKET_CAMPAIGN_ID = os.getenv("MARKET_CAMPAIGN_ID")  # например "131508390"
API_BASE = "https://api.partner.market.yandex.ru"

OFFERS_CACHE_TTL_SEC = int(os.getenv("OFFERS_CACHE_TTL_SEC", "300"))  # 5 минут

# Хиты — ссылки на карточки (Railway Variable HIT_CARD_URLS, по одной ссылке на строку)
_raw_hit_urls = os.getenv("HIT_CARD_URLS", "")
HIT_CARD_URLS: List[str] = []
if _raw_hit_urls.strip():
    parts = re.split(r"[\n,]+", _raw_hit_urls.strip())
    HIT_CARD_URLS = [p.strip() for p in parts if p.strip()]

# ================== FILES ==================
DB_PATH = os.path.join(BASE_DIR, "forward_map.json")

WELCOME_IMG = "welcome.png"
MAIN_MENU_IMG = "banner_main.png"

BANNER_SHOP = "banner_shop.png"
BANNER_RECIPES = "banner_recipes.png"
BANNER_PROMO = "banner_promo.png"
BANNER_MEMO = "banner_memo.png"
BANNER_SUPPORT = "banner_support.png"

# Акционный товар баннеры (положить рядом с bot.py)
BANNER_SALE = "banner_sale.png"
BANNER_SALE_PROMO = "banner_sale_promo.png"

# База для "выдать -10% один раз"
SALE_DB_PATH = os.path.join(BASE_DIR, "sale_bonus_users.json")

bot = Bot(TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

# ================== FSM ==================
class SupportFlow(StatesGroup):
    waiting_message = State()

class ShopSearchFlow(StatesGroup):
    waiting_query = State()

# ================== MODELS ==================
@dataclass
class Offer:
    offer_id: str
    name: str
    photo_url: Optional[str]
    url: Optional[str]

# ================== DB (support forward map) ==================
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

# ================== DB (sale bonus one-time) ==================
def load_sale_db() -> Dict[str, bool]:
    if not os.path.exists(SALE_DB_PATH):
        return {}
    try:
        with open(SALE_DB_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {}
        return {str(k): bool(v) for k, v in data.items()}
    except Exception:
        logging.exception("Failed to read %s", SALE_DB_PATH)
        return {}

def save_sale_db(db: Dict[str, bool]) -> None:
    tmp = SALE_DB_PATH + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(db, f, ensure_ascii=False)
        os.replace(tmp, SALE_DB_PATH)
    except Exception:
        logging.exception("Failed to write %s", SALE_DB_PATH)

SALE_BONUS_USERS = load_sale_db()

# ================== UTILS ==================
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
    """Поиск внутри магазина по businessId."""
    bid = MARKET_BUSINESS_ID or "176784099"
    return f"https://market.yandex.ru/search?text={quote_plus(query)}&businessId={bid}"

# ================== CATEGORY DETECT ==================
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

# ================== KEYBOARDS ==================
def kb_main() -> InlineKeyboardMarkup:
    # Книга рецептов (3-я и выделенная), Поддержка (5-я и выделенная)
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🛒 Товары", callback_data="shop"),
            InlineKeyboardButton(text="⚡ Акции", callback_data="sale"),
        ],
        [
            InlineKeyboardButton(text="🍗 КНИГА РЕЦЕПТОВ", callback_data="recipes"),
        ],
        [
            InlineKeyboardButton(text="🎁 Промокод -5%", callback_data="promo"),
            InlineKeyboardButton(text="📘 Памятка", callback_data="memo"),
        ],
        [
            InlineKeyboardButton(text="💬 ПОДДЕРЖКА", callback_data="support"),
        ],
    ])

def kb_back_to_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back")]
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

def kb_offer_nav(mode: str, index: int, total: int, url: str) -> InlineKeyboardMarkup:
    prev_i = max(index - 1, 0)
    next_i = min(index + 1, max(total - 1, 0))

    nav_row = []
    if total > 1 and index > 0:
        nav_row.append(InlineKeyboardButton(text="◀️", callback_data=f"shop_show:{mode}:{prev_i}"))
    nav_row.append(InlineKeyboardButton(text=f"{index+1}/{total}", callback_data="noop"))
    if total > 1 and index < total - 1:
        nav_row.append(InlineKeyboardButton(text="▶️", callback_data=f"shop_show:{mode}:{next_i}"))

    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 Открыть", url=url)],
        nav_row,
        [InlineKeyboardButton(text="⬅️ К категориям", callback_data="shop")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back")],
    ])

# ================== SCREENS ==================
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

# ================== SHOP SESSION (pagination) ==================
USER_SHOP_SESSION: dict[int, dict] = {}

# ================== MARKET API ==================
_OFFERS_CACHE: Tuple[float, List[Offer]] = (0.0, [])

async def market_post(path: str, body: Dict[str, Any]) -> Dict[str, Any]:
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
    offer = item.get("offer") or item.get("mappedOffer") or {}
    if not isinstance(offer, dict):
        offer = {}

    offer_id = item.get("offerId") or offer.get("offerId") or offer.get("shopSku") or offer.get("id") or ""
    offer_id = str(offer_id).strip()
    if not offer_id:
        return None

    name = offer.get("name") or item.get("name") or "Товар"

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

def _is_offer_in_stock(offer_item: Dict[str, Any]) -> bool:
    params = offer_item.get("offerParams") or offer_item.get("params") or {}
    if not isinstance(params, dict):
        params = {}

    cand = [
        params.get("status"),
        params.get("availability"),
        params.get("stock"),
        offer_item.get("status"),
        offer_item.get("availability"),
    ]
    cand_str = " ".join([str(x).lower() for x in cand if x is not None])

    if any(w in cand_str for w in ["out", "нет", "no", "disabled", "archive", "off", "zero"]):
        return False

    if any(w in cand_str for w in ["ok", "active", "published", "ready", "in_stock", "instock", "available", "on"]):
        return True

    if params.get("published") is True or params.get("hasStock") is True:
        return True

    # по умолчанию — считаем что в наличии, чтобы не «потерять» товары из-за нестабильных полей
    return True

async def get_instock_offer_ids(offer_ids: List[str]) -> set[str]:
    if not MARKET_CAMPAIGN_ID:
        return set(offer_ids)

    instock: set[str] = set()
    CHUNK = 200

    for i in range(0, len(offer_ids), CHUNK):
        chunk = offer_ids[i:i + CHUNK]
        data = await market_post(
            f"/v2/campaigns/{MARKET_CAMPAIGN_ID}/offers",
            {"offerIds": chunk}
        )
        items = (data.get("result") or {}).get("offers") or []
        if isinstance(items, list):
            for it in items:
                oid = str(it.get("offerId", "")).strip()
                if oid and _is_offer_in_stock(it):
                    instock.add(oid)

    return instock

async def get_offers(force: bool = False) -> List[Offer]:
    global _OFFERS_CACHE
    ts, cached = _OFFERS_CACHE
    now = time.time()

    if (not force) and cached and (now - ts) < OFFERS_CACHE_TTL_SEC:
        return cached

    data = await market_post(
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

    uniq: Dict[str, Offer] = {o.offer_id: o for o in offers}
    offers = list(uniq.values())

    # фильтр "только в наличии"
    try:
        ids = [o.offer_id for o in offers]
        instock = await get_instock_offer_ids(ids)
        offers = [o for o in offers if o.offer_id in instock]
    except Exception:
        logging.exception("Failed to filter by stock; showing unfiltered offers")

    offers.sort(key=lambda x: x.name.lower())
    _OFFERS_CACHE = (now, offers)
    return offers

# ================== SEND OFFER CARD ==================
async def send_offer(msg: Message, offer: Offer, mode: str, index: int, total: int):
    url = offer.url or store_search_url(offer.name)
    caption = f"<b>{offer.name}</b>"  # ID не показываем
    kb = kb_offer_nav(mode=mode, index=index, total=total, url=url)

    if offer.photo_url:
        await msg.answer_photo(photo=offer.photo_url, caption=caption, reply_markup=kb)
    else:
        await msg.answer(text=caption, reply_markup=kb)

# ================== HANDLERS ==================
@dp.callback_query(F.data == "noop")
async def noop(c: CallbackQuery):
    await c.answer()

@dp.message(CommandStart())
async def start(m: Message, state: FSMContext):
    await state.clear()
    await show_welcome(m)

@dp.callback_query(F.data == "back")
async def back(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await show_main_menu(c.message)
    await c.answer()

# ================== АКЦИОННЫЙ ТОВАР ==================
@dp.callback_query(F.data == "sale")
async def sale(c: CallbackQuery, state: FSMContext):
    await state.clear()
    text = (
        "⚡ <b>Акционный товар</b>\n\n"
        "Здесь мы публикуем предложения со скидкой:\n"
        "• уценка (царапины / повреждена коробка)\n"
        "• витринные образцы\n"
        "• ограниченные акции\n\n"
        "Подпишитесь на канал и нажмите «✅ Я подписался» — получите <b>-10%</b> (1 раз)."
    )
    try:
        await c.message.answer_photo(
            photo=photo_file(BANNER_SALE),
            caption=text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📲 Открыть канал с акциями", url=SALE_CHANNEL_URL)],
                [InlineKeyboardButton(text="✅ Я подписался", callback_data="sale_check")],
                [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back")],
            ])
        )
    except Exception:
        await c.message.answer(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📲 Открыть канал с акциями", url=SALE_CHANNEL_URL)],
                [InlineKeyboardButton(text="✅ Я подписался", callback_data="sale_check")],
                [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back")],
            ])
        )
    await c.answer()

@dp.callback_query(F.data == "sale_check")
async def sale_check(c: CallbackQuery):
    user_id = str(c.from_user.id)

    # уже выдавали
    if SALE_BONUS_USERS.get(user_id):
        await c.message.answer(
            "✅ Бонус -10% уже был выдан ранее.\n\nКанал с акциями 👇",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📲 Канал с акциями", url=SALE_CHANNEL_URL)],
                [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back")],
            ])
        )
        await c.answer()
        return

    # проверяем подписку (бот должен быть админом канала)
    try:
        member = await bot.get_chat_member(SALE_CHANNEL_USERNAME, c.from_user.id)
        if member.status not in ("member", "administrator", "creator"):
            await c.message.answer(
                "❌ Подписка не найдена.\n\nПодпишитесь на канал и нажмите кнопку ещё раз 👇",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="📲 Открыть канал с акциями", url=SALE_CHANNEL_URL)],
                    [InlineKeyboardButton(text="✅ Я подписался", callback_data="sale_check")],
                    [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back")],
                ])
            )
            await c.answer()
            return
    except Exception:
        await c.message.answer(
            "⚠️ Не удалось проверить подписку.\n\nПопробуйте ещё раз через минуту.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📲 Открыть канал с акциями", url=SALE_CHANNEL_URL)],
                [InlineKeyboardButton(text="✅ Я подписался", callback_data="sale_check")],
                [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back")],
            ])
        )
        await c.answer()
        return

    # фиксируем выдачу один раз
    SALE_BONUS_USERS[user_id] = True
    save_sale_db(SALE_BONUS_USERS)

    # отправляем картинку промокода + текст
    try:
        await c.message.answer_photo(
            photo=photo_file(BANNER_SALE_PROMO),
            caption=(
                "🎉 <b>Поздравляем!</b>\n\n"
                "Ваш промокод на <b>-10%</b>:\n"
                f"<b>{SALE_BONUS_PROMO}</b>\n\n"
                "⏳ Действует 7 дней\n"
                "⚠️ Не суммируется с другими акциями"
            ),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🛒 Перейти в магазин", url=SHOP_URL)],
                [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back")],
            ])
        )
    except Exception:
        await c.message.answer(
            "🎉 <b>Поздравляем!</b>\n\n"
            "Ваш промокод на <b>-10%</b>:\n"
            f"<b>{SALE_BONUS_PROMO}</b>\n\n"
            "⏳ Действует 7 дней\n"
            "⚠️ Не суммируется с другими акциями",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🛒 Перейти в магазин", url=SHOP_URL)],
                [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back")],
            ])
        )

    await c.answer()

# ================== НАШИ ТОВАРЫ ==================
@dp.callback_query(F.data == "shop")
async def shop_menu(c: CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        await c.message.answer_photo(
            photo=photo_file(BANNER_SHOP),
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
        await c.message.answer(f"⚠️ Не удалось загрузить товары.\n{e}")
        await c.answer()
        return

    filtered = [o for o in offers if detect_category(o.name) == cat]
    if not filtered:
        await c.message.answer("В этой категории пока нет товаров в наличии. Попробуйте «Другое» или поиск.")
        await c.answer()
        return

    title = CAT_TITLES.get(cat, "Категория")
    top = filtered[:10]
    lines = "\n".join([f"{i+1}. {o.name}" for i, o in enumerate(top)])

    await c.message.answer(
        f"<b>{title}</b>\n\n<b>Подборка:</b>\n{lines}\n\n"
        f"В наличии: <b>{len(filtered)}</b>\n"
        "Листай карточки ◀️▶️ ниже 👇"
    )

    mode = f"cat_{cat}"
    USER_SHOP_SESSION[c.from_user.id] = {"mode": mode, "offers": filtered}
    await send_offer(c.message, filtered[0], mode=mode, index=0, total=len(filtered))
    await c.answer()

@dp.callback_query(F.data == "shop_hits")
async def shop_hits(c: CallbackQuery):
    if HIT_CARD_URLS:
        rows = [[InlineKeyboardButton(text=f"🔥 Хит {i+1}", url=url)] for i, url in enumerate(HIT_CARD_URLS)]
        rows.append([InlineKeyboardButton(text="⬅️ К категориям", callback_data="shop")])
        rows.append([InlineKeyboardButton(text="🏠 Главное меню", callback_data="back")])

        await c.message.answer("🔥 <b>Хиты</b>\n\nОткрывайте товары по кнопкам 👇")
        await c.message.answer("Выберите хит:", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
        await c.answer()
        return

    try:
        offers = await get_offers()
    except Exception as e:
        await c.message.answer(f"⚠️ Не удалось загрузить товары.\n{e}")
        await c.answer()
        return

    hits = offers[:10]
    if not hits:
        await c.message.answer("🔥 Хиты пока пустые.")
        await c.answer()
        return

    USER_SHOP_SESSION[c.from_user.id] = {"mode": "hits", "offers": hits}
    await c.message.answer("🔥 <b>Хиты</b>\n\nЛистай карточки ◀️▶️ ниже 👇")
    await send_offer(c.message, hits[0], mode="hits", index=0, total=len(hits))
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
        await m.answer(f"⚠️ Не удалось загрузить товары.\n{e}")
        await state.clear()
        return

    q = query.lower()
    found = [o for o in offers if q in o.name.lower()]

    if not found:
        await m.answer("Ничего не найдено среди товаров в наличии. Попробуйте другое слово.")
        await state.clear()
        return

    USER_SHOP_SESSION[m.from_user.id] = {"mode": "search", "offers": found}
    await state.clear()

    await m.answer(f"Найдено: <b>{len(found)}</b>. Листай карточки ◀️▶️ ниже 👇")
    await send_offer(m, found[0], mode="search", index=0, total=len(found))

@dp.callback_query(F.data.startswith("shop_show:"))
async def shop_show(c: CallbackQuery):
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
    await send_offer(c.message, offers[index], mode=mode, index=index, total=len(offers))
    await c.answer()

# ================== КНИГА РЕЦЕПТОВ ==================
@dp.callback_query(F.data == "recipes")
async def recipes(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await c.message.answer_photo(
        photo=photo_file(BANNER_RECIPES),
        caption="🍗 <b>Книга рецептов для аэрогриля</b>\n\nПодписывайтесь 👇",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📲 Открыть канал", url=CHANNEL_URL)],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back")]
        ])
    )
    await c.answer()

# ================== ПРОМО -5% ==================
@dp.callback_query(F.data == "promo")
async def promo(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await c.message.answer_photo(
        photo=photo_file(BANNER_PROMO),
        caption="🎁 <b>Получите скидку -5%</b>\n\nПодпишитесь и нажмите «Я подписался» 👇",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📲 Подписаться", url=CHANNEL_URL)],
            [InlineKeyboardButton(text="✅ Я подписался", callback_data="promo_check")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back")]
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
            "Проверьте, что бот добавлен в канал и попробуйте ещё раз."
        )
        await c.answer()
        return

    await c.message.answer(
        f"✅ Ваш промокод:\n<b>{PROMO_CODE}</b>\n\n"
        "⏳ Действует 1 месяц\n"
        "⚠️ Не суммируется с другими промокодами",
        reply_markup=kb_back_to_menu()
    )
    await c.answer()

# ================== ПАМЯТКА (ПОЛНАЯ) ==================
@dp.callback_query(F.data == "memo")
async def memo(c: CallbackQuery, state: FSMContext):
    await state.clear()
    photo = photo_file(BANNER_MEMO)

    text = (
        "📘 <b>ПАМЯТКА ПО ИСПОЛЬЗОВАНИЮ АЭРОГРИЛЯ</b>\n"
        "<b>и ответы на частые вопросы</b>\n\n"

        "<b>Запах пластика при первом использовании</b>\n"
        "Это нормальное явление и не говорит о неисправности. "
        "Запах со временем исчезает и не влияет на вкус блюд.\n\n"

        "<b>Причины</b>\n"
        "При производстве используются пластмассовые и металлические элементы, "
        "на которых могут оставаться следы заводских смазок или защитных покрытий. "
        "При первом нагревании остатки испаряются — появляется запах.\n\n"

        "<b>Методы устранения</b>\n"
        "1) <b>Подготовить устройство</b>:\n"
        "• Вымойте съёмные элементы (корзину, решётки, поддоны) тёплой водой с мягким средством.\n"
        "• Протрите внутренние поверхности влажной тканью и дайте полностью высохнуть.\n\n"
        "2) <b>Прогреть вхолостую</b>:\n"
        "• 200–220°C на 15–20 минут без продуктов.\n"
        "• Проветрите помещение.\n\n"
        "3) <b>Натуральные средства</b>:\n"
        "• <b>Уксус</b>: вода + 1–2 ст. л. уксуса, 150–170°C ~ 15 минут.\n"
        "• <b>Лимон</b>: дольки лимона в воду, прогреть 10–15 минут.\n\n"

        "Если запах не исчезает после нескольких циклов — возможен заводской брак. "
        "В таком случае лучше обратиться в сервис.\n\n"

        "<b>Правила эксплуатации</b>\n"
        "• Не заполняйте чашу более чем на 70% — воздух должен циркулировать.\n"
        "• Используйте решётку для равномерного приготовления.\n"
        "• Переворачивайте/перемешивайте плотные продукты при долгой готовке.\n"
        "• Проверяйте готовность до выключения (снаружи может быть готово, внутри — нет).\n\n"

        "<b>Режимы</b>\n"
        "Есть автоматические программы или ручной режим — можно задать температуру и время самостоятельно."
    )

    await c.message.answer_photo(
        photo=photo,
        caption=text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💬 Поддержка", callback_data="support")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back")]
        ])
    )
    await c.answer()

# ================== ПОДДЕРЖКА (НОВЫЙ ТЕКСТ + ОТВЕТЫ НАЗАД) ==================
@dp.callback_query(F.data == "support")
async def support(c: CallbackQuery, state: FSMContext):
    await state.set_state(SupportFlow.waiting_message)
    await c.message.answer_photo(
        photo=photo_file(BANNER_SUPPORT),
        caption=(
            "✍️ <b>Обращение в поддержку</b>\n\n"
            "Для обращения укажите:\n"
            "• номер заказа\n"
            "• описание проблемы/вопроса\n"
            "• фото/видео\n\n"
            "⏳ <b>Примерное время ответа:</b> ~ 5 часов"
        ),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back")]
        ])
    )
    await c.answer()

@dp.message(SupportFlow.waiting_message)
async def support_message(m: Message, state: FSMContext):
    header = f"📩 Обращение от {m.from_user.full_name} | id:{m.from_user.id}"
    header_msg = await bot.send_message(SUPPORT_CHAT_ID, header)

    # copy_message — стабильнее для медиа, чем forward_message
    copied = await bot.copy_message(
        chat_id=SUPPORT_CHAT_ID,
        from_chat_id=m.chat.id,
        message_id=m.message_id
    )

    # привязка: если оператор ответит реплаем на header или на copied — бот поймет кому отвечать
    FORWARD_MAP[str(header_msg.message_id)] = m.from_user.id
    FORWARD_MAP[str(copied.message_id)] = m.from_user.id
    save_db(FORWARD_MAP)

    await m.answer("✅ Сообщение отправлено в поддержку. Мы ответим сюда же.", reply_markup=kb_back_to_menu())
    await state.clear()

# Операторы отвечают пользователю реплаем в SUPPORT_CHAT_ID
@dp.message(F.chat.id == SUPPORT_CHAT_ID, F.reply_to_message)
async def support_reply_to_user(m: Message):
    replied_id = str(m.reply_to_message.message_id)
    user_id = FORWARD_MAP.get(replied_id)
    if not user_id:
        return

    try:
        await bot.copy_message(
            chat_id=user_id,
            from_chat_id=m.chat.id,
            message_id=m.message_id
        )
    except Exception:
        # пользователь мог заблокировать бота или закрыть ЛС
        return

# ================== RUN ==================
async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    # На Railway используем polling — webhook чистим
    await bot.delete_webhook(drop_pending_updates=True)

    try:
        me = await bot.get_me()
        logging.info("Bot started as @%s (id=%s)", me.username, me.id)
    except TelegramUnauthorizedError:
        logging.error("Invalid TOKEN. Check Railway Variables.")
        raise

    if not MARKET_API_KEY or not MARKET_BUSINESS_ID:
        logging.warning("Market API env not set: MARKET_API_KEY / MARKET_BUSINESS_ID")
    if not MARKET_CAMPAIGN_ID:
        logging.warning("MARKET_CAMPAIGN_ID not set -> stock filter may be weaker")

    await dp.start_polling(
        bot,
        allowed_updates=dp.resolve_used_update_types(),
        polling_timeout=30,
        close_bot_session=True,
    )

if __name__ == "__main__":
    asyncio.run(main())
