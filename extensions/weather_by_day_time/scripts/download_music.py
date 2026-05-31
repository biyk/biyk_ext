import json, os, sys, urllib.request, urllib.parse, urllib.error, time, zipfile, re

AUDIO_EXTS = {".mp3", ".ogg", ".wav", ".flac", ".m4a", ".webm"}

YANDEX_API = "https://cloud-api.yandex.net/v1/disk/public/resources/download"
YANDEX_PUBLIC_KEY = "https://disk.yandex.ru/d/S25ICf3RhneLzA"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CALENDAR_JSON = os.path.join(BASE, "data", "calendar.json")
MUSIC_JSON = os.path.join(BASE, "data", "ydisk", "music.json")
MUSIC_DIR = os.path.join(BASE, "data", "music")
FOUNDRY_PREFIX = "modules/biyk_ext/extensions/weather_by_day_time/data/music"

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

def refresh_yandex_url(yandex_path):
    try:
        params = urllib.parse.urlencode({"public_key": YANDEX_PUBLIC_KEY, "path": yandex_path})
        req = urllib.request.Request(f"{YANDEX_API}?{params}")
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("href")
    except Exception as e:
        print(f"    URL refresh FAILED: {e}")
        return None

def download(url, dest, yandex_path=None):
    tmp = dest + ".tmp"
    try:
        urllib.request.urlretrieve(url, tmp)
        if os.path.exists(dest):
            os.remove(dest)
        os.rename(tmp, dest)
        return True
    except urllib.error.HTTPError as e:
        if os.path.exists(tmp):
            os.remove(tmp)
        print(f"  FAILED: {e}")
        if e.code in (410, 404) and yandex_path:
            print(f"  URL expired, refreshing from API...", end=" ", flush=True)
            new_url = refresh_yandex_url(yandex_path)
            if new_url:
                try:
                    urllib.request.urlretrieve(new_url, tmp)
                    if os.path.exists(dest):
                        os.remove(dest)
                    os.rename(tmp, dest)
                    print("OK (fresh URL)")
                    return True
                except Exception as e2:
                    if os.path.exists(tmp):
                        os.remove(tmp)
                    print(f"  FAILED: {e2}")
        return False
    except Exception as e:
        if os.path.exists(tmp):
            os.remove(tmp)
        print(f"  FAILED: {e}")
        return False

def extract_zip(zip_path):
    if not zip_path.lower().endswith(".zip"):
        return None
    archive_name = os.path.splitext(os.path.basename(zip_path))[0]
    extract_dir = os.path.join(MUSIC_DIR, archive_name)
    if os.path.isdir(extract_dir):
        print(f"  Already extracted: {extract_dir}")
        return extract_dir
    print(f"  Extracting {os.path.basename(zip_path)}...", end=" ", flush=True)
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(extract_dir)
        print("OK")
        return extract_dir
    except Exception as e:
        print(f"FAILED: {e}")
        return None

def scan_audio(dir_path):
    files = []
    for root, _, names in os.walk(dir_path):
        for n in names:
            ext = os.path.splitext(n)[1].lower()
            if ext in AUDIO_EXTS:
                rel = os.path.relpath(os.path.join(root, n), MUSIC_DIR)
                files.append(rel.replace("\\", "/"))
    return sorted(files)

