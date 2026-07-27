# OSINT_scrapper

Une application de bureau qui explore un site web que vous désignez — par domaine ou par URL de page —,
en extrait les informations OSINT que ce site publie, et les exporte, entièrement sourcées, dans le format
de votre choix.

Version 0.2.0. Écrite en Python avec Qt (PySide6). Windows, Linux et macOS.

*This document is the French translation of [`README.md`](README.md), which remains the reference version.*

> **Vous venez de la 0.1.0 ?** Ce n'est plus le même produit. La v0.1.0 recherchait une *personne* nommée
> auprès de quatre sources vérifiées, en ligne de commande. La v0.2.0 explore un *site* depuis une interface
> graphique. Il n'y a plus de sous-commande `investigate`, `sources` ou `erase`, ni de `--given-name`. Voir
> [`docs/MIGRATION.md`](docs/MIGRATION.md).

## Ce que fait cet outil

Vous lui donnez une cible — `example.com`, ou `https://example.com/about` — et une finalité. Il va alors :

1. lire le `robots.txt` du site et refuser de démarrer si la cible elle-même y est interdite ;
2. explorer le site en largeur d'abord depuis ce point d'entrée, sans jamais sortir de l'hôte que vous avez
   nommé, une requête polie à la fois, jusqu'à épuisement des pages ou du budget que vous avez fixé ;
3. extraire de chaque page les informations de contact et d'identité publiées ;
4. tout dédoublonner en une liste de découvertes, chacune portant toutes les URL où elle a été vue et
   l'instant exact de sa collecte ;
5. écrire le résultat en JSON, CSV, Excel, JSONL et Markdown.

```
cible → périmètre → crawl (frontière · robots · débit) → extraction → validation → agrégation → export
```

**Neuf choses sont extraites**, et rien d'autre :

| Champ | Ce que c'est |
|---|---|
| `email` | Adresses e-mail publiées, marquées `role` lorsqu'il s'agit d'une boîte partagée (`contact@`, `info@`, `dpo@`, …) |
| `phone` | Numéros de téléphone, validés et stockés en E.164 |
| `postal_address` | Adresses postales, **uniquement** depuis un balisage structuré — jamais devinées dans de la prose |
| `person_name` | Les noms que le site publie, tels qu'il les publie ; une fonction éventuelle voyage en métadonnée |
| `organization_name` | À qui appartient ce site |
| `social_profile` | URL complètes de profils sur des plateformes connues. Enregistrées, **jamais visitées** |
| `pgp_key_url` | L'endroit où le site publie une clé publique. La clé elle-même n'est pas récupérée |
| `company_identifier` | SIREN, SIRET, TVA intracommunautaire, RCS — clé de contrôle vérifiée |
| `technology` | La balise meta `generator` et deux en-têtes de réponse. C'est tout |

**Ce que ce n'est pas :**

- **Pas un moteur de recherche de personnes.** Il n'y a aucun nom à saisir. Vous le pointez vers un site.
- **Pas un robot d'indexation.** Il ne quitte jamais l'hôte que vous avez nommé. Les liens sortants ne sont
  retenus que s'il s'agit de profils sociaux, et même dans ce cas ils ne sont jamais requêtés.
- **Pas un outil d'empreinte technologique.** Trois sources, aucune base de signatures, aucune analyse
  JavaScript.
- **Pas un scanner de vulnérabilités.** Il émet des `GET` et rien d'autre, et ne sonde jamais un chemin qui
  ne soit pas lié, listé dans un sitemap, ou l'un des deux fichiers *well-known*.
- **Pas un outil en ligne de commande.** Le script console ouvre la fenêtre.

## Utilisation légale

**Usages prévus.** Auditer un site que vous détenez ou exploitez. Due diligence fournisseur ou
précontractuelle. Journalisme. Recherche académique ou statistique. Évaluations de sécurité autorisées,
menées dans un périmètre écrit.

**Pas pour.** Le harcèlement, la traque ou le *doxxing*. Le profilage de personnes qui n'ont pas consenti et
pour lesquelles vous n'avez aucune autre base légale. La constitution de fichiers de prospection ou de
recrutement. Toute collecte que vous ne pourriez pas justifier.

**Les obligations sont les vôtres, pas celles de l'outil.** Au sens du RGPD, c'est vous le responsable de
traitement. Aucun outil ne peut établir votre base légale, vous maintenir dans la finalité que vous avez
déclarée, décider de ce qui est proportionné à collecter, ni répondre aux demandes d'accès et d'effacement
qu'une personne concernée peut vous adresser. Cet outil vous aide à tenir des traces ; il ne vous rend pas
conforme.

**Ce que l'outil impose mécaniquement :**

- Une **finalité est obligatoire** avant qu'un crawl puisse démarrer, et aucune requête HTTP — pas même
  `robots.txt` — n'est émise avant qu'elle ne soit validée.
- **`robots.txt` est évalué pour chaque URL, et de nouveau à chaque saut de redirection**, en mode
  *fail-closed*. Aucun réglage, aucune entrée de menu et aucune variable d'environnement ne le désactive.
- Un **plancher de débit de 0,5 seconde** que rien ne peut abaisser, et le `Crawl-delay` de l'hôte l'emporte
  toujours lorsqu'il est plus long.
- Un **crawl borné** : au plus 2000 pages et au plus 10 niveaux de profondeur, quoi que vous saisissiez dans
  les champs.
- Une **concurrence bornée** : au plus 4 requêtes en vol, 2 par défaut.
- Un **confinement de périmètre** : le crawl ne peut pas quitter l'hôte que vous avez nommé, et une
  redirection qui tenterait de le faire est refusée plutôt que suivie.
- Un **`User-Agent` honnête**. L'usurpation de navigateur est refusée à l'endroit même où la chaîne est
  construite ; il n'existe aucun moyen de la contourner.
- Une **provenance par découverte** : chaque valeur exportée porte son URL source, son horodatage UTC de
  collecte et la couche d'extraction qui l'a produite.
- Des **seuils d'abandon** : des `429` répétés, une série d'échecs ou un taux d'erreur élevé arrêtent le
  crawl plutôt que d'insister contre un hôte manifestement en difficulté.
- L'**effacement en un clic** de n'importe quelle exécution, depuis l'écran *Runs*.

