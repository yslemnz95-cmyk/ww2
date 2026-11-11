function isBlkOpen(name) {
  return name === 'if' || name === 'function' || name === 'repeat' || name === 'do';
}

function isBlkSkip(name) {
  return name === 'for' || name === 'while';
}

function isWs(ch) {
  return ch === ' ' || ch === '\t' || ch === '\n' || ch === '\r' || ch === '\f' || ch === '\v';
}

function isDig(ch) {
  return ch >= '0' && ch <= '9';
}

function isA(ch) {
  return (ch >= 'a' && ch <= 'z') || (ch >= 'A' && ch <= 'Z');
}

function isId0(ch) {
  return isA(ch) || ch === '_';
}

function isId(ch) {
  return isId0(ch) || isDig(ch);
}

function strWs(s) {
  let out = '';
  for (let i = 0; i < s.length; i++) {
    if (!isWs(s[i])) out += s[i];
  }
  return out;
}

function colWs(s) {
  let out = '';
  let space = false;
  for (let i = 0; i < s.length; i++) {
    if (isWs(s[i])) {
      if (!space && out.length) {
        out += ' ';
        space = true;
      }
    } else {
      out += s[i];
      space = false;
    }
  }
  return out.trim();
}

function rdId(src, i) {
  if (!isId0(src[i] || '')) return null;
  let j = i + 1;
  while (j < src.length && isId(src[j])) j++;
  return { name: src.slice(i, j), end: j };
}

function rdNum(src, i) {
  if (!isDig(src[i]) && !(src[i] === '.' && isDig(src[i + 1] || ''))) return null;
  let j = i;
  while (j < src.length && (isDig(src[j]) || src[j] === '.')) j++;
  return { value: src.slice(i, j), end: j, num: Number(src.slice(i, j)) };
}

function skStr(src, i) {
  const q = src[i];
  if (q !== '"' && q !== "'") return i;
  let j = i + 1;
  while (j < src.length && src[j] !== q) {
    if (src[j] === '\\') j++;
    j++;
  }
  return j + 1;
}

function skWs(src, i) {
  while (i < src.length && isWs(src[i])) i++;
  return i;
}

function nextKw(src, i) {
  const start = skWs(src, i);
  if (start >= src.length) return null;
  if (src[start] === '"' || src[start] === "'") {
    return { kind: 'str', start, end: skStr(src, start) };
  }
  const id = rdId(src, start);
  if (!id) return { kind: 'ch', ch: src[start], start, end: start + 1 };
  return { kind: 'kw', name: id.name, start, end: id.end };
}

function findBlkEnd(src, from) {
  const head = nextKw(src, from);
  if (!head || head.kind !== 'kw') return -1;
  if (!isBlkOpen(head.name) && !isBlkSkip(head.name)) return -1;

  let i = head.end;
  let depth = 1;

  
  if (isBlkSkip(head.name)) {
    while (i < src.length) {
      if (src[i] === '"' || src[i] === "'") {
        i = skStr(src, i);
        continue;
      }
      const tok = nextKw(src, i);
      if (!tok) return -1;
      if (tok.kind === 'kw' && tok.name === 'do') {
        i = tok.end;
        break;
      }
      i = tok.end;
    }
  }

  while (i < src.length) {
    if (src[i] === '"' || src[i] === "'") {
      i = skStr(src, i);
      continue;
    }
    const tok = nextKw(src, i);
    if (!tok) break;
    if (tok.kind !== 'kw') {
      i = tok.end;
      continue;
    }
    const name = tok.name;
    if (name === 'elseif' || name === 'else') {
      i = tok.end;
      continue;
    }
    if (isBlkSkip(name)) {
      i = tok.end;
      continue;
    }
    if (isBlkOpen(name)) {
      depth++;
      i = tok.end;
      continue;
    }
    if (name === 'until' || name === 'end') {
      depth--;
      i = tok.end;
      if (depth === 0) return i;
      continue;
    }
    i = tok.end;
  }
  return -1;
}

function xtrQ(src, quoteIdx) {
  if (src[quoteIdx] !== '"') throw new Error('expected quote');
  let i = quoteIdx + 1;
  let content = '';
  while (i < src.length) {
    if (src[i] === '\\' && i + 1 < src.length) {
      content += '\\';
      i++;
      if (isDig(src[i])) {
        let n = 0;
        while (i < src.length && isDig(src[i]) && n < 3) {
          content += src[i++];
          n++;
        }
      } else {
        content += src[i++];
      }
    } else if (src[i] === '"') {
      return { content, end: i };
    } else {
      content += src[i++];
    }
  }
  throw new Error('unterminated string');
}

function wdAt(src, i, word) {
  if (src.slice(i, i + word.length) !== word) return false;
  const before = i === 0 ? '' : src[i - 1];
  const after = src[i + word.length] || '';
  if (before && isId(before)) return false;
  if (after && isId(after)) return false;
  return true;
}

function findWd(src, word, from = 0) {
  let i = from;
  while (i < src.length) {
    if (src[i] === '"' || src[i] === "'") {
      i = skStr(src, i);
      continue;
    }
    if (wdAt(src, i, word)) return i;
    i++;
  }
  return -1;
}

function evalOk(expr) {
  try {
    return evalEx(expr);
  } catch {
    return null;
  }
}


function stripSp(s) {
  let out = '';
  for (let i = 0; i < s.length; i++) {
    if (!isWs(s[i])) out += s[i];
  }
  return out;
}

function tok(expr) {
  const tokens = [];
  const s = stripSp(String(expr));
  let i = 0;
  while (i < s.length) {
    if (isDig(s[i]) || (s[i] === '.' && isDig(s[i + 1] || ''))) {
      let j = i;
      while (j < s.length && (isDig(s[j]) || s[j] === '.')) j++;
      tokens.push({ type: 'num', value: parseFloat(s.slice(i, j)) });
      i = j;
    } else if ('+-*/%()^'.includes(s[i])) {
      tokens.push({ type: 'op', value: s[i] });
      i++;
    } else {
      throw new Error(`bad expr: ${s[i]}`);
    }
  }
  return tokens;
}

function evalTok(tokens) {
  let pos = 0;
  const peek = () => tokens[pos];
  const take = () => tokens[pos++];

  function expr() {
    let left = term();
    while (peek() && (peek().value === '+' || peek().value === '-')) {
      const op = take().value;
      const right = term();
      left = op === '+' ? left + right : left - right;
    }
    return left;
  }

  function term() {
    let left = unary();
    while (peek() && '*/%^'.includes(peek().value || '')) {
      const op = take().value;
      const right = unary();
      if (op === '*') left *= right;
      else if (op === '/') left /= right;
      else if (op === '%') left %= right;
      else left **= right;
    }
    return left;
  }

  function unary() {
    if (peek() && peek().value === '-') {
      take();
      return -unary();
    }
    return prim();
  }

  function prim() {
    const t = peek();
    if (!t) throw new Error('eof');
    if (t.type === 'num') {
      take();
      return t.value;
    }
    if (t.value === '(') {
      take();
      const v = expr();
      if (!peek() || peek().value !== ')') throw new Error(')');
      take();
      return v;
    }
    throw new Error('token');
  }

  const result = expr();
  if (pos !== tokens.length) throw new Error('trailing');
  return result;
}

function evalEx(expr) {
  return evalTok(tok(expr));
}

function isArith(s) {
  let hasDigit = false;
  for (let i = 0; i < s.length; i++) {
    const ch = s[i];
    if (isDig(ch) || ch === '.') hasDigit = true;
    else if (isWs(ch) || '+-*/%'.includes(ch)) continue;
    else return false;
  }
  return hasDigit;
}

function hasBinOp(s) {
  let i = 0;
  while (i < s.length && isWs(s[i])) i++;
  if (s[i] === '-') i++;
  while (i < s.length) {
    if (isDig(s[i]) || s[i] === '.') {
      i++;
      continue;
    }
    if (isWs(s[i])) {
      i++;
      continue;
    }
    if ('+-*/%^'.includes(s[i])) return true;
    if (s[i] === '(' || s[i] === ')') {
      i++;
      continue;
    }
    return false;
  }
  return false;
}

function foldPar(code) {
  let out = code;
  let changed = true;
  while (changed) {
    changed = false;
    let i = 0;
    let next = '';
    while (i < out.length) {
      if (out[i] === '"' || out[i] === "'") {
        const q = out[i];
        next += q;
        i++;
        while (i < out.length && out[i] !== q) {
          if (out[i] === '\\') {
            next += out[i++];
            if (i < out.length) next += out[i++];
          } else {
            next += out[i++];
          }
        }
        if (i < out.length) next += out[i++];
        continue;
      }
      if (out[i] === '(') {
        let depth = 1;
        let j = i + 1;
        let inner = '';
        let ok = true;
        while (j < out.length && depth > 0) {
          if (out[j] === '"' || out[j] === "'") {
            ok = false;
            break;
          }
          if (out[j] === '(') depth++;
          else if (out[j] === ')') depth--;
          if (depth > 0) inner += out[j];
          j++;
        }
        if (ok && depth === 0 && isArith(inner) && hasBinOp(inner)) {
          try {
            const v = evalEx(inner);
            if (Number.isFinite(v)) {
              const prev = next.length ? next[next.length - 1] : '';
              const callParen = isId(prev) || prev === ')' || prev === ']';
              const lit = fmtNum(v);
              next += callParen ? `(${lit})` : lit;
              i = j;
              changed = true;
              continue;
            }
          } catch {
            
          }
        }
      }
      next += out[i++];
    }
    out = next;
  }
  return out;
}

function fmtNum(v) {
  if (!Number.isFinite(v)) return String(v);
  if (Object.is(v, -0)) return '0';
  if (Number.isInteger(v) && Math.abs(v) < 1e15) return String(v);
  const rounded = Math.round(v * 1e12) / 1e12;
  if (Number.isInteger(rounded) && Math.abs(rounded) < 1e15) return String(rounded);
  let t = String(rounded);
  if (t.includes('e') || t.includes('E')) return t;
  if (t.includes('.')) {
    let end = t.length;
    while (end > 0 && t[end - 1] === '0') end--;
    if (end > 0 && t[end - 1] === '.') end--;
    t = t.slice(0, end);
  }
  return t;
}

