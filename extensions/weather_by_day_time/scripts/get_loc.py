"""Get location for a day and output a battlemap generation prompt."""
import json, csv, sys, subprocess

day = int(sys.argv[1])
cal = json.load(open('extensions/weather_by_day_time/data/calendar.json', encoding='utf-8'))
entry = next((e for e in cal if e['day'] == day), None)
if not entry:
    print(f"Day {day}: no calendar entry"); sys.exit(1)

loc_name = entry.get('location', '')
if not loc_name:
    print(f"Day {day} ({entry['calendar_date']}): no location"); sys.exit(1)

with open('extensions/weather_by_day_time/data/locations.csv', encoding='utf-8') as f:
    for row in csv.DictReader(f):
        if row['Название локации'].strip() == loc_name.strip():
            env = row.get('Ландшафт / Описание окрестностей', '')
            music = row.get('Музыкальное сопровождение', '')
            weather_csv = row.get('Погода', '')
            break
    else:
        print(f"Location '{loc_name}' not found"); sys.exit(1)

weather_cal = entry.get('weather', '')
notes = entry.get('notes', '')

banner = """Нарисуй детализированную карту для D&D в формате battlemap.

Требования:

* Вид строго сверху (90 градусов, top-down).
* Вертикальная карта.
* Дорога проходит по центру карты сверху вниз.
* Сохрани дорогу главным элементом сцены.
* Не меняй форму дороги без необходимости.
* Детализируй только окружающую местность.
* Стиль — рисованная фэнтезийная battlemap для виртуального стола (Foundry VTT, Roll20).
* Много мелких деталей окружения.
* Реалистичные текстуры земли, травы, камней и растительности.
* Без подписей.
* Без интерфейса.
* Без рамок.
* Без клеток (grid).
* Без перспективы и горизонта.
* Только вид сверху.

ВАЖНО:

Карта должна быть бесшовной по вертикали.

Верхний край карты должен идеально продолжаться нижним краем.

Текстуры, дорога, трава, тени и детали окружения должны плавно переходить сверху вниз.

Карта будет использоваться для бесконечной вертикальной прокрутки."""

output = f"""{banner}

Day {day} — {entry['calendar_date']}
Location: {loc_name}
Weather:  {weather_cal} / {weather_csv}

=== Environment ===
{env}

=== Music ===
{music}

Создай атмосферу, соответствующую описанию локации и музыки. Добавляй характерные детали окружения, но не загромождай карту объектами. Карта должна оставаться удобной для перемещения персонажей."""

if notes:
    output += f"\n\n=== Campaign Notes ===\n{notes}"

print(output)

try:
    import tempfile, os
    tmp = tempfile.NamedTemporaryFile(mode='wb', suffix='.txt', delete=False)
    tmp.write(b'\xff\xfe')
    tmp.write((output + '\r\n').encode('utf-16-le'))
    tmp.close()
    subprocess.run(['powershell', '-NoProfile', '-Command',
                    f'Get-Content -Raw "{tmp.name}" -Encoding Unicode | Set-Clipboard'],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    os.unlink(tmp.name)
    print("\n(Copied to clipboard)", flush=True)
except Exception:
    pass
