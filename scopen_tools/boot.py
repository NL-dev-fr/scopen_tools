import frappe
from frappe.utils import cint


def boot_session(bootinfo):
	if frappe.session.user == "Guest":
		return

	try:
		settings = frappe.get_cached_doc("Scopen Tools Settings")
	except Exception:
		# doctype absent (migrate pas encore passé) : tout désactivé
		bootinfo.scopen_tools = {}
		return

	bootinfo.scopen_tools = {
		"alert_history": cint(settings.enable_alert_history),
	}