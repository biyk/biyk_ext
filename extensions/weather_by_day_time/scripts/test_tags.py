from tinytag import TinyTag
import os, glob
mps = sorted(glob.glob('extensions/weather_by_day_time/data/music/**/*.mp3', recursive=True))
missing = []
for p in mps:
    tag = TinyTag.get(p)
    bn = os.path.basename(p)
    if not tag.artist and not tag.album and not tag.title:
        missing.append("{} - ALL MISSING".format(bn))
    elif not tag.artist:
        missing.append("{} - no artist (album={}, title={})".format(bn, tag.album, tag.title))
    elif not tag.album:
        missing.append("{} - no album (artist={}, title={})".format(bn, tag.artist, tag.title))
print("Total MP3s: {}".format(len(mps)))
print("Missing metadata: {}".format(len(missing)))
for m in missing:
    print("  {}".format(m))
