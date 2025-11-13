# -*- coding: utf-8 -*-
"""
Pocket Foreman: Cloudinary -> Notion
- SafeSync структуры
- Главное меню и /photo (WebApp-камера или из галереи)
- Приём web_app_data (камера)
"""

import os, io, re, json, time, logging
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
    KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove, WebAppInfo
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, ConversationHandler,
    CallbackQueryHandler, ContextTypes, filters
)
from telegram._update import Update as _RawUpdate

# ===== Логи (глушим httpx-спам) =====
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("pf-bot")
for noisy in ("httpx", "urllib3", "cloudinary"):
    logging.getLogger(noisy).setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("telegram.ext._application").setLevel(logging.WARNING)
    
# ===== .env =====
load_dotenv()

# === Notion ===
NOTION_TOKEN = os.getenv("NOTION_TOKEN_SCHOOL65", "")
DATABASE_ID  = os.getenv("NOTION_DATABASE_ID_SCHOOL65", "")

# === Cloudinary ===
CLOUD_NAME        = os.getenv("CLOUD_NAME", "")
CLOUD_API_KEY     = os.getenv("CLOUD_API_KEY", "")
CLOUD_API_SECRET  = os.getenv("CLOUD_API_SECRET", "")
CLOUD_UNSIGNED_PRESET = os.getenv("CLOUD_UNSIGNED_PRESET", "pf_unsigned")

# === Telegram ===
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

# === Колонки в Notion ===
PROP_SECTION = os.getenv("PROP_SECTION", "Раздел")
PROP_FILE    = os.getenv("PROP_FILE", "Файл / Фото")
PROP_URL     = os.getenv("PROP_URL", "Ссылка OneDrive")
PROP_DATE    = os.getenv("PROP_DATE", "Дата")
PROP_COMMENT = os.getenv("PROP_COMMENT", "Комментарий")

# === Кэш структуры ===
STRUCTURE_CACHE_PATH = Path("structure_cache.json")
STRUCT_ROOT = "Школа_65"
STRUCT_INDEX: Dict[str, List[str]] = {}

# ===== Анти-дубль web_app_data =====
RECENT_URLS: Dict[str, float] = {}
def _seen_recent(url: str) -> bool:
    now = time.time()
    for k in list(RECENT_URLS.keys()):
        if now - RECENT_URLS[k] > 120:
            RECENT_URLS.pop(k, None)
    if not url: return False
    if url in RECENT_URLS: return True
    RECENT_URLS[url] = now
    return False

# ==== Главное меню (только нижняя кнопка) ====
BTN_START     = "▶️ Старт"
BTN_ADD_PHOTO = "📸 Добавить фото"
BTN_OPEN_CAM  = "📷 Открыть камеру"
BTN_CHANGE    = "🔄 Сменить раздел"
BTN_CANCEL    = "❌ Отмена"

def main_menu() -> ReplyKeyboardMarkup:
    # Две нижние кнопки. Никаких дублей в чате.
    return ReplyKeyboardMarkup(
        [[KeyboardButton(BTN_START)], [KeyboardButton(BTN_ADD_PHOTO)]],
        resize_keyboard=True
    )

def cam_menu(cam_url: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(text=BTN_OPEN_CAM, web_app=WebAppInfo(cam_url))],
            [KeyboardButton(text=BTN_CHANGE), KeyboardButton(text=BTN_CANCEL)],
        ],
        resize_keyboard=True,
    )

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
            parent = "/".join(parts[:i]); child = parts[i]
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

# ===== Notion helpers =====
def _notion_create_row_once(section: str, file_name: str, url: str, comment: Optional[str]) -> Tuple[bool, str]:
    today_iso = datetime.now().strftime("%Y-%m-%d")
    props: Dict[str, Any] = {
        PROP_SECTION: {"select": {"name": section}},
        PROP_FILE: {"files": [{"name": file_name, "type": "external", "external": {"url": url}}]},
        PROP_URL: {"url": url},
        PROP_DATE: {"date": {"start": today_iso}},
    }
    if comment:
        props[PROP_COMMENT] = {"rich_text": [{"text": {"content": comment}}]}
    payload = {"parent": {"database_id": DATABASE_ID}, "properties": props}
    r = requests.post("https://api.notion.com/v1/pages", headers=NOTION_HEADERS, json=payload, timeout=30)
    if r.status_code in (200, 201):
        return True, "ok"
    try:
        j = r.json()
        return False, str(j.get("message") or j.get("error") or j)
    except Exception:
        return False, r.text

