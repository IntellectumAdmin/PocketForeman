# -*- coding: utf-8 -*-
"""
Pocket Foreman: Cloudinary -> Notion
- SafeSync структуры
- Главное меню и /photo
- Ветка «Из галереи» (поддержка нескольких фото одним сообщением)
- Ветка «📷 Сделать фото» через WebApp (camera.html)
- Запись в Notion.Files & media (внешние ссылки) + дублирование первой ссылки в колонку URL
"""

import os
import io
import json
import time
import logging
from datetime import datetime
from typing import Dict, Any, Optional, List, Tuple
from pathlib import Path
from urllib.parse import quote

from dotenv import load_dotenv
import requests
import cloudinary
import cloudinary.uploader

from structure_safe_sync import start_safe_sync
from structure_sync import sync_structure

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    WebAppInfo,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# ===== Логи =====
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("pf-bot")
log.setLevel(logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("cloudinary").setLevel(logging.WARNING)

# ===== .env =====
load_dotenv()

# === Notion ===
NOTION_TOKEN = os.getenv("NOTION_TOKEN_SCHOOL65", "")
DATABASE_ID  = os.getenv("NOTION_DATABASE_ID_SCHOOL65", "")

# === Cloudinary ===
CLOUD_NAME        = os.getenv("CLOUD_NAME", "")
CLOUD_API_KEY     = os.getenv("CLOUD_API_KEY", "")
CLOUD_API_SECRET  = os.getenv("CLOUD_API_SECRET", "")
CLOUD_ROOT        = os.getenv("CLOUD_ROOT", "Project")
CLOUD_UNSIGNED_PRESET = os.getenv("CLOUD_UNSIGNED_PRESET", "pf_unsigned")

# === Telegram ===
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

# === Колонки в Notion ===
PROP_SECTION = os.getenv("PROP_SECTION", "Раздел")
PROP_FILE    = os.getenv("PROP_FILE", "Файл / Фото")       # Files & media
PROP_URL     = os.getenv("PROP_URL", "Ссылка OneDrive")    # дублируем первую ссылку
PROP_DATE    = os.getenv("PROP_DATE", "Дата")
PROP_COMMENT = os.getenv("PROP_COMMENT", "Комментарий")

# === Кэш структуры ===
STRUCTURE_CACHE_PATH = Path("structure_cache.json")
STRUCT_ROOT = "Школа_65"
STRUCT_INDEX: Dict[str, List[str]] = {}

# ==== Главное меню ====
BTN_ADD_PHOTO = "📸 Добавить фото"
BTN_OPEN_CAM  = "📷 Открыть камеру"
BTN_CHANGE    = "🔄 Сменить раздел"
BTN_CANCEL    = "❌ Отмена"

def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([[KeyboardButton(BTN_ADD_PHOTO)]], resize_keyboard=True)

def cam_menu(cam_url: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(text=BTN_OPEN_CAM, web_app=WebAppInfo(cam_url))],
            [KeyboardButton(text=BTN_CHANGE), KeyboardButton(text=BTN_CANCEL)],
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
    )

async def ensure_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        await update.message.reply_text("Выберите действие:", reply_markup=main_menu())

def quick_inline_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("📸 Добавить фото", callback_data="go")]])

# ===== Cloudinary config =====
if not (CLOUD_NAME and CLOUD_API_KEY and CLOUD_API_SECRET):
    raise RuntimeError("Заполни CLOUD_NAME/CLOUD_API_KEY/CLOUD_API_SECRET в .env")
cloudinary.config(
    cloud_name=CLOUD_NAME,
    api_key=CLOUD_API_KEY,
    api_secret=CLOUD_API_SECRET,
    secure=True,
)

# ===== Notion headers =====
NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}

# ===== Состояния разговора =====
PH1_WAIT_SECTION, PH2_WAIT_PHOTO, PH3_WAIT_COMMENT = range(100, 103)