function rdNumAt(s, i) {
  if (!(isDig(s[i]) || (s[i] === '.' && isDig(s[i + 1] || '')))) return null;
  let j = i;
  if (isDig(s[j])) {
    while (j < s.length && isDig(s[j])) j++;
  }
  if (s[j] === '.' && isDig(s[j + 1] || '')) {
    j++;
    while (j < s.length && isDig(s[j])) j++;
  }
  if ((s[j] === 'e' || s[j] === 'E') && (isDig(s[j + 1] || '') || ((s[j + 1] === '+' || s[j + 1] === '-') && isDig(s[j + 2] || '')))) {
    j++;
    if (s[j] === '+' || s[j] === '-') j++;
    while (j < s.length && isDig(s[j])) j++;
  }
  const value = s.slice(i, j);
  return { value, end: j, num: Number(value) };
}

function skSp(s, i) {
  while (i < s.length && isWs(s[i])) i++;
  return i;
}

function foldBin(code) {
  let out = code;
  let changed = true;
  while (changed) {
    changed = false;
    let i = 0;
    let next = '';
    while (i < out.length) {
      if (out[i] === '"' || out[i] === "'") {
        const q = out[i];
        next += q;
        i++;
        while (i < out.length && out[i] !== q) {
          if (out[i] === '\\') {
            next += out[i++];
            if (i < out.length) next += out[i++];
          } else next += out[i++];
        }
        if (i < out.length) next += out[i++];
        continue;
      }

      const left = rdNumAt(out, i);
      if (left && (i === 0 || !isId(out[i - 1]))) {
        let j = skSp(out, left.end);
        const op = out[j];
        if (op && '+-*/%^'.includes(op)) {
          j = skSp(out, j + 1);
          const right = rdNumAt(out, j);
          if (right && (right.end >= out.length || !isId(out[right.end]))) {
            let v;
            if (op === '+') v = left.num + right.num;
            else if (op === '-') v = left.num - right.num;
            else if (op === '*') v = left.num * right.num;
            else if (op === '/') v = left.num / right.num;
            else if (op === '%') v = left.num % right.num;
            else v = left.num ** right.num;
            next += fmtNum(v);
            i = right.end;
            changed = true;
            continue;
          }
        }
      }
      next += out[i++];
    }
    out = next;
  }
  return out;
}

function foldHash(code) {
  let out = '';
  let i = 0;
  while (i < code.length) {
    if (code[i] === '"' || code[i] === "'") {
      const q = code[i++];
      out += q;
      while (i < code.length && code[i] !== q) {
        if (code[i] === '\\') {
          out += code[i++];
          if (i < code.length) out += code[i++];
        } else out += code[i++];
      }
      if (i < code.length) out += code[i++];
      continue;
    }
    if (code[i] === '#' && (code[i + 1] === '"' || code[i + 1] === "'")) {
      const q = code[i + 1];
      let j = i + 2;
      let len = 0;
      while (j < code.length && code[j] !== q) {
        if (code[j] === '\\') j++;
        j++;
        len++;
      }
      if (code[j] === q) {
        out += String(len);
        i = j + 1;
        continue;
      }
    }
    out += code[i++];
  }
  return out;
}

function cmpNum(a, op, b) {
  if (op === '==') return a === b;
  if (op === '~=') return a !== b;
  if (op === '<') return a < b;
  if (op === '>') return a > b;
  if (op === '<=') return a <= b;
  if (op === '>=') return a >= b;
  return null;
}

function foldCmp(code) {
  let out = code;
  let changed = true;
  while (changed) {
    changed = false;
    let i = 0;
    let next = '';
    while (i < out.length) {
      if (out[i] === '"' || out[i] === "'") {
        const q = out[i];
        next += q;
        i++;
        while (i < out.length && out[i] !== q) {
          if (out[i] === '\\') {
            next += out[i++];
            if (i < out.length) next += out[i++];
          } else next += out[i++];
        }
        if (i < out.length) next += out[i++];
        continue;
      }

      const left = rdNumAt(out, i);
      if (left && (i === 0 || !isId(out[i - 1]))) {
        let j = skSp(out, left.end);
        let op = null;
        if (out.slice(j, j + 2) === '==' || out.slice(j, j + 2) === '~=' || out.slice(j, j + 2) === '<=' || out.slice(j, j + 2) === '>=') {
          op = out.slice(j, j + 2);
          j += 2;
        } else if (out[j] === '<' || out[j] === '>') {
          op = out[j];
          j += 1;
        }
        if (op) {
          j = skSp(out, j);
          const right = rdNumAt(out, j);
          if (right && (right.end >= out.length || !isId(out[right.end]))) {
            const v = cmpNum(left.num, op, right.num);
            if (v !== null) {
              next += v ? 'true' : 'false';
              i = right.end;
              changed = true;
              continue;
            }
          }
        }
      }
      next += out[i++];
    }
    out = next;
  }
  return out;
}

function foldBool(code) {
  let out = code;
  let guard = 0;
  while (guard++ < 40) {
    const prev = out;
    
    out = replPln(out, '(true)', 'true');
    out = replPln(out, '(false)', 'false');
    out = replPln(out, 'true and ', '');
    out = replPln(out, ' and true', '');
    out = replPln(out, 'false or ', '');
    out = replPln(out, ' or false', '');
    out = replPln(out, 'false and ', 'false and_STOP '); 
    
    out = replPln(out, ' or true', ' or_TRUE');
    out = replPln(out, 'and_STOP ', 'and ');
    
    out = simpbt(out);
    if (out === prev) break;
  }
  return out;
}

function replPln(s, a, b) {
  if (!a) return s;
  let out = '';
  let i = 0;
  while (i < s.length) {
    if (s[i] === '"' || s[i] === "'") {
      const q = s[i++];
      out += q;
      while (i < s.length && s[i] !== q) {
        if (s[i] === '\\') {
          out += s[i++];
          if (i < s.length) out += s[i++];
        } else out += s[i++];
      }
      if (i < s.length) out += s[i++];
      continue;
    }
    if (s.startsWith(a, i)) {
      out += b;
      i += a.length;
      continue;
    }
    out += s[i++];
  }
  return out;
}

function simpbt(code) {
  
  
  
  let out = replPln(code, ' or_TRUE', '');
  
  out = replPln(out, 'true or ', 'true or_KEEP ');
  
  out = replPln(out, 'true or_KEEP ', 'true or ');
  return out;
}

function foldt(code) {
  
  let out = '';
  let i = 0;
  const needle = '(function() return';
  while (i < code.length) {
    if (code[i] === '"' || code[i] === "'") {
      const q = code[i++];
      out += q;
      while (i < code.length && code[i] !== q) {
        if (code[i] === '\\') {
          out += code[i++];
          if (i < code.length) out += code[i++];
        } else out += code[i++];
      }
      if (i < code.length) out += code[i++];
      continue;
    }
    if (code.startsWith(needle, i)) {
      let j = skSp(code, i + needle.length);
      const num = rdNumAt(code, j);
      if (num) {
        j = skSp(code, num.end);
        if (code[j] === ';') j = skSp(code, j + 1);
        if (code.startsWith('end)()', j)) {
          out += String(num.num);
          i = j + 6;
          continue;
        }
      }
      
    }
    out += code[i++];
  }
  return out;
}

function foldConst(code) {
  const src = String(code);
  
  if (src === foldConst._lastIn) return foldConst._lastOut;
  let out = src;
  out = foldHash(out);
  out = foldPar(out);
  out = foldBin(out);
  out = foldCmp(out);
  out = foldt(out);
  out = foldBool(out);
  out = foldPar(out);
  out = foldBin(out);
  foldConst._lastIn = src;
  foldConst._lastOut = out;
  return out;
}


function parseLStr(s) {
  const out = [];
  for (let i = 0; i < s.length; ) {
    if (s[i] === '\\' && i + 1 < s.length) {
      const n = s[i + 1];
      if (n >= '0' && n <= '9') {
        let j = i + 1;
        let digits = '';
        while (j < s.length && s[j] >= '0' && s[j] <= '9' && digits.length < 3) {
          digits += s[j++];
        }
        out.push(parseInt(digits, 10) & 255);
        i = j;
      } else {
        const map = { n: 10, r: 13, t: 9, a: 7, b: 8, f: 12, v: 11, '"': 34, "'": 39, '\\': 92 };
        out.push(map[n] != null ? map[n] : n.charCodeAt(0));
        i += 2;
      }
    } else {
      out.push(s.charCodeAt(i));
      i++;
    }
  }
  return Buffer.from(out);
}

function xorDec(data, key) {
  const out = Buffer.alloc(data.length);
  for (let i = 0; i < data.length; i++) {
    const keyIdx = 1 + ((i + 1) % key.length);
    out[i] = data[i] ^ key[keyIdx - 1];
  }
  return out;
}

function findDec(src, fnName = 'v7') {
  const results = [];
  const tag = `${fnName}("`;
  let from = 0;
  while (from < src.length) {
    const at = src.indexOf(tag, from);
    if (at < 0) break;
    try {
      const dataQ = xtrQ(src, at + fnName.length + 1);
      if (src[dataQ.end + 1] !== ',' || src[dataQ.end + 2] !== '"') {
        from = at + tag.length;
        continue;
      }
      const keyQ = xtrQ(src, dataQ.end + 2);
      const data = parseLStr(dataQ.content);
      const key = parseLStr(keyQ.content);
      const decrypted = xorDec(data, key);
      results.push({
        index: at,
        data,
        key,
        decrypted,
        text: decrypted.toString('latin1'),
        end: keyQ.end + 1,
      });
      from = keyQ.end + 1;
    } catch {
      from = at + tag.length;
    }
  }
  return results;
}

function findV7Calls(src) {
  return findDec(src, 'v7');
}


function prnRatio(s) {
  if (!s || !s.length) return 0;
  let ok = 0;
  for (let i = 0; i < s.length; i++) {
    const c = s.charCodeAt(i);
    if ((c >= 32 && c < 127) || c === 9 || c === 10 || c === 13) ok++;
  }
  return ok / s.length;
}

function isPrn(s) {
  return typeof s === 'string' && s.length > 0 && prnRatio(s) >= 0.85;
}

function isCiph(s) {
  if (typeof s !== 'string' || s.length < 2 || isPrn(s)) return false;
  let bad = 0;
  for (let i = 0; i < s.length; i++) {
    const c = s.charCodeAt(i);
    if (c < 9 || (c > 13 && c < 32) || c >= 127) bad++;
  }
  return bad / s.length >= 0.3;
}

