# Copyright (c) 2026, Scopen and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class ScopenToolsSettings(Document):
	def on_update(self):
		# le boot est mis en cache par utilisateur : on le vide pour que
		# le changement soit pris en compte au prochain chargement du Desk
		frappe.clear_cache()
