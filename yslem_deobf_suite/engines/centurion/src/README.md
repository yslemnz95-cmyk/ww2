# Centurion v6/v6.1 offline deobfuscator

Input file in, readable source out. No Roblox, no executor needed for the
tool itself. Polymorphic per-build probe suites are answered by frozen
packs (live-verified once, replayed forever).

## Layout (send these two dirs)

- `centurion-deobfuscator/` — this driver (`centurion.py`), frozen packs
  (`*.json`), `samples/` (selftest corpus).
- `sandbox-copy-luraph/` — the fake Roblox/executor runtime (`envlog.luau`
  + `roblox_api.luau`, `datatypes.luau`, `harness.py`). Keep it as a sibling
  of this dir, or point `CENT_SANDBOX` at it.
- Luau binaries (`luau.exe` etc.): auto-found under a nearby `bin/` dir, or
  set `CENT_LUAU_EXE` / `CENT_LUAU_AST` / `CENT_LUAU_COMPILE`.

No hardcoded paths: everything resolves relative to this file, with
`CENT_SAMPLES` / `CENT_SANDBOX` / `CENT_LUAU_*` overrides. Legacy absolute
paths remain only as last-resort fallbacks.

## Commands

- `python centurion.py fingerprint <file>` — family + route.
- `python centurion.py deobfuscate <file> [--out-dir DIR]` — full attempt.
- `python centurion.py deep <file> [--out-dir DIR]` — outcome grid-search.
- `python centurion.py selftest` — fingerprint smoke test (must PASS).
- `python centurion.py live-harness <file>` — protected live-dump builder.
- `python centurion.py probe-batch <trace> [out.lua]` — micro-probe builder.

Per-run knobs (env): `CENT61_GUESS=1`, `CENT61_FIRSTTWO=1|2`,
`CENT61_TOSTRING_SWALLOW=1`, `CENT61_SORTPAIRS=1`, `CENT61_DICTPIN=N`,
`CENT61_TEMPLATE=1`. Prelude supports `setprop(game, 'PlaceId', N)` and
`CFG.hwid` overrides the offline HWID stand-in; `CFG.input_text` prefills
text boxes.

## Frozen packs (live-verified, replayed offline)

- `p2d_errors.json` — Path2D out-of-bounds/cast error texts.
- `callerr_rules.json` — poisoned-call errors as `Method|sig=message`
  (Path2D, GetTextSize, 20 Camera arg-validation shapes).
- `enumprops.json` — enum-typed service props (`CharacterSoundsUseNewApi`,
  `Retargeting`) resolved to real EnumItems.
- `httpresps.json` — frozen HTTP bodies (platoboost connectivity/start,
  whitelist). Pinned to the stub identity; per-user runs re-fetch.

## Sandbox rules (will bite otherwise)

1. The top-level chunk is at Luau's 200-local limit: **no new module-level
   locals** — keep state on `CFG` fields (`CFG._epm`, `CFG._http` pattern).
2. `onCall` is at the 200-register limit: **no additions there** — route
   new behavior through `PMT.__index` branches, `methodFn`, or small
   helpers (each has its own budget). Always recompile-check with
   `luau-compile --only-parse` after editing `envlog.luau`.
3. Never log via `fmt()`/`tok()` on the hot path (it registers expressions
   and perturbs execution). `R.print`/`R.tostring` are safe.

## Trust table (what the sandbox returns)

- Live-verified: Path2D/poisoned-call errors, enum values, services,
  typeof shapes, physics reads (0 awake / 60 FPS baseplate-typical),
  product info (Pilgrammed 6735572261, Cool Rarities 13020029200),
  platoboost bodies, Camera suite texts.
- Stand-ins (documented, overridable): executor name "Potassium", HWID
  `CENTURION-OFFLINE-PROBE-HWID` (`CFG.hwid`), key-file contents, clipboard.
- Known gaps: unexecuted handler bodies stay empty (features off / no
  events offline — use live interaction or synthetic firing), unseeded
  `math.random` is deterministic, infinite loops truncate, `signal:Fire`
  runs handlers (path-parity for input-only runs; engine has no such
  method).