function scorePln(s) {
  if (!isPrn(s)) return -1;
  let score = s.length;
  for (let i = 0; i < s.length; i++) {
    const c = s.charCodeAt(i);
    if ((c >= 65 && c <= 90) || (c >= 97 && c <= 122) || (c >= 48 && c <= 57)) score += 2;
    if (c === 32) score += 1;
  }
  return score;
}

function tryDec(cipher, key) {
  if (typeof cipher !== 'string' || typeof key !== 'string') return null;
  if (!cipher.length || !key.length) return null;
  const plain = xorDec(
    Buffer.from(cipher, 'latin1'),
    Buffer.from(key, 'latin1')
  ).toString('latin1');
  const score = scorePln(plain);
  if (score < 0) return null;
  return { plain, score };
}

function decOuter(source) {
  const out = [];
  for (const call of findV7Calls(source)) {
    if (call.text.startsWith('LOL!') || call.text === '..') continue;
    out.push({
      index: call.index,
      encryptedHex: call.data.toString('hex'),
      keyHex: call.key.toString('hex'),
      decrypted: call.text,
      kind: 'outer_v7',
    });
  }
  return out;
}

function rwOuter(source, fnName = 'v7') {
  const calls = [...findV7Calls(source)].sort((a, b) => b.index - a.index);
  let text = source;
  let replaced = 0;
  for (const call of calls) {
    if (call.text.startsWith('LOL!')) continue;
    try {
      const data = xtrQ(text, call.index + fnName.length + 1);
      if (text[data.end + 1] !== ',' || text[data.end + 2] !== '"') continue;
      const key = xtrQ(text, data.end + 2);
      const close = key.end + 1;
      if (text[close] !== ')') continue;
      text = text.slice(0, call.index) + JSON.stringify(call.text) + text.slice(close + 1);
      replaced++;
    } catch {
      
    }
  }
  return { source: text, replaced };
}

function patchOps(proto, from, to) {
  for (const ins of proto.instructions) {
    if (!ins || ins.skipped) continue;
    if (ins.A === from) ins.A = to;
    if (ins.B === from) ins.B = to;
    if (ins.C === from) ins.C = to;
  }
  for (const child of proto.prototypes) {
    if (child) patchOps(child, from, to);
  }
}

function bestK(cipher, pool) {
  let best = null;
  for (const item of pool) {
    if (typeof item.value !== 'string' || !item.value.length) continue;
    const hit = tryDec(cipher, item.value);
    if (!hit) continue;
    if (!best || hit.score > best.score) {
      best = { ...hit, key: item.value, keyPath: item.path, keyIndex: item.index };
    }
  }
  if (best) return best;
  for (let k = 1; k < 256; k++) {
    const hit = tryDec(cipher, String.fromCharCode(k));
    if (!hit) continue;
    if (!best || hit.score > best.score) {
      best = { ...hit, key: String.fromCharCode(k), keyPath: null, keyIndex: null, singleByte: true };
    }
  }
  return best;
}

function decVm(root) {
  const maps = [];
  const keyConsts = new Set();

  function walk(proto, path, inherited) {
    const local = [];
    for (let i = 1; i < proto.constants.length; i++) {
      const val = proto.constants[i];
      if (typeof val === 'string') local.push({ index: i, value: val, path });
    }
    const pool = local.concat(inherited);

    for (const item of local) {
      if (!isCiph(item.value)) continue;
      const hit = bestK(item.value, pool.filter((p) => !(p.path === item.path && p.index === item.index)));
      if (!hit || hit.score < 6) continue;
      maps.push({
        protoPath: item.path,
        index: item.index,
        encrypted: item.value,
        encryptedHex: Buffer.from(item.value, 'latin1').toString('hex'),
        key: hit.key,
        keyPath: hit.keyPath,
        keyIndex: hit.keyIndex,
        decrypted: hit.plain,
        score: hit.score,
        singleByte: !!hit.singleByte,
      });
      const old = item.value;
      proto.constants[item.index] = hit.plain;
      item.value = hit.plain;
      patchOps(root, old, hit.plain);
      if (hit.key && isCiph(hit.key)) keyConsts.add(hit.key);
    }

    for (let i = 0; i < proto.prototypes.length; i++) {
      if (!proto.prototypes[i]) continue;
      walk(proto.prototypes[i], `${path}/${i}`, pool);
    }
  }

  walk(root, 'main', []);

  
  function blankK(proto) {
    for (let i = 1; i < proto.constants.length; i++) {
      const val = proto.constants[i];
      if (typeof val === 'string' && keyConsts.has(val)) {
        const old = val;
        proto.constants[i] = null;
        patchOps(root, old, null);
      } else if (typeof val === 'string' && isCiph(val)) {
        
      }
    }
    for (const child of proto.prototypes) if (child) blankK(child);
  }
  blankK(root);

  
  function secPass(proto, path, plains) {
    const localPlains = plains.slice();
    for (let i = 1; i < proto.constants.length; i++) {
      const val = proto.constants[i];
      if (typeof val === 'string' && isPrn(val)) {
        localPlains.push({ index: i, value: val, path });
      }
    }
    for (let i = 1; i < proto.constants.length; i++) {
      const val = proto.constants[i];
      if (typeof val !== 'string' || !isCiph(val)) continue;
      const hit = bestK(val, localPlains);
      if (!hit || hit.score < 6) continue;
      maps.push({
        protoPath: path,
        index: i,
        encrypted: val,
        encryptedHex: Buffer.from(val, 'latin1').toString('hex'),
        key: hit.key,
        decrypted: hit.plain,
        score: hit.score,
        singleByte: !!hit.singleByte,
        pass: 2,
      });
      proto.constants[i] = hit.plain;
      patchOps(root, val, hit.plain);
      localPlains.push({ index: i, value: hit.plain, path });
    }
    for (let i = 0; i < proto.prototypes.length; i++) {
      if (!proto.prototypes[i]) continue;
      secPass(proto.prototypes[i], `${path}/${i}`, localPlains);
    }
  }
  secPass(root, 'main', []);

  return maps;
}

function decAllStr(source, root) {
  const outer = decOuter(source);
  const rewritten = rwOuter(source);
  const vm = root ? decVm(root) : [];
  return {
    outer,
    vm,
    rewrittenSource: rewritten.source,
    outerReplaced: rewritten.replaced,
    summary: {
      outerCount: outer.length,
      vmCount: vm.length,
      outerReplaced: rewritten.replaced,
    },
  };
}


function decLol(decrypted, sentinel = 0x4f) {
  const buf = Buffer.isBuffer(decrypted) ? decrypted : Buffer.from(decrypted, 'latin1');
  const magic = buf.slice(0, 4).toString('latin1');
  if (magic !== 'LOL!') {
    throw new Error(`bc:magic:${JSON.stringify(magic)}`);
  }
  const s = buf.slice(4).toString('latin1');
  const out = [];
  let i = 0;
  let rep = null;
  while (i + 1 < s.length) {
    const a = s.charCodeAt(i);
    const b = s.charCodeAt(i + 1);
    i += 2;
    if (b === sentinel) {
      rep = parseInt(String.fromCharCode(a), 10);
      if (Number.isNaN(rep)) throw new Error(`bc:rle:${i}`);
      continue;
    }
    const byte = parseInt(String.fromCharCode(a, b), 16);
    if (Number.isNaN(byte)) throw new Error(`bc:hex:${i}`);
    if (rep != null) {
      for (let r = 0; r < rep; r++) out.push(byte);
      rep = null;
    } else {
      out.push(byte);
    }
  }
  return Buffer.from(out);
}

function xtrRle(source) {
    const folded = foldConst(source);
  let i = 0;
  while (i < folded.length) {
    if (folded[i] !== '(') {
      i++;
      continue;
    }
    const close = folded.indexOf(')', i + 1);
    if (close < 0 || close - i > 40) {
      i++;
      continue;
    }
    const inner = folded.slice(i + 1, close);
    const comma = inner.lastIndexOf(',');
    if (comma >= 0) {
      let j = skWs(inner, comma + 1);
      if (inner[j] === '2' && (j + 1 >= inner.length || !isDig(inner[j + 1]))) {
        let k = skWs(folded, close + 1);
        if (folded[k] === '=' && folded[k + 1] === '=') {
          k = skWs(folded, k + 2);
          if (folded[k] === '(') k++;
          const num = rdNum(folded, k);
          
          if (num && num.num >= 32 && num.num < 127) return num.num;
        }
      }
    }
    i++;
  }
  return null;
}

function isHex(b) {
  return (b >= 48 && b <= 57) || (b >= 65 && b <= 70) || (b >= 97 && b <= 102);
}

function guessSent(decrypted) {
  const buf = Buffer.isBuffer(decrypted) ? decrypted : Buffer.from(decrypted, 'latin1');
  const s = buf.slice(4);
  const votes = new Map();
  for (let i = 0; i + 1 < Math.min(s.length, 200); i += 2) {
    const a = s[i];
    const b = s[i + 1];
    if (!isHex(a) || !isHex(b)) {
      if (a >= 48 && a <= 57) votes.set(b, (votes.get(b) || 0) + 1);
    }
  }
  let best = 0x4f;
  let bestN = 0;
  for (const [b, n] of votes) {
    if (n > bestN) {
      best = b;
      bestN = n;
    }
  }
  return best;
}

class Reader {
  constructor(buf) {
    this.buf = buf;
    this.pos = 0;
  }

  remaining() {
    return this.buf.length - this.pos;
  }

  byte() {
    if (this.pos >= this.buf.length) throw new Error('EOF byte');
    return this.buf[this.pos++];
  }

  u16() {
    return this.byte() + this.byte() * 256;
  }

  u32() {
    return this.byte() + this.byte() * 256 + this.byte() * 65536 + this.byte() * 16777216;
  }

  bits(n, start, end) {
    if (end == null) {
      const bit = 2 ** (start - 1);
      return n % (bit + bit) >= bit ? 1 : 0;
    }
    return Math.floor((n / 2 ** (start - 1)) % 2 ** (end - start + 1));
  }