def main():
    # Load calendar
    with open(CALENDAR_JSON, "r", encoding="utf-8") as f:
        cal = json.load(f)

    # Collect unique music paths from calendar
    cal_paths = {}
    for entry in cal:
        for p in entry.get("music", []):
            cal_paths.setdefault(p, []).append(entry["day"])
    print(f"Unique paths in calendar: {len(cal_paths)}")

    # Load and flatten music catalog
    if not os.path.exists(MUSIC_JSON):
        print(f"Error: {MUSIC_JSON} not found. Run gen_music_json.ps1 first.")
        sys.exit(1)

    with open(MUSIC_JSON, "r", encoding="utf-8-sig") as f:
        tree = json.load(f)
    all_files = flatten(tree)
    print(f"Music catalog files: {len(all_files)}")

    # Build lookup: path -> url
    # music.json paths from Yandex API start with / (e.g. /Music/...)
    # But flattened paths start relative. Normalize to just the relative part.
    lookup = {}
    for f in all_files:
        lookup[f["path"]] = f
        lookup[f"/Музыка/{f['path']}"] = f  # calendar stores paths with /Музыка/ prefix

    # Also build a lookup by name (for fallback matching)
    name_lookup = {}
    for f in all_files:
        name_lookup.setdefault(f["name"], []).append(f)

    # Match calendar paths to music.json entries
    os.makedirs(MUSIC_DIR, exist_ok=True)
    download_map = {}  # old path -> new local path(s)

    total = len(cal_paths)
    downloaded = 0
    skipped = 0
    failed = 0
    extract_count = 0

    for i, (cal_path, days) in enumerate(cal_paths.items(), 1):
        print(f"[{i}/{total}] {cal_path}")

        # Extract filename from path
        filename = os.path.basename(cal_path.replace("/", "\\"))

        # Try direct match by path
        entry = lookup.get(cal_path)

        # Fallback: match by name
        if not entry:
            matches = name_lookup.get(filename, [])
            if len(matches) == 1:
                entry = matches[0]
            elif len(matches) > 1:
                parent = cal_path.rsplit("/", 1)[0] if "/" in cal_path else ""
                parent_name = os.path.basename(parent.replace("/", "\\"))
                for m in matches:
                    if parent_name and parent_name.lower() in m["path"].lower():
                        entry = m
                        break
                if not entry:
                    entry = matches[0]

        if not entry:
            print(f"  NOT FOUND in music catalog, skipping")
            failed += 1
            continue

        url = entry.get("url", "")
        if not url:
            print(f"  No download URL, skipping")
            failed += 1
            continue

        dest = os.path.join(MUSIC_DIR, filename)

        if os.path.exists(dest):
            print(f"  Already downloaded: {dest}")
            skipped += 1
        else:
            print(f"  Downloading {entry.get('size', 0) / 1024 / 1024:.1f} MB...", end=" ", flush=True)
            if not download(url, dest, entry.get("path")):
                failed += 1
                continue
            downloaded += 1

        # Handle zip extraction
        if filename.lower().endswith(".zip"):
            extract_dir = extract_zip(dest)
            if extract_dir:
                audio_files = scan_audio(extract_dir)
                if audio_files:
                    local_paths = [f"{FOUNDRY_PREFIX}/{af}" for af in audio_files]
                    download_map[cal_path] = local_paths
                    extract_count += 1
                    print(f"  Found {len(audio_files)} audio file(s) in archive")
                else:
                    print(f"  WARNING: No audio files found in archive, keeping zip reference")
                    download_map[cal_path] = [f"{FOUNDRY_PREFIX}/{filename}"]
            else:
                download_map[cal_path] = [f"{FOUNDRY_PREFIX}/{filename}"]
        else:
            download_map[cal_path] = [f"{FOUNDRY_PREFIX}/{filename}"]

    print(f"\nDownloaded: {downloaded}, Skipped: {skipped}, Failed: {failed}")
    print(f"Archives extracted: {extract_count}")

    # Update calendar.json paths
    if download_map and (downloaded + skipped) > 0:
        changes = 0
        for entry in cal:
            new_music = []
            for p in entry.get("music", []):
                if p in download_map:
                    new_music.extend(download_map[p])
                else:
                    new_music.append(p)
            if new_music != entry.get("music", []):
                entry["music"] = new_music
                changes += 1

        with open(CALENDAR_JSON, "w", encoding="utf-8") as f:
            json.dump(cal, f, ensure_ascii=False, indent=2)
        print(f"Updated {changes} calendar entries with local paths")

    if failed > 0:
        print(f"\nWarning: {failed} files could not be downloaded.")
        print("Some URLs may still be expired. Try: Remove-Item temp/ -Recurse; then re-run gen_music_json.ps1 and download_music.py")

if __name__ == "__main__":
    main()
