# Connaissances du bot sur les obfuscateurs Lua/Luau (donnees a Gemini pour identifier et conseiller)

Chaque fiche : COMMENT LE RECONNAITRE (indices dans le texte), MOTEUR du bot (champ `engine`), CE QUE LE BOT PEUT / NE PEUT PAS FAIRE.

## luraph_v15  — Luraph v15.x (Luau, Roblox)
- Reconnaitre : en-tete « This file was protected using Luraph Obfuscator v15.x » ; OU sans en-tete : `return setmetatable({[1]=bit32.lshift,[2]=bit32.band,...` (table de fonctions de bit32/buffer/string/table/math), fin `}, {}):xx()(...)` ; utilise `buffer.*` (readu8/readu32/writeu8...), `bit32.*`, `getfenv`, `setfenv`, `coroutine`, `debug.info`. Variante « _bsdata0 » : tables de constantes paresseuses (operandes en t[-2], cache en t[-1]) et controles anti-falsification (pile C : « C stack overflow » a la profondeur exacte de Roblox).
- Le bot : lance le script dans un bac a sable Luau patche, trace + devirtualise (lifteur). Resultat souvent complet (ex. Spicy3 : 0 bloc manquant). Peut rester partiel (blocs `error("devirt:...")`).
- Limite : un chargeur a cle (FlowAuth, Luarmor) ne revele que le chargeur, jamais le script final (serveur distant, jamais contacte).

## deobf_py  — Luraph v14.7 / 14.8 / 14.9 et IronBrew1
- Luraph v14 : en-tete « This file was protected using Luraph Obfuscator v14.7|14.8|14.9 » ; OU SANS en-tete (retire par un chargeur) : tout le fichier est `return({Iy=function(G,R,e,y,Y,C,x)...,QT=bit32.lshift,NT=bit32.band,...}):R()(...)` — table de methodes aux noms de 1-2 lettres, litteraux ecrits `0X27`, `0B11_00011`, `0x00250`, appel final `}):nom()(...)`. Contient parfois `LPH_NO_UPVALUES`, `SoLPU`.
- IronBrew1 : « This file was generated using IronBrew1 » ; OU `return (function(a,b,c,...(20+ parametres d'une lettre),...) local x={-1,...` / `local a,b,c,d,e,f...=...`.
- Le bot : v14.7 -> code lisible ; v14.8/14.9 -> souvent seulement la TRACE d'execution (ce que le script appelle). IronBrew1 -> code lisible.
- Limite connue : script « reserve a certains jeux » (verifie game.PlaceId puis `Players.LocalPlayer:Kick("Game not supported")`) : dans le bac a sable PlaceId=0, donc seule la branche Kick est visible ; la liste des jeux et le hub sont chiffres dans la VM et ne sont pas reconstruits.

