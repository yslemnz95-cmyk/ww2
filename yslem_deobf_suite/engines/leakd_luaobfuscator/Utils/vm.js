const { foldConst, findBlkEnd, evalOk, skStr, nextKw, skWs, rdId, rdNum, isDig, isWs, isId0, wdAt, findWd, strWs, colWs } = require('./io');

function rdVar(s, i) {
  if (s[i] !== 'v' || !isDig(s[i + 1] || '')) return null;
  let j = i + 1;
  while (j < s.length && isDig(s[j])) j++;
  return { name: s.slice(i, j), end: j };
}

function stripN(body) {
  const src = foldConst(String(body));
  let out = '';
  let i = 0;
  while (i < src.length) {
    if (wdAt(src, i, 'local')) {
      let j = skWs(src, i + 5);
      const id = rdId(src, j);
      if (id && id.name[0] === 'v' && isDig(id.name[1] || '')) {
        j = skWs(src, id.end);
        if (src[j] === '=') {
          j = skWs(src, j + 1);
          if (isDig(src[j] || '')) {
            while (j < src.length && isDig(src[j])) j++;
            if (src[j] === ';') j++;
            i = j;
            continue;
          }
        } else if (src[j] === ';' || isWs(src[j]) || j >= src.length) {
          if (src[j] === ';') j++;
          i = j;
          continue;
        }
      }
    }

    if (src.slice(i, i + 13) === 'while true do') {
      i += 13;
      continue;
    }

    if (wdAt(src, i, 'if')) {
      let j = skWs(src, i + 2);
      if (src[j] === '(') {
        const left = rdVar(src, skWs(src, j + 1));
        if (left) {
          j = skWs(src, left.end);
          if (src[j] === '=' && src[j + 1] === '=') {
            j = skWs(src, j + 2);
            if (isDig(src[j] || '')) {
              while (j < src.length && isDig(src[j])) j++;
              j = skWs(src, j);
              if (src[j] === ')') {
                j = skWs(src, j + 1);
                if (wdAt(src, j, 'then')) {
                  i = j + 4;
                  continue;
                }
              }
            }
          }
        }
      }
    }

    if (wdAt(src, i, 'break')) {
      let j = i + 5;
      if (src[j] === ';') j++;
      j = skWs(src, j);
      if (wdAt(src, j, 'end')) {
        i = j + 3;
        continue;
      }
    }

    if (wdAt(src, i, 'end')) {
      i += 3;
      continue;
    }

    out += src[i++];
  }
  return colWs(out);
}

function cmpct(body) {
  return strWs(stripN(body));
}

function has(s, part) {
  return s.includes(part);
}

function lkClosCall(c) {
  
  let from = 0;
  while (from < c.length) {
    const mark = c.indexOf('[2]]=v', from);
    if (mark < 0) return false;
    const v = rdVar(c, mark + 5);
    if (!v || c[v.end] !== '(') {
      from = mark + 6;
      continue;
    }
    const a = rdVar(c, v.end + 1);
    if (!a) {
      from = mark + 6;
      continue;
    }
    if (c[a.end] === '[') return true;
    if (c[a.end] === ',') {
      const b = rdVar(c, a.end + 1);
      if (b && c[b.end] === ',') {
        const d = rdVar(c, b.end + 1);
        if (d && c[d.end] === ')') return true;
      }
    }
    from = mark + 6;
  }
  return false;
}

function isSetL(raw, text, c) {
  if (!(has(text, 'for ') || has(c, 'for'))) return false;
  if (has(c, '[2]]=v') || has(raw, 'setmetatable')) return false;
  
  if ((has(c, ',v') || has2VAsg(c)) && has(c, '](')) return false;
  if (has(raw, 'insert(') || has(raw, 'v15(') || has(raw, 'v6(')) return true;
  if (has(c, ']=v') && (has(c, '+1') || has(c, '-1') || has(c, '+v') || hasPlusV(c))) return true;
  if (has(c, ']=v') && has(c, '+') && has(c, '[2]')) return true;
  return false;
}

function isSelf(c) {
  
  
  let i = 0;
  while (i < c.length) {
    const v = rdVar(c, i);
    if (!v || c[v.end] !== '[') {
      i++;
      continue;
    }
    let j = v.end + 1;
    if (c[j] === '#') {
      i = v.end;
      continue;
    }
    const inner = rdVar(c, j);
    if (inner && c.slice(inner.end, inner.end + 4) === '+1]=') return true;
    
    const plus = c.indexOf('+1]=', j);
    if (plus > j && plus < j + 20 && c[plus - 1] !== '#') {
      const slice = c.slice(j, plus);
      if (!slice.includes('#')) return true;
    }
    i = v.end;
  }
  return false;
}

function isJmp(c) {
  const a = rdVar(c, 0);
  if (!a || c[a.end] !== '=') return false;
  const b = rdVar(c, a.end + 1);
  if (!b) return false;
  const tail = c.slice(b.end);
  return tail === '[3]' || tail === '[3];';
}

function isTest(text, c) {
  if (!has(text, 'if') || !has(text, 'else') || !has(text, 'then')) return false;
  for (let i = 0; i < c.length; i++) {
    const ch = c[i];
    if (ch === '<' || ch === '>' || ch === '~') return false;
    if (ch === '=' && c[i + 1] === '=') return false;
  }
  return has(c, '[2]]');
}

function matchAsgIdx(c) {
  const a = rdVar(c, 0);
  if (!a || c[a.end] !== '[') return null;
  const b = rdVar(c, a.end + 1);
  if (!b || c.slice(b.end, b.end + 4) !== '[2]]') return null;
  let i = b.end + 4;
  if (c[i] !== '=') return null;
  i++;
  const d = rdVar(c, i);
  if (!d || c[d.end] !== '[') return null;
  const e = rdVar(c, d.end + 1);
  if (!e) return null;
  const rest = c.slice(e.end);
  if (
    rest === '[3]' || rest === '[3];' ||
    rest === '[3]]' || rest === '[3]];'
  ) {
    return { left: a.name, right: d.name };
  }
  return null;
}

function isLoadK(c) {
  const a = rdVar(c, 0);
  if (!a || c[a.end] !== '[') return false;
  const b = rdVar(c, a.end + 1);
  if (!b || c.slice(b.end, b.end + 4) !== '[2]]') return false;
  let i = b.end + 4;
  if (c[i] !== '=') return false;
  const d = rdVar(c, i + 1);
  if (!d) return false;
  const rest = c.slice(d.end);
  return rest === '[3]' || rest === '[3];';
}

function isSetT(c) {
  if (!has(c, '][')) return false;
  const eq = c.indexOf(']=');
  if (eq < 0) return false;
  let closes = 0;
  for (let i = 0; i <= eq; i++) if (c[i] === ']') closes++;
  return closes >= 2;
}

function isCall(c, text) {
  if (has(c, '](')) return true;
  if (has(text, 'for ') && has(c, '(')) {
    for (let i = 0; i < c.length - 2; i++) {
      const a = rdVar(c, i);
      if (!a || c[a.end] !== ',') continue;
      const b = rdVar(c, a.end + 1);
      if (b && c[b.end] === '=') return true;
    }
  }
  return false;
}

