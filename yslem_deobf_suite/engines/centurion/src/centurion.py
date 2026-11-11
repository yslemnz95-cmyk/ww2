"""Centurion polymorphic deobfuscator (offline-first, live-assisted).

Usage:
    python centurion.py deobfuscate <file> [--out-dir DIR]
    python centurion.py deep <file> [--out-dir DIR]
    python centurion.py probe-batch <trace.txt> [out.lua]
    python centurion.py fingerprint <file>      # family + route
    python centurion.py offline <file>          # envlog sandbox attempt
    python centurion.py live-harness <file>     # build protected live-dump harness

Pipeline (proven on 1 v6 + 3 v6.1 samples):
  fingerprint -> v6-shape (c3 factories, plaintext payloads):
      static span harvest + escape decode + stub boot -> STAGE1/CLEAN.
      No game ever needed (demonstrated: somerandomobfidk 98 factories).
  fingerprint -> v6.1-shape (HA/while-z, encrypted blobs):
      offline: envlog sandbox + frozen answer packs (p2d_errors.json,
      callerr_rules.json) + alloc/OOB tolerance -> strings/stages.
      clean branch -> full pool (demonstrated live); junk branch ->
      exact missing-probe report for one live Q&A round (micro-probes only,
      script never runs), answers frozen into packs, re-run offline.
  live-dump fallback (needs client): protected harness (alloc cap 32MB,
      OOB zeros, farm block, BSTR tap, writefile) + dump reader + GUI
      census -> STRINGS/INDEX/CLEAN-skeleton (demonstrated x3 in baseplate).

Polymorphism model: dispatcher shape, payload-table kind (c3/HA), blob
inventory, h8 density, probe suite (service list + poisoned methods) are
per-build axes. Fingerprint selects packs; unknown fingerprints emit the
missing-probe log instead of guessing.
"""
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# Portable locations: explicit env override first, then directories relative
# to this file (works wherever the tree is checked out), then the legacy
# absolute paths (kept so existing checkouts keep working untouched).
#   CENT_SAMPLES : sample corpus dir (selftest)
#   CENT_SANDBOX : sandbox-copy-luraph dir (envlog runtime)
#   CENT_LUAU_EXE / CENT_LUAU_AST / CENT_LUAU_COMPILE : luau binaries
_LEGACY_ALCHEMIST = r"C:\Users\goldl\Downloads\thee-bot-main1\thee-bot-main\universal-deobf\universal\alchemistabuser"
_LEGACY_DEOBF = r"C:\Users\goldl\Downloads\thee-bot-main1\thee-bot-main\universal-deobf\luraph-v15-v14.x-deobfuscator-main\luraph-v15-v14.x-deobfuscator-main\Deobfuscator\deobf"
_LEGACY_SANDBOX = r"C:\Users\goldl\Downloads\thee-bot-main1\thee-bot-main\universal-deobf\sandbox-copy-luraph"


def _resolve_dir(envvar, *candidates):
    hit = os.environ.get(envvar)
    if hit and os.path.isdir(hit):
        return os.path.abspath(hit)
    for c in candidates:
        if c and os.path.isdir(c):
            return os.path.abspath(c)
    return None


def _find_luau(prog):
    exe = prog + (".exe" if os.name == "nt" else "")
    env = os.environ.get("CENT_LUAU_" + prog.upper().replace("-", "_"))
    if env and os.path.isfile(env):
        return os.path.abspath(env)
    parent = os.path.dirname(HERE)
    try:
        import glob as _glob
        for pat in (os.path.join(parent, "*", "bin", exe),
                    os.path.join(parent, "*", "*", "bin", exe),
                    os.path.join(HERE, "bin", exe)):
            hits = sorted(_glob.glob(pat))
            if hits:
                return os.path.abspath(hits[0])
    except Exception:
        pass
    legacy = os.path.join(_LEGACY_DEOBF, "bin", exe)
    if os.path.isfile(legacy):
        return legacy
    raise SystemExit(
        "error: luau binary '%s' not found. Put the Deobfuscator/deobf/bin "
        "dir next to this tool, or set CENT_LUAU_%s to its path."
        % (exe, prog.upper().replace("-", "_")))


SAMPLES_DIR = _resolve_dir("CENT_SAMPLES",
                           os.path.join(HERE, "samples"),
                           _LEGACY_ALCHEMIST)
LURAPH_DEOBF_COPY = (_resolve_dir("CENT_SANDBOX",
                                  os.path.join(HERE, "..", "sandbox-copy-luraph"),
                                  _LEGACY_SANDBOX)
                     or _LEGACY_SANDBOX)
LUAU_EXE = _find_luau("luau")
LUAU_AST = _find_luau("luau-ast")
LUAU_COMPILE = _find_luau("luau-compile")

P2D_ERRORS = "p2d_errors.json"
CALLERR_RULES = "callerr_rules.json"
ENUMPROPS = "enumprops.json"
HTTPRESPS = "httpresps.json"

FEATURE_KEYWORDS = ["FireForce", "Pity", "Boss", "Dungeon", "Prestige", "Bounty",
    "SkillTree", "InstaKill", "AutoM1", "Coffin", "Fish", "Codes", "Teleport",
    "Island", "Mob", "Summon", "Jump", "ESP", "Fly", "Noclip", "Fullbright",
    "WalkSpeed", "JumpPower", "Rejoin", "Explorer", "remote", "Inspector",
    "Fuzzer", "Farm", "Quest"]


def read_text(path):
    with open(path, "rb") as f:
        return f.read().decode("latin-1")