**Ce qu'il ne peut pas imposer — lisez ce passage.**

*La licéité de la finalité que vous déclarez.* Choisir `due_diligence` dans une liste demande un clic, et
taper seize caractères dans une case n'en demandait pas davantage. Ni cet outil ni aucun autre ne peut
vérifier votre base légale. Ce qu'il peut faire, c'est rendre l'affirmation inévitable, explicite et
enregistrée définitivement dans chaque export — et c'est ce qu'il fait.

*Le fait que les conditions d'utilisation du site autorisent le crawl.* **`robots.txt` est un signal lisible
par une machine, pas un contrat.** Un site peut autoriser un chemin dans son `robots.txt` et interdire la
collecte automatisée dans ses conditions d'utilisation : les deux documents s'ignorent l'un l'autre. La
v0.1.0 embarquait une liste fermée de quatre sources dont les conditions avaient été lues et datées ; la
v0.2.0 explore ce que vous tapez, il n'y a donc plus rien à pré-valider. **Lire les conditions d'utilisation
de la cible est votre travail, et l'outil ne prétend pas le contraire.**

## Installation

Nécessite **Python 3.11 ou plus récent**. Développé et testé sur 3.12 sous Windows 11.

```bash
git clone https://github.com/TonioCodeur/OSINT_Scrapper
cd OSINT_Scrapper

# Avec uv (recommandé : uv.lock est versionné, donc l'installation est reproductible)
uv sync --extra dev

# Ou avec pip
python -m venv .venv
.venv/Scripts/activate      # Windows
source .venv/bin/activate   # Linux et macOS
pip install -e ".[dev]"
```

Puis lancez-le :

```bash
osint-scrapper
```

`python -m osint_scrapper` fait exactement la même chose. Les deux ouvrent la fenêtre. Le script console
accepte exactement trois arguments et aucun autre :

| Argument | Signification |
|---|---|
| `--config CHEMIN` | Charge ce fichier de configuration au lieu de parcourir les emplacements par défaut |
| `--log-level {debug,info,warning,error}` | Verbosité des journaux. Ils vont sur `stderr`, jamais dans l'interface |
| `--version` | Affiche la version et quitte |

Il n'existe pas de mode d'exécution sans interface. Si vous en voulez un, ouvrez une *issue* plutôt que de
chercher une option qui n'existe pas.

**Dépendances d'exécution directes.** Les versions exactes résolues vivent dans le `uv.lock` versionné ; les
licences et l'arbre complet des dépendances sont dans
[`THIRD_PARTY_LICENSES.md`](THIRD_PARTY_LICENSES.md).

