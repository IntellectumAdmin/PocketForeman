# -*- coding: utf-8 -*-
"""
Pocket Foreman: Cloudinary -> Notion
- SafeSync структуры
- /photo: выбор раздела
- Галерея: ОДНО или НЕСКОЛЬКО фото (альбом одним сообщением)
- Камера: WebApp (camera.html)
"""

import os, io, json, time, logging
from datetime import datetime
from typing import Dict, Any, Optional, List, Tuple
from pathlib import Path
from urllib.parse import quote

from dotenv import load_dotenv
import requests
import cloudinary, cloudinary.uploader

from structure_safe_sync import start_safe_sync
from structure_sync import sync_structure

from telegram import (
    InlineKeyboardButton, InlineKeyboardMarkup, Update,
    KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove, WebAppInfo,
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, ConversationHandler,
    CallbackQueryHandler, ContextTypes, filters,
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
PROP_FILE    = os.getenv("PROP_FILE", "Файл / Фото")   # Files & media
PROP_URL     = os.getenv("PROP_URL", "Ссылка OneDrive")  # оставим как видимую URL (Cloudinary)
PROP_DATE    = os.getenv("PROP_DATE", "Дата")
PROP_COMMENT = os.getenv("PROP_COMMENT", "Комментарий")

# === Кэш структуры ===
STRUCTURE_CACHE_PATH = Path("structure_cache.json")
STRUCT_ROOT = "Школа_65"
STRUCT_INDEX: Dict[str, List[str]] = {}

# ==== Кнопки ====
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

def quick_inline_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("📸 Добавить фото", callback_data="go")]])

# ===== Cloudinary config =====
if not (CLOUD_NAME and CLOUD_API_KEY and CLOUD_API_SECRET):
    raise RuntimeError("Заполни CLOUD_NAME/CLOUD_API_KEY/CLOUD_API_SECRET в .env")
cloudinary.config(cloud_name=CLOUD_NAME, api_key=CLOUD_API_KEY, api_secret=CLOUD_API_SECRET, secure=True)

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

# ===== Короткие id для inline =====
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

# ===== Notion helpers =====
def _notion_payload(section: str, file_name: str, url: str, comment: Optional[str]) -> Dict[str, Any]:
    today_iso = datetime.now().strftime("%Y-%m-%d")
    props: Dict[str, Any] = {
        PROP_SECTION: {"select": {"name": section}},
        # Files & media + внешний URL
        PROP_FILE: {"files": [{"type": "external", "name": file_name, "external": {"url": url}}]},
        PROP_URL:   {"url": url},
        PROP_DATE:  {"date": {"start": today_iso}},
    }
    if comment:
        props[PROP_COMMENT] = {"rich_text": [{"text": {"content": comment}}]}
    return {"parent": {"database_id": DATABASE_ID}, "properties": props}

def _notion_create_row(section: str, file_name: str, url: str, comment: Optional[str]) -> Tuple[bool, str]:
    payload = _notion_payload(section, file_name, url, comment)
    for _ in range(3):
        try:
            r = requests.post("https://api.notion.com/v1/pages", headers=NOTION_HEADERS, json=payload, timeout=30)
            if r.status_code in (200, 201):
                return True, "ok"
            try:
                j = r.json()
                msg = j.get("message") or j.get("error") or j
                info = str(msg)
            except Exception:
                info = r.text
        except Exception as e:
            info = repr(e)
        time.sleep(1.0)
    return False, info

# ===== /start =====
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👷 Привет! Я Карманный Прораб.\nНажми кнопку ниже, чтобы добавить фото:",
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

# ===== Клавиатуры для разделов =====
def _kb_for_parent(parent_path: str) -> InlineKeyboardMarkup:
    children = structure_children(parent_path)
    rows: List[List[InlineKeyboardButton]] = []
    row: List[InlineKeyboardButton] = []
    for name in children:
        full = f"{parent_path}/{name}" if parent_path else name
        pid = _id_for_path(full)
        row.append(InlineKeyboardButton(f"📂 {name}", callback_data=f"p|{pid}"))
        if len(row) == 2:
            rows.append(row); row = []
    if row: rows.append(row)
    ctrl: List[InlineKeyboardButton] = []
    if parent_path:
        parent_parent = "/".join(parent_path.split("/")[:-1])
        ctrl.append(InlineKeyboardButton("⬅️ Назад", callback_data=f"b|{_id_for_path(parent_parent)}"))
    ctrl.append(InlineKeyboardButton("✅ Выбрать здесь", callback_data=f"c|{_id_for_path(parent_path)}"))
    rows.append(ctrl)
    return InlineKeyboardMarkup(rows)

# ===== Быстрый старт =====
async def photo_quick_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data.clear()
    context.user_data["cursor_path"] = ""
    root, _ = structure_load_index()
    if not STRUCT_INDEX:
        await q.edit_message_text("Похоже, список разделов пустой. Запусти /sync.")
        return
    await q.edit_message_text(f"Выбери раздел проекта (корень: {root}):")
    await q.message.reply_text(text="Навигация по разделам:", reply_markup=_kb_for_parent(""))
    return PH1_WAIT_SECTION

