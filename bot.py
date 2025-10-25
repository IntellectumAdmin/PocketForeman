# -*- coding: utf-8 -*-
"""
INTELLECTUM Bot — единый файл bot.py (обновлённый)

ИЗМЕНЕНИЯ КОРОТКО:
- Исправлен баг генерации ID: если пользователь вводит код вида "INTEL-034 — ...", он СОХРАНЯЕТСЯ, а не затирается числовым.
- Добавлен быстрый формат команды /add в одну строку: 
  "/add Название | 2025-10-01 | Спортзал | План" (разделитель — |, поля опциональны)
- /status теперь понимает коды в любом регистре и проверяет допустимость статуса до запроса в Notion.
- Улучшен парсер дедлайна: поддержка «сегодня», «завтра», «-» и «—».
- Базовые ретраи для запросов к Notion (429/5xx) с экспоненциальной паузой.
- Небольшие улучшения логов и сообщений пользователю.

ВАЖНО:
- Если нужно менять кусок — пиши: «замени блок N целиком» или «добавь между 8 и 9 блок 8.1».
"""

# ===== 1. Импорты и базовая настройка логов =====
import os
import re
import json
import time
import logging
from datetime import datetime, timedelta, date
from typing import Dict, Any, Optional, List, Tuple
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv

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

# Логи: потише шум библиотек
logging.basicConfig(level=logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("intel-bot")
log.setLevel(logging.INFO)


# ===== 2. Загрузка .env и переменные окружения =====
load_dotenv()

BOT_TOKEN     = os.getenv("TELEGRAM_BOT_TOKEN", "")
NOTION_TOKEN  = os.getenv("NOTION_TOKEN", "")
DATABASE_ID   = os.getenv("NOTION_DATABASE_ID", "")

NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}

# Сетевые параметры
HTTP_TIMEOUT = 20
RETRY_MAX = 4


# ===== 3. Имена колонок Notion (P[...] -> названия свойств) =====
# Эти названия должны совпадать с вашими свойствами в базе Notion
P: Dict[str, str] = {
    "TITLE_ID": os.getenv("PROP_TITLE_ID", "ID (текст)"),        # тип Title
    "NAME":     os.getenv("PROP_NAME",     "Название задачи"),   # тип Rich text
    "STATUS":   os.getenv("PROP_STATUS",   "Статус"),            # тип Status
    "DEADLINE": os.getenv("PROP_DEADLINE", "Срок ( Deadline)"),  # тип Date
    "SOURCE":   os.getenv("PROP_SOURCE",   "Источник (Source)"), # тип Select
    "OBJECT":   os.getenv("PROP_OBJECT",   "Объект"),            # тип Select
    "ATTACH":   os.getenv("PROP_ATTACH",   "Вложения"),          # тип Files & media
    "XAI_LOG":  os.getenv("PROP_XAI_LOG",  "XAI Log"),           # тип Rich text (опц.)
}


# ===== 4. Константы, клавиатуры и разрешённые значения =====
# Разрешённые статусы в вашей базе (проверьте в Notion)
ALLOWED_STATUSES = ["Not started", "In progress", "Done"]
STATUS_KBD = ReplyKeyboardMarkup(
    [ALLOWED_STATUSES],
    resize_keyboard=True,
    one_time_keyboard=True
)

SOURCES = ["План", "Дефект", "Операции", "API"]
SOURCE_KBD = ReplyKeyboardMarkup([SOURCES + ["-"]], resize_keyboard=True, one_time_keyboard=True)

# этапы разговоров
ADD_NAME, ADD_DEADLINE, ADD_OBJECT, ADD_SOURCE = range(4)
ST1_WAIT_ID, ST2_WAIT_STATUS = range(4, 6)


