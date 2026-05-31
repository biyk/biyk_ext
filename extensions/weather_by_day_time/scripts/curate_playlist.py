import json, sys, os, re, unicodedata, urllib.request, urllib.parse, urllib.error, traceback
from difflib import SequenceMatcher
from tinytag import TinyTag

def try_parse_json(text):
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r'^```(?:json)?\s*', '', text)
        text = re.sub(r'\s*```$', '', text)
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    repaired = repair_json(text)
    if repaired:
        try:
            return json.loads(repaired)
        except json.JSONDecodeError:
            pass
    return None

def repair_json(text):
    """Try to fix common JSON issues: unescaped quotes inside string values."""
    result = []
    in_string = False
    escape_next = False
    quote_char = None
    prev_char = None
    for ch in text:
        if escape_next:
            result.append(ch)
            escape_next = False
            prev_char = ch
            continue
        if ch == '\\':
            if in_string:
                result.append(ch)
                escape_next = True
                prev_char = ch
                continue
            else:
                result.append(ch)
                prev_char = ch
                continue
        if ch in ('"', "'"):
            if in_string:
                if ch == quote_char:
                    in_string = False
                    quote_char = None
                    result.append(ch)
                    prev_char = ch
                    continue
                else:
                    # Same quote type inside string — escape it
                    result.append('\\')
                    result.append(ch)
                    prev_char = ch
                    continue
            else:
                # Start of string — but only if not obviously part of a key or value
                # Check context: after `: `, `[`, `, `, or at start
                context_ok = prev_char is None or prev_char in (' ', ':', ',', '[', '{', '\n', '\t')
                if context_ok:
                    in_string = True
                    quote_char = ch
                    result.append(ch)
                    prev_char = ch
                    continue
                else:
                    # Bare quote in middle of text — escape it
                    result.append('\\')
                    result.append(ch)
                    prev_char = ch
                    continue
        if ch == '\n':
            if in_string:
                result.append('\\n')
                prev_char = ch
                continue
            else:
                result.append(ch)
                prev_char = ch
                continue
        result.append(ch)
        prev_char = ch
    return ''.join(result)

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLAYLIST_JSON = os.path.join(BASE, "data", "playlist.json")
CALENDAR_JSON = os.path.join(BASE, "data", "calendar.json")
MUSIC_JSON = os.path.join(BASE, "data", "ydisk", "music.json")
MUSIC_DIR = os.path.join(BASE, "data", "music")
AI_URL = "http://localhost:9999/ask"

MUSIC_PREFIX = "modules/biyk_ext/extensions/weather_by_day_time/data/music"

YANDEX_API = "https://cloud-api.yandex.net/v1/disk/public/resources/download"
YANDEX_PUBLIC_KEY = "https://disk.yandex.ru/d/S25ICf3RhneLzA"

def flatten_music(items):
    files = []
    if not items:
        return files
    for it in items:
        if not isinstance(it, dict):
            continue
        name = it.get("name", "?")
        if it.get("type") == "file" and name.endswith(".mp3"):
            files.append({
                "name": name,
                "path": it.get("path", ""),
                "url": it.get("file", ""),
            })
        children = it.get("children")
        if children and isinstance(children, list):
            files.extend(flatten_music(children))
    return files

def get_yandex_folders():
    if not os.path.exists(MUSIC_JSON):
        return []
    with open(MUSIC_JSON, "r", encoding="utf-8-sig") as f:
        data = json.load(f)
    folders = [item["name"] for item in data if item.get("type") == "dir"]
    return sorted(folders)

def get_downloaded_files():
    files = []
    if not os.path.exists(MUSIC_DIR):
        return files
    for entry in sorted(os.listdir(MUSIC_DIR)):
        full = os.path.join(MUSIC_DIR, entry)
        if os.path.isfile(full) and entry.endswith(".mp3") and not entry.startswith("._"):
            files.append(entry)
        elif os.path.isdir(full) and "__MACOSX" not in full:
            for root, dirs, fnames in os.walk(full):
                for fname in fnames:
                    if fname.endswith(".mp3") and not fname.startswith("._"):
                        rel = os.path.relpath(os.path.join(root, fname), MUSIC_DIR).replace(os.sep, '/')
                        files.append(rel)
    return sorted(files)