  double() {
    const lo = this.u32();
    const hi = this.u32();
    const tmp = Buffer.alloc(8);
    tmp.writeUInt32LE(lo >>> 0, 0);
    tmp.writeUInt32LE(hi >>> 0, 4);
    return tmp.readDoubleLE(0);
  }

  str() {
    const len = this.u32();
    if (len === 0) return '';
    if (this.pos + len > this.buf.length) throw new Error('EOF string');
    const s = this.buf.slice(this.pos, this.pos + len).toString('latin1');
    this.pos += len;
    return s;
  }
}

function desPr(r) {
  const constants = [];
  const instructions = [];
  const prototypes = [];

  const constCount = r.u32();
  for (let i = 1; i <= constCount; i++) {
    const t = r.byte();
    if (t === 1) constants[i] = r.byte() !== 0;
    else if (t === 2) constants[i] = r.double();
    else if (t === 3) constants[i] = r.str();
    else constants[i] = null;
  }

  const params = r.byte();
  const instCount = r.u32();
  for (let i = 1; i <= instCount; i++) {
    const flag = r.byte();
    if (r.bits(flag, 1, 1) === 0) {
      const mode = r.bits(flag, 2, 3);
      const kFlags = r.bits(flag, 4, 6);
      const opcode = r.u16();
      let A = r.u16();
      let B = null;
      let C = null;
      if (mode === 0) {
        B = r.u16();
        C = r.u16();
      } else if (mode === 1) {
        B = r.u32();
      } else if (mode === 2) {
        B = r.u32() - 65536;
      } else if (mode === 3) {
        B = r.u32() - 65536;
        C = r.u16();
      }
      const isKA = r.bits(kFlags, 1, 1) === 1;
      const isKB = r.bits(kFlags, 2, 2) === 1;
      const isKC = r.bits(kFlags, 3, 3) === 1;
      const rawA = A;
      const rawB = B;
      const rawC = C;
      if (isKA) A = constants[A];
      if (isKB) B = constants[B];
      if (isKC) C = constants[C];
      instructions[i] = {
        opcode, A, B, C, mode, kFlags, isKA, isKB, isKC, rawA, rawB, rawC, flag,
      };
    } else {
      instructions[i] = { skipped: true, flag };
    }
  }

  const protoCount = r.u32();
  for (let i = 0; i < protoCount; i++) {
    prototypes[i] = desPr(r);
  }

  return { params, constants, instructions, prototypes };
}

function findPlnLol(source) {
    const out = [];
  let from = 0;
  while (from < source.length) {
    const at = source.indexOf('"LOL!', from);
    if (at < 0) break;
    try {
      const q = xtrQ(source, at);
      if (q.content.startsWith('LOL!')) {
        out.push({
          index: at,
          text: q.content,
          decrypted: Buffer.from(q.content, 'latin1'),
          plain: true,
          end: q.end,
        });
      }
      from = q.end + 1;
    } catch {
      from = at + 5;
    }
  }
  return out;
}

function xtrBc(source) {
  const calls = findV7Calls(source);
  let payloads = calls
    .filter((c) => c.text.startsWith('LOL!'))
    .map((c) => ({
      index: c.index,
      text: c.text,
      decrypted: c.decrypted,
      plain: false,
      end: c.end,
    }));
  if (payloads.length === 0) {
    payloads = findPlnLol(source);
  }
  if (payloads.length === 0) {
    if (calls.length === 0) throw new Error('bc:no_v7');
    throw new Error('bc:no_lol');
  }
  const payload = payloads[payloads.length - 1];
  let sentinel = xtrRle(source);
  if (sentinel == null) sentinel = guessSent(payload.decrypted);
  const raw = decLol(payload.decrypted, sentinel);
  const reader = new Reader(raw);
  const root = desPr(reader);
  return {
    payload,
    raw,
    root,
    sentinel,
    bytesRead: reader.pos,
    bytesTotal: raw.length,
    xorCalls: calls.length,
  };
}


function hasWd(src, word) {
  let i = 0;
  while (i < src.length) {
    if (wdAt(src, i, word)) return true;
    i++;
  }
  return false;
}

function skStrCopy(src, i, out) {
  const q = src[i];
  out.push(q);
  i++;
  while (i < src.length && src[i] !== q) {
    if (src[i] === '\\') {
      out.push(src[i++]);
      if (i < src.length) out.push(src[i++]);
    } else {
      out.push(src[i++]);
    }
  }
  if (i < src.length) out.push(src[i++]);
  return i;
}

function findWdThen(src, from) {
  let i = from;
  while (i < src.length) {
    if (src[i] === '"' || src[i] === "'") {
      const q = src[i++];
      while (i < src.length && src[i] !== q) {
        if (src[i] === '\\') i++;
        i++;
      }
      i++;
      continue;
    }
    if (wdAt(src, i, 'then')) return i;
    i++;
  }
  return -1;
}

function stripPar(s) {
  let t = s.trim();
  while (t[0] === '(' && t[t.length - 1] === ')') {
    let depth = 0;
    let ok = true;
    for (let i = 0; i < t.length; i++) {
      if (t[i] === '"' || t[i] === "'") {
        const q = t[i++];
        while (i < t.length && t[i] !== q) {
          if (t[i] === '\\') i++;
          i++;
        }
        continue;
      }
      if (t[i] === '(') depth++;
      else if (t[i] === ')') {
        depth--;
        if (depth === 0 && i < t.length - 1) {
          ok = false;
          break;
        }
      }
    }
    if (!ok || depth !== 0) break;
    t = t.slice(1, -1).trim();
  }
  return t;
}

function simpCond(cond) {
  let t = stripPar(cond);
  let guard = 0;
  while (guard++ < 20) {
    const prev = t;
    t = stripPar(t);
    
    if (t.endsWith(' or false')) t = t.slice(0, -' or false'.length).trim();
    else if (t.endsWith(' and true')) t = t.slice(0, -' and true'.length).trim();
    else if (t.startsWith('false or ')) t = t.slice('false or '.length).trim();
    else if (t.startsWith('true and ')) t = t.slice('true and '.length).trim();
    else if (t.endsWith(' or true')) return { tautology: true };
    else if (t.startsWith('true or ')) return { tautology: true };
    else if (t.endsWith(' and false')) return { contradiction: true };
    else if (t.startsWith('false and ')) return { contradiction: true };
    if (t === prev) break;
  }
  return { text: stripPar(t) };
}

function rdStEq(cond, preferVar) {
  const simp = simpCond(cond);
  if (simp.tautology || simp.contradiction) return null;
  const text = simp.text || cond;
  let i = skWs(text, 0);

  const tryNumLeft = rdNum(text, i);
  if (tryNumLeft) {
    let j = skWs(text, tryNumLeft.end);
    if (text.slice(j, j + 2) !== '==') return null;
    j = skWs(text, j + 2);
    const id = rdId(text, j);
    if (!id || id.name[0] !== 'v' || !isDig(id.name[1] || '')) return null;
    if (preferVar && id.name !== preferVar) return null;
    
    j = skWs(text, id.end);
    if (j < text.length && text[j] === ')') j++;
    j = skWs(text, j);
    if (j < text.length) return null;
    return { stateVar: id.name, state: tryNumLeft.num };
  }

  const id = rdId(text, i);
  if (!id || id.name[0] !== 'v' || !isDig(id.name[1] || '')) return null;
  if (preferVar && id.name !== preferVar) return null;
  let j = skWs(text, id.end);
  if (text.slice(j, j + 2) !== '==') return null;
  j = skWs(text, j + 2);
  const num = rdNum(text, j);
  if (!num) return null;
  j = skWs(text, num.end);
  if (j < text.length && text[j] === ')') j++;
  j = skWs(text, j);
  if (j < text.length) return null;
  return { stateVar: id.name, state: num.num };
}

function rwNeEmpty(body) {
  
  let out = '';
  let i = 0;
  while (i < body.length) {
    if (body[i] === '"' || body[i] === "'") {
      const q = body[i++];
      out += q;
      while (i < body.length && body[i] !== q) {
        if (body[i] === '\\') {
          out += body[i++];
          if (i < body.length) out += body[i++];
        } else out += body[i++];
      }
      if (i < body.length) out += body[i++];
      continue;
    }
    if (wdAt(body, i, 'if')) {
      const thenAt = findWdThen(body, i + 2);
      if (thenAt >= 0) {
        const cond = body.slice(i + 2, thenAt).trim();
        const ne = rdStNe(cond);
        if (ne) {
          let j = skWs(body, thenAt + 4);
          if (wdAt(body, j, 'else')) {
            out += 'if (' + ne.stateVar + '==' + ne.state + ') then ';
            i = j + 4;
            continue;
          }
        }
      }
    }
    out += body[i++];
  }
  return out;
}

function rdStNe(cond) {
  const simp = simpCond(cond);
  if (!simp.text) return null;
  const text = simp.text;
  let i = skWs(text, 0);

  const tryNumLeft = rdNum(text, i);
  if (tryNumLeft) {
    let j = skWs(text, tryNumLeft.end);
    if (text.slice(j, j + 2) !== '~=') return null;
    j = skWs(text, j + 2);
    const id = rdId(text, j);
    if (!id || id.name[0] !== 'v' || !isDig(id.name[1] || '')) return null;
    j = skWs(text, id.end);
    if (j < text.length) return null;
    return { stateVar: id.name, state: tryNumLeft.num };
  }

  const id = rdId(text, i);
  if (!id || id.name[0] !== 'v' || !isDig(id.name[1] || '')) return null;
  let j = skWs(text, id.end);
  if (text.slice(j, j + 2) !== '~=') return null;
  j = skWs(text, j + 2);
  const num = rdNum(text, j);
  if (!num) return null;
  j = skWs(text, num.end);
  if (j < text.length) return null;
  return { stateVar: id.name, state: num.num };
}