# ===== ВСПОМОГАТЕЛЬНОЕ: HTTP с ретраями к Notion =====
def _request_with_retries(method: str, url: str, **kwargs) -> requests.Response:
    """Простой экспоненциальный бэкофф для 429/5xx."""
    for attempt in range(RETRY_MAX):
        resp = requests.request(method, url, timeout=HTTP_TIMEOUT, **kwargs)
        if resp.status_code < 429 or resp.status_code == 404:
            return resp
        if resp.status_code in (429, 500, 502, 503, 504):
            delay = min(2 ** attempt, 10)
            log.warning("Notion %s -> %s. Retry in %ss (attempt %s/%s)", method, resp.status_code, delay, attempt+1, RETRY_MAX)
            time.sleep(delay)
            continue
        return resp
    return resp


# ===== 5. Вспомогательное: парсинг дат, безопасные извлечения из Notion =====
def _today_iso() -> str:
    return date.today().strftime("%Y-%m-%d")

def parse_deadline(s: Optional[str]) -> Optional[str]:
    """Принимает 'YYYY-MM-DD' или 'DD.MM.YYYY' и возвращает ISO 'YYYY-MM-DD'.
    Понимает также «сегодня», «завтра», '-', '—'.
    """
    if not s:
        return None
    s = s.strip().lower()
    if s in ("", "-", "—"):
        return None
    if s in ("сегодня", "today"):
        return _today_iso()
    if s in ("завтра", "tomorrow"):
        return (date.today() + timedelta(days=1)).strftime("%Y-%m-%d")
    try:
        # 2025-10-01
        if len(s) == 10 and s[4] == "-" and s[7] == "-":
            datetime.strptime(s, "%Y-%m-%d")
            return s
        # 01.10.2025
        if len(s) == 10 and s[2] == "." and s[5] == ".":
            dt = datetime.strptime(s, "%d.%m.%Y")
            return dt.strftime("%Y-%m-%d")
    except Exception:
        return None
    return None


def safe_text(prop: dict) -> str:
    """Безопасно достаёт plain_text из rich_text / title."""
    if not isinstance(prop, dict):
        return ""
    for key in ("title", "rich_text"):
        arr = prop.get(key, [])
        if isinstance(arr, list) and arr:
            return arr[0].get("plain_text") or arr[0].get("text", {}).get("content", "")
    return ""


def safe_select_name(prop: dict) -> str:
    if not isinstance(prop, dict):
        return ""
    sel = prop.get("select")
    if isinstance(sel, dict):
        return sel.get("name", "")
    return ""


def page_code_from_props(props: dict) -> str:
    return safe_text(props.get(P["TITLE_ID"], {})) or "—"


# ===== 6. Notion: низкоуровневые функции (поиск страницы, создание, обновление статуса, запрос последних) =====
# ==== 6.1. Автонумерация: следующий ID в формате 3 цифры ====
def notion_get_next_numeric_id() -> str:
    """
    Сканирует последние страницы базы и ищет максимальный числовой ID в колонке Title (P['TITLE_ID']).
    Возвращает следующий номер как строку с ведущими нулями: '001', '002', ...
    Если ничего не нашлось — вернёт '001'.
    """
    url = f"https://api.notion.com/v1/databases/{DATABASE_ID}/query"
    payload = {
        "sorts": [{"timestamp": "last_edited_time", "direction": "descending"}],
        "page_size": 50
    }
    try:
        r = _request_with_retries("POST", url, headers=NOTION_HEADERS, data=json.dumps(payload))
        if r.status_code != 200:
            log.warning("Notion counter query failed: %s %s", r.status_code, r.text)
            return "001"

        max_num = 0
        for item in r.json().get("results", []):
            props = item.get("properties", {})
            code = safe_text(props.get(P["TITLE_ID"], {})).strip()
            if re.fullmatch(r"\d{1,}", code):
                n = int(code)
                if n > max_num:
                    max_num = n
        nxt = max_num + 1
        return str(nxt).zfill(3)
    except Exception as e:
        log.warning("Counter error: %s", e)
        return "001"

