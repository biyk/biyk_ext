# Weather by Day Time

FoundryVTT module extension that manages a 58-day journey from Baldur's Gate to Waterdeep (Forgotten Realms, 1489 DR). Features per-day weather, particle effects (FXMaster), time-of-day lighting, AI-curated music playlists, and automatic Foundry playlist management.

## Architecture

```
extensions/weather_by_day_time/
├── index.js              # Main module — hooks Simple Calendar, FXMaster, playlist mgmt
├── README.md
├── data/
│   ├── calendar.json     # 58-day journey calendar (weather, particles, music paths)
│   ├── playlist.json     # Per-day playlist source of truth (tracks + expert_processed flag)
│   ├── events.csv        # Journey events
│   ├── locations.csv     # Location descriptions + weather + music hints
│   ├── music/            # Downloaded audio files (254 MP3s)
│   └── ydisk/
│       └── music.json    # Full Yandex Disk catalog tree (~18,600 files, 1,061 collections)
├── scripts/
│   ├── gen_calendar.py       # Generate calendar.json from CSVs
│   ├── gen_music_json.ps1    # Fetch Yandex Disk music tree → music.json (24h cache)
│   ├── yadisk.ps1            # Raw Yandex Disk API (public + OAuth)
│   ├── download_music.py     # Download tracks from calendar paths → data/music/
│   ├── find_song.py          # Fuzzy search & interactive download from catalog
│   └── curate_playlist.py    # AI curator — sends day context to localhost:9999
└── temp/                 # API response cache (SHA256 per URL, 24h TTL)
```

## Data Flow

1. **`events.csv` + `locations.csv`** → **`gen_calendar.py`** → **`calendar.json`** (58 days with Harptos dates, weather, particles, music paths)
2. **Yandex Disk** → **`gen_music_json.ps1`** → **`music.json`** (full catalog with download URLs, cached 24h)
3. **`calendar.json` + `music.json`** → **`download_music.py`** → **`data/music/`** (local audio files + path updates)
4. **Day context + `music.json` catalog** → **`curate_playlist.py`** → **`playlist.json`** (AI-recommended tracks per day)
5. **`playlist.json`** → **`index.js`** → Foundry playlist folder "Дорога" with `День N` sub-playlists

## Setup

1. Install dependencies: `pip install tinytag`
2. Ensure Yandex public folder URL in `gen_music_json.ps1` is correct
3. Run `gen_music_json.ps1` (takes ~5 min; re-run when URLs expire/HTTP 410)
4. Run `gen_calendar.py` to generate `calendar.json`
5. Run `download_music.py` to fetch music locally
6. Run `curate_playlist.py all` to let AI curate all days
7. In Foundry, enable "Weather by Day Time" in module settings, ensure Simple Calendar and FXMaster are active

## Scripts Reference

### `gen_calendar.py`
```
python extensions/weather_by_day_time/scripts/gen_calendar.py
```
Generates `calendar.json` from `events.csv` + `locations.csv`. Matches event locations to location descriptions by name (fuzzy matching). Computes Harptos dates. Uses cumulative month offsets for Simple Calendar compatibility.

### `gen_music_json.ps1`
```
powershell -File extensions/weather_by_day_time/scripts/gen_music_json.ps1
```
Fetches full directory tree from Yandex Disk public folder. Each API response cached in `temp/` for 24h. Cleared manually when download URLs expire (HTTP 410).

### `download_music.py`
```
python extensions/weather_by_day_time/scripts/download_music.py
```
Reads `calendar.json` music paths, resolves to Yandex URLs from `music.json`, downloads to `data/music/`. Extracts zip archives into subdirectories. Updates both `calendar.json` and `playlist.json` paths.

**Note:** Some downloads fail with HTTP 410 (expired URLs). Fix: `Remove-Item temp/ -Recurse`, re-run `gen_music_json.ps1`, re-run `download_music.py`.

