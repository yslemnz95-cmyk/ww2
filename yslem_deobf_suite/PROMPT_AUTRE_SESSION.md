# Prompt à coller dans l'autre session (celle qui a accès au bot)

> 2026-11-09 : **Luraph a été retiré** du bot (moteurs, famille `moteur: luraph`, cog renommé `tools_cog`). Un fichier Luraph reçoit « Luraph n'est plus pris en charge ». Ignore les mentions historiques ci-dessous.

> Joindre `yslem_deobf_suite.zip` à ce message, ou le placer à la racine du dépôt du bot.

---

Tu es dans le dépôt de mon bot Discord (discord.py ≥ 2.3, `commands.Bot`). Je te fournis `yslem_deobf_suite.zip` :
un dossier unique avec le code du bot (`/analyse`, `/process`, `/deobf`, `/deobf_engines`, `/deobf_etat`, `/deobf_dernier`, `/deobf_annuler`, `/deobf_moi`) ET tous les
moteurs de déobfuscation. **Il n'y a rien à installer ni à compiler** : Node.js et le Luau patché se préparent
tout seuls. Lis `README_FR.md` du zip. Fais exactement ceci, dans l'ordre, et ne commit / ne pousse rien sans que
je te le demande.

## 0. Faille à corriger avant tout
`@commands.is_owner()` posé sur une commande **slash** n'est PAS appliqué par discord.py (`cmd.checks == []`) :
la commande est ouverte à tout le monde. Fais `grep -rn "is_owner" .` : toute occurrence sur une commande slash est
à remplacer par `@owner_only()` (défini dans `yslem_deobf_suite/cogs/tools_cog.py`).

## 1. Remplacement des anciens fichiers
Les nouveaux cogs remplacent : l'ancien `luraph_tools_cog.py` (renomme `tools_cog.py`, classe `ToolsCog`), `deobf_cog.py`, `devirt_cog.py`, `analyse_cog.py`,
`lua_scanner.py`, `setup_verify_luau.py`, l'ancien dossier d'outil (`v15_tool_attempt_source/`, `/opt/luraph-devirt/...`)
et la variable `LURAPH_TOOL_DIR`. Fais d'abord `grep -rn` pour vérifier que plus rien ne les référence, compare avec
`diff` pour garder mes éventuelles personnalisations, puis supprime. **Garde `deobf/`** (ancien pipeline) jusqu'à ce que
j'aie validé l'étape 4. Si le bot a son propre `lua_sandbox.py`, laisse-le : la suite utilise le sien (`yslem_deobf_suite/lua_sandbox.py`).

## 2. Mise en place
- Dézippe à la racine du bot (au même niveau que le fichier principal) : on obtient `./yslem_deobf_suite/`.
- Dans le démarrage du bot, une seule extension à charger, puis la synchro des commandes :
```python
await bot.load_extension("yslem_deobf_suite.bot_extension")
await bot.tree.sync()
```
- Prérequis du bot : Python ≥ 3.10, `discord.py`, `aiohttp`, `yarl` (normalement déjà présents). Rien d'autre.

## 3. Droits
Par défaut seuls le propriétaire de l'application (et son équipe) peuvent utiliser `/process`, `/deobf`, `/deobf_engines`.
Pour autoriser d'autres comptes : créer `yslem_deobf_suite/allowed_ids.txt` (un ID par ligne) ou définir
`DEOBF_ALLOWED_IDS`. `/deobf_moi` (tout le monde) affiche son ID. Ne pas activer `DEOBF_ALLOW_GUILD_ADMINS=1` sans me demander.