function binOp(c, op) {
  return c.includes(']' + op + 'v');
}

function has2VAsg(c) {
  let i = 0;
  while (i < c.length) {
    if (c[i] !== 'v') {
      i++;
      continue;
    }
    const a = rdVar(c, i);
    if (!a || c[a.end] !== ',') {
      i++;
      continue;
    }
    const b = rdVar(c, a.end + 1);
    if (b && c[b.end] === '=') return true;
    i = a.end;
  }
  return false;
}

function hasPlusV(c) {
  let i = 0;
  while (i < c.length) {
    if (c[i] === '+' && c[i + 1] === 'v') {
      const v = rdVar(c, i + 1);
      if (v && c[v.end] === ']') return true;
    }
    i++;
  }
  return false;
}

function hasAbcAdd(c) {
  let i = 0;
  while (i < c.length) {
    const a = rdId(c, i);
    if (!a) {
      i++;
      continue;
    }
    if (c[a.end] !== '=') {
      i = a.end;
      continue;
    }
    const b = rdId(c, a.end + 1);
    if (!b || c[b.end] !== '+') {
      i = a.end;
      continue;
    }
    const d = rdId(c, b.end + 1);
    if (d) return true;
    i = a.end;
  }
  return false;
}

function hasForAdd(c) {
  if (has(c, ']+v') || has(c, ']+=')) return true;
  if (hasAbcAdd(c) && has(c, '+2')) return true;
  return false;
}

function isForL(c, text) {
  if (!has(text, 'if')) return false;
  if (!has(c, '+2') || !has(c, '+1') || !has(c, '+3')) return false;
  if (!has(c, '>0') && !has(c, '<0')) return false;
  
  if (!has(c, '[3]') && !has(c, '[3];')) return false;
  
  if (!hasForAdd(c)) return false;
  return true;
}

function isForP(c, text) {
  
  if (!has(c, '+2')) return false;
  if (has(c, ']-v') || has(c, ']-=')) {
    if (!has(c, '[3]') && !has(text, 'if')) return false;
    return has(c, '[2]]') || has(c, '[2];') || has(c, '[2]=');
  }
  
  if (!has(text, 'if')) return false;
  if (!has(c, '+1') || !has(c, '+3')) return false;
  if (!has(c, '>0') && !has(c, '<0')) return false;
  if (!has(c, '[3]') && !has(c, '[3];')) return false;
  if (hasForAdd(c)) return false;
  return true;
}

function isSetG(c) {
  
  const eq = c.indexOf(']=');
  if (eq < 0) return false;
  const left = c.slice(0, eq + 1);
  if (!left.includes('[3]')) return false;
  if (left.includes('][')) return false;
  const right = c.slice(eq + 2);
  const v = rdVar(right, 0);
  if (!v || right[v.end] !== '[') return false;
  const idx = right.slice(v.end);
  return idx.startsWith('[') && idx.includes('[2]');
}

function isSetU(c) {
  const eq = c.indexOf(']=');
  if (eq < 0) return false;
  const left = c.slice(0, eq + 1);
  if (!left.includes('[3]')) return false;
  const right = c.slice(eq + 2);
  const v = rdVar(right, 0);
  if (!v || right[v.end] !== '[') return false;
  if (!right.slice(v.end).includes('[2]')) return false;
  return left.includes('][1]') || left.includes('][2]');
}

function isTset(text, c) {
  if (!has(text, 'if') || !has(text, 'else')) return false;
  if (!has(c, '[2]]=') || !has(c, '[3]')) return false;
  if (has(c, '<') || has(c, '>') || has(c, '==')) return false;
  return has(c, '[2]]=v');
}

function isUnm(c) {
  return has(c, ']=-v') || has(c, ']=-(') || has(c, '[2]]=-');
}

function isVarg(c) {
  return has(c, '...');
}

function clsH(body) {
  const raw = foldConst(String(body));
  const text = stripN(raw);
  const c = cmpct(raw);

  if (has(text, 'do return')) {
    if (!has(text, '(')) return 'RETURN';
    const ri = c.indexOf('returnv');
    if (ri >= 0) {
      const after = c.slice(ri + 6);
      const v = rdVar(after, 0);
      if (v && after[v.end] === '[') return 'TAILCALL';
      if (v && after[v.end] === '(' && rdVar(after, v.end + 1)) return 'RETURN';
    }
    return 'TAILCALL';
  }

  if (has(raw, 'setmetatable')) return 'CLOSURE';
  if (lkClosCall(c)) return 'CLOSURE';
  if (isSetL(raw, text, c)) return 'SETLIST';

  
  if (has(c, '..')) return 'CONCAT';

  
  if (
    has(text, 'for')
    && has(c, '](')
    && has(c, 'if')
    && has(c, ',v')
  ) {
    return 'TFORLOOP';
  }

  if (isSelf(c)) return 'SELF';
  if (isVarg(c)) return 'VARARG';
  if (isUnm(c)) return 'UNM';

  if (has(c, '=nil') && has(text, 'for')) return 'LOADNIL';
  if (has(c, '={}') && c.length < 80 && !has(text, 'for') && !has(text, 'while')) {
    return 'NEWTABLE';
  }
  if (isJmp(c)) return 'JMP';

  if (isForL(c, text)) return 'FORLOOP';
  if (isForP(c, text)) return 'FORPREP';

  if (
    has(text, 'if')
    && has(c, '[2]')
    && has(c, '[4]')
    && has(c, '[3]')
    && (has(c, '+1') || has(text, 'else'))
  ) {
    if (has(c, ']==') || has(c, ']==v') || (has(c, '==') && !has(c, '<') && !has(c, '>'))) return 'EQ';
    if (has(c, '<=') || has(c, '>=')) return 'LE';
    if (has(c, '<') || has(c, '>')) return 'LT';
  }
  if (has(text, 'if') && has(c, '+1') && has(c, '[3]')) {
    if (has(c, '==') || has(c, '~=')) return 'EQ';
    if (has(c, '<=') || has(c, '>=')) return 'LE';
    if (has(c, '<') || has(c, '>')) return 'LT';
  }
  if (has(c, '[v') && has(c, '[2]]') && has(c, '=v') && (has(c, '+1') || has(c, '[3]'))) {
    if (has(text, 'if') && (has(c, '==') || has(c, '~='))) return 'EQ';
    if (has(text, 'if') && (has(c, '<=') || has(c, '>='))) return 'LE';
    if (has(text, 'if') && (has(c, '<') || has(c, '>'))) return 'LT';
  }
  if (has(c, '==v') && has(c, '[4]') && has(c, '+1')) return 'EQ';

  if (isTset(text, c)) return 'TESTSET';
  if (isTest(text, c)) return 'TEST';

  if (has(c, '~=0') && has(c, '[2]]=') && has(c, '[3]') && !has(c, '](')) {
    return 'LOADBOOL';
  }

  if (has(c, '[2]]=') && has(c, '[3]][') && has(c, '[4]]')) return 'GETTABLE';
  if (has(c, '=v') && has(c, '[3]][') && has(c, '[4]]')) return 'GETTABLE';
  if (has(c, '[2]]=') && has(c, '[3]][') && has(c, '[4]')) return 'GETTABLE';

  if (isSetT(c)) return 'SETTABLE';
  if (isSetU(c)) return 'SETUPVAL';
  if (isSetG(c)) return 'SETGLOBAL';

  {
    const mv = matchAsgIdx(c);
    if (mv) return mv.left === mv.right ? 'MOVE' : 'GETGLOBAL_OR_UPVAL';
  }

  if (isLoadK(c)) return 'LOADK';
  if (isCall(c, text)) return 'CALL';

  if (binOp(c, '+')) return 'ADD';
  if (binOp(c, '-')) return 'SUB';
  if (binOp(c, '*')) return 'MUL';
  if (binOp(c, '/')) return 'DIV';
  if (binOp(c, '%')) return 'MOD';
  if (binOp(c, '^')) return 'POW';
  if (has(c, '=#v') || has(c, '=#(')) return 'LEN';
  if (has(text, 'not ')) return 'NOT';
  if (has(c, '={}') && !has(c, '](') && !has(text, 'setmetatable')) return 'NEWTABLE';

  return 'UNKNOWN';
}

