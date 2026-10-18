"""One-time migration: ydisk_catalog.json -> ydisk_catalog.db (replaces old JSON storage)."""
import json, os, sys, time
import ydisk_db

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
JSON_FILE = os.path.normpath(os.path.join(SCRIPT_DIR, "..", "data", "ydisk_catalog.json"))
DB_FILE = os.path.normpath(os.path.join(SCRIPT_DIR, "..", "data", "ydisk_catalog.db"))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

print(f"Reading {JSON_FILE} ...", flush=True)
with open(JSON_FILE, "r", encoding="utf-8") as f:
    data = json.load(f)

rows = []
listed = set()
stack = [data.get("items", [])]
while stack:
    for it in stack.pop():
        rows.append(ydisk_db.row_values(it))
        if it.get("type") == "dir":
            if "children" in it:
                listed.add(it["path"])
                stack.append(it["children"])
            # dir without children key = never fully listed -> listed stays 0

print(f"Rows: {len(rows)}, listed dirs: {len(listed)}", flush=True)

conn = ydisk_db.connect(DB_FILE)
conn.execute("BEGIN")
conn.execute("DELETE FROM items")
conn.executemany(ydisk_db.UPSERT_ITEM, rows)
conn.execute(ydisk_db.UPSERT_ITEM, ydisk_db.row_values(
    {"path": "/", "name": data.get("root_name", "/"), "type": "dir"}))
listed.add("/")
for i in range(0, len(listed), 900):
    conn.executemany("UPDATE items SET listed = 1 WHERE path = ?",
                     [(p,) for p in list(listed)[i:i + 900]])
ydisk_db.set_meta(conn, "source", data.get("source", ""))
ydisk_db.set_meta(conn, "root_name", data.get("root_name", ""))
ydisk_db.set_meta(conn, "migrated", time.strftime("%Y-%m-%d %H:%M:%S"))
conn.commit()

dirs, files = ydisk_db.counts(conn)
unlisted = conn.execute(
    "SELECT COUNT(*) FROM items WHERE type = 'dir' AND listed = 0").fetchone()[0]
print(f"Written: {DB_FILE} ({os.path.getsize(DB_FILE) / 1024 / 1024:.0f}MB)", flush=True)
print(f"Catalog: {dirs} dirs, {files} files ({unlisted} dirs not listed -> scan will refetch)", flush=True)
conn.close()
