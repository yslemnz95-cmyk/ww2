const { prefNm, shpGuess, guessOp, isGName, isBinK } = require('./vm');

function isSub(op) {
  if (!op || op.name === 'UNKNOWN' || op.name === 'CLOSE') return false;
  return [
    'CALL', 'TAILCALL', 'GETGLOBAL', 'SETGLOBAL', 'LOADK', 'SELF',
    'CLOSURE', 'SETTABLE', 'GETTABLE', 'ADD', 'SUB', 'MUL', 'DIV',
    'CONCAT', 'RETURN', 'NEWTABLE', 'SETLIST', 'LOADBOOL', 'TEST',
    'EQ', 'LT', 'LE', 'FORPREP', 'FORLOOP',
  ].includes(op.name);
}

function jmpsBefore(ops, i) {
  for (let j = 0; j < i; j++) {
    if (ops[j].name !== 'JMP') return false;
  }
  return true;
}

function resJmp(ops, byPc, b) {
  let guard = 0;
  let ti = byPc.get(b);
  while (ti != null && guard++ < 12) {
    const op = ops[ti];
    if (op.name === 'JMP' && typeof op.B === 'number' && op.B !== b) {
      b = op.B;
      ti = byPc.get(b);
      continue;
    }
    break;
  }
  return { ti, b };
}

function stripRedJmp(ops) {
  const out = [];
  for (let i = 0; i < ops.length; i++) {
    const op = ops[i];
    if (op.name !== 'JMP' || typeof op.B !== 'number') {
      out.push(op);
      continue;
    }
    if (i + 1 < ops.length && ops[i + 1].index === op.B) continue;
    if (out.length && out[out.length - 1].name === 'JMP' && out[out.length - 1].B === op.B) {
      continue;
    }
    out.push(op);
  }
  return out;
}

function stripFwdJmp(ops) {
  const byPc = new Map();
  ops.forEach((op, i) => byPc.set(op.index, i));

  const nop = new Set();
  for (let i = 0; i < ops.length; i++) {
    const op = ops[i];
    if (op.name !== 'JMP' || typeof op.B !== 'number') continue;
    const resolved = resJmp(ops, byPc, op.B);
    const ti = resolved.ti;
    if (ti == null || ti <= i) continue;

    let subst = 0;
    for (let j = i + 1; j < ti; j++) {
      if (isSub(ops[j])) subst++;
    }
    if (subst < 2) continue;

    let epiSubst = 0;
    for (let j = ti; j < Math.min(ti + 6, ops.length); j++) {
      if (isSub(ops[j]) && ops[j].name !== 'RETURN') epiSubst++;
    }

    
    if (jmpsBefore(ops, i) && subst >= 2) {
      nop.add(i);
      continue;
    }
    
    if (subst >= 2 && epiSubst <= 1) {
      nop.add(i);
    }
  }

  if (!nop.size) return ops;
  return ops.filter((_, i) => !nop.has(i));
}

function stripMutJmp(ops) {
  
  const byPc = new Map();
  ops.forEach((op, i) => byPc.set(op.index, i));
  const nop = new Set();
  for (let i = 0; i < ops.length; i++) {
    const a = ops[i];
    if (a.name !== 'JMP' || typeof a.B !== 'number') continue;
    const ti = byPc.get(a.B);
    if (ti == null) continue;
    const b = ops[ti];
    if (b.name === 'JMP' && b.B === a.index) {
      nop.add(i);
      nop.add(ti);
    }
  }
  if (!nop.size) return ops;
  return ops.filter((_, i) => !nop.has(i));
}

function stripBogRet(ops) {
  
  const nop = new Set();
  for (let i = 0; i < ops.length; i++) {
    const op = ops[i];
    if (op.name !== 'RETURN' && op.name !== 'TAILCALL') continue;
    if (i + 2 >= ops.length) continue;
    if (op.name === 'TAILCALL') continue;
    
    if (typeof op.B === 'number' && op.B >= 2) {
      let keep = false;
      for (let j = i + 1; j < Math.min(i + 5, ops.length); j++) {
        const n = ops[j];
        if (n.name === 'EQ' && typeof n.A === 'number' && n.A <= 4 && n.isKC) {
          keep = true;
          break;
        }
        if (n.name === 'LOADK' && n.B === 0 && typeof n.A === 'number' && n.A <= 4) {
          keep = true;
          break;
        }
      }
      if (keep) continue;
    }
    let subst = 0;
    for (let j = i + 1; j < ops.length; j++) {
      if (isSub(ops[j])) subst++;
    }
    if (subst >= 3) nop.add(i);
  }
  if (!nop.size) return ops;
  return ops.filter((_, i) => !nop.has(i));
}

function remapJmp(ops) {
  if (!ops.length) return ops;
  const present = new Set(ops.map((o) => o.index));
  const sorted = [...present].sort((a, b) => a - b);

  function resolve(b) {
    if (present.has(b)) return b;
    for (const ix of sorted) if (ix >= b) return ix;
    return sorted[sorted.length - 1];
  }

  let changed = false;
  const out = ops.map((op) => {
    if (!['JMP', 'EQ', 'LT', 'LE', 'TEST', 'TESTSET', 'FORLOOP', 'FORPREP'].includes(op.name)) {
      return op;
    }
    if (typeof op.B !== 'number') return op;
    const nb = resolve(op.B);
    if (nb === op.B) return op;
    changed = true;
    return Object.assign({}, op, { B: nb });
  });
  return changed ? out : ops;
}

function stripNil(ops) {
  
  const nop = new Set();
  for (let i = 0; i < ops.length; i++) {
    const op = ops[i];
    if (op.name !== 'LOADNIL') continue;
    const a = op.A;
    const to = typeof op.B === 'number' ? op.B : a;
    for (let j = i + 1; j < Math.min(i + 4, ops.length); j++) {
      const n = ops[j];
      if (!n) break;
      if (n.name === 'GETTABLE' && n.B === a) {
        nop.add(i);
        nop.add(j);
        if (ops[j + 1] && ops[j + 1].name === 'CALL' && ops[j + 1].A === n.A) nop.add(j + 1);
        break;
      }
      if (n.name === 'CALL' && n.A === a) {
        nop.add(i);
        nop.add(j);
        break;
      }
      if (n.name === 'LOADNIL') continue;
      if (['MOVE', 'JMP'].includes(n.name)) continue;
      break;
    }
    
    if (i === 0 && to >= a + 2) nop.add(i);
  }
  if (!nop.size) return ops;
  return ops.filter((_, i) => !nop.has(i));
}

function stripBack(ops) {
  
  const nop = new Set();
  for (let i = 0; i < ops.length; i++) {
    const op = ops[i];
    if (!['EQ', 'LT', 'LE'].includes(op.name)) continue;
    if (typeof op.A === 'number' && op.A > 32) nop.add(i);
  }
  if (!nop.size) return ops;
  return ops.filter((_, i) => !nop.has(i));
}

function linStCff(ops) {
  
  if (!ops || ops.length < 10) return ops;

  let stateReg = null;
  for (let i = 0; i < Math.min(6, ops.length); i++) {
    const op = ops[i];
    if (op.name === 'LOADK' && op.B === 0 && typeof op.A === 'number') {
      stateReg = op.A;
      break;
    }
  }
  if (stateReg == null) return ops;

  const byPc = new Map();
  ops.forEach((op, i) => byPc.set(op.index, i));

  const eqStates = [];
  for (let i = 0; i < ops.length; i++) {
    const op = ops[i];
    if (
      op.name === 'EQ'
      && op.A === stateReg
      && op.isKC
      && typeof op.C === 'number'
      && typeof op.B === 'number'
    ) {
      eqStates.push({ i, state: op.C, target: op.B });
    }
  }
  if (eqStates.length < 2) return ops;

  
  const blocks = new Map();
  for (const eq of eqStates) {
    let start = eq.i + 1;
    if (ops[start] && ops[start].name === 'JMP') start++;
    let end = ops.length;
    for (let j = start; j < ops.length; j++) {
      const op = ops[j];
      if (op.name === 'EQ' && op.A === stateReg && op.isKC) {
        end = j;
        break;
      }
      
      if (
        op.name === 'LOADK'
        && op.A === stateReg
        && typeof op.B === 'number'
        && op.B !== eq.state
      ) {
        end = j;
        break;
      }
    }
    if (end > start) blocks.set(eq.state, ops.slice(start, end));
  }

  if (blocks.size < 2) return ops;

  const ordered = [...blocks.keys()].sort((a, b) => a - b);
  const out = [];
  for (const s of ordered) {
    let block = blocks.get(s).slice();
    
    while (block.length) {
      const last = block[block.length - 1];
      if (last.name === 'JMP') {
        block.pop();
        continue;
      }
      if (last.name === 'LOADK' && last.A === stateReg) {
        block.pop();
        continue;
      }
      break;
    }
    out.push(...block);
  }
  
  const lastOrig = ops[ops.length - 1];
  if (lastOrig && lastOrig.name === 'RETURN' && (!out.length || out[out.length - 1].name !== 'RETURN')) {
    
    const hasRet = out.some((o) => o.name === 'RETURN');
    if (!hasRet) out.push(lastOrig);
  }
  return out.length >= 3 ? out : ops;
}

