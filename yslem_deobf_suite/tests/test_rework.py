#!/usr/bin/env python3
"""Rework vitesse/puissance : (1) la detection reconnait les variantes MoonSec V3 (suffixe, en-tete decale) et LuaObfuscator
(`local v0=string.char;...`) et les envoie au moteur de VRAI code source, qui reussit ; (2) l'echeance native du Luau coupe une
boucle de calcul pur (meme protegee par pcall) et la trace partielle sort ; (3) le thread du harnais n'est jamais interrompu.
Usage : python3 tests/test_rework.py"""
import json, os, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import decision as D  # noqa: E402

FAILS = []
def check(cond, label):
    print(("OK   " if cond else "FAIL ") + label, flush=True)
    if not cond:
        FAILS.append(label)

S = ROOT / "tests" / "samples" / "rework"
EXPECT = {"moonsec_suffixe_hash.lua": "moonsec_v3", "moonsec_suffixe_discord.lua": "moonsec_v3", "moonsec_decale.lua": "moonsec_v3",
          "luaobfuscator_v0char.lua": "leakd_luaobfuscator"}
for name, eng in EXPECT.items():
    f = S / name
    d = D.decide(f.read_bytes(), f.name)
    check(d.engine == eng and d.kind == "source" and d.supported, f"{name} : detecte -> {eng} (source), obtenu {d.engine}/{d.kind}")
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "o.lua"
        p = subprocess.run([sys.executable, "-I", str(ROOT / "deobf_router.py"), "run", str(f), str(out), "--json"],
                           capture_output=True, text=True, timeout=300)
        try:
            res = json.loads((p.stdout.strip().splitlines() or ["{}"])[-1])
        except Exception:  # noqa: BLE001
            res = {}
        check(res.get("ok") and res.get("engine") == eng and out.exists() and out.stat().st_size > 100,
              f"{name} : le routeur livre du code via {res.get('engine')} ({out.stat().st_size if out.exists() else 0} octets)")

# ---- echeance native du Luau patche
sys.path.insert(0, str(ROOT))
import bootstrap  # noqa: E402
state = bootstrap.ensure_ready(need_node=True, need_luau=True)
node = state.get("node") or "node"
JS = r'''
const H = require(process.argv[2]);
const tests = {
  boucle_pure: "local n=0 while true do n=n+1 end",
  boucle_pcall: "local n=0 while true do pcall(function() n=n+1 end) end",
  normal: 'print("ok") local x = Instance.new("Part")',
  pile: "local n,m=0,0 local function f() n+=1 if n>m then m=n end local x=setmetatable({}, {__index=f}) local _=x.foo n-=1 end " +
        "pcall(function() local x=setmetatable({}, {__index=f}) return x.bar end) print('depth', m)",
};
(async () => {
  const out = {};
  for (const [k, src] of Object.entries(tests)) {
    const t = Date.now();
    const r = await H.runOnce(H.findLuau(), src, { time_budget: 2, executor: 'Wave' }, process.argv[3] + '/h_' + k + '.luau', 60, false);
    const b = r.body || ('ERR ' + r.err);
    out[k] = { secs: (Date.now() - t) / 1000, status: ((/run status:[^\n]*/.exec(b) || [''])[0]), depth: ((/"depth", (\d+)/.exec(b) || [])[1]) };
  }
  console.log(JSON.stringify(out));
})();
'''
with tempfile.TemporaryDirectory() as td:
    (Path(td) / "t.js").write_text(JS)
    env = dict(os.environ, DEOB_DEADLINE_SLACK="1")
    p = subprocess.run([node, str(Path(td) / "t.js"), str(ROOT / "engines" / "sandbox" / "src" / "harness.js"), td],
                       capture_output=True, text=True, timeout=120, env=env, cwd=str(ROOT / "engines" / "sandbox"))
    try:
        r = json.loads(p.stdout.strip().splitlines()[-1])
    except Exception:  # noqa: BLE001
        r = {}
        print(p.stdout[-400:], p.stderr[-400:])
for k in ("boucle_pure", "boucle_pcall"):
    x = r.get(k, {})
    check("time limit" in x.get("status", "") and x.get("secs", 99) < 10, f"echeance : {k} coupee en {x.get('secs')} s, statut « {x.get('status', '')[12:60]} »")
check("finished" in r.get("normal", {}).get("status", ""), "echeance : un script normal n'est pas coupe (statut finished)")
check(r.get("pile", {}).get("depth") == "198", f"echeance : profondeur de pile C inchangee (198) : {r.get('pile', {}).get('depth')}")

# repli : moteur de source reconnu mais en echec (en-tete MoonSec V3 sur un corps invalide) -> trace, pas "aucun resultat"
import deobf_router as _R  # noqa: E402
with tempfile.TemporaryDirectory() as td:
    src = Path(td) / "in.lua"
    src.write_text('print("bonjour")\n([[This file was protected with MoonSec V3]]):gsub(".", function() end)\n')
    res = _R.deobfuscate(src, Path(td) / "out.lua")
    check(bool(res.get("ok")) and res.get("engine") == "trace" and "moonsec_v3" in (res.get("attempts") or []),
          f"repli : echec du moteur de source -> trace (moteur={res.get('engine')}, essais={res.get('attempts')})")

print()
if FAILS:
    print(f"ECHEC : {len(FAILS)} test(s)")
    sys.exit(1)
print("TOUT OK : rework verifie")
