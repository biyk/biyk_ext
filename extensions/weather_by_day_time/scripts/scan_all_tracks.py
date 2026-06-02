"""Scan ALL unique tracks across all days for problematic encoding patterns.
Flags files that may cause decodeAudioData() failures in Foundry v11/v12."""
import json, os, sys

music = r'extensions/weather_by_day_time/data/music'
pl_path = r'extensions/weather_by_day_time/data/playlist.json'
pl = json.load(open(pl_path, encoding='utf-8'))

# Collect all unique tracks
all_tracks = {}
for day, entry in pl.items():
    for t in entry.get('tracks', []):
        fname = t.split('/')[-1]
        if fname not in all_tracks:
            all_tracks[fname] = {'path': t, 'days': []}
        all_tracks[fname]['days'].append(day)

print(f"Total unique tracks: {len(all_tracks)}")
print()

# MPEG tables
BITRATE = {
    1: [0,32,40,48,56,64,80,96,112,128,160,192,224,256,320,0],
    2: [0,32,48,56,64,80,96,112,128,160,192,224,256,320,384,0],
    3: [0,32,64,96,128,160,192,224,256,288,320,352,384,416,448,0],
}
BITRATE_2 = {
    1: [0,8,16,24,32,40,48,56,64,80,96,112,128,144,160,0],
    2: [0,8,16,24,32,40,48,56,64,80,96,112,128,144,160,0],
    3: [0,32,48,56,64,80,96,112,128,144,160,176,192,224,256,0],
}
SRATE = {3: [44100,48000,32000], 2:[22050,24000,16000], 0:[11025,12000,8000]}
VER = {3:'MPEG1', 2:'MPEG2', 0:'MPEG2.5'}
LAY = {3:'I', 2:'II', 1:'III'}
CHAN = {3:'stereo',2:'joint stereo',1:'dual',0:'mono'}
CRITICAL_ENCODERS = ['LAME3.97', 'LAME3.96', 'LAME3.95', 'LAME3.94', 'LAME3.93', 'LAME3.92', 'LAME3.91', 'LAME3.90']

problems = []
warnings = []
ok_count = 0

for fname, info in sorted(all_tracks.items(), key=lambda x: x[1]['days'][0]):
    fp = os.path.join(music, fname)
    if not os.path.exists(fp):
        problems.append((fname, 'MISSING ON DISK', 'FILE_NOT_FOUND'))
        continue
    
    with open(fp, 'rb') as f:
        raw = f.read()
    
    # Find first valid MPEG1 Layer III frame
    off = 0
    if raw[:3] == b'ID3':
        off = (raw[6]<<21) | (raw[7]<<14) | (raw[8]<<7) | raw[9] + 10
    
    first_frame = -1
    for i in range(off, min(off + 500, len(raw) - 4)):
        if raw[i] == 0xFF and (raw[i+1] & 0xE0) == 0xE0:
            v = (raw[i+1] >> 3) & 3
            l = (raw[i+1] >> 1) & 3
            bi = (raw[i+2] >> 4) & 0xF
            if v == 3 and l == 1 and 1 <= bi <= 14:
                first_frame = i
                break
    
    if first_frame < 0:
        problems.append((fname, 'No valid MPEG1 LIII frame found', 'BAD_FORMAT'))
        continue
    
    h1 = raw[first_frame+1]
    bi = (raw[first_frame+2] >> 4) & 0xF
    si = (raw[first_frame+2] >> 2) & 3
    cm = (raw[first_frame+3] >> 6) & 3
    pad = (raw[first_frame+2] >> 1) & 1
    
    br = BITRATE[1][bi]
    sr = SRATE[3][si] if si < 3 else 0
    chan = CHAN.get(cm, '?')
    
    # Read Xing/Info/LAME tag
    xing = raw[first_frame+36:first_frame+40]
    has_xing = xing in [b'Xing', b'Info']
    has_lame = b'LAME' in raw[first_frame+36:first_frame+200]
    lame_ver = ''
    if has_lame:
        idx = raw.find(b'LAME', first_frame+36, first_frame+200)
        if idx > 0:
            lame_ver = raw[idx:idx+20].decode('latin-1', errors='replace').strip()
            lame_ver = ''.join(c if 32 <= ord(c) <= 126 else '?' for c in lame_ver)
    
    # Issues
    file_issues = []
    severity = 'ok'
    
    # Critical: old LAME encoder
    if any(crit in lame_ver for crit in CRITICAL_ENCODERS):
        file_issues.append(f'OLD_ENCODER:{lame_ver[:10]}')
        severity = 'critical'
    
    # Critical: dual channel + old encoder
    if cm == 1 and severity == 'critical':
        file_issues.append('DUAL_CHANNEL')
    
    # Warning: dual channel (uncommon, can cause issues)
    if cm == 1 and severity == 'ok':
        file_issues.append('DUAL_CHANNEL')
        severity = 'warning'
    
    # Warning: Info header (CBR with VBR header)
    if xing == b'Info' and severity == 'ok':
        file_issues.append('INFO_HEADER')
        severity = 'warning'
    
    # Warning: large ID3 (>50KB)
    if off > 50000:
        file_issues.append(f'LARGE_ID3:{off//1024}KB')
        severity = 'warning' if severity == 'ok' else severity
    
    # Warning: no Xing/Info header at all
    if not has_xing and not has_lame:
        file_issues.append('NO_VBR_HEADER')
    
    days_str = ','.join(info['days'])
    
    if severity == 'critical':
        problems.append((fname, f'{br}kbps {sr}Hz {chan}', ' | '.join(file_issues), days_str))
    elif severity == 'warning':
        warnings.append((fname, f'{br}kbps {sr}Hz {chan}', ' | '.join(file_issues), days_str))
    else:
        ok_count += 1

print(f"=== OK: {ok_count} tracks ===\n")

print(f"=== WARNINGS: {len(warnings)} tracks ===")
for w in warnings:
    print(f"  days [{w[3]}] {w[0]}  |  {w[1]}  |  {w[2]}")
print()

print(f"=== PROBLEMS: {len(problems)} tracks ===")
for p in problems:
    if len(p) == 3:
        print(f"  {p[0]}  |  {p[1]}  |  {p[2]}")
    else:
        print(f"  days [{p[3]}] {p[0]}  |  {p[1]}  |  {p[2]}")