function cleanCfg(ops) {
  let cur = ops.slice();
  for (let pass = 0; pass < 4; pass++) {
    const n = cur.length;
    cur = stripFwdJmp(cur);
    cur = stripRedJmp(cur);
    cur = stripMutJmp(cur);
    cur = stripBogRet(cur);
    cur = stripNil(cur);
    cur = stripBack(cur);
    cur = remapJmp(cur);
    if (cur.length === n) break;
  }
  cur = remapJmp(cur);
  cur = linStCff(cur);
  return remapJmp(cur);
}

function jmpStats(ops) {
  let jmps = 0;
  const cleaned = cleanCfg(ops);
  for (const op of ops) if (op.name === 'JMP') jmps++;
  return { jmps, removed: ops.length - cleaned.length, before: ops.length, after: cleaned.length };
}


function indOf(line) {
  let i = 0;
  while (line[i] === ' ') i++;
  return line.slice(0, i);
}

function isNoise(e) {
  if (e == null) return true;
  const t = typeof e === 'string' ? e : String(e);
  if (!t || t === 'nil' || t === 'null' || t === '0') return true;
  if (t.startsWith('nil[') || t.startsWith('nil.') || t.startsWith('null[') || t.startsWith('null.')) return true;
  if (t.startsWith('0[')) return true;
  if (t.startsWith('{}(')) return true;
  return false;
}

function anPrUse(proto, ops) {
  let loadkStr = 0;
  let loadkNum = 0;
  let getG = 0;
  let getF = 0;
  let getU = 0;
  let calls = 0;
  let setG = 0;
  let setT = 0;
  let newT = 0;
  let clos = 0;
  let loops = 0;
  let rets = 0;

  const list = ops || [];
  for (let i = 0; i < list.length; i++) {
    const op = list[i];
    if (!op || !op.name) continue;
    switch (op.name) {
      case 'LOADK':
        if (typeof op.B === 'string' && op.B.length > 0) loadkStr++;
        else if (typeof op.B === 'number') loadkNum++;
        break;
      case 'GETGLOBAL':
        getG++;
        break;
      case 'GETTABLE':
      case 'SELF':
        getF++;
        break;
      case 'GETUPVAL':
        getU++;
        break;
      case 'CALL':
      case 'TAILCALL':
        calls++;
        break;
      case 'SETGLOBAL':
        setG++;
        break;
      case 'SETTABLE':
        setT++;
        break;
      case 'NEWTABLE':
        newT++;
        break;
      case 'CLOSURE':
        clos++;
        break;
      case 'FORPREP':
      case 'FORLOOP':
      case 'TFORLOOP':
        loops++;
        break;
      case 'RETURN':
        rets++;
        break;
      default:
        break;
    }
  }

  const interesting =
    loadkStr > 0
    || setG > 0
    || setT > 0
    || (newT > 0 && (setT > 0 || loops > 0))
    || (calls > 0 && loadkStr + setG + setT + newT > 0)
    || (clos > 0 && calls > 0);

  const xorStub =
    loadkStr === 0
    && setG === 0
    && setT === 0
    && getU >= 1
    && (getG + getF) >= 2
    && (loops > 0 || calls > 0);

  return {
    loadkStr,
    loadkNum,
    getG,
    getF,
    getU,
    calls,
    setG,
    setT,
    newT,
    clos,
    loops,
    rets,
    interesting,
    xorStub,
    score:
      loadkStr * 12
      + setG * 15
      + setT * 8
      + newT * 3
      + clos * 4
      + (calls > 0 && loadkStr > 0 ? 10 : 0)
      + (xorStub ? -40 : 0)
      + (interesting ? 5 : 0),
  };
}

function parseAsg(t) {
  if (t[0] !== 'r') return null;
  let i = 1;
  if (i >= t.length || t[i] < '0' || t[i] > '9') return null;
  while (i < t.length && t[i] >= '0' && t[i] <= '9') i++;
  if (t.slice(i, i + 3) !== ' = ') return null;
  return { lhs: t.slice(0, i), rhs: t.slice(i + 3) };
}

function colRegs(text, into) {
  for (let i = 0; i < text.length; i++) {
    if (text[i] !== 'r') continue;
    if (i > 0) {
      const p = text[i - 1];
      if ((p >= 'a' && p <= 'z') || (p >= 'A' && p <= 'Z') || (p >= '0' && p <= '9') || p === '_') continue;
    }
    let j = i + 1;
    if (j >= text.length || text[j] < '0' || text[j] > '9') continue;
    while (j < text.length && text[j] >= '0' && text[j] <= '9') j++;
    const n = text[j];
    if (n && ((n >= 'a' && n <= 'z') || (n >= 'A' && n <= 'Z') || n === '_')) continue;
    into.add(text.slice(i, j));
    i = j - 1;
  }
}

function rhsCall(rhs) {
  for (let i = 0; i < rhs.length; i++) {
    const c = rhs[i];
    if (c === '"' || c === "'") {
      const q = c;
      i++;
      while (i < rhs.length && rhs[i] !== q) {
        if (rhs[i] === '\\') i++;
        i++;
      }
      continue;
    }
    if (c === '(') return true;
  }
  return false;
}

function labExists(lines, lab) {
  const needle = '::' + lab + '::';
  for (let i = 0; i < lines.length; i++) {
    if (lines[i].trim() === needle) return true;
  }
  return false;
}

function dropEmptyIf(lines) {
  const out = [];
  for (let i = 0; i < lines.length; i++) {
    const t = lines[i].trim();
    if (t.startsWith('if ') && t.endsWith(' then')) {
      let j = i + 1;
      while (j < lines.length && !lines[j].trim()) j++;
      if (j < lines.length && lines[j].trim() === 'end' && indOf(lines[j]) === indOf(lines[i])) {
        i = j;
        continue;
      }
    }
    out.push(lines[i]);
  }
  return out;
}

function finLines(lines) {
  const used = new Set();
  const keep = new Array(lines.length).fill(false);
  const demote = new Array(lines.length).fill(false);

  for (let i = lines.length - 1; i >= 0; i--) {
    const t = lines[i].trim();
    if (!t) {
      keep[i] = false;
      continue;
    }
    if (t.startsWith('--')) {
      keep[i] = true;
      continue;
    }
    if (t.startsWith('::') && t.endsWith('::')) {
      keep[i] = used.has('#' + t.slice(2, -2));
      continue;
    }
    if (t.startsWith('goto ')) {
      const lab = t.slice(5);
      if (!labExists(lines, lab)) {
        keep[i] = false;
        continue;
      }
      keep[i] = true;
      used.add('#' + lab);
      continue;
    }
    const asg = parseAsg(t);
    if (asg) {
      const live = used.has(asg.lhs);
      const call = rhsCall(asg.rhs);
      const keepBind = asg.rhs.startsWith('{') || isId(asg.rhs);
      if (live || keepBind) {
        keep[i] = true;
        used.delete(asg.lhs);
        colRegs(asg.rhs, used);
      } else if (call) {
        keep[i] = true;
        demote[i] = true;
        colRegs(asg.rhs, used);
      } else {
        keep[i] = false;
      }
      continue;
    }
    keep[i] = true;
    colRegs(t, used);
  }

  const out = [];
  for (let i = 0; i < lines.length; i++) {
    if (!keep[i]) continue;
    const raw = lines[i];
    if (demote[i]) {
      const asg = parseAsg(raw.trim());
      if (asg) {
        out.push(indOf(raw) + asg.rhs);
        continue;
      }
    }
    out.push(raw);
  }
  return dropEmptyIf(out);
}

function escStr(s) {
  return JSON.stringify(String(s));
}

function fmtK(v) {
  if (typeof v === 'string') return escStr(v);
  if (typeof v === 'boolean') return v ? 'true' : 'false';
  if (typeof v === 'number') {
    if (!Number.isFinite(v)) return String(v);
    if (Number.isInteger(v)) return String(v);
    return String(v);
  }
  if (v == null) return 'nil';
  return escStr(String(v));
}

function reg(n) {
  return `r${n}`;
}