function refOpNm(name, body, ctx = {}) {
  if (name !== 'GETGLOBAL_OR_UPVAL') return name;
  const c = cmpct(body);
  if (ctx.upValVar && c.includes('=' + ctx.upValVar + '[')) return 'GETUPVAL';
  if (ctx.envVar && c.includes('=' + ctx.envVar + '[')) return 'GETGLOBAL';
  const eq = c.indexOf(']=');
  if (eq >= 0) {
    const v = rdVar(c, eq + 2);
    if (v && c[v.end] === '[') {
      if (v.name === ctx.upValVar) return 'GETUPVAL';
      if (v.name === ctx.envVar) return 'GETGLOBAL';
    }
  }
  return 'GETGLOBAL';
}


function isIdStr(s) {
  if (typeof s !== 'string' || !s.length || s.length > 64) return false;
  const c0 = s.charCodeAt(0);
  if (!((c0 >= 65 && c0 <= 90) || (c0 >= 97 && c0 <= 122) || c0 === 95)) return false;
  for (let i = 1; i < s.length; i++) {
    const c = s.charCodeAt(i);
    if (!((c >= 65 && c <= 90) || (c >= 97 && c <= 122) || (c >= 48 && c <= 57) || c === 95)) {
      return false;
    }
  }
  return true;
}

function isGName(s) {
  if (typeof s !== 'string' || !s.length) return false;
  if (isBinK(s)) return false;
  return isIdStr(s);
}

function isBinK(s) {
  if (typeof s !== 'string' || s.length < 2) return false;
  let bad = 0;
  for (let i = 0; i < s.length; i++) {
    const c = s.charCodeAt(i);
    if (c < 9 || (c > 13 && c < 32) || c >= 127) bad++;
  }
  return bad / s.length >= 0.3;
}

function hasCallSoon(ins, proto) {
  if (!proto || ins._index == null) return false;
  const start = ins._index;
  for (let i = start + 1; i < Math.min(start + 8, proto.instructions.length); i++) {
    const n = proto.instructions[i];
    if (!n || n.skipped) continue;
    if ((n.mode === 0 || n.mode == null) && n.A === ins.A && !n.isKB && !n.isKC) {
      if (typeof n.B === 'number' || n.B == null) return true;
    }
    if (n.mode === 2) return false;
  }
  return false;
}

function feedsGlobalUse(ins, proto) {
  if (!proto || ins._index == null) return false;
  if (hasCallSoon(ins, proto)) return true;
  const start = ins._index;
  for (let i = start + 1; i < Math.min(start + 8, proto.instructions.length); i++) {
    const n = proto.instructions[i];
    if (!n || n.skipped) continue;
    if (n.mode === 2) return false;
    if ((n.mode === 0 || n.mode == null) && n.isKC && typeof n.B === 'number' && n.B === ins.A) return true;
    if (n.A === ins.A && n.mode === 1 && n.isKB) continue;
    if (typeof n.A === 'number' && n.A === ins.A) continue;
    break;
  }
  return false;
}

function lkArgMv(ins, proto) {
  if (!proto || ins._index == null) return false;
  for (let i = ins._index + 1; i < Math.min(ins._index + 4, proto.instructions.length); i++) {
    const n = proto.instructions[i];
    if (!n || n.skipped) continue;
    if (n.mode === 2) return false;
    if ((n.mode === 0 || n.mode == null) && !n.isKB && !n.isKC && typeof n.B === 'number') {
      if (n.A === ins.A - 1 && n.B === 2) return true;
      if (n.A === ins.A && n.B >= 2) return false;
    }
    break;
  }
  for (let i = ins._index - 1; i >= Math.max(1, ins._index - 4); i--) {
    const n = proto.instructions[i];
    if (!n || n.skipped) continue;
    if (n.mode === 1 && n.isKB && n.A === ins.A - 1) return true;
    break;
  }
  return false;
}

function lkCall(ins, proto) {
  if (!proto || ins._index == null) return false;
  const bNum = typeof ins.B === 'number' ? ins.B : -1;

  for (let i = ins._index - 1; i >= Math.max(1, ins._index - 8); i--) {
    const n = proto.instructions[i];
    if (!n || n.skipped) continue;
    if (n.A !== ins.A) {
      if (n.mode === 1 && n.isKB) continue;
      if (n.mode === 0 && !n.isKB && !n.isKC) continue;
      if (n.mode === 2) return false;
      continue;
    }
    if (n.mode === 0 && n.isKC) return true;
    if (n.mode === 1 && n.isKB) return true;
    if (n.mode === 3) return true;
    break;
  }

  
  if (bNum >= 2) {
    let argLoads = 0;
    for (let i = ins._index - 1; i >= Math.max(1, ins._index - 8); i--) {
      const n = proto.instructions[i];
      if (!n || n.skipped) continue;
      if (n.mode === 2) break;
      if (typeof n.A === 'number' && n.A > ins.A && n.A <= ins.A + Math.min(bNum, 8) - 1) {
        if (n.mode === 1 && n.isKB) argLoads++;
        if (n.mode === 0 && n.isKC) argLoads++;
      }
      if (n.A === ins.A && n.mode === 1 && n.isKB) return true;
    }
    if (argLoads >= 1) return true;
  }
  return false;
}

function lkUpFollow(ins, proto, closureLocalOp, opcodeMap) {
  if (!proto || typeof ins.B !== 'number' || typeof ins.C !== 'number') return false;
  if (ins.C <= 0 || ins.C > 32) return false;
  if (!proto.prototypes[ins.B]) return false;
  for (let u = 0; u < ins.C; u++) {
    const next = proto.instructions[ins._index + 1 + u];
    if (!next || next.skipped) return false;
    if (closureLocalOp != null && next.opcode === closureLocalOp) continue;
    const n = (opcodeMap && opcodeMap[next.opcode] && opcodeMap[next.opcode].name) || '';
    if (n === 'MOVE' || n === 'GETUPVAL') continue;
    if (next.mode === 0 && !next.isKB && !next.isKC && typeof next.B === 'number') continue;
    return false;
  }
  return true;
}

