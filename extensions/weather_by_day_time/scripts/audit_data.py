"""Compare calendar.json vs events.csv vs locations.csv for gaps."""
import json, csv, re
from difflib import SequenceMatcher

cal = json.load(open('extensions/weather_by_day_time/data/calendar.json', encoding='utf-8'))

# Collect unique locations from calendar
cal_locs = {}
for e in cal:
    loc = e.get('location', '').strip()
    day = e['day']
    if loc not in cal_locs:
        cal_locs[loc] = []
    cal_locs[loc].append(day)

# Read locations.csv
with open('extensions/weather_by_day_time/data/locations.csv', encoding='utf-8') as f:
    csv_rows = list(csv.DictReader(f))
csv_locs = {r['Название локации'].strip() for r in csv_rows}

# Read events.csv
with open('extensions/weather_by_day_time/data/events.csv', encoding='utf-8') as f:
    events = list(csv.DictReader(f))
ev_days = {int(r['День']) for r in events}

cal_days = {e['day'] for e in cal}
all_days_set = set(cal_days)
all_days = sorted(all_days_set)

print(f"Calendar days: {len(cal_days)} ({min(all_days)}–{max(all_days)})")
print(f"Events CSV days: {len(ev_days)} ({min(ev_days)}–{max(ev_days)})")
print(f"Locations CSV entries: {len(csv_locs)}")

print()
print("=== DAYS IN CALENDAR BUT NOT IN EVENTS ===")
missing_ev = sorted(all_days_set - ev_days)
if missing_ev:
    for d in missing_ev:
        e = next(x for x in cal if x['day'] == d)
        print(f"  Day {d}: {e.get('location','?')} — {e.get('calendar_date','')}")
else:
    print("  (none — all days have events)")

print()
print("=== LOCATIONS IN CALENDAR BUT NOT IN locations.csv ===")
missing_loc = sorted(set(cal_locs.keys()) - csv_locs)
if missing_loc:
    for l in missing_loc:
        days = cal_locs[l]
        # find closest match in CSV
        ratios = [(SequenceMatcher(None, l, csv).ratio(), csv) for csv in csv_locs]
        ratios.sort(reverse=True)
        print(f"  '{l}' (days {days[0]}–{days[-1]})")
        if ratios and ratios[0][0] > 0.5:
            print(f"    → closest CSV: '{ratios[0][1]}' (match: {ratios[0][0]:.0%})")
else:
    print("  (none — all locations have CSV entries)")

print()
print("=== LOCATIONS IN CSV BUT NOT IN CALENDAR ===")
unused_loc = sorted(csv_locs - set(cal_locs.keys()))
if unused_loc:
    for l in unused_loc:
        print(f"  '{l}'")
else:
    print("  (none — all CSV locations used in calendar)")

print()
print("=== ALL LOCATIONS (CALENDAR) ===")
for loc, days in sorted(cal_locs.items()):
    in_csv = "OK" if loc in csv_locs else "MISS"
    print(f"  [{in_csv}] {loc}: days {days[0]}–{days[-1]} ({len(days)} days)")
