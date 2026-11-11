# Yslem Deobf Suite

Un seul dossier : le code du bot Discord (`/analyse`, `/process`, `/deobf`) **et** tous les moteurs de
déobfuscation. **Aucune installation manuelle** : Node.js et le Luau patché sont fournis automatiquement.

> **Luraph n'est plus pris en charge (2026-11-09).** Le moteur `luraph_v15`, la partie Luraph v14 de `deobf_py` et la
> famille `moteur: luraph` ont été retirés. Un fichier Luraph reçoit le message « Luraph n'est plus pris en charge par ce bot ».
> `luraph_tools_cog.py` (le noyau du bot) a été renommé `tools_cog.py` (classe `ToolsCog`) ; l'ancien bac à sable de trace
> `engines/luraph_v15` est devenu `engines/sandbox` (sans lifteur ni détection Luraph).

```
yslem_deobf_suite/
  bot_extension.py       point d'entrée unique pour le bot (charge les deux cogs)
  cogs/                  tools_cog.py (/analyse, /process, noyau du bot)  deobf_cog.py (/deobf, /deobf_engines, /deobf_moi)
  bootstrap.py           prépare tout seul Node.js + Luau patché (runtime/)
  deobf_router.py        détection de l'obfuscateur + lancement du bon moteur (sous-processus, timeout dur)
  lua_sandbox.py         trace de comportement pour /analyse (jamais exécuté dans le processus du bot)
  engines/               un dossier par moteur (deobf_py = IronBrew1, hercules, ironveil, ...) + `sandbox/` (bac à sable de trace, pas un moteur)
  runtime/bin/           Luau patché livré (Linux x86_64) ; runtime/node/ apparaît au premier usage si Node manque
  allowed_ids.txt        (à créer si besoin) ID Discord autorisés en plus du propriétaire
  tests/                 tests automatiques
```

## Mise en place (2 lignes dans le bot)

1. Copier le dossier `yslem_deobf_suite/` à côté du fichier principal du bot (même niveau que `main.py`).
2. Dans le code de démarrage du bot (le bot doit être un `commands.Bot` de discord.py ≥ 2.3) :
```python
await bot.load_extension("yslem_deobf_suite.bot_extension")
await bot.tree.sync()
```
Redémarrer. Au chargement le bot prépare Node.js / Luau en tâche de fond (~10 s, une fois) sans bloquer.
Le bot lui-même n'a besoin que de `discord.py`, `aiohttp` et `yarl` (déjà là pour tout bot discord.py) et de
Python ≥ 3.10. **Rien d'autre** à installer : si `node` manque, l'archive officielle nodejs.org (version figée,
SHA-256 vérifié) est téléchargée dans `runtime/node/` ; le Luau patché est livré (Linux x86_64) et recompilé
automatiquement ailleurs (il faut alors git + cmake ou g++).

## Commandes

| Commande | Qui | Rôle |
|---|---|---|
| `/analyse url:\|fichier:` | tout le monde (cooldown 20 s) | triage statique + **identification de l'obfuscateur** + trace de comportement dans un bac à sable (HttpGet, loadstring, requêtes, fichiers) ; jetons de webhook **masqués** ; **répond toujours en moins de 2 min** |
| `/process url:\|fichier:` | **propriétaire** | déobfusque (détection automatique) ; un `.zip` = jusqu'à 100 scripts traités **en même temps** |
| `/deobf url:\|fichier: [moteur] [timeout_min] [recalculer]` | **propriétaire** | idem, avec choix du moteur ; `recalculer:True` ignore le cache |
| `/deobf_annuler [nom]` | **propriétaire** | arrête **tous** les jobs en cours, ou seulement ceux dont le nom contient `nom` (et tous leurs processus) |
| `/deobf_engines` | **propriétaire** | moteurs installés et leur état |
| `/deobf_etat` | **propriétaire** | **diagnostic** : prérequis, jobs en cours (étape), 5 derniers jobs et leur livraison, **test d'écriture dans le salon** (et de MP) avec la raison exacte de l'échec |
| `/deobf_dernier [nombre]` | **propriétaire** | **renvoie le(s) dernier(s) résultat(s) sauvegardé(s)** dans la réponse (visible de toi seul) et en MP |
| `/deobf_moi` | tout le monde | affiche ton ID Discord et si tu as accès |

### `/analyse` : identification de l'obfuscateur (FINAL16)
1. **Détecteur de la suite** (toujours actif, local) : les règles de chaque moteur de `engines/` nomment l'obfuscateur et le moteur qui le déobfusquera.
2. **Avis d'un modèle de langage (facultatif, désactivé sans clé)** : si le détecteur ne reconnaît rien (ou avec moins de 90 % de confiance),
   un extrait du script est soumis à une API de modèle qui nomme l'obfuscateur. C'est un **avis affiché** (« Avis du modèle ») :
   il ne lance aucun moteur, et sa réponse est validée (liste fermée de moteurs, texte assaini).
   - Activer : variable d'environnement `DEOBF_LLM_API_KEY` (ou fichier `llm_api_key.txt` dans ce dossier, une ligne). **Jamais dans le zip ni dans Git.**
   - Fournisseur déduit de la clé (`AQ.`/`AIza` = Gemini, `sk-ant` = Anthropic, `sk-` = OpenAI) ; forçable avec `DEOBF_LLM_PROVIDER`, `DEOBF_LLM_MODEL`.
     Gemini : repli automatique sur plusieurs modèles (surcharge 503, modèle retiré).
   - **Confidentialité** : l'extrait envoyé (début + fin, ~4 ko, jetons de webhook et longues suites secrètes retirés) quitte la machine
     vers le fournisseur. Pas de clé, ou `DEOBF_LLM_OFF=1` = rien n'est envoyé.
   **Base de connaissances donnée à Gemini** : `obf_knowledge_fr.md` (dans ce dossier) résume, pour chaque moteur, comment reconnaître l'obfuscateur
   (indices dans le texte), ce que le bot peut ou non en tirer, les cas sans moteur (Prometheus, WeAreDevs, MoonSec V2, IronBrew2...), les chargeurs à clé
   (FlowAuth, Luarmor) et les scripts réservés à certains jeux. Elle est jointe à chaque question : Gemini répond avec le moteur, la raison et un
   conseil (« 💡 ») adapté. **Complète ce fichier** quand tu apprends à reconnaître un nouvel obfuscateur : c'est la façon la plus simple de l'apprendre à Gemini.
