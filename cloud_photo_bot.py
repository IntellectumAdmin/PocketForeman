# -*- coding: utf-8 -*-
"""
Pocket Foreman: Cloudinary -> Notion
- SafeSync структуры
- Главное меню и /photo
- Ветка «Из галереи» (поддержка ОДНОГО фото и альбомов / медиагрупп)
- Ветка «📷 Сделать фото» через WebApp (camera.html)
- Запись в Notion: Files & media (external) + URL (первый)
"""

import os
import io
import json
import time
import logging
from datetime import datetime
from typing import Dict, Any, Optional, List, Tuple
from pathlib import Path
from urllib.parse import quote, urlparse

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
PROP_FILE    = os.getenv("PROP_FILE", "Файл / Фото")          # Files & media
PROP_URL     = os.getenv("PROP_URL", "Ссылка OneDrive")       # кладём первый URL
PROP_DATE    = os.getenv("PROP_DATE", "Дата")
PROP_COMMENT = os.getenv("PROP_COMMENT", "Комментарий")

# === Кэш структуры ===
from pathlib import Path
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

# ===== Вспомогательное =====
def _files_prop_from_urls(urls: List[str]) -> Dict[str, Any]:
    files = []
    for u in urls:
        name = Path(urlparse(u).path).name or "photo.jpg"
        files.append({"type": "external", "name": name, "external": {"url": u}})
    return {"files": files}

# ===== Notion =====
def _notion_create_row_once(section: str, urls: List[str], comment: Optional[str]) -> Tuple[bool, str]:
    today_iso = datetime.now().strftime("%Y-%m-%d")
    props: Dict[str, Any] = {
        PROP_SECTION: {"select": {"name": section}},
        PROP_FILE:    _files_prop_from_urls(urls),
        PROP_DATE:    {"date": {"start": today_iso}},
    }
    if urls:
        props[PROP_URL] = {"url": urls[0]}
    if comment:
        props[PROP_COMMENT] = {"rich_text": [{"text": {"content": comment}}]}

    payload = {"parent": {"database_id": DATABASE_ID}, "properties": props}
    r = requests.post("https://api.notion.com/v1/pages", headers=NOTION_HEADERS, json=payload, timeout=30)
    if r.status_code in (200, 201):
        return True, "ok"
    try:
        j = r.json()
        msg = j.get("message") or j.get("error") or j
        return False, str(msg)
    except Exception:
        return False, r.text

def _notion_create_row(section: str, urls: List[str], comment: Optional[str]) -> Tuple[bool, str]:
    last_info = ""
    for _ in range(3):
        ok, info = _notion_create_row_once(section, urls, comment)
        last_info = info
        if ok:
            return True, info
        time.sleep(1.2)
    return False, last_info

# ===== /start =====
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👷 Привет! Я Карманный Прораб.\nНажми кнопку ниже, чтобы добавить фото к нужному разделу проекта:",
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

# ===== Клавиатуры разделов =====
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

        await query.message.reply_text(
            "Нажми «📷 Открыть камеру», сделай фото и жми «Отправить».",
            reply_markup=cam_menu(cam_url)
        )

        kb_inline = InlineKeyboardMarkup(
            [[InlineKeyboardButton("📎 Из галереи", callback_data="ask_gallery")]]
        )
        await query.message.reply_text("Или прикрепи фото из галереи (можно сразу несколько):", reply_markup=kb_inline)

        return PH2_WAIT_PHOTO

    await query.answer("Неизвестная команда.", show_alert=True)
    return PH1_WAIT_SECTION

