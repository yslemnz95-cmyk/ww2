#!/usr/bin/env python3
"""
bootstrap.py -- met la suite en etat de marche TOUT SEUL (aucune installation manuelle).

    python3 bootstrap.py            # prepare tout et affiche l'etat
    python3 bootstrap.py --check    # affiche l'etat sans rien modifier

Ce que ca prepare (une seule fois, idempotent, verrou de fichier) :
  1. Luau PATCHE (luau + luau-ast) : livre dans runtime/bin/linux-x86_64/ (binaires statiques compiles
     depuis le depot officiel luau-lang/luau tag 0.739 + les patchs de engines/sandbox/build_luau.py).
     Copie dans les dossiers des moteurs. Si le binaire livre ne tourne pas sur cette machine (autre
     architecture / systeme), il est RECOMPILE (git + cmake ou g++ requis ; sinon message explicite).
  2. Node.js >= 18 : celui du systeme s'il existe, sinon l'archive OFFICIELLE nodejs.org (version figee,
     SHA-256 fige dans ce fichier, verifie avant extraction) est telechargee dans runtime/node/.

Le routeur (deobf_router.py) appelle ensure_ready() avant chaque job : un premier /deobf peut donc durer
~30 s de plus (telechargement de Node), jamais plus.
"""
from __future__ import annotations

import contextlib
import hashlib
import os
import platform
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Callable, Optional

HERE = Path(__file__).resolve().parent
RUNTIME = HERE / "runtime"
ENGINES = HERE / "engines"
SANDBOX = ENGINES / "sandbox"
SHIPPED_BIN = RUNTIME / "bin" / "linux-x86_64"
BIN_TARGETS = [SANDBOX / "bin", ENGINES / "deobf_py" / "deobf" / "bin", ENGINES / "centurion" / "bin"]

NODE_VERSION = "v22.22.0"
NODE_MIN_MAJOR = 18
# SHA-256 des archives officielles (https://nodejs.org/dist/v22.22.0/SHASUMS256.txt)
NODE_ARCHIVES = {
    ("Linux", "x86_64"):  ("linux-x64",    "tar.xz", "9aa8e9d2298ab68c600bd6fb86a6c13bce11a4eca1ba9b39d79fa021755d7c37"),
    ("Linux", "aarch64"): ("linux-arm64",  "tar.xz", "1bf1eb9ee63ffc4e5d324c0b9b62cf4a289f44332dfef9607cea1a0d9596ba6f"),
    ("Darwin", "x86_64"): ("darwin-x64",   "tar.gz", "5ea50c9d6dea3dfa3abb66b2656f7a4e1c8cef23432b558d45fb538c7b5dedce"),
    ("Darwin", "arm64"):  ("darwin-arm64", "tar.gz", "5ed4db0fcf1eaf84d91ad12462631d73bf4576c1377e192d222e48026a902640"),
}

Log = Callable[[str], None]


class BootstrapError(RuntimeError):
    """Prerequis impossible a fournir automatiquement (message destine a l'utilisateur)."""


def _say(msg: str) -> None:
    print(f"[bootstrap] {msg}", file=sys.stderr, flush=True)


NET_TIMEOUT = int(os.environ.get("DEOBF_NET_TIMEOUT", "30"))        # secondes sans donnee avant d'abandonner un telechargement


@contextlib.contextmanager
def _lock(log: "Log" = None):
    """Un seul bootstrap a la fois (bot + CLI, ou deux jobs). Si un autre processus tient le verrou, on le DIT toutes
    les 5 s au lieu d'attendre en silence (c'etait la cause de jobs « figes » en phase de preparation)."""
    log = log or _say
    RUNTIME.mkdir(parents=True, exist_ok=True)
    f = open(RUNTIME / ".lock", "a+")
    try:
        try:
            import fcntl
            t0 = last = time.monotonic()
            while True:
                try:
                    fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    now = time.monotonic()
                    if now - t0 > 900:
                        raise BootstrapError("un autre processus prepare Node.js / Luau depuis plus de 15 min (verrou "
                                             f"{RUNTIME / '.lock'}) : redemarre le bot ou supprime ce fichier")
                    if now - last >= 5 or now == t0:
                        last = now
                        log(f"attente : un autre processus prepare Node.js / Luau (verrou) depuis {int(now - t0)} s...")
                    time.sleep(1)
        except (ImportError, OSError):
            pass
        yield
    finally:
        f.close()


