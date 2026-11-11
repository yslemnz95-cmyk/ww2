'use strict';
const oM = 0xffff;
const bN = ['+','-','*','/','%','^','..','==','~=','<','<=','>','>=','&','|','~','<<','>>'];
const uN = ['-','not','#','~'];
const eN = ['id','str','num','bool','nil','vararg','binary','unary','member','call','table','function','mini'];
const sN = ['local','assign','expr','return','if','while','repeat','fornum','forin','break','continue','do','func'];
const lN = ['id','member'];
const fN = ['array','record','general'];

function o(s, k, sa) {
  const se = (k + (s * 149) + (sa * 53)) & oM;
  const m = (se ^ (((s * 17) + (sa * 29)) & oM)) & oM;
  const sp = (((k >>> (s & 7)) ^ (((s * 97) + (sa * 11)) & oM))) & oM;
  const sh = ((s + sa + (k % 7)) % 15) + 1;
  const a = (sp + sa + (s * 3)) & oM;
  const ma = (m + sp + sh) & oM;
  return { m, sh, a, ma };
}
function rl(v, s) {
  const a = s & 15;
  if (a === 0) return v & oM;
  return (((v << a) | (v >>> (16 - a))) & oM) >>> 0;
}
function eO(v, s, k, sa) {
  const x = o(s, k, sa);
  let r = (v ^ x.m) & oM;
  r = rl(r, x.sh);
  r = (r + x.a) & oM;
  r = (r ^ x.ma) & oM;
  return r >>> 0;
}
function rr(v, s) {
  const a = s & 15;
  if (a === 0) return v & oM;
  return (((v >>> a) | (v << (16 - a))) & oM) >>> 0;
}
function dO(e, s, k, sa) {
  const x = o(s, k, sa);
  let r = (e ^ x.ma) & oM;
  r = (r - x.a + 0x10000) & oM;
  r = rr(r, x.sh);
  r = (r ^ x.m) & oM;
  return r >>> 0;
}
function dK(s, i) {
  const v = (s + (i * 977) + (i * 131)) & oM;
  return v === 0 ? 1 : v;
}
function cM(p, h, s, sa) {
  return ((p * 131) + (h * 17) + sa + s) & oM;
}
function nH(h, d, s, sa) {
  return ((h * 257) + d + sa + s) & oM;
}
function dNO(e, s, k, sa, st) {
  const rX = dO(e, s, k, sa);
  const m = cM(st.pn, st.nh, s, sa);
  const r = (rX ^ m) & oM;
  st.pn = r;
  st.nh = nH(st.nh, r, s, sa);
  return r;
}
function dOO(e, s, k, sa, st) {
  const rX = dO(e, s, k, sa);
  const m = cM(st.po, st.oh, s, sa);
  const r = (rX ^ m) & oM;
  st.po = r;
  st.oh = nH(st.oh, r, s, sa);
  return r;
}
function bR(t, d, s, n) {
  const m = new Map();
  for (const e of t) m.set(dO(e[0], e[1][0], d, s), n[e[1][0] - 1]);
  return m;
}
const bS = bR;
function bC(p) {
  const [, e, f, m] = p;
  const [oS, dS, bS, uS, eS, sS] = m;
  return { entry: e, fns: f, opcodeSeed: oS, defSeed: dS, binSpecs: bS, unarySpecs: uS, exprSpecs: eS, stmtSpecs: sS };
}
module.exports = {
  encodeOpcode: eO, decodeOpcode: dO, decodeNodeOpcode: dNO, decodeOpOpcode: dOO,
  deriveKey: dK, buildRawMap: bR, buildSpecMap: bS,
  buildOpcodeContext: bC,
  BINARY_NAMES: bN, UNARY_NAMES: uN, EXPR_NAMES: eN, STMT_NAMES: sN, LVALUE_NAMES: lN, FIELD_NAMES: fN,
  OP_MASK: oM
};