function parseIfCh(body) {
  body = rwNeEmpty(body);
  const cases = new Map();
  let stateVar = null;
  let leadingLocals = '';
  let i = skWs(body, 0);

  while (i < body.length) {
    i = skWs(body, i);
    while (i < body.length && body[i] === ';') i = skWs(body, i + 1);
    if (i >= body.length) break;
    
    if (wdAt(body, i, 'local')) {
      const locStart = i;
      let j = skWs(body, i + 5);
      const id = rdId(body, j);
      if (id && id.name[0] === 'v' && isDig(id.name[1] || '')) {
        j = skWs(body, id.end);
        if (j >= body.length || body[j] === ';' || isWs(body[j])) {
          if (body[j] === ';') j++;
          const piece = body.slice(locStart, j).trim();
          if (piece) leadingLocals += piece + (piece.endsWith(';') ? ' ' : '; ');
          i = j;
          continue;
        }
      }
      return null;
    }
    if (!wdAt(body, i, 'if')) return null;

    const thenAt = findWdThen(body, i + 2);
    if (thenAt < 0) return null;
    const cond = body.slice(i + 2, thenAt).trim();
    const parsed = rdStEq(cond, stateVar);
    if (!parsed) return null;
    if (!stateVar) stateVar = parsed.stateVar;
    if (parsed.stateVar !== stateVar) return null;

    const endAfter = findBlkEnd(body, i);
    if (endAfter < 0) return null;
    const caseBody = body.slice(thenAt + 4, endAfter - 3).trim();
    if (cases.has(parsed.state)) return null;
    cases.set(parsed.state, caseBody);
    i = endAfter;
  }

  if (!stateVar || cases.size === 0) return null;
  return { stateVar, cases, leadingLocals };
}

function rdAsgNum(body, j) {
  j = skWs(body, j);
  const num = rdNum(body, j);
  if (num) return { state: num.num, end: num.end };
  
  const needle = '(function() return';
  if (body.startsWith(needle, j)) {
    let k = skWs(body, j + needle.length);
    const n = rdNum(body, k);
    if (!n) return null;
    k = skWs(body, n.end);
    if (body[k] === ';') k = skWs(body, k + 1);
    if (!body.startsWith('end)()', k)) return null;
    return { state: n.num, end: k + 6 };
  }
  return null;
}

function findStAsg(body, stateVar) {
  let last = null;
  let i = 0;
  while (i < body.length) {
    if (body[i] === '"' || body[i] === "'") {
      const q = body[i++];
      while (i < body.length && body[i] !== q) {
        if (body[i] === '\\') i++;
        i++;
      }
      i++;
      continue;
    }
    if (body.startsWith(stateVar, i)) {
      const after = i + stateVar.length;
      if (after < body.length && isId(body[after])) {
        i++;
        continue;
      }
      let j = skWs(body, after);
      if (body[j] === '=') {
        const rhs = rdAsgNum(body, j + 1);
        if (rhs) last = { state: rhs.state, start: i, end: rhs.end };
      }
    }
    i++;
  }
  return last;
}

function stripStN(body, stateVar) {
  const parts = [];
  let i = 0;
  while (i < body.length) {
    if (body[i] === '"' || body[i] === "'") {
      i = skStrCopy(body, i, parts);
      continue;
    }

    if (body.startsWith(stateVar, i)) {
      const after = i + stateVar.length;
      if (!(after < body.length && isId(body[after]))) {
        let j = skWs(body, after);
        if (body[j] === '=') {
          const rhs = rdAsgNum(body, j + 1);
          if (rhs) {
            j = rhs.end;
            if (body[j] === ';') j++;
            i = j;
            continue;
          }
        }
      }
    }

    if (wdAt(body, i, 'break')) {
      let j = i + 5;
      if (body[j] === ';') j++;
      i = j;
      continue;
    }

    parts.push(body[i++]);
  }

  let out = parts.join('');
  
  let cleaned = '';
  for (let k = 0; k < out.length; k++) {
    if (out[k] === ';' && cleaned.length && cleaned[cleaned.length - 1] === ';') continue;
    cleaned += out[k];
  }
  return cleaned.trim();
}

function linCff(cases, stateVar, init) {
  const parts = [];
  const seen = new Set();
  let state = init;
  let guard = 0;
  while (state != null && !seen.has(state) && guard++ < 64) {
    seen.add(state);
    const raw = cases.get(state);
    if (raw == null) break;
    const assign = findStAsg(raw, stateVar);
    const cleaned = stripStN(raw, stateVar);
    if (cleaned) parts.push(cleaned);
    if (!assign && (hasWd(raw, 'return') || hasWd(raw, 'break'))) break;
    state = assign ? assign.state : null;
  }
  if (!parts.length) return null;
  return parts.join(' ');
}

function onlyEmptyLoc(src, from, until) {
  let i = from;
  while (i < until) {
    i = skWs(src, i);
    if (i >= until) return true;
    if (src[i] === ';') {
      i++;
      continue;
    }
    if (!wdAt(src, i, 'local')) return false;
    let j = skWs(src, i + 5);
    const id = rdId(src, j);
    if (!id || id.name[0] !== 'v' || !isDig(id.name[1] || '')) return false;
    j = skWs(src, id.end);
    if (src[j] === '=' || src[j] === ',') return false;
    if (src[j] === ';') j++;
    i = j;
  }
  return true;
}

function findInit(src, whileAt, stateVar) {
  const from = Math.max(0, whileAt - 400);
  const window = src.slice(from, whileAt);
  let best = null;
  let j = 0;
  while (j < window.length) {
    const at = window.indexOf(stateVar, j);
    if (at < 0) break;
    const abs = from + at;
    const after = at + stateVar.length;
    if (after < window.length && isId(window[after])) {
      j = at + 1;
      continue;
    }
    let k = skWs(window, after);
    if (window[k] === '=') {
      k = skWs(window, k + 1);
      const num = rdNum(window, k);
      if (num) {
        const assignEnd = from + num.end;
        if (onlyEmptyLoc(src, assignEnd, whileAt)) {
          let start = abs;
          const loc = src.lastIndexOf('local', abs);
          if (loc >= 0 && loc >= abs - 12 && wdAt(src, loc, 'local')) {
            start = loc;
          }
          best = { init: num.num, start, end: assignEnd };
        }
      }
    }
    j = at + 1;
  }
  return best;
}

function colEmptyLoc(src, from, until) {
  let prefix = '';
  let i = from;
  while (i < until) {
    i = skWs(src, i);
    if (i >= until) break;
    if (src[i] === ';') {
      i++;
      continue;
    }
    if (wdAt(src, i, 'local')) {
      const locStart = i;
      let j = skWs(src, i + 5);
      const id = rdId(src, j);
      if (!id) break;
      j = skWs(src, id.end);
      if (src[j] === '=') break;
      if (src[j] === ',' ) break;
      if (src[j] === ';') j++;
      const piece = src.slice(locStart, j).trim();
      if (piece) prefix += piece + (piece.endsWith(';') ? ' ' : '; ');
      i = j;
      continue;
    }
    break;
  }
  return prefix;
}

function tryUnflat(src, whileAt) {
  if (!src.startsWith('while true do', whileAt)) return null;
  const endAt = findBlkEnd(src, whileAt);
  if (endAt < 0) return null;

  const body = src.slice(whileAt + 13, endAt - 3);
  
  

  const parsed = parseIfCh(body);
  if (!parsed) return null;

  const initInfo = findInit(src, whileAt, parsed.stateVar);
  const init = initInfo ? initInfo.init : Math.min(...parsed.cases.keys());
  const entry = parsed.cases.has(init) ? init : Math.min(...parsed.cases.keys());
  const lin = linCff(parsed.cases, parsed.stateVar, entry);
  if (!lin) return null;

  const start = initInfo ? initInfo.start : whileAt;
  let prefix = '';
  if (initInfo) prefix = colEmptyLoc(src, initInfo.end, whileAt);
  if (parsed.leadingLocals) prefix += parsed.leadingLocals;

  return {
    start,
    end: endAt,
    code: (prefix + lin).trim(),
    stateVar: parsed.stateVar,
    states: parsed.cases.size,
  };
}

function cntOcc(src, needle) {
  let n = 0;
  let i = 0;
  while (i < src.length) {
    const at = src.indexOf(needle, i);
    if (at < 0) break;
    n++;
    i = at + needle.length;
  }
  return n;
}

function unflatCff(source) {
  let src = foldConst(String(source));
  let replaced = 0;
  let statesTotal = 0;
  let guard = 0;

  while (guard++ < 800) {
    let from = src.length;
    let hit = null;
    while (from > 0) {
      const at = src.lastIndexOf('while true do', from - 1);
      if (at < 0) break;
      const trial = tryUnflat(src, at);
      if (trial) {
        hit = trial;
        break;
      }
      from = at;
    }
    if (!hit) break;
    src = src.slice(0, hit.start) + hit.code + src.slice(hit.end);
    replaced++;
    statesTotal += hit.states;
  }

  return {
    source: src,
    replaced,
    statesTotal,
    remaining: cntOcc(src, 'while true do'),
  };
}


function cntWhile(src) {
  return cntOcc(src, 'while true do');
}

function cntState(src) {
  let n = 0;
  let i = 0;
  while (i < src.length) {
    const at = src.indexOf('local v', i);
    if (at < 0) break;
    let j = at + 7;
    while (j < src.length && src[j] >= '0' && src[j] <= '9') j++;
    if (src[j] === '=' && src[j + 1] >= '0' && src[j + 1] <= '9') n++;
    i = at + 7;
  }
  return n;
}

function cntOpaque(src) {
  
  let n = 0;
  for (let i = 0; i < src.length - 4; i++) {
    if (src[i] !== '(') continue;
    let j = i + 1;
    if (src[j] < '0' || src[j] > '9') continue;
    while (j < src.length && src[j] >= '0' && src[j] <= '9') j++;
    if (src.slice(j, j + 2) !== '==') continue;
    j += 2;
    const start = j;
    while (j < src.length && src[j] >= '0' && src[j] <= '9') j++;
    if (j > start && src[j] === ')') n++;
  }
  return n;
}

function invProt(source, extras = {}) {
  const src = String(source);
  const layers = [];

  const whileTrue = cntWhile(src);
  const states = cntState(src);
  const opaque = cntOpaque(src);

  if (src.includes('bxor') || src.includes('function v7(') || src.includes('local function v7(')) {
    layers.push({ id: 'xor' });
  }
  if (src.includes('LOL!') || src.includes('math.ldexp') || src.includes('ldexp')) {
    layers.push({ id: 'vm' });
  }
  if (extras.wrapperCff && extras.wrapperCff.replaced > 0) {
    const w = extras.wrapperCff;
    layers.push({
      id: 'cff',
      status: w.remaining <= 1 ? 'ok' : 'partial',
      metrics: { whileTrue, states, ...w },
    });
  } else if (whileTrue >= 3 || states >= 5) {
    layers.push({ id: 'cff', status: 'seen', metrics: { whileTrue, states } });
  }
  if (opaque > 0) {
    layers.push({ id: 'opaque', metrics: { opaque } });
  }
  if (src.includes('getfenv') || src.includes('setmetatable')) {
    layers.push({ id: 'env' });
  }
  if (extras.bytecodeCff && extras.bytecodeCff.removed > 0) {
    layers.push({ id: 'bc_cff', metrics: extras.bytecodeCff });
  } else if (extras.bytecodeCff && extras.bytecodeCff.jmps > 0) {
    layers.push({ id: 'bc_jmp', metrics: extras.bytecodeCff });
  }

  return {
    layers,
    metrics: { whileTrue, states, opaque },
  };
}