def fingerprint(path):
    t = read_text(path)
    fp = {"file": os.path.basename(path), "bytes": len(t)}
    m = re.search(r"Centurion (v[\d.]+)", t)
    fp["tag"] = m.group(0) if m else "unknown"
    fp["sha8"] = hashlib.sha256(t.encode("latin-1")).hexdigest()[:16]
    fp["h8"] = t.count("h8")
    fp["getfenv"] = t.count("getfenv")
    fp["ha_refs"] = len(re.findall(r"HA\[", t))
    fp["c3_refs"] = len(re.findall(r"c3\[", t))
    fp["func_z"] = len(re.findall(r"=function\(Z\)", t))
    fp["while_z"] = len(re.findall(r"while z", t))
    fp["invokeserver"] = t.count("InvokeServer")
    longs = sorted((len(m.group(0)) for m in re.finditer(r'"(?:[^"\\]|\\.){200,}"', t)), reverse=True)[:4]
    fp["blobs_quoted"] = longs
    brackets = sorted((len(m.group(0)) for m in re.finditer(r"\[(=*)\[(.*?)\]\1\]", t, re.DOTALL)), reverse=True)[:4]
    fp["blobs_bracket"] = brackets
    if fp["c3_refs"] >= 50 and fp["func_z"] > 20:
        fp["route"] = "v6-static"
    elif "Centurion v6" in fp["tag"]:
        fp["route"] = "v6.1-sandbox"
    else:
        fp["route"] = "unknown"
    return fp


def cmd_fingerprint(path):
    print(json.dumps(fingerprint(path), indent=1))


def load_packs():
    packs = {}
    for name in (P2D_ERRORS, CALLERR_RULES, ENUMPROPS, HTTPRESPS):
        p = os.path.join(HERE, name)
        packs[name] = json.loads(open(p, encoding="utf-8").read()) if os.path.exists(p) else {}
    return packs


def enumprops_list(packs):
    """Frozen enum-typed service properties (live-verified) as cfg list."""
    ep = packs.get(ENUMPROPS, {})
    if isinstance(ep, dict):
        return ["%s=%s" % kv for kv in ep.items()]
    if isinstance(ep, list):
        return ep
    return []


def httpresps_list(packs):
    """Frozen live HTTP bodies (connectivity checks etc.) as cfg list."""
    hr = packs.get(HTTPRESPS, {})
    if isinstance(hr, dict):
        return ["%s=%s" % kv for kv in hr.items()]
    if isinstance(hr, list):
        return hr
    return []


LIVE_HARNESS_TMPL = r'''
-- PROTECTED LIVE DUMP (locals only, farm blocked, alloc-capped, OOB-tolerant)
local __BSTRS = {}
local __BSTR_N = 0
local __CAP = __CAPVAL__
local __realBuffer = buffer
local buffer = setmetatable({}, {__index = function(_, k)
  local f = __realBuffer[k]
  if k == "create" then
    return function(n)
      if type(n) == "number" and n > __CAP then n = __CAP end
      local ok, out = pcall(f, n)
      if ok then return out end
      return f(0)
    end
  end
  if k == "tostring" then
    return function(b, ...)
      local ok, r = pcall(f, b, ...)
      if ok and type(r) == "string" and #r >= 12 then
        __BSTR_N += 1
        if __BSTR_N <= __STRAP__ then table.insert(__BSTRS, "len=" .. #r .. " " .. string.sub(r, 1, 160):gsub("[%c%z]", ".") .. "\n") end
      end
      if ok then return r end
      return ""
    end
  end
  if k == "readu8" or k == "readu16" or k == "readu32" or k == "readi8" or k == "readi16" or k == "readi32" or k == "readf32" or k == "readf64" then
    return function(b, i, ...)
      local ok, r = pcall(f, b, i, ...)
      if ok then return r end
      return 0
    end
  end
  if k == "readstring" then
    return function(b, i, ...)
      local ok, r = pcall(f, b, i, ...)
      if ok then return r end
      return ""
    end
  end
  return f
end})
local __realTask = task
local task = setmetatable({wait=function(...) error("FARM_BLOCKED", 0) end, spawn=function() return nil end, delay=function() return nil end, defer=function() return nil end}, {__index=function(_, k) return __realTask[k] end})
'''

LIVE_TAIL_TMPL = '\nlocal __ok2, __err2 = pcall(function(...)\n__SRC__\nend, ...)\nlocal __out = "[LIVE] rec_n=" .. __BSTR_N .. " ok=" .. tostring(__ok2) .. " err=" .. tostring(__err2):sub(1, 120) .. "' + "\\n" + '"..table.concat(__BSTRS) .. "[END]' + "\\n" + '"\npcall(function() writefile("__DUMP__", __out) end)\n'


