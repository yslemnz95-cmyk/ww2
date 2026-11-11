import pathlib, re

SRC = pathlib.Path(r"C:\Users\goldl\Downloads\centuration4thobf_deobf_folded.lua")
ls = SRC.read_text(encoding="utf-8").split("\n")

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


def norm(ln):
    s = ln.strip()
    s = re.sub(r"\d+\.\d+", "#F", s)
    s = re.sub(r"\b([A-Za-z_]+)\d+\b", r"\1", s)
    s = re.sub(r"\d+", "#", s)
    return s


def free_vars(lines):
    """vNN-style free vars in order (excluding loop vars + locals + methods/fields)."""
    defined = set()
    for ln in lines:
        m = re.match(r"^\s*local ([A-Za-z_]\w*)\b", ln)
        if m:
            defined.add(re.sub(r"\d+$", "", m.group(1)))
        m2 = re.match(r"^\s*for (\w+),\s*(\w+) in", ln)
        if m2:
            defined.add(re.sub(r"\d+$", "", m2.group(1)))
            defined.add(re.sub(r"\d+$", "", m2.group(2)))
    # strip method calls (:name) and field access (.name) and strings
    ordered, seen = [], set()
    for ln in lines:
        code = re.sub(r'"[^"\n]*"', '""', ln)
        code = re.sub(r"'[^'\n]*'", "''", code)
        code = re.sub(r"--.*$", "", code)
        code = re.sub(r"[.:]([A-Za-z_]\w*)", "", code)
        for m in re.finditer(r"\b([A-Za-z_]\w*)\b", code):
            w = m.group(1)
            if w in KEYWORDS or w in GLOBALS:
                continue
            base = re.sub(r"\d+$", "", w)
            if base in defined:
                continue
            if w not in seen:
                seen.add(w)
                ordered.append(w)
    return ordered


n = len(ls)
nl = [norm(l) for l in ls]
starts = [i for i, l in enumerate(ls)
          if re.match(r"^\s*local Backpack\d* = Players\.LocalPlayer:FindFirstChild\(\"Backpack\"\)\s*$", l)]
print("backpack starts:", len(starts))

# group occurrences by normalized block (sizes 6..14)
groups = {}
for i in starts:
    for size in (14, 12, 10, 8, 6):
        if i + size > n:
            continue
        key = (size, "\n".join(nl[i:i + size]))
        groups.setdefault(key, []).append(i)

# keep non-overlapping maximal groups, biggest coverage first
used = [False] * n
chosen = []
for (size, key), idxs in sorted(groups.items(), key=lambda kv: -len(kv[1]) * kv[0][0]):
    if len(idxs) < 3:
        continue
    ok = [i for i in idxs if not any(used[i:i + size])]
    if len(ok) < 3:
        continue
    # self-containment / params from first occurrence
    fv = free_vars(ls[ok[0]:ok[0] + size])
    bad = [v for v in fv if not re.match(r"^[A-Za-z_]+\d+$", v)]
    if bad:
        print("SKIP size=%d count=%d nonparam-free=%s" % (size, len(ok), bad[:5]))
        continue
    for i in ok:
        for j in range(i, i + size):
            used[j] = True
    chosen.append((size, key, ok, fv))
    print("TAKE size=%d count=%d params=%s firstline=%d" % (size, len(ok), fv, ok[0] + 1))

print("chosen groups:", len(chosen))
import json
json_out = [{"size": s, "idxs": idxs, "params": fv} for s, k, idxs, fv in chosen]
pathlib.Path(r"C:\Users\goldl\Downloads\fold_scan_groups.json").write_text(json.dumps(json_out), encoding="utf-8")
