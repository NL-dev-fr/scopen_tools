"""
scopen-fixtures : remplace les fixtures Custom Field / Property Setter par des patches.

	bench --site <site> scopen-fixtures --app <app> [--init] [--yes]

- Détecte les ajouts / modifications / suppressions de Custom Fields et Property Setters
  rattachés aux modules de l'app, par rapport au registre `<app>/scopen_fixtures.json`.
- Génère un patch autonome dans `<app>/patches/scopen_fixtures/`, l'ajoute à patches.txt
  et le marque comme déjà exécuté sur le site de dev.
- Tient à jour le registre et `CUSTOMIZATIONS.md` (racine du dépôt de l'app).

Les patches générés n'importent que frappe : l'app client ne dépend pas de scopen_tools.
"""

import json
import os
import pprint
import importlib
from datetime import datetime

import click
import frappe

META_KEYS = {
	"name", "owner", "creation", "modified", "modified_by", "docstatus", "idx",
	"parent", "parentfield", "parenttype", "is_system_generated",
	"_user_tags", "_comments", "_assign", "_liked_by", "doctype",
}

SPECS = {
	"custom_fields": ("Custom Field", ("dt", "fieldname")),
	"property_setters": ("Property Setter", ("doc_type", "field_name", "row_name", "property")),
}

CF_ALWAYS = {"dt", "fieldname", "fieldtype", "label", "insert_after"}
PS_CREATE_KEYS = ("doctype_or_field", "doc_type", "field_name", "row_name",
                  "property", "property_type", "value", "module")

PATCH_TEMPLATE = '''# Généré par scopen-fixtures le {date} ({user}) - ne pas modifier à la main.
from . import apply

CHANGES = {changes}


def execute():
	apply(CHANGES)
'''


# --------------------------------------------------------------------------- #
# Hook before_insert : rattache au module les CF/PS créés à la main (dev)
# --------------------------------------------------------------------------- #

def set_module(doc, method=None):
	"""Inerte hors dev : exige developer_mode ET un module choisi dans Scopen Tools Settings."""
	if not frappe.conf.get("developer_mode"):
		return
	module = frappe.db.get_single_value("Scopen Tools Settings", "customization_module")
	if not module or doc.get("module"):
		return
	if any(frappe.flags.get(f) for f in ("in_install", "in_migrate", "in_patch", "in_import", "in_setup_wizard")):
		return
	doc.module = module


# --------------------------------------------------------------------------- #
# Point d'entrée
# --------------------------------------------------------------------------- #

def replay_app(app):
	"""Hook after_app_install : sur un site neuf, rejoue les patches scopen_fixtures de l'app installée.
	Aucune ligne à ajouter dans l'app client."""
	try:
		module = importlib.import_module(f"{app}.patches.scopen_fixtures")
	except ModuleNotFoundError:
		return
	module.replay()

