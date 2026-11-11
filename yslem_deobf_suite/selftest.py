#!/usr/bin/env python3
"""
selftest.py -- verifie la suite de bout en bout.

  1. DETECTION : chaque echantillon de tests/samples/ doit etre attribue au bon moteur
     (et un script Lua ordinaire a AUCUN) ;
  2. EXECUTION : pour chaque moteur dont les prerequis sont presents, deobfusque son
     echantillon et verifie le contenu attendu (les moteurs sans prerequis sont SKIP, pas FAIL) ;
  3. GARDE-FOU OWNER : tests/test_owner_guard.py (si discord.py est installe).

Code de sortie 0 si aucun FAIL.   Usage : python3 selftest.py [--fast] [--only NOM]
  --fast : detection + garde-fou uniquement (pas d'execution des moteurs)
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import deobf_router as R  # noqa: E402

SAMPLES = HERE / "tests" / "samples"

# (fichier, moteur attendu ou None, sous-chaine attendue dans la sortie ou None, execution ?, timeout)
CASES = [
    ("plain.lua",              None,                  None,                    False, 0),
    ("legaxyobf.lua",          "legaxyobf",           "protected by legaxyobf", True, 120),
    ("wearedevs.lua",         "wearedevs",           "Source RECONSTRUIT (WeAreDevs", True, 420),
    ("wearedevs_payload.lua", "wearedevs",           "Fluent-Renewed",        True, 420),
    ("moonsec_v2.lua",        "moonsec_trace",       "TRACE (MoonSec",        True, 240),
    ("moonsec_v3.lua",        "moonsec_v3",          "MoonSec V3 [decompile]", True, 240),
    ("psu.lua",               "psu_trace",           "TRACE (PSU",            True, 240),
    ("ironbrew1.lua",          "deobf_py",            None,                    True, 300),
    ("hercules_vm.lua",        "hercules",            None,                    True, 120),
    ("ironveil.lua",           "ironveil",            None,                    True, 120),
    ("leakd_luaobfuscator.lua", "leakd_luaobfuscator", None,                   False, 0),
    ("centurion_v6.lua",       "centurion_v6",        None,                    False, 0),
]


def main() -> int:
    fast = "--fast" in sys.argv
    only = sys.argv[sys.argv.index("--only") + 1] if "--only" in sys.argv else None
    engines = R.load_engines()
    by_name = {e.name: e for e in engines}
    fails = 0
    print(f"== Moteurs charges : {', '.join(sorted(by_name)) or 'AUCUN'}\n")

    print("== 1. Detection")
    for fname, want, _, _, _ in CASES:
        path = SAMPLES / fname
        if not path.exists():
            print(f"  [SKIP] {fname:28} echantillon absent")
            continue
        det = R.detect_text(R.read_text(path), engines)
        got = det[0][0] if det and det[0][1] >= R.MIN_CONFIDENCE else None
        if want is not None and want not in by_name:
            print(f"  [SKIP] {fname:28} moteur '{want}' non installe")
            continue
        ok = got == want
        fails += 0 if ok else 1
        shown = ", ".join(f"{n} {c:.2f}" for n, c, _ in det[:3]) or "aucun"
        print(f"  [{'OK  ' if ok else 'FAIL'}] {fname:28} attendu={want}  obtenu={got}  ({shown})")

    if not fast:
        print("\n== 2. Execution des moteurs")
        try:        # Node.js / Luau patche : fournis automatiquement (sinon les moteurs concernes seraient SKIP)
            import bootstrap
            bootstrap.ensure_ready(log=lambda m: print("  [prepa] " + m))
        except Exception as exc:  # noqa: BLE001
            print(f"  [prepa] preparation automatique impossible : {exc}")
        for fname, want, needle, run, timeout in CASES:
            if not run or want is None or (only and only != want):
                continue
            path = SAMPLES / fname
            eng = by_name.get(want)
            if eng is None or not path.exists():
                print(f"  [SKIP] {want:16} non installe / echantillon absent")
                continue
            miss = eng.missing_requirements()
            if miss:
                print(f"  [SKIP] {want:16} prerequis manquants : {', '.join(miss)}")
                continue
            with tempfile.TemporaryDirectory(prefix="selftest_") as tmp:
                dst = Path(tmp) / "out.lua"
                t0 = time.monotonic()
                res = R.run_engine(eng, path, dst, timeout)
                dt = time.monotonic() - t0
                text = dst.read_text("utf-8", "replace") if dst.exists() else ""
            good = res["ok"] and (needle is None or needle in text)
            fails += 0 if good else 1
            print(f"  [{'OK  ' if good else 'FAIL'}] {want:16} {res['out_bytes']:>8} octets  {dt:5.0f}s"
                  + ("" if good else f"\n         {res.get('log', '')[-400:]!r}"))

    print("\n== 3. Garde-fou proprietaire (commandes slash)")
    try:
        import discord  # noqa: F401
    except ImportError:
        print("  [SKIP] discord.py non installe (pip install discord.py aiohttp yarl)")
    else:
        r = subprocess.run([sys.executable, "-I", str(HERE / "tests" / "test_owner_guard.py")],
                           capture_output=True, text=True)
        print("  " + "\n  ".join(r.stdout.strip().splitlines()[-4:]))
        if r.returncode != 0:
            fails += 1
            print(r.stderr[-500:])

    print(f"\n{'AUTOTEST OK' if fails == 0 else f'AUTOTEST : {fails} ECHEC(S)'}")
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
