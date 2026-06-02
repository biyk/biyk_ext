from tinytag import TinyTag
import os, glob, unicodedata
mps = glob.glob('extensions/weather_by_day_time/data/music/**/*.mp3', recursive=True)
for p in mps:
    tag = TinyTag.get(p)
    for key in ('artist', 'album', 'title'):
        v = getattr(tag, key)
        if v:
            norm = unicodedata.normalize("NFKC", v)
            if any(ord(c) > 127 for c in norm):
                print("FILE: {}".format(os.path.basename(p)))
                print("  {} raw: {!r}".format(key, v))
                print("  {} nfkc: {!r}".format(key, norm))
