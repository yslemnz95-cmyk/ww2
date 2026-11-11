#!/usr/bin/env python3
"""Moteur legaxyobf : python3 run.py entree.lua sortie.lua   (0 ok, 1 echec, 2 entree invalide)."""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from legaxy import decrypt, lua_unescape   # noqa: E402
from rbxo import constants, parse          # noqa: E402
from lift import lift                      # noqa: E402


def say(msg):
    print(f"[engine:legaxyobf] {msg}", file=sys.stderr, flush=True)


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    if not src.is_file() or src.stat().st_size > 16 * 1024 * 1024:
        say("fail: entree invalide")
        return 2
    text = src.read_text("latin-1")
    m = re.search(r'local _z\d+_\w+ = "((?:[^"\\]|\\.)*)"\n', text, re.S)
    km = re.search(r'local _z\d+_\w+ = \{(\d+(?:,\d+){31})\}', text)
    if not m or not km:
        say("fail: enveloppe RBXE ou cle de 32 octets introuvable")
        return 1
    try:
        pt, ok = decrypt(lua_unescape(m.group(1)), bytes(int(x) for x in km.group(1).split(",")))
        if not ok:
            say("avertissement: etiquette Poly1305 invalide (cle ou enveloppe alteree) -- lecture tentee quand meme")
        c = parse(pt)
        body, notes, k_info = [], [], []
        for gi, p in enumerate(c["protos"]):
            code, nt = lift(c, p)
            body.append(code if len(c["protos"]) == 1 else f"-- proto {gi}\n{code}")
            notes += nt
    except Exception as exc:  # noqa: BLE001
        say(f"fail: {type(exc).__name__}: {exc}")
        return 1
    head = ["-- protected by legaxyobf  --  deobfuscated",
            f"-- Enveloppe RBXE (ChaCha20-Poly1305, etiquette {'valide' if ok else 'INVALIDE'}, cle dans le fichier) -> conteneur RBXO ({len(c['protos'])} proto, VM a opcodes).",
            "-- Le script n'a pas ete execute : dechiffre et releve statiquement."]
    head += [f"-- {n}" for n in notes]
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text("\n".join(head) + "\n" + "\n\n".join(body) + "\n", "utf-8")
    say(f"ok: {dst.stat().st_size} octets, {len(notes)} bloc(s) mort(s) retire(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
