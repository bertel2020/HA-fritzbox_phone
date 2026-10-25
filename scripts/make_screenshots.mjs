// Renders the dashboard card with sample data in a real browser and writes
// the README screenshots. Run from tests/card (needs jsdom's sibling
// dependency @mdi/js; Playwright with Chromium comes from the environment):
//   node ../../scripts/make_screenshots.mjs
import { mkdirSync, readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..");
const require = createRequire(join(root, "tests/card/package.json"));
const mdi = require("@mdi/js");
const { chromium } = require("playwright");

const CARD = readFileSync(join(root, "custom_components/fritzbox_phone/www/fritzbox-phone-card.js"), "utf-8");

const THEMES = {
  light: {
    "--primary-color": "#03a9f4",
    "--primary-text-color": "#212121",
    "--secondary-text-color": "#727272",
    "--card-background-color": "#ffffff",
    "--secondary-background-color": "#e5e5e5",
    "--divider-color": "rgba(0,0,0,0.12)",
    "--error-color": "#db4437",
    "--warning-color": "#ffa600",
    "--success-color": "#43a047",
    "--info-color": "#039be5",
    "--text-primary-color": "#ffffff",
    page: "#f4f4f4",
  },
  dark: {
    "--primary-color": "#03a9f4",
    "--primary-text-color": "#e1e1e1",
    "--secondary-text-color": "#9b9b9b",
    "--card-background-color": "#1c1c1c",
    "--secondary-background-color": "#282828",
    "--divider-color": "rgba(225,225,225,0.12)",
    "--error-color": "#ef5350",
    "--warning-color": "#ffb74d",
    "--success-color": "#66bb6a",
    "--info-color": "#29b6f6",
    "--text-primary-color": "#ffffff",
    page: "#111111",
  },
};

const pad = (n) => String(n).padStart(2, "0");
const avmDate = (minutesAgo) => {
  const d = new Date(Date.now() - minutesAgo * 60000);
  return `${pad(d.getDate())}.${pad(d.getMonth() + 1)}.${String(d.getFullYear()).slice(2)} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
};

const calls = [
  { id: "1", type: "missed", name: "Dr. Weber (Praxis)", caller_number: "03012345678", called_number: "0301111", device: "Telefon", date: avmDate(20), duration: "0:00", area_name: "Berlin" },
  { id: "2", type: "incoming", name: "Anna Schmidt", caller_number: "01711234567", called_number: "0301111", device: "Wohnzimmer", date: avmDate(95), duration: "0:12", vip: true, area_name: "Mobilfunk" },
  { id: "3", type: "missed", name: null, caller_number: "069987654", called_number: "0301111", device: "Telefon", date: avmDate(140), duration: "0:00", is_spam: true, spam_confidence: 92, reverse_name: "Gewinnspiel-Zentrale", area_name: "Frankfurt am Main" },
  { id: "4", type: "outgoing", name: "Pizzeria Roma", caller_number: "0301111", called_number: "03055512345", device: "Küche", date: avmDate(210), duration: "0:03", area_name: "Berlin" },
  { id: "5", type: "incoming", name: null, caller_number: "08912345", called_number: "0301111", device: "Anrufbeantworter", date: avmDate(300), duration: "0:01", is_answering_machine: true, area_name: "München", tam_index: 0, tam_message_index: 1 },
  { id: "6", type: "incoming", name: "Paketdienst", caller_number: "040555000", called_number: "0301111", device: "Flur", date: avmDate(1500), duration: "0:02", area_name: "Hamburg" },
];

const messages = [
  { index: 1, number: "08912345", name: null, date: avmDate(300), duration: "0:42", new: true, in_phonebook: false, area_name: "München", recording_path: "/api/fritzbox_phone/recording/e1/0/1" },
  { index: 2, number: "01711234567", name: "Anna Schmidt", date: avmDate(1600), duration: "0:18", new: false, in_phonebook: true, area_name: "Mobilfunk", recording_path: "/api/fritzbox_phone/recording/e1/0/2" },
  { index: 3, number: "069987654", name: null, reverse_name: "Gewinnspiel-Zentrale", is_spam: true, date: avmDate(2900), duration: "0:07", new: false, in_phonebook: false, area_name: "Frankfurt am Main", recording_path: "/api/fritzbox_phone/recording/e1/0/3" },
];

const contacts = [
  { name: "Anna Schmidt", vip: true, numbers: [{ type: "Mobil", number: "0171 1234567" }, { type: "Privat", number: "030 9876543" }] },
  { name: "Dr. Weber (Praxis)", vip: false, numbers: [{ type: "Arbeit", number: "030 12345678" }] },
  { name: "Familie Müller", vip: true, numbers: [{ type: "Privat", number: "040 555000" }] },
  { name: "Pizzeria Roma", vip: false, numbers: [{ type: "Arbeit", number: "030 55512345" }] },
];

const iso = (secondsAgo) => new Date(Date.now() - secondsAgo * 1000).toISOString();

const SCENES = {
  calls: { height: 560, config: { entity: "sensor.calls", tam_entity: "sensor.tam", rows: 6 }, open: ".fb-row[data-type=fb-miss] .fb-main" },
  messages: { height: 430, config: { entity: "sensor.tam", rows: 5 }, open: ".fb-vm .fb-main" },
  phonebook: { height: 400, config: { entity: "sensor.phonebook", rows: 6 } },
  ringing: { height: 130, config: { entity: "sensor.monitor" } },
  talking: { height: 130, config: { entity: "sensor.monitor" }, state: "talking" },
};

const LANGS = { de: "screenshots", en: "screenshots-en" };

function states(lang, sceneName) {
  const en = lang === "en";
  const monitor = {
    ringing: { state: "ringing", attributes: { from: "01711234567", from_name: "Anna Schmidt", vip: true, area_name: en ? "Mobile" : "Mobilfunk", initiated: iso(7) } },
    talking: { state: "talking", attributes: { with: "03055512345", with_name: "Pizzeria Roma", area_name: "Berlin", accepted: iso(74) } },
  };
  return {
    "sensor.calls": { entity_id: "sensor.calls", state: String(calls.length), attributes: { friendly_name: en ? "Call list" : "Anrufliste", calls } },
    "sensor.tam": { entity_id: "sensor.tam", state: "1", attributes: { friendly_name: en ? "Answering machine" : "Anrufbeantworter", messages } },
    "sensor.phonebook": { entity_id: "sensor.phonebook", state: String(contacts.length), attributes: { friendly_name: en ? "Phonebook" : "Telefonbuch", contacts } },
    "sensor.monitor": {
      entity_id: "sensor.monitor",
      ...(monitor[sceneName] || monitor.ringing),
      attributes: { friendly_name: en ? "Call monitor" : "Anrufmonitor", ...(monitor[sceneName] || monitor.ringing).attributes },
    },
  };
}

const iconPath = (name) => mdi["mdi" + name.replace(/^mdi:/, "").replace(/(^|-)(\w)/g, (_, __, c) => c.toUpperCase())];

const browser = await chromium.launch();
try {
  for (const [lang, dir] of Object.entries(LANGS)) {
    const outDir = join(root, dir);
    mkdirSync(outDir, { recursive: true });
    for (const [themeName, theme] of Object.entries(THEMES)) {
      const vars = Object.entries(theme).filter(([k]) => k.startsWith("--")).map(([k, v]) => `${k}:${v}`).join(";");
      for (const [sceneName, scene] of Object.entries(SCENES)) {
        const page = await browser.newPage({ viewport: { width: 460, height: scene.height }, deviceScaleFactor: 2 });
        await page.setContent(`<!doctype html><html><body style="margin:0;padding:16px;background:${theme.page};${vars};font-family:Roboto,system-ui,sans-serif;font-size:14px"><div id="host" style="width:428px"></div></body></html>`);
        await page.evaluate(
          () => {
            customElements.define("ha-card", class extends HTMLElement {
              connectedCallback() {
                this.style.cssText = "display:block;background:var(--card-background-color);border-radius:12px;box-shadow:0 1px 3px rgba(0,0,0,.2);overflow:hidden;color:var(--primary-text-color)";
              }
            });
            customElements.define("ha-icon", class extends HTMLElement {
              static get observedAttributes() { return ["icon"]; }
              attributeChangedCallback() { this.render(); }
              connectedCallback() { this.render(); }
              render() {
                const d = window.__paths[this.getAttribute("icon")];
                // :host rules lose against the card's own styles, so its
                // show/hide classes (play/pause) keep working.
                const shadow = this.shadowRoot || this.attachShadow({ mode: "open" });
                shadow.innerHTML = `<style>:host{display:inline-flex;width:24px;height:24px}</style>${
                  d ? `<svg viewBox="0 0 24 24" width="100%" height="100%" fill="currentColor"><path d="${d}"/></svg>` : ""}`;
              }
            });
          }
        );
        // ha-icon looks icons up by their "mdi:foo-bar" name; hand over just those.
        const names = new Set([...CARD.matchAll(/mdi:[a-z0-9-]+/g)].map((m) => m[0]));
        await page.evaluate((map) => { window.__paths = map; }, Object.fromEntries([...names].map((n) => [n, iconPath(n)])));
        await page.addScriptTag({ content: CARD });
        await page.evaluate(
          ({ config, hassStates, language }) => {
            const card = document.createElement("fritzbox-phone-card");
            document.getElementById("host").appendChild(card);
            card.setConfig(config);
            card.hass = {
              states: hassStates, language, locale: { language },
              entities: {}, callService: async () => {}, callWS: async () => ({ path: "" }),
            };
          },
          { config: scene.config, hassStates: states(lang, sceneName), language: lang }
        );
        if (scene.open) await page.locator(`fritzbox-phone-card >> css=${scene.open}`).first().click();
        await page.evaluate(() => document.querySelector("fritzbox-phone-card").shadowRoot.activeElement?.blur());
        await page.mouse.move(0, 0);
        await page.waitForTimeout(200);
        const target = page.locator("fritzbox-phone-card");
        await target.screenshot({ path: join(outDir, `${sceneName}-${themeName}.png`) });
        await page.close();
      }
    }
  }
} finally {
  await browser.close();
}
