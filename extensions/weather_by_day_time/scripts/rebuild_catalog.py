"""Rebuild ydisk_catalog.db offline from temp/ API response cache."""
import json, os, sys, glob
from collections import defaultdict
import ydisk_db

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.normpath(os.path.join(SCRIPT_DIR, "..", "temp"))
DB_FILE = os.path.normpath(os.path.join(SCRIPT_DIR, "..", "data", "ydisk_catalog.db"))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

db_target = sys.argv[1] if len(sys.argv) > 1 else DB_FILE

dir_meta = {}
children = defaultdict(dict)
n_files = n_used = n_bad = 0

print(f"Reading cache: {CACHE_DIR}", flush=True)
for fp in glob.iglob(os.path.join(CACHE_DIR, "*.json")):
    n_files += 1
    if n_files % 20000 == 0:
        print(f"  ... {n_files} files", flush=True)
    try:
        with open(fp, encoding="utf-8-sig") as f:
            data = json.load(f)
    except Exception:
        n_bad += 1
        continue
    if not isinstance(data, dict):
        n_bad += 1
        continue
    path = data.get("path")
    emb = data.get("_embedded")
    if not path or not isinstance(emb, dict) or "items" not in emb:
        n_bad += 1
        continue
    rec = dir_meta.setdefault(path, {"total": 0, "modified": "", "name": ""})
    if data.get("modified"):
        rec["modified"] = data["modified"]
    if data.get("name"):
        rec["name"] = data["name"]
    rec["total"] = max(rec["total"], emb.get("total") or 0)
    n_used += 1
    for item in emb.get("items") or []:
        if isinstance(item, dict) and "path" in item:
            children[path][item["path"]] = item

print(f"Cache files: {n_files}, listing responses: {n_used}, skipped: {n_bad}", flush=True)
print(f"Dirs with cached listing: {len(children)}", flush=True)

root_meta = dir_meta.get("/", {})
root_name = root_meta.get("name", "?")
print(f"Root: {root_name}", flush=True)
if "/" not in children:
    print("FATAL: no cached listing for root '/', cannot rebuild", flush=True)
    sys.exit(1)

item_rows = []
listed_dirs = []
incomplete = set()

def visit(path):
    items = children.get(path)
    meta = dir_meta.get(path, {})
    if items is None or len(items) < meta.get("total", 0):
        incomplete.add(path)
    else:
        listed_dirs.append((meta.get("modified") or "", path))
    if items is None:
        return
    for child_path, item in items.items():
        item_rows.append(ydisk_db.row_values(item))
        if item.get("type") == "dir":
            visit(child_path)

visit("/")
print(f"Reachable: {len(item_rows)} rows, dirs without complete listing: {len(incomplete)}", flush=True)

conn = ydisk_db.connect(db_target)
conn.execute("BEGIN")
conn.execute("DELETE FROM items")
conn.executemany(ydisk_db.UPSERT_ITEM, item_rows)
conn.execute(ydisk_db.UPSERT_ITEM, ydisk_db.row_values(
    {"path": "/", "name": root_name, "type": "dir", "modified": root_meta.get("modified")}))
conn.executemany("UPDATE items SET listed = 1, modified = ? WHERE path = ?", listed_dirs)
ydisk_db.set_meta(conn, "source", "https://disk.yandex.ru/d/S25ICf3RhneLzA")
ydisk_db.set_meta(conn, "root_name", root_name)
ydisk_db.set_meta(conn, "last_rebuild", __import__("time").strftime("%Y-%m-%d %H:%M:%S"))
conn.commit()

dirs, files = ydisk_db.counts(conn)
size_mb = os.path.getsize(db_target) / 1024 / 1024
print(f"Written: {db_target} ({size_mb:.0f}MB)", flush=True)
print(f"Catalog: {dirs} dirs, {files} files", flush=True)
if incomplete:
    print(f"{len(incomplete)} dirs have listed=0 — scan_disk.py will refetch them", flush=True)
print("Done.", flush=True)
conn.close()
