'use strict';
const { nxs: n } = require('./xor');
function xD(b, s) {
  let r = ((s ^ 0x13579bdf) >>> 0) || 0x9e3779b9;
  const o = Buffer.allocUnsafe(b.length);
  for (let i = 0; i < b.length; i++) {
    r = n(r);
    const m = ((r & 0xff) + ((s + ((i + 1) * 29)) & 0xff)) & 0xff;
    o[i] = b[i] ^ m;
  }
  return o;
}
function lD(b) {
  const c = [];
  for (let i = 0; i < b.length; i += 2) c.push((b[i] << 8) | b[i + 1]);
  const C = 256, E = 257;
  let d = null, nx = 258, k = [], p = null;
  function r() {
    d = [];
    for (let i = 0; i < 256; i++) d[i] = String.fromCharCode(i);
    nx = 258; p = null;
  }
  r();
  for (const x of c) {
    if (x === C) { r(); continue; }
    if (x === E) break;
    let y;
    if (x < nx) y = d[x];
    else if (x === nx && p !== null) y = p + p[0];
    else throw new Error('');
    k.push(y);
    if (p !== null) d[nx++] = p + y[0];
    p = y;
  }
  return k.join('');
}
function ds(s) {
  let i = 0;
  function r(d) {
    const p = i;
    while (s[i] !== d) i++;
    const v = s.slice(p, i); i++;
    return v;
  }
  function v() {
    const t = s[i++];
    if (t === 'Z') return null;
    if (t === 'T') return true;
    if (t === 'F') return false;
    if (t === 'N') return Number(r(';'));
    if (t === 'S') {
      const l = Number(r(':')) || 0;
      const x = s.slice(i, i + l); i += l;
      const b = [];
      for (let j = 0; j < x.length; j += 2) b.push(parseInt(x.slice(j, j + 2), 16) || 0);
      return Buffer.from(b).toString('utf8');
    }
    if (t === 'A') {
      const l = Number(r('[')) || 0;
      const a = [];
      for (let j = 0; j < l; j++) a.push(v());
      i++;
      return a;
    }
    if (t === 'O') {
      const l = Number(r('{')) || 0;
      const o = {};
      for (let j = 0; j < l; j++) { const k = v(); o[k] = v(); }
      i++;
      return o;
    }
    throw new Error('');
  }
  return v();
}
function hP(s, e) {
  let h = ((e ^ 0xa5a5a5a5) >>> 0);
  for (let i = 0; i < s.length; i++) {
    h = (h + (s.charCodeAt(i) & 0xff) + (((i + 1) * 97) >>> 0)) >>> 0;
    h ^= (h << 13) >>> 0; h ^= h >>> 7; h ^= (h << 17) >>> 0;
    h >>>= 0;
  }
  return h >>> 0;
}
function eP(b, k, ps, eh) {
  const rw = Buffer.from(b, 'base64');
  const d = xD(rw, k);
  const t = lD(d);
  const a = hP(t, ps);
  if (eh !== undefined && a !== (eh >>> 0)) throw new Error('');
  return ds(t);
}
module.exports = { extractPayload: eP, hashPayload: hP, xorDec: xD, lzwDec: lD, deser: ds };