function shpGuess(ins, proto, closureLocalOp, opcodeMap) {
  if (!ins || ins.skipped) return null;

  const { A, B, C, mode, isKB, isKC } = ins;
  const bStr = typeof B === 'string';
  const bNum = typeof B === 'number';
  const cNum = typeof C === 'number';
  const cStr = typeof C === 'string';
  const cNil = C == null;

  
  if (mode === 2 && bNum) return { name: 'JMP', conf: 95 };

  
  if (mode === 3 && bNum && cNum != null) {
    if (proto && proto.prototypes[B] && C >= 0 && C <= 255 && !isKC && !isKB) {
      return { name: 'CLOSURE', conf: 90 };
    }
    if (isKC || isKB) {
      return { name: 'EQ', conf: 55 };
    }
    if (proto && ins._index != null) {
      const next = proto.instructions[ins._index + 1];
      if (next && !next.skipped && next.mode === 2 && typeof next.B === 'number') {
        return { name: 'EQ', conf: 75 };
      }
    }
    if (B > 0 && proto && B < proto.instructions.length && C === 0) {
      return { name: 'JMP', conf: 55 };
    }
    
    return { name: 'EQ', conf: 50 };
  }

  
  if (mode === 1 && isKB && cNil) {
    if (bStr) {
      if (isBinK(B)) return { name: 'LOADK', conf: 95 };
      if (isIdStr(B) && feedsGlobalUse(ins, proto)) return { name: 'GETGLOBAL', conf: 90 };
      return { name: 'LOADK', conf: 88 };
    }
    if (typeof B === 'boolean') return { name: 'LOADBOOL', conf: 90 };
    if (bNum) return { name: 'LOADK', conf: 85 };
    if (B == null) return { name: 'LOADNIL', conf: 70 };
  }

  
  if (mode === 0 && !isKB && !isKC && bNum && (C === 0 || cNil) && B >= A && B <= A + 32) {
    if (lkCall(ins, proto)) return { name: 'CALL', conf: 80 };
    if (B === A) return { name: 'LOADNIL', conf: 70 };
    if (B - A <= 8) return { name: 'LOADNIL', conf: 55 };
  }

  
  if (mode === 0 && isKB && isKC) {
    return { name: 'SETTABLE', conf: 92 };
  }

  
  if (mode === 0 && isKC && !isKB && bNum) {
    if (A === B && cStr && isIdStr(C) && hasCallSoon(ins, proto)) {
      return { name: 'SELF', conf: 88 };
    }
    return { name: 'GETTABLE', conf: 90 };
  }

  
  if (mode === 0 && isKB && !isKC && (bNum || typeof B === 'string' || typeof B === 'boolean') && cNum) {
    return { name: 'ADD', conf: 45 };
  }

  
  if (bNum && cNum && lkUpFollow(ins, proto, closureLocalOp, opcodeMap)) {
    return { name: 'CLOSURE', conf: 80 };
  }

  
  if (mode === 0 && !isKB && !isKC && bNum) {
    
    if (B === 0 && cNum && C >= 1 && C <= 32) {
      return { name: 'CALL', conf: 72 };
    }
    if (B === 0 && (C === 0 || cNil)) {
      return { name: 'MOVE', conf: 25 };
    }
    if (B === 0 && C === 1) {
      return { name: 'CALL', conf: 50 };
    }
    
    if (B === 1 && (C === 0 || cNil || C === 1)) {
      if (lkArgMv(ins, proto)) return { name: 'MOVE', conf: 70 };
      return { name: 'CALL', conf: 48 };
    }
    
    if (B >= 2 && B <= 32) {
      if (lkCall(ins, proto)) return { name: 'CALL', conf: 75 };
      if (cNil || C === 0 || (cNum && C >= 1 && C <= 32)) {
        return { name: 'CALL', conf: 55 };
      }
    }
    if (B <= 255 && (cNil || C === 0)) return { name: 'MOVE', conf: 50 };
  }

  

  return null;
}

function isCmpOp(n) {
  return n === 'EQ' || n === 'LT' || n === 'LE' || n === 'TEST';
}

function isStrongMap(n) {
  return n === 'FORLOOP' || n === 'FORPREP' || n === 'SETTABLE' || n === 'NEWTABLE'
    || n === 'CONCAT' || n === 'SETGLOBAL' || n === 'CLOSURE' || n === 'SETUPVAL' || n === 'GETUPVAL';
}

function isWeakMap(n) {
  return n === 'UNKNOWN' || n === 'CALL' || n === 'SETLIST' || n === 'SELF' || n === 'TAILCALL'
    || n === 'EQ' || n === 'LT' || n === 'LE' || n === 'TEST' || n === 'RETURN' || n === 'MOVE';
}

function isModeBound(n) {
  return n === 'CLOSURE' || n === 'JMP' || n === 'GETGLOBAL' || n === 'LOADK'
    || n === 'GETTABLE' || n === 'SETTABLE' || n === 'SELF';
}

