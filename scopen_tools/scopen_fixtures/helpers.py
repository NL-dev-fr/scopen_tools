"""
Copié par scopen-fixtures dans <app>/patches/scopen_fixtures/__init__.py.
Autonome (n'importe que frappe) : l'app client ne dépend pas de scopen_tools.
NE PAS MODIFIER dans l'app client : ce fichier est réécrit à chaque passage.
"""

import importlib
import os

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_field

SPECS = {
	"custom_fields": ("Custom Field", ("dt", "fieldname")),
	"property_setters": ("Property Setter", ("doc_type", "field_name", "row_name", "property")),
}


def _n(v):
	return None if v in (None, "", 0, "0", 0.0) else str(v)


def _find(doctype, keys, d):
	filters = {k: d.get(k) if d.get(k) else ["is", "not set"] for k in keys}
	return frappe.db.get_value(doctype, filters)


def _warn(msg):
	print(f"[scopen-fixtures] {msg}")


def apply(changes):
	touched = set()
	cf = changes.get("custom_fields", {})
	ps = changes.get("property_setters", {})

	# 1. Création des Custom Fields (jamais d'écrasement)
	for d in cf.get("create", []):
		d = dict(d)
		dt = d.pop("dt")
		name = _find("Custom Field", ("dt", "fieldname"), {"dt": dt, **d})
		if name:
			_attach_module("Custom Field", name, d.get("module"))
			continue
		create_custom_field(dt, d, is_system_generated=False)
		touched.add(dt)

	# 2. Modifications des Custom Fields
	_update("custom_fields", cf.get("update", []), touched)

	# 3. Création des Property Setters (jamais d'écrasement)
	for d in ps.get("create", []):
		name = _find("Property Setter", SPECS["property_setters"][1], d)
		if name:
			_attach_module("Property Setter", name, d.get("module"))
			continue
		frappe.get_doc({"doctype": "Property Setter", **d}).insert(ignore_permissions=True)
		touched.add(d["doc_type"])

	# 4. Modifications des Property Setters
	_update("property_setters", ps.get("update", []), touched)

	# 5. Suppressions : Property Setters d'abord (ils peuvent viser un Custom Field)
	for kind in ("property_setters", "custom_fields"):
		doctype, keys = SPECS[kind]
		for d in changes.get(kind, {}).get("delete", []):
			name = _find(doctype, keys, d)
			if name:
				frappe.delete_doc(doctype, name, ignore_permissions=True, force=True)
				touched.add(d.get("dt") or d.get("doc_type"))

	for dt in touched:
		frappe.clear_cache(doctype=dt)

def _attach_module(doctype, name, module):
	"""Existant : on ne touche à rien, sauf le module s'il est vide (cohérence dev / prod)."""
	if module and not frappe.db.get_value(doctype, name, "module"):
		frappe.db.set_value(doctype, name, "module", module, update_modified=False)
		_warn(f"{doctype} {name} existait déjà : rattaché au module {module}")

def _update(kind, items, touched):
	"""Applique un changement seulement si la valeur est encore l'ancienne (client pas passé par là)."""
	doctype, keys = SPECS[kind]
	for u in items:
		label = ".".join(str(u.get(k)) for k in keys if u.get(k))
		name = _find(doctype, keys, u)
		if not name:
			_warn(f"{doctype} {label} introuvable, modification ignorée")
			continue
		doc = frappe.get_doc(doctype, name)
		changed = False
		for field, (old, new) in u["changes"].items():
			if _n(doc.get(field)) == _n(old):
				doc.set(field, new)
				changed = True
			else:
				_warn(f"{doctype} {label} : '{field}' modifié par le client ({doc.get(field)!r}), ignoré")
		if changed:
			doc.save(ignore_permissions=True)
			touched.add(u.get("dt") or u.get("doc_type"))


def replay():
	"""after_install : sur un site neuf, Frappe ne lance pas les patches -> on les rejoue dans l'ordre."""
	folder = os.path.dirname(__file__)
	for f in sorted(os.listdir(folder)):
		if f.startswith("p_") and f.endswith(".py"):
			importlib.import_module(f"{__name__}.{f[:-3]}").execute()
