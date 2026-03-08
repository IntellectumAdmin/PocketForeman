# -*- coding: utf-8 -*-
"""
INTELLECTUM — Pocket Foreman
ЖПР-бот (Журнал производства работ) v4

Функции:
- Отдельный Telegram-бот (TELEGRAM_BOT_TOKEN_ZHPR)
- Умная дата (сегодня / другая дата, пропуски)
- Выбор Раздела (ГПР) по иерархии из structure.txt
- Ввод участка, вида работ, объёмов, людей, техники, комментария
- Генерация ID ЖПР с порядковым номером за день
- Автопогода (OpenWeather) по /weather и колонке "12. Погода"
- Автоподтягивание фото-URL из Notion-базы "INTELLECTUM — Журнал вложений"
  по совпадению Дата + Раздел (ГПР)

Пока БЕЗ:
- редактирования старых записей
- сложной работы с несколькими фото
"""

import os
import json
import logging
from datetime import datetime, date, timedelta
from typing import Dict, Any, List, Tuple, Optional

from dotenv import load_dotenv
import requests

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

# ===== Логи =====
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("zhpr-bot")

# ===== .env =====
load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN_ZHPR", "")
NOTION_TOKEN = os.getenv("NOTION_TOKEN_ZHPR", "")
NOTION_DB_ID = os.getenv("NOTION_DATABASE_ID_ZHPR", "")

if not BOT_TOKEN:
    raise RuntimeError("Нет TELEGRAM_BOT_TOKEN_ZHPR в .env")
if not NOTION_TOKEN or not NOTION_DB_ID:
    raise RuntimeError("Нет NOTION_TOKEN_ZHPR / NOTION_DATABASE_ID_ZHPR в .env")

# ===== Названия свойств Notion (ЖПР) =====
PROP_TITLE       = os.getenv("ZPROP_TITLE", "1. Название записи")
PROP_DATE        = os.getenv("ZPROP_DATE", "2. Дата")
PROP_SECTION     = os.getenv("ZPROP_SECTION", "3. Раздел (ГПР)")
PROP_SUBSECTION  = os.getenv("ZPROP_SUBSECTION", "4. Подраздел / Участок")
PROP_WORKTYPE    = os.getenv("ZPROP_WORKTYPE", "5. Вид работ")
PROP_PLAN        = os.getenv("ZPROP_PLAN", "6. Объём по плану (на день)")
PROP_FACT        = os.getenv("ZPROP_FACT", "7. Объём факт (выполнено)")
PROP_UNIT        = os.getenv("ZPROP_UNIT", "8. Единица измерения")
PROP_WORKERS     = os.getenv("ZPROP_WORKERS", "9. Количество рабочих")
PROP_EQUIP_TYPE  = os.getenv("ZPROP_EQUIP_TYPE", "10. Машины и механизмы (тип)")
PROP_EQUIP_COUNT = os.getenv("ZPROP_EQUIP_COUNT", "11. Машины и механизмы (количество)")
PROP_WEATHER     = os.getenv("ZPROP_WEATHER", "12. Погода")
PROP_RESPONSIBLE = os.getenv("ZPROP_RESPONSIBLE", "13. Ответственный")
PROP_PHOTO       = os.getenv("ZPROP_PHOTO", "14. Фото (URL)")
PROP_COMMENT     = os.getenv("ZPROP_COMMENT", "15. Комментарий")

NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}

# ===== Notion: Журнал вложений (INTELLECTUM — Журнал вложений) =====
# Эти переменные ДОЛЖНЫ быть в .env:
# NOTION_TOKEN_SCHOOL65=...
# NOTION_DATABASE_ID_SCHOOL65=...
ATT_TOKEN = os.getenv("NOTION_TOKEN_SCHOOL65", "")
ATT_DB_ID = os.getenv("NOTION_DATABASE_ID_SCHOOL65", "")

# Названия колонок в журнале вложений (как в твоём скрине)
ATT_PROP_SECTION = "Раздел"
ATT_PROP_FILE    = "Файл / Фото"       # пока не используем, но оставляем на будущее
ATT_PROP_URL     = "Ссылка OneDrive"   # отсюда берём URL
ATT_PROP_DATE    = "Дата"