# ---------------------------------------------------------------- Node.js

def _node_major(exe: str) -> int:
    try:
        out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=20).stdout.strip()
        return int(out.lstrip("v").split(".")[0])
    except Exception:  # noqa: BLE001
        return 0


def local_node() -> Optional[Path]:
    p = RUNTIME / "node" / "bin" / "node"
    return p if p.exists() else None


def node_exe() -> Optional[str]:
    """Chemin d'un Node >= 18 utilisable (systeme d'abord, puis runtime/node), ou None."""
    sysnode = shutil.which("node")
    if sysnode and _node_major(sysnode) >= NODE_MIN_MAJOR:
        return sysnode
    ln = local_node()
    if ln and _node_major(str(ln)) >= NODE_MIN_MAJOR:
        return str(ln)
    return None


def path_prefix() -> str:
    """Dossier a mettre en tete du PATH des moteurs pour qu'ils trouvent `node` (chaine vide si inutile)."""
    exe = node_exe()
    if exe and Path(exe).resolve().parent != Path(shutil.which("node") or "/nonexistent").resolve().parent:
        return str(Path(exe).parent)
    return ""


def ensure_node(log: Log = _say) -> str:
    exe = node_exe()
    if exe:
        return exe
    key = (platform.system(), platform.machine())
    if key not in NODE_ARCHIVES:
        raise BootstrapError(f"Node.js >= {NODE_MIN_MAJOR} introuvable et pas d'archive officielle connue pour {key} : "
                             "installez Node.js (https://nodejs.org) puis relancez.")
    suffix, ext, sha = NODE_ARCHIVES[key]
    name = f"node-{NODE_VERSION}-{suffix}"
    url = f"https://nodejs.org/dist/{NODE_VERSION}/{name}.{ext}"
    with _lock(log):
        exe = node_exe()
        if exe:                         # un autre processus l'a installe pendant l'attente du verrou
            return exe
        log(f"Node.js absent : telechargement de {url} (une seule fois)...")
        tmp = Path(tempfile.mkdtemp(prefix="node_dl_", dir=str(RUNTIME)))
        try:
            arc = tmp / f"{name}.{ext}"
            h = hashlib.sha256()
            try:
                # delai de 30 s par lecture (au lieu de 120) : un reseau coupe echoue vite, avec un message clair
                with urllib.request.urlopen(url, timeout=NET_TIMEOUT) as r, open(arc, "wb") as out:   # noqa: S310 - URL fixe
                    total = int(r.headers.get("Content-Length") or 0)
                    done, last = 0, time.monotonic()
                    for chunk in iter(lambda: r.read(1 << 18), b""):
                        h.update(chunk)
                        out.write(chunk)
                        done += len(chunk)
                        if time.monotonic() - last >= 3:
                            last = time.monotonic()
                            log(f"telechargement de Node.js : {done / 1e6:.0f}" + (f" / {total / 1e6:.0f}" if total else "") + " Mo")
            except Exception as exc:  # noqa: BLE001
                raise BootstrapError(f"telechargement de Node.js impossible apres {NET_TIMEOUT} s sans reponse ({type(exc).__name__}: {exc}). "
                                     f"Cette machine n'a probablement pas acces a nodejs.org : installe Node.js >= {NODE_MIN_MAJOR} sur la "
                                     "machine du bot (ex. Debian/Ubuntu : sudo apt install nodejs, ou https://nodejs.org) "
                                     "ou autorise l'acces a nodejs.org.") from exc
            if h.hexdigest() != sha:
                raise BootstrapError(f"somme SHA-256 de {name}.{ext} inattendue ({h.hexdigest()}) : archive refusee")
            dest = RUNTIME / "node"
            shutil.rmtree(dest, ignore_errors=True)
            (dest / "bin").mkdir(parents=True)
            with tarfile.open(arc) as tf:
                for m in tf.getmembers():
                    rel = m.name.split("/", 1)[1] if "/" in m.name else ""
                    if rel in ("bin/node", "LICENSE") and m.isfile():
                        m.name = rel
                        tf.extract(m, dest)          # noms figes ci-dessus : aucun chemin venant de l'archive
            node = dest / "bin" / "node"
            node.chmod(node.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            if _node_major(str(node)) < NODE_MIN_MAJOR:
                raise BootstrapError("le Node.js telecharge ne s'execute pas sur cette machine")
            log(f"Node.js {NODE_VERSION} installe dans {dest}")
            return str(node)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- .NET 9 (runtime seul, pour MoonSec V3)

DOTNET_VERSION = "9.0.0"
# SHA-512 des archives OFFICIELLES (https://builds.dotnet.microsoft.com/dotnet/checksums/9.0.0-sha.txt)
DOTNET_ARCHIVES = {
    ("Linux", "x86_64"):  ("linux-x64",
                           "5176bd68637646cd36fce7a88f83effe1065fb075e6d4a46b8be3c33d5a8394740577f0ed4f8b4fb13fa69fe83b229eb55ab7f45caac90849bf0392a670ed5af"),
    ("Linux", "aarch64"): ("linux-arm64",
                           "4f9c2dd544af0b8540c16352b9f01f75f828b8e4e084057a300a4dec652fb3d6532906cdd4246399cc13f16b571b17575812ec2f9c297e27bbed678baf4b2fde"),
}
DOTNET_MIN_MAJOR = 9


def local_dotnet() -> Optional[Path]:
    p = RUNTIME / "dotnet" / "dotnet"
    return p if p.exists() else None


def _dotnet_ok(exe: str) -> bool:
    """Vrai si `exe --list-runtimes` annonce un Microsoft.NETCore.App >= 9."""
    try:
        out = subprocess.run([exe, "--list-runtimes"], capture_output=True, text=True, timeout=30,
                             env={**os.environ, "DOTNET_SYSTEM_GLOBALIZATION_INVARIANT": "1",
                                  "DOTNET_CLI_TELEMETRY_OPTOUT": "1"}).stdout
    except Exception:  # noqa: BLE001
        return False
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] == "Microsoft.NETCore.App":
            try:
                if int(parts[1].split(".")[0]) >= DOTNET_MIN_MAJOR:
                    return True
            except ValueError:
                pass
    return False