# ===== /photo =====
async def photo_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.user_data["cursor_path"] = ""
    root, _ = structure_load_index()
    if not STRUCT_INDEX:
        await update.message.reply_text("Похоже, список разделов пустой. Нажми /sync.")
        return ConversationHandler.END
    await update.message.reply_text(f"Выбери раздел проекта (корень: {root}):", reply_markup=_kb_for_parent(""))
    return PH1_WAIT_SECTION

async def photo_pick_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    act, _, pid = (q.data or "").strip().partition("|")
    path = _path_by_id(pid)

    if act in ("p", "b") and path is not None:
        context.user_data["cursor_path"] = path
        txt = f"Раздел: {format_path_for_notion(path) if path else 'Корень'}\nВыбери подраздел:"
        await q.edit_message_text(txt, reply_markup=_kb_for_parent(path))
        return PH1_WAIT_SECTION

    if act == "c":
        if not path:
            await q.answer("Нужно выбрать раздел.", show_alert=True); return PH1_WAIT_SECTION
        context.user_data["section_path"] = path
        nice = format_path_for_notion(path)

        cam_base = os.getenv("GHPAGES_CAMERA_URL", "https://intellectumadmin.github.io/PocketForeman/camera.html")
        folder = f"{STRUCT_ROOT}/{path}" if STRUCT_ROOT else path
        cam_url = (f"{cam_base}?cloud={quote(CLOUD_NAME)}&preset={quote(CLOUD_UNSIGNED_PRESET)}"
                   f"&folder={quote(folder)}&section={quote(nice)}&cam=back")

        await q.edit_message_text(f"✅ Раздел выбран:\n{nice}\n\nВыбери способ:")
        await q.message.reply_text("Нажми «📷 Открыть камеру», сделай фото и жми «Отправить».", reply_markup=cam_menu(cam_url))
        await q.message.reply_text("Или прикрепи фото из галереи (можно сразу несколько):",
                                   reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📎 Из галереи", callback_data="ask_gallery")]]))
        await q.message.reply_text("Пришли фото одним сообщением: можно сразу несколько (альбом).")
        return PH2_WAIT_PHOTO

    await q.answer("Меню устарело, начни заново: /photo", show_alert=True)
    return PH1_WAIT_SECTION

# ===== Галерея =====
async def on_ask_gallery(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.effective_message.reply_text(
        "Пришли фото одним сообщением. Можно сразу несколько (альбом).",
        reply_markup=ReplyKeyboardRemove()
    )
    return PH2_WAIT_PHOTO

# --- буфер для альбомов ---
ALBUM_KEY = "album_buffer"  # chat-level
ALBUM_DELAY = 1.2           # сек ожидания «хвоста» альбома

async def _finalize_album(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.chat_id
    buf: Dict[str, Dict[str, Any]] = context.chat_data.get(ALBUM_KEY, {})
    job_gid = context.job.data["gid"]
    pack = buf.pop(job_gid, None)
    if not pack: return

    # Сохраним набор байт в user_data и попросим комментарий
    context.user_data["photo_bytes_list"] = pack["bytes"]  # List[bytes]
    await context.bot.send_message(chat_id, "Комментарий (опционально) или «-»:",
                                   reply_markup=ReplyKeyboardMarkup([[KeyboardButton(BTN_CHANGE), KeyboardButton(BTN_CANCEL)]],
                                                                    resize_keyboard=True))

async def ph2_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.photo:
        await msg.reply_text("Это не фото. Пришли изображение.")
        return PH2_WAIT_PHOTO

    # Альбом?
    gid = msg.media_group_id
    if gid:
        buf = context.chat_data.setdefault(ALBUM_KEY, {})
        pack = buf.setdefault(gid, {"bytes": [], "job": None})
        # берём самое крупное превью
        file = await msg.photo[-1].get_file()
        bio = io.BytesIO(); await file.download_to_memory(out=bio); bio.seek(0)
        pack["bytes"].append(bio.read())
        # перезапускаем таймер
        if pack["job"]:
            pack["job"].schedule_removal()
        pack["job"] = context.job_queue.run_once(_finalize_album, ALBUM_DELAY, chat_id=msg.chat_id, data={"gid": gid})
        return PH2_WAIT_PHOTO

    # Обычное одиночное фото
    file = await msg.photo[-1].get_file()
    bio = io.BytesIO(); await file.download_to_memory(out=bio); bio.seek(0)
    context.user_data["photo_bytes_list"] = [bio.read()]

    await msg.reply_text(
        "Комментарий (опционально) или «-»:",
        reply_markup=ReplyKeyboardMarkup([[KeyboardButton(BTN_CHANGE), KeyboardButton(BTN_CANCEL)]], resize_keyboard=True)
    )
    return PH3_WAIT_COMMENT

async def ph3_comment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text_in = (update.message.text or "").strip()

    if text_in == BTN_CANCEL:
        context.user_data.clear()
        await update.message.reply_text("Операция отменена.", reply_markup=main_menu())
        return ConversationHandler.END
    if text_in == BTN_CHANGE:
        context.user_data.clear()
        root, _ = structure_load_index()
        await update.message.reply_text(f"Выбери раздел проекта (корень: {root}):", reply_markup=_kb_for_parent(""))
        return PH1_WAIT_SECTION

    comment = None if text_in in ("-", "—", "") else text_in
    section_path = context.user_data.get("section_path", "")
    bytes_list: List[bytes] = context.user_data.get("photo_bytes_list") or []
    if not section_path or not bytes_list:
        await update.message.reply_text("Не нашёл фото/раздел. Начни заново: /photo", reply_markup=main_menu())
        return ConversationHandler.END

    folder = f"{STRUCT_ROOT}/{section_path}" if STRUCT_ROOT else section_path
    leaf = section_path.split("/")[-1]
    ok_total, fail_total = 0, 0
    for b in bytes_list:
        try:
            up = cloudinary.uploader.upload(b, folder=folder, public_id=f"{leaf}_{datetime.now().strftime('%Y%m%d_%H%M%S%f')}",
                                            resource_type="image")
            url = up["secure_url"]
        except Exception as e:
            fail_total += 1
            continue

        section_for_notion = format_path_for_notion(section_path)
        ok, _ = _notion_create_row(section_for_notion, "Фото со стройки", url, comment)
        ok_total += 1 if ok else 0
        fail_total += 0 if ok else 1
        time.sleep(0.25)  # чуть разгрузим

    if ok_total:
        await update.message.reply_text(f"✓ Загружено: {ok_total}.", reply_markup=ReplyKeyboardRemove())
    if fail_total:
        await update.message.reply_text(f"⚠️ Не удалось загрузить: {fail_total}.", reply_markup=ReplyKeyboardRemove())

    await update.message.reply_text("Готово. Что дальше?", reply_markup=main_menu())
    context.user_data.clear()
    return ConversationHandler.END

# ===== Камера (WebApp) =====
async def on_webapp_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    wad = getattr(msg, "web_app_data", None)
    log.info("[WAD] received: %s", bool(wad))
    if not wad:
        return
    try:
        payload = json.loads(wad.data)
    except Exception as e:
        log.warning("[WAD] bad JSON: %s; raw=%s", e, getattr(wad, "data", None))
        await msg.reply_text("Не могу прочитать данные камеры."); return

    log.info("[WAD] payload: %s", payload)
    if payload.get("type") != "photo_uploaded":
        return

    url     = payload.get("url")
    section = payload.get("section", "") or "—"
    comment = payload.get("comment") or None
    if not url:
        await msg.reply_text("Не получил ссылку на фото из камеры."); return

    ok, info = _notion_create_row(section, "Фото (камера)", url, comment)
    if ok:
        # покажем превью + подтверждение
        await msg.reply_photo(photo=url, caption=f"✅ Фото загружено и добавлено в Notion.\nРаздел: {section}")
    else:
        await msg.reply_text(f"⚠️ Загрузка Ok, но Notion ответил: {info}")

# ===== Диагностика =====
async def debug_all_updates(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kind = ("message" if update.message else
            "edited_message" if update.edited_message else
            "callback_query" if update.callback_query else
            "channel_post" if update.channel_post else "unknown")
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
        log.info(f"✓ Структура синхронизирована. Корень: {info['root']}, разделов: {len(info['paths'])}")
    except Exception as e:
        log.warning(f"⚠️ Автосинхронизация структуры не удалась: {e}")

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
        entry_points=[CommandHandler("photo", photo_start), MessageHandler(filters.Regex(ADD_PHOTO_PATTERN), photo_start)],
        states={
            PH1_WAIT_SECTION: [CallbackQueryHandler(photo_pick_cb, pattern=r"^(p|b|c)\|")],
            PH2_WAIT_PHOTO:   [CallbackQueryHandler(on_ask_gallery, pattern=r"^ask_gallery$"),
                               MessageHandler(filters.PHOTO, ph2_photo)],
            PH3_WAIT_COMMENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, ph3_comment)],
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

    # Приём данных от WebApp (камера) — ставим ПЕРЕД общими обработчиками
    app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, on_webapp_data))

    # Универсальный дебаг (внизу, чтобы не перехватывал ничего важного)
    app.add_handler(MessageHandler(filters.ALL, debug_all_updates))

    log.info("Pocket Foreman (Cloudinary -> Notion) is starting...")
    app.run_polling(allowed_updates=None)  # None = все типы
    # при желании: allowed_updates=["message","callback_query","my_chat_member","chat_member","chat_join_request"]

if __name__ == "__main__":
    main()
