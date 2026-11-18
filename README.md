### Scopen Tools

Outils transverses Scopen pour Frappe / ERPNext (v15, v16).

| Outil | Rôle |
|---|---|
| [Historique des notifications](#historique-des-notifications) | Garde la trace des toasts du Desk pour les relire ou les copier |
| [scopen-fixtures](#scopen-fixtures) | Remplace les fixtures Custom Field / Property Setter par des patches générés automatiquement |

Les réglages se trouvent dans **Scopen Tools Settings** (`/app/scopen-tools-settings`).

---

### Installation

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch develop
bench --site <site> install-app scopen_tools
```

scopen_tools est un **outil de développement** : il est destiné aux environnements de dev.
Les apps client et transverses qui l'utilisent **n'en dépendent pas** en production.

> ⚠️ Une restauration de base (`bench restore`) remplace la liste des apps installées par celle de la production.
> Si scopen_tools n'est pas installé en production, il faut le **réinstaller après chaque restauration**
> (`bench --site <site> install-app scopen_tools`) puis re-choisir le module dans Scopen Tools Settings.
> (TODO)

---

## Historique des notifications

Bouton en bas à droite du Desk qui liste les toasts (`frappe.show_alert`) de la session, pour les relire ou les copier
après leur disparition. Historique par onglet, conservé au rafraîchissement de la page.

Activation : case **Historique des notifications** dans Scopen Tools Settings (rechargement du Desk nécessaire).

---

## scopen-fixtures

### Pourquoi

Les fixtures Frappe (`fixtures` dans `hooks.py` + JSON dans `fixtures/`) sont **réimportées à chaque `bench migrate`**.
Conséquences :

- toute modification faite par le client sur un champ de l'app est **écrasée** au déploiement suivant ;
- une suppression n'est **jamais** propagée (le JSON ne fait que créer / mettre à jour) ;
- le diff git d'un gros JSON est difficile à relire.

`scopen-fixtures` remplace ce mécanisme par des **patches Frappe** (`patches.txt`), générés automatiquement à partir
de ce que tu as modifié dans Customize Form. Un patch ne s'exécute **qu'une seule fois**, et il ne touche jamais
à ce que le client a modifié.

### Principe

```
Customize Form (dev)  ─►  bench scopen-fixtures --app <app>  ─►  patch généré dans l'app  ──►  git commit
                                                                                                    │
                                              production : bench migrate  ◄─────────────────────────┘
                                              (le patch s'exécute une fois, puis plus jamais)
```

1. Le **module** de chaque Custom Field / Property Setter indique à quelle app il appartient.
   En dev, scopen_tools remplit automatiquement ce module à la création (voir [Réglage](#réglage)).
2. La commande compare l'état actuel des personnalisations du module avec un **registre** (`scopen_fixtures.json`)
   et en déduit les ajouts, modifications et suppressions.
3. Elle écrit un **patch autonome** dans l'app, l'ajoute à `patches.txt`, et met à jour le registre.

### Réglage

Dans **Scopen Tools Settings**, section *Développement* :

| Champ | Rôle |
|---|---|
| **Module des personnalisations** | Module attribué automatiquement aux Custom Fields et Property Setters créés à la main |

Ce module doit être celui de **l'app sur laquelle tu travailles**. Si tu passes d'une app client à une app
transverse (ex. erpnext_france), change-le **avant** de créer tes champs.

Le remplissage automatique ne fonctionne que si :

- le site est en `developer_mode` ;
- un module est choisi dans les réglages ;
- le champ est créé à la main (jamais pendant une installation, un migrate, un patch ou un import).

En production (sans `developer_mode`), il ne fait **rien**.

### Utilisation au quotidien

```bash
# 1. Modifier / créer des champs dans Customize Form (en dev)
# 2. Générer le patch
bench --site <site> scopen-fixtures --app <app>
```

La commande affiche ce qu'elle a détecté, puis demande confirmation :

```
  + Custom Field     Item|custom_test_tools_1
  ~ Custom Field     Item|custom_poids_total  (in_list_view)
  - Property Setter  Sales Order|po_no||reqd

Générer le patch ? [y/N]:
```

| Symbole | Signification |
|---|---|
| `+` | Nouveau champ / property setter |
| `~` | Modification (les propriétés changées sont listées entre parenthèses) |
| `-` | Suppression |
| `! module perdu` | L'enregistrement existe encore mais n'est plus dans le module : **pas** une suppression, rien n'est généré |

👉 **Relis toujours cette liste** : un champ qui n'est pas à toi (mauvais module choisi), ou une modification faite
par le client et ramenée par une restauration, s'y verrait immédiatement. En cas de doute, réponds `N`.

Après confirmation, il ne reste qu'à committer l'app.

Options :

| Option | Rôle |
|---|---|
| `--app` | App à traiter (obligatoire) |
| `--init` | Initialisation d'une app (voir plus bas) |
| `--from-fixtures` | Avec `--init` : part de la liste des fixtures de `hooks.py` |
| `--module` | Avec `--from-fixtures` : module cible si l'app en a plusieurs |
| `-y`, `--yes` | Pas de confirmation |

### Ce qui est généré dans l'app

```
<app>/
├── CUSTOMIZATIONS.md                    ← tableau lisible de toutes les personnalisations suivies
└── <app>/
    ├── scopen_fixtures.json             ← registre (état de référence, sert à la détection)
    ├── patches.txt                      ← une ligne ajoutée par patch, section [post_model_sync]
    └── patches/
        └── scopen_fixtures/
            ├── __init__.py              ← fonctions utilisées par les patches (réécrit à chaque passage)
            ├── p_20261118_181923_init.py
            └── p_20261118_182314.py
```

- **Ne modifie aucun de ces fichiers à la main** : ils sont tous générés.
- Ils doivent tous être **committés**.
- Les patches n'importent que `frappe` : l'app **ne dépend pas** de scopen_tools en production.
- Sur le site de dev, le patch est marqué comme déjà exécuté (les champs y existent déjà).

### Ce que fait un patch en production

| Cas | Comportement |
|---|---|
| **Création** | Le champ est créé s'il n'existe pas. S'il existe déjà, rien n'est modifié (seul son module est rempli s'il était vide). |
| **Modification** | Chaque propriété n'est changée **que si sa valeur est encore l'ancienne**. Si le client l'a modifiée, elle est conservée et le migrate affiche `[scopen-fixtures] … modifié par le client, ignoré`. |
| **Suppression** | Les Property Setters sont supprimés avant les Custom Fields. |

Les champs sont créés comme s'ils avaient été faits dans Customize Form (`is_system_generated = 0`) : le client peut
les modifier ensuite.

### Passer une app existante à scopen-fixtures

À faire **une seule fois** par app, sur un site de dev dont les personnalisations reflètent **l'état de la
production** (copie récente de la prod, sans modifications en cours).

> Ordre conseillé : **les apps transverses d'abord** (erpnext_france, erpnext_einvoicing…), **puis les apps client**.
> Les fixtures d'une app client contiennent souvent par erreur des champs d'une app transverse : si l'app transverse
> est déjà passée à l'outil, ces champs ont déjà son module et sont ignorés automatiquement.

#### Cas 1 : les personnalisations ont déjà le module de l'app

C'est le cas si les fixtures de `hooks.py` sont filtrées par module :

```python
fixtures = [
	{"dt": "Custom Field", "filters": [["module", "=", "Mon Module"]]},
	{"dt": "Property Setter", "filters": [["module", "=", "Mon Module"]]},
]
```

```bash
bench --site <site> scopen-fixtures --app <app> --init
```

#### Cas 2 : les personnalisations n'ont pas de module

C'est le cas si les fixtures sont filtrées par nom, par doctype, etc. (`["name", "in", [...]]`).

```bash
bench --site <site> scopen-fixtures --app <app> --init --from-fixtures
# si l'app a plusieurs modules :
bench --site <site> scopen-fixtures --app <app> --init --from-fixtures --module "Mon Module"
```

`--from-fixtures` lit les filtres des fixtures de `hooks.py`, retrouve exactement les enregistrements qu'elles
exportent, et leur attribue le module de l'app sur le site de dev. Les enregistrements qui ont déjà le module
d'une autre app sont ignorés (avec un avertissement). Une fixture **sans filtre** est refusée, car elle couvrirait
tous les champs du site.

#### Ce que fait `--init` (dans les deux cas)

1. **Contrôle des conflits** : signale tout enregistrement du module qui figure aussi dans les fixtures d'une autre
   app installée (il serait géré par deux apps). À corriger avant de continuer, sauf raison connue.
2. Enregistre l'état actuel dans le registre.
3. Génère un **patch d'initialisation** (`p_..._init`) qui, en production :
   - rattache au module les personnalisations qui n'en ont pas (dev et prod deviennent cohérents) ;
   - crée celles qui manqueraient (utile sur un site neuf) ;
   - ne modifie rien d'autre.

#### Puis, retirer les anciennes fixtures

1. Dans `hooks.py`, supprimer les entrées `Custom Field` et `Property Setter` de `fixtures`
   (garder les autres doctypes éventuels).
2. **Supprimer** `fixtures/custom_field.json` et `fixtures/property_setter.json`.

> ⚠️ Retirer les entrées de `hooks.py` ne suffit pas : Frappe importe **tous** les fichiers JSON présents dans
> `fixtures/`, qu'ils soient déclarés dans `hooks.py` ou non.

Retirer les fixtures ne supprime rien en base : la bascule est sans risque.

### Sites neufs

À l'installation d'une app sur un site neuf, Frappe marque tous ses patches comme exécutés **sans les lancer**.
scopen_tools s'en charge via le hook `after_app_install` : il rejoue dans l'ordre les patches `scopen_fixtures`
de l'app installée. Aucune ligne n'est nécessaire dans l'app.

Condition : scopen_tools doit être installé **avant** l'app sur le site neuf.

### Après une restauration de base

- Réinstaller scopen_tools et re-choisir le module (voir [Installation](#installation)).
- Lancer la commande **avant** toute nouvelle modification : elle doit répondre `Aucune modification détectée.`
  Si elle propose des changements que tu n'as pas faits, ce sont des modifications faites en production par le
  client : réponds `N`.

### Dépannage

| Symptôme | Cause / solution |
|---|---|
| Le module n'est pas rempli à la création | Hooks en cache : `bench --site <site> clear-cache` puis relancer `bench start`. Vérifier `developer_mode` et le réglage. |
| Un champ créé dans Customize Form est introuvable par son nom | Depuis la v15, Frappe préfixe les champs créés dans Customize Form par `custom_`. |
| `migrate` bloqué sur `Waiting for table metadata lock` | Une autre connexion utilise la table (site ouvert, workers, scheduler). Arrêter `bench start`, tuer la requête bloquée (`SHOW FULL PROCESSLIST` / `KILL <id>`), relancer le migrate. Ne pas utiliser le site pendant un migrate. |
| `Aucun registre pour cette app` | L'app n'a pas encore été initialisée : lancer `--init`. |

---

### Contributing

This app uses `pre-commit` for code formatting and linting. Please [install pre-commit](https://pre-commit.com/#installation) and enable it for this repository:

```bash
cd apps/scopen_tools
pre-commit install
```

Pre-commit is configured to use the following tools for checking and formatting your code:

- ruff
- eslint
- prettier
- pyupgrade

### License

mit