function prefNm(mapName, ins, proto, closureLocalOp, opcodeMap) {
  const shape = shpGuess(ins, proto, closureLocalOp, opcodeMap);
  let name = mapName || 'UNKNOWN';

  if (shape && shape.conf >= 70 && shape.name !== 'UNKNOWN') {
    const protect =
      isStrongMap(mapName)
      && shape.name !== mapName
      && !(mapName === 'SETTABLE' && shape.name === 'GETTABLE');
    const retMis = mapName === 'RETURN' && (
      shape.name === 'LOADK' || shape.name === 'LOADNIL' || shape.name === 'GETGLOBAL'
      || shape.name === 'JMP' || shape.name === 'MOVE' || shape.name === 'CALL'
    );
    if (retMis) {
      name = shape.name;
    } else if (protect) {
      name = mapName;
    } else if (!(shape.name === 'CALL' && (mapName === 'CONCAT' || mapName === 'SETGLOBAL' || mapName === 'TFORLOOP'))) {
      name = shape.name;
    }
  } else if (shape && shape.name !== 'UNKNOWN' && name === 'UNKNOWN') {
    name = shape.name;
  } else if (
    shape
    && shape.name !== 'UNKNOWN'
    && shape.conf >= 55
    && isWeakMap(name)
    && isModeBound(shape.name)
  ) {
    name = shape.name;
  }

  if (mapName === 'CONCAT') name = 'CONCAT';
  if (mapName === 'SETGLOBAL' && ins.mode === 1) name = 'SETGLOBAL';
  if (mapName === 'SETTABLE') name = 'SETTABLE';
  if (mapName === 'GETTABLE') name = 'GETTABLE';
  if (mapName === 'FORLOOP' || mapName === 'FORPREP') name = mapName;

  if (
    mapName === 'RETURN'
    && ins.mode === 0
    && typeof ins.B === 'number'
    && ins.B >= 2
    && !ins.isKB
    && !ins.isKC
  ) {
    name = 'RETURN';
  }
  if (mapName === 'MOVE' && ins.mode === 0 && !ins.isKB && !ins.isKC && typeof ins.B === 'number' && ins.B <= 255) {
    if (!(shape && shape.name === 'CALL' && shape.conf >= 85 && lkCall(ins, proto))) {
      name = 'MOVE';
    }
  }
  if (mapName === 'TFORLOOP') name = 'TFORLOOP';
  if (mapName === 'LT' || mapName === 'LE' || mapName === 'EQ') {
    if (ins.mode === 3 || isCmpOp(mapName)) name = mapName;
  }

  if (
    name === 'TFORLOOP'
    && ins.mode === 0
    && typeof ins.B === 'number'
    && typeof ins.A === 'number'
    && ins.B >= 1
    && (ins.C === 0 || ins.C === 1 || ins.C == null || (typeof ins.C === 'number' && ins.C >= 2 && ins.C <= 16))
  ) {
    if (ins.B <= ins.A + 8 || (shape && shape.name === 'CALL')) name = 'CALL';
  }

  if (mapName === 'TFORLOOP' && ins.mode === 3) name = 'TFORLOOP';

  if (ins.mode === 2 && typeof ins.B === 'number') {
    if (mapName === 'FORLOOP' || mapName === 'FORPREP' || name === 'FORLOOP' || name === 'FORPREP') {
      name = mapName === 'FORPREP' || name === 'FORPREP' ? 'FORPREP' : 'FORLOOP';
      if (mapName === 'FORPREP') name = 'FORPREP';
      if (mapName === 'FORLOOP') name = 'FORLOOP';
    } else {
      name = 'JMP';
    }
  }

  if (ins.mode === 3 && typeof ins.B === 'number') {
    const pidx = ins.B;
    const nups = typeof ins.C === 'number' ? ins.C : 0;
    if (proto && proto.prototypes[pidx] && nups >= 0 && nups <= 32 && !ins.isKB && !ins.isKC) {
      name = 'CLOSURE';
    } else if (isCmpOp(mapName) || isCmpOp(name)) {
      name = isCmpOp(mapName) ? mapName : name;
    } else if (name === 'CLOSURE' || mapName === 'CLOSURE') {
      name = 'JMP';
    } else if (mapName && mapName !== 'UNKNOWN') {
      name = mapName;
    }
  }

  if (ins.mode === 1 && ins.isKB && ins.C == null) {
    if (mapName === 'SETGLOBAL') {
      name = 'SETGLOBAL';
    } else if (typeof ins.B === 'string') {
      if (isBinK(ins.B)) name = 'LOADK';
      else if (isIdStr(ins.B) && feedsGlobalUse(ins, proto)) name = 'GETGLOBAL';
      else name = 'LOADK';
    } else if (typeof ins.B === 'boolean') name = 'LOADBOOL';
    else if (typeof ins.B === 'number') {
      name = mapName === 'GETGLOBAL' ? 'GETGLOBAL' : 'LOADK';
    }
  }

  
  if (
    (name === 'GETGLOBAL' || name === 'GETUPVAL' || mapName === 'GETUPVAL') &&
    ins.mode === 0 &&
    !ins.isKB &&
    !ins.isKC &&
    typeof ins.B === 'number'
  ) {
    name = 'GETUPVAL';
  }
  if (name === 'GETGLOBAL' && ins.mode === 0 && !ins.isKB && typeof ins.B === 'number') {
    name = 'GETUPVAL';
  }

  if (name === 'LOADNIL' && typeof ins.B === 'number' && typeof ins.A === 'number' && ins.B < ins.A) {
    if (mapName === 'MOVE') name = 'MOVE';
    else if (mapName && mapName !== 'UNKNOWN' && mapName !== 'LOADNIL') name = mapName;
    else name = 'MOVE';
  }

  if (ins.mode === 0 && ins.isKB && ins.isKC) name = 'SETTABLE';

  if (ins.mode === 0 && ins.isKC && !ins.isKB && typeof ins.B === 'number') {
    if (mapName === 'SETTABLE') {
      name = 'SETTABLE';
    } else if (mapName === 'GETTABLE') {
      name = 'GETTABLE';
    } else if (
      ins.A === ins.B &&
      typeof ins.C === 'string' &&
      isIdStr(ins.C) &&
      hasCallSoon(ins, proto)
    ) {
      name = 'SELF';
    } else {
      name = 'GETTABLE';
    }
  }

  if (name === 'CLOSURE' && ins.mode === 0 && (ins.isKC || ins.isKB)) {
    if (ins.isKB && ins.isKC) name = 'SETTABLE';
    else if (ins.isKC) name = 'GETTABLE';
  }

  if (name === 'CLOSURE') {
    const nups = typeof ins.C === 'number' ? ins.C : 0;
    const pidx = typeof ins.B === 'number' ? ins.B : -1;
    if (nups < 0 || nups > 32 || !proto || !proto.prototypes[pidx]) {
      if (ins.mode === 3 && typeof ins.B === 'number') name = 'JMP';
      else if (
        ins.mode === 0
        && !ins.isKB
        && !ins.isKC
        && typeof ins.B === 'number'
        && ins.B <= 255
        && (ins.C === 0 || ins.C == null)
      ) {
        
        name = mapName === 'MOVE' ? 'MOVE' : 'MOVE';
      } else if (ins.mode === 0 && !ins.isKB && !ins.isKC) {
        name = mapName === 'CALL' || mapName === 'SETLIST' ? mapName : 'CALL';
      } else if (mapName && mapName !== 'UNKNOWN' && mapName !== 'CLOSURE') {
        name = mapName;
      } else {
        name = 'UNKNOWN';
      }
    }
  }

  
  if (
    ins.mode === 0 &&
    !ins.isKB &&
    !ins.isKC &&
    ins.B === 0 &&
    (ins.C === 0 || ins.C == null)
  ) {
    const strongShape = shape && shape.name !== 'UNKNOWN' && shape.conf >= 55;
    if (strongShape && (shape.name === 'LOADNIL' || shape.name === 'MOVE' || shape.name === 'CALL')) {
      name = shape.name;
    } else if (mapName === 'MOVE') {
      name = 'MOVE';
    } else if (mapName === 'RETURN' || mapName === 'TAILCALL') {
      
      if (!strongShape) name = mapName;
    } else if (mapName === 'CALL') {
      name = 'CALL';
    } else if (mapName === 'LOADNIL') {
      name = 'LOADNIL';
    } else if (mapName === 'SETLIST') {
      name = strongShape ? shape.name : 'CALL';
    } else if (name === 'UNKNOWN' && mapName && mapName !== 'UNKNOWN') {
      name = mapName;
    }
  }

  if ((name === 'JMP' || name === 'EQ' || name === 'LT' || name === 'LE' || name === 'TEST') && typeof ins.B === 'string') {
    if (ins.mode === 1 && ins.isKB) {
      name = (isIdStr(ins.B) && !isBinK(ins.B) && feedsGlobalUse(ins, proto)) ? 'GETGLOBAL' : 'LOADK';
    } else if (mapName && mapName !== 'UNKNOWN') {
      name = mapName;
    }
  }

  return name;
}