def dotnet_exe() -> Optional[str]:
    """Chemin d'un `dotnet` avec runtime >= 9 (DOTNET_ROOT, systeme, puis runtime/dotnet), ou None."""
    cands = []
    root = os.environ.get("DOTNET_ROOT")
    if root:
        cands.append(os.path.join(root, "dotnet"))
    cands.append(shutil.which("dotnet"))
    ld = local_dotnet()
    if ld:
        cands.append(str(ld))
    for c in cands:
        if c and os.path.isfile(c) and _dotnet_ok(c):
            return c
    return None


def _safe_tar_members(tf: tarfile.TarFile, dest: Path):
    base = dest.resolve()
    for m in tf.getmembers():
        if not (m.isfile() or m.isdir() or m.issym()):
            continue                                   # pas de peripheriques / liens durs
        target = (dest / m.name).resolve()
        if base != target and base not in target.parents:
            raise BootstrapError(f"archive .NET refusee : chemin suspect {m.name!r}")
        if m.issym():
            link = (target.parent / m.linkname).resolve()
            if base not in link.parents and link != base:
                raise BootstrapError(f"archive .NET refusee : lien suspect {m.name!r}")
        yield m


def ensure_dotnet(log: Log = _say) -> str:
    """Runtime .NET >= 9 pour le moteur MoonSec V3 : celui du systeme s'il existe, sinon l'archive OFFICIELLE
    Microsoft (version figee, SHA-512 fige ici, verifie avant extraction) dans runtime/dotnet/ (~75 Mo, une fois)."""
    exe = dotnet_exe()
    if exe:
        return exe
    key = (platform.system(), platform.machine())
    if key not in DOTNET_ARCHIVES:
        raise BootstrapError(f".NET >= {DOTNET_MIN_MAJOR} introuvable et pas d'archive officielle connue pour {key} : "
                             "installez le runtime .NET 9 (https://dotnet.microsoft.com/download/dotnet/9.0)")
    suffix, sha = DOTNET_ARCHIVES[key]
    name = f"dotnet-runtime-{DOTNET_VERSION}-{suffix}.tar.gz"
    url = f"https://builds.dotnet.microsoft.com/dotnet/Runtime/{DOTNET_VERSION}/{name}"
    with _lock(log):
        exe = dotnet_exe()
        if exe:
            return exe
        log(f"runtime .NET absent : telechargement de {url} (une seule fois)...")
        tmp = Path(tempfile.mkdtemp(prefix="dotnet_dl_", dir=str(RUNTIME)))
        try:
            arc = tmp / name
            h = hashlib.sha512()
            try:
                with urllib.request.urlopen(url, timeout=NET_TIMEOUT) as r, open(arc, "wb") as out:   # noqa: S310 - URL fixe
                    for chunk in iter(lambda: r.read(1 << 18), b""):
                        h.update(chunk)
                        out.write(chunk)
            except Exception as exc:  # noqa: BLE001
                raise BootstrapError(f"telechargement du runtime .NET impossible ({type(exc).__name__}: {exc}). "
                                     "Autorise l'acces a builds.dotnet.microsoft.com ou installe le runtime .NET 9 sur la machine du bot.") from exc
            if h.hexdigest() != sha:
                raise BootstrapError(f"somme SHA-512 de {name} inattendue : archive refusee")
            dest = RUNTIME / "dotnet"
            shutil.rmtree(dest, ignore_errors=True)
            dest.mkdir(parents=True)
            with tarfile.open(arc) as tf:
                tf.extractall(dest, members=list(_safe_tar_members(tf, dest)))   # noqa: S202 - membres verifies ci-dessus
            dn = dest / "dotnet"
            if not dn.exists():
                raise BootstrapError("archive .NET inattendue : binaire `dotnet` absent")
            dn.chmod(dn.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            if not _dotnet_ok(str(dn)):
                raise BootstrapError("le runtime .NET telecharge ne s'execute pas sur cette machine")
            log(f".NET {DOTNET_VERSION} installe dans {dest}")
            return str(dn)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- Luau patche

_LUAU_WHY = ""     # raison du dernier echec du test du binaire (pour le message d'erreur)

LUAU_BLOB = HERE / "luau_blob_linux_x86_64.txt"
LUAU_SHA256 = {
    "luau": "cbf5d549c71875524f279f9bbe13bd7cc3b038f9fffb635a8efce60c2eb7132c",
    "luau-ast": "5832e9130daed2c04f125cc3f99d412f0e4bee66aabb82fe3961ab41ca17c225",
}


def _is_linux_x86_64() -> bool:
    return platform.system() == "Linux" and platform.machine().lower() in ("x86_64", "amd64")


def restore_shipped_from_blob(log: Log = lambda m: None) -> bool:
    """Si runtime/bin/linux-x86_64/luau(-ast) a ete perdu par le deploiement (.gitignore / .dockerignore qui exclut bin/, copie
    qui ne garde que le texte...), les reconstruit depuis luau_blob_linux_x86_64.txt (tar+xz+base64, texte donc jamais filtre),
    en verifiant la somme SHA-256 de chaque binaire. True si les deux binaires sont en place."""
    if not _is_linux_x86_64() or not LUAU_BLOB.is_file():
        return False
    import base64
    import hashlib
    import io
    import lzma
    try:
        txt = "".join(l for l in LUAU_BLOB.read_text().splitlines() if l and not l.startswith("#"))
        raw = lzma.decompress(base64.b64decode(txt))
        SHIPPED_BIN.mkdir(parents=True, exist_ok=True)
        with tarfile.open(fileobj=io.BytesIO(raw)) as tf:
            for name, sha in LUAU_SHA256.items():
                f = tf.extractfile(name)
                data = f.read() if f else b""
                if hashlib.sha256(data).hexdigest() != sha:
                    log(f"restauration de {name} refusee : somme SHA-256 inattendue")
                    return False
                dest = SHIPPED_BIN / name
                dest.write_bytes(data)
                dest.chmod(0o755)
    except Exception as exc:  # noqa: BLE001
        log(f"restauration depuis {LUAU_BLOB.name} impossible ({type(exc).__name__}: {exc})")
        return False
    log(f"Luau patche restaure depuis {LUAU_BLOB.name} dans {SHIPPED_BIN}")
    return True


def _shipped_present() -> bool:
    return (SHIPPED_BIN / "luau").exists() and (SHIPPED_BIN / "luau-ast").exists()


def _make_executable(p: Path) -> None:
    """une extraction de zip (Windows, transfert, certains outils) perd le bit d'execution : le remettre"""
    try:
        mode = p.stat().st_mode
        if not mode & stat.S_IXUSR:
            p.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    except OSError:
        pass


def _luau_works(luau: Path) -> bool:
    global _LUAU_WHY
    if not luau.exists():
        _LUAU_WHY = f"{luau} est absent"
        return False
    _make_executable(luau)
    with tempfile.TemporaryDirectory() as d:
        script = Path(d) / "t.luau"
        script.write_text('print("ok"); local v = vector.create(1,2,3); getmetatable(v).Probe = 1; print(getmetatable(v).Probe)\n')
        try:
            # 90 s : une machine tres limitee en CPU (fraction de coeur) peut mettre longtemps a demarrer un binaire de 4 Mo
            r = subprocess.run([str(luau), str(script)], capture_output=True, text=True, timeout=90)
        except subprocess.TimeoutExpired:
            _LUAU_WHY = f"{luau.name} n'a pas repondu en 90 s (machine saturee ou limitee en CPU)"
            return False
        except PermissionError as exc:
            _LUAU_WHY = f"{luau} non executable ({exc}) : dossier monte en noexec, ou droits insuffisants"
            return False
        except OSError as exc:
            _LUAU_WHY = f"{luau.name} ne peut pas etre lance ({type(exc).__name__}: {exc}) : mauvaise architecture ou bibliotheque systeme manquante"
            return False
        # le patch ("metatable des vecteurs inscriptible") fait afficher « ok » puis « 1 »
        if r.returncode == 0 and r.stdout.split() == ["ok", "1"]:
            _LUAU_WHY = ""
            return True
        if r.returncode < 0:
            _LUAU_WHY = f"{luau.name} a ete tue par le signal {-r.returncode} (memoire insuffisante, ou instruction non geree par ce processeur)"
        else:
            _LUAU_WHY = f"{luau.name} a rendu le code {r.returncode} : {(r.stderr or r.stdout or '').strip()[:150]}"
        return False


def luau_ready() -> bool:
    return _luau_works(SANDBOX / "bin" / "luau") and (SANDBOX / "bin" / "luau-ast").exists()


def _install_bins(src: Path) -> None:
    for t in BIN_TARGETS:
        if not t.parent.exists():
            continue
        t.mkdir(parents=True, exist_ok=True)
        for name in ("luau", "luau-ast"):
            s, d = src / name, t / name
            if not s.exists() or (d.exists() and s.resolve() == d.resolve()):
                continue
            shutil.copy2(s, d)
            d.chmod(d.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def ensure_luau(log: Log = _say) -> None:
    global _LUAU_WHY
    if luau_ready():
        return
    with _lock(log):
        if luau_ready():
            return
        if not _shipped_present():
            restore_shipped_from_blob(log)
        if _shipped_present():
            log("installation du Luau patche livre (runtime/bin)...")
            _make_executable(SHIPPED_BIN / "luau")
            _make_executable(SHIPPED_BIN / "luau-ast")
            _install_bins(SHIPPED_BIN)      # copie + bit d'execution, meme si l'extraction l'avait perdu
            if luau_ready():
                return
            _luau_works(SHIPPED_BIN / "luau")   # renseigne _LUAU_WHY
        # binaire livre inutilisable ici (autre architecture / systeme) : compilation
        script = SANDBOX / "build_luau.py"
        missing = [t for t in ("git",) if not shutil.which(t)] + ([] if (shutil.which("cmake") or shutil.which("g++")) else ["cmake ou g++"])
        if missing or not script.exists():
            if not _shipped_present():
                _LUAU_WHY = (f"{SHIPPED_BIN / 'luau'} est absent" + ("" if LUAU_BLOB.is_file() else f" et {LUAU_BLOB.name} aussi")
                             + " : le deploiement a perdu des fichiers (verifier .gitignore / .dockerignore : ne pas exclure bin/ ni les .txt ; "
                             "recopier toute la suite)")
            raise BootstrapError(
                "le Luau patche livre ne tourne pas sur cette machine (" + platform.machine() + ")"
                + (" : " + _LUAU_WHY if _LUAU_WHY else "") + " ; et il manque, pour le recompiler : "
                + (", ".join(missing) or "build_luau.py") + ". Debian/Ubuntu : sudo apt install git cmake g++ make")
        log("le Luau livre ne tourne pas ici : compilation du Luau patche (5 a 10 min, une seule fois)...")
        r = subprocess.run([sys.executable, str(script), "--portable"], cwd=str(SANDBOX))
        if r.returncode != 0 or not luau_ready():
            raise BootstrapError("la compilation du Luau patche a echoue (voir la sortie ci-dessus)")
        # garder une copie pour les autres moteurs
        _install_bins(SANDBOX / "bin")


def ensure_ready(log: Log = _say, need_node: bool = True, need_luau: bool = True) -> dict:
    """Prepare ce qui manque ; leve BootstrapError (message lisible) sinon. Retourne l'etat.
    Toute erreur inattendue (dossier en lecture seule, disque plein, archive corrompue...) est convertie en
    BootstrapError : l'appelant n'a jamais a gerer autre chose."""
    state = {}
    try:
        if need_node:
            state["node"] = ensure_node(log)
        if need_luau:
            ensure_luau(log)
            state["luau"] = str(SANDBOX / "bin" / "luau")
    except BootstrapError:
        raise
    except PermissionError as exc:
        raise BootstrapError(f"dossier de la suite non inscriptible ({exc}) : donnez au bot le droit d'ecrire dans "
                             f"{HERE} (runtime/ et engines/*/bin/)") from exc
    except OSError as exc:
        raise BootstrapError(f"erreur systeme pendant la preparation ({type(exc).__name__}: {exc}) -- disque plein ?") from exc
    except (tarfile.TarError, subprocess.SubprocessError) as exc:
        raise BootstrapError(f"preparation impossible ({type(exc).__name__}: {exc})") from exc
    return state


def preflight() -> dict:
    """Ce qu'il faudrait faire pour que les moteurs tournent, SANS rien faire :
    {"ready": bool, "steps": [textes], "blocker": texte ou None, "slow": bool (compilation = plusieurs minutes)}.
    Sert a prevenir tout de suite l'utilisateur au lieu de le laisser attendre."""
    steps: list[str] = []
    blocker = None
    slow = False
    if node_exe() is None:
        key = (platform.system(), platform.machine())
        if key in NODE_ARCHIVES:
            steps.append("telechargement de Node.js (~30 Mo, une seule fois)")
        else:
            blocker = (f"Node.js >= {NODE_MIN_MAJOR} est absent et il n'y a pas d'archive officielle pour {key[0]} {key[1]} : "
                       "installez Node.js (https://nodejs.org) sur la machine du bot")
    if not luau_ready():
        if not _shipped_present() and _is_linux_x86_64() and LUAU_BLOB.is_file():
            steps.append("restauration du Luau patche depuis " + LUAU_BLOB.name)
        elif _luau_works(SHIPPED_BIN / "luau") and (SHIPPED_BIN / "luau-ast").exists():
            steps.append("installation du Luau patche livre")
        elif not (SANDBOX / "build_luau.py").exists():
            blocker = blocker or "build_luau.py absent"
        elif not shutil.which("git") or not (shutil.which("cmake") or shutil.which("g++")):
            blocker = blocker or (f"le Luau livre ne tourne pas sur {platform.system()} {platform.machine()}"
                                  + (f" ({_LUAU_WHY})" if _LUAU_WHY else "") + " et il manque "
                                  "git + cmake (ou g++) pour le recompiler (Debian/Ubuntu : sudo apt install git cmake g++ make)")
        else:
            steps.append("compilation du Luau patche (10 a 60 min selon la machine, une seule fois)")
            slow = True
    return {"ready": not steps and blocker is None, "steps": steps, "blocker": blocker, "slow": slow}


def status() -> dict:
    return {"dotnet": dotnet_exe(), "node": node_exe(), "node_local": str(local_node()) if local_node() else None,
            "luau_ready": luau_ready(), "platform": f"{platform.system()} {platform.machine()}",
            "python": platform.python_version()}


def main(argv: list[str]) -> int:
    if "--check" in argv:
        for k, v in status().items():
            print(f"  {k:12} {v}")
        return 0
    try:
        ensure_ready()
    except BootstrapError as exc:
        print(f"ECHEC : {exc}", file=sys.stderr)
        return 1
    for k, v in status().items():
        print(f"  {k:12} {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
