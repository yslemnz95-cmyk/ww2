'use strict';
const bO = ['+','-','*','/','%','^','..','==','~=','<','<=','>','>=','&','|','~','<<','>>'];
const uO = ['-','not','#','~'];
const P = { 'or':1,'and':2,'<':3,'<=':3,'>':3,'>=':3,'==':3,'~=':3,'..':4,'+':5,'-':5,'*':6,'/':6,'%':6,'^':8,'#':7,'not':7 };
function nP(o, c, ir) {
  const p = P[o] || 0, ch = P[c] || 0;
  if (ch === 0) return false;
  if (p > ch) return true;
  if (p === ch && ir && o !== '^') return true;
  return false;
}
function gOp(n) {
  if (!n || !Array.isArray(n)) return null;
  if (n[0] === 'binary') return typeof n[1] === 'string' ? n[1] : bO[(n[1] || 1) - 1] || '?';
  if (n[0] === 'unary') return typeof n[1] === 'string' ? n[1] : uO[(n[1] || 1) - 1] || '?';
  return null;
}
class G {
  constructor(n, s) { this.n = n; this.s = s; this.i = 0; }
  nm(r) { return this.n[r - 1] || ('_n' + r); }
  st(r) { return this.s[r - 1]; }
  id() { return '  '.repeat(this.i); }
  ex(e, f) {
    if (!e || !Array.isArray(e)) return '?';
    const [t, ...a] = e;
    switch (t) {
      case 'id': return this.nm(a[0]);
      case 'str': return lS(this.st(a[0]));
      case 'num': return String(a[0]);
      case 'bool': return a[0] === 1 ? 'true' : 'false';
      case 'nil': return 'nil';
      case 'vararg': return '...';
      case 'binary': {
        const o = typeof a[0] === 'string' ? a[0] : bO[(a[0] || 1) - 1] || '?';
        const l = this.ex(a[1], f), r = this.ex(a[2], f);
        const le = a[1], re = a[2];
        const wl = le && nP(o, gOp(le), false);
        const wr = re && nP(o, gOp(re), true);
        return `${wl ? '(' + l + ')' : l} ${o} ${wr ? '(' + r + ')' : r}`;
      }
      case 'unary': {
        const o = typeof a[0] === 'string' ? a[0] : uO[(a[0] || 1) - 1] || '?';
        const ar = this.ex(a[1], f);
        const sp = /[a-z]/.test(o) ? ' ' : '';
        return `${o}${sp}${ar}`;
      }
      case 'member': {
        const b = this.ex(a[0], f);
        if (a[2] === 1) return `${b}[${this.ex(a[1], f)}]`;
        return `${b}.${this.nm(a[1])}`;
      }
      case 'call': {
        const b = a[0], c = a[1] || [], s = a[2] === 1;
        if (s && Array.isArray(b) && b[0] === 'member' && b[2] !== 1) {
          const ob = this.ex(b[1], f), mt = this.nm(b[2]);
          return `${ob}:${mt}(${c.map(x => this.ex(x, f)).join(', ')})`;
        }
        return `${this.ex(b, f)}(${c.map(x => this.ex(x, f)).join(', ')})`;
      }
      case 'table': {
        const fi = a[0] || [];
        if (fi.length === 0) return '{}';
        return `{${fi.map(x => this.fd(x, f)).join(', ')}}`;
      }
      case 'function': {
        const fn = f[a[0] - 1];
        if (!fn) return 'function(...) end';
        return this.fE(fn, f);
      }
      case 'mini': return this.mE(a[0], f);
      default: return `nil`;
    }
  }
  fd(f, fs) {
    const [t, ...a] = f;
    if (t === 'array') return this.ex(a[0], fs);
    if (t === 'record') return `${this.nm(a[0])} = ${this.ex(a[1], fs)}`;
    return `[${this.ex(a[0], fs)}] = ${this.ex(a[1], fs)}`;
  }
  mE(p, f) {
    if (!p || !p.length) return 'nil';
    const s = [];
    for (const i of p) {
      const o = i[0];
      if (o === 1) s.push({ v: this.nm(i[1]), op: null });
      else if (o === 2) s.push({ v: lS(this.st(i[1])), op: null });
      else if (o === 3) s.push({ v: String(i[1]), op: null });
      else if (o === 4) s.push({ v: i[1] === 1 ? 'true' : 'false', op: null });
      else if (o === 5) s.push({ v: 'nil', op: null });
      else if (o === 6) { const b = s.pop(); s.push({ v: `${b.v}.${this.nm(i[1])}`, op: null }); }
      else if (o === 7) { const k = s.pop(); const b = s.pop(); s.push({ v: `${b.v}[${k.v}]`, op: null }); }
      else if (o === 8) { 
        const a = s.pop(); const u = uO[(i[1] || 1) - 1] || '?'; 
        const aV = (a.op && nP(u, a.op, false)) ? `(${a.v})` : a.v;
        s.push({ v: `${u}${/[a-z]/.test(u) ? ' ' : ''}${aV}`, op: u }); 
      }
      else if (o === 9) { 
        const r = s.pop(); const l = s.pop(); const bo = bO[(i[1] || 1) - 1] || '?'; 
        const lV = (l.op && nP(bo, l.op, false)) ? `(${l.v})` : l.v;
        const rV = (r.op && nP(bo, r.op, true)) ? `(${r.v})` : r.v;
        s.push({ v: `${lV} ${bo} ${rV}`, op: bo }); 
      }
    }
    return s[0] ? s[0].v : 'nil';
  }
  lv(l, f) {
    const [t, ...a] = l;
    if (t === 'id') return this.nm(a[0]);
    const b = this.ex(a[0], f);
    if (a[2] === 1) return `${b}[${this.ex(a[1], f)}]`;
    return `${b}.${this.nm(a[1])}`;
  }
  sm(s, f) {
    if (!s || !Array.isArray(s)) return '';
    const [t, ...a] = s, id = this.id();
    switch (t) {
      case 'local': {
        const v = a[0].map(r => this.nm(r)).join(', '), vl = a[1];
        if (!vl || vl.length === 0) return `${id}local ${v}`;
        return `${id}local ${v} = ${vl.map(e => this.ex(e, f)).join(', ')}`;
      }
      case 'assign': return `${id}${a[0].map(x => this.lv(x, f)).join(', ')} = ${a[1].map(x => this.ex(x, f)).join(', ')}`;
      case 'expr': return `${id}${this.ex(a[0], f)}`;
      case 'return': return (!a[0] || a[0].length === 0) ? `${id}return` : `${id}return ${a[0].map(e => this.ex(e, f)).join(', ')}`;
      case 'if': {
        let o = '';
        for (let i = 0; i < a[0].length; i++) {
          o += i === 0 ? `${id}if ${this.ex(a[0][i][0], f)} then\n` : `${id}elseif ${this.ex(a[0][i][0], f)} then\n`;
          o += this.bk(a[0][i][1], f);
        }
        if (a[1]) o += `${id}else\n${this.bk(a[1], f)}`;
        return o + `${id}end`;
      }
      case 'while': return `${id}while ${this.ex(a[0], f)} do\n${this.bk(a[1], f)}${id}end`;
      case 'repeat': return `${id}repeat\n${this.bk(a[0], f)}${id}until ${this.ex(a[1], f)}`;
      case 'fornum': return `${id}for ${this.nm(a[0])} = ${this.ex(a[1], f)}, ${this.ex(a[2], f)}${a[3] ? `, ${this.ex(a[3], f)}` : ''} do\n${this.bk(a[4], f)}${id}end`;
      case 'forin': return `${id}for ${a[0].map(r => this.nm(r)).join(', ')} in ${a[1].map(e => this.ex(e, f)).join(', ')} do\n${this.bk(a[2], f)}${id}end`;
      case 'break': return `${id}break`;
      case 'continue': return `${id}continue`;
      case 'do': return `${id}do\n${this.bk(a[0], f)}${id}end`;
      case 'func': {
        const il = a[0] === 1, l = this.lv(a[1], f), fn = f[a[2] - 1];
        if (!fn) return `${id}${il ? 'local ' : ''}function ${l}() end`;
        const p = fn.params.map(r => this.nm(r)).join(', ');
        const v = fn.vararg ? (fn.params.length > 0 ? ', ...' : '...') : '';
        let o = `${id}${il ? 'local ' : ''}function ${l}(${p}${v})\n`;
        this.i++; o += this.bk(fn.body, f); this.i--;
        return o + `${id}end`;
      }
      default: return ``;
    }
  }
  bk(s, f) {
    if (!s) return '';
    this.i++; const l = s.map(x => this.sm(x, f)).filter(Boolean); this.i--;
    return l.map(x => x + '\n').join('');
  }
  fE(f, fs) {
    const p = f.params.map(r => this.nm(r)).join(', ');
    const v = f.vararg ? (f.params.length > 0 ? ', ...' : '...') : '';
    let o = `function(${p}${v})\n`;
    o += this.bk(f.body, fs);
    return o + `${this.id()}end`;
  }
  pr(m) {
    const { entry: e, fns: f } = m, r = f[e - 1];
    if (!r) return '';
    return this.bk(r.body, f).trimEnd();
  }
}
function lS(s) {
  if (s === null || s === undefined) return '""';
  return '"' + String(s).replace(/\\/g,'\\\\').replace(/"/g,'\\"').replace(/\n/g,'\\n').replace(/\r/g,'\\r') + '"';
}
module.exports = { Gen: G, luaStr: lS };