def _notion_create_row(section: str, file_name: str, url: str, comment: Optional[str]) -> Tuple[bool, str]:
    last = "unknown"
    for _ in range(3):
        ok, info = _notion_create_row_once(section, file_name, url, comment)
        if ok: return True, info
        last = info; time.sleep(1.0)
    return False, last

# ===== Команды =====
async def btn_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Нажал "Старт" → сразу в поток добавления фото
    return await photo_start(update, context)

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👷 Привет! Я Карманный Прораб.\nНажми кнопку ниже, чтобы добавить фото к нужному разделу проекта:",
        reply_markup=main_menu()
    )

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

# ===== Выбор разделов =====
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

async def photo_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    root, _ = structure_load_index()
    if not STRUCT_INDEX:
        await update.message.reply_text("Похоже, список разделов пустой. Нажми /sync.")
        return ConversationHandler.END
    await update.message.reply_text(f"Выбери раздел проекта (корень: {root}):", reply_markup=_kb_for_parent(""))
    return PH1_WAIT_SECTION

async def photo_pick_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    act, _, pid = (query.data or "").partition("|")
    path = _path_by_id(pid)

    if act in ("p", "b"):
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
        ts = int(time.time())
        cam_url = (
            f"{cam_base}"
            f"?cloud={quote(CLOUD_NAME)}"
            f"&preset={quote(CLOUD_UNSIGNED_PRESET)}"
            f"&folder={quote(folder)}"
            f"&section={quote(nice)}"
            f"&cam=back"
            f"&v={ts}"
        )

        # Сообщение о выбранном разделе
        await query.edit_message_text(f"✅ Раздел выбран:\n{nice}\n\nСделайте фото:")

        # ТОЛЬКО нижняя клавиатура с WebApp-кнопкой
        await query.message.reply_text(
            "Откройте камеру, снимите и нажмите «Отправить».",
            reply_markup=cam_menu(cam_url)
        )

        # Оставляем кнопку «Из галереи» (если нужна), она компактная
        kb_inline = InlineKeyboardMarkup(
            [[InlineKeyboardButton("📎 Из галереи", callback_data="ask_gallery")]]
        )
        await query.message.reply_text(
            "Или прикрепите фото из галереи (можно сразу несколько):",
            reply_markup=kb_inline
        )
        return PH2_WAIT_PHOTO

    return PH1_WAIT_SECTION

