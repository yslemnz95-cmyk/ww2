#!/usr/bin/env node
const fs = require('fs');
const path = require('path');
const { deobf } = require('./deobf');

function usage() {
  process.stderr.write('node index.js <file.lua> [--out out.lua] [--disasm] [--json] [--stdout]\n');
}

function lineCount(text) {
  if (!text) return 0;
  return String(text).split(/\r?\n/).length;
}

function main(argv) {
  const args = argv.slice(2);
  if (args.length === 0 || args.includes('-h') || args.includes('--help')) {
    usage();
    process.exit(args.length ? 0 : 1);
  }
  const file = args.find((a) => !a.startsWith('-'));
  if (!file) {
    usage();
    process.exit(1);
  }
  const outIdx = args.indexOf('--out');
  const outPath = outIdx >= 0 ? args[outIdx + 1] : null;
  const wantDisasm = args.includes('--disasm');
  const wantJson = args.includes('--json');
  const wantStdout = args.includes('--stdout');

  const absIn = path.resolve(file);
  const source = fs.readFileSync(absIn, 'utf8');
  const result = deobf(source, { log: !wantJson });
  const isGood = result.detection.family === 'luaobfuscator-chaotic-good';

  if (wantJson) {
    const json = {
      detection: result.detection,
      vm: result.vm
        ? {
            opcodeCount: result.vm.opcodeCount,
            closureLocalOp: result.vm.closureLocalOp,
            usedMap: result.vm.usedMap,
            nameToOpcodes: result.vm.nameToOpcodes,
          }
        : null,
      lua: result.lua,
      disasm: result.disasm,
    };
    const text = JSON.stringify(json, null, 2);
    if (outPath) fs.writeFileSync(path.resolve(outPath), text);
    else process.stdout.write(text + '\n');
    return;
  }

  const output =
    wantDisasm && !isGood
      ? `${result.disasm}\n\n${result.reconstructed}\n\n${result.lifted}\n`
      : result.reconstructed;

  const dest = outPath
    ? path.resolve(outPath)
    : path.join(__dirname, 'output', path.basename(absIn), 'reconstructed.lua');

  fs.mkdirSync(path.dirname(dest), { recursive: true });
  fs.writeFileSync(dest, output);

  process.stderr.write(`lines=${lineCount(output)}\n`);
  process.stderr.write(`${dest}\n`);

  if (wantStdout) process.stdout.write(output);
}

if (require.main === module) {
  try {
    main(process.argv);
  } catch (e) {
    process.stderr.write(`\x1b[31m[err] ${e.message}\x1b[0m\n`);
    process.exit(1);
  }
}

module.exports = { main };
