"""Compare le comportement : VM IronBrew2 originale vs bytecode leve, avec le MEME environnement espion (ENV).
Le journal LOG (acces globaux, appels, arguments) est compare ; la premiere divergence est affichee."""
import sys
import re as _re
from lupa import lua51 as L

PRELUDE = r'''
LOG = {}
local real_pcall = pcall
local function rec(s) LOG[#LOG+1] = s end
local function show(v)
  if type(v) == "table" then return "<table>" end
  if type(v) == "function" then return "<fn>" end
  return tostring(v)
end
local proxy
ENV = setmetatable({}, {__index = function(_, k)
  rec("G " .. tostring(k))
  if (SCEN or 0) >= 8 then return proxy(tostring(k)) end   -- mode permissif : tout global inconnu est un proxy
  return nil
end, __newindex = function(t, k, v) rec("SG " .. tostring(k)) rawset(t, k, v) end})
local function fn(name, ret)
  return function(...)
    local parts = {}
    for i = 1, select("#", ...) do parts[#parts+1] = show((select(i, ...))) end
    rec("C " .. name .. "(" .. table.concat(parts, ",") .. ")")
    return ret
  end
end
local function obj(name, t)
  return setmetatable(t, {__index = function(_, k) rec("I " .. name .. "." .. tostring(k)) return rawget(t, k) end})
end
CBS = {}
local function track(v)
  if type(v) == "function" then CBS[#CBS+1] = v
  elseif type(v) == "table" then for _, x in pairs(v) do if type(x) == "function" then CBS[#CBS+1] = x end end end
end
proxy = function(name)
  local p = {}
  return setmetatable(p, {
    __index = function(_, k) rec("I " .. name .. "." .. tostring(k)) return proxy(name .. "." .. tostring(k)) end,
    __call = function(self, ...)
      local parts = {}
      for i = 1, select("#", ...) do parts[#parts+1] = show((select(i, ...))) track((select(i, ...))) end
      rec("C " .. name .. "(" .. table.concat(parts, ",") .. ")")
      return proxy(name .. "()")
    end,
    __newindex = function(_, k, v) rec("S " .. name .. "." .. tostring(k)) track(v) end,
    __tostring = function() return name end,
  })
end
local game = proxy("game")
game.HttpGet = function(self, u) rec("C game:HttpGet(" .. tostring(u) .. ")") return "return function() end" end
game.GetService = function(self, n) rec("C game:GetService(" .. tostring(n) .. ")") return proxy("svc_" .. tostring(n)) end
ENV.game = game
ENV.loadstring = function(s, ...) rec("C loadstring(" .. show(s) .. ")") return function(...) rec("C <chunk>()") return proxy("lib") end end
ENV.pcall = function(f, ...) rec("C pcall") local r = {real_pcall(f, ...)} rec("R " .. tostring(r[1]) .. " " .. tostring(r[2])) return unpack(r) end
ENV.warn = fn("warn", nil)
ENV.error = function(m) rec("C error(" .. tostring(m) .. ")") error("stuberr", 0) end
ENV.print = fn("print", nil)
ENV.string = {format = function(f, ...) rec("C string.format(" .. tostring(f) .. ")") return "x" end}
local function http(name, code)
  return function(t) rec("C " .. name) return {StatusCode = code, Body = "1.2.3.4", StatusMessage = "msg"} end
end
local sc = SCEN or 0
if sc % 2 == 1 then ENV.syn = {request = http("syn.request", 200)} end
if math.floor(sc / 2) % 2 == 1 then ENV.http_request = http("http_request", 200) end
if math.floor(sc / 4) % 2 == 1 then ENV.request = http("request", 500) end
ENV.tostring = tostring
ENV.tonumber = tonumber
ENV.select = select
ENV.unpack = unpack
ENV.table = table
ENV.type = type
ENV.getfenv = function() return ENV end
ENV.setmetatable = setmetatable
ENV.pairs = pairs
ENV.ipairs = ipairs
ENV.assert = assert
ENV.rawget = rawget
ENV.math = math
function RUNCB()
  local i = 1
  while i <= #CBS and i <= 60 do
    local f = CBS[i]
    local r = {real_pcall(f, proxy("arg1"), proxy("arg2"))}
    rec("CB" .. i .. " " .. tostring(r[1]) .. " " .. tostring(r[2]))
    i = i + 1
  end
end
'''

TAIL = "return I(B(),{},s())();"