# ===== Галерея / медиагруппа =====
async def on_ask_gallery(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.effective_message.reply_text(
        "Пришли фото одним сообщением: можно сразу несколько (альбом).",
        reply_markup=ReplyKeyboardRemove()
    )
    # очистим предыдущие накопления
    context.user_data.pop("album", None)
    context.user_data.pop("album_job", None)
    context.user_data.pop("single_photo", None)
    return PH2_WAIT_PHOTO

async def _album_finalize(context: ContextTypes.DEFAULT_TYPE):
    ud = context.user_data
    album = ud.get("album")
    if not album or not album.get("items"):
        return
    # запросим комментарий для всего альбома
    ud["awaiting_comment_for_album"] = True
    msg = album["message"]
    await msg.reply_text(
        "Комментарий (опционально) или «-»:",
        reply_markup=ReplyKeyboardMarkup([[KeyboardButton(BTN_CHANGE), KeyboardButton(BTN_CANCEL)]],
                                         resize_keyboard=True)
    )

async def ph2_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.photo:
        await msg.reply_text("Это не фото. Пришли изображение.")
        return PH2_WAIT_PHOTO

    # есть ли медиагруппа?
    mgid = msg.media_group_id
    if mgid:
        album = context.user_data.setdefault("album", {"id": mgid, "items": [], "message": msg})
        if album["id"] != mgid:
            # новый альбом — игнорируем старый
            album = {"id": mgid, "items": [], "message": msg}
            context.user_data["album"] = album

        # вытянем байты текущего кадра
        photo = msg.photo[-1]
        file = await photo.get_file()
        bio = io.BytesIO()
        await file.download_to_memory(out=bio)
        bio.seek(0)
        album["items"].append(bio.read())

        # перезапланируем «затухание» финализации
        job = context.user_data.get("album_job")
        if job:
            job.schedule_removal()
        job = context.application.job_queue.run_once(lambda c: _album_finalize(context), 1.2)
        context.user_data["album_job"] = job
        return PH2_WAIT_PHOTO

    # одиночное фото
    photo = msg.photo[-1]
    file = await photo.get_file()
    bio = io.BytesIO()
    await file.download_to_memory(out=bio)
    bio.seek(0)
    context.user_data["single_photo"] = bio.read()

    await msg.reply_text(
        "Комментарий (опционально) или «-»:",
        reply_markup=ReplyKeyboardMarkup([[KeyboardButton(BTN_CHANGE), KeyboardButton(BTN_CANCEL)]],
                                         resize_keyboard=True)
    )
    return PH3_WAIT_COMMENT

async def ph3_comment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text_in = (update.message.text or "").strip()

    # Служебные кнопки
    if text_in == BTN_CANCEL:
        context.user_data.clear()
        await update.message.reply_text("Операция отменена.", reply_markup=main_menu())
        return ConversationHandler.END
    if text_in == BTN_CHANGE:
        context.user_data.clear()
        root, _ = structure_load_index()
        await update.message.reply_text(
            f"Выбери раздел проекта (корень: {root}):",
            reply_markup=_kb_for_parent("")
        )
        return PH1_WAIT_SECTION

    comment = None if text_in in ("-", "—", "") else text_in

    section_path = context.user_data.get("section_path", "")
    if not section_path:
        await update.message.reply_text("Раздел потерян. Попробуй /photo заново.", reply_markup=main_menu())
        return ConversationHandler.END

    # соберём список фото-байтов: либо один, либо альбом
    bytes_list: List[bytes] = []
    album = context.user_data.get("album")
    if album and album.get("items"):
        bytes_list = album["items"]
    elif context.user_data.get("single_photo"):
        bytes_list = [context.user_data["single_photo"]]
    else:
        await update.message.reply_text("Не нашёл фото в сессии. Начни заново: /photo", reply_markup=main_menu())
        return ConversationHandler.END

    # Загрузка всех в Cloudinary
    folder = f"{STRUCT_ROOT}/{section_path}" if STRUCT_ROOT else section_path
    leaf = section_path.split("/")[-1]
    urls: List[str] = []
    try:
        for i, b in enumerate(bytes_list, start=1):
            public_id = f"{leaf}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{i:02d}"
            up = cloudinary.uploader.upload(
                b,
                folder=folder,
                public_id=public_id,
                resource_type="image",
            )
            urls.append(up["secure_url"])
    except Exception as e:
        await update.message.reply_text(f"✗ Ошибка загрузки в Cloudinary: {e}", reply_markup=main_menu())
        return ConversationHandler.END

    section_for_notion = format_path_for_notion(section_path)
    ok, info = _notion_create_row(section=section_for_notion, urls=urls, comment=comment)

    if ok:
        await update.message.reply_text("✓ Фото(а) загружено в Cloudinary и добавлено в Notion.",
                                        reply_markup=ReplyKeyboardRemove())
    else:
        await update.message.reply_text(f"⚠️ Загрузка ок, но Notion ответил: {info}",
                                        reply_markup=ReplyKeyboardRemove())

    await update.message.reply_text("Готово. Что дальше?", reply_markup=main_menu())
    context.user_data.clear()
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
        await msg.reply_text(f"Не могу прочитать данные камеры: {e!r}")
        return

    if payload.get("type") != "photo_uploaded":
        return

    url     = payload.get("url")
    section = payload.get("section", "")
    comment = payload.get("comment") or None

    if not url:
        await msg.reply_text("Не получил ссылку на фото из камеры.")
        return

    try:
        ok, info = _notion_create_row(
            section=section or "—",
            urls=[url],
            comment=comment,
        )
    except Exception as e:
        ok, info = False, repr(e)

    if ok:
        await msg.reply_photo(photo=url,
                              caption=f"✅ Фото загружено в облако и добавлено в Notion.\nРаздел: {section or '—'}")
    else:
        await msg.reply_photo(photo=url,
                              caption=f"⚠️ Загрузка ок, но Notion ответил: {info}")

# ===== Универсальный лог (временно) =====
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

    # SafeSync watcher
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
                MessageHandler(filters.TEXT & ~filters.COMMAND, ensure_menu),
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

    # Диалог
    app.add_handler(photo_conv)
    app.add_handler(CallbackQueryHandler(photo_quick_start, pattern=r"^go$"))

    # Приём данных от WebApp (камеры) — ОБЯЗАТЕЛЬНО раньше общего ALL
    app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, on_webapp_data))

    # Дебаг
    app.add_handler(MessageHandler(filters.ALL, debug_all_updates))

    log.info("Pocket Foreman (Cloudinary -> Notion) is starting...")
    app.run_polling()

if __name__ == "__main__":
    main()
