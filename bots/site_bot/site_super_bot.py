# -*- coding: utf-8 -*-
"""
Pocket Foreman (Journal) — Telegram → Notion
Диалог /add: Раздел → Имя файла → URL → Комментарий
Команда /sections: вывести доступные разделы из Notion
"""
from __future__ import annotations

import os
import re
import json
import logging
from datetime import datetime
from typing import Dict, Any, Optional, List, Tuple

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

# ==========================
# 1) ЛОГИ — ТИХИЙ РЕЖИМ
# ==========================
# Базовый уровень: INFO для нашего кода
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s:%(name)s:%(message)s",
)

# Угомоним «болтливые» библиотеки
for noisy in ("httpx", "telegram", "telegram.ext", "apscheduler", "urllib3"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

log = logging.getLogger("pocket-foreman")
log.setLevel(logging.INFO)


# ==========================
# 2) ENV / КОНФИГ
# ==========================
load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
NOTION_TOKEN = os.getenv("NOTION_TOKEN", "").strip()
DATABASE_ID = os.getenv("NOTION_DATABASE_ID_SCHOOL65", "").strip() or os.getenv("NOTION_DATABASE_ID", "").strip()

if not BOT_TOKEN:
    raise RuntimeError("Нет TELEGRAM_BOT_TOKEN в .env")
if not NOTION_TOKEN:
    raise RuntimeError("Нет NOTION_TOKEN в .env")
if not DATABASE_ID:
    raise RuntimeError("Нет NOTION_DATABASE_ID(_SCHOOL65) в .env")

NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}

# Названия свойств в базе «Журнал вложений»
PROP_SECTION  = os.getenv("PROP_SECTION",  "Раздел")
PROP_FILE     = os.getenv("PROP_FILE",     "Файл / Фото")
PROP_URL      = os.getenv("PROP_URL",      "URL")
PROP_DATE     = os.getenv("PROP_DATE",     "Дата")
PROP_COMMENT  = os.getenv("PROP_COMMENT",  "Комментарий")

# ==========================
# 3) УТИЛИТЫ ДЛЯ NOTION
# ==========================
def _retry_post(url: str, payload: Dict[str, Any], retries: int = 2) -> requests.Response:
    """POST с небольшой ретраем."""
    last_exc: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            r = requests.post(url, headers=NOTION_HEADERS, data=json.dumps(payload), timeout=20)
            return r
        except Exception as e:
            last_exc = e
    if last_exc:
        raise last_exc
    raise RuntimeError("unknown POST error")

def notion_ping() -> bool:
    """Лёгкая проверка доступа к базе — query с page_size=1."""
    url = f"https://api.notion.com/v1/databases/{DATABASE_ID}/query"
    r = requests.post(url, headers=NOTION_HEADERS, data=json.dumps({"page_size": 1}))
    log.info("Notion ping: %s %s", r.status_code, r.text[:120])
    return r.status_code == 200

def notion_get_section_options() -> List[str]:
    """Получить список вариантов (Select) из свойства «Раздел»."""
    url = f"https://api.notion.com/v1/databases/{DATABASE_ID}"
    r = requests.get(url, headers=NOTION_HEADERS)
    if r.status_code != 200:
        log.warning("get database failed: %s %s", r.status_code, r.text[:200])
        return []
    db = r.json()
    props = db.get("properties", {})
    section_prop = props.get(PROP_SECTION, {})
    select = section_prop.get("select", {})
    options = select.get("options", []) if isinstance(select, dict) else []
    names = [o.get("name") for o in options if isinstance(o, dict) and o.get("name")]
    return names

def _sanitize_url(s: str) -> Optional[str]:
    """Небольшая валидация ссылки (http/https)."""
    s = (s or "").strip()
    if not s:
        return None
    if not re.match(r"^https?://", s, flags=re.IGNORECASE):
        return None
    return s

def notion_create_journal_entry(
    section: str,
    file_name: str,
    url: str,
    comment: Optional[str],
) -> Tuple[bool, str]:
    """
    Создать запись в Журнале: Раздел, Файл/Фото (rich text), URL, Дата=сегодня, Комментарий.
    """
    today_iso = datetime.now().strftime("%Y-%m-%d")
    props: Dict[str, Any] = {
        PROP_SECTION: {"select": {"name": section}},
        PROP_FILE:    {"rich_text": [{"text": {"content": file_name}}]},
        PROP_URL:     {"url": url},
        PROP_DATE:    {"date": {"start": today_iso}},
    }
    if comment and comment.strip() not in ("-", "—"):
        props[PROP_COMMENT] = {"rich_text": [{"text": {"content": comment.strip()}}]}

    payload = {"parent": {"database_id": DATABASE_ID}, "properties": props}
    r = _retry_post("https://api.notion.com/v1/pages", payload)
    if r.status_code in (200, 201):
        page_id = r.json().get("id", "")
        return True, page_id
    return False, f"{r.status_code} {r.text}"