def get_downloaded_metadata():
    """Return dict {filename: {artist, album, title}} for all downloaded MP3s."""
    meta = {}
    if not os.path.exists(MUSIC_DIR):
        return meta
    for entry in sorted(os.listdir(MUSIC_DIR)):
        full = os.path.join(MUSIC_DIR, entry)
        if os.path.isfile(full) and entry.endswith(".mp3") and not entry.startswith("._"):
            meta[entry] = _read_tags(full, entry)
        elif os.path.isdir(full) and "__MACOSX" not in full:
            for root, dirs, fnames in os.walk(full):
                for fname in fnames:
                    if fname.endswith(".mp3") and not fname.startswith("._"):
                        rel = os.path.relpath(os.path.join(root, fname), MUSIC_DIR).replace(os.sep, '/')
                        meta[rel] = _read_tags(os.path.join(root, fname), rel)
    return meta

def _sanitize(s):
    """NFKC normalize and replace tricky Unicode with ASCII equivalents."""
    s = unicodedata.normalize("NFKC", s)
    s = re.sub(r'[\u0300-\u036f]', '', s)
    s = s.replace("\u2013", "-").replace("\u2014", "-").replace("\u2018", "'").replace("\u2019", "'")
    s = s.replace("\u201c", "\"").replace("\u201d", "\"").replace("\u00ab", "\"").replace("\u00bb", "\"")
    s = s.encode("ascii", errors="replace").decode("ascii")
    return s.strip()

def _read_tags(path, display_name):
    try:
        tag = TinyTag.get(path)
        return {
            "artist": _sanitize(tag.artist or ""),
            "album": _sanitize(tag.album or ""),
            "title": _sanitize(tag.title or ""),
        }
    except Exception:
        return {"artist": "", "album": "", "title": ""}

def format_track_info(filename, meta):
    """Format for AI: 'filename.mp3 (Artist - Title [Album])'."""
    info = meta.get(filename, {})
    artist = info.get("artist", "")
    album = info.get("album", "")
    title = info.get("title", "")
    if artist and title:
        md = "{} - {} [{}]".format(artist, title, album) if album else "{} - {}".format(artist, title)
    elif artist and album:
        md = "{} - {}".format(artist, album)
    elif album and title:
        md = "{} - {} [{}]".format(album, title, album)
    else:
        md = ""
    if md:
        result = "{} ({})".format(filename, md)
    else:
        result = filename
    return result.encode("ascii", errors="replace").decode("ascii")