function findPln(src, word, from = 0) {
  let i = from;
  while (i < src.length) {
    const at = src.indexOf(word, i);
    if (at < 0) return -1;
    if (wdAt(src, at, word)) return at;
    i = at + 1;
  }
  return -1;
}

function parseVer(src) {
  let alphaAt = 0;
  while ((alphaAt = src.indexOf('Alpha ', alphaAt)) >= 0) {
    const ver = src.slice(alphaAt + 6, alphaAt + 20);
    if (ver[0] === '0' && ver[1] === '.') {
      let i = 2;
      while (i < ver.length && isDig(ver[i])) i++;
      if (ver[i] === '.') {
        i++;
        const start = i;
        while (i < ver.length && isDig(ver[i])) i++;
        if (i > start) return ver.slice(0, i);
      }
    }
    alphaAt += 6;
  }
  return null;
}

function hasWrap(src) {
  let from = 0;
  while (from < src.length) {
    const at = findPln(src, 'return', from);
    if (at < 0) return false;
    let j = skWs(src, at + 6);
    const a = rdId(src, j);
    if (a && src[a.end] === '(') {
      j = skWs(src, a.end + 1);
      const b = rdId(src, j);
      if (b && src.slice(b.end, b.end + 2) === '()') {
        j = skWs(src, b.end + 2);
        if (src[j] === ',') {
          j = skWs(src, j + 1);
          if (src.slice(j, j + 2) === '{}') return true;
        }
      }
    }
    from = at + 6;
  }
  return false;
}

function hasOpUnpk(src) {
  let from = 0;
  while (from < src.length) {
    const at = src.indexOf('[1]', from);
    if (at < 0) return false;
    let i = at - 1;
    while (i >= 0 && isWs(src[i])) i--;
    if (i < 0 || !isId(src[i])) {
      from = at + 3;
      continue;
    }
    while (i >= 0 && isId(src[i])) i--;
    const inst = src.slice(i + 1, at);
    if (!inst || inst[0] !== 'v') {
      from = at + 3;
      continue;
    }
    const window = src.slice(at, at + 280);
    if (!window.includes('[2]')) {
      from = at + 3;
      continue;
    }
    if (window.includes('[3]')) return true;
    const needle = inst + '[';
    let hits = 1;
    let pos = 0;
    while (hits < 3) {
      const p = window.indexOf(needle, pos);
      if (p < 0) break;
      hits++;
      pos = p + needle.length;
    }
    if (hits >= 3) return true;
    from = at + 3;
  }
  return false;
}

function hasOpTree(src) {
  let hits = 0;
  let from = 0;
  while (from < src.length && hits < 3) {
    const at = src.indexOf('<=', from);
    if (at < 0) break;
    let i = at - 1;
    while (i >= 0 && isWs(src[i])) i--;
    while (i >= 0 && isId(src[i])) i--;
    const left = src.slice(i + 1, at).trim();
    if (left[0] === 'v' && isDig(left[1] || '')) {
      let j = skWs(src, at + 2);
      if (isDig(src[j])) hits++;
    }
    from = at + 2;
  }
  return hits >= 3;
}

function hasVmLoop(src) {
  let from = 0;
  while (from < src.length) {
    const at = src.indexOf('while true do', from);
    if (at < 0) return false;
    const window = src.slice(at, at + 1200);
    let fetch = false;
    let tree = false;
    for (let k = 0; k < window.length; k++) {
      const id = rdId(window, k);
      if (!id || id.name[0] !== 'v' || !isDig(id.name[1] || '')) continue;
      let j = skWs(window, id.end);
      if (window[j] !== '=') continue;
      j = skWs(window, j + 1);
      const r = rdId(window, j);
      if (!r || window[r.end] !== '[') continue;
      const inn = rdId(window, r.end + 1);
      if (inn && window[inn.end] === ']') fetch = true;
    }
    let le = 0;
    let p = 0;
    while ((p = window.indexOf('<=', p)) >= 0) {
      le++;
      p += 2;
    }
    if (le >= 2) tree = true;
    if (fetch && tree) return true;
    from = at + 13;
  }
  return false;
}

function findLol(src) {
  const tryFn = (fn) => {
    try {
      const calls = fn === 'v7' ? findV7Calls(src) : findDec(src, fn);
      for (const c of calls) {
        if (c.text.startsWith('LOL!')) {
          return { found: true, fn, preview: c.text.slice(0, 24), plain: false };
        }
      }
    } catch {
    }
    return null;
  };
  let hit = tryFn('v7');
  if (hit) return hit;
  const xorNm = findXorNm(src);
  if (xorNm && xorNm !== 'v7') {
    hit = tryFn(xorNm);
    if (hit) return hit;
  }
  const at = src.indexOf('"LOL!');
  if (at >= 0) {
    return { found: true, fn: null, preview: src.slice(at + 1, at + 25), plain: true };
  }
  return { found: false };
}

function hasXorBod(body) {
  const keyMix = body.includes('% #') || body.includes('%#');
  const xorUse = body.includes('bxor') || keyMix;
  const mod256 = body.includes('%256')
    || body.includes('% 256')
    || body.includes('%(256')
    || (body.includes('%(') && (body.includes('256') || body.includes('150') || body.includes('106')));
  const charPipe = body.includes('v0(') || body.includes('char') || mod256;
  return xorUse && (mod256 || (keyMix && charPipe));
}

function findXorNm(src) {
  let from = 0;
  while (from < src.length) {
    const at = src.indexOf('function', from);
    if (at < 0) return null;
    if (!wdAt(src, at, 'function')) {
      from = at + 8;
      continue;
    }
    let j = skWs(src, at + 8);
    const name = rdId(src, j);
    if (!name || src[name.end] !== '(') {
      from = at + 8;
      continue;
    }
    const close = src.indexOf(')', name.end);
    if (close < 0) return null;
    let depth = 1;
    let k = close + 1;
    const begin = k;
    while (k < src.length && depth > 0) {
      if (src[k] === '"' || src[k] === "'") {
        const q = src[k++];
        while (k < src.length && src[k] !== q) {
          if (src[k] === '\\') k++;
          k++;
        }
        k++;
        continue;
      }
      if (wdAt(src, k, 'function') || wdAt(src, k, 'then') || wdAt(src, k, 'do') || wdAt(src, k, 'repeat')) {
        depth++;
        const id = rdId(src, k);
        k = id ? id.end : k + 1;
        continue;
      }
      if (wdAt(src, k, 'end')) {
        depth--;
        if (depth === 0) {
          const body = src.slice(begin, k);
          if (hasXorBod(body)) return name.name;
          break;
        }
        k += 3;
        continue;
      }
      k++;
    }
    from = at + 8;
  }
  return null;
}

function findBoot(src) {
  const need = [
    'string.char',
    'string.byte',
    'string.sub',
    'bit32 or bit',
    '.bxor',
    'table.concat',
    'table.insert',
  ];
  let from = 0;
  while (from < src.length) {
    const anchor = src.indexOf('string.char', from);
    if (anchor < 0) return null;
    let pos = anchor;
    let ok = true;
    for (const token of need) {
      const at = src.indexOf(token, pos);
      if (at < 0 || at > anchor + 500) {
        ok = false;
        break;
      }
      pos = at + token.length;
    }
    if (!ok) {
      from = anchor + 11;
      continue;
    }
    const tail = src.slice(pos, pos + 80);
    const fnAt = tail.indexOf('function');
    if (fnAt < 0) {
      from = anchor + 11;
      continue;
    }
    return { start: anchor, afterAliases: pos };
  }
  return null;
}

function hasFnV(slice) {
  let from = 0;
  while (from < slice.length) {
    const at = slice.indexOf('function', from);
    if (at < 0) return false;
    if (!wdAt(slice, at, 'function')) {
      from = at + 8;
      continue;
    }
    let j = skWs(slice, at + 8);
    if (slice[j] === 'v' && isDig(slice[j + 1] || '')) {
      while (j < slice.length && isDig(slice[j])) j++;
      j = skWs(slice, j);
      if (slice[j] === '(') return true;
    }
    from = at + 8;
  }
  return false;
}

function hasBoot(src) {
  const boot = findBoot(src);
  if (!boot) return false;
  const fn = findXorNm(src);
  if (fn) return true;
  const slice = src.slice(boot.afterAliases, boot.afterAliases + 2500);
  if (!hasFnV(slice)) return false;
  return hasXorBod(slice);
}

function stripTail(src) {
  let t = String(src).trimEnd();
  let guard = 0;
  while (guard++ < 20 && t.length) {
    t = t.trimEnd();
    const nl = t.lastIndexOf('\n');
    const line = (nl < 0 ? t : t.slice(nl + 1)).trim();
    if (line.startsWith('--') && !line.includes('[[') && !line.includes(']]')) {
      t = nl < 0 ? '' : t.slice(0, nl);
      continue;
    }
    if (t.endsWith(']]--')) {
      const open = t.lastIndexOf('--[[');
      if (open >= 0) {
        t = t.slice(0, open);
        continue;
      }
    }
    if (t.endsWith(']]')) {
      const open = t.lastIndexOf('--[[');
      if (open >= 0) {
        t = t.slice(0, open);
        continue;
      }
    }
    break;
  }
  return t.trimEnd();
}

