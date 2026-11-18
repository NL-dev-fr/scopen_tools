import click
import frappe
from frappe.commands import get_site, pass_context


@click.command("scopen-fixtures")
@click.option("--app", required=True, help="App dont on suit les Custom Fields / Property Setters")
@click.option("--init", is_flag=True, help="Enregistre l'état actuel comme référence et génère le patch d'initialisation")
@click.option("--from-fixtures", is_flag=True, help="Avec --init : rattache d'abord au module ce que les fixtures de hooks.py exportent")
@click.option("--module", help="Avec --from-fixtures : module cible si l'app en a plusieurs")
@click.option("--yes", "-y", is_flag=True, help="Ne pas demander de confirmation")
@pass_context
def scopen_fixtures(context, app, init, from_fixtures, module, yes):
	"""Génère un patch à partir des modifications de Custom Fields / Property Setters."""
	from scopen_tools.scopen_fixtures.engine import run

	site = get_site(context)
	frappe.init(site=site)
	frappe.connect()
	try:
		run(app, init=init, yes=yes, from_fixtures=from_fixtures, module=module)
	finally:
		frappe.destroy()


commands = [scopen_fixtures]