### `curate_playlist.py`
```
python extensions/weather_by_day_time/scripts/curate_playlist.py <day>|all
```
Sends day context (campaign info, weather, current tracks, catalog metadata) to AI expert at `localhost:9999`. AI returns `keep/remove/add` JSON recommendations. Supports two modes:
- `<day_number>`: curate a single day
- `all`: process all days with `expert_processed: False`; auto-resets days with < 5 tracks

Features:
- Extracts MP3 metadata (Artist/Album/Title) via `tinytag` for AI visibility
- Matches AI track names by both filename AND metadata (Artist-Title, Album-Title)
- Auto-downloads missing tracks from Yandex Disk catalog
- Only sets `expert_processed: True` if final track count ≥ 5
- Filters `._` Apple Double files and `__MACOSX/` directories automatically
- Deduplicates tracks within each day

**AI recommendation format:**
```json
{
  "keep": ["exact_filename.mp3"],
  "remove": ["exact_filename.mp3"],
  "add": ["CollectionName - NN - Track Title.mp3"],
  "mood": "short mood description",
  "reasoning": "brief explanation"
}
```

### `strip_metadata.py`
```
python temp/opencode/strip_metadata.py
```
Removes ID3v2 tags from an MP3 to fix Foundry `decodeAudioData()` failures with old LAME-encoded tracks (pre-3.98). Requires editing the `fname` variable in the script. Creates a `.bak` backup automatically. Used to fix `The 13th Age Suite - 15 - Tales Around the Fire.mp3` (LAME3.97, dual channel, 204KB ID3) and `The 13th Age Suite - 22 - Dreams of a Lost Age.mp3`.

### `scan_all_tracks.py`
```
python temp/opencode/scan_all_tracks.py
```
Scans all unique tracks across all playlist days for encoding problems. Flags:
- `OLD_ENCODER` (LAME < 3.98 — critical for decodeAudioData)
- `DUAL_CHANNEL` (uncommon mode, may cause issues)
- `INFO_HEADER` (CBR with VBR-style header)
- `LARGE_ID3` (>50KB embedded album art)
- `NO_VBR_HEADER` (missing Xing/Info header)
- `MISSING ON DISK` (referenced in playlist.json but not found)

### `find_song.py`
```
python extensions/weather_by_day_time/scripts/find_song.py "query" [top_n]
```
Fuzzy search against `music.json` catalog. Supports Unicode normalization (em-dashes, quotes). Prompts to download selected tracks to `data/downloads/`.

### `yadisk.ps1`
```
powershell -File extensions/weather_by_day_time/scripts/yadisk.ps1 -Url "https://disk.yandex.ru/d/..."
```
Low-level Yandex Disk API wrapper.

## Calendar (Harptos)

### Start
- **Alturiak 22, 1489 DR, 06:00** — day 1 of journey

### Months
```
 1. Hammer          (30)      7. Flamerule       (30)
     Midwinter      (1)           Midsummer       (1)
 2. Alturiak        (30)          Shieldmeet      (0/1 leap)
 3. Ches            (30)      8. Elesias          (30)
 4. Tarsakh         (30)      9. Eleint           (30)
     Greengrass     (1)           Highharvestide  (1)
 5. Mirtul          (30)     10. Marpenoth        (30)
 6. Kythorn         (30)     11. Uktar            (30)
                                   Feast of the Moon (1)
                              12. Nightal          (30)
```
Total: 12 × 30 + 5 holidays = 365 days (366 in leap year). Leap: `year % 4 === 0`.

### Month Offsets (Simple Calendar)
For `numericRepresentation` -> Harptos date: `[0, 0, 31, 61, 91, 122, 152, 182, 213, 243/244, 273/274, 303/304, 334/335]`

### Seasons
- Spring: Alturiak 18+
- Summer: Flamerule 19+
- Autumn: Elesias 20+
- Winter: Feast of the Moon 19+

## Particle Effects (FXMaster)

Particle effects assigned per day in `calendar.json`. Time-of-day splits:
- **Morning** (6-12): fog, mist, birds
- **Day** (12-18): clearing, sun rays, eagles
- **Evening** (18-24): drizzle, fireflies, campfire
- **Night** (0-6): fog, stars, moonlight

