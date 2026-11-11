# Crédits, licences et modifications

Cette suite assemble des outils tiers (chacun garde sa licence, fichier `LICENSE` dans son dossier
quand il existe). Les modifications apportées par nous sont listées plus bas.

| Dossier | Outil / auteur d'après les fichiers de l'archive | Licence |
|---|---|---|
| `engines/sandbox` (ex-`luraph_v15`) | « Deobfuscator-Luraph-V15 » (Aditya-lua ; copyright du fichier LICENSE : caomod2077) -- il ne reste que le front-end Node (trace) et `envlog.luau` ; le noyau Python (lifteur Luraph) a été retiré le 2026-11-09 | MIT |
| `engines/deobf_py` | « luraph-v15-v14.x-deobfuscator » (contact indiqué : larpcorrupt, dsc.gg/oxyenv) -- il ne reste que le plugin IronBrew1 (plugins Luraph retirés le 2026-11-09) | aucun fichier de licence trouvé dans l'archive |
| `engines/hercules` | « hercules-deobfuscator » (décompileur Hercules 1.6 -> 2.0) | Apache-2.0 |
| `engines/ironveil` | « Ironveil-Deobfuscator-V1 » (prostone_, LeakD) | MIT |
| `engines/leakd_luaobfuscator` | « LuaObfuscator-Deobfuscator » (Prostone, LeakD) | MIT |
| `engines/centurion` | « centurion-deobfuscator » (v6/v6.1) | aucun fichier de licence trouvé |
| `engines/moonsec` | « MoonsecDeobfuscator » (tupsutumppu) -- source dans `src/`, binaire pré-compilé dans `bin/` (dépendances : Antlr4.Runtime.Standard, NLua/KeraLua, QuikGraph) | **GPL-3.0** (si vous redistribuez la suite, respectez la GPL pour ce dossier) |
| `engines/ironbrew2` | Code original (analyse des VM des forks IronBrew 2 ; aucun code tiers copié ; le dépôt `disrobe` n'a PAS été utilisé : sa licence interdit de s'en inspirer). Dépendance `luaparser` (MIT) | propriétaire / MIT |
| `engines/moonsec/decom.lua` | LuaDec en Lua pur, tiré de « MoonSecV3DeobfuscatorDiscordBot » (Daisuke Bauza / KenAdams) | **MIT** |
| runtime `.NET 9` (`runtime/dotnet/`, téléchargé) | Microsoft, archive officielle `dotnet-runtime-9.0.0` | **MIT** (+ avis tiers dans l'archive) |
| (idée reprise) | « FlowAuth-Deobfuscator » (@adi.codz) -- le repli du watchdog sur tous les `while true do` (cf. FLOWAUTH_HANDOFF.md §6) | -- |
| `runtime/bin` | Luau, tag 0.739, dépôt officiel `luau-lang/luau`, binaires compilés avec nos patchs (voir `runtime/bin/PROVENANCE.txt`) | MIT |
| `runtime/node` (téléchargé si absent) | Node.js v22.22.0, archive officielle nodejs.org, SHA-256 figé dans `bootstrap.py` | MIT et licences tierces (fichier LICENSE extrait avec le binaire) |

Non inclus : `ib2-deobf` (binaires .NET sans source, exécution de Lua avec stdlib complète, serveur
tiers ; son `.env` contient un jeton de bot Discord et une clé « ORACLE » : si ce sont les vôtres,
**régénérez-les**).

## Modifications apportées aux outils tiers

- (2026-11-09) **Retrait de Luraph** : `engines/luraph_v15` -> `engines/sandbox` (lifteur Python, détection et instrumentation Luraph supprimés), plugins Luraph de `deobf_py` supprimés, `cogs/luraph_tools_cog.py` -> `cogs/tools_cog.py` (`ToolsCog`). Les entrées ci-dessous qui citent `luraph_v15` décrivent l'historique.

- (FINAL16) `obf_identify.py` (nouveau) : identification de l'obfuscateur pour `/analyse` ; `cogs/luraph_tools_cog.py` : `/analyse` avec
  échéance globale, calcul hors boucle d'événements, identification et bac à sable en parallèle ; `lua_sandbox.py` : message clair en cas de délai.

- (FINAL15) `engines/luraph_v15/build_luau.py` / `runtime/bin/linux-x86_64/luau` : `resume_start` démarre le thread dont la
  fonction de base est le chunk principal `=Script` à la profondeur C d'un script Roblox ; le plafond « C stack overflow »
  n'exempte plus que les cadres du bac à sable (une fonction C appelée par le script déborde comme dans Roblox).
  `runtime/envlog.luau` : le chunk est la fonction de base de son thread (plus de `xpcall` ni de fonction du bac à sable
  au-dessus). `core/obfuscators/luraph_v15/devirt.py` : tables de constantes des builds `_bsdata0` (`lazy_operands`,
  `lazy_cache`), réglages de limites par variables d'environnement (valeurs par défaut inchangées).

- `luraph_v15`
  - `src/liftretry.js` (nouveau) + appel dans `src/driver.js` : relances automatiques du lifteur
    (processus frais, `PYTHONHASHSEED` différent, 4 en parallèle, jusqu'à 32), meilleur résultat conservé.
  - `src/vmmap.js` `patchEntries` (option `tagNative`), `runtime/envlog.luau` (`__TG`, `__FNID`, champ `sp` du dump) et
    `core/obfuscators/luraph_v15/devirt.py` (`function_source`, `_helper_table`, `_pretty`) : **fusion** -- les fonctions natives
    (non virtualisées) du chunk de la VM sont citées dans la sortie à la place des stubs `luraph_runtimeN`.
  - `src/vmmap.js` `patchSpin` et `core/obfuscators/luraph_v15/driver.py` `patch_spin` : si aucune forme
    ciblée ne correspond, compteur du watchdog injecté à **chaque** `while true do`.
  - `core/obfuscators/luraph_v15/devirt.py` : `reversed(list(curr.values()))` (compatibilité PyPy).
  - `postprocess.py` (nouveau) : évalue les appels littéraux aux fonctions d'aide de la VM, retire le bruit arithmétique inerte (AST).
  - `run.py`, `engine.json` (nouveaux) : enveloppe uniforme (timeout dur, env épuré, codes de sortie).
- `luauforge` (**nouveau, nos propres sources**) : défait les couches statiques de LuauForge (espaces/tabulations, dictionnaire de mots), puis exécute la
  machine virtuelle restante dans le bac à sable de `luraph_v15`. `runtime/envlog.luau` (luraph_v15) : une globale à **nom aléatoire** (9-16 car., majuscules +
  minuscules + chiffre) vaut `nil` au lieu d'un faux objet (la machine y range ses adresses de retour).
- `loader_chain.py` + `deobf_router.py` (**nouveau**) : suit `loadstring(game:HttpGet(url))()` (deux formes) avec garde-fous anti-SSRF ; s'arrête devant Luarmor
  sans le contacter ; enchaîne après `luauforge`.
- `ironveil` : `deobfuscator/utils/parse.js` -- les deux `eval()` sur du texte issu de l'entrée (fonction
  exportée mais jamais appelée) remplacés par un évaluateur arithmétique restreint (`sEv`).
- `leakd_luaobfuscator` : `Utils/io.js` `valFam` accepte la famille « evil » quand le bytecode `LOL!` et
  `math.ldexp` sont présents.
- `centurion` : `src/centurion.py` `harvest_table_spans_ast` reconnaît les nœuds `AstExprIndexExpr` /
  `AstExprLocal` émis par le `luau-ast` officiel.
- `bootstrap.py`, `lua_sandbox.py`, `bot_extension.py`, `runtime/` (nouveaux) : mise en route automatique de Node.js / Luau, trace de comportement de `/analyse`, point d'entrée du bot.
- `deobf_router.py` : appelle `bootstrap.ensure_ready()` avant chaque moteur et met le Node fourni en tête du `PATH` des moteurs.
- Chaque moteur reçoit `run.py` + `engine.json` (exécution dans un dossier temporaire, timeout dur avec
  arrêt du groupe de processus, plafond de taille, environnement épuré).
- `cogs/luraph_tools_cog.py` : `@commands.is_owner()` (sans effet sur une commande slash) remplacé par
  `owner_only()` ; `/process` passe par le routeur (repli sur l'ancien pipeline si la suite est absente) ;
  téléchargement par blocs (l'ancien code tronquait les fichiers), anti-gel des regex, jetons de webhook masqués,
  `/process` = `run_job()` (jobs simultanés sans file d'attente, `.zip` jusqu'à 100 scripts, tableau de bord unique
  par salon, résultat posté dans le salon avec replis MP / `results/`, cache SHA-256, mode machine faible), accès par
  `allowed_ids.txt` / `DEOBF_ALLOWED_IDS` (voir README_FR.md).


FINAL31 : le moteur `wearedevs` reconstruit désormais un Lua équivalent (relevé de la machine à états, chaînes déchiffrées, vérification dans le bac à sable), avec repli sur la trace. luaparse (MIT) est livré dans engines/wearedevs/ avec sa licence.