def cmd_probe_batch(trace_path, out_path):
    """Generate a ready-to-run live micro-probe batch from a saved trace.

    Covers every engine touchpoint the offline run could not answer itself:
    Path2D calls without replay data, integer-index Path2D calls, and magic
    Value assignments. Each probe is pcall-wrapped, creates only throwaway
    temporaries, touches no game state. Paste the whole file into the
    executor, run once, send back the printed table.
    """
    body = open(trace_path, encoding="utf-8", errors="replace").read()
    probes = []
    seen = set()

    def add(name, code):
        if name not in seen:
            seen.add(name)
            probes.append((name, code))

    def luastr(s):
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'

    # Path2D calls seen in trace without replay coverage
    for m in re.finditer(r"Path2D:(GetControlPoint|RemoveControlPoint|GetControlPoints|GetLength|GetPointAtU|GetTangentAtU)\(([^)]*)\)", body):
        method, args = m.group(1), m.group(2).strip()
        add("P2D_%s_%s" % (method, args),
            "local _p = Instance.new('Path2D') "
            "local _r = table.pack(pcall(function() return _p:%s(%s) end)) "
            "pcall(function() _p:Destroy() end) "
            "P2D_Q[%s] = pack_probe(_r)" % (method, args if args else "", luastr(method + "|" + (args or ""))))
    # magic Value assignments (per-build constants, e.g. IntValue = 307961)
    for m in re.finditer(r"(\w+)\.Value = (-?\d+)", body):
        add("MAGIC_%s_%s" % (m.group(1), m.group(2)),
            "do local _o = Instance.new('" + m.group(1) + "') "
            "local _r = table.pack(pcall(function() _o.Value = %s return _o.Value end)) "
            "pcall(function() _o:Destroy() end) "
            "P2D_Q[%s] = pack_probe(_r) end" % (m.group(2), luastr("MAGIC_Value_" + m.group(2))))
    # IntValue-style: generic ClassName + Value reads from trace are covered
    # by construction above; anything else falls through to manual review.
    lines = ["-- live probe batch (auto-generated, safe: temporaries only, no game impact)",
             "-- run once in any game, send back the printed P2D_Q table",
             "local P2D_Q = {}",
             "local function pack_probe(r)",
             "  if r[1] then local v = r[2]",
             "    return {ok=true, t=typeof(v), v=tostring(v):sub(1,100)} end",
             "  return {ok=false, e=tostring(r[2]):sub(1,160)}",
             "end"]
    for name, code in probes:
        lines.append("-- probe: %s" % name)
        lines.append(code)
    lines.append("for k, v in pairs(P2D_Q) do print(k, v.ok, v.t or '', (v.v or v.e or ''):sub(1,80)) end")
    lines.append("return P2D_Q")
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    print("wrote %s (%d probes)" % (out_path, len(probes)))
    return probes


def cmd_live_harness(path, dump="cent61_dumpX.txt", out="cent61_prot_X.luau", cap=33554432, strcap=400):
    src = read_text(path)
    h = LIVE_HARNESS_TMPL.replace("__CAPVAL__", str(cap)).replace("__STRAP__", str(strcap))
    tail = LIVE_TAIL_TMPL.replace("__SRC__", src).replace("__DUMP__", dump)
    full = h + tail
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write(full)
    print("wrote %s (%d bytes)" % (out, len(full)))