function scanBlk(src) {
  let depth = 0;
  let max = 0;
  let i = 0;
  let inStr = null;
  while (i < src.length) {
    const ch = src[i];
    if (inStr) {
      if (ch === '\\') {
        i += 2;
        continue;
      }
      if (ch === inStr) inStr = null;
      i++;
      continue;
    }
    if (ch === '"' || ch === "'") {
      inStr = ch;
      i++;
      continue;
    }
    if (ch === '[' && (src[i + 1] === '[' || src[i + 1] === '=')) {
      let j = i + 1;
      let eq = 0;
      while (src[j] === '=') {
        eq++;
        j++;
      }
      if (src[j] === '[') {
        const close = ']' + '='.repeat(eq) + ']';
        const at = src.indexOf(close, j + 1);
        i = at < 0 ? src.length : at + close.length;
        continue;
      }
    }
    if (ch === '-' && src[i + 1] === '-') {
      if (src[i + 2] === '[') {
        let j = i + 3;
        let eq = 0;
        while (src[j] === '=') {
          eq++;
          j++;
        }
        if (src[j] === '[') {
          const close = ']' + '='.repeat(eq) + ']';
          const at = src.indexOf(close, j + 1);
          i = at < 0 ? src.length : at + close.length;
          continue;
        }
      }
      while (i < src.length && src[i] !== '\n') i++;
      continue;
    }
    if (wdAt(src, i, 'function') || wdAt(src, i, 'then') || wdAt(src, i, 'do') || wdAt(src, i, 'repeat')) {
      depth++;
      if (depth > max) max = depth;
      const id = rdId(src, i);
      i = id ? id.end : i + 1;
      continue;
    }
    if (wdAt(src, i, 'end')) {
      depth--;
      i += 3;
      continue;
    }
    i++;
  }
  return { depth, max, openStr: !!inStr };
}

function isTrunc(src) {
  const t = stripTail(src);
  if (!t.length) return { bad: true, reason: 'empty_source' };
  const bal = scanBlk(t);
  const last = t[t.length - 1];
  const okEnd = last === ')' || last === ';' || last === '}' || last === 'd' || last === ']';

  if (last === ',' || last === '=' || last === '(' || last === '[' || last === '{' || last === '.' || last === '+' || last === '*' || last === '/' || last === '%' || last === '^' || last === '#') {
    return { bad: true, reason: 'ends_mid_expr' };
  }
  if (last === '-' && !t.endsWith('end')) {
    return { bad: true, reason: 'ends_mid_expr' };
  }

  let i = t.length - 1;
  while (i >= 0 && (t[i] === ' ' || t[i] === '\t' || t[i] === '\n' || t[i] === '\r')) i--;
  let j = i;
  while (j >= 0 && isId(t[j])) j--;
  const tailId = t.slice(j + 1, i + 1);
  if (tailId.length && j >= 0 && t[j] === ',') {
    return { bad: true, reason: 'ends_mid_list' };
  }
  if (tailId === 'v' || (tailId[0] === 'v' && isDig(tailId[1] || '') && j >= 0 && (t[j] === ',' || t[j] === '='))) {
    const before = t.slice(Math.max(0, t.length - 60));
    if (before.includes('for ')) return { bad: true, reason: 'ends_mid_for' };
  }

  if (bal.openStr && !okEnd) return { bad: true, reason: 'unclosed_string' };

  if (bal.depth > 0 && bal.depth === bal.max && bal.max >= 20 && !okEnd) {
    return { bad: true, reason: 'unclosed_blocks' };
  }

  if (!okEnd) return { bad: true, reason: 'bad_tail' };

  return { bad: false, reason: null, bal };
}

function valFam(src, family, bits) {
  const trunc = isTrunc(src);
  if (trunc.bad) {
    return { ok: false, reason: 'invalid_syntax:' + trunc.reason };
  }

  if (family === 'luaobfuscator-chaotic-evil') {
    if (!bits.lol && !bits.wrap) {
      return { ok: false, reason: 'incomplete_evil:missing_lol_or_wrap' };
    }
    if (!bits.ldexp && !bits.lol) {
      return { ok: false, reason: 'incomplete_evil:missing_vm_shape' };
    }
    // Alpha 0.10.9+ builds do bit ops arithmetically (no bxor): LOL! + ldexp is a sufficient VM signature.
    if (!(bits.bootstrap || bits.xorFn || bits.hasXor || (bits.lol && bits.ldexp))) {
      return { ok: false, reason: 'incomplete_evil:missing_xor_bootstrap' };
    }
    return { ok: true, reason: null };
  }

  if (family === 'luaobfuscator-chaotic-good') {
    if (!bits.bootstrap) {
      return { ok: false, reason: 'incomplete_good:missing_bootstrap' };
    }
    if (!bits.xorFn && !bits.hasXor) {
      return { ok: false, reason: 'incomplete_good:missing_xor' };
    }
    if (bits.ldexp) {
      return { ok: false, reason: 'invalid_good:vm_double_reader' };
    }
    return { ok: true, reason: null };
  }

  return { ok: false, reason: 'unknown_family' };
}

function det(source) {
  const src = String(source);
  const signals = [];

  const lol = findLol(src);
  const wrap = hasWrap(src);
  const ldexp = src.includes('math.ldexp') || (src.includes('ldexp') && src.includes('math'));
  const unpack = hasOpUnpk(src);
  const tree = hasOpTree(src);
  const loop = hasVmLoop(src);
  const watermark = src.includes('LuaObfuscator.com')
    || src.includes('Much Love, Ferib')
    || src.includes('Much Love,Ferib');
  const version = parseVer(src);
  const xorFn = findXorNm(src);
  const bootstrap = hasBoot(src);
  const hasXor = src.includes('bxor') && (src.includes('bit32') || src.includes('string.char'));

  if (lol.found) signals.push('lol_bytecode');
  if (wrap) signals.push('vm_wrap_return');
  if (ldexp) signals.push('double_reader');
  if (unpack) signals.push('opcode_unpack');
  if (tree) signals.push('opcode_tree');
  if (loop) signals.push('vm_dispatch');
  if (watermark) signals.push('ferib_watermark');
  if (version) signals.push('alpha_version');
  if (xorFn) signals.push('xor_fn:' + xorFn);
  if (bootstrap) signals.push('good_bootstrap');
  if (hasXor) signals.push('xor_decrypt');

  const opcodeScore = (unpack ? 1 : 0) + (tree ? 1 : 0) + (loop ? 1 : 0) + (ldexp ? 1 : 0);
  const bits = {
    lol: lol.found,
    wrap,
    ldexp,
    unpack,
    tree,
    loop,
    bootstrap,
    xorFn,
    hasXor,
    opcodeScore,
  };

  let family = null;
  if (lol.found || (wrap && opcodeScore >= 2) || (wrap && ldexp && unpack)) {
    family = 'luaobfuscator-chaotic-evil';
  } else if (ldexp && (tree || loop)) {
    family = 'luaobfuscator-chaotic-evil';
  } else if (bootstrap && !lol.found && !wrap && !ldexp) {
    family = 'luaobfuscator-chaotic-good';
  }

  const candidate = family;
  let reason = null;
  let valid = false;
  if (!family) {
    reason = 'not_luaobfuscator';
  } else {
    const v = valFam(src, family, bits);
    valid = v.ok;
    reason = v.reason;
    if (!valid) family = null;
  }

  const matched = valid && !!family;

  return {
    matched,
    family: matched ? family : null,
    candidate: matched ? family : candidate,
    valid,
    reason,
    version,
    score: signals.length,
    signals,
    lol: lol.found ? { fn: lol.fn, preview: lol.preview } : null,
    opcodes: matched && family === 'luaobfuscator-chaotic-evil'
      ? { unpack, tree, loop, ldexp, wrap }
      : null,
    format: matched && family === 'luaobfuscator-chaotic-good'
      ? { bootstrap: true, xorFn }
      : null,
  };
}


function stripWm(src) {
  const s = String(src);
  const out = [];
  let i = 0;
  while (i < s.length) {
    const ch = s[i];

    if (ch === '"' || ch === "'") {
      const q = ch;
      out.push(q);
      i++;
      while (i < s.length && s[i] !== q) {
        if (s[i] === '\\') {
          out.push(s[i++]);
          if (i < s.length) out.push(s[i++]);
        } else {
          out.push(s[i++]);
        }
      }
      if (i < s.length) out.push(s[i++]);
      continue;
    }

    if (ch === '[') {
      let j = i + 1;
      let eq = 0;
      while (s[j] === '=') {
        eq++;
        j++;
      }
      if (s[j] === '[') {
        const close = ']' + '='.repeat(eq) + ']';
        const at = s.indexOf(close, j + 1);
        if (at < 0) {
          out.push(s.slice(i));
          break;
        }
        out.push(s.slice(i, at + close.length));
        i = at + close.length;
        continue;
      }
    }

    if (ch === '-' && s[i + 1] === '-') {
      if (s[i + 2] === '[') {
        let j = i + 3;
        let eq = 0;
        while (s[j] === '=') {
          eq++;
          j++;
        }
        if (s[j] === '[') {
          const close = ']' + '='.repeat(eq) + ']';
          const at = s.indexOf(close, j + 1);
          i = at < 0 ? s.length : at + close.length;
          continue;
        }
      }
      i += 2;
      while (i < s.length && s[i] !== '\n') i++;
      continue;
    }

    out.push(ch);
    i++;
  }
  return out.join('');
}

function findXor(src) {
  let from = 0;
  while (from < src.length) {
    const at = src.indexOf('function', from);
    if (at < 0) break;
    if (!wdAt(src, at, 'function')) {
      from = at + 8;
      continue;
    }
    let j = skWs(src, at + 8);
    const name = rdId(src, j);
    if (!name || src[name.end] !== '(') {
      from = at + 8;
      continue;
    }
    const bodyStart = src.indexOf(')', name.end);
    if (bodyStart < 0) break;
    const endAt = findEnd(src, bodyStart + 1);
    if (endAt < 0) {
      from = at + 8;
      continue;
    }
    const body = src.slice(bodyStart + 1, endAt);
    if (
      body.includes('%256')
      || body.includes('bxor')
      || (body.includes('char') && body.includes('byte'))
    ) {
      let declStart = at;
      let k = at;
      while (k > 0 && isWs(src[k - 1])) k--;
      if (k >= 5 && wdAt(src, k - 5, 'local')) declStart = k - 5;
      return { name: name.name, start: declStart, end: endAt + 3 };
    }
    from = at + 8;
  }
  return null;
}

