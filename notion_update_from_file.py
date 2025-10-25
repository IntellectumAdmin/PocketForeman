# -*- coding: utf-8 -*-
import os, sys

from notion_update import (  # используем функции из первого файла
    normalize, parse_deadline, allowed_statuses, allowed_select,
    find_by_intel_id, find_by_name_contains, patch_page,
    build_props, STATUS_ALIASES, PRIORITY_ALIASES, SIZE_ALIASES,
    TITLE_PROP, NAME_TEXT_PROP
)

INPUT_FILE = "updates.txt"

def is_intel_id(s: str) -> bool:
    s = s.strip().upper()
    return s.startswith("INTEL-") and s[6:].isdigit()

def main():
    if not os.path.exists(INPUT_FILE):
        print(f"Файл {INPUT_FILE} не найден.")
        sys.exit(1)

    allowed_stat = allowed_statuses()
    allowed_pri  = allowed_select("Приоритет")
    allowed_size = allowed_select("Сложность (Size)")

    ok, fail = 0, 0

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line: continue

            parts = [p.strip() for p in line.split(";") if p.strip()]
            ident  = parts[0]
            kv = {}
            for p in parts[1:]:
                if "=" in p:
                    k,v = p.split("=",1)
                    kv[k.strip().upper()] = v.strip()

            new_status   = normalize(kv.get("STATUS"),   STATUS_ALIASES)
            new_deadline = parse_deadline(kv.get("DEADLINE"))
            new_source   = kv.get("SOURCE")
            new_priority = normalize(kv.get("PRIORITY"), PRIORITY_ALIASES)
            new_size     = normalize(kv.get("SIZE"),     SIZE_ALIASES)
            new_name     = kv.get("RENAME")

            if new_status and allowed_stat and new_status not in allowed_stat:
                print(f"⚠ Статус «{new_status}» не найден. Пропускаю строку: {line}")
                fail += 1
                continue
            if new_priority and allowed_pri and new_priority not in allowed_pri:
                print(f"⚠ Приоритет «{new_priority}» не найден. Пропускаю строку: {line}")
                fail += 1
                continue
            if new_size and allowed_size and new_size not in allowed_size:
                print(f"⚠ Сложность «{new_size}» не найдена. Пропускаю строку: {line}")
                fail += 1
                continue

            if is_intel_id(ident):
                page = find_by_intel_id(ident)
                pages = [page] if page else []
            else:
                pages = find_by_name_contains(ident)

            if not pages:
                print(f"✗ Не найдено по идентификатору/подстроке: {ident}")
                fail += 1
                continue

            props = build_props(new_status, new_deadline, new_source, new_priority, new_size, new_name)

            for pg in pages:
                pid = pg["id"]
                if patch_page(pid, props):
                    ok += 1
                    try:
                        t = pg["properties"][TITLE_PROP]["title"][0]["plain_text"]
                        n = pg["properties"][NAME_TEXT_PROP]["rich_text"][0]["plain_text"]
                    except Exception:
                        t=n=""
                    print(f"  ✓ Обновлено: {t} — «{n}»")
                else:
                    fail += 1
                    print(f"  ✗ Ошибка обновления строки: {line}")

    print(f"— Готово. Успешно: {ok}, с ошибками: {fail}")

if __name__ == "__main__":
    main()
