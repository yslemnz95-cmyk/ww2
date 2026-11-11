#!/usr/bin/env python3
"""
Moteur `luauforge` : defait les couches STATIQUES de l'obfuscateur LuauForge (https://luauforge-obf.netlify.app) sans
jamais executer le script. Couches reconnues (chacune reproduit exactement le decodeur Lua qui l'accompagne) :

  1. « blanc » : `local __k=#('NOM')`, `local __w1=[[W<espaces/tabulations/VT/FF>]]` ... : 4 caracteres blancs = 1 octet
     (base 4), puis chaque octet est decale de -len(NOM) modulo 256, puis `loadstring(...)` ;
  2. « dictionnaire » : `local __d={"function","local",...}` + `local __s=[=[ ... \\1@ ... ]=]` : chaque marqueur
     `\\x01` + chr(64+i) est remplace par l'entree i, de la derniere a la premiere ;

Les couches se suivent tant qu'une est reconnue. Ce qui reste est le code de la couche suivante : souvent une machine
virtuelle (aucun devirtualiseur). Dans ce cas elle est EXECUTEE dans le bac a sable Luau du bac a sable (engines/sandbox) (sans reseau,
HttpGet/loadstring/Instance... journalises) et le fichier livre est le PROGRAMME REEL qu'elle a revele (ce que fait le script
sur un chemin d'execution). Les variables globales a nom aleatoire que la machine utilise comme zone de stockage valent `nil`
dans ce bac a sable (comme dans un vrai etat Roblox). Sans Node.js / Luau, ou si l'execution echoue, la couche restante
est livree telle quelle avec une note.

    python3 run.py <entree.lua> <sortie.lua>
Codes de sortie : 0 ok, 1 echec / rien reconnu, 2 entree invalide.
"""
import hashlib
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

MAX_INPUT = int(os.environ.get("ENGINE_MAX_INPUT", 16 * 1024 * 1024))
MAX_LAYERS = 8
HERE = os.path.dirname(os.path.abspath(__file__))


def say(ok, msg, t0):
    print("[engine:luauforge] %s %s (%.1fs)" % ("ok" if ok else "fail", msg, time.time() - t0), file=sys.stderr)


def peel_blank(data: bytes):
    """Couche « blanc ». -> (octets, description) ou None."""
    mk = re.search(rb"local\s+__k\s*=\s*#\s*\(\s*(['\"])(.*?)\1\s*\)", data)
    if not mk:
        return None
    k = len(mk.group(2))
    dec = re.search(rb"local\s+function\s+__dec\s*\(\s*w\s*\)(.*?)\nlocal\s+__raw", data, re.S)
    body = dec.group(1) if dec else b""
    # table de correspondance « (c==32 and 0) or (c==9 and 1) ... » et taille des groupes « if n==4 then »
    pairs = re.findall(rb"c\s*==\s*(\d+)\s+and\s+(\d+)", body)
    mapping = {int(a): int(b) for a, b in pairs} or {32: 0, 9: 1, 11: 2, 12: 3}
    group = int((re.search(rb"if\s+n\s*==\s*(\d+)\s+then", body) or [0, b"4"])[1])
    start = int((re.search(rb"for\s+i\s*=\s*(\d+)\s*,\s*#w", body) or [0, b"2"])[1])
    base = len(mapping)
    if base < 2 or base & (base - 1) or group * int(math.log2(base)) != 8:
        return None                                   # variante inconnue : on ne devine pas
    blocks = re.findall(rb"local\s+__w(\d+)\s*=\s*\[(=*)\[(.*?)\]\2\]", data, re.S)
    if not blocks:
        return None
    raw = bytearray()
    for _, _, chunk in sorted(blocks, key=lambda b: int(b[0])):
        v = n = 0
        for c in chunk[start - 1:]:
            d = mapping.get(c)
            if d is None:
                continue
            v = v * base + d
            n += 1
            if n == group:
                raw.append(v)
                v = n = 0
    out = bytes((b - k) % 256 for b in raw)
    if not out.strip():                               # rien de decode (entree tronquee) : ce n'est pas un resultat
        return None
    return out, f"espaces/tabulations ({len(blocks)} bloc(s), decalage -{k})"


