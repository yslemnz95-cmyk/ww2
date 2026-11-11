import pathlib, re
from collections import Counter
ls = pathlib.Path(r"C:\Users\goldl\Downloads\centuration4thobf_deobf_folded.lua").read_text(encoding="utf-8").split("\n")

units = []
i, n = 0, len(ls)
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
            vals = {}
            for j, ln in enumerate(seq[1:10], 1):
                vals[keys[j - 1]] = ln.split("=", 1)[1].strip()
            vals["CanvasSize"] = seq[10].split("=", 1)[1].strip()
            vals["CanvasPosition"] = seq[11].split("=", 1)[1].strip()
            units.append((i, ind, name, vals))
            i += 12
            continue
    i += 1
print("units:", len(units))
for k in ["Size", "BackgroundTransparency", "TextColor3", "Font", "TextSize", "TextXAlignment"]:
    print(k, Counter(u[3][k] for u in units).most_common(3))
orders = [int(re.search(r"(\d+)", u[3]["LayoutOrder"]).group(1)) for u in units]
print("orders sequential:", orders == list(range(orders[0], orders[0] + len(orders))))
print("order range:", orders[0], "..", orders[-1])
bad_canvas = [u for u in units if u[3]["CanvasSize"] != "UDim2.new(0, 0, 0, %d)" % (18 * int(re.search(r"(\d+)", u[3]["LayoutOrder"]).group(1)))]
print("canvas != 18*order:", len(bad_canvas))
# print-line pairing
paired = 0
for (idx, ind, name, vals) in units:
    pass
print("sample texts:")
for u in units[:2] + units[-1:]:
    print("  order", u[3]["LayoutOrder"], u[3]["Text"][:70])
