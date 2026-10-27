import json
import os
import sys

proj = r"C:\Users\b5\AppData\Local\FoundryVTT\Data\modules\biyk_ext\extensions\deepVoyager\server"
bj = os.path.join(proj, "tools", "trace_viewer", "battles.json")
d = json.load(open(bj, encoding="utf-8"))
print("generated=", d.get("generated"))
print("files=", d.get("files"))
print("n_battles=", len(d.get("battles", [])))
print("roleStats_len=", len(d.get("roleStats", [])))
if d.get("battles"):
    b = d["battles"][0]
    print("sample_dealt/taken/uid=", b.get("dealt"), b.get("taken"), b.get("battleUid"))
    print("sample_hasTags=", b.get("hasTags"), "hasRewardLines=", b.get("hasRewardLines"))
