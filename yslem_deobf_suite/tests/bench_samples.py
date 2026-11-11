#!/usr/bin/env python3
"""Banc d'essai : echantillon par famille dans des depots d'echantillons, verdict du bot pour chaque fichier
(usage : SAMPLE_REPOS="sz=/chemin/a,vy=/chemin/b" [PER_FAMILY=10] [OUT=resultats.jsonl] python3 tests/bench_samples.py).
Detection en direct (deobf_router.detect_text) puis `--engine X` ou `--engine trace` : aucun acces reseau."""
import concurrent.futures as cf
import json
import os
import random
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SUITE = Path(os.environ.get("SUITE", str(Path(__file__).resolve().parent.parent)))
sys.path.insert(0, str(SUITE))
import deobf_router as R  # noqa: E402

# SAMPLE_REPOS="tag=chemin,tag2=chemin2" : dossiers contenant UN SOUS-DOSSIER PAR FAMILLE d'obfuscateur (ex. depots GitHub
# SixZensED/luau-obfuscator-samples et vyxonq-dev/obfuscator-samples, clones en lecture seule)
REPOS = {k: Path(v) for k, v in (kv.split("=", 1) for kv in os.environ.get("SAMPLE_REPOS", "").split(",") if "=" in kv)}
if not REPOS:
    sys.exit("definir SAMPLE_REPOS=\"tag=/chemin/depot,...\" (un sous-dossier par famille)")
PER_FAMILY = int(os.environ.get("PER_FAMILY", "10"))
MIN_SIZE, MAX_SIZE = 200, int(os.environ.get("MAX_SIZE", str(400 * 1024)))
OUT = Path(os.environ.get("OUT", "bench_results.jsonl"))
LURAPH_RE = re.compile(r"protected using Luraph Obfuscator|lura\.ph", re.I)
random.seed(7)


def pick():
    jobs = []
    for tag, root in REPOS.items():
        for fam in sorted(p for p in root.iterdir() if p.is_dir() and p.name != ".git"):
            files = [f for f in fam.rglob("*") if f.is_file() and f.suffix in (".lua", ".luau", ".txt") and MIN_SIZE <= f.stat().st_size <= MAX_SIZE]
            by_ver = {}
            for f in files:
                by_ver.setdefault(f.parent.relative_to(fam).as_posix(), []).append(f)
            for v in by_ver.values():
                random.shuffle(v)
            chosen, order = [], sorted(by_ver)
            while len(chosen) < PER_FAMILY and any(by_ver.values()):
                for k in order:
                    if by_ver[k] and len(chosen) < PER_FAMILY:
                        chosen.append(by_ver[k].pop())
            for f in chosen:
                jobs.append((f"{tag}:{fam.name}", f.parent.relative_to(fam).as_posix(), f))
    return jobs


def run_one(job):
    fam, ver, f = job
    rec = {"family": fam, "version": ver, "file": str(f), "size": f.stat().st_size}
    try:
        text = f.read_bytes().decode("latin-1")
        rec["head"] = text[:90].replace("\n", " ")
        d = R.detect_text(text)
        top = d[0] if d else None
        if top and top[1] >= R.MIN_CONFIDENCE:
            rec["detected"] = [top[0], round(top[1], 2)]
            engine = top[0]
        else:
            rec["detected"] = None
            if LURAPH_RE.search(text[:65536]):
                rec["verdict"] = "luraph_non_pris_en_charge"
                return rec
            engine = "trace"
        t0 = time.time()
        with tempfile.TemporaryDirectory(prefix="bench_") as td:
            out = Path(td) / "out.lua"
            tmo = 120 if engine != "trace" else 60
            try:
                p = subprocess.run([sys.executable, "-I", str(SUITE / "deobf_router.py"), "run", str(f), str(out), "--engine", engine, "--json"],
                                   capture_output=True, text=True, timeout=tmo + 30, cwd=td)
                last = (p.stdout.strip().splitlines() or ["{}"])[-1]
                try:
                    res = json.loads(last)
                except Exception:  # noqa: BLE001
                    res = {"ok": False, "log": (p.stdout + p.stderr)[-300:]}
            except subprocess.TimeoutExpired:
                res = {"ok": False, "log": "TIMEOUT"}
            rec["engine"] = engine
            rec["ok"] = bool(res.get("ok"))
            rec["secs"] = round(time.time() - t0, 1)
            rec["log"] = (res.get("log") or "")[-220:].replace("\n", " ")
            if out.exists():
                body = out.read_text("utf-8", "replace")
                rec["out_bytes"] = len(body)
                rec["out_lines"] = body.count("\n")
                m = re.search(r"Statut d'execution dans le bac a sable : (.*)", body)
                rec["status"] = m.group(1).strip() if m else None
                rec["http"] = len(re.findall(r"HttpGet|loadstring|request\(", body))
                rec["devirt_err"] = body.count('error("devirt:')
    except Exception as exc:  # noqa: BLE001
        rec["ok"] = False
        rec["log"] = f"{type(exc).__name__}: {exc}"
    return rec


def main():
    jobs = pick()
    print(f"{len(jobs)} echantillons", flush=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    done = 0
    with OUT.open("w") as fo, cf.ThreadPoolExecutor(int(os.environ.get("WORKERS", "4"))) as ex:
        for rec in ex.map(run_one, jobs):
            fo.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fo.flush()
            done += 1
            if done % 10 == 0:
                print(f"{done}/{len(jobs)}", flush=True)
    print("BENCH_DONE", flush=True)


if __name__ == "__main__":
    main()