function refOpMap(root, opcodeMap) {
  
  
  const votes = new Map();

  function walk(p) {
    for (let i = 1; i < p.instructions.length; i++) {
      const ins = p.instructions[i];
      if (!ins || ins.skipped) continue;
      ins._index = i;
      const mapName = (opcodeMap[ins.opcode] || {}).name || 'UNKNOWN';
      const name = prefNm(mapName, ins, p, null, opcodeMap);
      const shape = shpGuess(ins, p, null, opcodeMap);
      if (!shape || shape.conf < 80) continue;
      if (!votes.has(ins.opcode)) votes.set(ins.opcode, new Map());
      const m = votes.get(ins.opcode);
      m.set(name, (m.get(name) || 0) + 1);
    }
    for (const c of p.prototypes) if (c) walk(c);
  }
  walk(root);

  for (const [op, m] of votes) {
    if (!opcodeMap[op]) opcodeMap[op] = { name: 'UNKNOWN', body: '' };
    if (opcodeMap[op].name !== 'UNKNOWN') continue;
    let best = null;
    let bestN = 0;
    let total = 0;
    for (const [name, n] of m) {
      total += n;
      if (n > bestN) {
        best = name;
        bestN = n;
      }
    }
    if (best && bestN === total && bestN >= 2) opcodeMap[op].name = best;
  }
  return opcodeMap;
}


function isOpIdx(expr) {
  const folded = strWs(foldConst(expr));
  return folded === '1' || evalOk(expr) === 1;
}

function scanFetch(folded) {
  
  let best = null;
  let i = 0;
  while (i < folded.length) {
    if (folded[i] === '"' || folded[i] === "'") {
      i = skStr(folded, i);
      continue;
    }
    const a = rdId(folded, i);
    if (!a) {
      i++;
      continue;
    }
    let j = skWs(folded, a.end);
    if (folded[j] !== '=') {
      i = a.end;
      continue;
    }
    j = skWs(folded, j + 1);
    const code = rdId(folded, j);
    if (!code || folded[code.end] !== '[') {
      i = a.end;
      continue;
    }
    const pc = rdId(folded, code.end + 1);
    if (!pc || folded[pc.end] !== ']') {
      i = a.end;
      continue;
    }
    j = skWs(folded, pc.end + 1);
    if (folded[j] === ';') j++;
    j = skWs(folded, j);
    const op = rdId(folded, j);
    if (!op) {
      i = a.end;
      continue;
    }
    j = skWs(folded, op.end);
    if (folded[j] !== '=') {
      i = a.end;
      continue;
    }
    j = skWs(folded, j + 1);
    const inst2 = rdId(folded, j);
    if (!inst2 || inst2.name !== a.name || folded[inst2.end] !== '[') {
      i = a.end;
      continue;
    }
    const idxStart = inst2.end + 1;
    let depth = 1;
    let k = idxStart;
    while (k < folded.length && depth > 0) {
      if (folded[k] === '[') depth++;
      else if (folded[k] === ']') depth--;
      if (depth > 0) k++;
      else break;
    }
    if (depth !== 0) {
      i = a.end;
      continue;
    }
    const idxExpr = folded.slice(idxStart, k);
    if (isOpIdx(idxExpr)) {
      best = {
        instVar: a.name,
        codeVar: code.name,
        pcVar: pc.name,
        opVar: op.name,
        fetchIndex: i,
      };
    }
    i = a.end;
  }
  if (!best) throw new Error('VM fetch not found');
  return best;
}

function findOpLe(folded, opVar) {
  
  const hits = [];
  let from = 0;
  while (from < folded.length) {
    const at = findWd(folded, 'if', from);
    if (at < 0) break;
    let j = skWs(folded, at + 2);
    if (folded[j] !== '(') {
      from = at + 2;
      continue;
    }
    j = skWs(folded, j + 1);
    while (folded[j] === '(') j = skWs(folded, j + 1);
    const id = rdId(folded, j);
    if (!id || id.name !== opVar) {
      from = at + 2;
      continue;
    }
    j = skWs(folded, id.end);
    if (folded[j] !== '<' || folded[j + 1] !== '=') {
      from = at + 2;
      continue;
    }
    j = skWs(folded, j + 2);
    const num = rdNum(folded, j);
    if (!num) {
      from = at + 2;
      continue;
    }
    j = skWs(folded, num.end);
    while (folded[j] === ')') j = skWs(folded, j + 1);
    if (!wdAt(folded, j, 'then')) {
      from = at + 2;
      continue;
    }
    hits.push({ at, bound: num.num });
    from = at + 2;
  }
  return hits;
}

function pickDisp(folded, fetch, opVar) {
  const hits = findOpLe(folded, opVar);
  let best = null;

  for (const hit of hits) {
    const abs = typeof hit === 'number' ? hit : hit.at;
    if (abs <= fetch.fetchIndex - 50 && abs < fetch.fetchIndex) {
      
    } else if (abs < fetch.fetchIndex - 5000) {
      continue;
    }
    const end = findBlkEnd(folded, abs);
    if (end < 0) continue;
    const len = end - abs;
    if (len < 400) continue;
    const bound = typeof hit === 'object' ? hit.bound : 0;
    const score = len + bound * 50;
    if (!best || score > best.score) {
      best = { start: abs, len, raw: folded.slice(abs, end), score, bound };
    }
  }

  
  for (const hit of hits) {
    const abs = typeof hit === 'number' ? hit : hit.at;
    if (abs <= fetch.fetchIndex) continue;
    const end = findBlkEnd(folded, abs);
    if (end < 0) continue;
    const len = end - abs;
    if (len < 400) continue;
    const bound = typeof hit === 'object' ? hit.bound : 0;
    const score = len + bound * 80 + 1000; 
    if (!best || score > best.score) {
      best = { start: abs, len, raw: folded.slice(abs, end), score, bound };
    }
  }

  if (!best) throw new Error('Dispatch tree not found for ' + opVar);
  return best;
}

function findDisp(source) {
  const folded = foldConst(source);
  const fetch = scanFetch(folded);
  const tree = pickDisp(folded, fetch, fetch.opVar);
  return {
    ...fetch,
    start: tree.start,
    end: tree.start + tree.len,
    raw: tree.raw,
    folded,
  };
}

function scanSep(s, from) {
  let depth = 0;
  let i = from;
  const hits = [];
  while (i < s.length) {
    if (s[i] === '"' || s[i] === "'") {
      i = skStr(s, i);
      continue;
    }
    const tok = nextKw(s, i);
    if (!tok) break;
    if (tok.kind !== 'kw') {
      i = tok.end;
      continue;
    }
    const n = tok.name;
    if (n === 'if' || n === 'function' || n === 'repeat' || n === 'do') {
      depth++;
      i = tok.end;
      continue;
    }
    if (n === 'until') {
      if (depth > 0) depth--;
      i = tok.end;
      continue;
    }
    if (n === 'elseif') {
      if (depth === 0) hits.push({ type: 'elseif', index: tok.start });
      i = tok.end;
      continue;
    }
    if (n === 'else') {
      if (depth === 0) hits.push({ type: 'else', index: tok.start });
      i = tok.end;
      continue;
    }
    if (n === 'end') {
      if (depth === 0) {
        hits.push({ type: 'end', index: tok.start });
        return { hits, end: tok.end };
      }
      depth--;
      i = tok.end;
      continue;
    }
    i = tok.end;
  }
  return { hits, end: s.length };
}

