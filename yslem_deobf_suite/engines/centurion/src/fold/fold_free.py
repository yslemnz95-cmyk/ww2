import pathlib, re, json

groups = json.loads(pathlib.Path(r"C:\Users\goldl\Downloads\fold_scan_groups.json").read_text())
ls = pathlib.Path(r"C:\Users\goldl\Downloads\centuration4thobf_deobf_folded.lua").read_text(encoding="utf-8").split("\n")

KEYWORDS = {"local", "function", "end", "for", "in", "do", "while", "repeat",
            "until", "if", "then", "else", "elseif", "return", "break", "true",
            "false", "nil", "and", "or", "not"}
GLOBALS = {"Players", "ScrollingFrame", "task", "game", "workspace", "string",
           "table", "math", "tostring", "tonumber", "print", "pairs", "ipairs",
           "next", "select", "unpack", "Enum", "Color3", "UDim2", "UDim",
           "Vector2", "Vector3", "CFrame", "Instance", "Ray", "BrickColor",
           "tick", "os", "typeof", "type", "pcall", "xpcall", "error", "assert",
           "warn", "setmetatable", "getmetatable", "rawget", "rawset",
           "rawequal", "coroutine", "utf8", "bit32", "buffer", "debug",
           "collectgarbage", "gcinfo", "newproxy", "getfenv", "setfenv",
           "loadstring", "require", "TextButton2", "TextButton12", "TextButton15",
           "Frame5", "Frame8", "Frame27", "teleBtnOn", "teleBtnOff"}


def exact_free(lines):
    defined = set()
    for ln in lines:
        m = re.match(r"^\s*local ([A-Za-z_]\w*)\b", ln)
        if m:
            defined.add(m.group(1))
        m2 = re.match(r"^\s*for (\w+),\s*(\w+) in", ln)
        if m2:
            defined.add(m2.group(1))
            defined.add(m2.group(2))
        m3 = re.match(r"^\s*for (\w+) in", ln)
        if m3:
            defined.add(m3.group(1))
    ordered = []
    for ln in lines:
        code = re.sub(r'"[^"\n]*"', '""', ln)
        code = re.sub(r"'[^'\n]*'", "''", code)
        code = re.sub(r"--.*$", "", code)
        code = re.sub(r"[.:]([A-Za-z_]\w*)", "", code)
        for m in re.finditer(r"\b([A-Za-z_]\w*)\b", code):
            w = m.group(1)
            if w in KEYWORDS or w in GLOBALS or w in defined or w in ordered:
                continue
            ordered.append(w)
    return ordered


for g in json.load(open(r"C:\Users\goldl\Downloads\fold_scan_groups.json")):
    sets = []
    for i in g["idxs"]:
        sets.append(exact_free(ls[i:i + g["size"]]))
    same = all(s == sets[0] for s in sets)
    print("size=%d count=%d free0=%s uniform=%s" % (g["size"], len(g["idxs"]), sets[0], same))
    if not same:
        for k, s in enumerate(sets[:4]):
            print("   occ%d free=%s" % (k, s))
