'use strict';
const fs = require('fs');
const { parseObfuscated: pO, extractSalts: eSa } = require('./utils/parse');
const { hashPayload: hP, xorDec: xD, lzwDec: lD, deser: ds } = require('./utils/unpack');
const { buildRawMap: bR, BINARY_NAMES: bN, UNARY_NAMES: uN, EXPR_NAMES: eN, STMT_NAMES: sN } = require('./utils/opcodes');
const { decodeIR: dI } = require('./utils/decode');
const { Gen: G } = require('./utils/ir2lua');
function aC(f, k, hS, eH) {
  const n = f.length;
  if (n === 0) throw new Error();
  if (n === 1) return f[0];
  const sq = f.join('');
  const sd = dB(sq, k);
  if (sd) return sq;
  if (n <= 8) {
    const pr = [...Array(n).keys()];
    for (const x of pm(pr)) {
      const c = x.map(i => f[i]).join('');
      const d = dB(c, k);
      if (d) {
        if ((hP(d, hS) >>> 0) === (eH >>> 0)) return c;
      }
    }
  }
  return sq;
}
function dB(b, k) {
  try { return lD(xD(Buffer.from(b, 'base64'), k)); } catch { return null; }
}
function* pm(a) {
  if (a.length <= 1) { yield a; return; }
  for (let i = 0; i < a.length; i++) {
    const r = a.filter((_, j) => j !== i);
    for (const x of pm(r)) yield [a[i], ...x];
  }
}
function mS(d, db, df) {
  return {
    lval: d[0] || 0, field: d[1] || 0, expr: d[2] || 0, stmt: d[3] || 0,
    binary: db[0] || 0, unary: db[1] || 0,
    defBinary: df[0] || 0, defUnary: df[1] || 0, defExpr: df[2] || 0, defStmt: df[3] || 0,
  };
}
function vS(s, d, bs, es, ss) {
  try {
    const bm = bR(bs, d, s.defBinary, bN);
    const em = bR(es, d, s.defExpr, eN);
    const sm = bR(ss, d, s.defStmt, sN);
    return [...bm.values()].every(n => bN.includes(n)) &&
           [...em.values()].every(n => eN.includes(n)) &&
           [...sm.values()].every(n => sN.includes(n)) &&
           bm.size > 0 && em.size > 0 && sm.size > 0;
  } catch { return false; }
}
function rDS(d, db, df, ds, bs, us, es, ss) {
  const nt = mS(d, db, df);
  if (vS(nt, ds, bs, es, ss)) return nt;
  for (const dp of pm([...Array(Math.min(df.length, 4)).keys()])) {
    const s = mS(d, db, dp.map(i => df[i]));
    if (vS(s, ds, bs, es, ss)) return s;
  }
  return nt;
}
function de(s) {
  const { frags: fg, payloadKey: pk, payloadHashSeed: phs, payloadHash: ph } = pO(s);
  const si = eSa(s);
  const b = aC(fg, pk, phs, ph);
  const rw = Buffer.from(b, 'base64');
  const dc = xD(rw, pk);
  const tx = lD(dc);
  if ((hP(tx, phs) >>> 0) !== (ph >>> 0)) throw new Error();
  const pl = ds(tx);
  const [, en, rf, m] = pl;
  const [oS, dS, bS, uS, eS, sS] = m;
  const sl = rDS(si.dec, si.decB, si.def, dS, bS, uS, eS, sS);
  let ac, oc;
  const rx = new RegExp(`\\((\\d+),[a-zA-Z_]\\w*,${sl.binary}\\),.*?\\(((\\d+),[a-zA-Z_]\\w*,${sl.binary})\\)`);
  const mt = s.match(rx);
  if (mt) { ac = parseInt(mt[1]); oc = parseInt(mt[3]); }
  const bm = bR(bS, dS, sl.defBinary, bN);
  if (ac !== undefined) bm.set(ac, 'and');
  if (oc !== undefined) bm.set(oc, 'or');
  const rm = {
    binary: bm, unary: bR(uS, dS, sl.defUnary, uN),
    expr: bR(eS, dS, sl.defExpr, eN), stmt: bR(sS, dS, sl.defStmt, sN),
    lval: new Map(), field: new Map(),
  };
  let ir;
  try {
    ir = dI(pl, sl, rm);
    const is = JSON.stringify(ir);
    if (is.includes('"bin_') || is.includes('"un_')) throw new Error();
  } catch {
    const t = sl.binary; sl.binary = sl.unary; sl.unary = t;
    rm.lval = new Map(); rm.field = new Map();
    ir = dI(pl, sl, rm);
  }
  const { names: nm, strings: st } = eP(s);
  function tB(stms) {
    if (!stms) return stms;
    if (typeof stms[0] === 'string') {
      if (stms[0] === 'if' && stms[1] && stms[1].length === 1 && (!stms[2] || stms[2].length === 0)) {
        const c = stms[1][0][0];
        if (c && ((c[0] === 'bool' && c[1] !== 1) || (c[0] === 'mini' && c[1] && c[1].length === 1 && c[1][0][0] === 4 && c[1][0][1] !== 1))) return [];
      }
      tS(stms); return stms;
    }
    if (Array.isArray(stms)) {
      for (let i = 0; i < stms.length; i++) {
        let x = stms[i];
        if (!x) continue;
        if (x[0] === 'if' && x[1] && x[1].length === 1 && (!x[2] || x[2].length === 0)) {
          const c = x[1][0][0];
          if (c && ((c[0] === 'bool' && c[1] !== 1) || (c[0] === 'mini' && c[1] && c[1].length === 1 && c[1][0][0] === 4 && c[1][0][1] !== 1))) {
            stms.splice(i, 1); i--; continue;
          }
        }
        stms[i] = tS(x);
      }
      return stms;
    }
    return stms;
  }
  function tS(x) {
    if (!x || typeof x[0] !== 'string') return x;
    if (x[0] === 'if') {
      if (x[1]) x[1].forEach(c => { c[1] = tB(c[1]); });
      if (x[2]) x[2] = tB(x[2]);
    } else if (['while', 'repeat', 'fornum', 'forin', 'do'].includes(x[0])) {
      const idx = x[0] === 'while' ? 2 : x[0] === 'repeat' ? 1 : x[0] === 'fornum' ? 5 : x[0] === 'forin' ? 3 : 1;
      if(x[idx]) x[idx] = tB(x[idx]);
    }
    return x;
  }
  if (ir && ir.fns) ir.fns.forEach(fn => { if (fn && fn.body) fn.body = tB(fn.body); });
  const g = new G(nm, st);
  return g.pr({ entry: en, fns: ir.fns, names: nm, strings: st });
}
function eP(s) {
  const xD = (e, k) => {
    const b = Buffer.alloc(e.length);
    for (let i = 0; i < e.length; i++) b[i] = (e.charCodeAt(i) ^ ((k + i + 1) & 0xff)) & 0xff;
    return b.toString('utf8');
  };
  const pS = (x) => x.replace(/\\(\d{1,3})|\\n|\\r|\\t|\\"|\\\\|\\0/g, (m, d) => {
    if (d !== undefined) return String.fromCharCode(parseInt(d));
    if (m === '\\n') return '\n'; if (m === '\\r') return '\r'; if (m === '\\t') return '\t';
    if (m === '\\"') return '"'; if (m === '\\\\') return '\\'; if (m === '\\0') return '\0'; return m;
  });
  const pSE = (e) => {
    const p = [], r = /"((?:[^"\\]|\\.)*)"/g; let m;
    while ((m = r.exec(e)) !== null) p.push(pS(m[1]));
    return p.join('');
  };
  const dPB = (b, pf) => {
    const r = [], rx = /([a-zA-Z0-9_]+)\[\{((?:"(?:[^"\\]|\\.)*"\s*(?:\.\.\s*"(?:[^"\\]|\\.)*"\s*)*)),\s*(\d+)\s*\}\]/g; let m;
    while ((m = rx.exec(b)) !== null) if (m[1] === pf) r.push(xD(pSE(m[2]), parseInt(m[3])));
    return r;
  };
  const l = s.split('\n')[3] || s, w8 = l.indexOf('W[8]={'), w9 = l.indexOf('W[9]={');
  let rs = [], n = [];
  if (w8 > -1) {
    const e = w9 > w8 ? w9 : w8 + 8000, b = l.substring(w8, e), m = b.match(/W\[8\]=\{(\w+)\[/);
    rs = dPB(b, m ? m[1] : 'f80');
  }
  if (w9 > -1) {
    const b = l.substring(w9, w9 + 20000), m = b.match(/W\[9\]=\{(\w+)\[/);
    n = dPB(b, m ? m[1] : 'g80');
  }
  if (rs.length === 0 && n.length === 0) {
    const pm = new Map(), r = /([a-zA-Z0-9_]+)\[\{\s*((?:"(?:[^"\\]|\\.)*"\s*(?:\.\.\s*"(?:[^"\\]|\\.)*"\s*)*))\s*,\s*(\d+)\s*\}\]/g; let m;
    while ((m = r.exec(s)) !== null) {
      if (!pm.has(m[1])) pm.set(m[1], []);
      pm.get(m[1]).push(xD(pSE(m[2]), parseInt(m[3])));
    }
    const k = Array.from(pm.keys());
    rs = pm.get(k[0]) || []; n = pm.get(k[1]) || [];
  }
  let w10 = 1, w11 = 0;
  const m10_new = l.match(/\[10\]=\(\(function\(\)return\s+(\d+)\s+end\)\(\)-(\d+)\)/);
  const m10_new2 = l.match(/\[10\]=\(\((\d+)\)-\((\d+)\)\)/);
  const m10_old = l.match(/W\[10\]=\(\(\(\(\((\d+)\)\+(\d+)\)-\2\)\/(\d+)\)\)/);
  if (m10_new) w10 = parseInt(m10_new[1]) - parseInt(m10_new[2]);
  else if (m10_new2) w10 = parseInt(m10_new2[1]) - parseInt(m10_new2[2]);
  else if (m10_old) w10 = Math.floor(parseInt(m10_old[1]) / parseInt(m10_old[3]));

  const m11_new = l.match(/\[11\]=\(\(function\(\)return\s+(\d+)\s+end\)\(\)-(\d+)\)/);
  const m11_new2 = l.match(/\[11\]=\(\((\d+)\)-\((\d+)\)\)/);
  const m11_old = l.match(/W\[11\]=\(\(\(\(\((\d+)\)\+(\d+)\)-\2\)\/(\d+)\)\)/);
  if (m11_new) w11 = parseInt(m11_new[1]) - parseInt(m11_new[2]);
  else if (m11_new2) w11 = parseInt(m11_new2[1]) - parseInt(m11_new2[2]);
  else if (m11_old) w11 = Math.floor(parseInt(m11_old[1]) / parseInt(m11_old[3]));
  let st;
  const ps = rs.length;
  if (ps > 0 && (w10 !== 1 || w11 !== 0)) {
    const mr = ps * 3; st = new Array(mr);
    for (let a = 1; a <= mr; a++) st[a - 1] = rs[((a - 1) * w10 + w11) % ps];
  } else st = rs;
  return { names: n, strings: st };
}
const bt = require('./Beautiful/beautifier.js');
function dF(i, o) {
  const s = fs.readFileSync(i, 'utf8'); let r = de(s);
  try { r = bt.Beautify(r, { RenameVariables: false, RenameGlobals: false }); } catch {}
  r = `-- deobfuscated by LeakD discord.gg/qteAQmfJmP\n\n` + r.trimStart();
  if (o) fs.writeFileSync(o, r, 'utf8');
  return r;
}
module.exports = { deobfuscate: de, deobfuscateFile: dF };
if (require.main === module) {
  const [,, i, o] = process.argv;
  if (!i) {
    console.error('\x1b[31m[!] Missing input file path.\x1b[0m');
    process.exit(1);
  }
  try {
    console.error('\x1b[1;35mdeobfuscator made by LeakD discord.gg/qteAQmfJmP\x1b[0m');
    const start = Date.now();
    const r = dF(i, o);
    const elapsed = Date.now() - start;
    console.error(`\x1b[1;32m[+] Successfully deobfuscated in \x1b[1;33m${elapsed}ms\x1b[0m`);
    if (o) {
      console.log(`\x1b[1;36m[+] Output saved to: \x1b[1;37m${require('path').resolve(o)}\x1b[0m`);
    } else {
      console.log(r);
    }
  } catch (e) {
    console.error('\x1b[31m[!] Deobfuscation failed:\x1b[0m', e);
    process.exit(1);
  }
}