function annPr(proto, opcodeMap, closureLocalOp) {
  const out = [];
  const instructions = proto.instructions;
  let i = 1;
  while (i < instructions.length) {
    const ins = instructions[i];
    if (!ins || ins.skipped) {
      i++;
      continue;
    }
    ins._index = i;
    const info = opcodeMap[ins.opcode] || { name: 'UNKNOWN' };
    let name = info.name;
    if (name === 'GETGLOBAL_OR_UPVAL') name = 'GETGLOBAL';
    if (name === 'UNKNOWN') name = guessOp(ins);
    name = prefNm(name, ins, proto, closureLocalOp, opcodeMap);

    
    if (
      name === 'CALL' &&
      typeof ins.B === 'number' &&
      ins.B >= 1 &&
      ins.C === 1
    ) {
      let sawTable = false;
      let loads = 0;
      for (let j = i - 1; j >= Math.max(1, i - 12); j--) {
        const p = instructions[j];
        if (!p || p.skipped) continue;
        const pn = prefNm((opcodeMap[p.opcode] || {}).name || 'UNKNOWN', p, proto, closureLocalOp, opcodeMap);
        if (pn === 'NEWTABLE' && p.A === ins.A) {
          sawTable = true;
          break;
        }
        if (pn === 'LOADK' || pn === 'MOVE' || pn === 'LOADBOOL') {
          if (typeof p.A === 'number' && p.A > ins.A && p.A <= ins.A + ins.B) loads++;
          continue;
        }
        break;
      }
      if (sawTable && loads >= 1) name = 'SETLIST';
    }
    
    if (name === 'SETLIST' && typeof ins.B === 'number' && typeof ins.A === 'number' && ins.B > ins.A + 8) {
      name = 'CALL';
    }

    if (name === 'SELF' && typeof ins.C === 'number' && ins.C > 0 && typeof ins.B === 'number') {
      const protoIdx = ins.B;
      if (proto.prototypes[protoIdx]) {
        let looksUp = true;
        for (let u = 0; u < ins.C; u++) {
          const next = instructions[i + 1 + u];
          if (!next || next.skipped) {
            looksUp = false;
            break;
          }
          const n = (opcodeMap[next.opcode] || {}).name;
          if (closureLocalOp != null && next.opcode === closureLocalOp) continue;
          if (n === 'MOVE' || n === 'GETUPVAL') continue;
          if (next.mode === 0 && !next.isKB && !next.isKC) continue;
          looksUp = false;
          break;
        }
        if (looksUp) name = 'CLOSURE';
      }
    }

    
    if ((name === 'TAILCALL' || name === 'RETURN') && ins.B === 0 && (ins.C === 0 || ins.C == null) && i + 3 < instructions.length) {
      const mapName = (opcodeMap[ins.opcode] && opcodeMap[ins.opcode].name) || 'UNKNOWN';
      if (mapName === 'RETURN' || mapName === 'TAILCALL') {
        
      } else {
        const shape = shpGuess(ins, proto, closureLocalOp, opcodeMap);
        if (!shape || shape.conf < 60 || shape.name === 'UNKNOWN') {
          name = mapName !== 'UNKNOWN' ? mapName : 'MOVE';
        }
      }
    }

    if (name === 'CLOSURE') {
      const nups = typeof ins.C === 'number' ? ins.C : 0;
      const pidx = typeof ins.B === 'number' ? ins.B : -1;
      if (nups < 0 || nups > 32 || !proto.prototypes[pidx]) {
        name = 'UNKNOWN';
      } else {
        const upvals = [];
        for (let u = 0; u < nups; u++) {
          const next = instructions[i + 1 + u];
          if (!next || next.skipped) continue;
          const isLocal = closureLocalOp != null
            ? next.opcode === closureLocalOp
            : (opcodeMap[next.opcode] && opcodeMap[next.opcode].name === 'MOVE');
          upvals.push({ isLocal: !!isLocal, idx: next.B });
        }
        out.push({
          index: i,
          opcode: ins.opcode,
          name,
          A: ins.A,
          B: ins.B,
          C: ins.C,
          isKA: ins.isKA,
          isKB: ins.isKB,
          isKC: ins.isKC,
          mode: ins.mode,
          upvals,
          skip: nups,
        });
        i += 1 + nups;
        continue;
      }
    }

    out.push({
      index: i,
      opcode: ins.opcode,
      name,
      A: ins.A,
      B: ins.B,
      C: ins.C,
      isKA: ins.isKA,
      isKB: ins.isKB,
      isKC: ins.isKC,
      mode: ins.mode,
    });
    i += 1;
  }
  return out;
}

function idxOrK(v, isK) {
  if (typeof v === 'string' || isK) return fmtK(v);
  if (typeof v === 'number') return reg(v);
  return fmtK(v);
}

function liftIns(ins, protoName) {
  const { A, B, C } = ins;
  const ra = typeof A === 'number' ? reg(A) : fmtK(A);

  switch (ins.name) {
    case 'MOVE':
      return `${ra} = ${reg(B)}`;
    case 'LOADK':
      return `${ra} = ${fmtK(B)}`;
    case 'LOADBOOL':
      return `${ra} = ${B ? 'true' : 'false'}`;
    case 'LOADNIL': {
      const parts = [];
      const to = typeof B === 'number' ? B : A;
      for (let i = A; i <= to; i++) parts.push(`${reg(i)} = nil`);
      return parts.join('; ');
    }
    case 'GETUPVAL':
      return `${ra} = upval_${B}`;
    case 'GETGLOBAL':
      return `${ra} = _ENV[${fmtK(B)}]`;
    case 'GETTABLE':
      return `${ra} = ${reg(B)}[${idxOrK(C, ins.isKC)}]`;
    case 'SETGLOBAL':
      return `_ENV[${fmtK(B)}] = ${ra}`;
    case 'SETUPVAL':
      return `upval_${B} = ${ra}`;
    case 'SETTABLE':
      return `${reg(A)}[${idxOrK(B, ins.isKB)}] = ${idxOrK(C, ins.isKC)}`;
    case 'NEWTABLE':
      return `${ra} = {}`;
    case 'SELF':
      return `${reg(A + 1)} = ${reg(B)}; ${ra} = ${reg(B)}[${idxOrK(C, ins.isKC)}]`;
    case 'ADD':
      return `${ra} = ${reg(B)} + ${reg(C)}`;
    case 'SUB':
      return `${ra} = ${reg(B)} - ${reg(C)}`;
    case 'MUL':
      return `${ra} = ${reg(B)} * ${reg(C)}`;
    case 'DIV':
      return `${ra} = ${reg(B)} / ${reg(C)}`;
    case 'MOD':
      return `${ra} = ${reg(B)} % ${reg(C)}`;
    case 'POW':
      return `${ra} = ${reg(B)} ^ ${reg(C)}`;
    case 'UNM':
      return `${ra} = -${reg(B)}`;
    case 'NOT':
      return `${ra} = not ${reg(B)}`;
    case 'LEN':
      return `${ra} = #${reg(B)}`;
    case 'CONCAT':
      return `${ra} = ${reg(B)} .. ${reg(C)}`;
    case 'JMP':
      return `goto lbl_${B}`;
    case 'EQ':
      return `if ${ra} == ${fmtK(C)} then else goto lbl_${B} end`;
    case 'LT':
      return `if ${ra} < ${fmtK(C)} then else goto lbl_${B} end`;
    case 'LE':
      return `if ${ra} <= ${fmtK(C)} then else goto lbl_${B} end`;
    case 'TEST':
      return `if ${ra} then else goto lbl_${B} end`;
    case 'CALL': {
      if (B == null || B === 0) return `${ra} = ${ra}(${reg(A + 1)}, ...)`;
      if (B === 1) return `${ra} = ${ra}()`;
      if (typeof B === 'number' && B >= 2) {
        const args = [];
        for (let i = A + 1; i <= A + B - 1; i++) args.push(reg(i));
        return `${ra} = ${ra}(${args.join(', ')})`;
      }
      return `${ra} = ${ra}()`;
    }
    case 'TAILCALL': {
      if (B === 1) return `return ${ra}()`;
      if (typeof B === 'number' && B >= 2) {
        const args = [];
        for (let i = A + 1; i <= A + B - 1; i++) args.push(reg(i));
        return `return ${ra}(${args.join(', ')})`;
      }
      return `return ${ra}()`;
    }
    case 'RETURN': {
      if (B === 1 || B === 0) return 'return';
      if (typeof B === 'number' && B > 1) {
        const vals = [];
        for (let i = A; i <= A + B - 2; i++) vals.push(reg(i));
        return `return ${vals.join(', ')}`;
      }
      return `return ${ra}`;
    }
    case 'CLOSURE': {
      const fname = `${protoName}_f${B}`;
      return `${ra} = ${fname}`;
    }
    case 'SETLIST':
      return 'do end';
    case 'VARARG':
      return `${ra} = ...`;
    case 'CLOSE':
      return 'do end';
    default:
      return 'do end';
  }
}

function liftPr(proto, opcodeMap, closureLocalOp, protoName = 'main', ind = 0) {
  const sp = '  '.repeat(ind);
  const lines = [];
  const annotated = annPr(proto, opcodeMap, closureLocalOp);
  const params = [];
  for (let p = 0; p < proto.params; p++) params.push(reg(p));

  lines.push(`${sp}function ${protoName}(${params.join(', ')})`);

  for (let pi = 0; pi < proto.prototypes.length; pi++) {
    if (!proto.prototypes[pi]) continue;
    lines.push(liftPr(proto.prototypes[pi], opcodeMap, closureLocalOp, `${protoName}_f${pi}`, ind + 1));
  }

  const labels = new Set();
  for (const ins of annotated) {
    if (['JMP', 'EQ', 'LT', 'LE', 'TEST'].includes(ins.name) && typeof ins.B === 'number') {
      labels.add(ins.B);
    }
  }

  for (const ins of annotated) {
    if (labels.has(ins.index)) lines.push(`${sp}  ::lbl_${ins.index}::`);
    lines.push(`${sp}  ${liftIns(ins, protoName)}`);
  }

  lines.push(`${sp}end`);
  return lines.join('\n');
}

function liftProg(root, opcodeMap, closureLocalOp) {
  return [
    liftPr(root, opcodeMap, closureLocalOp, 'main', 0),
    '',
    'return main()',
  ].join('\n');
}

function disasmPr(proto, opcodeMap, closureLocalOp, name = 'main', ind = 0) {
  const sp = '  '.repeat(ind);
  const lines = [];
  lines.push(`${sp}.proto ${name} params=${proto.params}`);
  const consts = proto.constants
    .map((c, i) => (i ? `${i}=${fmtK(c)}` : null))
    .filter(Boolean);
  lines.push(`${sp}.constants ${consts.join(', ')}`);
  const annotated = annPr(proto, opcodeMap, closureLocalOp);
  for (const ins of annotated) {
    lines.push(
      `${sp}[${String(ins.index).padStart(3)}] ${ins.name.padEnd(10)} A=${JSON.stringify(ins.A)} B=${JSON.stringify(ins.B)} C=${JSON.stringify(ins.C)}`
      + (ins.upvals ? ` upvals=${JSON.stringify(ins.upvals)}` : '')
    );
  }
  for (let i = 0; i < proto.prototypes.length; i++) {
    if (!proto.prototypes[i]) continue;
    lines.push(disasmPr(proto.prototypes[i], opcodeMap, closureLocalOp, `${name}_f${i}`, ind + 1));
  }
  return lines.join('\n');
}


