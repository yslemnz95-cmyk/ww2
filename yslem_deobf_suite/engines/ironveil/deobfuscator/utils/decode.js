'use strict';
const { deriveKey: dK, decodeOpcode: dOp, OP_MASK: oM } = require('./opcodes');
function bM(t, ds, s, n) {
  const m = new Map();
  for (const e of t) m.set(dOp(e[0], e[1][0], ds, s), n[e[1][0] - 1]);
  return m;
}
function dF(f, os, fi, s, rm) {
  const p = Array.isArray(f[0]) ? f[0] : [];
  const rb = Array.isArray(f[1]) ? f[1] : [];
  const v = f[2] === 1;
  const k = dK(os, fi);
  const st = { n: 0, op: 0, pn: 0, po: 0, nh: 0, oh: 0 };
  const b = rb.map(x => dS(x, k, st, s, rm));
  return { params: p, vararg: v, body: b };
}
function nN(st) { st.n += 1; return st.n; }
function nO(st) { st.op += 1; return st.op; }
function dNO(e, k, s, st) {
  const sl = nN(st);
  const rx = dOp(e, sl, k, s);
  const m = cM(st.pn, st.nh, sl, s);
  const r = (rx ^ m) & oM;
  st.pn = r; st.nh = nH(st.nh, r, sl, s);
  return r;
}
function dOO(e, k, s, st) {
  const sl = nO(st);
  const rx = dOp(e, sl, k, s);
  const m = cM(st.po, st.oh, sl, s);
  const r = (rx ^ m) & oM;
  st.po = r; st.oh = nH(st.oh, r, sl, s);
  return r;
}
function cM(p, h, sl, s) { return ((p * 131) + (h * 17) + s + sl) & oM; }
function nH(h, d, sl, s) { return ((h * 257) + d + s + sl) & oM; }
function rS(r, rm) { return rm.stmt.get(r) || `stmt_${r}`; }
function rE(r, rm) { return rm.expr.get(r) || `expr_${r}`; }
function rL(r, rm) { return rm.lval.get(r) || `lval_${r}`; }
function rF(r, rm) { return rm.field.get(r) || `field_${r}`; }
function rB(r, rm) { return rm.binary.get(r) || `bin_${r}`; }
function rU(r, rm) { return rm.unary.get(r) || `un_${r}`; }
function dS(s, k, st, slt, rm) {
  const a = s.slice();
  const rt = dNO(a[0], k, slt.stmt, st);
  const n = rS(rt, rm);
  a[0] = n;
  switch (n) {
    case 'local': a[2] = a[2].map(e => dE(e, k, st, slt, rm)); break;
    case 'assign':
      a[1] = a[1].map(lv => dL(lv, k, st, slt, rm));
      a[2] = a[2].map(e => dE(e, k, st, slt, rm));
      break;
    case 'expr': a[1] = dE(a[1], k, st, slt, rm); break;
    case 'return': a[1] = a[1].map(e => dE(e, k, st, slt, rm)); break;
    case 'if':
      a[1] = a[1].map(([c, b]) => [dE(c, k, st, slt, rm), b.map(x => dS(x, k, st, slt, rm))]);
      if (a[2]) a[2] = a[2].map(x => dS(x, k, st, slt, rm));
      break;
    case 'while':
      a[1] = dE(a[1], k, st, slt, rm);
      a[2] = a[2].map(x => dS(x, k, st, slt, rm));
      break;
    case 'repeat':
      a[1] = a[1].map(x => dS(x, k, st, slt, rm));
      a[2] = dE(a[2], k, st, slt, rm);
      break;
    case 'fornum':
      a[2] = dE(a[2], k, st, slt, rm);
      a[3] = dE(a[3], k, st, slt, rm);
      if (a[4]) a[4] = dE(a[4], k, st, slt, rm);
      a[5] = a[5].map(x => dS(x, k, st, slt, rm));
      break;
    case 'forin':
      a[2] = a[2].map(e => dE(e, k, st, slt, rm));
      a[3] = a[3].map(x => dS(x, k, st, slt, rm));
      break;
    case 'do':
      a[1] = a[1].map(x => dS(x, k, st, slt, rm));
      break;
    case 'func':
      a[2] = dL(a[2], k, st, slt, rm);
      break;
  }
  return a;
}
function dE(e, k, st, slt, rm) {
  if (!e || !Array.isArray(e)) return e;
  const a = e.slice();
  const rt = dNO(a[0], k, slt.expr, st);
  const n = rE(rt, rm);
  a[0] = n;
  switch (n) {
    case 'binary':
      a[1] = rB(dOO(a[1], k, slt.binary, st), rm);
      a[2] = dE(a[2], k, st, slt, rm);
      a[3] = dE(a[3], k, st, slt, rm);
      break;
    case 'unary':
      a[1] = rU(dOO(a[1], k, slt.unary, st), rm);
      a[2] = dE(a[2], k, st, slt, rm);
      break;
    case 'member':
      a[1] = dE(a[1], k, st, slt, rm);
      if (a[3] === 1) a[2] = dE(a[2], k, st, slt, rm);
      break;
    case 'call':
      a[1] = dE(a[1], k, st, slt, rm);
      a[2] = a[2].map(x => dE(x, k, st, slt, rm));
      break;
    case 'table':
      a[1] = a[1].map(f => dFi(f, k, st, slt, rm));
      break;
  }
  return a;
}
function dL(lv, k, st, slt, rm) {
  const a = lv.slice();
  const rt = dNO(a[0], k, slt.lval, st);
  let n = rL(rt, rm);
  if (n.startsWith('lval_')) {
    n = lv.length === 2 ? 'id' : 'member';
    rm.lval.set(rt, n);
  }
  a[0] = n;
  if (a[0] === 'member') {
    a[1] = dE(a[1], k, st, slt, rm);
    if (a[3] === 1) a[2] = dE(a[2], k, st, slt, rm);
  }
  return a;
}
function dFi(f, k, st, slt, rm) {
  const a = f.slice();
  const rt = dNO(a[0], k, slt.field, st);
  let n = rF(rt, rm);
  if (n.startsWith('field_')) {
    if (f.length === 2) n = 'array';
    else if (typeof f[1] === 'number') n = 'record';
    else n = 'general';
    rm.field.set(rt, n);
  }
  a[0] = n;
  if (a[0] === 'array') a[1] = dE(a[1], k, st, slt, rm);
  else if (a[0] === 'record') a[2] = dE(a[2], k, st, slt, rm);
  else { a[1] = dE(a[1], k, st, slt, rm); a[2] = dE(a[2], k, st, slt, rm); }
  return a;
}
function dI(p, s, rm) {
  return { entry: p[1], fns: p[2].map((f, i) => dF(f, p[3][0], i + 1, s, rm)) };
}
module.exports = { decodeIR: dI, buildRawMap: bM, decodeFunction: dF, decodeStmt: dS, decodeExpr: dE };