# ===== Галерея =====
async def on_ask_gallery(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.effective_message.reply_text(
        "Пришлите фото одним сообщением (альбомы тоже можно, возьму первый кадр).",
        reply_markup=ReplyKeyboardRemove()
    )
    return PH2_WAIT_PHOTO

async def ph2_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.photo:
        await update.message.reply_text("Это не фото. Пришлите изображение.")
        return PH2_WAIT_PHOTO
    file = await update.message.photo[-1].get_file()
    bio = io.BytesIO()
    await file.download_to_memory(out=bio); bio.seek(0)
    context.user_data["photo_bytes"] = bio.read()
    await update.message.reply_text(
        "Комментарий (опционально) или «-»:",
        reply_markup=ReplyKeyboardMarkup([[KeyboardButton(BTN_CHANGE), KeyboardButton(BTN_CANCEL)]],
                                         resize_keyboard=True)
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
        await update.message.reply_text(f"Выбери новый раздел (корень: {root}):", reply_markup=_kb_for_parent(""))
        return PH1_WAIT_SECTION

    comment = None if text_in in ("-", "—", "") else text_in
    section_path = context.user_data.get("section_path", "")
    photo_bytes  = context.user_data.get("photo_bytes")
    if not photo_bytes or not section_path:
        await update.message.reply_text("Сессия потеряна. Начни заново: /photo", reply_markup=main_menu())
        return ConversationHandler.END

    folder = f"{STRUCT_ROOT}/{section_path}" if STRUCT_ROOT else section_path
    leaf = section_path.split("/")[-1]
    public_id = f"{leaf}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    try:
        up = cloudinary.uploader.upload(photo_bytes, folder=folder, public_id=public_id, resource_type="image")
        url = up["secure_url"]
    except Exception as e:
        await update.message.reply_text(f"✗ Ошибка загрузки в Cloudinary: {e}", reply_markup=main_menu())
        return ConversationHandler.END

    section_for_notion = format_path_for_notion(section_path)
    ok, info = _notion_create_row(section=section_for_notion, file_name="Фото со стройки", url=url, comment=comment)
    if ok:
        await update.message.reply_text("✓ Фото загружено и добавлено в Notion.", reply_markup=ReplyKeyboardRemove())
    else:
        await update.message.reply_text(f"⚠️ Фото загружено, но Notion вернул ошибку: {info}",
                                        reply_markup=ReplyKeyboardRemove())
    await update.message.reply_text("Готово. Что дальше?", reply_markup=main_menu())
    context.user_data.clear()
    return ConversationHandler.END

# ===== Приём данных из WebApp =====
async def on_webapp_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    wad = getattr(msg, "web_app_data", None)
    if not wad: return
    try:
        payload = json.loads(wad.data)
    except Exception:
        await msg.reply_text("Не могу прочитать данные камеры.", reply_markup=main_menu()); return
    if payload.get("type") != "photo_uploaded": return

    url     = (payload.get("url") or "").strip()
    section = (payload.get("section") or "—")
    comment = payload.get("comment") or None
    if not url:
        await msg.reply_text("Не получил ссылку на фото из камеры.", reply_markup=main_menu()); return
    if _seen_recent(url):
        await msg.reply_text("✓ Принято (повтор).", reply_markup=main_menu()); return

    ok, info = _notion_create_row(section=section, file_name="Фото (камера)", url=url, comment=comment)
    if ok:
        try:
            await msg.reply_photo(photo=url, caption=f"✅ Фото загружено и добавлено в Notion.\nРаздел: {section}")
        except Exception:
            await msg.reply_text("✅ Ссылка сохранена в Notion.")
    else:
        await msg.reply_text(f"⚠️ Notion ответил ошибкой: {info}")
    await msg.reply_text("Готово.", reply_markup=main_menu())

# ===== Кнопки вне диалога =====
async def on_text_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (update.message.text or "").strip()
    if txt == BTN_CHANGE:
        root, _ = structure_load_index()
        await update.message.reply_text(f"Выбери раздел проекта (корень: {root}):", reply_markup=_kb_for_parent(""))
    elif txt == BTN_CANCEL:
        await update.message.reply_text("Ок, отменил.", reply_markup=main_menu())
    elif txt == BTN_ADD_PHOTO:
        await photo_start(update, context)

# ===== main =====
def main():
    if not BOT_TOKEN: raise RuntimeError("Нет TELEGRAM_BOT_TOKEN в .env")
    if not NOTION_TOKEN or not DATABASE_ID: raise RuntimeError("Нет NOTION_TOKEN_SCHOOL65 / NOTION_DATABASE_ID_SCHOOL65 в .env")

    try:
        info = sync_structure()
        log.info(f"✓ Структура синхронизирована при старте. Корень: {info['root']}, разделов: {len(info['paths'])}")
    except Exception as e:
        log.warning(f"⚠️ Не удалось автоматически синхронизировать структуру: {e}")

    structure_load_index()

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    admin_chat_id = int(os.getenv("ADMIN_CHAT_ID", "0"))

    async def _start_safe_sync_once(context):
        safe_sync = start_safe_sync(app, admin_chat_id=admin_chat_id)
        app.bot_data["safe_sync"] = safe_sync
        print("[SafeSync] ✅ Запущен наблюдатель за structure.txt")
    app.job_queue.run_once(_start_safe_sync_once, 1.0)

    # 1) WEB_APP_DATA — ПЕРВЫМ
    app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, on_webapp_data))

    # 2) Диалог /photo
    ADD_PHOTO_PATTERN = r"(?i)(?:^|\s)добавить фото$"
    photo_conv = ConversationHandler(
        entry_points=[CommandHandler("photo", photo_start),
                      MessageHandler(filters.Regex(ADD_PHOTO_PATTERN), photo_start)],
        states={
            PH1_WAIT_SECTION: [CallbackQueryHandler(photo_pick_cb, pattern=r"^(p|b|c)\|")],
            PH2_WAIT_PHOTO:   [CallbackQueryHandler(on_ask_gallery, pattern=r"^ask_gallery$"),
                               MessageHandler(filters.PHOTO, ph2_photo)],
            PH3_WAIT_COMMENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, ph3_comment)],
        },
        fallbacks=[CommandHandler("cancel", lambda u,c: u.message.reply_text("Отменено.", reply_markup=main_menu()))],
        name="photo_conv",
        persistent=False,
    )
    app.add_handler(photo_conv)

    # резерв ловец навигации (вдруг вышли из состояния)
    app.add_handler(CallbackQueryHandler(photo_pick_cb, pattern=r"^(p|b|c)\|"))

    # Кнопка "Старт" внизу — запускает добавление фото без /start
    app.add_handler(MessageHandler(
        filters.Regex(r"^(▶️ Старт|Старт|start|Start)$"),
        btn_start
    ))


    # команды и общие кнопки
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("sync", cmd_sync))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text_buttons))

    print("Pocket Foreman (Cloudinary -> Notion) — running…")
    app.run_polling(allowed_updates=_RawUpdate.ALL_TYPES)

if __name__ == "__main__":
    main()
