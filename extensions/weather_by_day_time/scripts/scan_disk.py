"""Incremental Yandex Disk scanner. Re-scans only changed directories. Stores catalog in SQLite."""
import json, urllib.request, urllib.parse, ssl, sys, os, time, threading, hashlib, math, socket
from concurrent.futures import ThreadPoolExecutor, as_completed
import ydisk_db

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

API = "https://cloud-api.yandex.net/v1/disk/public/resources"
PUBLIC_KEY = "https://disk.yandex.ru/d/S25ICf3RhneLzA"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.normpath(os.path.join(SCRIPT_DIR, "..", "temp"))
DB_FILE = os.path.normpath(os.path.join(SCRIPT_DIR, "..", "data", "ydisk_catalog.db"))
CACHE_HOURS = 24
BASE_INTERVAL = 0.2
MAX_DELAY = 60
MAX_WORKERS = 3
COMMIT_EVERY = 1000

ctx = ssl.create_default_context()
lock = threading.RLock()
folder_count = 0
file_count = 0
removed_count = 0
mutations = 0
os.makedirs(CACHE_DIR, exist_ok=True)

class AdaptiveRateLimiter:
    def __init__(self, base=BASE_INTERVAL, max_delay=MAX_DELAY):
        self.base = base; self.max_delay = max_delay
        self.delay = base; self.consecutive_429 = 0
        self._lock = threading.Lock(); self._last = 0.0
    def acquire(self):
        with self._lock:
            now = time.time(); elapsed = now - self._last; d = self.delay
        wait = max(0, d - elapsed)
        if wait > 0: time.sleep(wait)
    def mark(self):
        with self._lock: self._last = time.time()
    def success(self):
        with self._lock:
            if self.consecutive_429 > 0:
                self.delay = max(self.base, math.ceil(self.delay / 2))
            self.consecutive_429 = 0
    def failed(self):
        with self._lock:
            self.consecutive_429 += 1
            if self.consecutive_429 % 5 == 0:
                self.delay = min(self.max_delay, self.delay + 5)
    def stats(self):
        with self._lock: return self.delay, self.consecutive_429
rate_limiter = AdaptiveRateLimiter()

def cache_key(params):
    raw = "&".join(sorted(f"{k}={params[k]}" for k in params))
    h = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return os.path.join(CACHE_DIR, f"{h}.json")

def fetch_cached(path, offset, limit):
    params = {"public_key": PUBLIC_KEY, "path": path, "limit": str(limit), "offset": str(offset)}
    cf = cache_key(params)
    if os.path.exists(cf):
        age = time.time() - os.path.getmtime(cf)
        if age < CACHE_HOURS * 3600:
            with open(cf, "r", encoding="utf-8") as f:
                return json.load(f)
    retries = 0
    while True:
        rate_limiter.acquire()
        url = f"{API}?{urllib.parse.urlencode(params)}"
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, context=ctx, timeout=120) as r:
                data = json.loads(r.read().decode("utf-8"))
            rate_limiter.mark(); rate_limiter.success()
            try:
                with open(cf, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False)
            except OSError:
                pass
            return data
        except urllib.error.HTTPError as e:
            rate_limiter.mark()
            if e.code == 429:
                rate_limiter.failed()
                d, c = rate_limiter.stats()
                print(f"  429 -> delay={d:.1f}s (streak={c})", flush=True)
            elif e.code == 500 or e.code == 502 or e.code == 503:
                retries += 1
                if retries > 5: raise
                print(f"  {e.code} -> retry {retries}/5", flush=True)
                time.sleep(5 * retries)
            else:
                raise
        except (urllib.error.URLError, socket.timeout, ConnectionError, TimeoutError) as e:
            retries += 1
            if retries > 5: raise
            print(f"  timeout/connection error -> retry {retries}/5", flush=True)
            time.sleep(3 * retries)

def fetch_meta(path):
    return fetch_cached(path, 0, 1)

def list_folder(path):
    all_items = []
    offset = 0
    limit = 1000
    while True:
        data = fetch_cached(path, offset, limit)
        all_items.extend(data["_embedded"]["items"])
        offset += limit
        if offset >= data["_embedded"]["total"]:
            break
    return all_items

conn = ydisk_db.connect(DB_FILE)

def walk(path, is_root=False):
    global folder_count, file_count, removed_count, mutations
    meta = fetch_meta(path)
    new_modified = meta.get("modified", "")

    with lock:
        row = ydisk_db.get_row(conn, path)
    if not is_root and row is not None and row["listed"] and row["modified"] == new_modified:
        with lock:
            folder_count += 1
        return

    items = list_folder(path)
    child_dirs = [it["path"] for it in items if it.get("type") == "dir"]

    with lock:
        removed = ydisk_db.upsert_listing(conn, path, new_modified, items)
        folder_count += 1
        file_count += sum(1 for it in items if it.get("type") == "file")
        removed_count += removed
        mutations += len(items) + 1
        if mutations >= COMMIT_EVERY:
            conn.commit(); mutations = 0
        if folder_count % 500 == 0 or file_count % 10000 == 0:
            d, c = rate_limiter.stats()
            print(f"  ... {folder_count} folders, {file_count} files | delay={d:.1f}s 429_streak={c}", flush=True)

    if child_dirs:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            fut_map = {pool.submit(walk, p): p for p in child_dirs}
            for fut in as_completed(fut_map):
                fut.result()

print("Scanning Yandex Disk (incremental, SQLite)...", flush=True)
root_name = fetch_meta("/")["name"]
print(f"Root: {root_name}", flush=True)
prev_missing = -1
walk("/", is_root=True)
conn.commit()

while True:
    missing = [r["path"] for r in conn.execute(
        "SELECT path FROM items WHERE type = 'dir' AND listed = 0 ORDER BY path")]
    if not missing:
        break
    print(f"Filling {len(missing)} unlisted dirs...", flush=True)
    progressed = False
    for p in missing:
        row = ydisk_db.get_row(conn, p)
        if row is None or not row["listed"]:
            try:
                walk(p)
            except urllib.error.HTTPError as e:
                if e.code != 404:
                    raise
                conn.execute(ydisk_db.DELETE_SUBTREE, (p,))
                print(f"  removed deleted dir: {p}", flush=True)
            progressed = True
    conn.commit()
    if not progressed:
        break
    if len(missing) == prev_missing:
        print(f"WARNING: still {len(missing)} unlisted dirs after fill pass", flush=True)
        break
    prev_missing = len(missing)

with lock:
    conn.commit(); mutations = 0
    conn.execute("UPDATE items SET name = ?, name_lower = ? WHERE path = '/'",
                 (root_name, root_name.lower()))
    ydisk_db.set_meta(conn, "source", PUBLIC_KEY)
    ydisk_db.set_meta(conn, "root_name", root_name)
    ydisk_db.set_meta(conn, "last_scan", time.strftime("%Y-%m-%d %H:%M:%S"))
    conn.commit()

dirs, files = ydisk_db.counts(conn)
d, c = rate_limiter.stats()
print(f"\nDone. {folder_count} folders visited this run ({removed_count} removed entries pruned), {file_count} files seen, final delay={d:.1f}s", flush=True)
print(f"DB: {DB_FILE} ({os.path.getsize(DB_FILE) / 1024 / 1024:.0f}MB)", flush=True)
print(f"Catalog total: {dirs} dirs, {files} files", flush=True)
conn.close()
