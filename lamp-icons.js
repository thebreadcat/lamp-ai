/** Lamp UI icons — Font Awesome Free 6 (self-hosted under /assets/fontawesome/). */
const LAMP_ICONS = {
  home: ["solid", "house"],
  chat: ["regular", "comment"],
  build: ["solid", "wand-magic-sparkles"],
  hammer: ["solid", "hammer"],
  apps: ["solid", "grip"],
  admin: ["solid", "gear"],
  sun: ["solid", "sun"],
  moon: ["solid", "moon"],
  star: ["regular", "star"],
  "star-filled": ["solid", "star"],
  pencil: ["solid", "pen"],
  sparkles: ["solid", "wand-magic-sparkles"],
  check: ["solid", "check"],
  spinner: ["solid", "spinner"],
  "chevron-left": ["solid", "chevron-left"],
  "arrow-up": ["solid", "arrow-up"],
  backspace: ["solid", "delete-left"],
  trash: ["solid", "trash"],
  bell: ["solid", "bell"],
  refresh: ["solid", "arrows-rotate"],
  microphone: ["solid", "microphone"],
  speaker: ["solid", "volume-high"],
  stop: ["solid", "stop"],
  journal: ["solid", "book"],
  timer: ["solid", "clock"],
  workout: ["solid", "dumbbell"],
  meal: ["solid", "utensils"],
  study: ["solid", "book-open"],
  invoice: ["solid", "file-invoice"],
  chores: ["solid", "circle-check"],
  budget: ["solid", "coins"],
  grocery: ["solid", "cart-shopping"],
  pill: ["solid", "pills"],
  users: ["solid", "users"],
  user: ["solid", "user"],
  account: ["solid", "circle-user"],
  "arrow-right": ["solid", "arrow-right"],
};

const TEMPLATE_ICON_ALIASES = {
  "📓": "journal", "⏱️": "timer", "🏋️": "workout", "🍽️": "meal", "📖": "study",
  "🧾": "invoice", "✅": "chores", "💰": "budget", "🛒": "grocery", "💊": "pill", "📱": "apps",
};

function resolveIconName(name) {
  if (!name) return "apps";
  const k = String(name).trim();
  return TEMPLATE_ICON_ALIASES[k] || k;
}

function faStyleClass(style) {
  if (style === "regular") return "fa-regular";
  if (style === "brands") return "fa-brands";
  return "fa-solid";
}

function iconHtml(name, extraClass) {
  const key = resolveIconName(name);
  const spec = LAMP_ICONS[key] || LAMP_ICONS.apps;
  const [style, glyph] = spec;
  const parts = [faStyleClass(style), `fa-${glyph}`];
  if (key === "spinner" || (extraClass && extraClass.includes("ico-loading"))) {
    parts.push("fa-spin");
  }
  const ico = extraClass ? `ico ${extraClass}` : "ico";
  parts.push(ico);
  return `<i class="${parts.join(" ")}" aria-hidden="true"></i>`;
}

function setIconEl(el, name, extraClass) {
  if (el) el.innerHTML = iconHtml(name, extraClass);
}

function iconStepHtml(kind) {
  if (kind === "check") return iconHtml("check", "ico-step ico-step-done");
  return iconHtml("spinner", "ico-step ico-step-spin");
}