function isId(s) {
  if (typeof s !== 'string' || !s.length) return false;
  const c0 = s.charCodeAt(0);
  if (!((c0 >= 65 && c0 <= 90) || (c0 >= 97 && c0 <= 122) || c0 === 95)) return false;
  for (let i = 1; i < s.length; i++) {
    const c = s.charCodeAt(i);
    if (!((c >= 65 && c <= 90) || (c >= 97 && c <= 122) || (c >= 48 && c <= 57) || c === 95)) return false;
  }
  return true;
}

function ind(n) {
  return '  '.repeat(n);
}

function gName(key) {
  if (isId(key)) return key;
  return `_ENV[${fmtK(key)}]`;
}

function field(base, key, isK) {
  if ((typeof key === 'string' || isK) && isId(key)) return `${base}.${key}`;
  if (typeof key === 'string' || isK) return `${base}[${fmtK(key)}]`;
  if (typeof key === 'number' && isK) return `${base}[${key}]`;
  if (typeof key === 'number') return `${base}[${reg(key)}]`;
  return `${base}[${fmtK(key)}]`;
}

function lit(v) {
  if (typeof v === 'string') return fmtK(v);
  if (typeof v === 'boolean') return v ? 'true' : 'false';
  if (typeof v === 'number') return String(v);
  if (v == null) return 'nil';
  return fmtK(v);
}

function rk(v, isK, regs) {
  if (isK || typeof v === 'string' || typeof v === 'boolean') return lit(v);
  if (v == null) return 'nil';
  if (typeof v === 'number') return regs.get(v) || reg(v);
  return lit(v);
}

function callArgs(op, regs, defined) {
  const { A, B, C } = op;
  
  if (
    typeof B === 'number'
    && B >= A + 1
    && B <= A + 8
    && (C === 0 || C == null || C === 1 || C === 2)
  ) {
    const out = [];
    for (let r = A + 1; r <= B; r++) {
      const e = regs.get(r) || reg(r);
      if (defined && e === reg(r) && !defined.has(r)) continue;
      if (e === 'nil') continue;
      out.push(e);
    }
    return out;
  }
  
  if (B == null || B === 0) {
    
    if (defined && defined.has(A + 1)) {
      const e = regs.get(A + 1) || reg(A + 1);
      if (e !== 'nil') return [e];
    }
    for (let r = A + 2; r <= A + 8; r++) {
      if (!defined || !defined.has(r)) continue;
      const e = regs.get(r) || reg(r);
      if (e !== 'nil') return [e];
    }
    return [];
  }
  if (B === 1) return [];
  if (typeof B === 'number' && B >= 2) {
    const out = [];
    for (let r = A + 1; r <= A + B - 1; r++) {
      const e = regs.get(r) || reg(r);
      if (defined && e === reg(r) && !defined.has(r)) continue;
      out.push(e);
    }
    while (out.length && out[out.length - 1] === 'nil') out.pop();
    while (out.length && out[0] === 'nil') out.shift();
    return out;
  }
  return [];
}

function jmpTgts(ops) {
  const t = new Set();
  for (const op of ops) {
    if (['JMP', 'EQ', 'LT', 'LE', 'TEST', 'TESTSET', 'FORLOOP', 'FORPREP'].includes(op.name)) {
      if (typeof op.B === 'number') t.add(op.B);
    }
  }
  return t;
}

function byIdx(ops) {
  const m = new Map();
  ops.forEach((op, i) => m.set(op.index, i));
  return m;
}

function cmpSym(n) {
  if (n === 'EQ') return '==';
  if (n === 'LT') return '<';
  if (n === 'LE') return '<=';
  return null;
}

function tidy(lines) {
  const text = lines.join('\n');
  const out = [];
  let dead = false;
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const t = line.trim();
    if (!t) continue;
    if (t.startsWith('::') && t.endsWith('::')) {
      dead = false;
      const lab = t.slice(2, -2);
      if (!text.includes(`goto ${lab}`)) continue;
      out.push(line);
      continue;
    }
    if (dead) continue;
    if (t === 'return' && out.length && out[out.length - 1].trim().startsWith('return')) continue;
    if (t.startsWith('goto L')) {
      const lab = t.slice(5);
      let j = i + 1;
      while (j < lines.length && !lines[j].trim()) j++;
      if (j < lines.length && lines[j].trim() === `::${lab}::`) continue;
      out.push(line);
      dead = true;
      continue;
    }
    if (t === 'return' || t.startsWith('return ')) {
      out.push(line);
      dead = true;
      continue;
    }
    out.push(line);
  }
  return out;
}

function foldLn(lines) {
  const out = [];
  for (let i = 0; i < lines.length; i++) {
    const a = matchAsg(lines[i]);
    const b = i + 1 < lines.length ? matchAsg(lines[i + 1]) : null;
    if (a && b && a.left === b.left) {
      if (b.right.startsWith(a.left + '.') || b.right.startsWith(a.left + '[')) {
        out.push(`${a.ind}${a.left} = ${a.right}${b.right.slice(a.left.length)}`);
        i++;
        continue;
      }
    }
    out.push(lines[i]);
  }
  return out;
}

function matchAsg(line) {
  let i = 0;
  while (line[i] === ' ') i++;
  if (line[i] !== 'r') return null;
  let j = i + 1;
  while (j < line.length && line[j] >= '0' && line[j] <= '9') j++;
  const left = line.slice(i, j);
  if (line.slice(j, j + 3) !== ' = ') return null;
  return { ind: line.slice(0, i), left, right: line.slice(j + 3) };
}

function reconPr(proto, opcodeMap, closureLocalOp, fname, upvals, depth) {
  let ops = annPr(proto, opcodeMap, closureLocalOp);
  ops = cleanCfg(ops);
  const targets = jmpTgts(ops);
  const idx = byIdx(ops);
  const regs = new Map();
  const defined = new Set();
  for (let p = 0; p < proto.params; p++) {
    regs.set(p, reg(p));
    defined.add(p);
  }

  const childNames = {};
  for (let i = 0; i < proto.prototypes.length; i++) {
    if (proto.prototypes[i]) childNames[i] = `${fname}_f${i}`;
  }

  const closureBinds = [];
  const lines = [];
  const sp = ind(depth);
  const bsp = ind(depth + 1);

  let i = 0;
  while (i < ops.length) {
    const op = ops[i];

    if (targets.has(op.index)) lines.push(`${bsp}::L${op.index}::`);

    const asFor = tryNumFor(ops, i, idx, targets, regs, defined, depth + 1, upvals, childNames, closureBinds);
    if (asFor) {
      lines.push(...asFor.lines);
      i = asFor.next;
      continue;
    }

    const asGfor = tryGenFor(ops, i, idx, targets, regs, defined, depth + 1, upvals, childNames, closureBinds);
    if (asGfor) {
      lines.push(...asGfor.lines);
      i = asGfor.next;
      continue;
    }

    
    const structured = tryIf(ops, i, idx, targets, regs, defined, depth + 1, upvals, childNames, closureBinds);
    if (structured) {
      lines.push(...structured.lines);
      i = structured.next;
      continue;
    }

    const em = step(op, ops, i, regs, defined, depth + 1, upvals, childNames, closureBinds);
    if (em.lines) lines.push(...em.lines);
    i += 1 + (em.skip || 0);
  }

  
  const body = finLines(tidy(foldLn(lines)));
  const bodyText = body.join('\n');
  const nested = [];
  for (let pi = 0; pi < proto.prototypes.length; pi++) {
    if (!proto.prototypes[pi]) continue;
    const child = proto.prototypes[pi];
    const cname = childNames[pi];
    const childOps = cleanCfg(annPr(child, opcodeMap, closureLocalOp));
    const childUsage = anPrUse(child, childOps);
    if (childUsage.xorStub && !childUsage.interesting) continue;
    const bound = closureBinds.some((b) => b.idx === pi);
    if (!bodyText.includes(cname) && !bound) continue;
    const bind = closureBinds.filter((b) => b.idx === pi).pop();
    const ups = bind ? bind.ups : defUps(child, opcodeMap, closureLocalOp);
    const src = reconPr(child, opcodeMap, closureLocalOp, cname, ups, depth + 1);
    if (isEmptyFn(src)) continue;
    nested.push(src);
  }

  const keptNames = new Set();
  for (const n of nested) {
    const k = fnNmOf(n);
    if (k) keptNames.add(k);
  }
  const body2 = body.filter((l) => {
    const t = l.trim();
    if (t[0] !== 'r') return true;
    const spn = t.indexOf(' = ');
    if (spn < 0) return true;
    const rhs = t.slice(spn + 3);
    
    if (isPlnLine(rhs) && rhs.startsWith(fname) && !keptNames.has(rhs)) return false;
    return true;
  });

  const params = [];
  for (let p = 0; p < proto.params; p++) params.push(reg(p));

  const early = [];
  const late = [];
  for (const l of body2) {
    const t = l.trim();
    let plain = null;
    if (t[0] === 'r') {
      let j = 1;
      while (j < t.length && t[j] >= '0' && t[j] <= '9') j++;
      if (t.slice(j, j + 3) === ' = ') plain = t.slice(j + 3);
    }
    if (plain != null && !plain.includes('(') && isPlnLine(plain)) {
      early.push(l);
    } else if (plain != null && !plain.includes('(') && plain.startsWith('{')) {
      early.push(l);
    } else {
      late.push(l);
    }
  }

  const out = [
    `${sp}local function ${fname}(${params.join(', ')})`,
    ...early,
    ...nested,
    ...late,
    `${sp}end`,
  ].join('\n');
  return out;
}