2 bis. **Aussi pour `/process` et `/deobf`** : quand le détecteur local ne reconnaît rien, ou que tous les moteurs reconnus échouent, le routeur
   demande l'avis du modèle et essaie le moteur qu'il désigne — seulement s'il figure dans la liste fermée des moteurs installés et sûrs
   (le modèle ne peut jamais faire lancer autre chose). Le journal du job affiche « avis du modèle : … ».
2 ter. **`/deobf` : analyse puis choix du moteur.** Avec `moteur: auto` (défaut), le bot analyse d'abord le script
   (détecteur de la suite + avis de Gemini, toujours demandé ici), puis affiche une interface : un menu avec **tous les moteurs installés**
   le moteur recommandé marqué ⭐, et « auto ». Le script n'est déobfusqué
   qu'après ton choix (3 min pour choisir). Un `.zip` ou un `moteur:` précis lance directement le job. `DEOBF_PICKER=0` désactive le menu.
3. **Échéance globale de 120 s** : au-delà, message explicite (plus de « réfléchit… » sans fin). Le calcul (regex) tourne hors de la boucle
   d'événements, l'identification et le bac à sable s'exécutent en parallèle. Un script trop lent à tracer (VM d'obfuscation lourde) affiche
   « délai dépassé : … /process peut le déobfusquer » au lieu d'un message brut.

`/process` et `/deobf` exécutent **le même code** (`run_job`) que la ligne de commande
`python3 deobf_router.py run entree.lua sortie.lua` : même moteur, même résultat.

