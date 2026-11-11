import pathlib, re, json

SRC = pathlib.Path(r"C:\Users\goldl\Downloads\centuration4thobf_deobf_folded.lua")
ls = SRC.read_text(encoding="utf-8").split("\n")
groups = json.load(open(r"C:\Users\goldl\Downloads\fold_scan_groups.json"))

KEYWORDS = {"local", "function", "end", "for", "in", "do", "while", "repeat",
            "until", "if", "then", "else", "elseif", "return", "break", "true",
            "false", "nil", "and", "or", "not"}


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


# safety: no return/break/goto, balanced for/end + if/end + while/end + repeat/until + function/end
def balanced(lines):
    depth = {"for": 0, "if": 0, "while": 0, "repeat": 0, "function": 0}
    for ln in lines:
        code = re.sub(r'"[^"\n]*"', '""', ln)
        code = re.sub(r"'[^'\n]*'", "''", code)
        code = re.sub(r"--.*$", "", code)
        if re.search(r"\b(return|break|goto)\b", code):
            return False
        for w in re.findall(r"\b(for|while|function)\b", code):
            # 'for' here means loop-start only if followed by ...in? keep simple: count
            depth[w if w != "while" else "while"] += 0
        # count opens/closes crudely
        opens = len(re.findall(r"\b(for\b.+?\bin\b|while\b.+?\bdo\b|function\b|repeat\b)", code))
        closes = len(re.findall(r"\bend\b", code)) + len(re.findall(r"\buntil\b", code))
        # track net via stack-ish counting is overkill; require per-line sanity only
        _ = (opens, closes)
    # net counts over whole unit
    text = "\n".join(lines)
    text = re.sub(r'"[^"\n]*"', '""', text)
    text = re.sub(r"'[^'\n]*'", "''", text)
    text = re.sub(r"--.*$", "", text, flags=re.M)
    if len(re.findall(r"\bfor\b", text)) != len(re.findall(r"\bend\b", text)):
        return False
    if text.count("repeat") != len(re.findall(r"\buntil\b", text)):
        return False
    if len(re.findall(r"\bfunction\b", text)) != 0:
        return False
    if re.search(r"\b(return|break|goto)\b", text):
        return False
    return True


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

emitted = []
calls = {}  # start idx -> (helper, args)
hid = 0
for g in groups:
    size, idxs = g["size"], g["idxs"]
    body = ls[idxs[0]:idxs[0] + size]
    if not balanced(body):
        print("UNBALANCED size=%d first=%d SKIP" % (size, idxs[0]))
        continue
    fv = exact_free(body)
    nonv = [v for v in fv if not re.match(r"^[A-Za-z_]+\d+$", v)]
    if nonv:
        print("NONV size=%d first=%d free=%s SKIP" % (size, idxs[0], fv))
        continue
    # verify every occurrence has identical free set
    sets = [exact_free(ls[i:i + size]) for i in idxs]
    if not all(s == fv for s in sets):
        print("NONUNIFORM size=%d SKIP" % size)
        continue
    hid += 1
    hname = "scanCycle%d_%d" % (size, hid)
    params = ", ".join("p%d" % (k + 1) for k in range(len(fv)))
    emits = ["-- [folded] %d identical scan cycles (%d lines each); params: %s" % (
        len(idxs), size, ", ".join(fv) if fv else "none")]
    emits.append("local function %s(%s)" % (hname, params))
    # rename free vars to params inside body copy
    bcopy = list(body)
    for k, v in enumerate(fv):
        bcopy = [re.sub(r"\b%s\b" % re.escape(v), "p%d" % (k + 1), ln) for ln in bcopy]
    emits.extend(bcopy)
    emits.append("end")
    emitted.extend(emits)
    for i in idxs:
        actual = exact_free(ls[i:i + size])
        calls[i] = (hname, actual)
    print("FOLD size=%d count=%d helper=%s params=%s" % (size, len(idxs), hname, fv))

# emit helpers before first call site, in file order
order = sorted(calls)
first = order[0]
skip_ranges = []
for idx in order:
    size = next(g["size"] for g in groups if idx in g["idxs"])
    skip_ranges.append((idx, idx + size))
out2 = []
for idx, ln in enumerate(ls):
    if idx == first:
        out2.append("-- [folded] scan-cycle helpers (repeated Backpack/Character tool scans)")
        out2.extend(emitted)
        out2.append("")
    if any(s <= idx < e for s, e in skip_ranges):
        if idx in calls:
            hname, actual = calls[idx]
            ind = ln[:len(ln) - len(ln.lstrip())]
            out2.append("%s%s(%s)" % (ind, hname, ", ".join(actual)))
        continue
    out2.append(ln)

pathlib.Path(r"C:\Users\goldl\Downloads\centuration4thobf_deobf_folded.lua").write_text("\n".join(out2) + "\n", encoding="utf-8")
print("wrote folded, lines:", len(out2))
