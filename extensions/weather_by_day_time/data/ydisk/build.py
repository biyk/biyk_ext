import json, urllib.request, urllib.parse, ssl, sys, os

API = "https://cloud-api.yandex.net/v1/disk/public/resources"
PUBLIC_KEY = "https://disk.yandex.ru/d/S25ICf3RhneLzA"

ssl_ctx = ssl.create_default_context()

def fetch_json(url):
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, context=ssl_ctx, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))

def get_items(folder_path):
    all_items = []
    offset = 0
    limit = 100
    while True:
        params = urllib.parse.urlencode({"public_key": PUBLIC_KEY, "path": folder_path, "limit": limit, "offset": offset})
        data = fetch_json(f"{API}?{params}")
        all_items.extend(data["_embedded"]["items"])
        offset += limit
        if offset >= data["_embedded"]["total"]:
            break
    return all_items

def build_tree(folder_path):
    items = get_items(folder_path)
    tree = []
    for item in items:
        entry = {"name": item["name"], "type": item["type"], "path": item["path"]}
        if item["type"] == "file":
            for k in ("size", "file", "media_type", "mime_type"):
                if k in item:
                    entry[k] = item[k]
        else:
            entry["children"] = build_tree(item["path"])
        tree.append(entry)
    return tree

if __name__ == "__main__":
    print("Collecting data...", flush=True)
    tree = build_tree("/Музыка")
    j = json.dumps(tree, indent=2, ensure_ascii=False)
    with open("data/ydisk/music.json", "w", encoding="utf-8") as f:
        f.write(j)

    def count_files(items):
        n = 0
        for it in items:
            if it["type"] == "file":
                n += 1
            elif "children" in it:
                n += count_files(it["children"])
        return n

    print(f"Done. {len(tree)} top folders, {count_files(tree)} files total")
    print(f"Size: {len(j)/1024:.0f} KB")