# ==== 6.2. Поиск страницы по коду, обновление статуса, создание страницы, запрос последних ====
def notion_find_page_by_code(code: str) -> Optional[str]:
    """
    Находит страницу по коду (например, 'INTEL-005' или '001') в колонке Title (P["TITLE_ID"]).
    Возвращает page_id или None.
    """
    url = f"https://api.notion.com/v1/databases/{DATABASE_ID}/query"
    payload = {
        "filter": {
            "property": P["TITLE_ID"],
            "title": {"equals": code}
        },
        "page_size": 1
    }
    r = _request_with_retries("POST", url, headers=NOTION_HEADERS, data=json.dumps(payload))
    if r.status_code != 200:
        log.warning("Notion query failed: %s %s", r.status_code, r.text)
        return None
    results = r.json().get("results", [])
    if not results:
        return None
    return results[0].get("id")


def notion_update_status(page_id: str, new_status: str) -> Tuple[bool, str]:
    """Обновляет статус страницы в Notion. new_status должен быть одним из ALLOWED_STATUSES."""
    if new_status not in ALLOWED_STATUSES:
        return False, f"Недопустимый статус: {new_status}"

    url = f"https://api.notion.com/v1/pages/{page_id}"
    payload = {"properties": {P["STATUS"]: {"status": {"name": new_status}}}}
    r = _request_with_retries("PATCH", url, headers=NOTION_HEADERS, data=json.dumps(payload))
    if r.status_code in (200, 201):
        return True, "ok"
    return False, f"{r.status_code} {r.text}"


def notion_create_page(
    title_raw: str,
    deadline_iso: Optional[str],
    object_text: Optional[str],
    source_name: Optional[str],
) -> Tuple[bool, str]:
    """
    Создаёт задачу в базе по "умному" разбору заголовка.
    Допустимые формы:
      - 'INTEL-034 — Проверить гидроизоляцию'
      - 'INTEL-034 Проверить гидроизоляцию'
      - 'Привезти бетон' -> сгенерируем NAME из текста, а ID сгенерим числовой автоматически
    """
    def gen_tmp_id() -> str:
        return f"TMP-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

    def split_id_and_name(raw: str) -> Tuple[str, str, bool]:
        """Возвращает (code, name, code_was_provided).
        code_was_provided=True, если пользователь явно задал алфанумерический код (INTEL-034 и т.п.).
        """
        if not raw:
            return gen_tmp_id(), "", False
        text = raw.strip()

        # INTEL-034 — Что-то
        parts = re.split(r"\s*[—-]\s*", text, maxsplit=1)
        if len(parts) == 2:
            left, right = parts[0].strip(), parts[1].strip()
            if re.match(r"^[A-Za-zА-ЯЁ]+-\d+(?:-\d+)?$", left):
                return left, right, True

        # INTEL-034 Что-то
        m = re.match(r"^([A-Za-zА-ЯЁ]+-\d+(?:-\d+)?)[\s]+(.+)$", text)
        if m:
            return m.group(1), m.group(2).strip(), True

        # Только код?
        if re.match(r"^[A-Za-zА-ЯЁ]+-\d+(?:-\d+)?$", text):
            return text, "", True

        # Иначе: ID временный, NAME = исходный текст
        return gen_tmp_id(), text, False

    code, name_text, code_provided = split_id_and_name(title_raw)

    # Если пользователь НЕ дал готовый алфанумерический код — генерируем следующий числовой ID вида 001/002/003...
    if not code_provided:
        code = notion_get_next_numeric_id()

    props: Dict[str, Any] = {
        P["TITLE_ID"]: {"title": [{"text": {"content": code}}]},
        P["NAME"]:     {"rich_text": [{"text": {"content": (name_text or title_raw)}}]},
        P["STATUS"]:   {"status": {"name": "Not started"}},
    }
    if deadline_iso:
        props[P["DEADLINE"]] = {"date": {"start": deadline_iso}}
    if object_text and object_text not in ("-", "—"):
        props[P["OBJECT"]] = {"select": {"name": object_text}}
    if source_name:
        props[P["SOURCE"]] = {"select": {"name": source_name}}

    payload = {"parent": {"database_id": DATABASE_ID}, "properties": props}
    r = _request_with_retries("POST", "https://api.notion.com/v1/pages", headers=NOTION_HEADERS, data=json.dumps(payload))
    if r.status_code in (200, 201):
        return True, r.json().get("id", "")
    return False, f"{r.status_code} {r.text}"