function parseIf(s) {
  if (!wdAt(s, 0, 'if') && !(skWs(s, 0) === 0 && wdAt(s, 0, 'if'))) {
    const start = skWs(s, 0);
    if (!wdAt(s, start, 'if')) return null;
  }
  const start = wdAt(s, 0, 'if') ? 0 : skWs(s, 0);
  if (!wdAt(s, start, 'if')) return null;

  const branches = [];
  let i = start + 2;
  while (true) {
    const thenAt = findWd(s, 'then', i);
    if (thenAt < 0) return null;
    const cond = s.slice(i, thenAt).trim();
    const bodyStart = thenAt + 4;
    const { hits } = scanSep(s, bodyStart);
    const first = hits[0];
    if (!first) return null;
    branches.push({ cond, body: s.slice(bodyStart, first.index).trim() });

    if (first.type === 'end') {
      return {
        branches,
        elseBody: null,
        end: first.index + 3,
        full: s.slice(0, first.index + 3),
      };
    }
    if (first.type === 'else') {
      const elseStart = first.index + 4;
      const rest = scanSep(s, elseStart);
      const endHit = rest.hits.find((h) => h.type === 'end');
      const elseEnd = endHit ? endHit.index : rest.end;
      return {
        branches,
        elseBody: s.slice(elseStart, elseEnd).trim(),
        end: elseEnd + 3,
        full: s.slice(0, elseEnd + 3),
      };
    }
    if (first.type === 'elseif') {
      i = first.index + 6;
      continue;
    }
    return null;
  }
}

function parseCond(cond, opVar) {
  let i = 0;
  while (i < cond.length) {
    const id = rdId(cond, i);
    if (id && id.name === opVar) {
      let j = skWs(cond, id.end);
      let op = null;
      if (cond.slice(j, j + 2) === '<=' || cond.slice(j, j + 2) === '>='
        || cond.slice(j, j + 2) === '==' || cond.slice(j, j + 2) === '~=') {
        op = cond.slice(j, j + 2);
        j += 2;
      } else if (cond[j] === '<' || cond[j] === '>') {
        op = cond[j];
        j += 1;
      }
      if (op) {
        j = skWs(cond, j);
        const num = rdNum(cond, j);
        if (num) return { op, n: num.num };
      }
    }
    i++;
  }
  return null;
}

function evalCond(c, opcode) {
  if (!c) return false;
  switch (c.op) {
    case '<=': return opcode <= c.n;
    case '>=': return opcode >= c.n;
    case '==': return opcode === c.n;
    case '~=': return opcode !== c.n;
    case '<': return opcode < c.n;
    case '>': return opcode > c.n;
    default: return false;
  }
}

function fmtIf(branches, elseBody) {
  if (!branches.length) return elseBody || '';
  let out = '';
  for (let i = 0; i < branches.length; i++) {
    const br = branches[i];
    out += (i === 0 ? 'if ' : 'elseif ') + br.cond + ' then ' + br.body + ' ';
  }
  if (elseBody != null) out += 'else ' + elseBody + ' ';
  out += 'end';
  return out.trim();
}

function resLeaf(fragment, opcode, opVar, depth = 0) {
  const f = fragment.trim();
  if (depth > 40) return f;

  const tryParse = (src) => {
    const parsed = parseIf(src);
    if (!parsed) return null;
    for (let bi = 0; bi < parsed.branches.length; bi++) {
      const br = parsed.branches[bi];
      const c = parseCond(br.cond, opVar);
      if (!c) {
        
        
        return fmtIf(parsed.branches.slice(bi), parsed.elseBody);
      }
      if (evalCond(c, opcode)) return resLeaf(br.body, opcode, opVar, depth + 1);
    }
    if (parsed.elseBody != null) return resLeaf(parsed.elseBody, opcode, opVar, depth + 1);
    return f;
  };

  if (wdAt(f, 0, 'if') && f.slice(0, 80).includes(opVar)) {
    const got = tryParse(f);
    if (got != null) return got;
  }

  const ifIdx = findOpIf(f, opVar);
  if (ifIdx >= 0 && ifIdx < 80) {
    const got = tryParse(f.slice(ifIdx));
    if (got != null) return got;
  }
  return f;
}

function findOpIf(src, opVar) {
  let from = 0;
  let best = -1;
  while (from < src.length) {
    const at = findWd(src, 'if', from);
    if (at < 0) break;
    let j = skWs(src, at + 2);
    if (src[j] === '(') {
      j = skWs(src, j + 1);
      while (src[j] === '(') j = skWs(src, j + 1);
      const id = rdId(src, j);
      if (id && id.name === opVar) {
        j = skWs(src, id.end);
        const op2 = src.slice(j, j + 2);
        if (op2 === '<=' || op2 === '==' || op2 === '>=' || src[j] === '>' || src[j] === '<') {
          
          if (best < 0) best = at;
          
          if (at > best + 200) break;
        }
      }
    }
    from = at + 2;
  }
  return best;
}

function maxOpTree(tree, opVar) {
  let maxOp = 0;
  let i = 0;
  while (i < tree.length) {
    const id = rdId(tree, i);
    if (id && id.name === opVar) {
      let j = skWs(tree, id.end);
      if (tree.slice(j, j + 2) === '<=' || tree.slice(j, j + 2) === '==' || tree[j] === '>') {
        if (tree.slice(j, j + 2) === '<=' || tree.slice(j, j + 2) === '==') j += 2;
        else j += 1;
        j = skWs(tree, j);
        const num = rdNum(tree, j);
        if (num) maxOp = Math.max(maxOp, num.num);
      }
      i = id.end;
      continue;
    }
    i++;
  }
  return maxOp;
}

function parseDisp(code, opVar) {
  const folded = foldConst(code);
  const start = findOpIf(folded, opVar);
  if (start < 0) throw new Error('Dispatch tree start not found for ' + opVar);
  const root = parseIf(folded.slice(start));
  if (!root) throw new Error('Failed to parse dispatch if-tree');

  const map = new Map();
  const probeMax = maxOpTree(root.full, opVar) + 8;
  for (let op = 0; op <= probeMax; op++) {
    map.set(op, resLeaf(root.full, op, opVar));
  }
  return { map, foldedTree: root.full, opVar, maxOp: probeMax };
}