# ===== Структура из кэша =====
def _build_index(paths: List[str]) -> Dict[str, List[str]]:
    idx: Dict[str, set] = {}
    for p in paths:
        parts = [s.strip() for s in p.split("/") if s.strip()]
        for i in range(len(parts)):
            parent = "/".join(parts[:i])
            child  = parts[i]
            idx.setdefault(parent, set()).add(child)
    return {k: sorted(list(v)) for k, v in idx.items()}

def structure_load_index():
    global STRUCT_ROOT, STRUCT_INDEX
    if STRUCTURE_CACHE_PATH.exists():
        data  = json.loads(STRUCTURE_CACHE_PATH.read_text(encoding="utf-8"))
        STRUCT_ROOT = data.get("root", STRUCT_ROOT)
        paths = data.get("paths", [])
        STRUCT_INDEX = _build_index(paths)
    else:
        STRUCT_INDEX = {}
    return STRUCT_ROOT, STRUCT_INDEX

def structure_children(parent_path: str) -> List[str]:
    return STRUCT_INDEX.get(parent_path, [])

def format_path_for_notion(path_str: str) -> str:
    parts = [s for s in path_str.split("/") if s]
    return " / ".join(parts)

# ===== Короткие id =====
PATH2ID: Dict[str, str] = {}
ID2PATH: Dict[str, str] = {}
ID_SEQ = 1

def _id_for_path(path: str) -> str:
    global ID_SEQ
    if path not in PATH2ID:
        PATH2ID[path] = str(ID_SEQ)
        ID2PATH[str(ID_SEQ)] = path
        ID_SEQ += 1
    return PATH2ID[path]

def _path_by_id(pid: str) -> str:
    return ID2PATH.get(pid, "")

# ===== Notion: запись строки с одним/несколькими файлами =====
def _props_files(section: str, file_name: str, urls: List[str], comment: Optional[str]) -> Dict[str, Any]:
    today_iso = datetime.now().strftime("%Y-%m-%d")
    files_payload = [
        {"type": "external", "name": file_name if i == 0 else f"{file_name} {i+1}", "external": {"url": u}}
        for i, u in enumerate(urls)
    ]
    props: Dict[str, Any] = {
        PROP_SECTION: {"select": {"name": section}},
        PROP_FILE:    {"files": files_payload},
        PROP_URL:     {"url": urls[0] if urls else None},
        PROP_DATE:    {"date": {"start": today_iso}},
    }
    if comment:
        props[PROP_COMMENT] = {"rich_text": [{"text": {"content": comment}}]}
    return props

def _notion_create_row_files(section: str, file_name: str, urls: List[str], comment: Optional[str]) -> Tuple[bool, str]:
    payload = {"parent": {"database_id": DATABASE_ID}, "properties": _props_files(section, file_name, urls, comment)}
    try:
        r = requests.post("https://api.notion.com/v1/pages", headers=NOTION_HEADERS, json=payload, timeout=30)
    except Exception as e:
        return False, repr(e)
    if r.status_code in (200, 201):
        return True, "ok"
    try:
        j = r.json()
        msg = j.get("message") or j.get("error") or j
        return False, str(msg)
    except Exception:
        return False, r.text

def _notion_create_row_files_retry(section: str, file_name: str, urls: List[str], comment: Optional[str]) -> Tuple[bool, str]:
    last = "error"
    for _ in range(3):
        ok, info = _notion_create_row_files(section, file_name, urls, comment)
        if ok:
            return True, info
        last = info
        time.sleep(1.2)
    return False, last

# ===== /start =====
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👷 Привет! Я Карманный Прораб.\n"
        "Нажми кнопку ниже, чтобы добавить фото к нужному разделу проекта:",
        reply_markup=main_menu()
    )
    await update.message.reply_text("Быстрые действия:", reply_markup=quick_inline_menu())