ATT_HEADERS = None
if ATT_TOKEN and ATT_DB_ID:
    ATT_HEADERS = {
        "Authorization": f"Bearer {ATT_TOKEN}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }
else:
    log.warning("Журнал вложений: NOTION_TOKEN_SCHOOL65/NOTION_DATABASE_ID_SCHOOL65 не заданы, автоподтяжка фото отключена.")

# ===== OpenWeather (автопогода) =====
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY", "")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WEATHER_STORE_FILE = os.path.join(BASE_DIR, "weather_store.json")

def _load_weather_store() -> Dict[str, Any]:
    if not os.path.exists(WEATHER_STORE_FILE):
        return {}
    try:
        with open(WEATHER_STORE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        log.exception("Не удалось прочитать weather_store.json")
        return {}

def _save_weather_store(data: Dict[str, Any]) -> None:
    try:
        with open(WEATHER_STORE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        log.exception("Не удалось сохранить weather_store.json")

def _get_user_location_str(user_id: int) -> Optional[str]:
    data = _load_weather_store()
    return data.get(str(user_id))

def _set_user_location_str(user_id: int, value: Optional[str]) -> None:
    data = _load_weather_store()
    key = str(user_id)
    if value:
        data[key] = value
    elif key in data:
        data.pop(key)
    _save_weather_store(data)

def _fetch_weather_text(location: str) -> Optional[str]:
    """
    location: либо 'Уральск', либо '51.233, 51.383'
    Возвращает строку вида: 'Уральск, 7.0°C, небольшая морось'
    """
    if not OPENWEATHER_API_KEY:
        return None

    params = {
        "appid": OPENWEATHER_API_KEY,
        "units": "metric",
        "lang": "ru",
    }

    loc = location.strip()
    # координаты через запятую
    if "," in loc and any(ch.isdigit() for ch in loc):
        try:
            lat_str, lon_str = [x.strip() for x in loc.split(",", 1)]
            params["lat"] = float(lat_str.replace(" ", ""))
            params["lon"] = float(lon_str.replace(" ", ""))
        except Exception:
            log.warning("Не смог распарсить координаты погоды: %r", loc)
            params["q"] = loc
    else:
        params["q"] = loc

    try:
        r = requests.get(
            "https://api.openweathermap.org/data/2.5/weather",
            params=params,
            timeout=10,
        )
    except Exception:
        log.exception("Ошибка запроса к OpenWeather")
        return None

    if r.status_code != 200:
        log.warning("OpenWeather вернул %s: %s", r.status_code, r.text)
        return None

    try:
        j = r.json()
        temp = j.get("main", {}).get("temp")
        weather_list = j.get("weather", [])
        desc = weather_list[0].get("description") if weather_list else ""
        city_name = j.get("name") or loc
        if temp is None:
            return None
        # Приводим описание к виду "Небольшая морось"
        desc_norm = (desc or "").capitalize()
        return f"{city_name}, {temp:.1f}°C, {desc_norm}"
    except Exception:
        log.exception("Не удалось распарсить ответ OpenWeather")
        return None

# ===== Кнопки =====
BTN_NEW_ENTRY   = "➕ Новая запись ЖПР"
BTN_CANCEL      = "❌ Отмена"
BTN_SAVE        = "✅ Сохранить"
BTN_FIX         = "✏️ Исправить"

BTN_DATE_KEEP   = "✅ Оставить"

BTN_CHOOSE_HERE = "✅ Выбрать здесь"
BTN_BACK        = "⬅ Назад"

FOLDER_ICON     = "📁 "

def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([[BTN_NEW_ENTRY]], resize_keyboard=True)

# ===== Состояния диалога ЖПР =====
(
    ZHPR_DATE,
    ZHPR_SECTION,
    ZHPR_SUBSECTION,
    ZHPR_WORKTYPE,
    ZHPR_PLAN,
    ZHPR_FACT,
    ZHPR_UNIT,
    ZHPR_WORKERS,
    ZHPR_EQUIP_TYPE,
    ZHPR_EQUIP_COUNT,
    ZHPR_COMMENT,
    ZHPR_REVIEW,
) = range(200, 212)

# Состояние небольшого диалога /weather
WEATHER_SETUP = 150

# ===== Структура ГПР из structure.txt =====

class SectionNode:
    def __init__(self, name: str):
        self.name: str = name
        self.children: List["SectionNode"] = []

    def __repr__(self) -> str:
        return f"SectionNode({self.name!r}, children={len(self.children)})"

def load_structure_tree(path: str) -> List[SectionNode]:
    """
    Парсим structure.txt с отступами пробелами (шаг 4 пробела).
    """
    if not os.path.exists(path):
        log.warning("structure.txt не найден: %s", path)
        return []

    roots: List[SectionNode] = []
    stack: List[Tuple[int, SectionNode]] = []

    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.rstrip()
            if not line:
                continue

            indent = len(line) - len(line.lstrip(" "))
            name = line.strip().rstrip("/")

            node = SectionNode(name)

            if not stack:
                roots.append(node)
                stack.append((indent, node))
                continue

            while stack and stack[-1][0] >= indent:
                stack.pop()

            if not stack:
                roots.append(node)
                stack.append((indent, node))
            else:
                parent = stack[-1][1]
                parent.children.append(node)
                stack.append((indent, node))

    log.info("structure.txt загружен, корневых разделов: %d", len(roots))
    return roots

STRUCTURE_FILE = os.path.join(BASE_DIR, "structure.txt")
STRUCTURE_ROOTS: List[SectionNode] = load_structure_tree(STRUCTURE_FILE)

# ===== Вспомогательные функции =====

def _get_next_seq_for_date(date_obj: datetime) -> int:
    """
    Считает, сколько записей ЖПР уже есть в Notion за эту дату,
    и возвращает следующий порядковый номер (1, 2, 3, ...).
    """
    date_str = date_obj.strftime("%Y-%m-%d")

    payload = {
        "filter": {
            "property": PROP_DATE,
            "date": {"equals": date_str},
        }
    }

    try:
        r = requests.post(
            f"https://api.notion.com/v1/databases/{NOTION_DB_ID}/query",
            headers=NOTION_HEADERS,
            json=payload,
            timeout=30,
        )
        if r.status_code != 200:
            log.warning(
                "Не удалось получить список ЖПР за дату %s: %s %s",
                date_str,
                r.status_code,
                r.text,
            )
            return 1

        data = r.json()
        count = len(data.get("results", []))
        return count + 1

    except Exception:
        log.exception("Ошибка при запросе Notion для подсчёта записей за день")
        return 1

def _generate_zhpr_id(date_obj: datetime) -> str:
    """
    ЖПР-ГГГГММДД-XXX, где XXX — порядковый номер записи за день.
    """
    seq = _get_next_seq_for_date(date_obj)
    date_part = date_obj.strftime("%Y%m%d")
    return f"ЖПР-{date_part}-{seq:03d}"

def _chunk_buttons(items: List[str], per_row: int = 2) -> List[List[str]]:
    rows: List[List[str]] = []
    row: List[str] = []
    for item in items:
        row.append(item)
        if len(row) == per_row:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return rows

def _parse_date_str(text: str) -> Optional[date]:
    try:
        dt = datetime.strptime(text, "%d.%m.%Y").date()
        return dt
    except ValueError:
        return None

def _get_last_zhpr_date() -> Optional[date]:
    """
    Берём последнюю дату из Notion по полю PROP_DATE.
    """
    try:
        payload = {
            "page_size": 1,
            "sorts": [
                {
                    "property": PROP_DATE,
                    "direction": "descending",
                }
            ],
        }
        resp = requests.post(
            f"https://api.notion.com/v1/databases/{NOTION_DB_ID}/query",
            headers=NOTION_HEADERS,
            json=payload,
            timeout=20,
        )
        if resp.status_code != 200:
            log.warning("Не удалось получить последнюю дату из Notion: %s", resp.text)
            return None
        data = resp.json()
        results = data.get("results", [])
        if not results:
            return None
        props = results[0]["properties"]
        date_prop = props.get(PROP_DATE, {}).get("date")
        if not date_prop or not date_prop.get("start"):
            return None
        d = datetime.fromisoformat(date_prop["start"]).date()
        return d
    except Exception:
        log.exception("Ошибка при запросе последней даты ЖПР из Notion")
        return None

# ===== Журнал вложений: поиск фото =====

def _find_photo_url_for_entry(date_obj: datetime, section_full: str) -> Optional[str]:
    """
    Ищем первую (последнюю отредактированную) запись в Журнале вложений
    с той же датой и тем же разделом. Берём URL из колонки "Ссылка OneDrive".
    """
    if not (ATT_HEADERS and ATT_DB_ID):
        return None

    date_str = date_obj.strftime("%Y-%m-%d")

    payload: Dict[str, Any] = {
        "filter": {
            "and": [
                {
                    "property": ATT_PROP_DATE,
                    "date": {"equals": date_str},
                },
                {
                    "property": ATT_PROP_SECTION,
                    "select": {"equals": section_full},
                },
            ]
        },
        "page_size": 1,
        "sorts": [
            {
                "timestamp": "last_edited_time",
                "direction": "descending",
            }
        ],
    }

    try:
        r = requests.post(
            f"https://api.notion.com/v1/databases/{ATT_DB_ID}/query",
            headers=ATT_HEADERS,
            json=payload,
            timeout=20,
        )
    except Exception:
        log.exception("Ошибка запроса к Notion (Журнал вложений)")
        return None

    if r.status_code != 200:
        log.warning(
            "Журнал вложений: Notion вернул %s: %s",
            r.status_code,
            r.text,
        )
        return None

    try:
        data = r.json()
        results = data.get("results", [])
        if not results:
            return None
        props = results[0]["properties"]

        url_prop = props.get(ATT_PROP_URL, {})
        url = url_prop.get("url")
        if url:
            return url

        # запасной вариант — попробовать вытащить из "Файл / Фото"
        file_prop = props.get(ATT_PROP_FILE, {})
        files = file_prop.get("files") or []
        if files:
            f0 = files[0]
            if f0.get("type") == "external":
                return f0.get("external", {}).get("url")
            if f0.get("type") == "file":
                return f0.get("file", {}).get("url")

        return None
    except Exception:
        log.exception("Не удалось распарсить ответ Notion (Журнал вложений)")
        return None

# ===== Создание страницы в Notion (ЖПР) =====

async def _create_notion_page_from_context(
    context: ContextTypes.DEFAULT_TYPE,
) -> Tuple[bool, str]:
    """
    Собираем данные из context.user_data["zhpr"] и создаём страницу в Notion.
    Возвращаем (успех, сообщение/ошибка).
    """
    ud = context.user_data.get("zhpr", {})
    if not ud:
        return False, "Нет данных ЖПР в контексте."

    date_obj: datetime = ud.get("date_obj", datetime.now())
    zhpr_id = ud.get("zhpr_id") or _generate_zhpr_id(date_obj)

    # Автофото: если в zhpr нет photo_url, пробуем взять из Журнала вложений
    section_full: Optional[str] = ud.get("section")
    if not ud.get("photo_url") and section_full:
        auto_url = _find_photo_url_for_entry(date_obj, section_full)
        if auto_url:
            ud["photo_url"] = auto_url

    props: Dict[str, Any] = {}

    # Title (ID + краткое описание)
    title_text = zhpr_id
    if ud.get("section"):
        title_text += f" — {ud.get('section')}"
    if ud.get("subsection"):
        title_text += f" / {ud.get('subsection')}"

    props[PROP_TITLE] = {
        "title": [{"text": {"content": title_text}}]
    }

    # Дата
    props[PROP_DATE] = {
        "date": {"start": date_obj.strftime("%Y-%m-%d")}
    }

    # Раздел (Select)
    section = ud.get("section")
    if section:
        props[PROP_SECTION] = {"select": {"name": section}}

    # Подраздел (Text)
    subsection = ud.get("subsection")
    if subsection:
        props[PROP_SUBSECTION] = {
            "rich_text": [{"text": {"content": subsection}}]
        }

    # Вид работ (Select — берём первый)
    worktypes: List[str] = ud.get("worktypes", [])
    if worktypes:
        props[PROP_WORKTYPE] = {"select": {"name": worktypes[0]}}

    # Объёмы
    if ud.get("plan") is not None:
        props[PROP_PLAN] = {"number": ud.get("plan")}
    if ud.get("fact") is not None:
        props[PROP_FACT] = {"number": ud.get("fact")}

    # Ед. измерения
    unit = ud.get("unit")
    if unit:
        props[PROP_UNIT] = {"select": {"name": unit}}

    # Рабочие
    if ud.get("workers") is not None:
        props[PROP_WORKERS] = {"number": ud.get("workers")}

    # Техника (тип) — Select, первый вариант
    equip_types: List[str] = ud.get("equip_types", [])
    if equip_types:
        props[PROP_EQUIP_TYPE] = {"select": {"name": equip_types[0]}}

    # Кол-во техники — текст
    equip_count = ud.get("equip_count")
    if equip_count:
        props[PROP_EQUIP_COUNT] = {
            "rich_text": [{"text": {"content": equip_count}}]
        }

    # Погода
    weather = ud.get("weather") or ""
    if weather:
        props[PROP_WEATHER] = {
            "rich_text": [{"text": {"content": weather}}]
        }

    # Ответственный
    responsible = ud.get("responsible")
    if responsible:
        props[PROP_RESPONSIBLE] = {
            "rich_text": [{"text": {"content": responsible}}]
        }

    # Фото (URL)
    photo_url = ud.get("photo_url")
    if photo_url:
        props[PROP_PHOTO] = {"url": photo_url}

    # Комментарий
    comment = ud.get("comment")
    if comment:
        props[PROP_COMMENT] = {
            "rich_text": [{"text": {"content": comment}}]
        }

    payload = {
        "parent": {"database_id": NOTION_DB_ID},
        "properties": props,
    }

    try:
        r = requests.post(
            "https://api.notion.com/v1/pages",
            headers=NOTION_HEADERS,
            json=payload,
            timeout=30,
        )
    except Exception as e:
        log.exception("Ошибка запроса к Notion")
        return False, f"Ошибка сети при обращении к Notion: {e}"

    if r.status_code in (200, 201):
        return True, zhpr_id

    try:
        j = r.json()
        msg = j.get("message") or j.get("error") or str(j)
    except Exception:
        msg = r.text

    return False, f"Notion вернул ошибку: {msg}"

# ===== /weather =====

async def cmd_weather(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🌤 Настройка погоды для ЖПР.\n\n"
        "Напиши город, например: *Уральск*\n"
        "или координаты в формате: `51.233, 51.383`.\n\n"
        "Если хочешь отключить автопогоду — напиши `-`."
    )
    await update.message.reply_text(text, parse_mode="Markdown")
    return WEATHER_SETUP

async def st_weather_setup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (update.message.text or "").strip()
    user = update.effective_user

    if txt in ("-", "—"):
        _set_user_location_str(user.id, None)
        await update.message.reply_text(
            "Автопогода для ЖПР отключена.",
            reply_markup=main_menu(),
        )
        return ConversationHandler.END

    _set_user_location_str(user.id, txt)
    await update.message.reply_text(
        f"Город (или координаты) для погоды установлен(ы): {txt}",
        reply_markup=main_menu(),
    )
    return ConversationHandler.END

async def cancel_weather(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Настройка погоды отменена.", reply_markup=main_menu())
    return ConversationHandler.END

# ===== Дата (умная логика) =====

async def btn_new_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Старт новой записи ЖПР: сначала спрашиваем дату.
    """
    context.user_data["zhpr"] = {}

    today = date.today()
    last_date = _get_last_zhpr_date()

    lines = [f"Сегодня: {today.strftime('%d.%m.%Y')}"]

    suggested = today

    if last_date is None:
        lines.append("В ЖПР пока нет записей. Начинаем с сегодняшнего дня.")
    else:
        last_str = last_date.strftime("%d.%m.%Y")
        if last_date == today:
            lines.append(f"Последняя запись в ЖПР уже за сегодня ({last_str}).")
            lines.append("Оставляю сегодняшнюю дату.")
            suggested = today
        elif last_date < today:
            diff = (today - last_date).days
            lines.append(f"Последняя запись в ЖПР: {last_str}.")
            if diff == 1:
                lines.append("Вчерашний день заполнен. По умолчанию ставлю сегодняшнюю дату.")
                suggested = today
            else:
                suggested = last_date + timedelta(days=1)
                s_str = suggested.strftime("%d.%m.%Y")
                lines.append("Похоже, есть пропущенные дни.")
                lines.append(f"По умолчанию ставлю дату: {s_str}.")
        else:
            lines.append(f"Последняя запись в ЖПР: {last_str}.")
            lines.append("Но дата в будущем, поэтому по умолчанию ставлю сегодня.")

    context.user_data["zhpr"]["date_obj"] = datetime.combine(
        suggested, datetime.min.time()
    )

    msg = "\n".join(lines) + (
        "\n\nЕсли эта дата подходит — нажми «✅ Оставить».\n"
        "Или напиши другую дату в формате ДД.ММ.ГГГГ (например: 23.11.2025)."
    )

    await update.message.reply_text(
        msg,
        reply_markup=ReplyKeyboardMarkup([[BTN_DATE_KEEP]], resize_keyboard=True),
    )
    return ZHPR_DATE

async def st_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (update.message.text or "").strip()

    if txt == BTN_DATE_KEEP:
        return await _start_section_selection(update, context)

    d = _parse_date_str(txt)
    if not d:
        await update.message.reply_text(
            "Не понял дату. Введи в формате ДД.ММ.ГГГГ, например: 23.11.2025\n"
            "Или нажми «✅ Оставить», чтобы взять предложенную дату."
        )
        return ZHPR_DATE

    context.user_data["zhpr"]["date_obj"] = datetime.combine(d, datetime.min.time())
    return await _start_section_selection(update, context)

# ===== Выбор раздела (ГПР) по иерархии =====

def _get_current_children(struct_ctx: Dict[str, Any]) -> List[SectionNode]:
    stack: List[SectionNode] = struct_ctx.get("stack", [])
    if not stack:
        return STRUCTURE_ROOTS
    return stack[-1].children

async def _send_section_level(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    struct_ctx = context.user_data.setdefault("zhpr_struct", {})
    path: List[str] = struct_ctx.get("path", [])
    children = _get_current_children(struct_ctx)

    if not children:
        section_full = " / ".join(path) if path else "—"
        context.user_data["zhpr"]["section"] = section_full
        context.user_data.pop("zhpr_struct", None)

        await update.message.reply_text(
            f"Раздел выбран: {section_full}\n\n"
            "Теперь введи *подраздел / участок*.\n"
            "Например: `Цоколь / входная группа`",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardRemove(),
        )
        return ZHPR_SUBSECTION

    if not path:
        header = "Выбери раздел проекта (корень: Школа_65):"
    else:
        header = f"Раздел: {' / '.join(path)}\nВыбери подраздел:"

    btns = [FOLDER_ICON + n.name for n in children]
    keyboard = _chunk_buttons(btns, per_row=2)

    if path:
        keyboard.append([BTN_BACK, BTN_CHOOSE_HERE])
    else:
        keyboard.append([BTN_CHOOSE_HERE])

    await update.message.reply_text(
        header,
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True),
    )
    return ZHPR_SECTION

async def _start_section_selection(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    struct_ctx = {
        "path": [],
        "stack": [],
    }
    context.user_data["zhpr_struct"] = struct_ctx
    return await _send_section_level(update, context)

async def st_section(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (update.message.text or "").strip()
    struct_ctx = context.user_data.setdefault("zhpr_struct", {})
    path: List[str] = struct_ctx.get("path", [])
    stack: List[SectionNode] = struct_ctx.get("stack", [])

    if txt.startswith(FOLDER_ICON):
        name = txt[len(FOLDER_ICON):].strip()
        children = _get_current_children(struct_ctx)
        target = next((n for n in children if n.name == name), None)
        if not target:
            await update.message.reply_text("Не нашёл такой раздел. Попробуй ещё раз.")
            return await _send_section_level(update, context)

        stack.append(target)
        path.append(target.name)
        struct_ctx["stack"] = stack
        struct_ctx["path"] = path
        return await _send_section_level(update, context)

    if txt == BTN_BACK:
        if stack:
            stack.pop()
        if path:
            path.pop()
        struct_ctx["stack"] = stack
        struct_ctx["path"] = path
        return await _send_section_level(update, context)

    if txt == BTN_CHOOSE_HERE:
        if not path:
            await update.message.reply_text(
                "Сначала выбери хотя бы один раздел (нажми на папку)."
            )
            return await _send_section_level(update, context)

        section_full = " / ".join(path)
        context.user_data["zhpr"]["section"] = section_full
        context.user_data.pop("zhpr_struct", None)

        await update.message.reply_text(
            f"Раздел выбран: {section_full}\n\n"
            "Теперь введи *подраздел / участок*.\n"
            "Например: `Цоколь / входная группа`",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardRemove(),
        )
        return ZHPR_SUBSECTION

    await update.message.reply_text(
        "Чтобы выбрать раздел, нажми на одну из кнопок-папок ниже."
    )
    return await _send_section_level(update, context)

# ===== Остальная часть диалога =====

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👷 Привет! Это тестовый бот ЖПР (Журнал производства работ).\n"
        "Нажми кнопку ниже, чтобы создать новую запись.\n"
        "Для настройки погоды: /weather",
        reply_markup=main_menu(),
    )

async def st_subsection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    context.user_data["zhpr"]["subsection"] = text

    await update.message.reply_text(
        "Введи *вид работ*.\nНапример: `Бетон`, `Кирпич`, `Отделка`.\n"
        "Если несколько — напиши через запятую.",
        parse_mode="Markdown",
    )
    return ZHPR_WORKTYPE

async def st_worktype(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (update.message.text or "").strip()
    worktypes = [w.strip() for w in txt.split(",") if w.strip()]
    context.user_data["zhpr"]["worktypes"] = worktypes

    await update.message.reply_text(
        "Введи *объём по плану (на день)* числом.\nНапример: `25`",
        parse_mode="Markdown",
    )
    return ZHPR_PLAN

async def st_plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (update.message.text or "").replace(",", ".").strip()
    try:
        val = float(txt)
    except ValueError:
        await update.message.reply_text(
            "Нужно число. Попробуй ещё раз (пример: 25 или 12.5)"
        )
        return ZHPR_PLAN

    context.user_data["zhpr"]["plan"] = val

    await update.message.reply_text(
        "Теперь введи *фактический объём за день* числом.\nНапример: `18`",
        parse_mode="Markdown",
    )
    return ZHPR_FACT

async def st_fact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (update.message.text or "").replace(",", ".").strip()
    try:
        val = float(txt)
    except ValueError:
        await update.message.reply_text(
            "Нужно число. Попробуй ещё раз (пример: 18 или 9.5)"
        )
        return ZHPR_FACT

    context.user_data["zhpr"]["fact"] = val

    await update.message.reply_text(
        "Введи *единицу измерения* (например: `м³`, `м²`, `шт`, `п.м.`).",
        parse_mode="Markdown",
    )
    return ZHPR_UNIT

async def st_unit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (update.message.text or "").strip()
    context.user_data["zhpr"]["unit"] = txt

    await update.message.reply_text(
        "Сколько было рабочих на этом участке? Введи число.\nНапример: `6`"
    )
    return ZHPR_WORKERS

async def st_workers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (update.message.text or "").strip()
    try:
        val = int(txt)
    except ValueError:
        await update.message.reply_text(
            "Нужно целое число. Попробуй ещё раз (пример: 5 или 12)."
        )
        return ZHPR_WORKERS

    context.user_data["zhpr"]["workers"] = val

    await update.message.reply_text(
        "Введи *типы техники*, если была.\nНапример: `Экскаватор, Автокран`.\n"
        "Если техники не было — напиши `-`.",
        parse_mode="Markdown",
    )
    return ZHPR_EQUIP_TYPE

async def st_equip_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (update.message.text or "").strip()
    if txt in ("-", "—", ""):
        context.user_data["zhpr"]["equip_types"] = []
    else:
        types_ = [t.strip() for t in txt.split(",") if t.strip()]
        context.user_data["zhpr"]["equip_types"] = types_

    await update.message.reply_text(
        "Теперь напиши *количество техники* текстом.\n"
        "Например: `1 экскаватор`, `1 кран, 0.5 смены насоса`.\n"
        "Или `-`, если не было.",
        parse_mode="Markdown",
    )
    return ZHPR_EQUIP_COUNT

async def st_equip_count(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (update.message.text or "").strip()
    if txt in ("-", "—", ""):
        context.user_data["zhpr"]["equip_count"] = ""
    else:
        context.user_data["zhpr"]["equip_count"] = txt

    await update.message.reply_text(
        "Добавь комментарий (что важно запомнить).\n"
        "Например: `Отставание из-за поздней поставки бетона`, `Готово под приёмку`.\n"
        "Или напиши `-`, чтобы пропустить.",
        parse_mode="Markdown",
    )
    return ZHPR_COMMENT

async def st_comment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (update.message.text or "").strip()
    if txt in ("-", "—", ""):
        context.user_data["zhpr"]["comment"] = ""
    else:
        context.user_data["zhpr"]["comment"] = txt

    # Погода: пробуем получить по сохранённому городу/координатам
    user = update.effective_user
    weather_text = None
    loc = _get_user_location_str(user.id)
    if loc:
        weather_text = _fetch_weather_text(loc)

    if weather_text:
        context.user_data["zhpr"]["weather"] = weather_text
    else:
        context.user_data["zhpr"].setdefault("weather", "")

    # Ответственный
    context.user_data["zhpr"]["responsible"] = (
        user.full_name or (user.username or "Прораб")
    )

    ud = context.user_data["zhpr"]
    date_obj: datetime = ud.get("date_obj", datetime.now())
    zhpr_id = _generate_zhpr_id(date_obj)
    context.user_data["zhpr"]["zhpr_id"] = zhpr_id

    text_lines = [
        "ПРОВЕРЬ ЗАПИСЬ ЖПР перед сохранением:",
        "",
        f"ID: {zhpr_id}",
        f"Дата: {date_obj.strftime('%d.%m.%Y')}",
        f"Раздел: {ud.get('section')}",
        f"Участок: {ud.get('subsection')}",
        f"Вид работ: {', '.join(ud.get('worktypes', [])) or '—'}",
        f"План: {ud.get('plan')} {ud.get('unit')}",
        f"Факт: {ud.get('fact')} {ud.get('unit')}",
        f"Рабочих: {ud.get('workers')}",
        f"Техника: {', '.join(ud.get('equip_types', [])) or '—'}",
        f"Кол-во техники: {ud.get('equip_count') or '—'}",
    ]

    if ud.get("weather"):
        text_lines.append(f"Погода: {ud.get('weather')}")

    text_lines.extend(
        [
            f"Ответственный: {ud.get('responsible')}",
            f"Комментарий: {ud.get('comment') or '—'}",
            "",
            "Сохранить запись в ЖПР?",
        ]
    )

    await update.message.reply_text(
        "\n".join(text_lines),
        reply_markup=ReplyKeyboardMarkup(
            [[BTN_SAVE, BTN_FIX], [BTN_CANCEL]], resize_keyboard=True
        ),
    )
    return ZHPR_REVIEW

async def st_review(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (update.message.text or "").strip()

    if txt == BTN_CANCEL:
        context.user_data.pop("zhpr", None)
        context.user_data.pop("zhpr_struct", None)
        await update.message.reply_text(
            "Ок, запись ЖПР не сохранена.", reply_markup=main_menu()
        )
        return ConversationHandler.END

    if txt == BTN_FIX:
        context.user_data.pop("zhpr", None)
        context.user_data.pop("zhpr_struct", None)
        await update.message.reply_text(
            "Пока исправление полей не реализовано.\n"
            "Можно начать запись заново.",
            reply_markup=main_menu(),
        )
        return ConversationHandler.END

    if txt == BTN_SAVE:
        ok, info = await _create_notion_page_from_context(context)
        if ok:
            await update.message.reply_text(
                f"✅ Запись ЖПР сохранена в Notion.\nID: {info}",
                reply_markup=main_menu(),
            )
        else:
            await update.message.reply_text(
                f"⚠️ Не удалось сохранить запись ЖПР: {info}",
                reply_markup=main_menu(),
            )
        context.user_data.pop("zhpr", None)
        context.user_data.pop("zhpr_struct", None)
        return ConversationHandler.END

    await update.message.reply_text(
        "Выбери одну из кнопок: сохранить, исправить или отменить."
    )
    return ZHPR_REVIEW

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Ловим нажатие кнопки "Новая запись ЖПР" вне диалога.
    """
    txt = (update.message.text or "").strip()
    if txt == BTN_NEW_ENTRY:
        return await btn_new_entry(update, context)

    await update.message.reply_text(
        "Если хочешь создать запись ЖПР — нажми кнопку или команду /start.",
        reply_markup=main_menu(),
    )

async def cancel_conv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("zhpr", None)
    context.user_data.pop("zhpr_struct", None)
    await update.message.reply_text("Диалог ЖПР отменён.", reply_markup=main_menu())
    return ConversationHandler.END

# ===== main() =====

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Диалог настройки погоды
    conv_weather = ConversationHandler(
        entry_points=[CommandHandler("weather", cmd_weather)],
        states={
            WEATHER_SETUP: [MessageHandler(filters.TEXT & ~filters.COMMAND, st_weather_setup)],
        },
        fallbacks=[CommandHandler("cancel", cancel_weather)],
        name="weather_conv",
        persistent=False,
    )

    # Диалог ЖПР
    conv_zhpr = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex(f"^{BTN_NEW_ENTRY}$"), btn_new_entry)
        ],
        states={
            ZHPR_DATE:        [MessageHandler(filters.TEXT & ~filters.COMMAND, st_date)],
            ZHPR_SECTION:     [MessageHandler(filters.TEXT & ~filters.COMMAND, st_section)],
            ZHPR_SUBSECTION:  [MessageHandler(filters.TEXT & ~filters.COMMAND, st_subsection)],
            ZHPR_WORKTYPE:    [MessageHandler(filters.TEXT & ~filters.COMMAND, st_worktype)],
            ZHPR_PLAN:        [MessageHandler(filters.TEXT & ~filters.COMMAND, st_plan)],
            ZHPR_FACT:        [MessageHandler(filters.TEXT & ~filters.COMMAND, st_fact)],
            ZHPR_UNIT:        [MessageHandler(filters.TEXT & ~filters.COMMAND, st_unit)],
            ZHPR_WORKERS:     [MessageHandler(filters.TEXT & ~filters.COMMAND, st_workers)],
            ZHPR_EQUIP_TYPE:  [MessageHandler(filters.TEXT & ~filters.COMMAND, st_equip_type)],
            ZHPR_EQUIP_COUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, st_equip_count)],
            ZHPR_COMMENT:     [MessageHandler(filters.TEXT & ~filters.COMMAND, st_comment)],
            ZHPR_REVIEW:      [MessageHandler(filters.TEXT & ~filters.COMMAND, st_review)],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_conv),
            MessageHandler(filters.Regex(f"^{BTN_CANCEL}$"), cancel_conv),
        ],
        name="zhpr_conv",
        persistent=False,
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(conv_weather)
    app.add_handler(conv_zhpr)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    log.info("ZHPR Bot — running…")
    app.run_polling()

if __name__ == "__main__":
    main()