def notion_query_recent(limit: int = 10) -> List[dict]:
    """Последние изменённые задачи (для /report)."""
    url = f"https://api.notion.com/v1/databases/{DATABASE_ID}/query"
    payload = {
        "sorts": [{"timestamp": "last_edited_time", "direction": "descending"}],
        "page_size": limit,
    }
    r = _request_with_retries("POST", url, headers=NOTION_HEADERS, data=json.dumps(payload))
    if r.status_code != 200:
        log.warning("Notion query error: %s %s", r.status_code, r.text)
        return []
    return r.json().get("results", [])

# ===== 6.3. Вложения: хелперы и операция добавления ссылки =====

def _get_existing_files(page_id: str) -> List[dict]:
    """Возвращает текущие файлы из свойства P["ATTACH"] (Files & media)."""
    try:
        url = f"https://api.notion.com/v1/pages/{page_id}"
        r = _request_with_retries("GET", url, headers=NOTION_HEADERS)
        if r.status_code != 200:
            log.warning("Notion retrieve page failed: %s %s", r.status_code, r.text)
            return []
        props = r.json().get("properties", {})
        files_prop = props.get(P["ATTACH"], {})
        return files_prop.get("files", []) or []
    except Exception as e:
        log.warning("Read files error: %s", e)
        return []


def _nice_filename_from_url(url: str) -> str:
    """Делает читаемое имя файла из URL по хвосту пути."""
    try:
        p = urlparse(url)
        tail = (p.path or "/").rstrip("/").split("/")[-1] or "link"
        return tail[:80]
    except Exception:
        return "link"


def attach_link_to_task(text_id: str, url: str, name: Optional[str] = None) -> Tuple[bool, str]:
    """
    Добавляет внешнюю ссылку в свойство P["ATTACH"] задачи с заданным текстовым ID.
    - text_id: '001', '002', ... (или любой код, который хранится в колонке Title/ID)
    - url: ссылка (OneDrive/Google Drive/и т.д.)
    - name: подпись (если None — сформируем из URL)
    """
    # 1) Найти страницу по коду
    page_id = notion_find_page_by_code(text_id)
    if not page_id:
        return False, f"Не нашёл задачу с ID {text_id}. Проверь номер (например, 001)."

    # 2) Подготовить элемент файла (external)
    file_name = name.strip() if name else _nice_filename_from_url(url)
    new_file = {"name": file_name, "external": {"url": url}}

    # 3) Считать текущие файлы и добавить новый
    existing = _get_existing_files(page_id)
    updated_files = (existing or []) + [new_file]

    # 4) Обновить страницу
    payload = {"properties": {P["ATTACH"]: {"files": updated_files}}}
    r = _request_with_retries("PATCH", f"https://api.notion.com/v1/pages/{page_id}", headers=NOTION_HEADERS, data=json.dumps(payload))
    if r.status_code in (200, 201):
        return True, f"Готово! Ссылка добавлена в ‘{P['ATTACH']}’ задачи {text_id}."
    return False, f"Не удалось обновить ‘{P['ATTACH']}’: {r.status_code} {r.text}"


# ===== 7. Telegram: общие команды (/start, /help, /report) =====
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Я INTELLECTUM Bot.\n"
        "Команды:\n"
        "/add — добавить задачу (мастер или быстро: /add Текст | 2025-10-01 | Объект | Источник)\n"
        "/status — сменить статус задачи\n"
        "/report — последние изменения\n"
        "/help — подсказка"
    )

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "Доступно:\n"
        "/add — мастер добавления задачи (название → дедлайн → объект → источник)\n"
        "      Быстрый формат: /add Название | 2025-10-01 | Спортзал | План (поля после Названия — опциональны)\n"
        "/attach — прикрепить ссылку в поле «Вложения»: /attach <ID> <URL> [описание]\n"
        "/status — смена статуса по ID (например INTEL-005 или 001)\n"
        "     Примеры:\n"
        "       /status INTEL-005 In progress\n"
        "       /status  (запустит диалог)\n"
        "/report — последние задачи из Backlog"
    )
    await update.message.reply_text(text)