def normalize(s):
    s = s.lower().strip()
    s = re.sub(r'[—–\-_«»"''\[\](){}]', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s

def score_name(query, name):
    qn = normalize(query)
    nn = normalize(name)
    if not qn or not nn:
        return 0
    if nn == qn:
        return 100
    if nn.startswith(qn):
        return 95
    if qn in nn:
        return 85
    if nn in qn:
        return 75
    q_tokens = set(qn.split())
    n_tokens = set(nn.split())
    if not q_tokens:
        return 0
    common = q_tokens & n_tokens
    ratio = len(common) / len(q_tokens)
    score = round(ratio * 70)
    seq = SequenceMatcher(None, qn, nn).ratio()
    if seq > 0.5:
        score = max(score, round(seq * 85))
    return min(score, 100)

def match_in_list(track_name, names_list, meta=None):
    """Match AI track_name against names_list using filename + metadata. Returns matched name or None."""
    best_score = 0
    best_match = None
    for name in names_list:
        s = score_name(track_name, name)
        if s > best_score:
            best_score = s
            best_match = name
    if meta:
        for name in names_list:
            info = meta.get(name, {})
            artist = info.get("artist", "")
            title = info.get("title", "")
            album = info.get("album", "")
            md_strings = []
            if artist and title:
                md_strings.append(f"{artist} - {title}")
                md_strings.append(f"{artist} -- {title}")
            if title:
                md_strings.append(title)
            if album and title:
                md_strings.append(f"{album} - {title}")
            if artist:
                md_strings.append(artist)
            for md in md_strings:
                s = score_name(track_name, md)
                if s > best_score:
                    best_score = s
                    best_match = name
    if best_score >= 60:
        return best_match
    return None

def find_track_file(track_name, downloaded, meta=None):
    best_score = 0
    best_match = None
    for f in downloaded:
        s = score_name(track_name, f)
        if s > best_score:
            best_score = s
            best_match = f
    if meta:
        for fname, info in meta.items():
            if fname not in downloaded:
                continue
            artist = info.get("artist", "")
            title = info.get("title", "")
            album = info.get("album", "")
            md_strings = []
            if artist and title:
                md_strings.append(f"{artist} - {title}")
                md_strings.append(f"{artist} -- {title}")
            if title:
                md_strings.append(title)
            if album and title:
                md_strings.append(f"{album} - {title}")
            if artist:
                md_strings.append(artist)
            if album and title:
                md_strings.append(f"{album} - {title} [{album}]")
            for md in md_strings:
                s = score_name(track_name, md)
                if s > best_score:
                    best_score = s
                    best_match = fname
    if best_score >= 60:
        return best_match
    return None

def make_path(filename):
    return f"{MUSIC_PREFIX}/{filename.replace(os.sep, '/')}"

def format_path(filename):
    return filename.replace(os.sep, '/')

def get_catalog_files():
    if not os.path.exists(MUSIC_JSON):
        return []
    with open(MUSIC_JSON, "r", encoding="utf-8-sig") as f:
        data = json.load(f)
    return flatten_music(data)

def search_catalog(track_name, catalog):
    best_score = 0
    best_match = None
    for f in catalog:
        s = score_name(track_name, f["name"])
        if s > best_score:
            best_score = s
            best_match = f
    if best_score >= 60 and best_match and best_match.get("url"):
        return best_match
    return None

def download_file(url, dest_path):
    try:
        print(f"    Downloading {os.path.basename(dest_path)}...", end=" ", flush=True)
        urllib.request.urlretrieve(url, dest_path)
        print("OK")
        return True
    except urllib.error.HTTPError as e:
        print(f"FAILED: {e}")
        return False

def refresh_yandex_url(yandex_path):
    """Get a fresh download URL from Yandex API (URLs expire after ~1h)."""
    try:
        params = urllib.parse.urlencode({"public_key": YANDEX_PUBLIC_KEY, "path": yandex_path})
        req = urllib.request.Request(f"{YANDEX_API}?{params}")
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("href")
    except Exception as e:
        print(f"    URL refresh FAILED: {e}")
        return None

def get_day_tracks(entry):
    if isinstance(entry, dict) and "tracks" in entry:
        return entry["tracks"]
    if isinstance(entry, list):
        return entry
    return []

def download_track(track_name, catalog):
    match = search_catalog(track_name, catalog)
    if not match:
        return None
    dest = os.path.join(MUSIC_DIR, match["name"])
    if os.path.exists(dest):
        return match["name"]
    if download_file(match["url"], dest):
        return match["name"]
    # HTTP 410 or other failure — try fresh URL from Yandex API
    if match.get("path"):
        print(f"    URL expired, refreshing from API...", end=" ", flush=True)
        new_url = refresh_yandex_url(match["path"])
        if new_url and download_file(new_url, dest):
            return match["name"]
    return None

def calibrate_tracks(day, downloaded, catalog, meta):
    with open(PLAYLIST_JSON, "r", encoding="utf-8") as f:
        playlists = json.load(f)
    skey = str(day)
    entry = playlists.get(skey, {})
    current = get_day_tracks(entry)
    current_names = [os.path.basename(p) for p in current]
    print(f"\nDay {day} current tracks ({len(current)}):")
    for t in current:
        bn = os.path.basename(t)
        info = format_track_info(bn, meta)
        print(f"  {info}")

    yandex_folders = get_yandex_folders()
    folders_text = ", ".join(yandex_folders)

    with open(CALENDAR_JSON, "r", encoding="utf-8") as f:
        cal = json.load(f)
    entry = next((e for e in cal if e["day"] == day), None)
    if not entry:
        print(f"  Day {day} not found in calendar.json")
        return

    prompt = f"""You are a music curator for a D&D 5e campaign. The campaign is a caravan journey from Baldur's Gate to Waterdeep along the Trade Way (Forgotten Realms, 1489 DR), lasting 58 days.

DAY {day} — {entry['calendar_date']}
Location: {entry.get('location', '?')}
Event: {entry.get('event', '?')}
Weather: {entry.get('weather', '?')}
Notes: {entry.get('notes', '?')[:500]}

Current playlist tracks (FILENAME only for keep/remove):
{chr(10).join(f'  - {format_track_info(os.path.basename(t), meta)}' for t in current) if current else '  (empty)'}

AVAILABLE MUSIC COLLECTIONS ON YANDEX DISK (use ONLY these):
{chr(10).join(yandex_folders)}

ALREADY DOWNLOADED TRACKS (FILENAME first, then metadata in parentheses):
{chr(10).join(f'  - {format_track_info(f, meta)}' for f in downloaded)}

The playlist MUST have exactly 10 tracks per day. Recommend tracks from ANY Yandex Disk collection in the AVAILABLE list (not just already downloaded ones) — I will automatically download them. Don't repeat the same tracks across different days.

CRITICAL rules:
1. Use ONLY collection names from the AVAILABLE MUSIC COLLECTIONS list above. Do NOT invent collection names.
2. For `keep` and `remove`, use the EXACT FILENAME shown before the parentheses (e.g., "01 - Track Title.mp3").
3. For `add`, use format "CollectionName - NN - Track Title.mp3" matching the collection's naming pattern.
4. If you keep all or most current tracks, still try to add enough from the available collections to reach 10 total.

Analyze the current playlist. Consider:
1. Does the mood of each track match the day's atmosphere, event, and weather?
2. Which Yandex Disk collections (from the list) have music that fits this day?
3. Vary recommendations across days so the same tracks don't repeat.

Respond ONLY with valid JSON (no markdown, no code fences, no extra wrapper object with "response" key). Use this exact structure:
{{
  "keep": ["exact_filename.mp3"],
  "remove": ["exact_filename.mp3"],
  "add": ["CollectionName - NN - Track Title.mp3"],
  "mood": "short mood description",
  "reasoning": "brief explanation with suggested collections"
}}
For `keep` and `remove`, use the FILENAME from the current tracks list (before the parentheses).
For `add`, use "CollectionName - NN - Track Title.mp3" format as files appear in that collection.

CRITICAL: Do NOT use double quotes (") inside any string value. If a track name contains quotes, use single quotes or remove them instead."""

    print(f"\n  Sending prompt to AI ({len(prompt)} chars)...", end=" ", flush=True)
    try:
        body = json.dumps({"text": prompt}).encode("utf-8")
        req = urllib.request.Request(
            AI_URL,
            data=body,
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=600) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:2000]
        print(f"FAILED (HTTP {e.code})")
        print(f"  Expert says: {body}")
        sys.exit(1)
    except Exception as e:
        print(f"FAILED: {e}")
        sys.exit(1)

    print("OK")

    ai_json = None
    parsed = None

    try:
        ai_json = json.loads(raw)
        if isinstance(ai_json, dict):
            if any(k in ai_json for k in ("keep", "remove", "add")):
                parsed = ai_json
            elif "response" in ai_json and isinstance(ai_json["response"], str):
                parsed = try_parse_json(ai_json["response"])
            elif "text" in ai_json and isinstance(ai_json["text"], str):
                parsed = try_parse_json(ai_json["text"])
    except (json.JSONDecodeError, TypeError):
        pass

    if not parsed:
        json_match = re.search(r'\{[^{}]*"keep"[^{}]*"remove"[^{}]*"add"[^{}]*\}', raw, re.DOTALL)
        if json_match:
            parsed = try_parse_json(json_match.group())
        else:
            json_match2 = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', raw, re.DOTALL)
            if json_match2:
                parsed = try_parse_json(json_match2.group(1))
        # Also try inside the "response" or "text" inner strings (AI may nest JSON)
        if not parsed and isinstance(ai_json, dict):
            for inner_key in ("response", "text", "content"):
                inner = ai_json.get(inner_key, "")
                if isinstance(inner, str):
                    jm = re.search(r'\{[^{}]*"keep"[^{}]*"remove"[^{}]*"add"[^{}]*\}', inner, re.DOTALL)
                    if jm:
                        parsed = try_parse_json(jm.group())
                        if parsed:
                            break
                    jm2 = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', inner, re.DOTALL)
                    if jm2:
                        parsed = try_parse_json(jm2.group(1))
                        if parsed:
                            break

    if not parsed:
        print(f"  Could not parse JSON from AI response")
        print(f"  Raw response (first 800 chars): {raw[:800]}")
        return

    print(f"  Parsed keys: {list(parsed.keys())}")
    keep = [_sanitize(t) for t in parsed.get("keep", [])]
    remove = [_sanitize(t) for t in parsed.get("remove", [])]
    add = [_sanitize(t) for t in parsed.get("add", [])]
    mood = _sanitize(parsed.get("mood", ""))
    reasoning = _sanitize(parsed.get("reasoning", ""))

    print(f"\n  AI reasoning: {reasoning}")
    if mood:
        print(f"  Mood: {mood}")
    if remove:
        print(f"  Remove: {remove}")
    if add:
        print(f"  Add: {add}")
    if keep:
        print(f"  Keep: {keep}")

    # Match AI keep/remove entries against actual filenames using metadata
    keep_fnames = set()
    for k in keep:
        m = match_in_list(k, current_names, meta)
        if m:
            keep_fnames.add(m)
    remove_fnames = set()
    for r in remove:
        m = match_in_list(r, current_names, meta)
        if m:
            remove_fnames.add(m)

    new_tracks = list(keep_fnames) if keep_fnames else []
    for t in current_names:
        if t in remove_fnames:
            continue
        if t not in new_tracks:
            new_tracks.append(t)

    for track_name in add:
        matched = match_in_list(track_name, downloaded, meta)
        if matched:
            if matched not in new_tracks:
                new_tracks.append(matched)
                print(f"  ADDED: {matched}")
        else:
            print(f"  NEEDS DOWNLOAD: {track_name}")
            dl_name = download_track(track_name, catalog)
            if dl_name:
                if dl_name not in new_tracks:
                    new_tracks.append(dl_name)
                    downloaded.append(dl_name)
                    print(f"  DOWNLOADED & ADDED: {dl_name}")
            else:
                coll_match = re.match(r'^([^—–-]+)', track_name)
                if coll_match:
                    coll_name = coll_match.group(1).strip()
                    alt = [f for f in catalog if coll_name.lower() in f["name"].lower()]
                    if alt:
                        best = alt[0]
                        print(f"  Trying alternative from same collection: {best['name']}")
                        dl_name2 = download_track(best["name"], catalog)
                        if dl_name2:
                            if dl_name2 not in new_tracks:
                                new_tracks.append(dl_name2)
                                downloaded.append(dl_name2)
                                print(f"  DOWNLOADED & ADDED: {dl_name2}")
                        else:
                            print(f"  SKIPPED: {track_name}")
                    else:
                        print(f"  SKIPPED: {track_name} (collection not found)")

    new_paths = []
    seen_names = set()
    for t in new_tracks:
        norm = normalize(t)
        if norm in seen_names:
            continue
        seen_names.add(norm)
        # Try to find full path from current tracks first
        full_path = None
        if t in current_names:
            idx = current_names.index(t)
            full_path = current[idx]
        if not full_path:
            full_path = make_path(t)
        # Validate path ends in .mp3 — skip otherwise
        if not full_path.lower().endswith(".mp3"):
            print(f"  SKIPPED (not .mp3): {full_path}")
            continue
        new_paths.append(full_path)

    is_processed = len(new_paths) >= 5
    playlists[skey] = {
        "tracks": new_paths,
        "expert_processed": is_processed
    }
    with open(PLAYLIST_JSON, "w", encoding="utf-8") as f:
        json.dump(playlists, f, indent=2, ensure_ascii=False)
    status = "expert_processed=True" if is_processed else f"expert_processed=False ({len(new_paths)} tracks < 5)"
    print(f"\n  Updated playlist.json for day {day}: {len(new_paths)} tracks ({status})")
    if not is_processed:
        print(f"  WARNING: Day {day} has only {len(new_paths)} tracks — will be re-processed next run")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python curate_playlist.py <day_number>")
        print("  <day_number>: 1-58 for a specific day, or 'all' for all days")
        sys.exit(1)

    arg = sys.argv[1]
    downloaded = get_downloaded_files()
    print(f"Downloaded tracks available: {len(downloaded)}")
    print("Reading MP3 metadata...", end=" ", flush=True)
    meta = get_downloaded_metadata()
    print("OK ({}/{} with metadata)".format(
        sum(1 for v in meta.values() if v.get("artist") or v.get("title")),
        len(meta)
    ))
    catalog = get_catalog_files()
    print(f"Catalog tracks available: {len(catalog)}")

    if arg == "all":
        with open(PLAYLIST_JSON, "r", encoding="utf-8") as f:
            playlists = json.load(f)
        # Reset expert_processed for any day with < 5 tracks (recurate them)
        for k, v in playlists.items():
            if len(v.get("tracks", [])) < 5:
                if v.get("expert_processed"):
                    print(f"Resetting day {k} ({len(v['tracks'])} tracks) — too few tracks")
                playlists[k]["expert_processed"] = False
        with open(PLAYLIST_JSON, "w", encoding="utf-8") as f:
            json.dump(playlists, f, indent=2, ensure_ascii=False)
        to_process = [k for k, v in sorted(playlists.items(), key=lambda x: int(x[0])) if not v.get("expert_processed")]
        print(f"Days to process: {len(to_process)} — {', '.join(to_process)}")
        for d in to_process:
            calibrate_tracks(int(d), downloaded, catalog, meta)
    else:
        try:
            day = int(arg)
            calibrate_tracks(day, downloaded, catalog, meta)
        except Exception as e:
            import traceback
            print(f"Error: {e}")
            traceback.print_exc()
            sys.exit(1)
