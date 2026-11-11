#!/usr/bin/env python3
"""luadec_run.py <in.luac> <out.lua> -- decompile du bytecode Lua 5.1 avec decom.lua (LuaDec en Lua pur).

decom.lua est execute dans un interprete Lua 5.1 SANS acces au systeme : `io`/`os`/`package`/`debug` sont remplaces
par un mini-shim (lecture de CE seul bytecode, ecriture en memoire). Interpreteur : lupa (lua51), sinon `lua5.1`
du systeme. Exit : 0 ok | 2 usage | 6 aucun interpreteur Lua 5.1 | 7 echec de decompilation."""
import os, shutil, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
DECOM = os.path.join(HERE, "decom.lua")

SHIM = """
local data, outbuf = __DATA, __OUT
__DATA, __OUT = nil, nil
local real_tostring = tostring
local nop = function() return true end
io = {
  stderr = {write = nop, flush = nop},
  open = function(_, mode)
    if mode == "rb" or mode == "r" then return {read = function() return data end, close = nop, flush = nop} end
    return {write = function(self, s) outbuf[#outbuf + 1] = s; return self end, close = nop, flush = nop, setvbuf = nop}
  end,
}
os = {exit = function(c) error("exit " .. real_tostring(c), 0) end}
package, require, debug, dofile, loadfile, collectgarbage = nil, nil, nil, nil, nil, nil
print = function() end
arg = {"in.luac", "out.lua"}
"""


def via_lupa(data: bytes) -> bytes:
    from lupa import lua51 as L          # ImportError -> l'appelant essaie lua5.1
    lua = L.LuaRuntime(encoding=None, unpack_returned_tuples=True, register_eval=False, register_builtins=False)
    g = lua.globals()
    out = lua.eval("{}")
    g.__DATA, g.__OUT = data, out
    lua.execute(SHIM)
    with open(DECOM, "rb") as f:
        lua.execute(f.read())
    return b"".join(out[i] for i in range(1, len(out) + 1))


def via_binary(src: str, dst: str) -> bytes:
    exe = None
    for c in (os.path.join(HERE, "..", "..", "runtime", "bin", "lua5.1"), shutil.which("lua5.1"), shutil.which("lua")):
        if c and os.path.isfile(c):
            try:
                v = subprocess.run([c, "-v"], capture_output=True, text=True, timeout=10)
                if "5.1" in (v.stdout + v.stderr):
                    exe = c
                    break
            except Exception:  # noqa: BLE001
                pass
    if not exe:
        raise FileNotFoundError("no lua 5.1")
    p = subprocess.run([exe, DECOM, src, dst], capture_output=True, timeout=120, stdin=subprocess.DEVNULL)
    if p.returncode != 0 or not os.path.isfile(dst):
        raise RuntimeError((p.stderr or p.stdout).decode("utf-8", "replace")[-200:])
    with open(dst, "rb") as f:
        return f.read()


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__); return 2
    src, dst = sys.argv[1:3]
    with open(src, "rb") as f:
        data = f.read()
    if data[:4] != b"\x1bLua":
        print("not a Lua bytecode file"); return 7
    text = None
    try:
        text = via_lupa(data)
    except ImportError:
        try:
            text = via_binary(src, dst + ".bin.lua")
        except FileNotFoundError:
            print("aucun interpreteur Lua 5.1 (lupa ou lua5.1)"); return 6
        except Exception as exc:  # noqa: BLE001
            print(f"decompilation failed: {exc}"); return 7
    except Exception as exc:  # noqa: BLE001
        print(f"decompilation failed: {str(exc)[:200]}"); return 7
    if not text or not text.strip():
        print("decompilation produced no output"); return 7
    with open(dst, "wb") as f:
        f.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