def run(app, init=False, yes=False, from_fixtures=False, module=None):
	modules = frappe.get_all("Module Def", filters={"app_name": app}, pluck="name")
	if not modules:
		frappe.throw(f"Aucun module trouvé pour l'app '{app}'.")

	if from_fixtures:
		if not init:
			frappe.throw("--from-fixtures s'utilise uniquement avec --init.")
		if not module:
			if len(modules) > 1:
				frappe.throw(f"L'app a plusieurs modules ({', '.join(modules)}) : précise --module.")
			module = modules[0]
		elif module not in modules:
			frappe.throw(f"Le module '{module}' n'appartient pas à l'app '{app}'.")
		_attach_from_fixtures(app, module, modules)

	current = {kind: _collect(doctype, keys, modules) for kind, (doctype, keys) in SPECS.items()}
	if init:
		_check_conflicts(app, current, yes)
	reg_path = frappe.get_app_path(app, "scopen_fixtures.json")
	registry = _load_registry(reg_path)
	now = datetime.now()
	user = frappe.session.user

	if init:
		# Patch d'initialisation : crée ce qui manque (sites neufs) et rattache au module
		# ce qui existe sans module (production) -> dev et prod deviennent cohérents.
		if os.path.exists(reg_path) and not yes:
			click.confirm("Un registre existe déjà. L'écraser ?", abort=True)
		nb = {kind: len(rows) for kind, rows in current.items()}
		click.echo(f"Initialisation : {nb['custom_fields']} Custom Fields, {nb['property_setters']} Property Setters.")
		if not any(nb.values()):
			click.secho("Rien à enregistrer.", fg="yellow")
			return
		changes, _summary, _lost = _diff({}, current)
		patch_name = f"p_{now:%Y%m%d_%H%M%S}_init"
		module_path = _write_patch(app, patch_name, changes, now, user)
		_add_to_patches_txt(app, module_path)
		_mark_executed(module_path)
		registry = {kind: {k: _entry(row, patch_name, now) for k, row in rows.items()} for kind, rows in current.items()}
		_save(app, reg_path, registry)
		click.secho(f"Registre initialisé. Patch d'initialisation : {module_path}", fg="green")
		return

	if not registry:
		click.secho("Aucun registre pour cette app. Sur une app existante, lance d'abord --init "
		            "(sinon tout sera vu comme nouveau).", fg="yellow")
		if not yes:
			click.confirm("Continuer quand même ?", abort=True)

	changes, summary, lost = _diff(registry, current)
	for k in lost:
		click.secho(f"  ! module perdu (existe encore en base, ignoré) : {k}", fg="yellow")
	if lost:
		click.secho("    -> remets le module sur ces enregistrements : ce ne sont PAS des suppressions.", fg="yellow")
	if not summary:
		click.secho("Aucune modification détectée.", fg="green")
		return

	click.echo("\n".join(summary))
	if not yes:
		click.confirm("\nGénérer le patch ?", abort=True)

	patch_name = f"p_{now:%Y%m%d_%H%M%S}"
	module_path = _write_patch(app, patch_name, changes, now, user)
	_add_to_patches_txt(app, module_path)
	_mark_executed(module_path)

	for kind in SPECS:
		old, new = registry.setdefault(kind, {}), current[kind]
		for k in list(old):
			if k not in new and k not in lost:
				del old[k]
		for k, row in new.items():
			if k not in old or old[k]["data"] != _data(row):
				old[k] = _entry(row, patch_name, now)
	_save(app, reg_path, registry)

	click.secho(f"\nPatch généré : {module_path}", fg="green")

# --------------------------------------------------------------------------- #
# Initialisation depuis les fixtures existantes / conflits entre apps
# --------------------------------------------------------------------------- #

FIXTURE_FILES = {"Custom Field": "custom_field.json", "Property Setter": "property_setter.json"}


def _owned_by_fixtures(app):
	"""Enregistrements que les fixtures de hooks.py exportent aujourd'hui pour cette app."""
	owned = {}
	for entry in frappe.get_hooks("fixtures", app_name=app) or []:
		if isinstance(entry, str):
			dt, filters, or_filters = entry, None, None
		else:
			dt = entry.get("dt") or entry.get("doctype")
			filters, or_filters = entry.get("filters"), entry.get("or_filters")
		if dt not in FIXTURE_FILES:
			continue
		if not filters and not or_filters:
			frappe.throw(f"La fixture '{dt}' n'a aucun filtre : elle couvre TOUS les enregistrements du site. "
			             "Ajoute un filtre dans hooks.py avant --from-fixtures.")
		owned.setdefault(dt, set()).update(
			frappe.get_all(dt, filters=filters, or_filters=or_filters, pluck="name"))
	if not owned:
		frappe.throw("Aucune fixture Custom Field / Property Setter trouvée dans hooks.py.")
	return owned


def _attach_from_fixtures(app, module, modules):
	"""Rattache au module de l'app ce que ses fixtures exportent, s'il n'a pas encore de module (dev)."""
	for dt, names in _owned_by_fixtures(app).items():
		attached = 0
		for name in sorted(names):
			current = frappe.db.get_value(dt, name, "module")
			if not current:
				frappe.db.set_value(dt, name, "module", module, update_modified=False)
				attached += 1
			elif current not in modules:
				click.secho(f"  ⚠ {dt} {name} appartient déjà au module '{current}' : ignoré", fg="yellow")
		click.echo(f"{dt} : {len(names)} dans les fixtures, {attached} rattachés au module {module}")
	frappe.db.commit()


