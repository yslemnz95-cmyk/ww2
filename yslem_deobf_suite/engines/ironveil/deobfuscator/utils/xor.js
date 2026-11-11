'use strict';
class X {
  constructor(s) { this.s = (s >>> 0) || 0x9e3779b9; }
  next() {
    let x = this.s >>> 0;
    x ^= x << 13; x ^= x >>> 17; x ^= x << 5;
    this.s = x >>> 0;
    return this.s;
  }
  int(m) { return m <= 0 ? 0 : this.next() % m; }
  range(l, h) { return h <= l ? l : l + this.int(h - l + 1); }
}
function nx(s) {
  let x = s >>> 0;
  x ^= x << 13; x ^= x >>> 17; x ^= x << 5;
  return x >>> 0;
}
module.exports = { XS: X, nxs: nx };