# ===== Автоприветствие =====
async def on_first_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("welcomed"):
        return
    context.user_data["welcomed"] = True
    if update.message:
        await update.message.reply_text(
            "👷 Привет! Я Карманный Прораб.\n"
            "Нажми кнопку ниже, чтобы добавить фото:",
            reply_markup=main_menu()
        )
        await update.message.reply_text("Быстрые действия:", reply_markup=quick_inline_menu())

# ===== /sync =====
async def cmd_sync(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Синхронизация структуры…")
    try:
        info = sync_structure()
        await update.message.reply_text(
            f"✓ Готово. Корень: {info['root']}\nРазделов: {len(info['paths'])}",
            reply_markup=main_menu()
        )
    except Exception as e:
        await update.message.reply_text(f"✗ Ошибка синхронизации: {e}")

# ===== Клавиатуры для выбора разделов =====
def _kb_for_parent(parent_path: str) -> InlineKeyboardMarkup:
    children = structure_children(parent_path)
    rows: List[List[InlineKeyboardButton]] = []
    row: List[InlineKeyboardButton] = []
    for name in children:
        full = f"{parent_path}/{name}" if parent_path else name
        pid = _id_for_path(full)
        row.append(InlineKeyboardButton(f"📂 {name}", callback_data=f"p|{pid}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    ctrl: List[InlineKeyboardButton] = []
    if parent_path:
        parent_parent = "/".join(parent_path.split("/")[:-1])
        bid = _id_for_path(parent_parent)
        ctrl.append(InlineKeyboardButton("⬅️ Назад", callback_data=f"b|{bid}"))
    cid = _id_for_path(parent_path)
    ctrl.append(InlineKeyboardButton("✅ Выбрать здесь", callback_data=f"c|{cid}"))
    rows.append(ctrl)
    return InlineKeyboardMarkup(rows)

# ===== Быстрый старт по inline =====
async def photo_quick_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    context.user_data["cursor_path"] = ""
    root, _ = structure_load_index()
    if not STRUCT_INDEX:
        await query.edit_message_text("Похоже, список разделов пустой. Запусти /sync.")
        return
    await query.edit_message_text(f"Выбери раздел проекта (корень: {root}):")
    await query.message.reply_text(text="Навигация по разделам:", reply_markup=_kb_for_parent(""))
    return PH1_WAIT_SECTION

# ===== /photo =====
async def photo_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.user_data["cursor_path"] = ""
    root, _ = structure_load_index()
    if not STRUCT_INDEX:
        await update.message.reply_text("Похоже, список разделов пустой. Нажми /sync, чтобы обновить структуру.")
        return ConversationHandler.END
    await update.message.reply_text(
        f"Выбери раздел проекта (корень: {root}):",
        reply_markup=_kb_for_parent("")
    )
    return PH1_WAIT_SECTION

async def photo_pick_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = (query.data or "").strip()
    act, _, pid = data.partition("|")
    path = _path_by_id(pid)

    if act in ("p", "b", "c") and path is None:
        await query.answer("Меню устарело, начните заново: /photo", show_alert=True)
        return PH1_WAIT_SECTION

    if act in ("p", "b"):
        context.user_data["cursor_path"] = path
        text = f"Раздел: {format_path_for_notion(path) if path else 'Корень'}\nВыбери подраздел:"
        await query.edit_message_text(text=text, reply_markup=_kb_for_parent(path))
        return PH1_WAIT_SECTION

    if act == "c":
        if not path:
            await query.answer("Нужно выбрать хоть какой-то раздел.", show_alert=True)
            return PH1_WAIT_SECTION

        context.user_data["section_path"] = path
        nice = format_path_for_notion(path)

        cam_base = os.getenv("GHPAGES_CAMERA_URL",
                             "https://intellectumadmin.github.io/PocketForeman/camera.html")
        folder = f"{STRUCT_ROOT}/{path}" if STRUCT_ROOT else path
        cam_url = (
            f"{cam_base}"
            f"?cloud={quote(CLOUD_NAME)}"
            f"&preset={quote(CLOUD_UNSIGNED_PRESET)}"
            f"&folder={quote(folder)}"
            f"&section={quote(nice)}"
            f"&cam=back"
        )

        await query.edit_message_text(f"✅ Раздел выбран:\n{nice}\n\nВыбери способ:")

        # большая клавиатура снизу
        await query.message.reply_text(
            "Нажми «📷 Открыть камеру», сделай фото и жми «Отправить».",
            reply_markup=cam_menu(cam_url)
        )

        # маленькая inline-кнопка: «Из галереи»
        kb_inline = InlineKeyboardMarkup(
            [[InlineKeyboardButton("📎 Из галереи", callback_data="ask_gallery")]]
        )
        await query.message.reply_text("Или прикрепи фото из галереи (можно сразу несколько):", reply_markup=kb_inline)
        await query.message.reply_text("Пришли фото одним сообщением: можно сразу несколько (альбом).")
        return PH2_WAIT_PHOTO

    await query.answer("Неизвестная команда.", show_alert=True)
    return PH1_WAIT_SECTION

# ===== Галерея / приём фото (одного или альбома) =====
async def on_ask_gallery(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.effective_message.reply_text(
        "Пришли фото одним сообщением: можно сразу несколько (альбом).",
        reply_markup=ReplyKeyboardRemove()
    )
    return PH2_WAIT_PHOTO

async def ph2_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Собираем либо одно фото, либо альбом (media_group).
    Хитрость: Telegram присылает альбом серией сообщений с одинаковым media_group_id.
    Мы складываем кадры в context.user_data['mg']['photos'], а завершение — по твоему комментарию.
    """
    if not update.message or not update.message.photo:
        await update.message.reply_text("Это не фото. Пришли изображение (или альбом одним сообщением).")
        return PH2_WAIT_PHOTO

    mgid = update.message.media_group_id
    if mgid:
        bucket = context.user_data.get("mg")
        if not bucket or bucket.get("id") != mgid:
            bucket = {"id": mgid, "photos": []}
            context.user_data["mg"] = bucket

        # достаём bytes
        ph = update.message.photo[-1]
        file = await ph.get_file()
        bio = io.BytesIO()
        await file.download_to_memory(out=bio)
        bio.seek(0)
        bucket["photos"].append(bio.read())

        # молча ждём остальные кадры; запросим комментарий один раз – после любой фотки
        if len(bucket["photos"]) == 1:
            await update.message.reply_text("Комментарий (опционально) или «-» — когда все фото загрузятся:")
        return PH3_WAIT_COMMENT

    # одиночное фото
    ph = update.message.photo[-1]
    file = await ph.get_file()
    bio = io.BytesIO()
    await file.download_to_memory(out=bio)
    bio.seek(0)
    context.user_data["photo_bytes"] = bio.read()

    await update.message.reply_text("Комментарий (опционально) или «-»:")
    return PH3_WAIT_COMMENT

async def ph3_comment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text_in = (update.message.text or "").strip()

    # Служебные кнопки
    if text_in == BTN_CANCEL:
        context.user_data.clear()
        await update.message.reply_text("Операция отменена.", reply_markup=main_menu())
        return ConversationHandler.END
    if text_in == BTN_CHANGE:
        context.user_data.pop("section_path", None)
        context.user_data.pop("photo_bytes", None)
        context.user_data.pop("mg", None)
        root, _ = structure_load_index()
        await update.message.reply_text(f"Выбери новый раздел (корень: {root}):", reply_markup=_kb_for_parent(""))
        return PH1_WAIT_SECTION

    comment = None if text_in in ("-", "—", "") else text_in

    section_path = context.user_data.get("section_path", "")
    if not section_path:
        await update.message.reply_text("Раздел потерян. Попробуй /photo заново.", reply_markup=main_menu())
        return ConversationHandler.END

    # Готовим список байтов: одиночное фото или медиа-группа
    photos_bytes: List[bytes] = []
    if "mg" in context.user_data and context.user_data["mg"].get("photos"):
        photos_bytes = context.user_data["mg"]["photos"]
    elif "photo_bytes" in context.user_data:
        photos_bytes = [context.user_data["photo_bytes"]]
    else:
        await update.message.reply_text("Не нашёл фото в сессии. Начни заново: /photo", reply_markup=main_menu())
        return ConversationHandler.END

    # Загрузка в Cloudinary
    folder = f"{STRUCT_ROOT}/{section_path}" if STRUCT_ROOT else section_path
    leaf = section_path.split("/")[-1]
    urls: List[str] = []
    for i, pb in enumerate(photos_bytes):
        public_id = f"{leaf}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{i+1:02d}"
        try:
            up = cloudinary.uploader.upload(pb, folder=folder, public_id=public_id, resource_type="image")
            urls.append(up["secure_url"])
        except Exception as e:
            await update.message.reply_text(f"✗ Ошибка загрузки в Cloudinary: {e}", reply_markup=main_menu())
            return ConversationHandler.END

    # Запись в Notion (Files & media)
    section_for_notion = format_path_for_notion(section_path)
    ok, info = _notion_create_row_files_retry(
        section=section_for_notion, file_name="Фото со стройки", urls=urls, comment=comment
    )

    if ok:
        if len(urls) == 1:
            await update.message.reply_photo(urls[0], caption="✅ Фото загружено и записано в Notion.")
        else:
            await update.message.reply_text(f"✅ Загружено фото: {len(urls)} шт. Добавлено одной строкой в Notion.")
    else:
        await update.message.reply_text(f"⚠️ Загрузка ок, но Notion ответил: {info}")

    # Чистим состояние и показываем меню
    context.user_data.clear()
    await update.message.reply_text("Готово. Что дальше?", reply_markup=main_menu())
    return ConversationHandler.END

# ===== Приём данных из WebApp (camera.html) =====
async def on_webapp_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    wad = getattr(msg, "web_app_data", None)
    if not wad:
        return

    try:
        payload = json.loads(wad.data)
    except Exception as e:
        await msg.reply_text("Не могу прочитать данные камеры.")
        return

    if payload.get("type") != "photo_uploaded":
        return

    url     = payload.get("url")
    section = payload.get("section", "") or "—"
    comment = payload.get("comment") or None

    if not url:
        await msg.reply_text("Не получил ссылку на фото из камеры.")
        return

    ok, info = _notion_create_row_files_retry(
        section=section, file_name="Фото (камера)", urls=[url], comment=comment
    )

    if ok:
        await msg.reply_photo(photo=url, caption=f"✅ Фото из камеры добавлено в Notion.\nРаздел: {section}")
    else:
        await msg.reply_photo(photo=url, caption=f"⚠️ Загрузка ок, но Notion ответил: {info}")

# ===== Универсальный лог всех апдейтов (временно) =====
async def debug_all_updates(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kind = (
        "message" if update.message else
        "edited_message" if update.edited_message else
        "callback_query" if update.callback_query else
        "channel_post" if update.channel_post else
        "unknown"
    )
    has_wad = bool(getattr(update.effective_message, "web_app_data", None)) if update.effective_message else False
    print(f"[DEBUG] update kind={kind}; has_web_app_data={has_wad}")

# ===== Быстрый self-test Notion =====
async def cmd_notionselftest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ok, info = _notion_create_row_files_retry(
        section="Тест",
        file_name="Проверка",
        urls=["https://example.com/test.jpg"],
        comment="selftest"
    )
    await update.message.reply_text(f"Notion selftest: {'OK' if ok else 'FAIL'} — {info}")

# ===== Обработчики нижней клавиатуры вне диалога =====
async def on_text_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (update.message.text or "").strip()
    if txt == BTN_CHANGE:
        root, _ = structure_load_index()
        await update.message.reply_text(f"Выбери раздел проекта (корень: {root}):", reply_markup=_kb_for_parent(""))
        return
    if txt == BTN_CANCEL:
        await update.message.reply_text("Ок, отменил.", reply_markup=main_menu())
        return
    if txt == BTN_ADD_PHOTO:
        await photo_start(update, context)
        return
    # Никаких лишних сообщений тут не шлём — чтобы не появлялось «Выберите действие».

# ===== Отмена =====
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Операция отменена.", reply_markup=main_menu())
    return ConversationHandler.END

# ===== main =====
def main():
    if not BOT_TOKEN:
        raise RuntimeError("Нет TELEGRAM_BOT_TOKEN в .env")
    if not NOTION_TOKEN or not DATABASE_ID:
        raise RuntimeError("Нет NOTION_TOKEN_SCHOOL65 / NOTION_DATABASE_ID_SCHOOL65 в .env")

    # Синхронизация структуры при старте
    try:
        info = sync_structure()
        log.info(f"✓ Структура синхронизирована при старте. Корень: {info['root']}, разделов: {len(info['paths'])}")
    except Exception as e:
        log.warning(f"⚠️ Не удалось автоматически синхронизировать структуру: {e}")

    root, _ = structure_load_index()

    print("=======================================")
    print("INTELLECTUM — Pocket Foreman (Cloudinary → Notion)")
    print(f"Notion DB: {DATABASE_ID[:8]}...{DATABASE_ID[-5:]}")
    print(f"Cloudinary: {cloudinary.config().cloud_name}")
    print(f"Корень Cloudinary: {root}")
    print("Camera page:", os.getenv("GHPAGES_CAMERA_URL"))
    print("Using filter for web_app_data: filters.StatusUpdate.WEB_APP_DATA")
    print("=======================================")

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    admin_chat_id = int(os.getenv("ADMIN_CHAT_ID", "0"))

    # SafeSync watcher (async callback)
    async def _start_safe_sync_once(context):
        safe_sync = start_safe_sync(app, admin_chat_id=admin_chat_id)
        app.bot_data["safe_sync"] = safe_sync
        print("[SafeSync] ✅ Запущен наблюдатель за structure.txt")
    app.job_queue.run_once(_start_safe_sync_once, 1.0)

    async def _on_safe_sync_callback(update, context):
        ss = context.application.bot_data.get("safe_sync")
        if ss:
            await ss.on_callback(update, context)
    app.add_handler(CallbackQueryHandler(_on_safe_sync_callback, pattern=r"^safesync:(apply|cancel)\|\d+$"))

    # /photo диалог
    ADD_PHOTO_PATTERN = r"(?i)(?:^|\s)добавить фото$"
    photo_conv = ConversationHandler(
        entry_points=[
            CommandHandler("photo", photo_start),
            MessageHandler(filters.Regex(ADD_PHOTO_PATTERN), photo_start),
        ],
        states={
            PH1_WAIT_SECTION: [CallbackQueryHandler(photo_pick_cb, pattern=r"^(p|b|c)\|")],
            PH2_WAIT_PHOTO: [
                CallbackQueryHandler(on_ask_gallery, pattern=r"^ask_gallery$"),
                MessageHandler(filters.PHOTO, ph2_photo),
            ],
            PH3_WAIT_COMMENT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, ph3_comment),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        name="photo_conv",
        persistent=False,
    )

    # Команды
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("sync", cmd_sync))
    app.add_handler(CommandHandler("notionselftest", cmd_notionselftest))

    # Диалог
    app.add_handler(photo_conv)
    app.add_handler(CallbackQueryHandler(photo_quick_start, pattern=r"^go$"))

    # 1) Приём данных от WebApp (должен стоять ПЕРЕД общей обработкой)
    app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, on_webapp_data))

    # 2) Универсальный дебаг (можно оставить)
    app.add_handler(MessageHandler(filters.ALL, debug_all_updates))

    # 3) Кнопки по умолчанию (без лишних сообщений)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text_buttons))

    log.info("Pocket Foreman (Cloudinary -> Notion) is starting...")
    app.run_polling()

if __name__ == "__main__":
    main()
