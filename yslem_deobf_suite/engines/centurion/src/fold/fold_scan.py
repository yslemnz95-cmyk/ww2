import pathlib, re
from collections import Counter

SRC = pathlib.Path(r"C:\Users\goldl\Downloads\centuration4thobf_deobf_folded.lua")
ls = SRC.read_text(encoding="utf-8").split("\n")

def norm(ln):
    s = ln.strip()
    s = re.sub(r"\d+\.\d+", "#F", s)
    s = re.sub(r"\b([A-Za-z_]+)\d+\b", r"\1", s)
    s = re.sub(r"\d+", "#", s)
    return s

nl = [norm(l) for l in ls]
n = len(ls)

# candidate: blocks starting with Backpack-led line, len 6..14, count>=3 (normalized form)
starts = [i for i, l in enumerate(ls) if re.match(r"^\s*local Backpack\d* = Players\.LocalPlayer:FindFirstChild\(\"Backpack\"\)\s*$", l)]
print("backpack-led starts:", len(starts))

# group by normalized 6/8/10-line head signature
groups = {}
for i in starts:
    for size in (10, 8, 6):
        key = "\n".join(nl[i:i + size])
        groups.setdefault((size, key), []).append(i)

for (size, key), idxs in sorted(groups.items(), key=lambda kv: -len(kv[1])):
    if len(idxs) >= 3:
        print(f"--- size={size} count={len(idxs)} firstline={idxs[0] + 1} ---")
        for l in ls[idxs[0]:idxs[0] + size]:
            print("   ", l[:95])
        # free v-role vars in first occurrence (vNN not defined within unit)
        defined = set()
        for l in ls[idxs[0]:idxs[0] + size]:
            m = re.match(r"^\s*local ([A-Za-z_]\w*)\b", l)
            if m:
                defined.add(re.sub(r"\d+$", "", m.group(1)))
            m2 = re.match(r"^\s*for (\w+),\s*(\w+) in", l)
            if m2:
                defined.add(re.sub(r"\d+$", "", m2.group(1)))
                defined.add(re.sub(r"\d+$", "", m2.group(2)))
        roles = []
        for l in ls[idxs[0]:idxs[0] + size]:
            for m in re.finditer(r"\bv\d+\b", l):
                r = "v"
                if r not in defined and r not in roles:
                    roles.append(r)
        print("    free roles:", roles if roles else "(none: only v-roles normalized?)")
        # more precise: actual var names in order
        actual = []
        seen = set()
        for l in ls[idxs[0]:idxs[0] + size]:
            for m in re.finditer(r"\b(v\d+)\b", l):
                if m.group(1) not in seen:
                    seen.add(m.group(1))
                    actual.append(m.group(1))
        # exclude ones defined inside unit (loop vars iNN/vNN of inner fors)
        inner_defined = set()
        for l in ls[idxs[0]:idxs[0] + size]:
            m2 = re.match(r"^\s*for (\w+),\s*(\w+) in", l)
            if m2:
                inner_defined.add(m2.group(1))
                inner_defined.add(m2.group(2))
        actual = [a for a in actual if a not in inner_defined]
        print("    actual free vars:", actual)
        break
