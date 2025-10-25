# preview_tasks.py
import os, re

PATH = "tasks_to_add.txt"

print("cwd:", os.getcwd())
print("file exists:", os.path.exists(PATH))

with open(PATH, "r", encoding="utf-8") as f:
    lines = f.readlines()
print("lines:", len(lines))

def clean(s: str) -> str:
    # нормализуем хитрые символы, пробелы, табы и т.п.
    return re.sub(r"\s+", " ",
                  s.replace("＠", "@").replace("\u2060", "").replace("\u00A0", " ")
                 ).strip()

def parse(raw: str):
    if not raw.strip():
        return None, None, "EMPTY"
    raw = clean(raw.rstrip("\r\n"))
    if raw.startswith(("#", "//", "--")):
        return None, None, "COMMENT"
    if "@" in raw:
        left, right = raw.split("@", 1)
        name = clean(left)
        obj  = clean(right) or None
        return name, obj, "OK@"
    return raw, None, "OK"

ok = 0
for i, ln in enumerate(lines, 1):
    name, obj, why = parse(ln)
    print(f"{i:02d} | {why:8} | name={name!r} | obj={obj!r}")
    if why.startswith("OK") and name:
        ok += 1

print(f"\nvalid: {ok} of {len(lines)}")
