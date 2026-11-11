const { det, xtrBc, decAllStr, invProt, unflatCff, deobfGd } = require('./Utils/io');
const { anVm, guessOp, refOpMap } = require('./Utils/vm');
const { liftProg, disasmPr, reconProg, sumCfg } = require('./Utils/out');

const ANSI = {
  reset: '\x1b[0m',
  green: '\x1b[32m',
  red: '\x1b[31m',
  yellow: '\x1b[33m',
  cyan: '\x1b[36m',
};

const OUT_HDR = '-- Deоbfuѕсаtеԁ by LeakD | discord.gg/qteAQmfJmP\n\n';

function withHdr(code) {
  return OUT_HDR + String(code || '').replace(/^\uFEFF/, '');
}

function mkLog(enabled) {
  return (step, status, extra = '') => {
    if (!enabled) return;
    let col = ANSI.red;
    let tag = 'fail';
    if (status === true || status === 'ok') {
      col = ANSI.green;
      tag = 'ok';
    } else if (status === 'partial' || status === 'warn') {
      col = ANSI.yellow;
      tag = 'warn';
    }
    const tail = extra ? ` ${extra}` : '';
    process.stderr.write(`${col}[${step}] ${tag}${tail}${ANSI.reset}\n`);
  };
}

function walkp(root, fn) {
  const stop = fn(root);
  if (stop) return true;
  for (const child of root.prototypes) {
    if (child && walkp(child, fn)) return true;
  }
  return false;
}

function collectOpcodes(root) {
  const used = new Set();
  walkp(root, (p) => {
    for (const ins of p.instructions) {
      if (ins && !ins.skipped) used.add(ins.opcode);
    }
  });
  return used;
}

function guessFromIns(root, op) {
  let guess = 'UNKNOWN';
  walkp(root, (p) => {
    for (const ins of p.instructions) {
      if (ins && !ins.skipped && ins.opcode === op) {
        guess = guessOp(ins);
        return true;
      }
    }
  });
  return guess;
}