Mood-matched manually to weather descriptions. Clear/sunny days get birds/eagles only (no clouds). Each day has a `weather_object.particles` array (daytime default) plus `weather_object.times` with per-slot arrays.

## Playlist Management (`index.js`)

### Hooks
- `simple-calendar-date-time-change` → calculate day number, time of day, update particles, darkness, playlists
- Module `ready` → create "Дорога" playlist folder, ensure `День N` playlists exist

### Playlist Logic
1. Reads `data/playlist.json` for current day's tracks
2. Checks if current day's playlist is already playing (`target.playing === true`) — skip if so
3. Otherwise stops all "Дорога" playlists, plays current day via `playAll()`
4. Uses `createEmbeddedDocuments("PlaylistSound", ...)` for Foundry v11/v12 compatibility
5. Sends DM whisper with calendar date, time of day, location, event, weather, and notes

### Sound Path Encoding
Audio paths are URL-encoded via `soundPath(path)` to replace `&` → `%26`, preventing Chromium/Express from interpreting `&` as a query separator in audio URLs (e.g., `Taverns & Inns` → `Taverns%20%26%20Inns`). The `syncPlaylistSounds()` function also validates file extensions, deleting stale database entries with metadata-string paths (no `.mp3`).

### Debug Prefix
All console logs use `[WeatherByDayTime]` prefix.

## AI Curator (`localhost:9999`)

The curator sends day context + MP3 metadata + catalog to a local AI service at port 9999. The AI service must be running separately.

### Prompt Structure
- Campaign context, day number, Harptos date
- Location, event, weather, notes
- Current playlist tracks with metadata (`Artist - Title [Album]`)
- Available Yandex Disk collections (must use only these)
- All downloaded tracks with metadata
- Instruction to generate exactly 10 tracks

### Response Parsing
Handles nested JSON (`response`, `text` keys), markdown code blocks, and direct JSON. Falls back to regex extraction for malformed responses.

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Foundry `416 Range Not Satisfiable` | Zero-byte MP3s found and deleted; delete more: `find . -size 0 -name '*.mp3'` in `data/music/` |
| `ERR_CACHE_OPERATION_NOT_SUPPORTED` (old LAME) | File encoded with LAME 3.97 (pre-2008) + dual channel mode + 204KB ID3 art → Foundry's `decodeAudioData()` rejects it. Fix: strip ID3 with `strip_metadata.py` or re-encode with modern LAME. |
| `ERR_CACHE_OPERATION_NOT_SUPPORTED` (zero-byte) | Corrupted zero-byte audio files. Remove and re-download. |
| `ERR_CACHE_OPERATION_NOT_SUPPORTED` (`&` in path) | Raw `&` in filename parsed as URL query separator. Fix: `soundPath()` in `index.js` encodes `&` → `%26`. Reload Foundry. |
| HTTP 410 on download | Yandex URLs expired. `Remove-Item temp/ -Recurse`, re-run `gen_music_json.ps1`, then `download_music.py` |
| Apple Double duplicates (`._` files, `__MACOSX/`) | Filtered automatically by curator + cleanup script. Check `playlist.json` for `._` entries. |
| AI recommends tracks from non-existent collections | Prompt now uses critical rules. Check that Yandex folder list in `music.json` includes the collection. |
| AI returns HTTP 500 | AI model backend timed out (~20-30s response). Retry the day. |
| Unicode/encoding errors on Windows | `_sanitize()` in curator handles NFKC normalization + ASCII fallback. `Sys.stdout.reconfigure(encoding='utf-8')` may help in scripts. |
| Playlist not updating in Foundry | Reload Foundry, or check that playlist folder name is "Дорога" and sub-playlists are named "День N". |

## File Locations

- Calendar: `data/calendar.json`
- Playlists: `data/playlist.json`
- Music catalog: `data/ydisk/music.json`
- Audio files: `data/music/`
- API cache: `temp/`
- Events: `data/events.csv`
- Locations: `data/locations.csv`
