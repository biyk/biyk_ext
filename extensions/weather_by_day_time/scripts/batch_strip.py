"""Batch-strip ID3v2 tags from all tracks with large metadata to prevent decodeAudioData failures.
Safe: preserves raw MPEG frames unchanged, only removes ID3 tags (unused by Foundry)."""
import json, os

music = r'extensions/weather_by_day_time/data/music'
pl = json.load(open(r'extensions/weather_by_day_time/data/playlist.json', encoding='utf-8'))

all_tracks = set()
for entry in pl.values():
    for t in entry.get('tracks', []):
        all_tracks.add(t.split('/')[-1])
print(f"Total unique tracks: {len(all_tracks)}")

SRATE = {3: (44100,48000,32000), 2:(22050,24000,16000), 0:(11025,12000,8000)}
stripped = skipped = errors = 0

for fname in sorted(all_tracks):
    fp = os.path.join(music, fname)
    if not os.path.exists(fp):
        skipped += 1; continue
    with open(fp, 'rb') as f:
        raw = bytearray(f.read())
    if raw[:3] != b'ID3':
        skipped += 1; continue
    id3_end = (raw[6]<<21)|(raw[7]<<14)|(raw[8]<<7)|raw[9] + 10
    if id3_end < 20000:
        skipped += 1; continue

    # Find first valid MPEG1 LIII frame after ID3
    first = 0
    for i in range(id3_end, min(len(raw)-1, id3_end+5000)):
        if raw[i]==0xFF and (raw[i+1]&0xE0)==0xE0:
            v=(raw[i+1]>>3)&3; l=(raw[i+1]>>1)&3; bi=(raw[i+2]>>4)&0xF; si=(raw[i+2]>>2)&3
            if v==3 and l==1 and 1<=bi<=14 and si<=2:
                first=i; break
    if first==0:
        skipped+=1; continue

    # Walk frames
    pos = first; last_pos = first
    while pos < len(raw)-1:
        if raw[pos]!=0xFF or (raw[pos+1]&0xE0)!=0xE0: break
        v=(raw[pos+1]>>3)&3; l=(raw[pos+1]>>1)&3; bi=(raw[pos+2]>>4)&0xF
        si=(raw[pos+2]>>2)&3; pad=(raw[pos+2]>>1)&1
        if v!=3 or l!=1 or bi<1 or bi>14 or si>2: break
        br=[0,32,40,48,56,64,80,96,112,128,160,192,224,256,320,0][bi]
        sr=SRATE[v][si]
        fsize=144*br*1000//sr+pad
        if fsize<=0: break
        last_pos=pos; pos+=fsize
    if last_pos==first:
        skipped+=1; continue

    clean = raw[first:pos]
    bak = fp+'.bak'
    if not os.path.exists(bak):
        os.rename(fp, bak)
    with open(fp, 'wb') as f:
        f.write(clean)
    stripped+=1
    print(f'OK: {fname}  ({id3_end//1024}KB ID3 -> {len(clean)//1024}KB)')

print(f'\nDone: {stripped} stripped, {skipped} skipped, {errors} errors')

# Cleanup .bak
baks=[f for f in os.listdir(music) if f.endswith('.bak')]
for b in baks: os.remove(os.path.join(music,b))
print(f'Removed {len(baks)} .bak files')
