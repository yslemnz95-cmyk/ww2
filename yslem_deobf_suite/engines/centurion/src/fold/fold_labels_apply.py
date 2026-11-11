import pathlib, re

SRC = pathlib.Path(r"C:\Users\goldl\Downloads\centuration4thobf_deobf_folded.lua")
ls = SRC.read_text(encoding="utf-8").split("\n")

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
            texts = re.search(r'Text = (".*")\s*$', seq[3])
            order = re.search(r"LayoutOrder = (\d+)", seq[8])
            units.append((i, ind, name, texts.group(1) if texts else '"?"',
                          order.group(1) if order else "0"))
            i += 12
            continue
    i += 1
print("label units:", len(units))
assert len(units) == 135, len(units)

helper = '''-- [folded] 135 log-row creations (12-line boilerplate each) collapsed
-- to one call per row. Order/text preserved verbatim; per-row print()
-- echoes left inline. No Name is set (faithful: original never sets one,
-- so Clear-Log lookup below behaves identically).
local function logRow(order, text)
    local row = Instance.new("TextLabel")
    row.Size = UDim2.new(1, -8, 0, 16)
    row.BackgroundTransparency = 1
    row.Text = text
    row.TextColor3 = Color3.fromRGB(200, 200, 210)
    row.Font = Enum.Font.Code
    row.TextSize = 11
    row.TextXAlignment = Enum.TextXAlignment.Left
    row.LayoutOrder = order
    row.Parent = ScrollingFrame
    ScrollingFrame.CanvasSize = UDim2.new(0, 0, 0, 18 * order)
    ScrollingFrame.CanvasPosition = Vector2.new(0, 18 * order)
end'''

out = []
placed = False
skip_until = -1
rows = {u[0]: u for u in units}
for idx, ln in enumerate(ls):
    if idx in rows:
        _, ind, name, text, order = rows[idx]
        if not placed:
            out.append(helper)
            placed = True
        out.append('%slogRow(%s, %s)' % (ind, order, text))
        skip_until = idx + 11
        continue
    if idx <= skip_until:
        continue
    out.append(ln)

folded = "\n".join(out) + "\n"
DST = pathlib.Path(r"C:\Users\goldl\Downloads\centuration4thobf_deobf_folded.lua")
DST.write_text(folded, encoding="utf-8")
print("in:", len(ls), "out:", len(out))