async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pages = notion_query_recent(limit=10)
    if not pages:
        await update.message.reply_text("Пока нет данных.")
        return

    lines = []
    for p in pages:
        props = p.get("properties", {})
        code = page_code_from_props(props)
        name = safe_text(props.get(P["NAME"], {}))
        status = safe_select_name(props.get(P["STATUS"], {})) or "—"
        deadline = ""
        if isinstance(props.get(P["DEADLINE"]), dict):
            d = props[P["DEADLINE"]].get("date", {})
            deadline = (d.get("start") or "")[:10]
        lines.append(f"{code}: {name} | {status} | {deadline or '—'}")

    await update.message.reply_text("Последние изменения:\n" + "\n".join(lines[:10]))


# ===== 7.1. Telegram: команда /attach (прикрепить ссылку) =====
async def attach_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ /attach <ID> <URL> [описание] — добавляет ссылку в Files & media """
    try:
        if not context.args or len(context.args) < 2:
            await update.message.reply_text(
                "Использование: /attach <ID> <URL> [описание]\n"
                "Например: /attach 002 https://1drv.ms/u/... Фото геотекстиля"
            )
            return

        text_id = context.args[0].strip()
        url = context.args[1].strip()
        name = " ".join(context.args[2:]).strip() if len(context.args) > 2 else None
        ok, msg = attach_link_to_task(text_id, url, name)
        await update.message.reply_text(msg)
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")


# ===== 8. Telegram: диалог /add (добавить задачу) =====
async def add_task_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    # Попытка быстрым форматом: "/add Название | 2025-10-01 | Объект | Источник"
    if "|" in text:
        parts = [p.strip() for p in text.split(" ", 1)]
        if len(parts) == 2:
            payload = [x.strip() for x in parts[1].split("|")]
            title = payload[0] if len(payload) >= 1 else ""
            deadline_iso = parse_deadline(payload[1]) if len(payload) >= 2 else None
            object_text = payload[2] if len(payload) >= 3 else None
            source_name = payload[3] if len(payload) >= 4 else None
            ok, info = notion_create_page(title, deadline_iso, object_text, source_name)
            if ok:
                await update.message.reply_text("✓ Задача добавлена в Notion.")
            else:
                await update.message.reply_text(f"✗ Ошибка создания: {info}")
            return ConversationHandler.END

    await update.message.reply_text("Добавление задачи.\nВведи название:")
    return ADD_NAME

async def add_task_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["name"] = update.message.text.strip()
    await update.message.reply_text("Дедлайн (YYYY-MM-DD, ДД.MM.ГГГГ, 'сегодня/завтра') или «-» если нет:")
    return ADD_DEADLINE

async def add_task_deadline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw = update.message.text.strip()
    context.user_data["deadline_iso"] = parse_deadline(raw)
    await update.message.reply_text("Объект (например: Спортзал) или «-»:", reply_markup=ReplyKeyboardRemove())
    return ADD_OBJECT

async def add_task_object(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["object"] = update.message.text.strip()
    await update.message.reply_text("Источник (выбери кнопку или напиши, «-» если нет):", reply_markup=SOURCE_KBD)
    return ADD_SOURCE

async def add_task_source(update: Update, context: ContextTypes.DEFAULT_TYPE):
    src = update.message.text.strip()
    source_name = src if src in SOURCES else (None if src in ("-", "—") else src)
    context.user_data["source"] = source_name

    title = context.user_data.get("name", "")
    deadline_iso = context.user_data.get("deadline_iso")
    object_text = context.user_data.get("object")
    ok, info = notion_create_page(title, deadline_iso, object_text, source_name)

    if ok:
        await update.message.reply_text("✓ Задача добавлена в Notion.", reply_markup=ReplyKeyboardRemove())
    else:
        await update.message.reply_text(f"✗ Ошибка создания: {info}", reply_markup=ReplyKeyboardRemove())

    context.user_data.clear()
    return ConversationHandler.END

async def add_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Отменено.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


# ===== 9. Telegram: диалог /status (сменить статус задачи) =====
async def cmd_status_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Точка входа в /status. Поддерживает: "/status INTEL-005 Done" одной строкой."""
    text = (update.message.text or "").strip()
    parts = text.split(maxsplit=2)  # ['/status', 'INTEL-005', 'Done?']

    if len(parts) >= 3:
        code = parts[1].strip().upper()
        new_status = parts[2].strip()
        return await _apply_status(update, context, code, new_status)

    await update.message.reply_text("Введи ID задачи (например, INTEL-005 или 001):")
    return ST1_WAIT_ID