### Où va le résultat : dans la conversation, plusieurs jobs en même temps
**Pas de file d'attente** : chaque commande démarre tout de suite, même si d'autres jobs tournent (2, 10 ou 100 en même temps).
Un `.zip` (jusqu'à 100 scripts, 64 Mo décompressés) lance un job par script, tous en parallèle. Deux fois le même script en même
temps = **un seul calcul partagé**.
1. Le bot poste **un seul tableau de bord par salon**, qu'il **modifie toutes les 5 secondes**, avec une ligne par job :
```
⏳ spicy3.txt (594 Ko) — Etape 5/7 Reconstruction — tentative 5
   ▓▓▓▓▓▓▓▓░░░░ 66 % · 1 min 35 s · reste ~49 s
✅ lenon_obf.txt — terminé en 2 min 03 s
```
   (étape réelle du moteur, barre, temps écoulé, **compte à rebours**). C'est un message normal du bot, **sans la limite de 15 min**
   des réponses de commandes. La réponse « visible de toi seul » de la commande est **supprimée** : plus de messages en arrière-plan.
   Le tableau passe à « ✅ terminé » **dès la fin du dernier job** (avant, jusqu'à 5 s de retard) et le compte à rebours ne remonte jamais :
   arrivé à zéro il affiche « plus long que prévu, je continue ».
2. À la fin de chaque job, le bot poste **le fichier `deobfuscated_<nom>.lua`** (avec une mention), le résumé de sécurité
   (`findings.txt`) et, en cas d'échec, le journal `deobf_log.txt` avec la cause. Plus de MP en fonctionnement normal.
3. **Replis automatiques** si le bot ne peut pas écrire dans le salon (droits « Envoyer des messages » / « Joindre des fichiers » manquants) :
   MP → copie dans `results/` (20 derniers), MP retenté après 1, 5, 15 min, 1 h, 3 h.
4. **À tout moment** : `/deobf_dernier` renvoie le dernier résultat, `/deobf_etat` montre ce qui s'est passé (et teste l'écriture dans le salon),
   `logs/deobf.log` garde l'historique côté serveur.
**Cache** : un script déjà déobfusqué (même contenu, empreinte SHA-256) est renvoyé **instantanément** (« ⚡ déjà calculé le … »).
Seuls les résultats complets sont mis en cache. Le résultat vérifié de Spicy3 est livré avec la suite (`cache_seed/`).
**Partage du CPU** : les jobs simultanés se partagent les cœurs ; le bot répartit automatiquement les lifteurs parallèles
(`DEOB_LIFT_PARALLEL`) selon le nombre de jobs actifs et la mémoire libre (≈ 350 Mo par lifteur). 100 jobs sur 2 cœurs fonctionnent,
mais chacun va ~50× moins vite qu'un job seul : le temps total ne diminue pas, il est seulement partagé.
⚠️ Le fichier est visible de **tous ceux qui voient le salon** : utilise un salon privé
(il peut contenir des webhooks / jetons du script analysé, que le résumé masque mais pas le fichier).

#### Quand ça rame ou que ça bloque : le bot le dit et donne la cause
- L'avancement affiché est celui du **moteur en direct** (les lignes qu'il écrit changent l'étape), plus une ligne d'activité réelle :
  `🖥️ luau · CPU 97 % · 310 Mo · RAM libre 1200 Mo`.
- La phase affichée est la **vraie** : « Etape 1/6 Préparation » tant que Node.js / Luau se préparent (avec « téléchargement de Node.js : 12 / 30 Mo »
  ou « attente : un autre processus prépare… »), puis le moteur. Le dernier message réel du moteur est montré (💬) et le CPU / la mémoire sont ceux de
  **tout l'arbre de processus** du moteur (Node, Luau, lifteurs).
- **Machine bridée** : le bot lit la limite CPU de l'hébergeur (cgroup) et du système. S'il reste moins de 1,5 cœur utilisable, le message affiche
  « ⚠️ CPU limité : 0,25 cœur utilisable (8 visibles) → job ~16× plus lent (estimation 38 min) ». Il **adapte** alors l'estimation, les délais et les
  budgets du moteur. **Machine faible** (moins d'un cœur par job), deux modes (`DEOBF_WEAK_MODE`) :
  - **`complet` (défaut)** : le moteur garde **toutes** ses tentatives (32) et dispose d'un long budget (jusqu'à 40 min de tentatives, une à la
    fois). Il s'arrête **dès qu'un résultat complet est trouvé** (une tentative sur ~10 réussit). Le job est long (le délai passe automatiquement
    à ~75 min sur 0,25 cœur ; ton `timeout_min` est respecté s'il est précisé), mais il se termine complet dans la grande majorité des cas.
    Le tableau de bord affiche « 💪 Machine faible … mode COMPLET » et le compte à rebours.
  - **`rapide`** : 2 à 11 tentatives et durée plafonnée → un résultat en quelques minutes, mais souvent **partiel** (« N blocs non reconstruits »).
  Si l'hébergeur annonce un quota **faux**, `DEOBF_FORCE_CPU=2` impose le nombre de cœurs utilisables (`/deobf_etat` l'indique). Le calcul de Luraph v15 est lourd (~6 min de CPU pour Spicy3, avec des
  tentatives aléatoires du lifteur) : sur un hébergeur à CPU très limité, prévois un serveur avec ≥ 2 cœurs. `/deobf_etat` affiche le CPU utilisable.
- Réseau coupé ou nodejs.org inaccessible : échec en 30 s (réglable : `DEOBF_NET_TIMEOUT`) avec la consigne « installe Node.js ≥ 18 sur la machine du bot ».
- Si **rien ne bouge** (aucune sortie ET aucun CPU) pendant 60 s, le message ajoute « ⚠️ Aucune activité depuis 1 min 10 s ; processus : node[S], luau[S] ;
  tous attendent (réseau, disque ou verrou) ; mémoire … ; dernière étape connue : … ». Au bout de 4 min d'inactivité totale le job est **arrêté** et
  la cause est écrite (réglable : `DEOBF_STALL_WARN`, `DEOBF_STALL_KILL`). Un moteur qui calcule (CPU) n'est jamais pris pour un blocage.
- Les échecs sont **expliqués** : « le système a TUÉ le moteur (mémoire insuffisante probable) », « temps maximal dépassé », « aucun obfuscateur reconnu »,
  « Node.js introuvable », ligne d'exception du moteur, « résultat PARTIEL : N blocs non reconstruits »…
- Si Discord refuse de modifier le tableau de bord (message supprimé, droits retirés, limitation) : le bot poste « Je n'arrive plus à modifier le message de
  suivi (HTTP 404, code Discord 10008…) » et continue dans un nouveau message.
- Si le **bot lui-même redémarre** pendant un job (hébergeur, plantage, mémoire) : au redémarrage, le tableau de bord devient
  « ⚠️ Job interrompu : le bot s'est arrêté ou a redémarré pendant la déobfuscation ».
- Si le bot est figé (machine surchargée) : « Le bot a été figé ~N s ».

#### « Je n'ai rien reçu » : marche à suivre
1. `/deobf_etat` — la commande **n'existe pas** ? Alors l'ancien code tourne encore : vérifier que le dossier a été remplacé, que le bot a été
   redémarré et que `await bot.tree.sync()` a été exécuté.
2. Dans `/deobf_etat`, ligne « Ecriture dans ce salon » : si ECHEC, donne au bot les permissions « Voir le salon », « Envoyer des messages »,
   « Joindre des fichiers » et « Intégrer des liens » dans ce salon.
3. « Prérequis : BLOQUÉ » : lis la raison (machine non Linux x86_64 sans git + cmake/g++, pas d'accès à nodejs.org...).
4. Une ligne du tableau de bord reste bloquée sur une étape : machine lente ; le délai maximal est de 25 min, après quoi le bot tue le job et poste l'échec.
5. Le résultat est toujours dans `results/` sur la machine du bot (et `/deobf_dernier`), `logs/deobf.log` dit pourquoi.

### Qui a le droit : `/process`, `/deobf`, `/deobf_engines`
- le propriétaire de l'application du bot (ou les membres de son équipe) ;
- les ID listés dans `allowed_ids.txt` (un par ligne, `#` = commentaire ; relu à chaque commande) ou dans la
  variable d'environnement `DEOBF_ALLOWED_IDS="123, 456"` ;
- si `DEOBF_ALLOW_GUILD_ADMINS=1` : les administrateurs du serveur (désactivé par défaut : ces commandes
  exécutent des scripts inconnus).
`/deobf_moi` te montre ton ID. Le garde-fou est un vrai `app_commands.check` (`owner_only()`) : le décorateur
`@commands.is_owner()` des commandes préfixées n'est **pas** appliqué par discord.py sur une commande slash
(`cmd.checks == []`) — `tests/test_owner_guard.py` le prouve.

## Moteurs

| Moteur | Obfuscateur | État vérifié |
|---|---|---|
| `deobf_py` | IronBrew 1 | code reconstruit (échantillon : 36 lignes lisibles). Sert aussi de repli « trace de comportement ». |
| `legaxyobf` | legaxyobf (enveloppe RBXE ChaCha20-Poly1305 + VM RBXO) | **complet** : déchiffre l'enveloppe, relève la VM, retire les prédicats opaques, sans exécuter le script (~1 s). `tests/test_legaxyobf.py`. Un opcode inconnu est signalé en commentaire. |
| `luauforge` | LuauForge (couches statiques + machine virtuelle) | défait **exactement et sans exécuter** les couches « espaces/tabulations → octets » et « dictionnaire de mots » (chacune vérifiée par `luau-ast`). S'il reste une **machine virtuelle** (code aplati, constantes chiffrées), elle est **exécutée dans le bac à sable** (sans réseau) et le fichier livré est le **programme réel** qu'elle révèle, puis le routeur suit le chargeur éventuel. **Limite** : c'est le comportement sur *un* chemin d'exécution (les blocs `Folder` créés puis détruits sont des leurres), pas un dévirtualiseur complet |
| `hercules` | Hercules 1.6 → 2.0 | VM, BytecodeEncoder et `--maximum` : OK ; presets « source seule » refusés |
| `ironveil` | Ironveil v1 | OK |
| `wearedevs` | WeAreDevs obfuscator / Prometheus (avec l'en-tête `--[[ v1.0.0 https://wearedevs.net/obfuscator ]]` **ou sans** : même modèle à table de chaînes décimales) | **Lua RECONSTRUIT** (pas le fichier d'origine : noms de variables perdus, structure `if`/`while` reconstruite, chaînes chiffrées déchiffrées), vérifié dans le bac à sable ; **repli sur la TRACE** si le relevé échoue. Banc d'essai sur 120 fichiers tirés des dépôts d'échantillons : 98 % reconstruits ou équivalents (voir la section « Relevé de la machine à états »). |
| `moonsec_trace` | MoonSec **V2** (`Protected_by_MoonSecV2`) et **V3** (secours) | **TRACE, pas le source**. Seul moteur pour MoonSec **V2** ; pour la **V3** il ne sert plus que de secours si `moonsec_v3` échoue (par ex. .NET indisponible). Banc d'essai : **25 échantillons sur 30** vont au bout (de 10 à 3 702 lignes). |
| `ironbrew2` | IronBrew 2 et forks : KrystekYT, SFG ENCRYPTED, NCDev Team Evolution, AztupBrew, moonstrike.cc, et les IronBrew 2 « V2 » sans en-tête (structure reconnue) | **Bytecode Lua 5.1 reconstitué puis décompilé (LuaDec)**, toujours **PARTIEL** (structure et noms approximatifs, détecteurs anti-exécuteur du script conservés). Le dispatch de la VM est lu dans le script (AST) et chaque handler est classé par la forme de ses micro-opérations : aucune table propre à un fork. Vérifié : même séquence d'appels/accès que la VM originale (scénarios stricts + permissif) sur 7 forks et les fichiers de test ; le bytecode est chargé et contrôlé par un vérificateur Lua 5.1. Forme de handler inconnue -> échec explicite, rien d'inventé. IronBrew 3 (`--ironbrew3`) : autre VM, pas pris en charge. |
| `boronide` (sans moteur) | Boronide (`Boronide™`, `discord.gg/boronide`) | **Non pris en charge** : son en-tête imite `Protected_by_MoonSecV2`, il n'est donc PAS classé MoonSec. |
| `moonsec_v3` | MoonSec **V3** (`This file was protected with MoonSec V3`) | **Vrai source** : devirtualisation (MoonsecDeobfuscator, C#, livré pré-compilé dans `engines/moonsec/bin/`) puis décompilation du bytecode Lua 5.1 (`decom.lua` = LuaDec, exécuté dans un Lua isolé). Le runtime **.NET 9** est celui du système ou est **téléchargé une fois** (archive officielle Microsoft, SHA-512 figé, `runtime/dotnet/`, ~75 Mo ; pré-installé par le Dockerfile). Banc d'essai sur **60 échantillons MoonSec V3 : 60/60 devirtualisés et décompilés en < 3 s (à 512 Mo)**, tas .NET plafonné à 512 Mo (`MOONSEC_HEAP_HEX`; à 96 Mo, 29 échantillons sur 60 échouaient en « Out of memory », à 300 Mo encore 2). La décompilation reste **approximative** : 49/60 gardent des `upval_N` (upvalues non résolues) → le bot affiche **PARTIEL** avec la raison ; 11/60 sans défaut visible → réussi. Si la décompilation échoue, le désassemblage est livré (partiel). **V2 non géré** par cet outil. |
| `psu_trace` | PSU Obfuscator 4.x (`This file was obfuscated using PSU Obfuscator`) | **TRACE, pas le source**. 9 échantillons sur 10 vont au bout. Les échantillons « AztupBrew » du dépôt vyxonq-dev sont en fait du PSU. |
| `trace` | n'importe quel script (utile aussi pour IronBrew 2, MoonVeil, Boronide, wYnFuscate, LuaST, Synapse Xen : en-têtes variables ou taux de réussite < 60 %) (VM ou obfuscateur sans moteur dédié) | **À la demande seulement** (`/deobf moteur: trace` ou `--engine trace`, jamais choisi automatiquement). Exécute le script dans le bac à sable et livre la TRACE de ce qu'il fait (étiquetée, pas le source). Vérifié sur une VM sans en-tête : statut `finished`, 588 lignes. Une VM lourde peut atteindre le délai (150 s). |
| `leakd_luaobfuscator` | LuaObfuscator.com | **partiel** |
| `centurion_v6` | Centurion v6 / v6.1 | **détection seule, non fonctionnel dans ce zip** : l'exécution exige `luau-compile` (non livré : code 4 « luau-compile not found ») et l'échantillon `tests/samples/centurion_v6.lua` relève de la route v6.1, qui demande un vrai Roblox (`invalid argument #1 to create (size)`, verdict NEEDS). Le « partiel v6 statique » vient des échantillons du dépôt d'origine, absents d'ici. L'autotest ne vérifie que la détection. |

Non inclus volontairement : `ib2-deobf` (IronBrew 2 : exécutables .NET sans source, exécution avec stdlib
complète, envoi du bytecode à un serveur tiers).

### LuauForge : de l'emballage au script final (exemple réel)
Un script de 528 Ko → 2 couches statiques retirées exactement → une machine virtuelle de 160 Ko (≈ 4 000 lignes de code aplati, 10 301 constantes
cachées derrière `e(-N)`, ~100 noms leurres) → exécutée dans le bac à sable → **9 lignes** (deux dossiers leurres, `HttpGet`, `loadstring`) → le chargeur
est suivi → un script de 291 Ko en clair. Le bot livre un seul fichier : la chaîne, le programme réel, puis le script final.
Le correctif clé du bac à sable : une globale à **nom aléatoire** (9-16 lettres/chiffres, majuscules + minuscules + chiffre, ex. `LPNAWR0rtFSf`)
vaut `nil` — la machine y range ses adresses de retour ; un faux objet à la place la faisait planter (« compare userdata < number »).
Le bot l'annonce : « 🧠 Protection LuauForge : … machine virtuelle exécutée dans le bac à sable ».

### Chargeurs : `loadstring(game:HttpGet("https://…"))()`
Un script qui ne fait que télécharger puis exécuter un autre script n'est **pas obfusqué** : le vrai code est à l'adresse indiquée.
Le routeur la **télécharge** (comme le ferait l'exécuteur), suit la chaîne (4 niveaux au plus) puis traite le script récupéré :
déobfusqué s'il l'est (`loader_chain+luauforge`…), livré en clair sinon. Le fichier rendu commence par la chaîne (adresses, tailles, sha256).
- **Garde-fous** : seulement `http(s)` sur les ports 80/443/8080/8443, aucune adresse privée / locale / réservée (vérifiée à chaque redirection),
  5 redirections, 8 Mo, 20 s ; seul un script **court** (≤ 8 Ko) dont le seul `HttpGet` est une adresse littérale est suivi.
  Rien n'est exécuté. `DEOBF_FOLLOW_LOADERS=0` désactive tout. Le résultat n'est jamais mis en cache (le contenu distant change).
- **Services de protection (Luarmor)** : le contenu n'est servi qu'à un exécuteur autorisé (clé / identifiant machine). Le bot **ne contacte pas**
  ces adresses et n'imite pas un exécuteur : il s'arrête, le dit (« 🔒 protégé par Luarmor : le code réel n'est pas récupérable ») et livre la chaîne.
  Si tu possèdes le script (clé valide), envoie-le directement.

### Second étage : le code chargé par `loadstring`
Beaucoup de scripts sont des **chargeurs** : la VM ne fait que déchiffrer un autre code puis l'exécuter avec `loadstring`.
Avant, seuls les 200 premiers caractères de ce code apparaissaient dans la trace. Maintenant, le bac à sable transmet le
source **complet** de chaque `loadstring` (quelle que soit sa taille, jusqu'à 4 Mo, 8 morceaux), et le routeur :
- l'ajoute **en tête du résultat**, dans un bloc `do local function second_etage_N(...) … end end` (le fichier reste du Luau valide) ;
- le **déobfusque à son tour** s'il est lui-même obfusqué par un autre obfuscateur reconnu (2 niveaux au plus) ;
- ignore la VM interne que le moteur a déjà traitée.
Le bot l'annonce : « 📦 N second(s) étage(s) récupéré(s) ».
Limite : un code téléchargé (`game:HttpGet`) n'existe pas dans le bac à sable (pas de réseau) : seule l'URL apparaît.

### legaxyobf (FINAL21)
Enveloppe `RBXE` chiffrée en ChaCha20-Poly1305 **dont la clé est dans le fichier**, conteneur `RBXO` (machine virtuelle à 29 opcodes, constantes chiffrées
par un flot dépendant d'une somme de contrôle du bytecode), plus des blocs « anti-falsification » morts (prédicats opaques). Le moteur `legaxyobf`
(Python pur, **n'exécute jamais le script**) déchiffre, vérifie l'étiquette Poly1305, lit le bytecode et relève le Lua en ~0,1 s ; test : `tests/test_legaxyobf.py`.

## Banc d'essai sur des dépôts d'échantillons (2026-11-09)

Outil : `tests/bench_samples.py` (`SAMPLE_REPOS="sz=/chemin/a,vy=/chemin/b" python3 tests/bench_samples.py`). Il prend 10 échantillons par famille
(répartis sur les versions), fait la détection en direct puis lance `--engine <détecté>` ou `--engine trace` (aucun accès réseau).
Dépôts : `SixZensED/luau-obfuscator-samples` (607 fichiers) et `vyxonq-dev/obfuscator-samples` (22 747 fichiers, 17 familles), 220 échantillons testés.

| | départ | après correctifs |
|---|---|---|
| réussis (moteur OK ou trace jusqu'au bout) | 92 | **149** |
| échecs durs (aucune sortie) | 39 | **1** |
| Luraph (message « non pris en charge ») | 11 | 11 |

Correctifs du bac à sable `envlog.luau` trouvés grâce au banc : (1) noms de globales aléatoires **sans chiffre** (WeAreDevs : `qJsOminZtkUaum`) = `nil`, pas un proxy ; (2) bibliothèque **`bit`** de LuaJIT (IronBrew 2 : `bit.bxor`) ; (3) alias `connect` / `wait` / `disconnect` ; (4) noms de globales **tout-chiffres**. Nouveaux moteurs : `moonsec_trace`, `psu_trace`.
Restent faibles (réussis / 10) : wYnFuscate 3, MoonVeil 3-5, LuaST 2, Boronide 3-4, Synapse Xen (en-têtes variables) : moteur `trace` à la demande.

## Tests (tous sans prérequis)
```bash
python3 selftest.py                  # détection + exécution des moteurs + garde-fou        -> « AUTOTEST OK »
python3 tests/test_owner_guard.py    # 3 commandes owner-only vérifiées                       -> « TOUT OK »
python3 tests/test_cog_fixes.py      # correctifs du téléchargement / envoi                    -> « TOUT OK »
python3 tests/test_bot_e2e.py        # le bot complet avec un faux Discord (MP, retries, /analyse, droits)
python3 tests/test_discord_http.py   # idem avec la VRAIE bibliothèque discord.py sur un faux serveur HTTP Discord (MP réels, 403/429/500, jeton expiré, /deobf_dernier)
python3 tests/test_luauforge.py      # moteur luauforge : couches fabriquées puis défaites exactement + machine virtuelle factice exécutée  -> « TOUT OK »
python3 tests/test_loader_chain.py   # chargeurs suivis, garde-fous anti-SSRF, Luarmor jamais contacté, LuauForge → machine virtuelle → chargeur → script final  -> « TOUT OK »
python3 tests/test_lifter_determinism.py  # Spicy3 avec UNE seule tentative, 2 fois : 0 bloc manquant, sortie identique (~2 min)
python3 tests/test_detection.py      # détection sans en-tête (v14, v15 + superflow) et second étage -> « TOUT OK »
python3 tests/test_stack_fidelity.py # pile C du bac à sable identique à Roblox (« C stack overflow » à 198, rien au-dessus du script) -> « TOUT OK »
python3 tests/test_legaxyobf.py      # legaxyobf : détection + déobfuscation complète -> « TOUT OK »
python3 tests/test_identify.py       # identification de l'obfuscateur (sans réseau : API simulée), secrets retirés, clé jamais affichée -> « TOUT OK »
python3 tests/test_extension_load.py # l'extension se charge dans un vrai commands.Bot (7 commandes, limites Discord)
python3 tests/test_bot_e2e.py --full # idem + Spicy3 complet : le MP == le résultat de la ligne de commande
```

## Bugs corrigés dans les cogs d'origine
| Où | Défaut | Correctif |
|---|---|---|
| téléchargement (`url:`) | **fichiers tronqués en silence** (`StreamReader.read(n)` ne rend pas n octets) | lecture par blocs jusqu'à la fin ; liens `github blob` / `pastebin` convertis en brut |
| `/analyse` | regex quadratique : un fichier de 7 Mo **gelait le bot** (déconnexion de la gateway) | motif supprimé, analyse bornée (début + fin) |
| `/analyse` | **jeton de webhook affiché en clair** dans une réponse publique | masqué dans l'embed et le rapport |
| `/analyse` | bac à sable absent (`lua_sandbox.py` jamais livré) → « Non exécuté » | `lua_sandbox.py` livré (Luau patché, limites CPU, timeout) |
| `/process` | résultat en pièce jointe éphémère : perdu si le jeton expire (15 min), si > 8 Mo, ou en cas d'erreur Discord | suivi en direct + fichier **dans le salon**, replis (interaction → MP → disque), copie dans `results/` |
| `/process`, `/deobf` | commandes slash « owner » ouvertes à tous (`is_owner()` sans effet) ; pas d'accès pour un administrateur de confiance | `owner_only()` + `allowed_ids.txt` / `DEOBF_ALLOWED_IDS` |
| `/process` + `/deobf` | pouvaient tourner en même temps | verrou unique |
| **Python ≤ 3.11** | `tools_cog.py` (alors `luraph_tools_cog.py`) ne se chargeait **pas** (f-string avec backslash : SyntaxError) | corrigé, testé sous 3.11 + discord.py 2.3.2 |
| **Python ≤ 3.11** | un processus orphelin gardant le tube ouvert bloquait le job jusqu'au délai (25 min) alors que le résultat était prêt | la fin du job = la fin du processus (waitpid) ; sortie moteur dans un fichier ; groupe de processus tué |
| rechargement | `reload_extension` échouait (« cog already loaded ») | `teardown` retire les cogs |
| résultat non livré | aucun moyen de le récupérer ni de savoir pourquoi | tableau de bord avec compte à rebours, journal, `/deobf_dernier`, `/deobf_etat`, renvoi différé du MP |
| erreurs après `defer()` | « réfléchit… » sans fin | réponse par `followup` |

## Sécurité — à lire
- **Le bac à sable n'est pas une isolation système.** Les moteurs exécutent le script dans un Luau qui journalise
  `HttpGet`/`writefile`/... au lieu de les faire (Luau n'a ni réseau ni disque), mais sans conteneur. Hébergez le bot
  dans un conteneur/VM sans secrets, gardez `/process` et `/deobf` réservés. `/analyse` (public) n'exécute que la
  trace de comportement, avec limite CPU, timeout et fichier ≤ 384 Ko.
- Les résultats peuvent contenir des webhooks ou jetons (ceux du script analysé) : ils sont postés dans le salon de la commande — utilise un salon privé.
- Node.js téléchargé = archive officielle nodejs.org, SHA-256 figé dans `bootstrap.py`.

## Dépannage
| Symptôme | Cause / remède |
|---|---|
| « Commande réservée au propriétaire… » | `/deobf_moi` → ajoutez votre ID dans `allowed_ids.txt` |
| Le suivi/fichier n'apparaît pas dans le salon | permissions du bot dans ce salon (voir `/deobf_etat`) ; sinon MP |
| « préparation automatique impossible » | pas d'accès à nodejs.org (installez Node ≥ 18) ou architecture non Linux x86_64 sans git + cmake/g++ |
| `/analyse` : « Sandbox : Erreur » | lancer `python3 bootstrap.py` à la main pour voir l'erreur |

Crédits et licences : `NOTICE_FR.md`.



## Relevé de la machine à états (moteur `wearedevs`)

Le modèle WeAreDevs / Prometheus « v1.0.0 » n'est **pas** de la virtualisation à bytecode : le script d'origine est converti en une machine à états
(un répartiteur `while v do if v < N ...` dont chaque feuille est un bloc de code à trois adresses), avec les variables locales rangées dans une
table indexée par des identifiants alloués à l'exécution et les chaînes dans une table chiffrée. Le moteur la relève :

1. `parse.js` (luaparse, MIT, légèrement patché pour les `+=` de Luau) → AST ; la table de chaînes est obtenue en **exécutant son prélude dans le bac à sable** ;
2. reconnaissance des rôles (répartiteur, créateurs de fermetures par arité, allocation/libération de variables, table de variables, point d'entrée) ;
3. blocs → forme à versions (SSA locale), propagation conditionnelle de constantes et de références (qui rend `y[x]` lisible comme une variable), pseudo-registres pour les
   tables-registres (`BH[1]`...), graphe de flot par fonction ;
4. suppression du code mort, intégration des temporaires à usage unique (en respectant l'ordre des effets), déchiffrement des chaînes (exécution dans le bac à sable) ;
5. structuration (dominateurs, post-dominateurs, boucles naturelles) en `if`/`while`/`break`/`continue` ; **repli en machine à états** pour une fonction non structurable ;
6. vérification : le Lua reconstruit compile, puis sa trace dans le bac à sable est comparée à celle de l'original. Si le reconstruit se comporte moins bien que l'original,
   le moteur livre la trace à la place (avec la raison en tête de fichier).

Ce que le fichier reconstruit contient encore : le code parasite de l'obfuscateur (anti-altération par numéros de ligne d'erreur, fonction de déchiffrement), des noms
`v1`, `t1`, `r_x`, `p1`. Il n'est **pas** garanti identique à l'original instruction par instruction : il est équivalent (même trace) sur les chemins que le bac à sable exerce.
Les scripts qui utilisent de l'aléatoire ou du temps donnent des traces différentes d'une exécution à l'autre ; le moteur le dit (« les deux terminent mais les traces diffèrent »).
Limites connues : saut vers une boucle englobante (labels) → repli en machine à états pour cette fonction ; fichiers qui ne compilent pas (deux programmes concaténés) → repli sur la trace.

## Déploiement : fichiers qui ne doivent pas être perdus

Le bot a besoin de `runtime/bin/linux-x86_64/luau` et `luau-ast` (Luau patché, binaires statiques). Si un déploiement les perd (`.gitignore` ou `.dockerignore` qui exclut
`bin/`, copie qui ne garde que le texte, extraction qui retire le bit d'exécution), `bootstrap.py` :
1. remet le bit d'exécution et copie les binaires dans les dossiers des moteurs ;
2. à défaut, les **reconstruit depuis `luau_blob_linux_x86_64.txt`** (tar + xz + base64, SHA-256 vérifié) : ce fichier texte survit à ces filtres, ne pas l'exclure ;
3. à défaut, recompile Luau (git + cmake ou g++ requis ; sinon l'erreur nomme le fichier absent et la cause probable).
Tests : `tests/test_bootstrap_noexec.py`, `tests/test_bootstrap_blob.py`.

Les prérequis manquants (Luau, Node) ne bloquent plus un job d'emblée : le moteur n'est pas encore choisi à ce stade et beaucoup (LuaObfuscator, legaxyobf, hercules) n'en ont pas besoin.
Un moteur qui en a besoin échoue lui-même (« prerequis manquant : ... ») et la cause affichée rappelle le prérequis absent.

# Refonte de l'interface Discord (FINAL35)

## Ce que fait le bot maintenant
L'utilisateur envoie un script (`/get`, `.get`, `/deobf`, `.deobf`) : le bot **analyse seul** le contenu, **reconnaît l'obfuscateur sur preuve technique**
(règles des moteurs, jamais de supposition), **choisit lui-même le moteur** (`decision.py`) et répond par **un seul message court** (embed : statut, fichier,
protection, moteur, durée) avec le fichier nettoyé. Il ne demande jamais quel moteur utiliser (le champ `moteur` de `/deobf` reste pour forcer un moteur ;
`DEOBF_PICKER=1` rétablit l'ancien menu « quel moteur ? »).

| Statut | Quand |
|---|---|
| ✅ Réussie | code source reconstruit, rien de manquant détecté |
| ⚠️ Partielle | trace d'exécution (le source n'est pas reconstruit), blocs non reconstruits, chaînes encore chiffrées, opcodes non résolus, arrêt dans le bac à sable |
| ❌ Échec | rien produit, contenu invalide (vide, HTML, JSON, binaire), obfuscateur non pris en charge ou moteur indisponible |
| ❌ Protégé | Luarmor, FlowAuth, LuaProtect : clé / licence / autorisation requise — reconnu, **jamais contourné** |

Un résultat incomplet n'est jamais présenté comme réussi (`result_tools.classify`). Luraph n'est plus pris en charge (retiré à la demande) : reconnu, refusé clairement.
Les bannières et en-têtes des moteurs (publicités, `-- TRACE`, `Source RECONSTRUIT`, avertissements) sont retirés du **début** du fichier ; les vrais commentaires du code sont conservés.

## Commandes (slash ET préfixe : mêmes fonctions, mêmes interfaces)
| Slash | Préfixe | Droits | Rôle |
|---|---|---|---|
| `/get` | `.get` | tous (anti-spam) ; « Oui » réservé au propriétaire / ID autorisés | récupère (lien ou fichier), analyse, propose **Oui / Non** |
| `/panel` | `.panel` `.menu` | tous (chaque panneau applique ses droits) | tableau de bord : Préfixes · Déobfuscation · Moteurs · Statistiques · Paramètres |
| `/prefix` | `.prefix` | tous en lecture ; « Gérer le serveur » pour modifier | panneau des préfixes |
| `/stats` | `.stats` | propriétaire / ID autorisés | statistiques |
| `/deobf` `/process` `/deobf_engines` `/deobf_etat` `/deobf_dernier` `/deobf_annuler` | `.deobf` `.process` `.engines` `.etat` `.dernier` `.annuler` | propriétaire / ID autorisés | existants, conservés |
| `/analyse` `/deobf_moi` | `.analyse` `.moi` | tous | existants, conservés |

`.get` : pris en charge → boutons ✅ Oui (lance la déobfuscation, moteur automatique) / ❌ Non (annule, **l'analyse reste affichée**) ; non pris en charge, protégé, vide,
HTML, erreur HTTP → message court, sans boutons. Les redirections HTTP et les clés demandées par le script sont signalées.

## Préfixes par serveur (persistants)
Ajouter, modifier, supprimer, réinitialiser (boutons, menus déroulants, fenêtres modales). Plusieurs préfixes par serveur (8 max), 1 à 5 caractères, sans espace ni
`@ # < > \ ` * _ ~ |`, pas de `/` initial, doublons refusés. Sauvegarde automatique dans `data/settings.json` (écriture atomique ; fichier corrompu mis de côté, le bot repart
par défaut). Sans réglage, **les préfixes d'origine du bot restent actifs** ; « Réinitialiser » y revient. En MP : préfixes par défaut. Le bot reste joignable par mention.
Au déchargement de l'extension, l'ancien `command_prefix` est restauré.

## Sécurité, performances, journaux
- SSRF : IP privées / locales / cloud, ports sensibles, schémas non http(s) refusés (aussi après résolution DNS et à chaque redirection) ; 7 Mo max ; 4 téléchargements simultanés ; cache de 2 min.
- Anti-spam par utilisateur (6 commandes / 30 s ; 30 pour le propriétaire). Aucune opération n'est bloquante : calculs lourds dans des threads, délais partout.
- Les journaux (`logs/deobf.log`, `logs/jobs/<id>.log`) **masquent** jetons Discord, webhooks, clés d'API et valeurs de `DISCORD_TOKEN` / `DEOBF_LLM_API_KEY`.
  Le détail technique d'un job (journal du moteur, détection) n'est **que** dans `logs/jobs/` (administrateur) : le salon ne reçoit que le statut.
- Statistiques (`data/stats.json`, via `/stats`) : analyses, déobfuscations réussies / partielles / échecs, temps moyen, utilisateurs, 50 dernières opérations.

## Ajouter un obfuscateur
Un dossier `engines/<nom>/engine.json` avec ses règles `detect` suffit (voir « Moteurs »). Champs facultatifs lus par `decision.py` : `"display"` (nom affiché),
`"kind"` (`source` ou `trace`), `"unavailable"` (raison si le moteur ne peut pas tourner : il est alors reconnu mais **jamais présenté comme pris en charge**).

## Variables d'environnement
`DEOBF_DATA_DIR` (dossier des réglages/stats), `DEOBF_PICKER=1` (ancien menu de choix du moteur), `DEOBF_DECIDE=0` (désactive la décision automatique : le routeur choisit seul),
`DEOBF_PREFIX=0` (n'installe aucune commande à préfixe), `DEOBF_KEEP_PREFIX=1` (ne remplace pas une commande à préfixe existante du même nom — **par défaut `.get`, `.panel`... remplacent**
celles de l'ancien bot qui portent le même nom).

## Rework FINAL41 (vitesse / puissance) — mesures honnêtes
**Puissance**
- Détection : variantes MoonSec V3 (en-tête `([[This file was protected with MoonSec V3…]]):gsub(`) et LuaObfuscator (`local v0=string.char;local v1=string.byte;…`) reconnues par leur moteur.
  Sur le corpus de 2 591 fichiers testés : routage vers un moteur à **code source réel** 893 → 1 040 (+147). Série de 24 échantillons : code réel 14/24 → 24/24.
- **Échéance native dans Luau** (`DEOB_DEADLINE_MS`, marge `DEOB_DEADLINE_SLACK`, 15 s par défaut) : passé le délai, le script analysé reçoit l'erreur « execution deadline », même dans un
  calcul pur ; le thread du harnais n'est jamais interrompu, donc la **trace partielle sort toujours** (statut « stopped at the time limit (truncated) »). Les pires cas (boucles sans fin) sont bornés.
  Patch reproductible : `engines/sandbox/build_luau.py` (`patch_deadline`). Nouveau binaire `luau` (sha256 dans `bootstrap.py`), profondeur de pile C inchangée (198).
- MoonSec : plafond mémoire .NET 512 Mo (`MOONSEC_HEAP_HEX`).

**Vitesse** — mesurée, sans enjolivement
- Vitesse moyenne **inchangée** (série de 24 : 22,6 s → 25,4 s, dans le bruit ; plus de fichiers vont à de vrais moteurs, donc un peu plus de travail).
- Tentative d'accélération du parseur ANTLR d'IronBrew2 : **aucun gain réel** en pipeline (le gain mesuré était un artefact de cache), annulée. Démarrage .NET de MoonSec (~1,5 s) non réglable.
- Non résolu : Luraph `fetched_14` (hors bot), familles « trace seule » (Boronide, MoonVeil, wYnFuscate, Synapse Xen, PSU, MoonSec V2) sans moteur à code source réel.

**Banc de 179 échantillons (corpus vyxonq-dev, PER_FAMILY=12, même sélection avant/après)**
| | référence (4 workers) | rework (2 workers) |
|---|---|---|
| moteurs à code source réel | 59 | 71 (+12) |
| sorties produites (ok) | 174 | 175 |
| taille totale des sorties | 4,27 Mo | 3,98 Mo (moins de bruit de trace) |
| pire durée d'un fichier | 90 s | 45 s |
- 14 fichiers changent : 9 LuaObfuscator/VM Compressed → `leakd_luaobfuscator`, 3 → `moonsec_v3` (dont 1 MinifiedLua), 2 timeouts (MoonVeil, Unknown) qui rendent maintenant une trace partielle au lieu de rien.
- Les durées totales (535 s → 255 s) ne sont **pas** comparables : la référence a tourné avec 4 workers (machine saturée), le rework avec 2. À charge égale la vitesse moyenne est inchangée.
- **Régression trouvée par ce banc et corrigée** : un MoonSec V3 avec préambule `hookfunction` fait planter le moteur C# (`HandleAntiTamper`, InvalidCast) ; il était auparavant routé vers la trace et ne donnait donc plus rien.
  Le routeur retombe maintenant sur la **trace** quand un moteur de source reconnu échoue (jamais si le moteur est imposé) ; résultat identique à la référence (667 octets). Test : `tests/test_rework.py`.
- Reste : ce MoonSec V3 « anti-tamper » n'est pas devirtualisé (moteur C# à corriger), donc résultat partiel.
Test : `tests/test_rework.py`.

## Limites connues
- Un panneau ne peut pas recevoir de fichier (limite de Discord) : fichier = `/get`, `/deobf` ou `.get` avec pièce jointe.
- Les messages d'une commande à préfixe ne peuvent pas être « éphémères » : le panneau s'affiche dans le salon (seul son auteur peut s'en servir).
- `.get` remplace une éventuelle commande `.get` de l'ancien bot (voir `DEOBF_KEEP_PREFIX`). Les commandes de votre bot principal qui ne sont pas dans cette suite n'ont pas été vues ni modifiées.
- Moteurs en trace (MoonSec V2/V3, PSU, générique) : résultat toujours **partiel**.
