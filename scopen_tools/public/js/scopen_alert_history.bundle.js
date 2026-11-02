const STORAGE_KEY = "scopen_tools:alert_history";
const MAX_ENTRIES = 100;

const BELL_ICON = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
	stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
	<path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg>`;

let entries = load();
let unread = 0;
let $root, $panel, $list, $badge;

function is_enabled() {
	const settings = (frappe.boot && frappe.boot.scopen_tools) || {};
	return !!settings.alert_history;
}

// ---------- Stockage ----------

function load() {
	try {
		return JSON.parse(sessionStorage.getItem(STORAGE_KEY)) || [];
	} catch (e) {
		return [];
	}
}

function save() {
	try {
		sessionStorage.setItem(STORAGE_KEY, JSON.stringify(entries));
	} catch (e) {
		// quota plein ou stockage indisponible : on garde au moins la mémoire
	}
}

// ---------- Capture ----------

function capture(message) {
	const m = typeof message === "string" ? { message } : message || {};
	entries.push({
		ts: Date.now(),
		indicator: m.indicator || "blue",
		message: strip_actions(to_html(m.message)),
		subtitle: strip_actions(to_html(m.subtitle)),
		body: strip_actions(to_html(m.body)),
		route: frappe.get_route_str ? frappe.get_route_str() : "",
	});
	if (entries.length > MAX_ENTRIES) entries = entries.slice(-MAX_ENTRIES);
	save();

	if (is_open()) {
		render();
	} else {
		unread++;
		update_badge();
	}
}

if (is_enabled()) {
	const original_show_alert = frappe.show_alert;
	frappe.show_alert = function (message, ...args) {
		try {
			capture(message);
		} catch (e) {
			console.error("[scopen_tools] alert_history", e);
		}
		return original_show_alert.apply(this, [message, ...args]);
	};
	frappe.toast = frappe.show_alert;
}

// ---------- Utilitaires ----------

function esc(value) {
	return frappe.utils.escape_html(value || "");
}

function to_plain_text(html) {
	const div = document.createElement("div");
	div.innerHTML = html || "";
	return (div.textContent || "").trim();
}

function to_html(value) {
	if (value == null || value === false) return "";
	if (typeof value === "string" || typeof value === "number") return String(value);
	if (value.jquery) {
		return value
			.toArray()
			.map((el) => el.outerHTML || el.textContent || "")
			.join("");
	}
	if (value instanceof Node) return value.outerHTML || value.textContent || "";
	if (Array.isArray(value)) return value.map(to_html).join("<br>");
	if (typeof value === "object" && "message" in value) return to_html(value.message);

	console.debug("[scopen_tools] alert_history: valeur non gérée", value);
	return "";
}

const ACTION_SELECTOR = "button, .btn, input, select, textarea, [data-action]";

function strip_actions(html) {
	if (!html) return "";
	const div = document.createElement("div");
	div.innerHTML = html;
	div.querySelectorAll(ACTION_SELECTOR).forEach((el) => el.remove());

	// s'il ne reste que des séparateurs (ex. "New | Print | Email"), on vide
	const text = (div.textContent || "").replace(/[\s|·•\-]/g, "");
	if (!text && !div.querySelector("a, img")) return "";

	return div.innerHTML.trim();
}

function copy_text(text) {
	if (navigator.clipboard && window.isSecureContext) {
		return navigator.clipboard.writeText(text);
	}
	// fallback HTTP (environnements de dev)
	const ta = document.createElement("textarea");
	ta.value = text;
	ta.style.position = "fixed";
	ta.style.opacity = "0";
	document.body.appendChild(ta);
	ta.select();
	document.execCommand("copy");
	ta.remove();
	return Promise.resolve();
}

// ---------- Interface ----------

function is_open() {
	return !!$panel && !$panel.hasClass("hidden");
}

function open_panel() {
	$panel.removeClass("hidden");
	unread = 0;
	update_badge();
	render();
}

function close_panel() {
	$panel.addClass("hidden");
}

function update_badge() {
	if (!$badge) return;
	$badge.text(unread > 99 ? "99+" : unread).toggleClass("hidden", unread === 0);
}

function render() {
	if (!$list) return;

	if (!entries.length) {
		$list.html(`<div class="sct-ah-empty">${__("No new notifications")}</div>`);
		return;
	}

	const html = [];
	for (let i = entries.length - 1; i >= 0; i--) {
		const e = entries[i];
		html.push(`
			<div class="sct-ah-item" data-indicator="${esc(e.indicator)}">
				<div class="sct-ah-meta">
					<span class="sct-ah-time">${new Date(e.ts).toLocaleTimeString()}</span>
					<span class="sct-ah-route" title="${esc(e.route)}">${esc(e.route)}</span>
					<button class="btn btn-xs btn-link sct-ah-copy" data-index="${i}">${__("Copy")}</button>
				</div>
				<div class="sct-ah-message">${e.message}</div>
				${e.subtitle ? `<div class="sct-ah-subtitle">${e.subtitle}</div>` : ""}
				${e.body ? `<div class="sct-ah-body">${e.body}</div>` : ""}
			</div>`);
	}
	$list.html(html.join(""));
}

function build_ui() {
	if (document.querySelector(".sct-alert-history")) return;

	$root = $(`
		<div class="sct-alert-history">
			<div class="sct-ah-panel hidden">
				<div class="sct-ah-header">
					<span class="sct-ah-title">${__("Notifications")}</span>
					<button class="btn btn-xs btn-default sct-ah-clear">${__("Clear")}</button>
					<button class="btn btn-xs btn-default sct-ah-close" title="${__("Close")}">&times;</button>
				</div>
				<div class="sct-ah-list"></div>
			</div>
			<button class="btn btn-default sct-ah-toggle" title="${__("Notifications")}">
				${BELL_ICON}
				<span class="sct-ah-badge hidden"></span>
			</button>
		</div>`).appendTo(document.body);

	$panel = $root.find(".sct-ah-panel");
	$list = $root.find(".sct-ah-list");
	$badge = $root.find(".sct-ah-badge");

	$root.on("click", ".sct-ah-toggle", () => (is_open() ? close_panel() : open_panel()));
	$root.on("click", ".sct-ah-close", close_panel);
	$root.on("click", ".sct-ah-clear", () => {
		entries = [];
		save();
		render();
	});
	$root.on("click", ".sct-ah-copy", (ev) => {
		const btn = ev.currentTarget;
		const e = entries[btn.dataset.index];
		if (!e) return;
		const text = [e.message, e.subtitle, e.body].map(to_plain_text).filter(Boolean).join("\n");
		copy_text(text).then(() => {
			btn.textContent = "✓";
			setTimeout(() => (btn.textContent = __("Copy")), 1000);
		});
	});
	$(document).on("keydown", (ev) => {
		if (ev.key === "Escape" && is_open()) close_panel();
	});

	update_badge();
}

if (is_enabled()) $(build_ui);