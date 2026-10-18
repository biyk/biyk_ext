import sys, os

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "ydisk_catalog.db")

if len(sys.argv) < 2:
    print("Usage: python find_in_disk.py <query> [query2 ...]")
    sys.exit(1)

queries = sys.argv[1:]

import ydisk_db
conn = ydisk_db.connect(DB)

def size_str(size):
    if size > 1024 * 1024 * 1024:
        return f"{size/1024/1024/1024:.1f}GB"
    if size > 1024 * 1024:
        return f"{size/1024/1024:.1f}MB"
    if size > 1024:
        return f"{size/1024:.0f}KB"
    return f"{size}B"

for q in queries:
    rows = conn.execute(
        "SELECT name, path, type, size FROM items WHERE instr(name_lower, ?) > 0 "
        "ORDER BY type, name", (q.lower(),)).fetchall()
    print(f"\n=== \"{q.lower()}\" — {len(rows)} results ===")
    dirs = [r for r in rows if r["type"] == "dir"]
    files = [r for r in rows if r["type"] == "file"]
    if dirs:
        print(f"  Directories ({len(dirs)}):")
        for r in dirs:
            print(f"    {r['name']}")
            print(f"      {r['path']}")
    if files:
        print(f"  Files ({len(files)}):")
        for r in files:
            print(f"    {size_str(r['size'] or 0):>8s}  {r['name']}")
            print(f"      {r['path']}")

conn.close()