## 3 bis. Piège connu : l'ancien code qui tourne encore
Un symptôme déjà vu : « je n'ai jamais rien reçu ». Avant toute autre vérification, assure-toi que la NOUVELLE version tourne :
l'ancien dossier/cog est bien remplacé, le bot est redémarré, `await bot.tree.sync()` a été exécuté, et la commande `/deobf_etat`
existe dans Discord (elle n'existe que dans cette version). Si le bot est lancé depuis un autre dossier que celui où tu as dézippé,
corrige-le : `yslem_deobf_suite/` doit être importable depuis le dossier de lancement.

## 4. Vérifications (montre-moi les sorties)
1. `python3 yslem_deobf_suite/selftest.py` -> « AUTOTEST OK » (au premier lancement il télécharge Node.js si besoin).
2. `python3 yslem_deobf_suite/tests/test_owner_guard.py` -> « TOUT OK : 6 commande(s) » ;
   `python3 yslem_deobf_suite/tests/test_discord_http.py` et `tests/test_extension_load.py` et `tests/test_detection.py` et `tests/test_luauforge.py` et `tests/test_loader_chain.py` et `tests/test_stack_fidelity.py` et `tests/test_identify.py` -> « TOUT OK ». Le bot a besoin, dans le salon
   d'utilisation, des permissions Voir le salon, Envoyer des messages, Joindre des fichiers.
3. `python3 yslem_deobf_suite/tests/test_bot_e2e.py --full` -> « TOUT OK » (compte 2 à 6 min : déobfusque Spicy3).
4. Redémarre le bot ; aucune erreur de chargement. Avec mon compte : `/deobf_engines` (deobf_py, hercules,
   ironveil, leakd_luaobfuscator en « OK » ; moonsec_v3 / centurion_v6 peuvent être « KO »), puis `/process fichier:`
   avec `yslem_deobf_suite/tests/samples/legaxyobf.lua` : je dois voir, **dans le salon**, un tableau de bord qui se met à jour (étape, barre, compte à rebours) puis un fichier
   dont le contenu est `print("blah blah")`. Aucune réponse « visible de toi seul » ne doit rester.
   **Jobs simultanés** : lance deux `/process` coup sur coup (ou un `.zip` de plusieurs scripts) : les deux démarrent tout de suite
   (pas de file d'attente), une ligne chacun dans le MÊME tableau de bord, un fichier chacun. Avec un compte non autorisé : « Commande réservée au propriétaire… ».
5. `/process` avec `yslem_deobf_suite/examples/spicy3_obfuscated.txt` : réponse INSTANTANÉE « déjà calculé » (résultat vérifié livré
   dans `cache_seed/`). Puis `/deobf fichier:` (le même) `recalculer:True` : vrai calcul, ~1 à 5 min sur ≥ 2 cœurs, je reçois dans le salon un fichier de
   ~1,1 Mo avec 0 marqueur `error("devirt:` (plusieurs tentatives automatiques dans le journal sont NORMALES).
   Si `/deobf_etat` affiche un CPU utilisable < 1 cœur (hébergeur bridé), le bot passe en **mode machine faible** : par défaut mode
   **COMPLET** (toutes les tentatives, jusqu'à ~40 min, arrêt dès qu'un résultat complet est trouvé ; le job peut durer ~1 h) ; `DEOBF_WEAK_MODE=rapide`
   donne un résultat en quelques minutes mais souvent PARTIEL (il le dit). Si le quota CPU annoncé est faux : `DEOBF_FORCE_CPU=2`. Dans ce cas dis-moi la valeur affichée : il faut un hébergeur
   avec ≥ 2 cœurs pour un calcul complet rapide.
6. `/deobf_etat` : colle-moi sa sortie complète (surtout « Prérequis » et « Ecriture dans ce salon »). `/deobf_dernier` doit me renvoyer le dernier
   résultat. Si l'écriture dans le salon échoue, donne au bot les permissions « Envoyer des messages » et « Joindre des fichiers » dans ce salon.
7. `/analyse` avec un fichier quelconque : un embed + un rapport, jamais de jeton de webhook en clair.

## 4 quater. /analyse : identification de l'obfuscateur (nouveau, FINAL16)
`/analyse` nomme l'obfuscateur avec le détecteur de la suite ; si une clé d'API de modèle est fournie, il ajoute un « Avis du modèle »
(extrait de ~4 ko, secrets retirés). La clé se met dans la variable d'environnement `DEOBF_LLM_API_KEY` de l'hébergeur (jamais dans le zip,
jamais dans Git, jamais dans un salon). Sans clé, tout reste local. `/analyse` répond toujours en moins de 120 s.

## 4 bis. Chargeurs et LuauForge (nouveau)
Un script qui n'est qu'un chargeur `loadstring(game:HttpGet("https://…"))()` est maintenant **suivi** (le bot télécharge l'adresse, garde-fous anti-SSRF) ;
un script protégé par **LuauForge** est défait puis sa machine virtuelle est exécutée dans le bac à sable ; **Luarmor** n'est jamais contacté (le bot dit
« protégé »). `DEOBF_FOLLOW_LOADERS=0` désactive le suivi. Le bot a besoin d'un accès sortant HTTPS pour suivre un chargeur.

## 5. Règles
- Ne modifie pas le code des moteurs (`engines/`) ni `bootstrap.py` ; si quelque chose échoue, rapporte l'erreur exacte.
- Ne lis, n'affiche ni ne commite `.env` / jetons ; si tu en vois un en clair, dis-le-moi sans le recopier.
- Le bot exécute des scripts inconnus dans un bac à sable Luau qui n'est PAS une isolation système : signale-moi si
  le bot tourne hors conteneur ou avec des secrets accessibles au processus.
- Ne fais rien d'autre que ce qui est listé ; en cas de doute, demande.

## 6. Compte rendu final
Liste : fichiers supprimés / remplacés / ajoutés, sorties des vérifications de l'étape 4, écarts éventuels
(`is_owner` trouvé ailleurs…), et ce qui reste à faire de mon côté.


Note : WeAreDevs/Prometheus = machine à états (pas du bytecode). Le moteur `wearedevs` relève le Lua (engines/wearedevs/wadlift) ; lire README_FR.md, section « Relevé de la machine à états », avant d'y toucher. Variante non gérée : fonctions de déchiffrement locales à la fonction externe (U[T(...)]).