def _check_conflicts(app, current, yes):
	"""Signale ce qui est dans le module de l'app ET dans les fixtures d'une autre app installée."""
	found = []
	for kind, (doctype, _keys) in SPECS.items():
		mine = {r["name"] for r in current[kind].values()}
		for other in frappe.get_installed_apps():
			path = frappe.get_app_path(other, "fixtures", FIXTURE_FILES[doctype])
			if other == app or not os.path.exists(path):
				continue
			with open(path, encoding="utf-8") as f:
				both = mine & {d.get("name") for d in json.load(f)}
			found += [(doctype, name, other) for name in sorted(both)]
	for doctype, name, other in found:
		click.secho(f"  ⚠ {doctype} {name} : aussi dans les fixtures de {other}", fg="yellow")
	if found:
		click.secho("    -> ces enregistrements seraient gérés par deux apps. Corrige leur module avant l'init.",
		            fg="yellow")
		if not yes:
			click.confirm("Continuer quand même ?", abort=True)
# --------------------------------------------------------------------------- #
# Collecte / comparaison
# --------------------------------------------------------------------------- #

def _key(row, keys):
	return "|".join(str(row.get(k) or "") for k in keys)


def _collect(doctype, keys, modules):
	rows = frappe.get_all(doctype, filters={"module": ["in", modules]}, fields=["*"])
	return {_key(r, keys): r for r in rows}


def _data(row):
	return {k: v for k, v in row.items() if k not in META_KEYS}


def _entry(row, patch, now):
	return {
		"data": json.loads(json.dumps(_data(row), default=str)),
		"patch": patch,
		"date": f"{now:%Y-%m-%d %H:%M}",
		"by": row.get("modified_by"),
	}


def _n(v):
	return None if v in (None, "", 0, "0", 0.0) else str(v)


def _diff(registry, current):
	changes, summary, lost = {}, [], []
	cf_defaults = {df.fieldname: df.default for df in frappe.get_meta("Custom Field").fields}

	for kind, (doctype, keys) in SPECS.items():
		old = {k: e["data"] for k, e in registry.get(kind, {}).items()}
		new = {k: json.loads(json.dumps(_data(r), default=str)) for k, r in current[kind].items()}
		create, update, delete = [], [], []

		for k in sorted(new.keys() - old.keys()):
			d = new[k]
			if kind == "custom_fields":
				d = {f: v for f, v in d.items() if f in CF_ALWAYS or _n(v) != _n(cf_defaults.get(f))}
			else:
				d = {f: d[f] for f in PS_CREATE_KEYS if d.get(f) not in (None, "")}
			create.append(d)
			summary.append(f"  + {doctype:<16} {k}")

		for k in sorted(new.keys() & old.keys()):
			diff = {f: [old[k].get(f), new[k].get(f)]
			        for f in sorted(set(old[k]) | set(new[k]))
			        if _n(old[k].get(f)) != _n(new[k].get(f))}
			if diff:
				update.append({**{f: new[k].get(f) for f in keys}, "changes": diff})
				summary.append(f"  ~ {doctype:<16} {k}  ({', '.join(diff)})")

		for k in sorted(old.keys() - new.keys()):
			key_fields = {f: old[k].get(f) for f in keys}
			if _exists(doctype, keys, key_fields):
				# Toujours en base mais plus dans le module (ex. après restauration prod) : pas une suppression
				lost.append(k)
				continue
			delete.append(key_fields)
			summary.append(f"  - {doctype:<16} {k}")

		if create or update or delete:
			changes[kind] = {"create": create, "update": update, "delete": delete}

		return changes, summary, lost

def _exists(doctype, keys, d):
	filters = {k: d.get(k) if d.get(k) else ["is", "not set"] for k in keys}
	return frappe.db.get_value(doctype, filters)

# --------------------------------------------------------------------------- #
# Écriture des fichiers
# --------------------------------------------------------------------------- #