def peel_dict(data: bytes):
    """Couche « dictionnaire de mots ». -> (octets, description) ou None."""
    text = data.decode("latin-1")
    m = re.match(r"\s*local\s+__d\s*=\s*\{(.*?)\}\s*local\s+__s\s*=\s*\[(=*)\[(.*)\]\2\]\s*"
                 r"for\s+__i\s*=\s*#__d\s*,\s*1\s*,\s*-1\s+do\s+local\s+__p\s*=\s*string\.char\(\s*1\s*,\s*(\d+)\s*\+\s*__i\s*\)",
                 text, re.S)
    if not m:
        return None
    entries = re.findall(r'"((?:[^"\\\n]|\\.)*)"', m.group(1))
    if not entries or len(entries) > 190:
        return None
    base = int(m.group(4))

    def unescape(s: str) -> str:
        return re.sub(r"\\(.)", lambda mm: {"n": "\n", "t": "\t", "r": "\r"}.get(mm.group(1), mm.group(1)), s)
    entries = [unescape(e) for e in entries]
    body = m.group(3)
    for i in range(len(entries), 0, -1):
        body = body.replace("\x01" + chr(base + i), entries[i - 1])
    if "\x01" in body:
        return None                                   # un marqueur sans entree : decodage incomplet
    if not body.strip():
        return None
    return body.encode("latin-1", "replace"), f"dictionnaire de mots ({len(entries)} entrees)"


PEELERS = (peel_blank, peel_dict)


def find_luau_ast():
    for cand in (os.environ.get("LURAPH_LUAU_AST"), os.path.join(HERE, "..", "sandbox", "bin", "luau-ast"),
                 os.path.join(HERE, "..", "..", "runtime", "bin", "linux-x86_64", "luau-ast"), shutil.which("luau-ast")):
        if cand and os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    return None


def parses(code: bytes) -> bool | None:
    ast = find_luau_ast()
    if not ast:
        return None
    with tempfile.TemporaryDirectory(prefix="luauforge_") as td:
        p = os.path.join(td, "layer.luau")
        with open(p, "wb") as f:
            f.write(code)
        try:
            return subprocess.run([ast, p], capture_output=True, timeout=60).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return None


def looks_like_vm(code: bytes) -> bool:
    t = code[:400000].decode("latin-1")
    return bool(re.search(r"newproxy", t) and re.search(r"getfenv|_ENV", t) and t.count("function") > 8
                and len(re.findall(r'"l[^"\\]{3,}"', t)) > 20)


def run_vm_trace(src, work):
    """Execute le script (couches comprises) dans le bac a sable du bac a sable (engines/sandbox) : -> (texte de la trace, note).
    `src` = le fichier d'origine. Echec -> (None, raison)."""
    eng = os.path.join(HERE, "..", "sandbox")
    deob = os.path.join(eng, "deob.js")
    node = shutil.which("node")
    if not node or not os.path.isfile(deob):
        return None, "Node.js ou le bac a sable engines/sandbox est absent"
    if not os.path.isfile(os.path.join(eng, "bin", "luau")):
        return None, "Luau patche absent (python3 bootstrap.py)"
    out = os.path.join(work, "trace.lua")
    timeout = int(os.environ.get("LURAPH_TIMEOUT", "300"))
    budget = int(os.environ.get("LURAPH_BUDGET", "120"))
    env = {k: os.environ[k] for k in ("PATH", "LANG", "LC_ALL") if k in os.environ}
    env["HOME"] = env["TMPDIR"] = work
    cmd = [node, deob, src, "-o", out, "--no-devirt", "--timeout", str(timeout), "--budget", str(budget)]
    try:
        proc = subprocess.Popen(cmd, cwd=eng, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, start_new_session=True)
        try:
            log, _ = proc.communicate(timeout=timeout + 60)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, 9)
            except OSError:
                proc.kill()
            proc.communicate()
            return None, "execution dans le bac a sable trop longue (%d s)" % (timeout + 60)
    except OSError as exc:
        return None, "lancement impossible : %s" % exc
    if not os.path.isfile(out):
        return None, "aucune trace produite : " + (log or b"").decode("utf-8", "replace")[-200:].strip()
    text = open(out, "rb").read().decode("utf-8", "replace")
    status = re.search(r"-- run status: (.*)", text)
    # les retours de pile du bac a sable sont longs et inutiles ici
    kept = [ln for ln in text.splitlines() if not ln.startswith("--   ") or len(ln) < 160]
    return "\n".join(kept).strip() + "\n", (status.group(1).strip() if status else "")


