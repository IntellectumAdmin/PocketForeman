# -*- coding: utf-8 -*-
"""
Отслеживание изменений structure.txt.
При сохранении файла — запускаем sync_structure() и обновляем structure_cache.json,
чтобы бот сразу показывал новую структуру без перезапуска.
"""

import os
import time
import threading
from typing import Optional, Callable

from structure_sync import sync_structure

DEFAULT_FILE = os.getenv("STRUCTURE_FILE", "structure.txt")

def _watch_loop(file_path: str, on_synced: Optional[Callable[[dict], None]] = None):
    """Простой цикл слежения за mtime файла."""
    last_mtime = None
    while True:
        try:
            if os.path.exists(file_path):
                mtime = os.path.getmtime(file_path)
                if last_mtime is None:
                    last_mtime = mtime
                elif mtime != last_mtime:
                    # Файл изменился — синхронизируем
                    info = sync_structure()
                    last_mtime = mtime
                    print(f"[Watcher] ✓ Обновлена структура: root={info.get('root')} paths={len(info.get('paths', []))}")
                    if on_synced:
                        try:
                            on_synced(info)
                        except Exception as e:
                            print(f"[Watcher] on_synced error: {e}")
            else:
                # файла нет — просто ждём
                pass
        except Exception as e:
            print(f"[Watcher] ошибка цикла: {e}")
        time.sleep(2)  # частота проверки

def start_watcher(file_path: Optional[str] = None, on_synced: Optional[Callable[[dict], None]] = None) -> threading.Thread:
    """
    Запустить фонового наблюдателя. Возвращает поток (daemon),
    который можно оставить работать до остановки процесса.
    """
    fp = file_path or DEFAULT_FILE
    t = threading.Thread(target=_watch_loop, args=(fp, on_synced), daemon=True)
    t.start()
    print(f"[Watcher] ▶ Старт. Следим за: {fp}")
    return t