function findLocFn(source, from = 0) {
  
  let i = from;
  while (i < source.length) {
    const at = findWd(source, 'local', i);
    if (at < 0) return null;
    let j = skWs(source, at + 5);
    if (!wdAt(source, j, 'function')) {
      i = at + 5;
      continue;
    }
    j = skWs(source, j + 8);
    const fn = rdId(source, j);
    if (!fn) {
      i = at + 5;
      continue;
    }
    j = skWs(source, fn.end);
    if (source[j] !== '(') {
      i = at + 5;
      continue;
    }
    j++;
    const a = rdId(source, skWs(source, j));
    if (!a || source[a.end] !== ',') {
      i = at + 5;
      continue;
    }
    const b = rdId(source, skWs(source, a.end + 1));
    if (!b || source[b.end] !== ',') {
      i = at + 5;
      continue;
    }
    const c = rdId(source, skWs(source, b.end + 1));
    if (!c) {
      i = at + 5;
      continue;
    }
    j = skWs(source, c.end);
    if (source[j] !== ')') {
      i = at + 5;
      continue;
    }
    j = skWs(source, j + 1);
    if (!wdAt(source, j, 'local')) {
      i = at + 5;
      continue;
    }
    j = skWs(source, j + 5);
    const d = rdId(source, j);
    if (!d) {
      i = at + 5;
      continue;
    }
    j = skWs(source, d.end);
    if (source[j] !== '=') {
      i = at + 5;
      continue;
    }
    j = skWs(source, j + 1);
    const e = rdId(source, j);
    if (!e || e.name !== a.name || source.slice(e.end, e.end + 3) !== '[1]') {
      i = at + 5;
      continue;
    }
    return {
      index: at,
      wrapVar: fn.name,
      chunkVar: a.name,
      upValVar: b.name,
      envVar: c.name,
      codeLocal: d.name,
    };
  }
  return null;
}

function infVmCtx(source, dispatch) {
  const { instVar, opVar, pcVar, codeVar } = dispatch;
  const folded = foldConst(source.slice(dispatch.start, dispatch.end));

  let wrapVar = 'v40';
  let envVar = 'v74';
  let upValVar = 'v73';
  let stackVar = 'v88';
  let protoVar = 'v79';
  let unpackVar = 'v21';

  const wrapFn = findLocFn(source);
  if (wrapFn) {
    wrapVar = wrapFn.wrapVar;
    upValVar = wrapFn.upValVar;
    envVar = wrapFn.envVar;
    const slice = source.slice(wrapFn.index, wrapFn.index + 400);
    
    let i = 0;
    while (i < slice.length) {
      const at = findWd(slice, 'local', i);
      if (at < 0) break;
      let j = skWs(slice, at + 5);
      const id = rdId(slice, j);
      if (id) {
        j = skWs(slice, id.end);
        if (slice[j] === '=') {
          j = skWs(slice, j + 1);
          const base = rdId(slice, j);
          if (base && slice.slice(base.end, base.end + 3) === '[2]') {
            protoVar = id.name;
            break;
          }
        }
      }
      i = at + 5;
    }
  }

  
  let i = 0;
  while (i < folded.length) {
    const left = rdId(folded, i);
    if (!left) {
      i++;
      continue;
    }
    const needle = '[' + instVar + '[2]]=';
    if (folded.slice(left.end, left.end + needle.length) === needle) {
      let j = left.end + needle.length;
      const right = rdId(folded, j);
      if (right && folded.slice(right.end, right.end + needle.length - 1) === '[' + instVar + '[3]]') {
        if (left.name === right.name) stackVar = left.name;
        else if (left.name === stackVar) upValVar = right.name;
      }
    }
    i = left.end;
  }

  const stkNeedle = '[' + instVar + '[2]]';
  const stkAt = folded.indexOf(stkNeedle);
  if (stkAt > 0) {
    let k = stkAt - 1;
    while (k >= 0 && isDig(folded[k])) k--;
    if (folded[k] === 'v') {
      const id = rdId(folded, k);
      if (id) stackVar = id.name;
    }
  }

  const unAt = source.indexOf('=unpack or table.unpack');
  if (unAt > 0) {
    let k = unAt - 1;
    while (k >= 0 && isWs(source[k])) k--;
    while (k >= 0 && (isDig(source[k]) || source[k] === 'v')) k--;
    const id = rdId(source, k + 1);
    if (id) unpackVar = id.name;
  }

  return {
    instVar, opVar, pcVar, codeVar,
    envVar, upValVar, stackVar, protoVar, wrapVar,
    topVar: 'v83',
    unpackVar,
  };
}

function findClosOp(source) {
  const folded = foldConst(source);
  let from = 0;
  while (from < folded.length) {
    const at = findWd(folded, 'if', from);
    if (at < 0) break;
    let j = skWs(folded, at + 2);
    if (folded[j] === '(') {
      j = skWs(folded, j + 1);
      const v = rdId(folded, j);
      if (v && folded[v.end] === '[' && folded[v.end + 1] === '1' && folded[v.end + 2] === ']') {
        j = skWs(folded, v.end + 3);
        if (folded[j] === '=' && folded[j + 1] === '=') {
          j = skWs(folded, j + 2);
          if (folded[j] === '(') j++;
          const num = rdNum(folded, j);
          if (num) return num.num;
        }
      }
    }
    from = at + 2;
  }
  return null;
}

function guessOp(ins) {
  if (!ins || ins.skipped) return 'UNKNOWN';
  return prefNm('UNKNOWN', ins, null, null, {});
}

function councn(body) {
  let n = 0;
  let i = 0;
  while (i < body.length) {
    if (body[i] === 'v' && isDig(body[i + 1] || '')) {
      let j = i + 1;
      while (j < body.length && isDig(body[j])) j++;
      if (body.slice(j, j + 2) === '<=' || body.slice(j, j + 2) === '==') n++;
      i = j;
      continue;
    }
    i++;
  }
  return n;
}

function anVm(source) {
  let dispatch;
  try {
    dispatch = findDisp(source);
  } catch {
    return {
      dispatch: null,
      ctx: {},
      opcodeMap: {},
      nameToOpcodes: {},
      closureLocalOp: null,
      opcodeCount: 0,
    };
  }

  const folded = dispatch.folded || foldConst(source);
  const ctx = infVmCtx(folded, dispatch);

  let map;
  try {
    ({ map } = parseDisp(dispatch.raw, dispatch.opVar));
  } catch {
    return {
      dispatch,
      ctx,
      opcodeMap: {},
      nameToOpcodes: {},
      closureLocalOp: findClosOp(folded),
      opcodeCount: 0,
    };
  }

  const opcodeMap = {};
  const nameToOpcodes = {};
  for (const [op, body] of map.entries()) {
    const name = refOpNm(clsH(body, ctx), body, ctx);
    if (councn(body) > 3 && op > 45) continue;
    opcodeMap[op] = { name, body: stripN(body).slice(0, 200) };
    if (!nameToOpcodes[name]) nameToOpcodes[name] = [];
    nameToOpcodes[name].push(op);
  }

  return {
    dispatch,
    ctx,
    opcodeMap,
    nameToOpcodes,
    closureLocalOp: findClosOp(folded),
    opcodeCount: Object.keys(opcodeMap).length,
  };
}

module.exports = {
  anVm,
  guessOp,
  refOpMap,
  prefNm,
  shpGuess,
  isGName,
  isBinK,
};
