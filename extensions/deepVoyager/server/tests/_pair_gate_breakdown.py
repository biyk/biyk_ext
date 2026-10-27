import glob
import os
import re

# из stage3_imitate6.log: win-rate по парам в гейте vs battlecast, для стадий BC и BC+PPO
proj = r"C:\Users\b5\AppData\Local\FoundryVTT\Data\modules\biyk_ext\extensions\deepVoyager\server"
log = os.path.join(proj, ".ray", "stage3_imitate6.log")
raw = open(log, "rb").read()
text = raw.decode("utf-16", errors="replace") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else raw.decode("utf-8", errors="replace")

STAGE_RE = re.compile(r"== GEJT: (.*?) ==")
VS_RE = re.compile(r"s3_vs_(\w+)\s*:")
PAIR_RE = re.compile(r"pair\s+(\w+)\s*:\s*win=([0-9.]+)\s+bootCI>=([0-9.]+)\s+fights=(\d+)")

stage = None
opp = None
data = {}  # (stage, opp, pair) -> win
for line in text.splitlines():
    m = STAGE_RE.search(line)
    if m:
        stage = m.group(1).strip()
        continue
    m = VS_RE.search(line)
    if m:
        opp = m.group(1)
        continue
    m = PAIR_RE.search(line)
    if m and stage and opp:
        data[(stage, opp, m.group(1))] = (float(m.group(2)), float(m.group(3)), int(m.group(4)))

# интересуют melee vs melee и ranged vs melee (и зеркало melee vs ranged)
WANT = ["s3w_meleevmelee", "s3w_rangedvmelee", "s3w_meleevranged"]
stages = sorted({s for (s, o, p) in data if o == "battlecast"})
print("стадии в логе vs battlecast:", stages)
for pair in WANT:
    print("\n=== пара %s (vs battlecast) ===" % pair)
    for s in stages:
        rec = data.get((s, "battlecast", pair))
        if rec:
            print("  %-18s win=%.3f bootCI>=%.3f fights=%d" % (s, rec[0], rec[1], rec[2]))
