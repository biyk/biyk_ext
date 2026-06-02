"""Get location description for a given journey day from locations.csv + calendar.json."""
import json, csv, sys

day = int(sys.argv[1])
cal = json.load(open('extensions/weather_by_day_time/data/calendar.json', encoding='utf-8'))
entry = next((e for e in cal if e['day'] == day), None)
if not entry:
    print(f"Day {day}: no calendar entry"); sys.exit(1)

loc_name = entry.get('location', '')
if not loc_name:
    print(f"Day {day} ({entry['calendar_date']}): no location"); sys.exit(1)

with open('extensions/weather_by_day_time/data/locations.csv', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        if row['Название локации'].strip() == loc_name.strip():
            print(f"Day {day} — {entry['calendar_date']}")
            print(f"Location: {loc_name}")
            print(f"Weather:  {entry.get('weather')} / {row.get('Погода', '')}")
            print()
            print("=== Environment ===")
            print(row.get('Ландшафт / Описание окрестностей', ''))
            print()
            print("=== Music ===")
            print(row.get('Музыкальное сопровождение', ''))
            break
    else:
        print(f"Location '{loc_name}' not found in locations.csv")