async def st1_got_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = update.message.text.strip().upper()
    context.user_data["status_target_code"] = code
    await update.message.reply_text(
        f"Выбери новый статус для {code}:",
        reply_markup=STATUS_KBD
    )
    return ST2_WAIT_STATUS


async def st2_got_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_status = update.message.text.strip()
    code = context.user_data.get("status_target_code", "")
    return await _apply_status(update, context, code, new_status)


async def _apply_status(update: Update, context: ContextTypes.DEFAULT_TYPE, code: str, new_status: str):
    if new_status not in ALLOWED_STATUSES:
        await update.message.reply_text(
            f"Недопустимый статус: {new_status}\nРазрешено: {', '.join(ALLOWED_STATUSES)}",
            reply_markup=ReplyKeyboardRemove()
        )
        return ConversationHandler.END

    page_id = notion_find_page_by_code(code)
    if not page_id:
        await update.message.reply_text(
            f"Не нашёл задачу с ID {code}. Проверь, что в колонке «{P['TITLE_ID']}» есть такое значение.",
            reply_markup=ReplyKeyboardRemove()
        )
        return ConversationHandler.END

    ok, info = notion_update_status(page_id, new_status)
    if ok:
        await update.message.reply_text(
            f"✓ Статус задачи {code} обновлён на «{new_status}».",
            reply_markup=ReplyKeyboardRemove()
        )
    else:
        await update.message.reply_text(
            f"✗ Не удалось обновить статус: {info}",
            reply_markup=ReplyKeyboardRemove()
        )
    context.user_data.clear()
    return ConversationHandler.END


# ===== 10. MAIN: сборка Application, регистрация хендлеров и запуск =====
def main():
    if not BOT_TOKEN:
        raise RuntimeError("Нет TELEGRAM_BOT_TOKEN в .env")
    if not NOTION_TOKEN or not DATABASE_ID:
        raise RuntimeError("Нет NOTION_TOKEN / NOTION_DATABASE_ID в .env")

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # /add
    add_conv = ConversationHandler(
        entry_points=[CommandHandler("add", add_task_start)],
        states={
            ADD_NAME:     [MessageHandler(filters.TEXT & ~filters.COMMAND, add_task_name)],
            ADD_DEADLINE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_task_deadline)],
            ADD_OBJECT:   [MessageHandler(filters.TEXT & ~filters.COMMAND, add_task_object)],
            ADD_SOURCE:   [MessageHandler(filters.TEXT & ~filters.COMMAND, add_task_source)],
        },
        fallbacks=[CommandHandler("cancel", add_cancel)],
        name="add_task_conv",
        persistent=False,
    )

    # /status
    status_conv = ConversationHandler(
        entry_points=[CommandHandler("status", cmd_status_entry)],
        states={
            ST1_WAIT_ID:     [MessageHandler(filters.TEXT & ~filters.COMMAND, st1_got_id)],
            ST2_WAIT_STATUS: [MessageHandler(filters.TEXT & ~filters.COMMAND, st2_got_status)],
        },
        fallbacks=[CommandHandler("cancel", add_cancel)],
        name="status_conv",
        persistent=False,
    )

    # Общие команды
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("report", cmd_report))
    app.add_handler(CommandHandler("attach", attach_command))
    app.add_handler(add_conv)
    app.add_handler(status_conv)

    log.warning("Bot is starting...")
    app.run_polling()


if __name__ == "__main__":
    main()
