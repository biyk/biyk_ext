import csv, json, os, re, difflib

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EVENTS_CSV = os.path.join(BASE, "data", "events.csv")
LOCATIONS_CSV = os.path.join(BASE, "data", "locations.csv")
MUSIC_JSON = os.path.join(BASE, "data", "ydisk", "music.json")
OUTPUT = os.path.join(BASE, "data", "calendar.json")

MONTH_DAYS = [("Hammer", 30), ("Midwinter", 1), ("Alturiak", 30), ("Ches", 30),
              ("Tarsakh", 30), ("Greengrass", 1), ("Mirtul", 30), ("Kythorn", 30),
              ("Flamerule", 30), ("Midsummer", 1), ("Elesias", 30), ("Eleint", 30),
              ("Highharvestide", 1), ("Marpenoth", 30), ("Uktar", 30),
              ("Feast of the Moon", 1), ("Nightal", 30)]

MONTH_SEQUENCE = []
for name, days in MONTH_DAYS:
    MONTH_SEQUENCE.extend([name] * days)

def day_to_calendar(day_offset):
    idx = day_offset % len(MONTH_SEQUENCE)
    name = MONTH_SEQUENCE[idx]
    month_start = idx
    while month_start > 0 and MONTH_SEQUENCE[month_start-1] == name:
        month_start -= 1
    day_of_month = idx - month_start + 1
    return f"{name} {day_of_month}, 1489 DR"

def match_location(loc_name, locs):
    best, best_score = None, 0
    for l in locs:
        val = list(l.values())[0]
        if not val: continue
        score = difflib.SequenceMatcher(None, loc_name.lower(), val.lower()).ratio()
        if score > best_score:
            best_score = score
            best = l
    return best, best_score

def parse_weather_note(note):
    note_clean = note.replace("\n", " ").replace("\r", "")
    m = re.search(r'(Погода[^.]*\.)', note_clean)
    return m.group(1).strip() if m else ""

# --- music search (from find_song.py) ---

def flatten(items, parent_path=""):
    files = []
    if not items: return files
    for it in items:
        if not isinstance(it, dict): continue
        name = it.get("name", "?")
        full = f"{parent_path}/{name}" if parent_path else name
        if it.get("type") == "file":
            files.append({"name": name, "path": f"/Музыка/{full}"})
        children = it.get("children")
        if children and isinstance(children, list):
            files.extend(flatten(children, full))
    return files

