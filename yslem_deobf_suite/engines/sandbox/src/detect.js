'use strict';

// Le bac a sable ne reconnait plus aucun obfuscateur : toute entree est tracee en mode generique
// (comportement observe). La detection par famille est faite par deob_router.py / obf_identify.py.
const GENERIC = { name: 'generic', label: 'behaviour trace (generic sandbox)' };

function detect() {
  return { plugin: GENERIC, confidence: 0 };
}

function byName(name) {
  if (name === 'generic') return GENERIC;
  throw new Error(`Unknown plugin '${name}' (known: generic)`);
}

function restoreHeaderNewline(source) {
  return source;
}

module.exports = { detect, byName, restoreHeaderNewline, PLUGINS: [GENERIC] };
