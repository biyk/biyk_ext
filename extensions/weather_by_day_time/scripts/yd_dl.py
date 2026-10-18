"""Get info/download from a Yandex Disk public file link."""
import json, urllib.request, urllib.parse, ssl, sys, os, hashlib, time

API = "https://cloud-api.yandex.net/v1/disk/public/resources"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.normpath(os.path.join(SCRIPT_DIR, "..", "temp"))
OUT_DIR = os.path.normpath(os.path.join(SCRIPT_DIR, "..", "data", "downloads"))
os.makedirs(CACHE_DIR, exist_ok=True)
os.makedirs(OUT_DIR, exist_ok=True)

URL = sys.argv[1] if len(sys.argv) > 1 else "https://disk.yandex.ru/i/7bErQOJiG912Ug"
ctx = ssl.create_default_context()

def cache_key(url):
    h = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return os.path.join(CACHE_DIR, f"yd_{h}.json")

def fetch_meta(public_key):
    cf = cache_key(public_key)
    if os.path.exists(cf):
        age = time.time() - os.path.getmtime(cf)
        if age < 3600:
            print("(from cache)", flush=True)
            with open(cf, "r", encoding="utf-8") as f:
                return json.load(f)
    url = f"{API}?public_key={urllib.parse.quote(public_key)}"
    print(f"Fetching: {url}", flush=True)
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, context=ctx, timeout=60) as r:
        data = json.loads(r.read().decode("utf-8"))
    with open(cf, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return data

data = fetch_meta(URL)
item = data.get("type") and data

print(f"\nName:       {data.get('name', '?')}")
file_type = data.get("type", "?")
print(f"Type:       {file_type}")
if file_type == "file":
    size = data.get("size", 0)
    size_str = f"{size:,} bytes" if size < 1024 else (
        f"{size/1024:,.1f} KB" if size < 1024*1024 else f"{size/1024/1024:,.1f} MB")
    print(f"Size:       {size_str}")
    print(f"MIME:       {data.get('mime_type', '?')}")
    print(f"Media:      {data.get('media_type', '?')}")
    print(f"Created:    {data.get('created', '?')}")
    print(f"Modified:   {data.get('modified', '?')}")
    print(f"MD5:        {data.get('md5', '?')}")
    print(f"SHA256:     {data.get('sha256', '?')}")
    dl_url = data.get("file", "")
    print(f"\nDirect URL:\n{dl_url}")
elif file_type == "dir":
    items = data.get("_embedded", {}).get("items", [])
    print(f"Items:      {len(items)}")
    for i, it in enumerate(items[:20]):
        print(f"  {i+1}. {it['name']} ({it['type']})")
    if len(items) > 20:
        print(f"  ... and {len(items)-20} more")

with open(os.path.join(OUT_DIR, f"{os.path.basename(SCRIPT_DIR)}_last_fetch.json"), "w", encoding="utf-8") as f:
    json.dump({"url": URL, "time": time.strftime("%Y-%m-%d %H:%M:%S"), "info": data}, f, ensure_ascii=False, indent=2)