# ==========================
# 4) TELEGRAM BOT
# ==========================
ADD_SECTION, ADD_NAME, ADD_URL, ADD_COMMENT = range(4)

def _sections_keyboard() -> ReplyKeyboardMarkup:
    names = notion_get_section_options()
    # разобьём на столбцы по 2–3, чтобы не было «портянки» в одну строку
    rows: List[List[str]] = []
    row: List[str] = []
    for name in names:
        row.append(name)
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return ReplyKeyboardMarkup(rows or [["-"]], resize_keyboard=True, one_time_keyboard=True)

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Это Карманный прораб (Журнал вложений).\n\n"
        "Команды:\n"
        "• /add — добавить запись в Notion\n"
        "• /sections — список разделов\n"
        "• /help — справка"
    )

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Как пользоваться:\n"
        "1) /add — бот спросит раздел, имя файла/фото, URL (OneDrive/HTTPS), комментарий (опц.)\n"
        "2) /sections — показать список доступных «Разделов» из базы Notion\n\n"
        "Совет: ссылку OneDrive вставляй вида https://1drv.ms/... — они отлично работают в Notion."
    )

async def cmd_sections(update: Update, context: ContextTypes.DEFAULT_TYPE):
    names = notion_get_section_options()
    if not names:
        await update.message.reply_text("Разделы не найдены (проверь доступ интеграции к базе).")
        return
    await update.message.reply_text("Доступные разделы:\n• " + "\n• ".join(names))

# ===== Диалог /add =====
async def add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = _sections_keyboard()
    await update.message.reply_text("Выбери раздел:", reply_markup=kb)
    return ADD_SECTION

async def add_got_section(update: Update, context: ContextTypes.DEFAULT_TYPE):
    section = update.message.text.strip()
    valid = notion_get_section_options()
    if section not in valid:
        await update.message.reply_text("Такого раздела нет. Нажми на кнопку с нужным разделом.")
        return ADD_SECTION
    context.user_data["section"] = section
    await update.message.reply_text("Имя файла / фото (как показать в журнале):", reply_markup=ReplyKeyboardRemove())
    return ADD_NAME

async def add_got_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    if not name:
        await update.message.reply_text("Имя не может быть пустым. Введи имя:")
        return ADD_NAME
    context.user_data["name"] = name
    await update.message.reply_text("Вставь ссылку OneDrive (или другую HTTPS ссылку):")
    return ADD_URL

async def add_got_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = _sanitize_url(update.message.text)
    if not url:
        await update.message.reply_text("Это не похоже на ссылку. Вставь корректный URL, начинающийся с http(s)://")
        return ADD_URL
    context.user_data["url"] = url
    await update.message.reply_text("Комментарий (опционально) или «-» :", reply_markup=ReplyKeyboardRemove())
    return ADD_COMMENT

async def add_got_comment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    comment = update.message.text or ""
    section = context.user_data.get("section", "")
    name = context.user_data.get("name", "")
    url = context.user_data.get("url", "")

    ok, info = notion_create_journal_entry(section, name, url, comment)
    if ok:
        await update.message.reply_text("✓ Запись добавлена в Notion «Журнал вложений».")
    else:
        await update.message.reply_text(f"✗ Ошибка: {info}")

    context.user_data.clear()
    return ConversationHandler.END

async def add_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Отменено.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


# ==========================
# 5) MAIN
# ==========================
def main():
    # Быстрый пинг — чисто чтобы в логах было видно доступность базы
    try:
        notion_ping()
    except Exception as e:
        log.warning("Notion ping error: %s", e)

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    add_conv = ConversationHandler(
        entry_points=[CommandHandler("add", add_start)],
        states={
            ADD_SECTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_got_section)],
            ADD_NAME:    [MessageHandler(filters.TEXT & ~filters.COMMAND, add_got_name)],
            ADD_URL:     [MessageHandler(filters.TEXT & ~filters.COMMAND, add_got_url)],
            ADD_COMMENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_got_comment)],
        },
        fallbacks=[CommandHandler("cancel", add_cancel)],
        name="add_conv",
        persistent=False,
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("sections", cmd_sections))
    app.add_handler(add_conv)

    log.info("Pocket Foreman (Journal) bot is starting...")
    app.run_polling(drop_pending_updates=True)  # без лишних накопившихся апдейтов


if __name__ == "__main__":
    main()
