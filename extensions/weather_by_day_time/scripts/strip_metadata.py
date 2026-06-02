"""Strip all metadata/ID3 tags from a problematic MP3, keep only raw MPEG frames."""
import os, sys

music = r'extensions/weather_by_day_time/data/music'
fname = r'Highlands.mp3'
fp = os.path.join(music, fname)

with open(fp, 'rb') as f:
    raw = bytearray(f.read())

# Skip ID3v2 tag
id3_end = 0
if raw[:3] == b'ID3':
    id3_end = (raw[6]<<21) | (raw[7]<<14) | (raw[8]<<7) | raw[9] + 10
    print(f'ID3v2 tag: {id3_end} bytes ({id3_end//1024}KB)')

# Find first real MPEG frame (scan from id3_end)
first = 0
for i in range(id3_end, min(len(raw) - 1, id3_end + 10000)):
    if raw[i] == 0xFF and (raw[i+1] & 0xE0) == 0xE0:
        v = (raw[i+1] >> 3) & 3
        l = (raw[i+1] >> 1) & 3
        bi = (raw[i+2] >> 4) & 0xF
        si = (raw[i+2] >> 2) & 3
        if v == 3 and l == 1 and 1 <= bi <= 14 and si <= 2:
            first = i
            break

if first == 0:
    print('ERROR: could not find first MPEG frame')
    sys.exit(1)

print(f'First audio frame at offset {first} (of {len(raw)})')
print(f'Stripping {first} bytes of metadata ({first/1024:.0f}KB)')

# Walk frame by frame from first to find end of valid audio
pos = first
last_pos = first
while pos < len(raw) - 1:
    if raw[pos] != 0xFF or (raw[pos+1] & 0xE0) != 0xE0:
        break
    v = (raw[pos+1] >> 3) & 3
    l = (raw[pos+1] >> 1) & 3
    bi = (raw[pos+2] >> 4) & 0xF
    si = (raw[pos+2] >> 2) & 3
    pad = (raw[pos+2] >> 1) & 1
    if v != 3 or l != 1 or bi < 1 or bi > 14 or si > 2:
        break
    br = [0,32,40,48,56,64,80,96,112,128,160,192,224,256,320,0][bi]
    sr = [44100,48000,32000][si]
    fsize = 144 * br * 1000 // sr + pad
    if fsize <= 0:
        break
    last_pos = pos
    pos += fsize

print(f'Total frames: from {first} to {last_pos + fsize}')
print(f'Audio data: {(last_pos + fsize - first) / 1024 / 1024:.1f}MB')

# Backup
bak = fp + '.bak'
if not os.path.exists(bak):
    os.rename(fp, bak)
    print(f'Backup: {bak}')

# Write clean file (from first frame to end of last valid frame)
clean = raw[first:last_pos + fsize]
with open(fp, 'wb') as f:
    f.write(clean)
print(f'Written clean file: {len(clean)} bytes ({len(clean)/1024/1024:.1f}MB)')

if clean[0] == 0xFF and (clean[1] & 0xE0) == 0xE0:
    print('OK: clean file starts with MPEG sync')
else:
    print('ERROR: clean file does not start with sync!')

try:
    from mutagen.mp3 import MP3
    m = MP3(fp)
    print(f'Mutagen: {m.info.bitrate/1000:.0f}kbps, {m.info.sample_rate}Hz, {m.info.length:.1f}s')
except Exception as e:
    print(f'Mutagen check: {e}')
