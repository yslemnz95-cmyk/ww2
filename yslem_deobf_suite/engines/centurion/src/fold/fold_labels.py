import pathlib, re
ls = pathlib.Path(r"C:\Users\goldl\Downloads\centuration4thobf_deobf_folded.lua").read_text(encoding="utf-8").split("\n")

def norm(ln):
    s = ln.strip()
    s = re.sub(r"\d+\.\d+", "#F", s)
    s = re.sub(r"\b([A-Za-z_]+)\d+\b", r"\1", s)
    s = re.sub(r"\d+", "#", s)
    return s

# find 12-line label units in folded file
units = []
i = 0
n = len(ls)
while i < n:
    m = re.match(r"^(\s*)local (TextLabel\d+) = Instance\.new\(\"TextLabel\"\)\s*$", ls[i])
    if m:
        ind, name = m.group(1), m.group(2)
        seq = ls[i:i + 12]
        ok = len(seq) == 12
        keys = []
        if ok:
            for j, ln in enumerate(seq[1:], 1):
                mm = re.match(r"^\s*" + re.escape(name) + r"\.(\w+)\s*=", ln)
                if j <= 9:
                    if not mm:
                        ok = False
                        break
                    keys.append(mm.group(1))
                else:
                    if not re.match(r"^\s*ScrollingFrame\.(CanvasSize|CanvasPosition)\s*=", ln):
                        ok = False
                        break
        if ok and keys == ["Size", "BackgroundTransparency", "Text", "TextColor3", "Font",
                           "TextSize", "TextXAlignment", "LayoutOrder", "Parent"]:
            texts = re.search(r'Text = (".*")\s*$', seq[3])
            order = re.search(r"LayoutOrder = (\d+)", seq[8])
            # following print line?
            pl = ls[i + 12] if i + 12 < n else ""
            pm = re.match(r'^\s*print\("\[farm\] " \.\. tostring\((.*)\)\)\s*$', pl)
            units.append((i, ind, name, texts.group(1) if texts else "?",
                          order.group(1) if order else "?", pm.group(1) if pm else None))
            i += 12
            continue
    i += 1
print("label units:", len(units))
ts = [u for u in units if re.match(r'^"\[\d\d:\d\d:\d\d\] ', u[3])]
print("with [HH:MM:SS] prefix:", len(ts), "/", len(units))
nopr = [u for u in units if u[5] is None]
print("without trailing print:", len(nopr))
# check print exprs reference vNN locals
vrefs = set()
for u in units:
    if u[5]:
        vrefs.update(re.findall(r"\bv\d+\b", u[5]))
print("distinct vNN refs in prints:", len(vrefs))
# canvas derivability: CanvasSize == 18*order?
import json
print(json.dumps([u[3][:50] for u in units[:3]]))
