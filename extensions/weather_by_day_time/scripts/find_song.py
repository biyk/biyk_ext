import json, sys, os, re, difflib, urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MUSIC_JSON = os.path.join(BASE, "data", "ydisk", "music.json")
DOWNLOAD_DIR = os.path.join(BASE, "data", "downloads")

def flatten(items, parent_path=""):
    files = []
    if not items:
        return files
    for it in items:
        if not isinstance(it, dict):
            continue
        name = it.get("name", "?")
        full = f"{parent_path}/{name}" if parent_path else name
        if it.get("type") == "file":
            files.append({
                "name": name,
                "path": full,
                "url": it.get("file", ""),
                "size": it.get("size", 0),
            })
        children = it.get("children")
        if children and isinstance(children, list):
            files.extend(flatten(children, full))
    return files

def normalize(s):
    """Приводит строку к поисковому виду: убирает спецсимволы, лишние пробелы."""
    s = s.lower().strip()
    s = re.sub(r'[—–\-_«»"''\[\](){}]', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s

def score_name(query_norm, name_norm, path_norm):
    """Оценка релевантности от 0 до 100."""
    if not query_norm or not name_norm:
        return 0

    # Полное совпадение
    if name_norm == query_norm:
        return 100
    # Имя начинается с запроса
    if name_norm.startswith(query_norm):
        return 95
    # Запрос целиком содержится в имени
    if query_norm in name_norm:
        return 85
    # Имя целиком содержится в запросе
    if name_norm in query_norm:
        return 75

    # Токены запроса
    q_tokens = set(query_norm.split())
    n_tokens = set(name_norm.split())
    p_tokens = set(path_norm.split())

    if not q_tokens:
        return 0

    # Процент совпавших токенов
    common = q_tokens & n_tokens
    ratio = len(common) / len(q_tokens)

    # Базовый скор от совпавших токенов
    score = round(ratio * 70)

    # Бонус: все токены запроса есть в пути
    if q_tokens.issubset(p_tokens | n_tokens):
        score += 15

    # Бонус за последовательное совпадение подстроки (SequenceMatcher)
    seq = difflib.SequenceMatcher(None, query_norm, name_norm).ratio()
    if seq > 0.5:
        score = max(score, round(seq * 85))

    return min(score, 100)

def search(query, top=10):
    if not os.path.exists(MUSIC_JSON):
        print(f"Error: {MUSIC_JSON} not found. Run gen_music_json.ps1 first.")
        return []

    with open(MUSIC_JSON, "r", encoding="utf-8-sig") as f:
        tree = json.load(f)

    print(f"Loading files...", end=" ", flush=True)
    all_files = flatten(tree)
    print(f"{len(all_files)} files loaded.", flush=True)

    query_norm = normalize(query)

    results = []
    for f in all_files:
        name_norm = normalize(f["name"])
        path_norm = normalize(f["path"])
        score = score_name(query_norm, name_norm, path_norm)
        if score > 0:
            results.append((score, f))

    results.sort(key=lambda x: -x[0])
    results = results[:top]

    print(f"Found {len(results)} results:\n")
    for i, (score, f) in enumerate(results, 1):
        size_kb = f["size"] / 1024 if f["size"] else 0
        print(f"[{i}] ({score}%) {f['name']}")
        print(f"    Path: {f['path']}")
        print(f"    Size: {size_kb:,.0f} KB")
        if f["url"]:
            print(f"    URL:  {f['url'][:120]}...")
        print()

    return results

def download_file(url, dest_path):
    try:
        print(f"Downloading to {dest_path}...", end=" ", flush=True)
        urllib.request.urlretrieve(url, dest_path)
        print("OK", flush=True)
        return True
    except Exception as e:
        print(f"FAILED: {e}", flush=True)
        return False

def prompt_download(results):
    if not results:
        return
    print("-" * 40)
    print("Enter number to download, or 'q' to quit:")
    while True:
        try:
            choice = input("> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if choice in ("q", ""):
            break
        if not choice.isdigit():
            continue
        idx = int(choice) - 1
        if idx < 0 or idx >= len(results):
            print(f"Enter 1-{len(results)} or 'q'")
            continue
        score, f = results[idx]
        if not f.get("url"):
            print(f"No download URL for [{idx+1}] {f['name']}")
            continue
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)
        dest = os.path.join(DOWNLOAD_DIR, f["name"])
        if os.path.exists(dest):
            print(f"Already exists: {dest}")
            continue
        download_file(f["url"], dest)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python find_song.py \"<query>\" [top]")
        sys.exit(1)
    query = sys.argv[1]
    top = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    results = search(query, top)
    prompt_download(results)