def main(argv):
    t0 = time.time()
    if len(argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    src, dst = argv[1], argv[2]
    if not os.path.isfile(src) or os.path.getsize(src) == 0 or os.path.getsize(src) > MAX_INPUT:
        say(False, "entree invalide (absente, vide ou > %d octets)" % MAX_INPUT, t0)
        return 2
    data = open(src, "rb").read()
    done = []
    for _ in range(MAX_LAYERS):
        for peeler in PEELERS:
            r = peeler(data)
            if r:
                data, desc = r
                ok = parses(data)
                done.append((desc, ok))
                if ok is False:
                    say(False, "la couche « %s » ne donne pas du Luau valide : decodage abandonne" % desc, t0)
                    return 1
                break
        else:
            break
    if not done:
        say(False, "aucune couche LuauForge reconnue", t0)
        return 1
    layers = "-- Couches retirees : " + " -> ".join(f"{i}. {d}" + (" [Luau valide]" if ok else "") for i, (d, ok) in enumerate(done, 1))
    vm = looks_like_vm(data)
    if vm:
        with tempfile.TemporaryDirectory(prefix="luauforge_vm_") as work:
            trace, note = run_vm_trace(src, work)
        sha = hashlib.sha256(data).hexdigest()[:16]
        if trace:
            notes = ["-- Deobfusque par le moteur `luauforge`.", layers,
                     f"-- Il restait une MACHINE VIRTUELLE ({len(data)} octets, sha256 {sha}) : elle a ete EXECUTEE dans le bac a sable",
                     "-- (sans reseau ; HttpGet, loadstring, Instance... sont journalises, aucune requete n'est faite). Ci-dessous : le PROGRAMME",
                     "-- REEL qu'elle a revele = ce que fait le script sur UN chemin d'execution. Les blocs 'Folder' crees puis detruits sont",
                     "-- des leurres de l'obfuscateur. Etat de l'execution : " + (note or "terminee, aucune erreur signalee")]
            body = trace.encode("utf-8", "replace")
            how = "machine virtuelle executee dans le bac a sable"
        else:
            notes = ["-- Deobfusque PARTIELLEMENT par le moteur `luauforge` (statique : le script n'a pas ete execute).", layers,
                     "-- ATTENTION : ce qui reste est une MACHINE VIRTUELLE (interpreteur, table de constantes chiffrees). Elle n'a pas pu",
                     f"-- etre executee dans le bac a sable ({note}). Couche suivante livree telle quelle."]
            body = data.lstrip(b"\n")
            how = "machine virtuelle NON executee (%s)" % note
    else:
        notes = ["-- Deobfusque par le moteur `luauforge` (statique : le script n'a pas ete execute).", layers]
        body = data.lstrip(b"\n")
        how = "statique"
    with open(dst, "wb") as f:
        f.write(("\n".join(notes) + "\n").encode() + body)
    say(True, "%d couche(s) retiree(s) -> %d octets (%s)" % (len(done), len(body), how), t0)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