def normalize(s):
    s = s.lower().strip()
    s = re.sub(r'[—–\-_«»"''\[\](){}]', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s

def score_name(query_norm, name_norm, path_norm):
    if not query_norm or not name_norm: return 0
    if name_norm == query_norm: return 100
    if name_norm.startswith(query_norm): return 95
    if query_norm in name_norm: return 85
    if name_norm in query_norm: return 75
    q_tokens = set(query_norm.split())
    n_tokens = set(name_norm.split())
    p_tokens = set(path_norm.split())
    if not q_tokens: return 0
    common = q_tokens & n_tokens
    ratio = len(common) / len(q_tokens)
    score = round(ratio * 70)
    if q_tokens.issubset(p_tokens | n_tokens): score += 15
    seq = difflib.SequenceMatcher(None, query_norm, name_norm).ratio()
    if seq > 0.5: score = max(score, round(seq * 85))
    return min(score, 100)

def search_track(query, all_files, top=3, min_score=50):
    q_norm = normalize(query)
    results = []
    for f in all_files:
        score = score_name(q_norm, normalize(f["name"]), normalize(f["path"]))
        if score >= min_score:
            results.append((score, f["path"]))
    results.sort(key=lambda x: -x[0])
    return [p for _, p in results[:top]]

def parse_music_tracks(music_text):
    """Извлечь названия треков из music-описания в locations.csv."""
    tracks = []
    if not music_text: return tracks
    # Ищем все «...» — это названия треков
    titles = re.findall(r'«([^»]+)»', music_text)
    # Извлекаем пары Исполнитель — «Название»
    pairs = re.findall(r'([A-Za-zÀ-ÿ0-9 .\'&!?,:-]+)\s*[—–-]\s*«([^»]+)»', music_text)
    for artist, title in pairs:
        tracks.append((artist.strip(), title.strip()))
    # Если пар нет, но есть голые названия в кавычках
    if not tracks and titles:
        for t in titles:
            tracks.append(("", t.strip()))
    return tracks

# --- main ---

def build():
    # Load events
    with open(EVENTS_CSV, "r", encoding="utf-8-sig") as f:
        events = list(csv.DictReader(f, delimiter=","))

    # Load locations
    with open(LOCATIONS_CSV, "r", encoding="utf-8-sig") as f:
        locs = list(csv.DictReader(f, delimiter=","))

    # Load music catalog
    print("Loading music catalog...", end=" ", flush=True)
    with open(MUSIC_JSON, "r", encoding="utf-8-sig") as f:
        tree = json.load(f)
    all_files = flatten(tree)
    print(f"{len(all_files)} files.", flush=True)

    print(f"Loaded {len(events)} days, {len(locs)} locations")

    calendar = []
    prev_loc_raw = ""
    prev_weather = ""
    prev_loc_desc = ""
    prev_music_paths = []

    for i, e in enumerate(events):
        vals = list(e.values())
        day_num = int(vals[0]) if len(vals) > 0 else i + 1
        loc_raw = (vals[3] if len(vals) > 3 else "").strip().strip('"').strip('«').strip('»').strip()
        event_name = (vals[4] if len(vals) > 4 else "").strip().strip('"').strip('«').strip('»').strip()
        notes = (vals[5] if len(vals) > 5 else "").strip().strip('"')
        miles_str = (vals[1] if len(vals) > 1 else "0").strip()
        miles = int(miles_str) if miles_str and miles_str not in ("–", "-") else 0
        total_miles_str = (vals[2] if len(vals) > 2 else "0").strip()
        total_miles = int(total_miles_str) if total_miles_str and total_miles_str not in ("–", "-") else 0
        is_rest = (miles == 0)

        start_idx = 52
        date_idx = start_idx + (day_num - 1)
        date_str = day_to_calendar(date_idx)

        is_fake_loc = loc_raw in ("", "–", "-") or loc_raw.lower().startswith("день отдыха")
        if is_fake_loc:
            loc_display = prev_loc_raw if prev_loc_raw else "Дорога"
            weather = prev_weather
            loc_desc = prev_loc_desc
            music_paths = prev_music_paths
        else:
            loc_display = loc_raw
            matched_loc, score = match_location(loc_raw, locs)
            weather = ""
            loc_desc = ""
            music_paths = []

            if matched_loc and score >= 0.35:
                loc_vals = list(matched_loc.values())
                weather = loc_vals[1] if len(loc_vals) > 1 else ""
                loc_desc = loc_vals[2] if len(loc_vals) > 2 else ""
                music_text = loc_vals[3] if len(loc_vals) > 3 else ""

                # Parse and search music tracks
                tracks = parse_music_tracks(music_text)
                for artist, title in tracks:
                    paths = search_track(title, all_files, top=2, min_score=40)
                    music_paths.extend(paths)
                music_paths = list(dict.fromkeys(music_paths))

            # fallback weather from notes
            if not weather:
                weather_note = parse_weather_note(notes)
                if weather_note:
                    weather = weather_note

            if music_paths:
                prev_music_paths = music_paths
            prev_weather = weather if weather else prev_weather
            prev_loc_desc = loc_desc if loc_desc else prev_loc_desc
            prev_loc_raw = loc_raw

        entry = {
            "day": day_num,
            "calendar_date": date_str,
            "location": loc_display,
            "event": event_name if event_name and event_name not in ("–", "-") else "",
            "notes": notes,
            "miles": miles,
            "total_miles": total_miles,
            "is_rest_day": is_rest,
            "music": music_paths,
            "weather": weather,
            "weather_object": {},
            "location_description": loc_desc,
        }
        calendar.append(entry)

    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(calendar, f, ensure_ascii=False, indent=2)

    print(f"Written {len(calendar)} days to {OUTPUT}")

    # Stats
    with_music = sum(1 for d in calendar if d["music"])
    with_weather = sum(1 for d in calendar if "weather" in d)
    print(f"Days with music files: {with_music}/{len(calendar)}")
    print(f"Days without music: {[d['day'] for d in calendar if not d['music']]}")
    total_tracks = sum(len(d["music"]) for d in calendar)
    print(f"Total tracks matched: {total_tracks}")

if __name__ == "__main__":
    build()