## hercules  — Hercules obfuscator v1.6 a v2.0
- Reconnaitre : « Obfuscated by Hercules v… », `hercules-obfuscator.xyz`, appel `BcToState(`, entete de « polyfills de compatibilite Lua 5.3+ / Luau » (~465 octets de debut). Presets VM, BytecodeEncoder, --maximum (imbrique).
- Le bot : decompilateur statique Python (n'execute jamais le script). Les presets « source seule » (LIGHT/VRSECF, sans VM) sont refuses : rien a decompiler.

## ironveil  — Ironveil v1
- Reconnaitre : « Obfuscated using ironveil v1 », `s[1]=table.concat s[2]=table.insert s[3]=table.unpack or unpack`, cles de table `[("ab".."")]=` repetees.
- Le bot : outil JS statique ; sortie fidele sur l'echantillon fourni.

## leakd_luaobfuscator  — LuaObfuscator.com (Chaotic Good / Chaotic Evil, LeakD)
- Reconnaitre : « Welcome to LuaObfuscator.com (Alpha 0.10.x) », « Much Love, Ferib », `local v0=tonumber;local v1=string.byte;local v2=string.char;local v3=string.sub;local v4=string.gsub`, `local v1=math.ldexp;local v2=getfenv or function() return _ENV;end`, variables `v0,v1,v2...`, chaines en `\ddd`.
- Le bot : outil JS statique ; Chaotic Good OK ; Chaotic Evil (bytecode « LOL! ») : leve la protection mais la carte des opcodes peut rester vide -> resultat PARTIEL (structure seulement).

## centurion_v6  — Centurion v6 / v6.1
- Reconnaitre : « Centurion v6 », fabriques `c3[12]=function(Z)`, `=function(Z)const ...`.
- Le bot : route statique v6 -> charge utile PARTIELLEMENT lisible ; v6.1 (necessite le Luau patche + Roblox reel) souvent en echec.

## moonsec_v3  — MoonSec V3
- Reconnaitre : mot « MoonSec » ; sinon deux tres longues chaines `local a="..."` (400+ car.) en debut de fichier. Regles NON verifiees sur un vrai echantillon.
- Le bot : produit un desassemblage de bytecode Lua 5.1 (pas du source).

## legaxyobf  — legaxyobf (enveloppe RBXE + VM RBXO)
- Reconnaitre : premiere ligne `-- protected by legaxyobf` ; une longue chaine `"RBXE\001\000\001\002\000..."` (enveloppe chiffree), une table de 32 nombres (la CLE, en clair dans le fichier),
  puis un chargeur « machine a etats » `while true do if _zNN_xxxxxxx == 5 then ... elseif ...` avec ChaCha20-Poly1305 ecrit en Lua, noms `_z12_f29068c`, `MAX_PROTOS`, `MAX_CODE`, `Vector3.new(...)` / `CFrame` utilises comme sommes de controle.
- Le bot : moteur Python pur (n'execute jamais le script) : dechiffre l'enveloppe avec la cle du fichier, lit le conteneur RBXO (VM a 29 opcodes, constantes chiffrees), releve le Lua, retire les predicats opaques. ~0,1 s. Resultat complet.

## luauforge  — LuauForge
- Reconnaitre : `-- luauforge |`, `local __k=#("mot")` puis `local __w1=[` ; `local __d={...} local __s=[=[`. Couches : espaces/tabulations, dictionnaire de mots, puis machine virtuelle.
- Le bot : defait les couches statiques, EXECUTE la VM dans le bac a sable (sans reseau), livre le programme reel (un chemin d'execution) puis suit le chargeur `loadstring(game:HttpGet(url))()`.

## SANS moteur dans le bot (le dire honnetement : engine = unknown)
- Prometheus (« Protected by Prometheus », `-- This file was protected using Prometheus`) ; PSU / Konstant / Vigilant / WeAreDevs (« wearedevs.net/obfuscator ») / Synapse Xen / MoonSec V2 / IronBrew2 : le bot les NOMME, le detecteur ne les reconnait pas toujours, aucun moteur dedie. Le mode « trace d'execution » (bac a sable) montre au moins ce que le script fait.
- Chargeur a cle FlowAuth (« [FlowAuth] », flowauth.net) ou Luarmor (`script_key`, `loadstring(game:HttpGet("https://api.luarmor.net/..."))`) : le vrai script n'est servi qu'a un executeur autorise ; il n'est pas recuperable, jamais contacte. Ce n'est pas un obfuscateur a « casser ».
- Script en clair : `engine = unknown`, obfuscator = « non obfusque ».

## Regles pour repondre
- Choisir `engine` UNIQUEMENT parmi les noms de la liste fournie ou `unknown`. Ne jamais inventer de moteur.
- Un seul obfuscateur peut en cacher un autre (couches) : nommer celui de l'exterieur.
- Si plusieurs moteurs sont plausibles, prendre le plus specifique et expliquer le doute dans `advice`.
- `advice` : une phrase utile a l'utilisateur sur ce que le bot pourra (ou pas) obtenir, d'apres ces fiches.