def _write_patch(app, patch_name, changes, now, user):
	patches_dir = frappe.get_app_path(app, "patches")
	sf_dir = os.path.join(patches_dir, "scopen_fixtures")
	os.makedirs(sf_dir, exist_ok=True)

	init_patches = os.path.join(patches_dir, "__init__.py")
	if not os.path.exists(init_patches):
		open(init_patches, "w").close()

	# Helpers autonomes, réécrits à chaque passage pour rester à jour
	helpers_src = os.path.join(os.path.dirname(__file__), "helpers.py")
	with open(helpers_src, encoding="utf-8") as src, \
	     open(os.path.join(sf_dir, "__init__.py"), "w", encoding="utf-8") as dst:
		dst.write(src.read())

	with open(os.path.join(sf_dir, f"{patch_name}.py"), "w", encoding="utf-8") as f:
		f.write(PATCH_TEMPLATE.format(
			date=f"{now:%Y-%m-%d %H:%M}", user=user,
			changes=pprint.pformat(changes, sort_dicts=False, width=110),
		))
	return f"{app}.patches.scopen_fixtures.{patch_name}"


def _add_to_patches_txt(app, module_path):
	path = frappe.get_app_path(app, "patches.txt")
	content = open(path, encoding="utf-8").read() if os.path.exists(path) else ""
	if content and not content.endswith("\n"):
		content += "\n"
	if "[pre_model_sync]" in content and "[post_model_sync]" not in content:
		content += "\n[post_model_sync]\n"
	content += f"{module_path}\n"
	with open(path, "w", encoding="utf-8") as f:
		f.write(content)


def _mark_executed(module_path):
	if not frappe.db.exists("Patch Log", {"patch": module_path}):
		frappe.get_doc({"doctype": "Patch Log", "patch": module_path}).insert(ignore_permissions=True)
		frappe.db.commit()


def _load_registry(path):
	if not os.path.exists(path):
		return {}
	with open(path, encoding="utf-8") as f:
		return json.load(f)


def _save(app, reg_path, registry):
	with open(reg_path, "w", encoding="utf-8") as f:
		json.dump(registry, f, indent="\t", ensure_ascii=False, sort_keys=True, default=str)
		f.write("\n")
	_write_markdown(app, registry)


def _write_markdown(app, registry):
	cf = sorted(registry.get("custom_fields", {}).values(), key=lambda e: (e["data"].get("dt"), e["data"].get("fieldname")))
	ps = sorted(registry.get("property_setters", {}).values(),
	            key=lambda e: (e["data"].get("doc_type"), e["data"].get("field_name") or "", e["data"].get("property")))

	def esc(v):
		return str(v if v not in (None, "") else "").replace("|", "\\|").replace("\n", " ")

	lines = [
		f"# Personnalisations de `{app}`",
		"",
		"_Fichier généré par `bench scopen-fixtures` - ne pas modifier à la main._",
		"",
		f"## Custom Fields ({len(cf)})",
		"",
		"| Doctype | Champ | Libellé | Type | Options | Patch | Date | Par |",
		"|---|---|---|---|---|---|---|---|",
	]
	for e in cf:
		d = e["data"]
		lines.append(f"| {esc(d.get('dt'))} | `{esc(d.get('fieldname'))}` | {esc(d.get('label'))} | "
		             f"{esc(d.get('fieldtype'))} | {esc(d.get('options'))} | {e['patch']} | {e['date']} | {esc(e.get('by'))} |")
	lines += [
		"",
		f"## Property Setters ({len(ps)})",
		"",
		"| Doctype | Champ | Propriété | Valeur | Patch | Date | Par |",
		"|---|---|---|---|---|---|---|",
	]
	for e in ps:
		d = e["data"]
		value = esc(d.get("value"))
		if len(value) > 60:
			value = value[:57] + "…"
		lines.append(f"| {esc(d.get('doc_type'))} | {esc(d.get('field_name') or '(doctype)')} | "
		             f"{esc(d.get('property'))} | {value} | {e['patch']} | {e['date']} | {esc(e.get('by'))} |")

	path = os.path.normpath(os.path.join(frappe.get_app_path(app), "..", "CUSTOMIZATIONS.md"))
	with open(path, "w", encoding="utf-8") as f:
		f.write("\n".join(lines) + "\n")