function deobf(source, options = {}) {
  const log = mkLog(!!options.log);
  const src = String(source);
  const detection = det(src);
  if (!detection.matched && !options.force) {
    log('det', false, detection.reason || 'reject');
    const err = new Error(`det:${detection.reason || 'reject'}`);
    err.detection = detection;
    throw err;
  }
  const fam =
    detection.family === 'luaobfuscator-chaotic-good'
      ? 'good'
      : detection.family === 'luaobfuscator-chaotic-evil'
        ? 'evil'
        : detection.family || '?';
  log('det', true, fam);

  if (detection.family === 'luaobfuscator-chaotic-good') {
    let good;
    try {
      good = deobfGd(src);
      log('xor', true);
      log('cff', good.wrapperCff && good.wrapperCff.remaining <= 1 ? true : 'partial');
    } catch (e) {
      log('xor', false);
      throw e;
    }
    if (good.lua.includes('math.ldexp')) {
      log('recon', false, 'ldexp');
      const err = new Error('good:ldexp');
      err.detection = detection;
      throw err;
    }
    log('recon', true);
    const out = withHdr(good.lua);
    return {
      detection,
      protections: [],
      wrapperCff: good.wrapperCff,
      bytecode: null,
      vm: null,
      strings: good.strings,
      cfg: null,
      lifted: out,
      reconstructed: out,
      lua: out,
      disasm: '',
      rewrittenSource: good.lua,
    };
  }

  const wrapperCff = unflatCff(src);
  const flatSrc = wrapperCff.source;
  log(
    'cff',
    wrapperCff.replaced > 0 ? (wrapperCff.remaining <= 1 ? true : 'partial') : 'warn',
    `rep=${wrapperCff.replaced} rem=${wrapperCff.remaining}`
  );

  let bytecode;
  try {
    bytecode = xtrBc(src);
    log('bc', true, `${bytecode.bytesRead}/${bytecode.bytesTotal}`);
  } catch (e) {
    log('bc', false);
    throw e;
  }

  const strings = decAllStr(flatSrc, bytecode.root);
  const s = strings.summary || {};
  log('str', true, `outer=${s.outerCount || 0} vm=${s.vmCount || 0}`);

  let rewrittenSource = flatSrc;
  let wrapperAfter = { replaced: 0, statesTotal: 0, remaining: wrapperCff.remaining };
  if (strings.rewrittenSource && strings.rewrittenSource !== flatSrc) {
    rewrittenSource = strings.rewrittenSource;
    wrapperAfter = unflatCff(rewrittenSource);
    rewrittenSource = wrapperAfter.source;
  }

  const protections = invProt(src, {
    wrapperCff: {
      replaced: wrapperCff.replaced + (wrapperAfter.replaced || 0),
      remaining: wrapperAfter.remaining != null ? wrapperAfter.remaining : wrapperCff.remaining,
    },
  });

  let vm;
  try {
    vm = anVm(rewrittenSource);
    const used = collectOpcodes(bytecode.root);
    let mapped = 0;
    for (const op of used) if (vm.opcodeMap[op]) mapped++;
    if (mapped < Math.max(3, Math.ceil(used.size * 0.35))) {
      const vmFlat = anVm(flatSrc);
      let mappedFlat = 0;
      for (const op of used) if (vmFlat.opcodeMap[op]) mappedFlat++;
      if (mappedFlat > mapped) vm = vmFlat;
    }

    refOpMap(bytecode.root, vm.opcodeMap);

    for (const op of used) {
      if (!vm.opcodeMap[op] || vm.opcodeMap[op].name === 'UNKNOWN') {
        const g = guessFromIns(bytecode.root, op);
        if (!vm.opcodeMap[op]) vm.opcodeMap[op] = { name: g, body: '' };
        else vm.opcodeMap[op].name = g;
      }
    }
    log('vm', true, `ops=${vm.opcodeCount} used=${used.size}`);
  } catch (e) {
    log('vm', false);
    throw e;
  }

  const used = collectOpcodes(bytecode.root);
  let reconstructed;
  let lifted;
  let disasm;
  let cfg;
  try {
    reconstructed = reconProg(bytecode.root, vm.opcodeMap, vm.closureLocalOp);
    lifted = liftProg(bytecode.root, vm.opcodeMap, vm.closureLocalOp);
    disasm = disasmPr(bytecode.root, vm.opcodeMap, vm.closureLocalOp);
    cfg = sumCfg(bytecode.root, vm.opcodeMap, vm.closureLocalOp);
    log('recon', true);
  } catch (e) {
    log('recon', false);
    throw e;
  }

  const out = withHdr(reconstructed);
  return {
    detection,
    protections,
    wrapperCff: {
      replaced: wrapperCff.replaced + (wrapperAfter.replaced || 0),
      statesTotal: (wrapperCff.statesTotal || 0) + (wrapperAfter.statesTotal || 0),
      remaining: wrapperAfter.remaining != null ? wrapperAfter.remaining : wrapperCff.remaining,
    },
    bytecode: {
      bytesRead: bytecode.bytesRead,
      bytesTotal: bytecode.bytesTotal,
      sentinel: bytecode.sentinel,
      xorCalls: bytecode.xorCalls,
      root: bytecode.root,
    },
    vm: {
      opcodeCount: vm.opcodeCount,
      closureLocalOp: vm.closureLocalOp,
      usedOpcodes: [...used],
      usedMap: Object.fromEntries(
        [...used].map((op) => [op, (vm.opcodeMap[op] && vm.opcodeMap[op].name) || 'UNKNOWN'])
      ),
      nameToOpcodes: vm.nameToOpcodes,
      opcodeMap: vm.opcodeMap,
    },
    strings: {
      outer: strings.outer,
      vm: strings.vm,
      summary: strings.summary,
      maps: (strings.vm || []).map((m) => ({
        path: m.path,
        index: m.index,
        key: m.key,
        decrypted: m.decrypted,
        score: m.score,
        singleByte: !!m.singleByte,
      })),
      rewrittenSource: options.includeRewrittenSource ? rewrittenSource : undefined,
    },
    cfg,
    lifted,
    reconstructed: out,
    lua: out,
    disasm,
    rewrittenSource,
  };
}

module.exports = { deobf };