| Paquet | Pourquoi |
|---|---|
| `PySide6` | Le binding Qt. Choisi devant PyQt6 parce que PySide6 propose une option LGPLv3 et pas PyQt6 — voir [Licences tierces](#licences-tierces) |
| `requests` | Client HTTP. Fournit ses propres annotations de type, donc aucun paquet de stubs n'est installé |
| `beautifulsoup4` | Analyse HTML sur le backend `html.parser` de la bibliothèque standard : aucune dépendance compilée, résultats identiques sur toutes les plateformes |
| `phonenumbers` | Analyse et validation des numéros. Une expression régulière sur ce champ exporterait des faux positifs comme des faits |
| `email-validator` | Validation d'e-mail, vérifications DNS de délivrabilité désactivées |
| `openpyxl` | Écriture XLSX. Aucune alternative dans la bibliothèque standard |

Outils de développement : `pytest`, `pytest-qt`, `ruff`, `mypy`.

## Configuration

Copiez `osint-scrapper.toml.example` vers `osint-scrapper.toml`, ou utilisez le panneau **Settings**, qui
écrit le même fichier.

```toml
[http]
contact_email = "vous@example.org"
project_url = "https://github.com/TonioCodeur/OSINT_Scrapper"
request_interval_seconds = 1.0
timeout_seconds = 10.0
max_retries = 3
concurrent_requests = 2

[crawl]
max_pages = 200
max_depth = 3
include_subdomains = true
follow_sitemap = true
phone_region = "FR"

[purpose]
category = "due_diligence"
note = ""

[output]
directory = "runs"
retention_days = 30
formats = ["json", "csv", "xlsx"]
```

**Une adresse e-mail de contact est obligatoire.** Sans elle, le bouton **Start crawl** reste désactivé et
le panneau *Settings* explique pourquoi. Elle est insérée dans le `User-Agent` de chaque requête, afin qu'un
administrateur voyant votre trafic dans ses journaux puisse joindre un humain. C'est tout l'intérêt de
s'identifier honnêtement.

**Ordre de recherche :** `--config <chemin>`, puis `./osint-scrapper.toml`, puis
`$XDG_CONFIG_HOME/osint-scrapper/config.toml` (avec repli sur `~/.config/...`).

**Variables d'environnement :** `OSINT_SCRAPPER_CONTACT_EMAIL`, `OSINT_SCRAPPER_PROJECT_URL`,
`OSINT_SCRAPPER_OUTPUT_DIR`.

**Priorité :** ce que vous réglez dans l'interface > variable d'environnement > fichier de configuration >
valeur par défaut interne.

**Les valeurs hors bornes sont ramenées dans les bornes, et le fait est signalé.** Un fichier de
configuration demandant `max_pages = 99999` devient 2000 et le panneau *Settings* vous dit que c'est
arrivé. Les bornes ne sont pas des suggestions et le fichier ne peut pas faire passer une valeur plus grande
derrière le dos de l'interface.

La taille de la fenêtre, la position des séparateurs et la largeur des colonnes sont stockées séparément par
Qt, par machine. Tout ce qui influe sur un crawl ou un export vit dans le fichier TOML et nulle part
ailleurs.

## Utilisation

La fenêtre comporte trois panneaux — **Crawl**, **Runs** et **Settings** — plus une barre de menus (*File*,
*Run*, *Help*) et une barre d'état. Changer de panneau n'interrompt jamais un crawl en cours.

### Démarrer un crawl

Dans le panneau **Crawl** :

| Contrôle | Défaut | Remarques |
|---|---|---|
| **Target** | — | `example.com` ou `https://example.com/about`. Un domaine nu devient `https://…` ; l'outil ne retombe jamais silencieusement sur `http://`, donc saisissez l'URL `http://` complète si vous en avez besoin. Une ligne d'indication affiche l'URL résolue et l'hôte de périmètre qui en a été déduit |
| **Purpose** | votre dernier choix | Obligatoire. Six valeurs ; voir plus bas |
| **Purpose note** | votre dernière saisie | Facultative — **obligatoire, et d'au moins 16 caractères, quand *Purpose* vaut `other`** |
| **Max pages** | 200 | 1 – 2000 |
| **Max depth** | 3 | 0 – 10. La page cible est à la profondeur 0 |
| **Request interval (s)** | 1.0 | 0,5 – 60,0. Le minimum *est* le plancher matériel ; le contrôle ne peut pas descendre en dessous |
| **Concurrent requests** | 2 | 1 – 4 |
| **Include subdomains** | activé | Voir [Le périmètre du crawl](#le-périmètre-du-crawl) |
| **Follow sitemap** | activé | |
| **Phone region** | `FR` | ISO 3166-1 alpha-2. La région selon laquelle les numéros sont analysés |

Les quatre contrôles de limite sont regroupés dans un cadre **Crawl limits** déplié par défaut. Ce sont des
contrôles de conformité, pas des options avancées, et les masquer reviendrait à mentir sur ce que
l'application s'apprête à faire en votre nom.

**Start crawl** reste désactivé tant que la cible et la finalité ne sont pas toutes deux valides ; son
info-bulle indique laquelle manque.

### La finalité

Choisissez-en une :

| Valeur | Signification |
|---|---|
| `security_assessment` | Évaluation de sécurité autorisée, avec un périmètre écrit |
| `due_diligence` | Due diligence fournisseur, sous-traitant ou précontractuelle |
| `journalism` | Recherche journalistique |
| `self_audit` | Audit d'un site que vous détenez ou exploitez |
| `academic_research` | Recherche académique ou statistique |
| `other` | Autre chose — une note d'au moins 16 caractères est exigée |

La catégorie et la note sont toutes deux écrites dans chaque export et dans le registre d'exécutions. La
finalité reste visible à côté du bouton *Start* et n'est jamais reléguée derrière une boîte de dialogue que
l'on ferme une fois puis que l'on oublie.

*Pourquoi une liste et pas un champ libre ?* La v0.1.0 exigeait 16 caractères de texte libre avant chaque
exécution. Dans un outil graphique, c'est une friction que l'on rencontre plusieurs fois par heure, et une
friction de ce genre ne produit pas de réponses réfléchies : elle produit `aaaaaaaaaaaaaaaa`, ce qui est
pire que rien, puisqu'elle fabrique la preuve d'une délibération qui n'a jamais eu lieu. Un vocabulaire
contrôlé court conserve les deux choses qui comptaient (vous devez énoncer une base ; elle est enregistrée
définitivement) et produit des traces réellement comparables d'une exécution à l'autre. La règle des 16
caractères survit exactement là où elle a une utilité : sur `other`.

### Pendant l'exécution

**Start** devient **Stop**. Il n'y a délibérément pas de *Pause* : un crawl en pause maintient des
connexions ouvertes sans rien faire, ce qui est moins poli que d'arrêter puis de recommencer.

Quatre choses sont vivantes :

- **La progression** — une barre rapportée à votre budget de pages, plus l'étiquette qui fait foi :
  `fetched N/BUDGET · queued Q · depth D · skipped S · errors E · elapsed mm:ss`. La barre est une borne
  supérieure, pas une estimation : un crawl qui épuise les pages disponibles se termine plus tôt, et c'est
  un dénouement normal et souhaitable.
- **Les découvertes** — un tableau triable, `Field · Value · Extraction · Pages · First seen`, qui se
  remplit au fil du crawl. Les lignes se mettent à jour sur place quand le nombre de pages d'une valeur
  augmente. `Ctrl+C` copie la sélection.
- **Le journal des pages** — `# · Depth · Status · URL · Detail`, filtrable par statut. Les codes de statut
  sont exactement les valeurs machine qui apparaissent dans les exports : ce que vous lisez à l'écran est
  ce que vous pourrez rechercher plus tard.
- **Un bandeau de conformité** non masquable, indiquant le `User-Agent` utilisé, le fait que `robots.txt`
  est respecté, l'intervalle effectif et son plancher, ainsi que le périmètre du crawl. Il est à l'écran
  pendant tout le temps où du trafic sort.

**Stop** est coopératif : les requêtes en vol se terminent ou expirent, rien n'est tué en pleine écriture,
et le résultat partiel est un rapport réel que vous pouvez exporter. Il est enregistré comme
`stopped_by_operator`.

### Les erreurs

Trois niveaux, délibérément :

- **Une page a échoué** → une ligne dans le journal des pages avec son code de statut. Pas de boîte de
  dialogue, pas de son. L'échec partiel est normal en scraping ; le traiter comme un événement vous
  apprendrait seulement à cliquer *OK* par réflexe.
- **L'exécution ne peut pas continuer** → un bandeau en ligne en haut du panneau, avec le code de raison,
  l'URL et une phrase en clair. Utilisé pour un refus `robots.txt` sur la cible, une cible injoignable, une
  configuration invalide, et chaque seuil d'abandon. Il ne recouvre jamais le journal — c'est précisément le
  moment où vous avez le plus besoin de le lire.
- **Un bug** → une fenêtre modale avec le type d'exception et un bouton **Copy details**. C'est la seule
  modale du produit que vous n'avez pas demandée, et elle existe pour que les défauts soient bruyants. Ce
  qui avait été collecté reste exportable.

### Exporter

**Run → Export…**, ou le bouton de la bande de fin d'exécution, ou **Re-export…** depuis le panneau *Runs*.

Cochez les formats voulus. **JSON est toujours écrit et ne peut pas être décoché** : c'est
l'enregistrement canonique, tout le reste en dérive. Choisissez une destination si vous voulez une copie
ailleurs ; le dossier de l'exécution garde toujours la sienne.

Ré-exporter une exécution terminée émet **zéro** requête HTTP. Décider que vous vouliez aussi de l'Excel ne
signifie pas réexplorer le site.

### Gérer ce que vous avez collecté

Le panneau **Runs** liste chaque exécution : date, hôte cible, finalité, pages, découvertes, taille, et
jours de rétention restants. Les exécutions ayant dépassé leur rétention sont mises en évidence.

- **Open folder** — le dossier de l'exécution dans votre gestionnaire de fichiers.
- **Re-export…** — d'autres formats, aucune nouvelle requête.
- **Delete** — supprime le dossier de l'exécution et sa ligne de registre, après une confirmation qui nomme
  les dossiers exacts et le nombre de découvertes qui seront détruites.
- **Delete expired** — la même chose, pour tout ce qui a dépassé la rétention.

Rien n'est jamais supprimé automatiquement. L'outil enregistre une durée de rétention et vous montre quand
elle est échue ; la décision reste la vôtre.

## Fonctionnement

### Le périmètre du crawl

L'**hôte de périmètre** est l'hôte de votre cible débarrassé d'un éventuel `www.` initial. Une URL est dans
le périmètre lorsque son hôte est cet hôte, que son port correspond, et que :

- **Include subdomains activé** (le défaut) — l'hôte de périmètre, ou tout ce qui se termine par `.` +
  l'hôte de périmètre. Ainsi `example.com` atteint `blog.example.com`.
- **Include subdomains désactivé** — l'hôte de périmètre ou son jumeau en `www.`, et rien d'autre.

Trois conséquences à connaître avant de le pointer vers quelque chose :

- **Le périmètre descend, il ne remonte jamais.** Ciblez `docs.example.com` et vous n'atteindrez pas
  `example.com`. Si vous voulez tout le domaine, saisissez le domaine.
- **Aucune *public suffix list* n'est consultée.** Le confinement est défini par l'hôte que vous avez
  réellement saisi, ce qui est plus étroit que « le même domaine enregistrable » et donc toujours sûr :
  `foo.co.uk` ne peut jamais atteindre `bar.co.uk`, et aucune liste n'a besoin d'être téléchargée pour que
  ce soit vrai.
- **Les liens externes ne sont jamais récupérés.** Un `href` externe est proposé à l'extracteur de profils
  sociaux ; s'il s'agit d'un profil sur une plateforme connue il devient une découverte, sinon il est
  abandonné. Vous n'obtiendrez pas un déversoir de tous les liens sortants du site, et l'outil n'ira pas
  discrètement se promener sur les serveurs d'un tiers.

Une redirection qui tente de sortir du périmètre est enregistrée en `off_scope_redirect` et **n'est pas
suivie**. C'est la règle qui empêche une redirection mal configurée de transformer le crawl d'un site en
crawl d'Internet.

### Le crawl

**En largeur d'abord**, pour que les pages peu profondes viennent en premier — c'est là que vivent les
informations de contact et les mentions légales. Une modification : les URL dont le chemin ressemble à une
page à forte valeur (`contact`, `mentions-legales`, `legal`, `impressum`, `about`, `a-propos`, `team`,
`equipe`, `privacy`, `security`, `presse`, et leurs voisines) passent en tête de file à leur propre
profondeur. Cela n'ajoute jamais une requête — cela ne fait que réordonner une file qui contenait déjà
l'URL —, si bien qu'un crawl qui épuise son budget revient tout de même avec les pages qui comptent.

**Chaque URL est canonisée** avant de pouvoir entrer dans la file, pour qu'une même page ne soit jamais
récupérée deux fois : schéma et hôte en minuscules, hôte en punycode, ports par défaut retirés, `.` et `..`
résolus, barres obliques dupliquées réduites, **fragments toujours supprimés**, paramètres de suivi et de
session (`utm_*`, `gclid`, `fbclid`, `phpsessid`, …) retirés, et paramètres de requête restants triés, de
sorte que `?a=1&b=2` et `?b=2&a=1` soient une seule URL et non deux.

Deux non-normalisations délibérées : **la casse du chemin est préservée** (les chemins sont sensibles à la
casse sur la plupart des serveurs) et **la barre oblique finale est significative** (`/a` et `/a/` sont deux
URL différentes). En pratique les serveurs redirigent l'une vers l'autre et le doublon s'effondre de
lui-même, puisque c'est l'URL *finale* après redirections qui entre dans l'ensemble des visitées : l'outil
n'a pas besoin de deviner.

Un **garde anti-piège à robots** rejette les URL de plus de 20 segments de chemin, celles dont un segment se
répète plus de quatre fois, celles ayant plus de 10 paramètres de requête, ou dépassant 2048 caractères — ce
sont les formes que produisent les calendriers infinis et les pages de recherche à facettes.

**La découverte** au-delà des liens de page, effectuée une fois au démarrage :

- les lignes `Sitemap:` du `robots.txt`, qui est récupéré de toute façon ;
- `/sitemap.xml`, si le `robots.txt` n'en a déclaré aucun et que *Follow sitemap* est activé. Au plus 5
  documents sitemap, au plus 500 URL chacun, les fichiers d'index suivis sur un seul niveau, les documents
  de plus de 10 Mio abandonnés ;
- `/.well-known/security.txt` (RFC 9116). Un `Contact:` en `mailto:` devient un e-mail, un `Contact:` en
  `tel:` devient un téléphone, `Encryption:` devient une URL de clé PGP. Ces URL sont des contacts, pas des
  cibles de crawl, et ne sont pas mises en file.

**Ce qui est récupéré.** HTML et XHTML, plus du texte brut pour `security.txt` et du XML pour les sitemaps.
Les URL se terminant par une extension binaire ou d'*asset* connue (`.pdf`, `.jpg`, `.zip`, `.css`, `.js`,
`.woff2`, et une quarantaine d'autres) ne sont **jamais requêtées du tout** — mais elles apparaissent
malgré tout dans le journal en `skipped_extension`, pour que vous puissiez constater l'existence de
`/rapport-annuel.pdf` sans que l'outil l'ait téléchargé. Toute autre réponse dont le `Content-Type` se
révèle non analysable voit son corps rejeté sans être lu. Les réponses de plus de 5 Mio sont abandonnées.

Le sort de chaque page est l'un de dix-sept codes de statut, et tous apparaissent dans le journal comme dans
les exports : `ok`, `no_findings`, `skipped_robots`, `skipped_extension`, `skipped_content_type`,
`skipped_off_scope`, `skipped_budget`, `skipped_depth`, `url_rejected_shape`, `credentials_in_url`,
`off_scope_redirect`, `too_many_redirects`, `too_large`, `rate_limited`, `http_error`, `transport_error`,
`parse_error`.

**L'échec partiel est normal.** L'échec d'une page ne dégrade que cette page. Le crawl continue et le
journal dit exactement ce qui s'est passé, plutôt que de renvoyer discrètement moins de résultats.

### Les couches d'extraction

Cinq couches passent sur chaque page. Chaque découverte enregistre la meilleure couche qui l'a produite.

| Couche | Ce qu'elle lit | Confiance |
|---|---|---|
| `well_known` | Les champs de `/.well-known/security.txt` (RFC 9116) | 0.95 |
| `structured_data` | JSON-LD et microdonnées schema.org : `Organization`, `Person`, `PostalAddress`, `ContactPoint`, `sameAs` | 0.90 |
| `semantic_html` | Liens `mailto:` / `tel:`, `<address>`, microformats et classes vCard historiques, `<meta name="author">`, `<meta name="generator">`, `<link rel="author">`, `<link rel="me">`, `<link rel="pgpkey">`, et deux en-têtes de réponse | 0.75 |
| `text_heuristic` | Motifs d'e-mail, correspondances `phonenumbers` et identifiants d'entreprise dans le texte visible | 0.50 |
| `text_heuristic_deobfuscated` | Les adresses que le site a publiées sous la forme `nom [at] domaine [dot] com`, `(at)`, ` AT `, `＠`, `﹫` | 0.40 |

Le texte visible, c'est le document après suppression de `<script>`, `<style>`, `<noscript>`, `<template>`
et des commentaires. La déobfuscation lit du texte que le site a choisi d'afficher ; elle déjoue les
moissonneurs d'adresses naïfs, pas un contrôle d'accès. Seuls les séparateurs listés sont réécrits, et
seulement lorsque le résultat passe ensuite la validation d'e-mail — elle ne devine jamais un domaine.

### Une seule règle sur le texte libre

> **Une valeur ne peut être extraite de la prose que si quelque chose d'indépendant peut confirmer qu'elle
> est bien formée.**

Trois champs remplissent cette condition : **`email`** (il doit s'analyser comme une adresse réelle),
**`phone`** (libphonenumber doit le déclarer valide) et **`company_identifier`** (SIREN et SIRET doivent
passer leur clé de contrôle, les numéros de TVA le format de leur pays). Un candidat qui échoue est écarté,
et non exporté avec un score plus bas.

Les six autres — adresses postales, noms de personnes, noms d'organisation, profils sociaux, URL de clés PGP
et technologies — proviennent **uniquement** des trois couches supérieures, jamais de la prose.

Ce n'est pas de la prudence pour la prudence. Un crawl de 200 pages de texte contient des centaines de
paires de mots capitalisés et des dizaines de motifs « numéro + rue ». Sans invariant vérifiable, un
extracteur de couche texte sur ces champs ne trouve pas des faits : il en fabrique, en volume, et attache un
indice de confiance à chacun. C'est la pire chose que ce produit pourrait faire, donc il ne la fait pas.

### Lire `extraction_confidence` et `page_support`

Chaque découverte porte **deux nombres, et ils ne sont pas combinés** :

- **`extraction_confidence`** — l'une des valeurs `0.95`, `0.90`, `0.75`, `0.50`, `0.40`. Elle répond à
  *comment cette valeur a-t-elle été obtenue*, et à rien d'autre. C'est une étiquette, pas une probabilité,
  et aucune arithmétique n'est jamais faite dessus. Une valeur trouvée en JSON-LD vaut 0,90 qu'elle
  apparaisse sur une page ou sur quatre cents, parce que l'extraction était aussi solide dans les deux cas.
- **`page_support`** — un nombre entier : sur combien de pages distinctes de ce site la valeur est apparue.
  Il reste un entier précisément pour que personne ne le prenne pour une probabilité.

**Un support élevé signifie « présent sur tout le site »** — un pied de page, un bloc de contact — et
identifie l'*organisation*. **Un support de 1 signifie « local à une page »** — une personne précise, un
service précis. Aucun n'est meilleur que l'autre ; ils répondent à des questions différentes.

**Le support n'est pas une corroboration.** La v0.1.0 relevait un score quand plusieurs *sources
indépendantes* concordaient, ce qui est une chose signifiante pour des sources indépendantes. Ici il y a une
seule source. Un numéro de téléphone présent sur quarante pages d'un même site n'est pas quarante
confirmations : c'est **un seul éditeur qui parle une fois, fort**. L'outil rapporte à quel point c'est
fort et vous laisse l'inférence, plutôt que de blanchir de la répétition en un nombre qui aurait l'air d'une
certitude.

Il n'existe aucun score mélangé nulle part dans aucun export, et pas de marqueur `identity_unconfirmed` :
puisqu'aucun nom n'est mis en correspondance, il n'y a aucun risque d'homonymie contre lequel vous prévenir.

Les valeurs sont dédoublonnées sur une clé normalisée, si bien que le même e-mail vu sur quarante pages est
une découverte avec un support de quarante pages — jamais quarante lignes. La provenance est plafonnée à 10
entrées par découverte pour que les rapports restent lisibles, tandis que les compteurs de pages et
d'occurrences donnent toujours les totaux réels.

## Comportement de conformité

### robots.txt

Récupéré avec le `User-Agent` et le délai d'expiration propres à l'outil, mis en cache par
`(schéma, hôte, port)` pendant au plus 24 heures, apparié sur le jeton produit `OSINT-Scrapper`.

**Il est évalué pour chaque URL, et pas une fois par hôte** — des règles au niveau du chemin rendent une
décision au niveau de l'hôte dénuée de sens. Et il est évalué **de nouveau à chaque saut de redirection**,
avant que le saut ne soit suivi, faute de quoi un `302` d'un chemin autorisé vers un chemin interdit serait
un moyen de contourner la vérification. Cinq sauts maximum.

| Résultat de la récupération de `/robots.txt` | Décision |
|---|---|
| 2xx, corps analysable | Suivre les règles analysées |
| 3xx, jusqu'à 5 sauts, puis 2xx | Suivre les règles du corps final |
| 401 ou 403 | **Refus** — l'hôte nous éconduit |
| **404**, et autres 4xx | **Autorisation** |
| 5xx | **Refus** |
| Expiration, DNS, TLS, connexion réinitialisée | **Refus** |
| Corps de plus de 512 Kio | **Refus** |
| Corps non décodable, ou non analysable | **Refus** |
| Plus de 5 redirections, ou une boucle | **Refus** |

**La divergence sur le 404, énoncée ouvertement.** Un 404 est traité comme une *autorisation*. C'est une
réponse définitive de l'hôte — « il n'y a pas de robots.txt » — et non une ambiguïté ; c'est ce que prescrit
la RFC 9309 §2.3.1.3 ; et c'est ce qu'implémente le `RobotFileParser` de Python lui-même. Le traiter comme
un refus rendrait l'outil incapable de lire la page de mentions légales de la plupart des petits sites. Tout
ce qui est réellement *ambigu* — injoignable, malformé, surdimensionné, éconduit — refuse.

**Si `robots.txt` interdit votre cible elle-même, l'exécution ne démarre pas.** Pas de dossier d'exécution,
pas d'entrée de registre, pas de requêtes. Il n'existe aucun contrôle de contournement nulle part dans le
produit, et en ajouter un serait un défaut.

### Limitation de débit

L'intervalle minimal entre deux *départs* de requête vers l'hôte vaut
`max(votre réglage, le Crawl-delay de l'hôte, 0,5 s)`. C'est un plancher. Rien ne l'abaisse — ni le fichier
de configuration, ni l'interface, ni une variable d'environnement.

**La concurrence, et pourquoi le chiffre est 2.** Parce que le limiteur cadence les *départs* de requête,
faire tourner davantage de travailleurs **ne peut pas** augmenter la charge sur l'hôte : à un intervalle
d'une seconde, l'outil émet une requête par seconde quel que soit le nombre de travailleurs. La concurrence
ne fait que masquer la latence. Face à un site répondant en 2 secondes, un seul travailleur gaspille la
moitié du budget autorisé à attendre ; deux travailleurs utilisent l'intervalle que vous avez réellement
configuré. Deux suffisent à saturer n'importe quel intervalle face à n'importe quel temps de réponse
inférieur au double de cet intervalle, ce qui couvre à peu près tous les sites réels. Davantage de
travailleurs n'achètent rien d'autre que des connexions ouvertes, d'où un maximum de 4. Mettez-le à 1 si
vous voulez la forme de trafic la plus simple possible.

### Reculer, et savoir s'arrêter

**429** — `Retry-After` est respecté jusqu'à 120 secondes ; en son absence, le recul est de 2 s, 4 s, 8 s
avec gigue. **Trois `429` consécutifs abandonnent le crawl**, et un `Retry-After` supérieur à 120 secondes
l'abandonne immédiatement. Un 429 répété, c'est l'hôte qui vous dit d'arrêter ; insister est la façon dont
les intégrations se font bannir.

**5xx** — jusqu'à 3 nouvelles tentatives avec recul exponentiel et gigue, plafonné à 30 secondes. Ensuite la
page est enregistrée en `http_error` et le crawl continue. Les autres 4xx sont enregistrés et jamais
retentés.

Quatre seuils abandonnent un crawl, et chacun produit malgré tout un rapport complet et exportable de tout
ce qui a été collecté jusque-là :

| Déclencheur | Dénouement |
|---|---|
| 3 `429` consécutifs, ou un `Retry-After` de plus de 120 s | `aborted_rate_limited` |
| 10 échecs consécutifs, de quelque nature que ce soit | `aborted_host_unhealthy` |
| Plus de 50 % d'échecs après au moins 20 récupérations | `aborted_error_rate` |
| Vous avez appuyé sur *Stop* | `stopped_by_operator` |

### User-Agent

```
OSINT-Scrapper/0.2.0 (+https://github.com/TonioCodeur/OSINT_Scrapper; contact: vous@example.org)
```

Il n'existe aucun contrôle, clé de configuration, variable d'environnement ou argument de ligne de commande
qui définisse un `User-Agent` arbitraire. L'unique fonction qui le construit refuse toute chaîne contenant
`Mozilla`, `AppleWebKit`, `Chrome`, `Chromium`, `Safari`, `Firefox`, `Gecko` ou `Edg`, sans distinction de
casse. Cet outil s'identifie ; il ne déjoue pas la détection de robots.

L'outil émet **des `GET` et rien d'autre**, jamais.

## Formats de sortie

Tout ce qu'une exécution écrit vit sous `<dossier-de-sortie>/<run_id>/`, soit `./runs/<run_id>/` par défaut.
Les horodatages sont en RFC 3339 UTC avec un suffixe `Z`.

**L'ordre est déterministe** et calculé à partir de clés de tri, jamais à partir de l'ordre dans lequel les
pages sont revenues : les découvertes par champ, puis confiance, puis support, puis valeur ; les pages par
profondeur puis URL. Deux exécutions sur le même site produisent la même disposition de fichiers, et un
crawl à 2 travailleurs produit le même ordre qu'un crawl à 1.

### `report.json` — canonique

Un sur-ensemble de tous les autres formats. UTF-8, `indent=2`, clés dans un ordre fixe plutôt que triées,
saut de ligne final. Aucune clé hors de ce schéma n'est jamais écrite.

```json
{
  "schema_version": "2.0",
  "run":        { "run_id": "…", "started_at": "…", "finished_at": "…",
                  "outcome": "completed", "outcome_detail": null,
                  "purpose_category": "due_diligence", "purpose_note": "",
                  "retention_days": 30,
                  "tool": { "name": "…", "version": "…", "user_agent": "…" } },
  "target":     { "entered_value": "example.com", "target_url": "https://example.com/",
                  "scope_host": "example.com", "include_subdomains": true },
  "settings":   { "max_pages": 200, "max_depth": 3, "request_interval_seconds": 1.0,
                  "concurrent_requests": 2, "follow_sitemap": true, "phone_region": "FR" },
  "statistics": { "pages_fetched": 147, "requests_made": 152, "pages_skipped": 38,
                  "pages_failed": 5, "findings_count": 63 },
  "findings":   [ { "field": "email", "value": "…",
                    "extraction_confidence": 0.9, "page_support": 41,
                    "occurrence_count": 78, "first_seen_url": "…",
                    "metadata": { "email_kind": "role" },
                    "provenance": [ { "source_url": "…", "collected_at": "…",
                                      "extraction_layer": "…", "raw_value": "…" } ] } ],
  "pages":      [ { "url": "…", "depth": 0, "status": "ok", "detail": null,
                    "http_status": 200, "content_type": "text/html",
                    "findings_count": 6 } ]
}
```

### `report.csv` et `report_pages.csv`

Une ligne **par entrée de provenance**, de sorte que chaque ligne soit attribuable indépendamment. Écrits en
`utf-8-sig` (c'est la BOM qui permet à Excel de lire correctement les valeurs accentuées), avec des fins de
ligne CRLF et un guillemetage minimal.

`report.csv` :

```
run_id, purpose_category, purpose_note, retention_days,
target_entered, target_url, scope_host,
field, value, email_kind, extraction_confidence, page_support, occurrence_count, first_seen_url,
source_url, extraction_layer, raw_value, collected_at,
tool_name, tool_version
```

`report_pages.csv` :

```
run_id, url, depth, status, detail, http_status, content_type, findings_count
```

`email_kind` est vide pour tous les champs sauf `email`. Les autres métadonnées propres à un champ
(`number_type`, `platform`, `scheme`, `role`) sont dans les exports JSON et JSONL ; leur donner à chacune
une colonne produirait une feuille large et presque vide.

### `report.xlsx`

Quatre feuilles, dans cet ordre :

1. **`Run`** — clé/valeur : identifiants, horaires, dénouement, finalité, outil, cible, réglages,
   statistiques.
2. **`Findings`** — en-tête identique, cellule pour cellule, à `report.csv`.
3. **`Pages`** — en-tête identique à `report_pages.csv`.
4. **`Compliance`** — le `User-Agent`, le fait que `robots.txt` a été respecté, l'URL du robots, l'intervalle
   effectif et son plancher, la concurrence, le nombre de pages écartées par robots, la rétention et la
   finalité. Cette feuille existe pour que la posture de conformité d'une exécution soit un artefact de
   premier plan, qu'un auditeur peut lire sans analyser du JSON.

Les en-têtes sont en gras ; les confiances sont des flottants et les compteurs des entiers.

### `report.jsonl`

Un objet JSON par ligne, UTF-8, fins de ligne LF, sans BOM. Chaque ligne est une découverte × une entrée de
provenance, avec les mêmes champs qu'une ligne CSV, plus l'objet `metadata` complet — `email_kind` n'est pas
répété au premier niveau, car `metadata` le porte déjà. Les nombres restent des
nombres, les valeurs contenant des sauts de ligne n'ont besoin d'aucun guillemetage, et le fichier se lit en
flux et s'ajoute en fin — c'est pourquoi il existe à côté du CSV plutôt qu'à sa place.

### `report.md`

Le livrable humain : un tableau de synthèse, les découvertes groupées par champ, le journal des pages et une
section de conformité. Dans les valeurs, `|`, les accents graves et les barres obliques inverses sont
échappés, `<` et `>` sont convertis en entités, `[` et `]` sont échappés afin qu'aucune valeur collectée ne
puisse s'afficher comme un lien, et les sauts de ligne sont aplatis. **Aucun HTML brut n'est jamais émis**,
de sorte qu'un moteur de rendu Markdown ne puisse pas être amené à exécuter quoi que ce soit qu'un site
exploré aurait publié.

### Garde contre l'injection de formule

Toute cellule CSV ou XLSX dont le premier caractère est `=`, `+`, `-`, `@`, une tabulation ou un retour
chariot est écrite avec une apostrophe en tête. Ces fichiers acheminent du texte récupéré sur des centaines
de pages tierces directement dans un tableur : c'est donc obligatoire et non optionnel. Cela ne s'applique
ni au JSONL ni au Markdown, qui ne sont pas des tableurs et où altérer une valeur corromprait le format.

## Vie privée et rétention

**Ce qui est stocké.** Uniquement les neuf champs, leurs valeurs normalisées, et la provenance de chaque
découverte : URL source, horodatage UTC, couche d'extraction, et la courte chaîne brute qui a produit la
valeur (plafonnée à 200 caractères). Plus le journal des pages, les réglages de l'exécution et la finalité
que vous avez déclarée.

**Ce qui n'est jamais stocké.** Le HTML des pages. Les corps de réponse. Le texte libre des pages. Rien de
tout cela ne touche le disque, à aucun moment, sous aucun format. Un test le garantit.

**Où cela vit.** `./runs/<run_id>/` par défaut, plus un registre en ajout seul dans `runs/index.jsonl`, avec
une ligne par exécution : hôte cible, finalité, compteurs, rétention. `runs/` est ignoré par git et doit le
rester : il contient des données personnelles collectées.

Le registre enregistre l'hôte cible en clair. La v0.1.0 hachait sa clé de sujet, parce que l'index de *qui a
fait l'objet d'une enquête* est lui-même une donnée personnelle. Ici la cible est un nom d'hôte, le rapport
posé dans le dossier voisin le contient en entier, et le panneau *Runs* doit pouvoir vous montrer ce que
vous avez exploré sans ouvrir chaque fichier du disque — le hacher n'apporterait donc rien et coûterait la
fonctionnalité. Là où un nom d'hôte *est* une donnée personnelle, le remède est celui que le RGPD demande
réellement : supprimer l'exécution, ce qui est à un clic dans ce même panneau.

**La rétention est déclarée, pas appliquée.** Chaque export enregistre la durée de rétention que vous avez
configurée (30 jours par défaut). L'outil ne supprime jamais rien de lui-même. Le panneau *Runs* montre ce
qui est échu et vous propose **Delete expired** ; c'est vous qui décidez.

**Effacement.** Supprimer une exécution retire son dossier et réécrit le registre sans ses lignes. Si
quelqu'un vous adresse une demande d'effacement, c'est le mécanisme — et comme chaque découverte porte son
URL source et son horodatage, vous pouvez aussi lui dire exactement ce que vous détenez et d'où cela vient.

## Développement

```bash
uv sync --extra dev

pytest                  # la suite complète
ruff check .            # lint
ruff check . --fix      # le sous-ensemble corrigible automatiquement
mypy src                # vérification de types en mode strict
```

Les tests d'interface sans affichage nécessitent le greffon de plateforme *offscreen* de Qt :

```bash
# Windows (PowerShell)
$env:QT_QPA_PLATFORM = "offscreen"; pytest

# Linux et macOS
QT_QPA_PLATFORM=offscreen pytest
```

**La suite de tests n'émet aucun appel réseau.** Une fixture *autouse* remplace `socket.socket` et
`socket.create_connection` par des fonctions qui lèvent, de sorte qu'une requête accidentelle échoue
bruyamment au lieu de réussir en silence.

**Politique de fixtures.** Les analyseurs et le crawl entier sont testés contre des fixtures versionnées —
principalement `tests/fixtures/site/`, un petit site web inventé qui exerce une autorisation et un refus
robots, une chaîne de redirections, une redirection hors périmètre, un sitemap, un `security.txt`, un piège
à robots et un e-mail obfusqué. **Aucune fixture ne peut contenir les données d'une personne réelle.**
Uniquement des valeurs inventées sur `example.com` / `example.org`.

**L'architecture est garantie par des tests, pas par convention.**
`tests/test_architecture_boundaries.py` analyse chaque module avec `ast` et échoue si `domain/` importe quoi
que ce soit hors de la bibliothèque standard, si `application/` importe quoi que ce soit hors de la
bibliothèque standard et des couches internes, ou si **`PySide6` apparaît ailleurs que dans
`src/osint_scrapper/interfaces/`**. Cette dernière règle est ce qui garde tout le produit testable sans
jamais construire de `QApplication`, et c'est pourquoi le crawl peut être piloté de bout en bout dans un
test, sans aucune fenêtre à l'écran.

**Le fil d'exécution de l'interface ne fait jamais d'entrées-sorties.** Requêtes réseau, analyse et export
tournent tous sur un fil de travail et rendent compte par des signaux. L'annulation est coopérative — un
jeton vérifié entre deux récupérations — et `QThread.terminate()` est interdit, parce qu'il peut laisser un
fichier à moitié écrit et romprait la promesse selon laquelle *Stop* produit toujours un rapport
exportable.

`tests/test_end_to_end.py` fait tourner toute la chaîne sur le site de fixtures versionné — vraie boucle de
crawl, vraie canonisation, vraie politique robots, vrais extracteurs, vrais rédacteurs de fichiers — en ne
simulant que le récupérateur de pages, l'horloge et le temporisateur, et vérifie les six fichiers émis.
C'est le seul test qui attrape une dérive entre ce qu'un extracteur produit et ce que l'agrégateur attend.
**Ne remplacez pas ses collaborateurs par des doublures.**

## Limitations

- **Les analyseurs cassent quand les sites changent leur balisage.** C'est inhérent au scraping. Cet outil
  échoue bruyamment quand cela arrive — en nommant le sélecteur et l'URL, et en enregistrant `parse_error`
  pour cette page — au lieu de renvoyer un résultat vide d'apparence plausible.
- **Le contenu rendu en JavaScript est invisible.** Il n'y a pas de moteur de navigateur ici. Un site qui
  construit sa page de contact côté client paraîtra vide, et l'outil ne peut pas vous dire que c'est ce qui
  s'est passé. C'est un arbitrage délibéré : un navigateur sans interface multiplierait la charge imposée à
  la cible et la surface d'attaque de cette application.
- **Les noms et adresses postales en texte libre ne sont pas extraits, délibérément.** Voir
  [Une seule règle sur le texte libre](#une-seule-règle-sur-le-texte-libre). Manquer un nom est rattrapable ;
  exporter une adresse fausse comme un fait ne l'est pas.
- **`extraction_confidence` est une étiquette, pas une probabilité.** Une valeur à 0,90 n'est pas « correcte
  à 90 % ». Cela signifie qu'un balisage schema.org l'a publiée.
- **`page_support` n'est pas une corroboration.** Un site qui se répète, c'est un seul éditeur qui parle une
  fois, fort.
- **`robots.txt` n'est pas les conditions d'utilisation.** Lire les conditions de la cible est votre
  travail.
- **L'outil ne voit que ce qu'un site choisit de publier.** Il ne contourne aucune authentification, aucun
  paywall et aucune détection de robots. Un résultat vide signifie « rien de public n'a été trouvé ici », et
  non « cette organisation n'a aucune présence en ligne ».
- **Un crawl est un instantané.** Rien n'est re-récupéré au sein d'une exécution, il n'y a pas de reprise
  après interruption, et pas de comparaison entre deux exécutions sur le même site.
- **Un site par exécution.** Explorer plusieurs cibles signifie plusieurs exécutions.
- **Hors périmètre pour cette version :** le crawl authentifié, la rotation de proxys ou l'évasion de
  détection de robots, la gestion des CAPTCHA, les exécutions planifiées ou en arrière-plan, une base de
  données, un serveur ou une interface web, une base de signatures technologiques, l'analyse de clés
  OpenPGP, et les exports ODS, HTML ou PDF.

## Licences tierces

Le détail complet, et les obligations qui accompagnent une redistribution, sont dans
[`THIRD_PARTY_LICENSES.md`](THIRD_PARTY_LICENSES.md). En résumé :

**Le code source de cette application est sous licence MIT.** Elle utilise **Qt** via **PySide6**, sous la
**GNU Lesser General Public License version 3**. PySide6 a été choisi devant PyQt6 pour exactement cette
raison : PySide6 propose une option LGPLv3, et Riverbank Computing déclare que *« Unlike Qt, PyQt is not
available under the LGPL »* — lier une application MIT à PyQt6 sous GPLv3 relicencierait l'œuvre
distribuée.

Si vous vous contentez d'utiliser cet outil, vous n'avez rien à faire. **Si vous le redistribuez**, la
LGPLv3 vous demande de garder Qt lié dynamiquement et remplaçable, de transmettre le texte de la licence, et
d'indiquer à vos utilisateurs que Qt est utilisé — le tout détaillé concrètement dans ce fichier. Figer
l'application en un binaire d'un seul fichier est une modification qui touche à la licence, et ce n'est pas
une chose à faire à la légère.