function isPlnLine(s) {
  if (!s || !s.length) return false;
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

function fnNmOf(src) {
  const i = src.indexOf('function ');
  if (i < 0) return null;
  let j = i + 9;
  if (src.startsWith('local function ', i)) j = i + 15;
  let k = j;
  while (k < src.length && src[k] !== '(') k++;
  const name = src.slice(j, k).trim();
  return name || null;
}

function colWs(src) {
  let out = '';
  let sp = false;
  for (let i = 0; i < src.length; i++) {
    const ch = src[i];
    if (ch === ' ' || ch === '\t' || ch === '\n' || ch === '\r') {
      if (!sp && out.length) {
        out += ' ';
        sp = true;
      }
    } else {
      out += ch;
      sp = false;
    }
  }
  return out;
}

function isEmptyFn(src) {
  const flat = colWs(src).trim();
  if (!flat.includes('while true do')) return false;
  if (flat.includes('while true do end')) return true;
  if (flat.includes('while true do {} end')) return true;
  if (flat.includes('while true do table.insert({}) end')) return true;
  const a = flat.indexOf('while true do');
  if (a < 0) return false;
  const b = flat.lastIndexOf('end');
  if (b <= a) return false;
  const body = flat.slice(a + 13, b).trim();
  return !body || body === '{}' || body === 'table.insert({})';
}

function defUps(proto, opcodeMap, closureLocalOp) {
  const ops = annPr(proto, opcodeMap, closureLocalOp);
  let max = -1;
  for (const op of ops) {
    if ((op.name === 'GETUPVAL' || op.name === 'SETUPVAL') && typeof op.B === 'number' && op.B > max) {
      max = op.B;
    }
  }
  const ups = [];
  for (let i = 0; i <= max; i++) ups[i] = `up${i}`;
  return ups;
}

function parseNum(t) {
  if (!t) return null;
  let i = 0;
  let neg = false;
  if (t[i] === '-') {
    neg = true;
    i++;
  }
  if (i >= t.length || t[i] < '0' || t[i] > '9') return null;
  let j = i;
  while (j < t.length && t[j] >= '0' && t[j] <= '9') j++;
  if (t[j] === '.') {
    j++;
    if (j >= t.length || t[j] < '0' || t[j] > '9') return null;
    while (j < t.length && t[j] >= '0' && t[j] <= '9') j++;
  }
  if (j !== t.length) return null;
  const n = Number(t.slice(i));
  return neg ? -n : n;
}

function parseBin(t, op) {
  let s = t.trim();
  if (s[0] === '(' && s[s.length - 1] === ')') s = s.slice(1, -1).trim();
  let k = -1;
  for (let i = 1; i < s.length; i++) {
    if (s[i] === op[0] && (op.length === 1 || s.slice(i, i + op.length) === op)) {
      const left = parseNum(s.slice(0, i).trim());
      const right = parseNum(s.slice(i + op.length).trim());
      if (left != null && right != null) {
        k = i;
        return op === '+' ? left + right : left - right;
      }
    }
  }
  return null;
}

function parseStat(expr) {
  if (typeof expr === 'number') return expr;
  if (typeof expr !== 'string') return null;
  const t = expr.trim();
  const n = parseNum(t);
  if (n != null) return n;
  if (t === 'true') return true;
  if (t === 'false') return false;
  const add = parseBin(t, '+');
  if (add != null) return add;
  const sub = parseBin(t, '-');
  if (sub != null) return sub;
  return null;
}

function evalCmp(name, left, right) {
  const a = parseStat(left);
  const b = parseStat(right);
  if (a == null || b == null) return null;
  if (name === 'EQ') return a === b;
  if (name === 'LT') return a < b;
  if (name === 'LE') return a <= b;
  return null;
}

function cmpl(op, regs) {
  
  if (op.isKA && typeof op.A === 'number') return lit(op.A);
  return regs.get(op.A) || reg(op.A);
}

function cmpr(op, regs) {
  if (op.name === 'TEST') return null;
  
  if (op.isKA && typeof op.C === 'number' && !op.isKC) {
    return regs.get(op.C) || reg(op.C);
  }
  return rk(op.C, op.isKC, regs);
}

function tryNumFor(ops, i, idx, targets, regs, defined, depth, upvals, childNames, closureBinds) {
  const op = ops[i];
  if (op.name !== 'FORPREP' || typeof op.B !== 'number') return null;
  const loopI = idx.get(op.B);
  if (loopI == null || loopI <= i) return null;
  const loopOp = ops[loopI];
  if (!loopOp || loopOp.name !== 'FORLOOP') return null;

  const A = op.A;
  const init = regs.get(A) || reg(A);
  const limit = regs.get(A + 1) || reg(A + 1);
  const step = regs.get(A + 2) || reg(A + 2);
  const varR = A + 3;
  const sp = ind(depth);

  const bodyRegs = new Map(regs);
  const bodyDef = new Set(defined);
  bodyRegs.set(varR, reg(varR));
  bodyDef.add(varR);
  bodyDef.add(A);
  bodyDef.add(A + 1);
  bodyDef.add(A + 2);

  
  
  const ne = matcnns(ops, i + 1, loopI, varR, bodyRegs);
  let bodyLines;
  if (ne) {
    bodyLines = [`${ind(depth + 1)}${ne}`];
  } else {
    bodyLines = emitSl(
      ops,
      i + 1,
      loopI,
      bodyRegs,
      bodyDef,
      depth + 1,
      upvals,
      childNames,
      closureBinds,
      targets
    );
    const neat = recNeStore(bodyLines, varR);
    if (neat) bodyLines = neat;
  }

  const stepLit = parseStat(step);
  const header =
    stepLit === 1 || step === '1'
      ? `${sp}for ${reg(varR)} = ${init}, ${limit} do`
      : `${sp}for ${reg(varR)} = ${init}, ${limit}, ${step} do`;

  for (const [k, v] of bodyRegs) regs.set(k, v);
  for (const k of bodyDef) defined.add(k);

  return {
    lines: [header, ...bodyLines, `${sp}end`],
    next: loopI + 1,
  };
}

function matcnns(ops, from, to, varR, regs) {
  
  for (let i = from; i < to - 2; i++) {
    const eq = ops[i];
    if (!eq || eq.name !== 'EQ' || !eq.isKA) continue;
    const left = cmpl(eq, regs);
    const right = cmpr(eq, regs);
    if (String(left) !== '1' && left !== 1) continue;
    if (right !== reg(varR)) continue;

    
    let fb = null;
    let tb = null;
    let st = null;
    for (let j = i + 1; j < to; j++) {
      const o = ops[j];
      if (!o) continue;
      if (o.name === 'JMP') continue;
      if (o.name === 'LOADBOOL' && o.B === 0 && fb == null) {
        fb = o;
        continue;
      }
      if (o.name === 'LOADBOOL' && o.B === 1 && fb && tb == null) {
        tb = o;
        continue;
      }
      if (o.name === 'SETTABLE' && fb && tb && o.B === varR && o.C === fb.A) {
        st = o;
        break;
      }
      if (o.name === 'SETTABLE' && fb && tb && o.B === varR) {
        st = o;
        break;
      }
      if (!['LOADBOOL', 'EQ', 'JMP'].includes(o.name) && st == null && tb) break;
    }
    if (st) {
      const base = regs.get(st.A) || reg(st.A);
      return `${base}[${reg(varR)}] = (1 ~= ${reg(varR)})`;
    }
  }
  return null;
}

function leadWs(s) {
  let i = 0;
  while (i < s.length && (s[i] === ' ' || s[i] === '\t')) i++;
  return s.slice(0, i);
}

function isFalsAsg(a) {
  if (!a || a.length < 10) return null;
  if (!a.startsWith('r') || !a.endsWith(' = false')) return null;
  let i = 1;
  while (i < a.length && a[i] >= '0' && a[i] <= '9') i++;
  if (i === 1 || a.slice(i) !== ' = false') return null;
  return a.slice(1, i);
}

function isTrueAsg(a, n) {
  return a === `r${n} = true`;
}

function isStoreFr(a, n, vr) {
  const needle = `[${vr}] = r${n}`;
  const k = a.indexOf(needle);
  if (k <= 0) return null;
  const left = a.slice(0, k);
  if (!left.startsWith('r')) return null;
  let i = 1;
  while (i < left.length && left[i] >= '0' && left[i] <= '9') i++;
  if (i !== left.length) return null;
  return left;
}

function recNeStore(lines, varR) {
  if (!lines || lines.length < 1) return null;
  const vr = reg(varR);
  const out = [];
  let i = 0;
  let changed = false;
  while (i < lines.length) {
    const a = lines[i] && lines[i].trim();
    const b = lines[i + 1] && lines[i + 1].trim();
    const c = lines[i + 2] && lines[i + 2].trim();
    const n = isFalsAsg(a);
    const okT = n && b && isTrueAsg(b, n);
    const left = okT && c ? isStoreFr(c, n, vr) : null;
    if (n && okT && left) {
      out.push(`${leadWs(lines[i + 2])}${left}[${vr}] = (1 ~= ${vr})`);
      i += 3;
      changed = true;
      continue;
    }
    if (a && a.startsWith('if 1 == ') && a.includes('then else goto')) {
      i++;
      changed = true;
      continue;
    }
    out.push(lines[i]);
    i++;
  }
  return changed ? out : null;
}

function tryGenFor(ops, i, idx, targets, regs, defined, depth, upvals, childNames, closureBinds) {
  const op = ops[i];
  
  if (!(op.name === 'CALL' || (op.name === 'TFORLOOP' && op.mode !== 3))) return null;
  const jmp = ops[i + 1];
  if (!jmp || jmp.name !== 'JMP' || typeof jmp.B !== 'number') return null;

  const A = op.A;
  
  let tforI = null;
  for (let j = i + 2; j < ops.length; j++) {
    const n = ops[j];
    if (n.name === 'TFORLOOP' && (n.mode === 3 || typeof n.B === 'number') && n.A === A) {
      
      tforI = j;
      if (n.mode === 3) break;
    }
  }
  if (tforI == null) return null;
  const tfor = ops[tforI];
  const nvars = typeof tfor.C === 'number' && tfor.C > 0 ? Math.min(tfor.C, 4) : 2;

  
  const bodyStart = i + 2;
  const bodyEnd = tforI;

  const bodyRegs = new Map(regs);
  const bodyDef = new Set(defined);
  
  const gen = bodyRegs.get(A) || reg(A);
  const state = bodyRegs.get(A + 1) || reg(A + 1);
  for (let v = 0; v < nvars; v++) {
    bodyDef.add(A + 3 + v);
    bodyRegs.set(A + 3 + v, reg(A + 3 + v));
  }

  const bodyLines = emitSl(
    ops,
    bodyStart,
    bodyEnd,
    bodyRegs,
    bodyDef,
    depth + 1,
    upvals,
    childNames,
    closureBinds,
    targets
  );

  const sp = ind(depth);
  const vars = [];
  for (let v = 0; v < nvars; v++) vars.push(reg(A + 3 + v));

  
  let iterExpr = null;
  const callFn = regs.get(A);
  if (typeof callFn === 'string' && callFn.includes('pairs')) {
    iterExpr = callFn.includes('(') ? callFn : `${callFn}(${regs.get(A + 1) || reg(A + 1)})`;
  } else if (callFn === 'pairs' || regs.get(A) === 'pairs') {
    iterExpr = `pairs(${regs.get(A + 1) || state})`;
  } else {
    const prev = regs.get(A);
    if (typeof prev === 'string' && prev.startsWith('pairs(')) iterExpr = prev;
  }

  if (!iterExpr) {
    iterExpr = `${getSafe(regs, A)}(${getSafe(regs, A + 1)})`;
  }

  const fnBefore = regs.get(A);
  const argBefore = regs.get(A + 1);
  if (fnBefore === 'pairs' && argBefore) {
    iterExpr = `pairs(${argBefore})`;
  } else if (typeof fnBefore === 'string' && fnBefore.startsWith('pairs(')) {
    iterExpr = fnBefore;
  }

  for (const [k, v] of bodyRegs) regs.set(k, v);
  for (const k of bodyDef) defined.add(k);

  
  let next = tforI + 1;
  if (ops[next] && ops[next].name === 'JMP' && typeof ops[next].B === 'number') {
    const back = idx.get(ops[next].B);
    if (back != null && back >= i && back <= tforI) next++;
  }

  return {
    lines: [`${sp}for ${vars.join(', ')} in ${iterExpr} do`, ...bodyLines, `${sp}end`],
    next,
  };
}

function getSafe(regs, r) {
  return regs.get(r) || reg(r);
}

function thentii(ops, elseI) {
  const t = ops[elseI];
  if (!t) return false;
  if (['JMP', 'RETURN', 'EQ', 'LT', 'LE', 'TEST'].includes(t.name)) {
    return false;
  }
  
  if (t.name === 'FORLOOP' || t.name === 'FORPREP') return false;
  const n = ops[elseI + 1];
  if (!n) return false;
  if (t.name === 'TFORLOOP') return false;
  if (n.name === 'TFORLOOP' || n.name === 'FORLOOP') return true;
  if (t.name === 'CALL' && (n.name === 'TFORLOOP' || n.name === 'JMP')) return true;
  if (t.name === 'SETTABLE' && (n.name === 'FORLOOP' || n.name === 'JMP')) return true;
  return false;
}

function tryIf(ops, i, idx, targets, regs, defined, depth, upvals, childNames, closureBinds) {
  const op = ops[i];
  if (!['EQ', 'LT', 'LE', 'TEST'].includes(op.name) || typeof op.B !== 'number') return null;
  let elseI = idx.get(op.B);
  if (elseI == null || elseI <= i) return null;

  
  
  const inclusiveThen = thentii(ops, elseI);

  let thenEnd = inclusiveThen ? elseI + 1 : elseI;
  let joinPc = null;
  const elseAnchor = inclusiveThen ? elseI + 1 : elseI;
  const beforeElse = ops[elseAnchor - 1];
  if (
    !inclusiveThen
    && beforeElse
    && beforeElse.name === 'JMP'
    && typeof beforeElse.B === 'number'
    && beforeElse.B > op.B
  ) {
    joinPc = beforeElse.B;
    thenEnd = elseI - 1;
  }

  const sp = ind(depth);
  const left = cmpl(op, regs);
  const right = cmpr(op, regs);

  
  if (op.name === 'EQ' && left === right) {
    const thenRegs = new Map(regs);
    const thenDef = new Set(defined);
    const thenLines = emitSl(ops, i + 1, thenEnd, thenRegs, thenDef, depth, upvals, childNames, closureBinds, targets);
    let next = joinPc != null ? idx.get(joinPc) : elseAnchor;
    if (next == null) return null;
    if (joinPc == null && iste(ops, elseAnchor)) next = ops.length;
    if (!thenLines.length && iste(ops, elseAnchor)) {
      const elseLines = emitSl(ops, elseAnchor, ops.length, new Map(regs), new Set(defined), depth, upvals, childNames, closureBinds, targets);
      return {
        lines: elseLines,
        next: ops.length,
      };
    }
    return { lines: thenLines, next };
  }

  
  if (op.name !== 'TEST') {
    const hit = evalCmp(op.name, left, right);
    if (hit === true) {
      const thenRegs = new Map(regs);
      const thenDef = new Set(defined);
      const thenLines = emitSl(ops, i + 1, thenEnd, thenRegs, thenDef, depth, upvals, childNames, closureBinds, targets);
      for (const [k, v] of thenRegs) regs.set(k, v);
      for (const k of thenDef) defined.add(k);
      let next = joinPc != null ? idx.get(joinPc) : elseAnchor;
      if (next == null) next = elseAnchor;
      return { lines: thenLines, next };
    }
    if (hit === false) {
      let next = joinPc != null ? idx.get(joinPc) : elseAnchor;
      if (next == null) return null;
      if (joinPc != null && !iste(ops, elseAnchor)) {
        const elseRegs = new Map(regs);
        const elseDef = new Set(defined);
        const elseLines = emitSl(ops, elseAnchor, next, elseRegs, elseDef, depth, upvals, childNames, closureBinds, targets);
        for (const [k, v] of elseRegs) regs.set(k, v);
        return { lines: elseLines, next };
      }
      return { lines: [], next };
    }
  }

  const cond = op.name === 'TEST' ? left : `${left} ${cmpSym(op.name)} ${right}`;

  const thenRegs = new Map(regs);
  const thenDef = new Set(defined);
  const thenLines = emitSl(ops, i + 1, thenEnd, thenRegs, thenDef, depth + 1, upvals, childNames, closureBinds, targets);

  
  if (inclusiveThen) {
    return {
      lines: [`${sp}if ${cond} then`, ...thenLines, `${sp}end`],
      next: elseAnchor,
    };
  }

  if (joinPc != null) {
    const joinI = idx.get(joinPc);
    if (joinI == null) return null;
    if (iste(ops, elseI)) {
      const flat = emitSl(ops, i + 1, thenEnd, new Map(regs), new Set(defined), depth, upvals, childNames, closureBinds, targets);
      return { lines: flat, next: joinI };
    }
    const elseRegs = new Map(regs);
    const elseDef = new Set(defined);
    const elseLines = emitSl(ops, elseI, joinI, elseRegs, elseDef, depth + 1, upvals, childNames, closureBinds, targets);
    const lines = [`${sp}if ${cond} then`, ...thenLines];
    if (elseLines.length) {
      lines.push(`${sp}else`);
      lines.push(...elseLines);
    }
    lines.push(`${sp}end`);
    return { lines, next: joinI };
  }

  if (thenEnd > i + 1) {
    
    if (iste(ops, elseI)) {
      const flat = emitSl(ops, i + 1, thenEnd, new Map(regs), new Set(defined), depth, upvals, childNames, closureBinds, targets);
      return { lines: flat, next: ops.length };
    }
    return {
      lines: [`${sp}if ${cond} then`, ...thenLines, `${sp}end`],
      next: elseI,
    };
  }

  
  if (thenLines.length === 0 || thenEnd === i + 1) {
    const elseRegs = new Map(regs);
    const elseDef = new Set(defined);
    const elseLines = emitSl(ops, elseI, ops.length, elseRegs, elseDef, depth, upvals, childNames, closureBinds, targets);
    if (iste(ops, elseI)) {
      return {
        lines: elseLines,
        next: ops.length,
      };
    }
    return { lines: [], next: elseI };
  }
  return null;
}

function iste(ops, elseI) {
  if (elseI == null || elseI >= ops.length) return false;
  const a = ops[elseI];
  const b = ops[elseI + 1];
  if (!a) return false;
  
  
  if (a.name === 'GETTABLE' && b && b.name === 'RETURN') return elseI + 2 >= ops.length;
  if (a.name === 'RETURN' && elseI + 1 >= ops.length) return true;
  return false;
}

function emitSl(ops, from, to, regs, defined, depth, upvals, childNames, closureBinds, targets) {
  const lines = [];
  const idx = byIdx(ops);
  let i = from;
  while (i < to) {
    const op = ops[i];
    if (targets.has(op.index)) lines.push(`${ind(depth)}::L${op.index}::`);

    const asFor = tryNumFor(ops, i, idx, targets, regs, defined, depth, upvals, childNames, closureBinds);
    if (asFor && asFor.next > i) {
      const loopAtBoundary = asFor.next === to + 1 && ops[to] && ops[to].name === 'FORLOOP';
      if (asFor.next <= to || loopAtBoundary) {
        lines.push(...asFor.lines);
        i = loopAtBoundary ? to : asFor.next;
        continue;
      }
    }

    const asGfor = tryGenFor(ops, i, idx, targets, regs, defined, depth, upvals, childNames, closureBinds);
    if (asGfor && asGfor.next > i && asGfor.next <= to) {
      lines.push(...asGfor.lines);
      i = asGfor.next;
      continue;
    }

    const structured = tryIf(ops, i, idx, targets, regs, defined, depth, upvals, childNames, closureBinds);
    if (structured && structured.next > i && structured.next <= to) {
      lines.push(...structured.lines);
      i = structured.next;
      continue;
    }
    if (op.name === 'JMP' || op.name === 'FORLOOP' || op.name === 'FORPREP') {
      i++;
      continue;
    }
    const em = step(op, ops, i, regs, defined, depth, upvals, childNames, closureBinds);
    if (em.lines) lines.push(...em.lines);
    i += 1 + (em.skip || 0);
  }
  return lines;
}

function step(op, ops, i, regs, defined, depth, upvals, childNames, closureBinds) {
  const sp = ind(depth);
  const A = op.A;
  const B = op.B;
  const C = op.C;
  const lines = [];
  const get = (r) => regs.get(r) || reg(r);
  const set = (r, e, def) => {
    regs.set(r, e);
    if (def !== false) defined.add(r);
  };

  switch (op.name) {
    case 'MOVE':
      set(A, get(B));
      return { lines, skip: 0 };
    case 'LOADK':
    case 'LOADBOOL': {
      if (typeof B === 'string') {
        if (isBinK(B) || B == null) return { lines, skip: 0 };
      }
      if (B == null) return { lines, skip: 0 };
      
      if (op.name === 'LOADK' && typeof B === 'string' && isId(B)) {
        if (isGName(B)) {
          for (let j = i + 1; j < Math.min(i + 8, ops.length); j++) {
            const n = ops[j];
            if (!n) break;
            if (n.name === 'CALL' && n.A === A) {
              set(A, gName(B));
              return { lines, skip: 0 };
            }
            if (['LOADK', 'LOADBOOL', 'GETGLOBAL', 'MOVE', 'CLOSURE', 'GETTABLE', 'SELF'].includes(n.name)) {
              continue;
            }
            if (n.name === 'JMP' || n.name === 'EQ' || n.name === 'TEST') break;
            break;
          }
        }
      }
      set(A, lit(B));
      return { lines, skip: 0 };
    }
    case 'LOADNIL': {
      const to = typeof B === 'number' ? B : A;
      for (let r = A; r <= to; r++) set(r, 'nil');
      return { lines, skip: 0 };
    }
    case 'GETUPVAL':
      set(A, upvals[B] || `up${B}`);
      return { lines, skip: 0 };
    case 'GETGLOBAL': {
      if (typeof B === 'string' && !isGName(B)) {
        let asFn = false;
        for (let j = i + 1; j < Math.min(i + 5, ops.length); j++) {
          const n = ops[j];
          if (!n) break;
          if (n.name === 'CALL' && n.A === A) {
            asFn = true;
            break;
          }
          if (['LOADK', 'LOADBOOL', 'MOVE', 'GETUPVAL'].includes(n.name)) continue;
          break;
        }
        set(A, asFn ? gName(B) : lit(B));
      } else {
        set(A, gName(B));
      }
      return { lines, skip: 0 };
    }
    case 'GETTABLE': {
      const base = get(B);
      if (isNoise(base) || base === 'nil' || base === 'null') {
        return { lines, skip: 0 };
      }
      const expr = field(base, C, op.isKC);
      if (isNoise(expr)) return { lines, skip: 0 };
      const next = ops[i + 1];
      
      if (
        next &&
        next.name === 'RETURN' &&
        typeof next.B === 'number' &&
        next.B <= 1
      ) {
        lines.push(`${sp}return ${expr}`);
        return { lines, skip: 1 };
      }
      if (next && next.name === 'RETURN' && next.B === 2 && next.A === A) {
        lines.push(`${sp}return ${expr}`);
        return { lines, skip: 1 };
      }
      set(A, expr);
      return { lines, skip: 0 };
    }
    case 'SETGLOBAL':
      lines.push(`${sp}${gName(B)} = ${get(A)}`);
      return { lines, skip: 0 };
    case 'SETUPVAL':
      lines.push(`${sp}${upvals[B] || `up${B}`} = ${get(A)}`);
      return { lines, skip: 0 };
    case 'SETTABLE': {
      let base = get(A);
      if (base === '{}') {
        lines.push(`${sp}${reg(A)} = {}`);
        base = reg(A);
        set(A, base);
      }
      lines.push(`${sp}${field(base, B, op.isKB)} = ${rk(C, op.isKC, regs)}`);
      return { lines, skip: 0 };
    }
    case 'NEWTABLE':
      lines.push(`${sp}${reg(A)} = {}`);
      set(A, reg(A));
      return { lines, skip: 0 };
    case 'SELF': {
      let j = i + 1;
      while (j < ops.length && j <= i + 8) {
        const n = ops[j];
        if (n.name === 'CALL' && n.A === A) break;
        if (
          ['LOADK', 'LOADBOOL', 'MOVE', 'GETGLOBAL', 'GETTABLE', 'GETUPVAL'].includes(n.name) &&
          n.A !== A
        ) {
          step(n, ops, j, regs, defined, depth, upvals, childNames, closureBinds);
          j++;
          continue;
        }
        break;
      }
      if (ops[j] && ops[j].name === 'CALL' && ops[j].A === A) {
        set(A + 1, get(B));
        const args = callArgs(ops[j], regs, defined).slice(1);
        const expr = isId(C)
          ? `${get(B)}:${C}(${args.join(', ')})`
          : `${field(get(B), C, true)}(${[get(B), ...args].join(', ')})`;
        lines.push(`${sp}${reg(A)} = ${expr}`);
        set(A, reg(A));
        return { lines, skip: j - i };
      }
      set(A + 1, get(B));
      set(A, field(get(B), C, op.isKC));
      return { lines, skip: 0 };
    }
    case 'ADD':
    case 'SUB':
    case 'MUL':
    case 'DIV':
    case 'MOD':
    case 'POW': {
      const sym = { ADD: '+', SUB: '-', MUL: '*', DIV: '/', MOD: '%', POW: '^' }[op.name];
      set(A, `(${rk(B, op.isKB, regs)} ${sym} ${rk(C, op.isKC, regs)})`);
      return { lines, skip: 0 };
    }
    case 'UNM':
      set(A, `(-${rk(B, op.isKB, regs)})`);
      return { lines, skip: 0 };
    case 'NOT':
      set(A, `(not ${rk(B, op.isKB, regs)})`);
      return { lines, skip: 0 };
    case 'LEN':
      set(A, `(#${rk(B, op.isKB, regs)})`);
      return { lines, skip: 0 };
    case 'CONCAT': {
      if (typeof B === 'number' && typeof C === 'number' && C > B) {
        const parts = [];
        for (let r = B; r <= C; r++) parts.push(get(r));
        set(A, `(${parts.join(' .. ')})`);
      } else {
        set(A, `(${get(B)} .. ${get(C)})`);
      }
      return { lines, skip: 0 };
    }
    case 'JMP':
      if (typeof B === 'number') lines.push(`${sp}goto L${B}`);
      return { lines, skip: 0 };
    case 'EQ':
    case 'LT':
    case 'LE': {
      const sym = cmpSym(op.name);
      if (typeof B === 'number') {
        const left = cmpl(op, regs);
        const right = cmpr(op, regs);
        if (op.name === 'EQ' && left === right) {
          let skip = 0;
          if (ops[i + 1] && ops[i + 1].name === 'JMP') skip = 1;
          return { lines, skip };
        }
        if (isNoise(left) || isNoise(right) || left === 'nil' || right === 'nil') {
          return { lines, skip: 0 };
        }
        if (typeof A === 'number' && A > 32 && !op.isKA) return { lines, skip: 0 };
        const hit = evalCmp(op.name, left, right);
        if (hit === true) {
          let skip = 0;
          if (ops[i + 1] && ops[i + 1].name === 'JMP' && ops[i + 1].B === B) skip = 1;
          return { lines, skip };
        }
        if (hit === false) {
          lines.push(`${sp}goto L${B}`);
          return { lines, skip: 0 };
        }
        lines.push(`${sp}if ${left} ${sym} ${right} then else goto L${B} end`);
      }
      return { lines, skip: 0 };
    }
    case 'TEST':
      if (typeof B === 'number') {
        const left = get(A);
        if (isNoise(left) || left === 'nil') return { lines, skip: 0 };
        lines.push(`${sp}if ${left} then else goto L${B} end`);
      }
      return { lines, skip: 0 };
    case 'TESTSET': {
      if (typeof B !== 'number') return { lines, skip: 0 };
      const src = get(A);
      
      const jmp = B;
      const val = get(typeof C === 'number' && C <= 255 && !op.isKC ? C : A);
      if (isNoise(val) || val === 'nil') return { lines, skip: 0 };
      lines.push(`${sp}if ${val} then`);
      lines.push(`${sp}  ${reg(A)} = ${val}`);
      lines.push(`${sp}else goto L${jmp} end`);
      set(A, reg(A));
      return { lines, skip: 0 };
    }
    case 'CALL': {
      const fn = get(A);
      if (!defined.has(A) && fn === reg(A)) {
        return { lines, skip: 0 };
      }
      if (isNoise(fn) || fn === 'nil' || fn === 'null' || fn === '0') {
        return { lines, skip: 0 };
      }
      if (
        (typeof fn === 'string' && (fn.startsWith('"') || fn.startsWith("'")))
        || fn === 'true'
        || fn === 'false'
      ) {
        return { lines, skip: 0 };
      }
      let args = callArgs(op, regs, defined);
      if (args.length >= 1) {
        const a0 = args[0];
        if (typeof a0 === 'string' && (a0.startsWith('"') || a0.startsWith("'"))) {
          let looksUp = fn === 'dec';
          if (!looksUp && typeof fn === 'string' && fn.length >= 3 && fn[0] === 'u' && fn[1] === 'p') {
            looksUp = true;
            for (let k = 2; k < fn.length; k++) {
              if (fn[k] < '0' || fn[k] > '9') {
                looksUp = false;
                break;
              }
            }
          }
          const next = ops[i + 1];
          const feedsPrint = next && next.name === 'CALL' && next.B === 0 && next.A !== A;
          if (looksUp || feedsPrint) {
            set(A, a0);
            return { lines, skip: 0 };
          }
        }
      }
      args = args.filter((a, idx) => {
        if (idx === 0) return true;
        if (typeof a !== 'string') return true;
        if (!(a.startsWith('"') || a.startsWith("'"))) return true;
        const inner = a.slice(1, -1);
        let bad = 0;
        for (let k = 0; k < inner.length; k++) {
          const c = inner.charCodeAt(k);
          if (c < 32 || c >= 127) bad++;
        }
        return !(inner.length >= 2 && bad / inner.length >= 0.3);
      });
      const expr = `${fn}(${args.join(', ')})`;
      if (C === 1) {
        lines.push(`${sp}${expr}`);
        return { lines, skip: 0 };
      }
      lines.push(`${sp}${reg(A)} = ${expr}`);
      set(A, reg(A));
      return { lines, skip: 0 };
    }
    case 'TFORLOOP': {
      if (op.mode === 3 && typeof B === 'number') {
        return { lines, skip: 0 };
      }
      const fn = get(A);
      const args = callArgs(
        { A, B: typeof B === 'number' && B <= 32 ? B : 2, C },
        regs,
        defined
      );
      if (fn && fn !== reg(A) && !isNoise(fn)) {
        const nret = typeof C === 'number' && C > 1 ? Math.min(C, 4) : 3;
        lines.push(`${sp}${reg(A)} = ${fn}(${args.join(', ')})`);
        set(A, reg(A));
        for (let r = 1; r < nret; r++) {
          set(A + r, reg(A + r));
          defined.add(A + r);
        }
      }
      return { lines, skip: 0 };
    }
    case 'TAILCALL': {
      const args = callArgs(op, regs, defined);
      lines.push(`${sp}return ${get(A)}(${args.join(', ')})`);
      return { lines, skip: 0 };
    }
    case 'RETURN': {
      if (B === 1 || B === 0) lines.push(`${sp}return`);
      else if (typeof B === 'number' && B > 1) {
        const vals = [];
        for (let r = A; r <= A + B - 2; r++) vals.push(get(r));
        lines.push(`${sp}return ${vals.join(', ')}`);
      } else lines.push(`${sp}return ${get(A)}`);
      return { lines, skip: 0 };
    }
    case 'CLOSURE': {
      const name = childNames[B] || `f${B}`;
      const ups = [];
      for (let u = 0; u < (op.upvals || []).length; u++) {
        const uv = op.upvals[u];
        ups[u] = uv.isLocal ? get(uv.idx) : (upvals[uv.idx] || `up${uv.idx}`);
      }
      closureBinds.push({ idx: B, ups });
      
      let fname = name;
      const next = ops[i + 1];
      if (next && next.name === 'SETGLOBAL' && next.A === A && typeof next.B === 'string' && isId(next.B)) {
        fname = next.B;
        childNames[B] = fname;
        set(A, fname);
        return { lines, skip: 1 };
      }
      set(A, name);
      return { lines, skip: 0 };
    }
    case 'SETLIST': {
      const n = typeof B === 'number' && B > 0 ? B : 32;
      const parts = [];
      for (let r = A + 1; r <= A + n; r++) {
        if (!regs.has(r) && !defined.has(r)) break;
        parts.push(get(r));
      }
      if (parts.length) {
        const expr = `{ ${parts.join(', ')} }`;
        lines.push(`${sp}${reg(A)} = ${expr}`);
        set(A, expr);
      } else {
        set(A, get(A) === '{}' ? '{}' : get(A));
      }
      return { lines, skip: 0 };
    }
    case 'FORPREP':
    case 'FORLOOP':
      
      return { lines, skip: 0 };
    case 'VARARG':
      set(A, '...');
      return { lines, skip: 0 };
    case 'CLOSE':
    case 'UNKNOWN':
      return { lines, skip: 0 };
    default:
      return { lines, skip: 0 };
  }
}

function isatr(proto) {
  const names = new Set((proto.constants || []).filter((c) => typeof c === 'string'));
  return names.has('string') && names.has('match') && names.has('pcall') && names.has('tonumber');
}

function islcp(proto) {
  const names = new Set((proto.constants || []).filter((c) => typeof c === 'string'));
  return names.has(':%d+:') && names.has('%d+');
}

function findpp(root) {
  if (!root || !isatr(root)) return null;
  const mid = (root.prototypes || []).find((p) => p && islcp(p));
  if (!mid) return null;
  const payload = (mid.prototypes || []).find(Boolean);
  return payload || null;
}

function isep(proto) {
  if (!proto) return true;
  const consts = (proto.constants || []).slice(1);
  const useful = consts.filter((c) => typeof c === 'string' && c.length > 1);
  if (useful.length) return false;
  const ops = (proto.instructions || []).filter((i) => i && !i.skipped);
  return ops.length <= 8;
}

function reconProg(root, opcodeMap, closureLocalOp) {
  const payload = findpp(root);
  if (payload) {
    if (isep(payload)) {
      return [
        'local function main()',
        'end',
        '',
        'return main()',
        '',
      ].join('\n');
    }
    const body = reconPr(payload, opcodeMap, closureLocalOp, 'main', [], 0);
    return [
      body,
      '',
      'return main()',
      '',
    ].join('\n');
  }

  const leaf = findil(root, opcodeMap, closureLocalOp);
  if (leaf && leaf !== root) {
    const body = reconPr(leaf, opcodeMap, closureLocalOp, 'main', [], 0);
    return [
      body,
      '',
      'return main()',
      '',
    ].join('\n');
  }

  return [
    reconPr(root, opcodeMap, closureLocalOp, 'main', [], 0),
    '',
    'return main()',
    '',
  ].join('\n');
}

function findil(root, opcodeMap, closureLocalOp) {
  let best = null;
  let bestScore = 0;
  function score(p) {
    const ops = cleanCfg(annPr(p, opcodeMap, closureLocalOp));
    return anPrUse(p, ops).score;
  }
  function walk(p) {
    const sc = score(p);
    const kids = (p.prototypes || []).filter(Boolean);
    if (sc > bestScore && (kids.length === 0 || sc >= 20)) {
      bestScore = sc;
      best = p;
    }
    for (const k of kids) walk(k);
  }
  walk(root);
  if (!best || best === root || bestScore < 15) return null;
  const rootScore = score(root);
  if (rootScore >= bestScore) return null;
  const rootUsage = anPrUse(root, cleanCfg(annPr(root, opcodeMap, closureLocalOp)));
  if (!rootUsage.xorStub && rootScore >= 8) return null;
  return best;
}

function sumCfg(root, opcodeMap, closureLocalOp) {
  let jmps = 0;
  let removed = 0;
  function walk(p) {
    const ops = annPr(p, opcodeMap, closureLocalOp);
    const st = jmpStats(ops);
    jmps += st.jmps;
    removed += st.removed;
    for (const c of p.prototypes) if (c) walk(c);
  }
  walk(root);
  return { jmps, removed };
}


module.exports = {
  cleanCfg,
  liftProg,
  disasmPr,
  reconProg,
  sumCfg,
};