import re as _re
def _first(e):
    if e is None: return None
    t = _re.sub(r"^(\[string [^\]]*\]|\?):\d+: ", "", e.splitlines()[0])
    # le nom de variable des messages d'erreur vient des infos de debug (absentes du bytecode leve) : on le neutralise
    t = _re.sub(r"(attempt to [\w ]+?) (?:(?:field|upvalue|local|global|method|constant) )?'[^']*' \((a \w+ value)\)", r"\1 \2", t)
    return _re.sub(r"(attempt to [\w ]+?) \((a \w+ value)\)", r"\1 \2", t)

def run_callbacks(lua):
    lua.execute('RUNCB()')

def log_of(lua):
    t = lua.globals().LOG
    out = []
    for i in range(1, len(t) + 1):
        x = str(t[i])
        if x.startswith("R false "):
            x = "R false " + str(_first(x[len("R false "):]))
        m = _re.match(r"(CB\d+ false )(.*)", x)
        if m:
            x = m.group(1) + str(_first(m.group(2)))
        x = _re.sub(r"(?:\[string \"[^\"]*\"\]|\?):\d+: ", "", x)          # position « fichier:ligne: » des messages d'erreur
        x = _re.sub(r"(attempt to [\w ]+?) (?:(?:field|upvalue|local|global|method|constant) )?'[^']*' \((a \w+ value)\)", r"\1 \2", x)
        x = _re.sub(r"(attempt to [\w ]+?) \((a \w+ value)\)", r"\1 \2", x)
        out.append(x)
    return out

def run_original(path, scen=0):
    lua = L.LuaRuntime(unpack_returned_tuples=True, register_eval=False)
    lua.globals().SCEN = scen
    lua.execute(PRELUDE)
    src = open(path, encoding="latin-1").read()
    m = _re.findall(r"return (\w+)\((\w+)\(\),\{\},(\w+)\(\)\)\(\);?", src)
    if len(m) == 1:
        src = _re.sub(r"return (\w+)\((\w+)\(\),\{\},(\w+)\(\)\)\(\);?", r"return \1(\2(),{},ENV)();", src)   # la VM recoit NOTRE environnement
    else:                                                    # AztupBrew : return F(true,{},G())()
        m2 = _re.findall(r"return (\w+)\(true,\{\},(\w+)\(\)\)\(\);?", src)
        assert len(m2) == 1, "queue d'appel"
        src = _re.sub(r"return (\w+)\(true,\{\},(\w+)\(\)\)\(\);?", r"return \1(true,{},ENV)();", src)
    err = None
    try:
        lua.execute(src)
    except Exception as e:
        err = str(e)[:160]
    run_callbacks(lua)
    return log_of(lua), _first(err)

def run_lifted(path):
    lua = L.LuaRuntime(unpack_returned_tuples=True, register_eval=False)
    lua.execute(PRELUDE)
    data = open(path, "rb").read()
    f = lua.globals().loadstring(data)
    if isinstance(f, str):
        return [], "chargement: " + f[:120]
    lua.execute("local f = ...; setfenv(f, ENV)")  # placeholder, remplace ci-dessous
    return f, None

def run_lifted_env(path, scen=0):
    lua = L.LuaRuntime(unpack_returned_tuples=True, register_eval=False)
    lua.globals().SCEN = scen
    lua.execute(PRELUDE)
    data = open(path, "rb").read()
    lua.globals().__DATA = data
    lua.execute("local f = loadstring(__DATA); assert(f, 'load'); setfenv(f, ENV); __RUN = f")
    err = None
    try:
        lua.globals().__RUN()
    except Exception as e:
        err = str(e)[:160]
    run_callbacks(lua)
    return log_of(lua), _first(err)

if __name__ == "__main__":
    o_log, o_err = run_original(sys.argv[1])
    l_log, l_err = run_lifted_env(sys.argv[2])
    print("ORIGINE :", len(o_log), "evenements; fin:", o_err)
    print("LEVE    :", len(l_log), "evenements; fin:", l_err)
    n = 0
    for i, (a, b) in enumerate(zip(o_log, l_log)):
        if a != b:
            print("PREMIERE DIVERGENCE a l'evenement", i)
            print("  origine :", a)
            print("  leve    :", b)
            break
        n += 1
    else:
        print("identiques sur les", n, "premiers evenements")
    for x in o_log[:12]: print("  O", x)
    for x in l_log[:12]: print("  L", x)