function findEnd(src, from) {
  let depth = 1;
  let i = from;
  while (i < src.length) {
    if (src[i] === '"' || src[i] === "'") {
      const q = src[i++];
      while (i < src.length && src[i] !== q) {
        if (src[i] === '\\') i++;
        i++;
      }
      i++;
      continue;
    }
    if (src[i] === '-' && src[i + 1] === '-') {
      if (src[i + 2] === '[') {
        let j = i + 3;
        let eq = 0;
        while (src[j] === '=') {
          eq++;
          j++;
        }
        if (src[j] === '[') {
          const close = ']' + '='.repeat(eq) + ']';
          const at = src.indexOf(close, j + 1);
          i = at < 0 ? src.length : at + close.length;
          continue;
        }
      }
      while (i < src.length && src[i] !== '\n') i++;
      continue;
    }
    if (wdAt(src, i, 'function') || wdAt(src, i, 'then') || wdAt(src, i, 'do') || wdAt(src, i, 'repeat')) {
      const id = rdId(src, i);
      depth++;
      i = id ? id.end : i + 1;
      continue;
    }
    if (wdAt(src, i, 'end')) {
      depth--;
      if (depth === 0) return i;
      i += 3;
      continue;
    }
    i++;
  }
  return -1;
}

function isXorAlias(path) {
  if (path === 'bit32' || path === 'bit') return true;
  if (path.endsWith('.bxor')) return true;
  const dot = path.indexOf('.');
  if (dot <= 0) return false;
  const lib = path.slice(0, dot);
  return lib === 'string' || lib === 'table';
}

function stripXorBoot(src, fnName) {
  let out = src;
  const fn = findXor(out);
  let limit = out.length;
  if (fn && (!fnName || fn.name === fnName)) {
    limit = fn.start;
    out = out.slice(0, fn.start) + out.slice(fn.end);
  } else {
    limit = Math.min(out.length, 1200);
  }

  let guard = 0;
  while (guard++ < 20) {
    let changed = false;
    let i = 0;
    while (i < out.length && i < limit) {
      if (!wdAt(out, i, 'local')) {
        i++;
        continue;
      }
      const start = i;
      let j = skWs(out, i + 5);
      const name = rdId(out, j);
      if (!name) {
        i++;
        continue;
      }
      j = skWs(out, name.end);
      if (out[j] !== '=') {
        i = name.end;
        continue;
      }
      j = skSp(out, j + 1);
      if (out.startsWith('bit32 or bit', j) || out.startsWith('bit or bit32', j)) {
        let end = j + 12;
        while (end < out.length && out[end] !== ';') end++;
        if (out[end] === ';') end++;
        const rem = end - start;
        out = out.slice(0, start) + out.slice(end);
        limit = Math.max(0, limit - rem);
        changed = true;
        break;
      }
      const rhs = rdId(out, j);
      if (!rhs) {
        i = name.end;
        continue;
      }
      let k = rhs.end;
      let path = rhs.name;
      while (out[k] === '.') {
        const part = rdId(out, k + 1);
        if (!part) break;
        path += '.' + part.name;
        k = part.end;
      }
      if (isXorAlias(path)) {
        let end = k;
        while (end < out.length && out[end] !== ';') end++;
        if (out[end] === ';') end++;
        const rem = end - start;
        out = out.slice(0, start) + out.slice(end);
        limit = Math.max(0, limit - rem);
        changed = true;
        break;
      }
      i = name.end;
    }
    if (!changed) break;
  }

  return out;
}

function cleanNoise(src) {
  let out = '';
  let i = 0;
  while (i < src.length) {
    if (src[i] === '"' || src[i] === "'") {
      const q = src[i++];
      out += q;
      while (i < src.length && src[i] !== q) {
        if (src[i] === '\\') {
          out += src[i++];
          if (i < src.length) out += src[i++];
        } else out += src[i++];
      }
      if (i < src.length) out += src[i++];
      continue;
    }
    if (src[i] === ';' && src[i + 1] === ';') {
      out += ';';
      i += 2;
      while (src[i] === ';') i++;
      continue;
    }
    if (src[i] === ' ' && src[i + 1] === ' ') {
      out += ' ';
      i++;
      while (src[i] === ' ') i++;
      continue;
    }
    if (src[i] === ',' && src[i + 1] === ' ') {
      out += ', ';
      i += 2;
      while (src[i] === ' ') i++;
      continue;
    }
    out += src[i++];
  }
  return tidySp(out);
}

function tidySp(src) {
  let out = '';
  for (let i = 0; i < src.length; i++) {
    const ch = src[i];
    const n = src[i + 1];
    if (ch === ' ' && (n === ';' || n === ',' || n === ')' || n === '}' || n === '\n')) continue;
    if ((ch === '(' || ch === '{' ) && n === ' ') {
      out += ch;
      while (src[i + 1] === ' ') i++;
      continue;
    }
    if (ch === ';' && n === ';') continue;
    out += ch;
  }
  return out.trim();
}

function isFmtOpen(name) {
  return name === 'then' || name === 'do' || name === 'repeat' || name === 'else';
}

function fmtLua(src) {
  let out = '';
  let ind = 0;
  let i = 0;
  let line = '';

  function flush() {
    const t = line.trimEnd();
    if (t.length) out += '  '.repeat(Math.max(0, ind)) + t.trimStart() + '\n';
    line = '';
  }

  function skStr() {
    const q = src[i++];
    line += q;
    while (i < src.length && src[i] !== q) {
      if (src[i] === '\\') {
        line += src[i++];
        if (i < src.length) line += src[i++];
      } else line += src[i++];
    }
    if (i < src.length) line += src[i++];
  }

  function copyPar() {
    if (src[i] !== '(') return false;
    let depth = 0;
    while (i < src.length) {
      if (src[i] === '"' || src[i] === "'") {
        skStr();
        continue;
      }
      if (src[i] === '(') depth++;
      if (src[i] === ')') {
        depth--;
        line += src[i++];
        if (depth === 0) return true;
        continue;
      }
      line += src[i++];
    }
    return false;
  }

  while (i < src.length) {
    if (src[i] === '"' || src[i] === "'") {
      skStr();
      continue;
    }
    if (src[i] === '-' && src[i + 1] === '-') {
      flush();
      let j = i;
      if (src[j + 2] === '[') {
        let k = j + 3;
        let eq = 0;
        while (src[k] === '=') {
          eq++;
          k++;
        }
        if (src[k] === '[') {
          const close = ']' + '='.repeat(eq) + ']';
          const at = src.indexOf(close, k + 1);
          j = at < 0 ? src.length : at + close.length;
          out += src.slice(i, j) + '\n';
          i = j;
          continue;
        }
      }
      while (j < src.length && src[j] !== '\n') j++;
      out += src.slice(i, j) + '\n';
      i = j + (src[j] === '\n' ? 1 : 0);
      continue;
    }

    const id = rdId(src, i);
    if (id) {
      if (id.name === 'elseif' || id.name === 'else') {
        ind = Math.max(0, ind - 1);
        flush();
        line += id.name;
        i = id.end;
        if (id.name === 'else') {
          flush();
          ind++;
        }
        continue;
      }
      if (id.name === 'end' || id.name === 'until') {
        ind = Math.max(0, ind - 1);
        flush();
        line += id.name;
        i = id.end;
        flush();
        continue;
      }
      if (id.name === 'function') {
        line += 'function';
        i = id.end;
        while (i < src.length && isWs(src[i])) {
          line += src[i++];
        }
        const name = rdId(src, i);
        if (name) {
          line += name.name;
          i = name.end;
          while (i < src.length && isWs(src[i])) line += src[i++];
        }
        if (src[i] === '(') {
          copyPar();
          flush();
          ind++;
        }
        continue;
      }
      line += id.name;
      i = id.end;
      if (isFmtOpen(id.name)) {
        flush();
        ind++;
      }
      continue;
    }

    if (src[i] === ';') {
      i++;
      flush();
      continue;
    }
    if (src[i] === '\n') {
      flush();
      i++;
      continue;
    }
    line += src[i++];
  }
  flush();
  return colBlank(out);
}

function colBlank(src) {
  let out = '';
  let nl = 0;
  for (let i = 0; i < src.length; i++) {
    const ch = src[i];
    if (ch === '\n') {
      nl++;
      if (nl <= 2) out += ch;
    } else {
      nl = 0;
      out += ch;
    }
  }
  return out.trim() + '\n';
}

function deobfGd(source) {
  let src = stripWm(String(source));
  const xor = findXor(src);
  const fnName = xor ? xor.name : 'v7';

  const outer = fnName === 'v7'
    ? decOuter(src)
    : findDec(src, fnName).map((c) => ({
      index: c.index,
      decrypted: c.text,
      kind: 'outer_v7',
    }));

  let rewritten;
  if (fnName === 'v7') {
    rewritten = rwOuter(src, fnName);
  } else {
    const calls = [...findDec(src, fnName)].sort((a, b) => b.index - a.index);
    let text = src;
    let replaced = 0;
    for (const call of calls) {
      text = text.slice(0, call.index) + JSON.stringify(call.text) + text.slice(call.end + 1);
      replaced++;
    }
    rewritten = { source: text, replaced };
  }

  const cff1 = unflatCff(rewritten.source);
  const folded = foldConst(cff1.source);
  const cff2 = unflatCff(folded);
  let cleaned = stripXorBoot(cff2.source, fnName);
  cleaned = foldConst(cleaned);
  cleaned = cleanNoise(cleaned);
  cleaned = stripXorBoot(cleaned, fnName);
  cleaned = stripWm(cleaned);
  const lua = fmtLua(cleaned);

  return {
    family: 'luaobfuscator-chaotic-good',
    strings: {
      outer,
      summary: { outerCount: outer.length, outerReplaced: rewritten.replaced },
    },
    wrapperCff: {
      replaced: cff1.replaced + cff2.replaced,
      statesTotal: cff1.statesTotal + cff2.statesTotal,
      remaining: cff2.remaining,
    },
    lua,
    reconstructed: lua,
  };
}


module.exports = {
  det,
  xtrBc,
  decAllStr,
  invProt,
  unflatCff,
  deobfGd,
  foldConst,
  findBlkEnd,
  evalOk,
  skStr,
  nextKw,
  skWs,
  rdId,
  rdNum,
  isDig,
  isWs,
  isId0,
  wdAt,
  findWd,
  strWs,
  colWs,
};