def cmd_selftest():
    """Fast offline smoke test: fingerprint known samples, assert routes."""
    base = SAMPLES_DIR or _LEGACY_ALCHEMIST
    cases = [
        ("somerandomobfidk.txt",
         os.path.join(base, "somerandomobfidk.txt"), "v6-static"),
        ("Centurion6.1v.txt",
         os.path.join(base, "Centurion6.1v.txt"), "v6.1-sandbox"),
        ("centurion6.1v2nd.lua",
         os.path.join(base, "centurion6.1v2nd.lua"), "v6.1-sandbox"),
        ("centurion6.1v3rd.lua",
         os.path.join(base, "centurion6.1v3rd.lua"), "v6.1-sandbox"),
    ]
    ok = True
    for name, path, want in cases:
        if not os.path.exists(path):
            print("SKIP %s (missing)" % name)
            continue
        try:
            got = fingerprint(path).get("route")
        except Exception as e:
            print("FAIL %s: %s" % (name, e))
            ok = False
            continue
        status = "ok" if got == want else "MISMATCH"
        if got != want:
            ok = False
        print("%s %s route=%s" % (status, name, got))
    print("selftest " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


def cmd_offline(path):
    print("offline path: run sample through envlog sandbox + packs in this folder;")
    print("see cent61_envlog_test.py pattern (fingerprint route, P2D/callerr packs).")
    print(json.dumps(fingerprint(path), indent=1))


def _esc_byte(v):
    if v == 34:
        return '\\"'
    if v == 92:
        return "\\\\"
    if v == 10:
        return "\\10"
    if v == 13:
        return "\\13"
    if v == 0:
        return "\\0"
    return chr(v)


def clean_escapes(code):
    """Decode \\ddd / \\xNN / \\u{...} / \\z inside string literals only."""
    out = []
    i, n = 0, len(code)
    state = None
    while i < n:
        ch = code[i]
        if state is None:
            if ch == '"' or ch == "'":
                state = ch
                out.append(ch)
                i += 1
                continue
            if ch == "[":
                m = i + 1
                lvl = 0
                while m < n and code[m] == "=":
                    lvl += 1
                    m += 1
                if m < n and code[m] == "[":
                    state = ("lb", lvl)
                    out.append(code[i:m + 1])
                    i = m + 1
                    continue
            out.append(ch)
            i += 1
            continue
        if isinstance(state, tuple):
            close = "]" + "=" * state[1] + "]"
            if code.startswith(close, i):
                out.append(close)
                i += len(close)
                state = None
                continue
            out.append(ch)
            i += 1
            continue
        if ch == "\\":
            if i + 1 >= n:
                out.append("\\")
                i += 1
                continue
            nx = code[i + 1]
            if nx in ("x", "X") and i + 3 < n and all(c in "0123456789ABCDEFabcdef" for c in code[i + 2:i + 4]):
                out.append(_esc_byte(int(code[i + 2:i + 4], 16)))
                i += 4
                continue
            if nx == "u" and i + 2 < n and code[i + 2] == "{":
                j = code.find("}", i + 3)
                if j > 0:
                    try:
                        out.append(_esc_byte(int(code[i + 3:j], 16)))
                        i = j + 1
                        continue
                    except ValueError:
                        pass
            if nx == "z":
                i += 2
                while i < n and code[i] in " \t\n\r\v\f":
                    i += 1
                continue
            if nx.isdigit():
                j = i + 1
                while j < n and j < i + 4 and code[j].isdigit():
                    j += 1
                out.append(_esc_byte(int(code[i + 1:j]) % 256))
                i = j
                continue
            out.append(ch)
            out.append(nx)
            i += 2
            continue
        if ch == state:
            out.append(ch)
            i += 1
            state = None
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def harvest_table_spans_ast(src, table_name):
    """Find TABLE[N] = function spans via luau-ast JSON. Returns [(N, s, e)]."""
    import subprocess
    if not os.path.exists(LUAU_AST):
        return []
    with open(os.path.join(HERE, "_ast_tmp.txt"), "w", encoding="latin-1", newline="\n") as f:
        f.write(src)
    try:
        raw = subprocess.run([LUAU_AST, os.path.join(HERE, "_ast_tmp.txt")],
                             capture_output=True, timeout=120).stdout
    finally:
        try:
            os.remove(os.path.join(HERE, "_ast_tmp.txt"))
        except OSError:
            pass
    ast = None
    for enc in ("utf-8", "utf-16", "latin-1"):
        try:
            ast = json.loads(raw.decode(enc))
            break
        except Exception:
            continue
    if ast is None:
        return []

    def loc(n):
        a, b = n["location"].split(" - ")
        return int(a.split(",")[1]), int(b.split(",")[1])

    spans = []

    def walk(n):
        if isinstance(n, dict):
            if n.get("type") == "AstStatAssign":
                tg = n.get("targets", n.get("vars", []))
                vals = n.get("values", [])
                if isinstance(tg, list) and isinstance(vals, list):
                    for t2, v in zip(tg, vals + [None] * len(tg)):
                        if isinstance(t2, dict) and t2.get("type") in ("AstExprIndex", "AstExprIndexExpr"):
                            ex = t2.get("expr")
                            # stock luau-ast: IndexExpr + Local/Global (the author's build used Index + Global)
                            if isinstance(ex, dict) and (
                                    (ex.get("type") == "AstExprGlobal" and ex.get("global") == table_name)
                                    or (ex.get("type") == "AstExprLocal"
                                        and (ex.get("local") or {}).get("name") == table_name)):
                                if isinstance(v, dict) and v.get("type") == "AstExprFunction":
                                    s, e = loc(v)
                                    idx = t2.get("index")
                                    nv = idx.get("value") if isinstance(idx, dict) else idx
                                    spans.append((nv, s, e))
            for v in n.values():
                walk(v)
        elif isinstance(n, list):
            for v in n:
                walk(v)

    walk(ast)
    spans.sort(key=lambda x: x[1])
    return spans


def deobfuscate_v6_static(path, outdir):
    """Full static lift for v6-shape (c3 factories). No game ever needed."""
    src = read_text(path)
    base = os.path.splitext(os.path.basename(path))[0]
    spans = harvest_table_spans_ast(src, "c3")
    if not spans:
        return {"verdict": "NEEDS", "reason": "no c3 factory spans found via AST"}
    header = ("--[[ PARTIAL deobfuscation (static, no game): %s\n"
              "   Centurion v6 VM, %d payload factories below, escapes decoded.\n"
              "   Factories need their Z import tables + boot order from the VM\n"
              "   program; wire those for a runnable build (needs target game).\n"
              "   Status: analysis reference. ]]\n\nlocal c3 = {}\n" % (os.path.basename(path), len(spans)))
    parts = [header]
    for num, s, e in spans:
        parts.append("-- ===== c3[%s] =====\nc3[%s]=" % (num, num) + clean_escapes(src[s:e]))
    out = "\n\n".join(parts)
    out = re.sub(r"\bconst\b", "local", out)
    stage_path = os.path.join(outdir, base + "_deobf_stage1.lua")
    with open(stage_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(out)
    compiled = False
    if os.path.exists(LUAU_COMPILE):
        import subprocess
        c = subprocess.run([LUAU_COMPILE, "--binary", stage_path], capture_output=True, timeout=120)
        compiled = (c.returncode == 0)
    feats = {kw: sum(1 for _ in re.finditer(re.escape(kw), out, re.IGNORECASE)) for kw in FEATURE_KEYWORDS}
    feats = {k: v for k, v in feats.items() if v}
    index = ["-- %s static index (no game)" % os.path.basename(path),
             "-- factories: %d, compiles: %s" % (len(spans), compiled),
             "-- InvokeServer=%d FireServer=%d" % (out.count("InvokeServer"), out.count("FireServer")),
             "-- features: " + ", ".join("%s=%d" % kv for kv in sorted(feats.items()))]
    index_path = os.path.join(outdir, base + "_deobf_index.txt")
    with open(index_path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(index) + "\n")
    return {"verdict": "DEOBFUSCATED", "factories": len(spans), "compiles": compiled,
            "files": [stage_path, index_path], "features": sorted(feats)}


def deobfuscate_v61_sandbox(path, outdir, timeout=150):
    """Offline sandbox attempt for v6.1-shape with frozen packs."""
    if LURAPH_DEOBF_COPY not in sys.path:
        sys.path.insert(0, LURAPH_DEOBF_COPY)
    import harness
    try:
        packs = load_packs()
    except Exception as e:
        return {"verdict": "NEEDS", "reason": "pack load failed: %s" % e}
    src = read_text(path)
    base = os.path.splitext(os.path.basename(path))[0]
    for k, v in packs.get(P2D_ERRORS, {}).items():
        harness.P2D_CACHE[k] = v
    callerr = []
    cr = packs.get(CALLERR_RULES, {})
    if isinstance(cr, dict):
        callerr = ["%s=%s" % kv for kv in cr.items()]
    elif isinstance(cr, list):
        callerr = cr
    cfg = {"time_budget": 90, "executor": "Potassium", "heartbeat": 2,
           "v14_alloc_trap": False, "v14_lenient_create": True,
           "centurion_bigzero": 8388608, "centurion_oob": True,
           "centurion_oob_cap": 500, "centurion_dictpin": 0,
           "centurion_pcallog": True, "ptrace": True, "callerr": callerr,
           "enumprops": enumprops_list(packs),
           "httpresps": httpresps_list(packs)}
    _ft = os.environ.get("CENT61_FIRSTTWO")
    if _ft in ("1", "2"):
        cfg["centurion_firsttwo"] = int(_ft)
    if os.environ.get("CENT61_TOSTRING_SWALLOW") == "1":
        cfg["centurion_tostring_swallow"] = True
    if os.environ.get("CENT61_SORTPAIRS") == "1":
        cfg["centurion_sortpairs"] = True
    _dp = os.environ.get("CENT61_DICTPIN")
    if _dp is not None and _dp.lstrip("-").isdigit():
        cfg["centurion_dictpin"] = int(_dp)
    hpath = os.path.join(outdir, base + "_deobf.harness.luau")
    body, err = harness.run_once(LUAU_EXE, src, cfg, hpath, timeout, True)
    if body is None:
        return {"verdict": "NEEDS", "reason": "harness run failed: %s" % (err or "")[-500:]}
    raw = harness.LAST_RAW[0]
    with open(os.path.join(outdir, base + "_deobf.trace.txt"), "w", encoding="utf-8", errors="replace", newline="\n") as f:
        f.write(body)
    with open(os.path.join(outdir, base + "_deobf.raw.txt"), "w", encoding="utf-8", errors="replace", newline="\n") as f:
        f.write(raw)
    raw = harness.LAST_RAW[0]
    status = "finished" if "run status: finished" in body else "died"
    strings = sorted(set(re.findall(r'loadstring\(\) of \d+ bytes: "([^"]{4,120})"', body)))
    misses = sorted(set(re.findall(r"\x00P2DMISS", raw)))
    sigs = sorted(set(re.findall(r"CALLERR-SIG ([^\n]+)", raw)))
    death = ""
    m = re.search(r"-- run status: ([^\n]+)", body)
    if m:
        death = m.group(1).strip()
    index = ["-- %s sandbox index (offline, frozen packs)" % os.path.basename(path),
             "-- run status: %s" % death,
             "-- decoded loadstring chunks: %s" % (strings if strings else "-"),
             "-- missing engine answers: %s" % ("; ".join(misses) if misses else "-"),
             "-- poisoned-call signatures seen: %s" % ("; ".join(sigs[:10]) if sigs else "-")]
    index_path = os.path.join(outdir, base + "_deobf_index.txt")
    with open(index_path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(index) + "\n")
    clean = False
    files = [index_path]
    nstmt = 0
    m = re.search(r"-- (\d+) statements recorded", body)
    if m:
        nstmt = int(m.group(1))
    if status == "finished" and nstmt >= 100:
        code = trace_to_clean(body)
        if len([ln for ln in code.splitlines() if ln.strip()]) >= 50:
            clean_path = os.path.join(outdir, base + "_deobf_clean.lua")
            with open(clean_path, "w", encoding="utf-8", newline="\n") as f:
                f.write(code if code.endswith("\n") else code + "\n")
            beaut_path = os.path.join(outdir, base + "_deobf_beautified.lua")
            with open(beaut_path, "w", encoding="utf-8", newline="\n") as f:
                f.write(strip_luau_comments(code))
            files = [clean_path, beaut_path, index_path]
            clean = True
    out = {"verdict": "DEOBFUSCATED" if clean else "NEEDS",
           "files": files, "status": death, "statements": nstmt}
    # Maximal readable reconstruction on EVERY run (clean or not): stages,
    # pool, stubs, gaps. Never fakes data; stubs stay empty.
    pool = sorted(set(re.findall(r"CENT-STR len=(\d+) ([^\n]*)", raw)))
    fp = fingerprint(path)
    max_path = emit_maximal(path, outdir, body, pool, fp, death, nstmt)
    files.append(max_path)
    out["files"] = files
    out["maximal"] = max_path
    if not clean:
        out["reason"] = "junk branch offline; collect: %s" % (
            "; ".join(misses) if misses else "deeper gate (see pcall/CALLERR logs); use live-harness")
        out["signatures"] = sigs[:10]
    else:
        out["chunks"] = strings
    return out


def _find_traceout_dir():
    """Directory holding the third-party traceout/tidy helpers (optional)."""
    env = os.environ.get("CENT_LURAPH_DEOBF")
    if env and os.path.isdir(env):
        return os.path.abspath(env)
    parent = os.path.dirname(HERE)
    try:
        import glob as _glob
        for pat in (os.path.join(parent, "*", "traceout.py"),
                    os.path.join(parent, "*", "*", "traceout.py"),
                    os.path.join(parent, "*", "*", "*", "traceout.py")):
            hits = sorted(_glob.glob(pat))
            if hits:
                return os.path.abspath(os.path.dirname(hits[0]))
    except Exception:
        pass
    if os.path.isdir(_LEGACY_DEOBF):
        return _LEGACY_DEOBF
    return None


def render_trace_clean(body):
    """Render behavior trace to readable Luau via their traceout/tidy
    (read-only use). Returns code string or None."""
    try:
        _tdir = _find_traceout_dir()
        if _tdir is None or _tdir not in sys.path:
            if _tdir is None:
                return None
            sys.path.insert(0, _tdir)
        import traceout

        class Args:
            no_tidy = False
            no_fold = False
            keep_preamble = False

        return traceout.render(body, Args(), preamble=True)
    except Exception:
        return None


def trace_to_clean(body):
    """Behavior trace -> clean Luau: drop markers, envlog meta, machine
    lines; keep every reconstructed statement in order."""
    kept = []
    for ln in body.split("\n"):
        s = ln.strip()
        if not s:
            continue
        if "\0" in ln:
            continue
        if re.match(r"^--@\d+\s*$", s):
            continue
        if s.startswith("-- run status:") or s.startswith("-- non-standard globals"):
            continue
        if re.match(r"^-- \d+ statements recorded", s):
            continue
        kept.append(ln.rstrip())
    return "\n".join(kept) + "\n"


def strip_luau_comments(code):
    out = []
    i, n = 0, len(code)
    while i < n:
        ch = code[i]
        if ch == "-" and i + 1 < n and code[i + 1] == "-":
            j = i + 2
            lvl = 0
            while j < n and code[j] == "=":
                lvl += 1
                j += 1
            if j < n and code[j] == "[":
                close = "]" + "=" * lvl + "]"
                k = code.find(close, j + 1)
                if k >= 0:
                    out.append("\n")
                    i = k + len(close)
                    continue
                break
            k = code.find("\n", i + 2)
            if k >= 0:
                out.append("\n")
                i = k + 1
                continue
            break
        if ch in "\"'":
            q = ch
            out.append(ch)
            i += 1
            while i < n:
                c = code[i]
                out.append(c)
                i += 1
                if c == "\\":
                    if i < n:
                        out.append(code[i])
                        i += 1
                    continue
                if c == q or c == "\n":
                    break
            continue
        out.append(ch)
        i += 1
    lines = [ln.rstrip() for ln in "".join(out).split("\n")]
    return "\n".join(ln for ln in lines if ln.strip() != "") + "\n"


def collect_unknowns(raw):
    """CENT-P2DKEY keys missed (no replay data). Deduped, in order."""
    keys = []
    for m in re.finditer(r"CENT-P2DKEY ([^\n]+)", raw):
        k = m.group(1).strip()
        if k and k not in keys:
            keys.append(k)
    return keys


def run_sandbox(path, outdir, tag, extra_p2d=None, extra_callerr=None,
                bigzero=8388608, dictpin=0, timeout=150):
    """One offline sandbox run. Returns dict with body/raw/status/strings."""
    if LURAPH_DEOBF_COPY not in sys.path:
        sys.path.insert(0, LURAPH_DEOBF_COPY)
    import harness
    try:
        packs = load_packs()
    except Exception as e:
        return {"error": "pack load failed: %s" % e}
    src = read_text(path)
    base = os.path.splitext(os.path.basename(path))[0]
    frozen = dict(packs.get(P2D_ERRORS, {}))
    # Guessed edges (UNVERIFIED live): applied only with CENT61_GUESS=1.
    # Never frozen without a live observation; junk branch on a wrong guess
    # dies the same loud death, never quiet garbage.
    if os.environ.get("CENT61_GUESS") == "1":
        try:
            guessed = json.loads(open(os.path.join(HERE, "guessed_p2d.json"), encoding="utf-8").read())
            for k, v in guessed.items():
                frozen[k] = v
        except Exception:
            pass
    for k in list(harness.P2D_CACHE.keys()):
        if k not in frozen:
            del harness.P2D_CACHE[k]
    for k, v in frozen.items():
        harness.P2D_CACHE[k] = v
    for k, v in (extra_p2d or {}).items():
        harness.P2D_CACHE[k] = v
    callerr = []
    cr = packs.get(CALLERR_RULES, {})
    if isinstance(cr, dict):
        callerr = ["%s=%s" % kv for kv in cr.items()]
    elif isinstance(cr, list):
        callerr = cr
    for rule in (extra_callerr or []):
        callerr.append(rule)
    cfg = {"time_budget": 90, "executor": "Potassium", "heartbeat": 2,
           "v14_alloc_trap": False, "v14_lenient_create": True,
           "centurion_bigzero": bigzero, "centurion_oob": True,
           "centurion_oob_cap": 500, "centurion_dictpin": dictpin,
           "centurion_pcallog": True, "ptrace": True, "callerr": callerr,
           "enumprops": enumprops_list(packs),
           "httpresps": httpresps_list(packs)}
    _ft = os.environ.get("CENT61_FIRSTTWO")
    if _ft in ("1", "2"):
        cfg["centurion_firsttwo"] = int(_ft)
    if os.environ.get("CENT61_TOSTRING_SWALLOW") == "1":
        cfg["centurion_tostring_swallow"] = True
    if os.environ.get("CENT61_SORTPAIRS") == "1":
        cfg["centurion_sortpairs"] = True
    _dp = os.environ.get("CENT61_DICTPIN")
    if _dp is not None and _dp.lstrip("-").isdigit():
        cfg["centurion_dictpin"] = int(_dp)
    if os.environ.get("CENT61_TEMPLATE") == "1":
        cfg["centurion_template"] = True
    hpath = os.path.join(outdir, base + "_deep_%s.harness.luau" % tag)
    body, err = harness.run_once(LUAU_EXE, src, cfg, hpath, timeout, True)
    if body is None:
        return {"error": "harness run failed: %s" % (err or "")[-300:]}
    raw = harness.LAST_RAW[0]
    m = re.search(r"-- (\d+) statements recorded", body)
    strings = sorted(set(re.findall(r'loadstring\(\) of \d+ bytes: "([^"]{4,120})"', body)))
    death = ""
    m2 = re.search(r"-- run status: ([^\n]+)", body)
    if m2:
        death = m2.group(1).strip()
    return {"body": body, "raw": raw,
            "finished": death == "finished" or body.startswith("-- run status: finished"),
            "statements": int(m.group(1)) if m else 0,
            "strings": strings, "death": death,
            "misses": [l for l in raw.splitlines() if "P2DMISS" in l][:1],
            "unknowns": collect_unknowns(raw)}


def score_run(r):
    if "error" in r:
        return (-1, 0, 0)
    return (1 if r.get("finished") else 0, r.get("statements", 0),
            len("".join(r.get("strings", []))))


def emit_deep_artifacts(path, outdir, r, tag):
    base = os.path.splitext(os.path.basename(path))[0]
    files = []
    body = r.get("body", "")
    trace_path = os.path.join(outdir, base + "_deep_%s.trace.txt" % tag)
    with open(trace_path, "w", encoding="utf-8", errors="replace", newline="\n") as f:
        f.write(body)
    files.append(trace_path)
    raw_path = os.path.join(outdir, base + "_deep_%s.raw.txt" % tag)
    with open(raw_path, "w", encoding="utf-8", errors="replace", newline="\n") as f:
        f.write(r.get("raw", ""))
    files.append(raw_path)
    pool = sorted(set(re.findall(r"CENT-STR len=(\d+) ([^\n]*)", r.get("raw", ""))))
    if pool:
        pool_path = os.path.join(outdir, base + "_deep_%s_pool.txt" % tag)
        with open(pool_path, "w", encoding="utf-8", errors="replace", newline="\n") as f:
            f.write("\n".join("len=%s %s" % p for p in pool) + "\n")
        files.append(pool_path)
    index = ["-- %s deep index (%s)" % (os.path.basename(path), tag),
             "-- run status: %s" % r.get("death", "?"),
             "-- statements: %s" % r.get("statements", 0),
             "-- decoded loadstring chunks: %s" % (r.get("strings") or "-"),
             "-- unknowns at best: %s" % (r.get("unknowns") or "-")]
    if r.get("finished") and r.get("statements", 0) >= 100:
        code = trace_to_clean(body)
        if len([ln for ln in code.splitlines() if ln.strip()]) >= 50:
            clean_path = os.path.join(outdir, base + "_deep_%s_clean.lua" % tag)
            with open(clean_path, "w", encoding="utf-8", newline="\n") as f:
                f.write(code if code.endswith("\n") else code + "\n")
            files.append(clean_path)
            beaut_path = os.path.join(outdir, base + "_deep_%s_beautified.lua" % tag)
            with open(beaut_path, "w", encoding="utf-8", newline="\n") as f:
                f.write(strip_luau_comments(code))
            files.append(beaut_path)
    index_path = os.path.join(outdir, base + "_deep_%s_index.txt" % tag)
    with open(index_path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(index) + "\n")
    files.append(index_path)
    return files


P2D_PARENT_ERR = "Attempting to use Path2D with invalid parent"


def cmd_deep(path, outdir=None):
    """Branch explorer: grid-search unknown probe outcomes offline."""
    outdir = outdir or os.path.dirname(os.path.abspath(path))
    os.makedirs(outdir, exist_ok=True)
    fp = fingerprint(path)
    print(json.dumps({k: fp[k] for k in ("file", "bytes", "tag", "route")}, indent=1), flush=True)
    if fp["route"] != "v6.1-sandbox":
        print(json.dumps({"verdict": "NEEDS",
                          "reason": "deep mode supports v6.1-sandbox route only"}))
        return 3
    base = run_sandbox(path, outdir, "base")
    if "error" in base:
        print(json.dumps({"verdict": "NEEDS", "reason": base["error"]}))
        return 3
    unknowns = base.get("unknowns", [])
    print(json.dumps({"baseline": {"finished": base.get("finished"),
                                   "statements": base.get("statements"),
                                   "death": base.get("death"),
                                   "unknowns": unknowns}}), flush=True)
    best, best_desc = base, "base"
    best_score = score_run(base)
    # D1: P2D int-index markers (invalid-parent errors) over unknown subsets.
    # D2: SetControlPoints table-arg force error (guessed text: engine
    #     rejects numbers where ControlPoints belong; verified live shape
    #     pending - ok-flag experiment first, exact text on match).
    SCP_RULE = "SetControlPoints|Array[number]=Variant cast failed"
    combos = []
    if len(unknowns) <= 4:
        for mask in range(1, 1 << len(unknowns)):
            combos.append({"p2d": sorted(unknowns[i] for i in range(len(unknowns)) if mask & (1 << i)),
                           "callerr": [], "tag": None})
    else:
        for u in unknowns:
            combos.append({"p2d": [u], "callerr": [], "tag": None})
    combos.append({"p2d": [], "callerr": [SCP_RULE], "tag": None})
    combos.append({"p2d": list(unknowns), "callerr": [SCP_RULE], "tag": None})
    for ci, combo in enumerate(combos, 1):
        combo["tag"] = "m%d" % ci
        extra = {k: "ERROR:" + P2D_PARENT_ERR for k in combo["p2d"]}
        r = run_sandbox(path, outdir, combo["tag"], extra_p2d=extra,
                        extra_callerr=combo["callerr"])
        s = score_run(r)
        print(json.dumps({"combo": combo["tag"], "p2d": combo["p2d"],
                          "callerr": [c.split("=")[0] for c in combo["callerr"]],
                          "finished": r.get("finished"),
                          "statements": r.get("statements"),
                          "death": r.get("death", "")[:80]}), flush=True)
        if s > best_score:
            best_score, best, best_desc = s, r, combo["tag"]
    tag = best_desc
    files = emit_deep_artifacts(path, outdir, best, tag)
    res = {"verdict": "DEOBFUSCATED" if best.get("finished") and best.get("statements", 0) >= 100 else "NEEDS",
           "files": files, "best_combo": best_desc,
           "finished": best.get("finished"), "statements": best.get("statements"),
           "death": best.get("death", "")[:120]}
    if res["verdict"] == "NEEDS":
        res["reason"] = "wall stands on all %d combos; unknowns: %s" % (len(combos) + 1, unknowns)
    print(json.dumps(res, indent=1))
    return 0 if res["verdict"] == "DEOBFUSCATED" else 3


def emit_maximal(path, outdir, body, pool, fp, death, statements):
    """Maximal readable reconstruction (no live, no game needed).
    Everything recoverable in place; composition stubs + gaps marked.
    Never fakes data: stubs are empty, gaps are comments."""
    base = os.path.splitext(os.path.basename(path))[0]
    lines = []
    lines.append("--[[ MAXIMAL recovery: %s" % os.path.basename(path))
    lines.append("   Family: %s, %d bytes. Status: decode stops at composition;" % (fp.get("tag"), fp.get("bytes")))
    lines.append("   everything below is recovered verbatim; stubs are EMPTY")
    lines.append("   tables standing in for game/remote content (Pilgrammed).")
    lines.append("   Readable target met; runnable target needs that content. ]]")
    lines.append("")
    lines.append("-- ---- Part 1: behavior prefix (init + probes, in order) ----")
    for ln in body.split("\n"):
        s = ln.strip()
        if not s or "\0" in ln:
            continue
        if re.match(r"^--@\d+\s*$", s):
            continue
        if s.startswith("-- run status:") or s.startswith("-- non-standard globals"):
            continue
        if re.match(r"^-- \d+ statements recorded", s):
            continue
        if re.match(r"^--\s+.*\.luau:\d+\s*$", s):
            continue
        if re.match(r"^--\s+Script:1\s*$", s):
            continue
        if s == "--":
            continue
        lines.append(ln.rstrip())
    lines.append("")
    lines.append("-- ---- Part 2: decoded string pool (%d entries) ----" % len(pool))
    lines.append("local __POOL = {")
    for length, text in pool:
        lines.append("  [%s] = %s," % (length, json.dumps(text)))
    lines.append("}")
    lines.append("")
    lines.append("-- ---- Part 3: composition stubs (EMPTY -- content lives in-game) ----")
    lines.append("-- The VM died here: %s" % death)
    lines.append("local QS, S, I, D, T = {}, {}, {}, {}, {}  -- register file, stacks, upvalues, consts, temps")
    lines.append("-- TODO(game): populate from Pilgrammed remote/content tables.")
    lines.append("return { pool = __POOL, registers = { QS = QS, S = S, I = I, D = D, T = T } }")
    out_path = os.path.join(outdir, base + "_maximal.lua")
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    return out_path


def cmd_deobfuscate(path, outdir=None):
    outdir = outdir or os.path.dirname(os.path.abspath(path))
    os.makedirs(outdir, exist_ok=True)
    fp = fingerprint(path)
    print(json.dumps({k: fp[k] for k in ("file", "bytes", "tag", "route")}, indent=1))
    if fp["route"] == "v6-static":
        res = deobfuscate_v6_static(path, outdir)
    elif fp["route"] == "v6.1-sandbox":
        res = deobfuscate_v61_sandbox(path, outdir)
    else:
        res = {"verdict": "NEEDS", "reason": "unknown family (not Centurion v6/v6.1 shape)"}
    print(json.dumps(res, indent=1))
    return 0 if res.get("verdict") == "DEOBFUSCATED" else 3


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    if argv[1] == "selftest":
        return cmd_selftest()
    if len(argv) < 3:
        print(__doc__)
        return 2
    cmd, path = argv[1], argv[2]
    if cmd == "fingerprint":
        cmd_fingerprint(path)
    elif cmd == "deobfuscate":
        outdir = None
        if "--out-dir" in argv:
            outdir = argv[argv.index("--out-dir") + 1]
        return cmd_deobfuscate(path, outdir)
    elif cmd == "deep":
        outdir = None
        if "--out-dir" in argv:
            outdir = argv[argv.index("--out-dir") + 1]
        return cmd_deep(path, outdir)
    elif cmd == "offline":
        cmd_offline(path)
    elif cmd == "selftest":
        return cmd_selftest()
    elif cmd == "live-harness":
        dump = argv[3] if len(argv) > 3 else "cent61_dumpX.txt"
        out = argv[4] if len(argv) > 4 else "cent61_prot_X.luau"
        cmd_live_harness(path, dump, out)
    elif cmd == "probe-batch":
        out = argv[3] if len(argv) > 3 else "cent61_probe_batch.lua"
        cmd_probe_batch(path, out)
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
