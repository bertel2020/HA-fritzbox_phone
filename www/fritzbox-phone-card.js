/**
 * fritzbox-phone-card
 *
 * Lovelace custom card for the "fritzbox_phone" integration. Auto-detects
 * whether the configured entity is a call-list sensor (`calls` attribute),
 * an answering-machine sensor (`messages` attribute), or the CallMonitor
 * sensor (idle/ringing/dialing/talking) and renders the matching view -
 * the two list views share the same icon+text row layout so they look and
 * size consistently next to each other; the CallMonitor view is a single
 * "hero" row highlighting the current call. For messages it wires
 * Play/Delete directly to the real `hass` object (no injected-HTML
 * workarounds needed, unlike a generic html-template-card).
 */

const CARD_TAG = "fritzbox-phone-card";
const EDITOR_TAG = "fritzbox-phone-card-editor";

const DEFAULT_ROWS = 8;

const STYLE_CSS = `
  :host { display: block; }
  ha-card { overflow: hidden; }
  .fb-header {
    display: flex; align-items: baseline; justify-content: space-between;
    padding: 16px 16px 8px;
  }
  .fb-header h2 {
    margin: 0; font-size: 18px; font-weight: 500; letter-spacing: -0.012em;
  }
  .fb-pill {
    font-size: 11.5px; font-weight: 600; color: var(--warning-color, #c98a1f);
    background: color-mix(in srgb, var(--warning-color, #c98a1f) 16%, transparent);
    padding: 3px 9px; border-radius: 999px; white-space: nowrap;
  }
  .fb-content { padding: 0 16px 16px; }
  .fb-empty {
    padding: 16px 0; color: var(--secondary-text-color); font-size: 13px;
  }

  .fb-legend { display: flex; gap: 14px; flex-wrap: wrap; margin: 0 0 8px; }
  .fb-legend-item {
    display: inline-flex; align-items: center; gap: 6px; font: inherit; font-size: 12px;
    color: var(--secondary-text-color); background: none; border: none; cursor: pointer;
    padding: 3px 6px; margin: -3px -6px; border-radius: 6px; -webkit-tap-highlight-color: transparent;
  }
  .fb-legend-item:hover { background: var(--secondary-background-color); }
  .fb-legend-item i { width: 9px; height: 9px; border-radius: 50%; display: inline-block; background: currentColor; }
  .fb-legend-item.fb-out { color: var(--success-color, #3ddc84); }
  .fb-legend-item.fb-in { color: var(--info-color, #4f9dff); }
  .fb-legend-item.fb-miss { color: var(--error-color, #f2585a); }
  .fb-legend-item.fb-ab { color: var(--warning-color, #e0ac4c); }
  .fb-legend-item.inactive { opacity: .4; }
  .fb-row.fb-limit-hidden { display: none; }

  .fb-list { display: flex; flex-direction: column; }
  .fb-row {
    display: grid; grid-template-columns: 30px 1fr auto; align-items: center; gap: 10px;
    padding: 8px 2px; border-top: 1px solid var(--divider-color);
  }
  .fb-row:first-child { border-top: none; }
  .fb-calls-body .fb-row { cursor: pointer; }
  .fb-calls-body .fb-row:hover { background: var(--secondary-background-color); }
  .fb-calls-body .fb-name { font-weight: 700; }

  .fb-icon {
    width: 30px; height: 30px; border-radius: 50%; display: flex; align-items: center;
    justify-content: center; background: var(--secondary-background-color);
    color: var(--secondary-text-color); position: relative; flex-shrink: 0;
  }
  .fb-icon ha-icon { --mdc-icon-size: 15px; }
  .fb-icon.fb-out { color: var(--success-color, #3ddc84); }
  .fb-icon.fb-in { color: var(--info-color, #4f9dff); }
  .fb-icon.fb-miss { color: var(--error-color, #f2585a); }
  .fb-row.is-new .fb-icon { color: var(--primary-color); }
  .fb-row.is-new .fb-icon::after {
    content: ""; position: absolute; top: -1px; right: -1px; width: 8px; height: 8px;
    border-radius: 50%; background: var(--warning-color, #e0ac4c);
    border: 2px solid var(--card-background-color, #fff);
  }
  .fb-icon.fb-ab { color: var(--warning-color, #e0ac4c); }

  .fb-main { min-width: 0; }
  .fb-name-row { display: flex; align-items: center; gap: 6px; min-width: 0; }
  .fb-name-row .fb-name { min-width: 0; }
  .fb-name { font-size: 13px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .fb-row.is-new .fb-name { font-weight: 700; }
  .fb-meta {
    font-size: 11.5px; color: var(--secondary-text-color); display: flex; gap: 6px;
    margin-top: 1px; font-variant-numeric: tabular-nums;
  }

  .fb-spam-badge {
    flex-shrink: 0; display: inline-flex; align-items: center;
    font-size: 9.5px; font-weight: 700; text-transform: uppercase; letter-spacing: .03em;
    color: var(--error-color, #e0453f);
    background: color-mix(in srgb, var(--error-color, #e0453f) 16%, transparent);
    padding: 1px 6px; border-radius: 999px;
  }

  .fb-actions { display: flex; gap: 4px; }
  .fb-btn {
    width: 28px; height: 28px; border-radius: 50%; border: none; cursor: pointer;
    background: var(--secondary-background-color); color: var(--primary-text-color);
    display: flex; align-items: center; justify-content: center;
  }
  .fb-btn:disabled { opacity: .5; cursor: default; }
  .fb-btn ha-icon { --mdc-icon-size: 14px; }
  .fb-btn .icon-pause { display: none; }
  .fb-row.is-playing .fb-btn.fb-play {
    background: var(--primary-color); color: var(--text-primary-color, #fff);
  }
  .fb-row.is-playing .fb-btn.fb-play .icon-play { display: none; }
  .fb-row.is-playing .fb-btn.fb-play .icon-pause { display: inline-flex; }

  .fb-progress {
    grid-column: 1 / -1; height: 3px; background: var(--divider-color); border-radius: 2px;
    overflow: hidden; display: none;
  }
  .fb-row.is-playing .fb-progress { display: block; }
  .fb-progress > span { display: block; height: 100%; width: 0%; background: var(--primary-color); }

  .fb-confirm {
    grid-column: 1 / -1; display: none; align-items: center; justify-content: space-between;
    gap: 8px; padding: 6px 8px; margin-top: 2px; border-radius: 8px;
    background: rgba(224, 90, 90, .15); font-size: 11.5px;
  }
  .fb-row.is-confirming .fb-confirm { display: flex; }
  .fb-confirm button {
    font: inherit; font-size: 11.5px; font-weight: 600; border: none; border-radius: 6px;
    padding: 4px 8px; cursor: pointer;
  }
  .fb-confirm .fb-confirm-no { background: transparent; color: var(--secondary-text-color); }
  .fb-confirm .fb-confirm-yes { background: var(--error-color, #e05a5a); color: #fff; }

  .fb-chevron {
    --mdc-icon-size: 18px; color: var(--secondary-text-color);
    transition: transform .15s ease; flex-shrink: 0; cursor: pointer;
  }
  .fb-row.is-expanded .fb-chevron { transform: rotate(180deg); }

  .fb-row-end { display: flex; align-items: center; gap: 6px; }

  .fb-vm .fb-main { cursor: pointer; border-radius: 6px; margin: -2px -4px; padding: 2px 4px; }
  .fb-vm .fb-main:hover { background: var(--secondary-background-color); }

  .fb-details {
    grid-column: 1 / -1; display: none; font-size: 11.5px; color: var(--secondary-text-color);
    padding: 6px 4px 2px 40px; line-height: 1.7;
  }
  .fb-row.is-expanded .fb-details { display: block; }
  .fb-details b { color: var(--primary-text-color); font-weight: 500; margin-right: 4px; }

  .fb-cm { display: grid; grid-template-columns: 44px 1fr; align-items: center; gap: 12px; padding: 6px 2px; }
  .fb-cm-icon {
    width: 44px; height: 44px; border-radius: 50%; display: flex; align-items: center;
    justify-content: center; background: var(--secondary-background-color);
    color: var(--secondary-text-color); flex-shrink: 0;
  }
  .fb-cm-icon ha-icon { --mdc-icon-size: 22px; }
  .fb-cm-icon.fb-cm-ringing { color: var(--error-color, #f2585a); animation: fb-cm-pulse 1.1s ease-in-out infinite; }
  .fb-cm-icon.fb-cm-dialing { color: var(--info-color, #4f9dff); }
  .fb-cm-icon.fb-cm-talking { color: var(--success-color, #3ddc84); }
  @keyframes fb-cm-pulse {
    0%, 100% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--error-color, #f2585a) 45%, transparent); }
    50% { box-shadow: 0 0 0 8px color-mix(in srgb, var(--error-color, #f2585a) 0%, transparent); }
  }
  .fb-cm-main { min-width: 0; }
  .fb-cm-name-row { display: flex; align-items: center; gap: 6px; min-width: 0; }
  .fb-cm-name { font-size: 15px; font-weight: 700; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .fb-cm-idle .fb-cm-name, .fb-cm-idle .fb-cm-state { color: var(--secondary-text-color); font-weight: 400; }
  .fb-cm-state {
    font-size: 12px; font-weight: 600; margin-top: 1px;
  }
  .fb-cm-state.fb-cm-state-ringing { color: var(--error-color, #f2585a); }
  .fb-cm-state.fb-cm-state-dialing { color: var(--info-color, #4f9dff); }
  .fb-cm-state.fb-cm-state-talking { color: var(--success-color, #3ddc84); }
  .fb-vip-badge {
    flex-shrink: 0; display: inline-flex; align-items: center;
    font-size: 9.5px; font-weight: 700; text-transform: uppercase; letter-spacing: .03em;
    color: var(--primary-color); background: color-mix(in srgb, var(--primary-color) 16%, transparent);
    padding: 1px 6px; border-radius: 999px;
  }
`;

function parseAvmDate(value) {
  const m = /^(\d{2})\.(\d{2})\.(\d{2})\s+(\d{2}):(\d{2})$/.exec(value || "");
  if (!m) return null;
  const [, d, mo, y, h, mi] = m;
  return new Date(2000 + Number(y), Number(mo) - 1, Number(d), Number(h), Number(mi));
}

function isSameDay(a, b) {
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  );
}

function formatDateObj(dt) {
  const now = new Date();
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  const hhmm = `${String(dt.getHours()).padStart(2, "0")}:${String(dt.getMinutes()).padStart(2, "0")}`;
  if (isSameDay(dt, now)) return `heute ${hhmm}`;
  if (isSameDay(dt, yesterday)) return `gestern ${hhmm}`;
  const dd = String(dt.getDate()).padStart(2, "0");
  const mm = String(dt.getMonth() + 1).padStart(2, "0");
  const yy = String(dt.getFullYear()).slice(-2);
  return `${dd}.${mm}.${yy} ${hhmm}`;
}

function formatClockTime(dt) {
  return `${String(dt.getHours()).padStart(2, "0")}:${String(dt.getMinutes()).padStart(2, "0")}`;
}

function formatDatum(value) {
  const dt = parseAvmDate(value);
  return dt ? formatDateObj(dt) : value || "";
}

// AVM's call-list Duration field is "hh:mm" (hours:minutes, minutes
// rounded up) - NOT minutes:seconds, despite looking like it at a glance
// (TR-064_Contact_SCPD.pdf, table 69: "Duration | String | hh:mm (minutes
// rounded up)"). A call showing "1:10" ran for ~1h10m, not 1m10s.
function parseCallDurationMinutes(value) {
  const m = /^(\d+):(\d{2})$/.exec(value || "");
  if (!m) return null;
  return Number(m[1]) * 60 + Number(m[2]);
}

function callEndTime(call) {
  const start = parseAvmDate(call.date);
  const minutes = parseCallDurationMinutes(call.duration);
  if (!start || minutes == null) return null;
  return new Date(start.getTime() + minutes * 60000);
}

function callVisuals(call) {
  if (call.type === "outgoing") return { cls: "fb-out", icon: "mdi:phone-outgoing" };
  if (call.type === "missed" || call.type === "rejected_incoming") {
    return { cls: "fb-miss", icon: "mdi:phone-missed" };
  }
  return { cls: "fb-in", icon: "mdi:phone-incoming" };
}

function callNumber(call) {
  if (call.type === "outgoing") return call.called_number || call.called || "";
  return call.caller_number || call.caller || "";
}

function displayName(name, reverseName, number) {
  if (name) return name;
  if (reverseName) return reverseName;
  return number ? `Unbekannt (${number})` : "Unbekannt";
}

function normalizeNumberForMatch(value) {
  return (value || "").replace(/\D/g, "");
}

// True if two numbers are "the same" for correlation purposes, tolerating
// national ("030123456") vs. international ("+4930123456"/"0049 30...")
// representations - the call-list and TAM APIs don't necessarily agree on
// which form they use, so a plain string/digit comparison can miss a real
// match. Compares trailing digits instead (a household's own call/message
// history is very unlikely to collide there).
function numbersLikelyMatch(a, b) {
  const da = normalizeNumberForMatch(a);
  const db = normalizeNumberForMatch(b);
  if (!da || !db) return false;
  if (da === db) return true;
  const tailLen = Math.min(da.length, db.length, 8);
  if (tailLen < 6) return false;
  return da.slice(-tailLen) === db.slice(-tailLen);
}

// Correlates a call-list entry that went to the answering machine with the
// corresponding message in a linked TAM entity's `messages` attribute.
// There's no shared ID between the two APIs, so this matches on caller
// number (tolerantly, see numbersLikelyMatch), then - if several messages
// came from that number - picks whichever is closest in time to the call.
// AVM's Date fields only have minute precision and the TAM records only
// after playing its announcement, so the call's and the message's Date
// commonly land in different minutes; requiring an exact match would miss
// this normal case. `claimed` prevents the same message being linked to
// more than one call row.
function findMatchingTamMessage(call, messages, claimed) {
  const callerRaw = call.caller_number || call.caller;
  if (!callerRaw) return null;
  const candidates = messages.filter(
    (m) => !claimed.has(m.index) && numbersLikelyMatch(callerRaw, m.number)
  );
  if (candidates.length === 0) return null;

  let best = candidates[0];
  if (candidates.length > 1) {
    const callTime = parseAvmDate(call.date);
    let bestDiff = Infinity;
    for (const m of candidates) {
      const messageTime = parseAvmDate(m.date);
      const diff = callTime && messageTime ? Math.abs(messageTime.getTime() - callTime.getTime()) : Infinity;
      if (diff < bestDiff) {
        bestDiff = diff;
        best = m;
      }
    }
  }
  claimed.add(best.index);
  return best;
}

function metaLine(parts) {
  const meta = document.createElement("div");
  meta.className = "fb-meta";
  meta.innerHTML = parts
    .filter(Boolean)
    .map((part) => `<span>${part}</span>`)
    .join("<span>·</span>");
  return meta;
}

const CALL_TYPE_LABELS = {
  outgoing: "Ausgehend",
  incoming: "Eingehend",
  missed: "Verpasst",
  active_incoming: "Aktiv eingehend",
  rejected_incoming: "Abgewiesen",
  active_outgoing: "Aktiv ausgehend",
};

const CALLMONITOR_STATES = ["idle", "ringing", "dialing", "talking"];

const CALLMONITOR_VISUALS = {
  ringing: { icon: "mdi:phone-ring", cls: "fb-cm-ringing", label: "Klingelt" },
  dialing: { icon: "mdi:phone-outgoing", cls: "fb-cm-dialing", label: "Wählt" },
  talking: { icon: "mdi:phone-in-talk", cls: "fb-cm-talking", label: "Gespräch" },
  idle: { icon: "mdi:phone-hangup", cls: "", label: "Kein aktiver Anruf" },
};

function formatElapsed(seconds) {
  const s = Math.max(0, Math.floor(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  const mm = String(m).padStart(h > 0 ? 2 : 1, "0");
  const ss = String(sec).padStart(2, "0");
  return h > 0 ? `${h}:${String(m).padStart(2, "0")}:${ss}` : `${mm}:${ss}`;
}

// PhoneBlock's Rating enum (de.haumacher.phoneblock.app.api.model.Rating).
const PHONEBLOCK_RATING_LABELS = {
  A_LEGITIMATE: "Unauffällig",
  B_MISSED: "Negativ bewertet",
  C_PING: "Ping-Anruf",
  D_POLL: "Umfrage",
  E_ADVERTISING: "Werbung",
  F_GAMBLE: "Gewinnspiel",
  G_FRAUD: "Betrugsversuch",
};

function spamDetailItems(entity) {
  const items = [];
  if (entity.spam_confidence != null) {
    items.push(["Spam-Wahrscheinlichkeit", `${entity.spam_confidence}% (PhoneBlock)`]);
  }
  if (entity.spam_rating) {
    items.push(["Einstufung", PHONEBLOCK_RATING_LABELS[entity.spam_rating] || entity.spam_rating]);
  }
  if (entity.spam_location) {
    items.push(["Ort (PhoneBlock)", entity.spam_location]);
  }
  return items;
}

function reverseDetailItems(entity) {
  const items = [];
  if (!entity.name && entity.reverse_name) {
    items.push(["Quelle", "Tellows (Online-Rückwärtssuche)"]);
    if (entity.reverse_category) items.push(["Kategorie", entity.reverse_category]);
  }
  return items;
}

function callDetails(call, tamMessage) {
  const items = [
    ["Anruftyp", CALL_TYPE_LABELS[call.type] || call.type || "-"],
    ["Rufnummer", callNumber(call) || "-"],
  ];
  if (call.date) items.push(["Beginn", formatDatum(call.date)]);
  if (call.type !== "missed") {
    const end = callEndTime(call);
    if (end) items.push(["Ende", formatDateObj(end)]);
    if (call.duration) items.push(["Dauer", call.duration]);
  }
  if (call.area_name) items.push(["Ort/Land", call.area_name]);
  if (call.type === "outgoing") {
    const own = call.caller_number || call.caller;
    if (own) items.push(["Eigene Nebenstelle", own]);
  } else {
    const own = call.called_number || call.called;
    if (own) items.push(["Eigene Nummer", own]);
  }
  if (call.is_fax) items.push(["Fax", "Ja"]);
  if (call.is_answering_machine) items.push(["Anrufbeantworter", "Ja"]);
  if (tamMessage) {
    items.push(["Nachricht", tamMessage.new ? "Neu" : "Gelesen"]);
    items.push(["In Telefonbuch", tamMessage.inbook ? "Ja" : "Nein"]);
  }
  items.push(...spamDetailItems(call));
  items.push(...reverseDetailItems(call));
  return items;
}

function messageDetails(message) {
  const items = [
    ["Rufnummer", message.number || "-"],
    ["Status", message.new ? "Neu" : "Gelesen"],
  ];
  if (message.area_name) items.push(["Ort/Land", message.area_name]);
  if (message.called) items.push(["Eigene Nummer", message.called]);
  items.push(["In Telefonbuch", message.in_phonebook ? "Ja" : "Nein"]);
  items.push(...spamDetailItems(message));
  items.push(...reverseDetailItems(message));
  return items;
}

function buildDetails(items) {
  const box = document.createElement("div");
  box.className = "fb-details";
  box.innerHTML = items.map(([label, value]) => `<div><b>${label}:</b> ${value}</div>`).join("");
  return box;
}

function buildNameLine(text, isSpam) {
  const wrap = document.createElement("div");
  wrap.className = "fb-name-row";
  const name = document.createElement("span");
  name.className = "fb-name";
  name.textContent = text;
  wrap.appendChild(name);
  if (isSpam) {
    const badge = document.createElement("span");
    badge.className = "fb-spam-badge";
    badge.textContent = "Spam";
    wrap.appendChild(badge);
  }
  return wrap;
}

class FritzboxPhoneCard extends HTMLElement {
  static getStubConfig(hass) {
    const entity = Object.keys(hass.states || {}).find((id) => {
      if (!id.startsWith("sensor.")) return false;
      const attrs = hass.states[id].attributes || {};
      return (
        Array.isArray(attrs.calls) ||
        Array.isArray(attrs.messages) ||
        CALLMONITOR_STATES.includes(hass.states[id].state)
      );
    });
    return { entity: entity || "", rows: DEFAULT_ROWS };
  }

  static getConfigElement() {
    return document.createElement(EDITOR_TAG);
  }

  setConfig(config) {
    if (!config || !config.entity) {
      throw new Error(
        "Bitte eine Entität auswählen (sensor.*_anrufliste, sensor.*_<anrufbeantworter> oder sensor.*_anrufmonitor)."
      );
    }
    this._config = {
      rows: DEFAULT_ROWS,
      mark_read_on_play: true,
      show_legend: true,
      ...config,
    };
    this._lastStateObj = undefined;
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  get hass() {
    return this._hass;
  }

  getCardSize() {
    const entityId = this._config && this._config.entity;
    const stateObj = this._hass && entityId && this._hass.states[entityId];
    if (stateObj && CALLMONITOR_STATES.includes(stateObj.state)) {
      return 1;
    }
    const rows = (this._config && this._config.rows) || DEFAULT_ROWS;
    const extra = this._config && this._config.tam_entity ? 2 : 0;
    return Math.max(2, Math.ceil(rows / 2) + 1) + extra;
  }

  connectedCallback() {
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    this._render();
  }

  disconnectedCallback() {
    this._stopCallMonitorTimer();
  }

  _stopCallMonitorTimer() {
    if (this._cmInterval) {
      clearInterval(this._cmInterval);
      this._cmInterval = null;
    }
  }

  _render() {
    if (!this._hass || !this._config || !this.shadowRoot) return;
    const entityId = this._config.entity;
    const stateObj = this._hass.states[entityId];
    const tamEntityId = this._config.tam_entity;
    const tamStateObj = tamEntityId ? this._hass.states[tamEntityId] : undefined;

    // Skip re-render if neither this entity's nor the linked TAM entity's
    // state object changed (avoids resetting playback/confirm UI state on
    // unrelated hass updates).
    if (stateObj === this._lastStateObj && tamStateObj === this._lastTamStateObj) return;
    this._lastStateObj = stateObj;
    this._lastTamStateObj = tamStateObj;
    this._stopCallMonitorTimer();

    this.shadowRoot.innerHTML = "";
    const style = document.createElement("style");
    style.textContent = STYLE_CSS;
    this.shadowRoot.appendChild(style);

    const card = document.createElement("ha-card");

    const title = this._config.title || (stateObj && (stateObj.attributes.friendly_name || entityId)) || entityId;
    const attrs = (stateObj && stateObj.attributes) || {};
    const isMessages = Array.isArray(attrs.messages);
    const isCallMonitor = !!stateObj && CALLMONITOR_STATES.includes(stateObj.state);
    const tamContext =
      Array.isArray(attrs.calls) && tamStateObj && Array.isArray(tamStateObj.attributes.messages)
        ? { entityId: tamStateObj.entity_id, messages: tamStateObj.attributes.messages }
        : null;

    const header = document.createElement("div");
    header.className = "fb-header";
    const h2 = document.createElement("h2");
    h2.textContent = title;
    header.appendChild(h2);
    if (isMessages || tamContext) {
      // Same "X neu" pill as the standalone Anrufbeantworter card - counts
      // ALL new messages on the linked TAM entity, not just the ones that
      // happened to get matched to a currently-visible call row.
      const messages = isMessages ? attrs.messages : tamContext.messages;
      const newCount = messages.filter((m) => m.new).length;
      const pill = document.createElement("span");
      pill.className = "fb-pill";
      pill.textContent = newCount > 0 ? `${newCount} neu` : "Alles gelesen";
      header.appendChild(pill);
    }
    card.appendChild(header);

    const content = document.createElement("div");
    content.className = "fb-content";

    if (!stateObj) {
      content.innerHTML = `<div class="fb-empty">Entität <code>${entityId}</code> nicht gefunden.</div>`;
    } else if (Array.isArray(attrs.calls)) {
      content.appendChild(this._buildCallsList(attrs.calls, tamContext));
    } else if (isMessages) {
      content.appendChild(this._buildMessagesList(attrs.messages, entityId));
    } else if (isCallMonitor) {
      content.appendChild(this._buildCallMonitor(stateObj));
    } else {
      content.innerHTML =
        '<div class="fb-empty">Diese Entität liefert weder <code>calls</code>, <code>messages</code> noch einen Anrufmonitor-Status - falsche Entität ausgewählt?</div>';
    }

    card.appendChild(content);
    this.shadowRoot.appendChild(card);
  }

  _buildCallMonitor(stateObj) {
    const state = stateObj.state;
    const attrs = stateObj.attributes || {};
    const visuals = CALLMONITOR_VISUALS[state] || CALLMONITOR_VISUALS.idle;

    const wrap = document.createElement("div");
    wrap.className = `fb-cm${state === "idle" ? " fb-cm-idle" : ""}`;

    const iconEl = document.createElement("div");
    iconEl.className = `fb-cm-icon ${visuals.cls}`;
    const ic = document.createElement("ha-icon");
    ic.setAttribute("icon", visuals.icon);
    iconEl.appendChild(ic);
    wrap.appendChild(iconEl);

    const main = document.createElement("div");
    main.className = "fb-cm-main";

    if (state === "idle") {
      const stateLine = document.createElement("div");
      stateLine.className = "fb-cm-state";
      stateLine.textContent = visuals.label;
      main.appendChild(stateLine);

      // The last DISCONNECT keeps the previous call's context (see
      // sensor.py) - "with"/"to"/"from" cover talking->idle, an
      // unanswered outgoing call, and a missed incoming call respectively.
      const lastNumber = attrs.with || attrs.to || attrs.from;
      if (lastNumber) {
        const lastName = attrs.with_name || attrs.to_name || attrs.from_name;
        const nameRow = document.createElement("div");
        nameRow.className = "fb-cm-name-row";
        const nameEl = document.createElement("span");
        nameEl.className = "fb-cm-name";
        nameEl.textContent = `Letzter Anruf: ${displayName(lastName, attrs.reverse_name, lastNumber)}`;
        nameRow.appendChild(nameEl);
        main.appendChild(nameRow);

        const startDt = attrs.started ? new Date(attrs.started) : null;
        const endDt = attrs.closed ? new Date(attrs.closed) : null;
        const timeRange =
          startDt && endDt ? `${formatClockTime(startDt)}–${formatClockTime(endDt)}` : null;
        main.appendChild(metaLine([timeRange, attrs.area_name, attrs.duration_formatted]));
      }

      wrap.appendChild(main);
      return wrap;
    }

    let name = null;
    let reverseName = null;
    let number = null;
    let timestampKey = null;
    if (state === "ringing") {
      name = attrs.from_name;
      reverseName = attrs.reverse_name;
      number = attrs.from;
      timestampKey = "initiated";
    } else if (state === "dialing") {
      name = attrs.to_name;
      number = attrs.to;
      timestampKey = "initiated";
    } else if (state === "talking") {
      name = attrs.with_name;
      number = attrs.with;
      timestampKey = "accepted";
    }

    const nameRow = document.createElement("div");
    nameRow.className = "fb-cm-name-row";
    const nameEl = document.createElement("span");
    nameEl.className = "fb-cm-name";
    nameEl.textContent = displayName(name, reverseName, number);
    nameRow.appendChild(nameEl);
    if (attrs.vip) {
      const vipBadge = document.createElement("span");
      vipBadge.className = "fb-vip-badge";
      vipBadge.textContent = "VIP";
      nameRow.appendChild(vipBadge);
    }
    if (attrs.is_spam) {
      const spamBadge = document.createElement("span");
      spamBadge.className = "fb-spam-badge";
      spamBadge.textContent = "Spam";
      nameRow.appendChild(spamBadge);
    }
    main.appendChild(nameRow);

    const stateLine = document.createElement("div");
    stateLine.className = `fb-cm-state fb-cm-state-${state}`;
    stateLine.textContent = visuals.label;
    main.appendChild(stateLine);

    const meta = metaLine([attrs.area_name].filter(Boolean));
    if (timestampKey && attrs[timestampKey]) {
      if (meta.childElementCount > 0) {
        const sep = document.createElement("span");
        sep.textContent = "·";
        meta.appendChild(sep);
      }
      const timerSpan = document.createElement("span");
      timerSpan.className = "fb-cm-timer";
      meta.appendChild(timerSpan);
      this._startCallMonitorTimer(timerSpan, attrs[timestampKey]);
    }
    main.appendChild(meta);

    wrap.appendChild(main);
    return wrap;
  }

  _startCallMonitorTimer(el, isoTimestamp) {
    const start = new Date(isoTimestamp).getTime();
    if (Number.isNaN(start)) return;
    const tick = () => {
      el.textContent = formatElapsed((Date.now() - start) / 1000);
    };
    tick();
    this._cmInterval = setInterval(tick, 1000);
  }

  _buildCallsList(calls, tamContext) {
    const body = document.createElement("div");
    body.className = "fb-calls-body";
    const activeTypes = new Set(["fb-out", "fb-in", "fb-miss"]);
    if (tamContext) activeTypes.add("fb-ab");

    const list = document.createElement("div");
    list.className = "fb-list";

    if (this._config.show_legend !== false) {
      body.appendChild(
        this._buildLegend(activeTypes, () => this._applyCallFilter(list, activeTypes), !!tamContext)
      );
    }
    body.appendChild(list);

    if (calls.length === 0) {
      const empty = document.createElement("div");
      empty.className = "fb-empty";
      empty.textContent = "Keine Anrufe";
      list.appendChild(empty);
      return body;
    }

    // Each matched TAM message can only be linked to one call row, so
    // matches are claimed as they're used (relevant if the same number
    // called more than once and left more than one message).
    const claimedMessages = tamContext ? new Set() : null;
    for (const call of calls) {
      const tamMessage =
        call.is_answering_machine && tamContext
          ? findMatchingTamMessage(call, tamContext.messages, claimedMessages)
          : null;
      list.appendChild(
        this._buildCallRow(call, tamMessage ? tamContext.entityId : null, tamMessage)
      );
    }

    const filterEmpty = document.createElement("div");
    filterEmpty.className = "fb-empty fb-filter-empty";
    filterEmpty.textContent = "Keine Anrufe für diese Auswahl";
    filterEmpty.style.display = "none";
    list.appendChild(filterEmpty);

    this._applyCallFilter(list, activeTypes);
    return body;
  }

  _buildCallRow(call, tamEntityId, tamMessage) {
    const visuals = callVisuals(call);
    // A call that went to the answering machine gets its own filter/color
    // category ("AB"), same idea as "Verpasst" already being its own
    // category instead of just staying tagged "Eingehend".
    const cls = tamMessage ? "fb-ab" : visuals.cls;
    const icon = tamMessage ? "mdi:voicemail" : visuals.icon;

    const row = document.createElement("div");
    row.className = `fb-row ${cls}${tamMessage ? " fb-vm" : ""}${tamMessage && tamMessage.new ? " is-new" : ""}`;
    row.dataset.type = cls;

    const iconEl = document.createElement("div");
    iconEl.className = `fb-icon ${cls}`;
    const ic = document.createElement("ha-icon");
    ic.setAttribute("icon", icon);
    iconEl.appendChild(ic);
    row.appendChild(iconEl);

    const main = document.createElement("div");
    main.className = "fb-main";
    main.appendChild(
      buildNameLine(displayName(call.name, call.reverse_name, callNumber(call)), call.is_spam)
    );
    main.appendChild(
      metaLine([
        formatDatum(call.date),
        call.device,
        call.type !== "missed" ? call.duration : null,
      ])
    );
    row.appendChild(main);
    main.addEventListener("click", () => row.classList.toggle("is-expanded"));

    const chevron = document.createElement("ha-icon");
    chevron.className = "fb-chevron";
    chevron.setAttribute("icon", "mdi:chevron-down");
    chevron.addEventListener("click", () => row.classList.toggle("is-expanded"));

    if (tamMessage) {
      // Play/Delete sit next to the chevron in the same row-end area, so
      // both the expand affordance and the AB controls stay available.
      const endWrap = document.createElement("div");
      endWrap.className = "fb-row-end";
      row.appendChild(endWrap);
      this._appendTamActions(row, tamEntityId, tamMessage, endWrap);
      endWrap.appendChild(chevron);
    } else {
      row.appendChild(chevron);
    }

    row.appendChild(buildDetails(callDetails(call, tamMessage)));

    return row;
  }

  // Legend clicks toggle membership in `activeTypes`; the row limit is then
  // re-applied to the *filtered* set so exactly `rows` matching entries stay
  // visible (backfilling from further down the list) instead of just
  // hiding whatever happened to be in the first `rows` unfiltered rows.
  _applyCallFilter(list, activeTypes) {
    const rows = Array.from(list.querySelectorAll(".fb-row"));
    const limit = this._config.rows;
    let shown = 0;
    for (const row of rows) {
      const withinLimit = activeTypes.has(row.dataset.type) && shown < limit;
      row.classList.toggle("fb-limit-hidden", !withinLimit);
      if (withinLimit) shown++;
    }
    const emptyMsg = list.querySelector(".fb-filter-empty");
    if (emptyMsg) emptyMsg.style.display = shown === 0 && rows.length > 0 ? "block" : "none";
  }

  _buildLegend(activeTypes, onChange, includeAb) {
    const legend = document.createElement("div");
    legend.className = "fb-legend";
    const types = [
      { cls: "fb-out", label: "Ausgehend" },
      { cls: "fb-in", label: "Eingehend" },
      { cls: "fb-miss", label: "Verpasst" },
    ];
    if (includeAb) types.push({ cls: "fb-ab", label: "AB" });
    for (const t of types) {
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = `fb-legend-item ${t.cls}`;
      chip.setAttribute("aria-pressed", "true");
      chip.innerHTML = `<i></i>${t.label}`;
      chip.addEventListener("click", () => {
        const active = chip.classList.toggle("inactive");
        chip.setAttribute("aria-pressed", String(!active));
        if (active) activeTypes.delete(t.cls);
        else activeTypes.add(t.cls);
        onChange();
      });
      legend.appendChild(chip);
    }
    return legend;
  }

  _buildMessagesList(messages, entityId) {
    const rows = messages.slice(0, this._config.rows);
    const list = document.createElement("div");
    list.className = "fb-list";

    if (rows.length === 0) {
      const empty = document.createElement("div");
      empty.className = "fb-empty";
      empty.textContent = "Keine Nachrichten";
      list.appendChild(empty);
      return list;
    }

    for (const message of rows) {
      list.appendChild(this._buildMessageRow(message, entityId));
    }
    return list;
  }

  _buildMessageRow(message, entityId) {
    const row = document.createElement("div");
    row.className = "fb-row fb-vm" + (message.new ? " is-new" : "");

    const iconEl = document.createElement("div");
    iconEl.className = "fb-icon";
    const ic = document.createElement("ha-icon");
    ic.setAttribute("icon", "mdi:voicemail");
    iconEl.appendChild(ic);
    row.appendChild(iconEl);

    const main = document.createElement("div");
    main.className = "fb-main";
    main.appendChild(
      buildNameLine(
        displayName(message.name, message.reverse_name, message.number),
        message.is_spam
      )
    );
    main.appendChild(metaLine([formatDatum(message.date), message.duration]));
    row.appendChild(main);
    main.addEventListener("click", () => row.classList.toggle("is-expanded"));

    this._appendTamActions(row, entityId, message);
    row.appendChild(buildDetails(messageDetails(message)));

    return row;
  }

  // Play/Delete buttons, playback progress bar, delete-confirm box and the
  // hidden <audio> element - shared between a standalone TAM message row
  // and a call-list row for a call that went to the answering machine
  // (linked via the card's optional `tam_entity` option).
  // `actionsContainer` lets the play/delete buttons land in a different
  // element than `row` itself (the merged call-row view groups them with
  // the chevron in a small end-of-row wrapper); everything else (progress
  // bar, delete-confirm box, audio element) always attaches to `row`.
  _appendTamActions(row, entityId, message, actionsContainer) {
    const actions = document.createElement("div");
    actions.className = "fb-actions";

    const playBtn = document.createElement("button");
    playBtn.className = "fb-btn fb-play";
    playBtn.title = "Abspielen";
    playBtn.innerHTML =
      '<ha-icon class="icon-play" icon="mdi:play"></ha-icon><ha-icon class="icon-pause" icon="mdi:pause"></ha-icon>';

    const delBtn = document.createElement("button");
    delBtn.className = "fb-btn fb-del";
    delBtn.title = "Löschen";
    delBtn.innerHTML = '<ha-icon icon="mdi:trash-can-outline"></ha-icon>';

    actions.appendChild(playBtn);
    actions.appendChild(delBtn);
    (actionsContainer || row).appendChild(actions);

    const progress = document.createElement("div");
    progress.className = "fb-progress";
    const progressBar = document.createElement("span");
    progress.appendChild(progressBar);
    row.appendChild(progress);

    const confirm = document.createElement("div");
    confirm.className = "fb-confirm";
    confirm.innerHTML = `
      <span>Nachricht endgültig löschen?</span>
      <span>
        <button class="fb-confirm-no">Abbrechen</button>
        <button class="fb-confirm-yes">Löschen</button>
      </span>
    `;
    row.appendChild(confirm);

    const audio = document.createElement("audio");
    audio.style.display = "none";
    audio.addEventListener("play", () => row.classList.add("is-playing"));
    audio.addEventListener("pause", () => row.classList.remove("is-playing"));
    audio.addEventListener("ended", () => row.classList.remove("is-playing"));
    audio.addEventListener("timeupdate", () => {
      if (audio.duration) {
        progressBar.style.width = `${(audio.currentTime / audio.duration) * 100}%`;
      }
    });
    row.appendChild(audio);

    playBtn.addEventListener("click", () =>
      this._handlePlay(entityId, message, row, audio, playBtn)
    );
    delBtn.addEventListener("click", () => row.classList.add("is-confirming"));
    confirm
      .querySelector(".fb-confirm-no")
      .addEventListener("click", () => row.classList.remove("is-confirming"));
    confirm
      .querySelector(".fb-confirm-yes")
      .addEventListener("click", () => this._handleDelete(entityId, message, row));
  }

  async _handlePlay(entityId, message, row, audio, playBtn) {
    if (!audio.paused) {
      audio.pause();
      return;
    }
    this.shadowRoot.querySelectorAll("audio").forEach((a) => {
      if (a !== audio) a.pause();
    });
    const filename = `tam_${message.index}.mp3`;
    const play = () => {
      audio.src = `/local/fritzbox_tam/${filename}?t=${Date.now()}`;
      audio.play();
    };
    if (audio.dataset.loaded === "1") {
      play();
      return;
    }
    playBtn.disabled = true;
    try {
      await this._hass.callService("fritzbox_phone", "download_message", {
        entity_id: entityId,
        message_index: message.index,
        filename,
      });
      audio.dataset.loaded = "1";
      play();
      row.classList.remove("is-new");
      if (this._config.mark_read_on_play !== false) {
        this._hass.callService("fritzbox_phone", "mark_message_read", {
          entity_id: entityId,
          message_index: message.index,
          read: true,
        });
      }
    } catch (err) {
      alert(`Fehler beim Laden der Nachricht: ${err.message || err}`);
    } finally {
      playBtn.disabled = false;
    }
  }

  async _handleDelete(entityId, message, row) {
    try {
      await this._hass.callService("fritzbox_phone", "delete_message", {
        entity_id: entityId,
        message_index: message.index,
      });
      row.remove();
    } catch (err) {
      row.classList.remove("is-confirming");
      alert(`Fehler beim Löschen: ${err.message || err}`);
    }
  }
}

class FritzboxPhoneCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = config;
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  connectedCallback() {
    this._render();
  }

  _schema() {
    return [
      { name: "entity", selector: { entity: { domain: "sensor" } } },
      { name: "title", selector: { text: {} } },
      {
        name: "rows",
        selector: { number: { min: 1, max: 50, mode: "box" } },
      },
      { name: "show_legend", selector: { boolean: {} } },
      { name: "tam_entity", selector: { entity: { domain: "sensor" } } },
      { name: "mark_read_on_play", selector: { boolean: {} } },
    ];
  }

  _computeLabel(schemaItem) {
    const labels = {
      entity: "Entität",
      title: "Titel (optional, Standard: Name der Entität)",
      rows: "Anzahl Zeilen",
      show_legend: "Filter-Legende anzeigen (nur Anrufliste)",
      tam_entity:
        "Verknüpfter Anrufbeantworter (optional, nur Anrufliste) - zeigt dessen Nachrichten unterhalb in derselben Karte",
      mark_read_on_play: "Beim Abspielen automatisch als gelesen markieren (nur Anrufbeantworter)",
    };
    return labels[schemaItem.name] || schemaItem.name;
  }

  _render() {
    if (!this._hass || !this._config) return;
    let form = this.querySelector("ha-form");
    if (!form) {
      this.innerHTML = "";
      form = document.createElement("ha-form");
      form.addEventListener("value-changed", (ev) => {
        ev.stopPropagation();
        this._config = ev.detail.value;
        this.dispatchEvent(
          new CustomEvent("config-changed", {
            detail: { config: this._config },
            bubbles: true,
            composed: true,
          })
        );
      });
      this.appendChild(form);
    }
    form.hass = this._hass;
    form.schema = this._schema();
    form.data = {
      rows: DEFAULT_ROWS,
      mark_read_on_play: true,
      show_legend: true,
      ...this._config,
    };
    form.computeLabel = (schemaItem) => this._computeLabel(schemaItem);
  }
}

customElements.define(CARD_TAG, FritzboxPhoneCard);
customElements.define(EDITOR_TAG, FritzboxPhoneCardEditor);

window.customCards = window.customCards || [];
window.customCards.push({
  type: CARD_TAG,
  name: "FRITZ!Box Anrufliste / Anrufbeantworter / Anrufmonitor",
  description:
    "Zeigt die Anrufliste, die Anrufbeantworter-Nachrichten oder den aktiven Anruf (Anrufmonitor) einer fritzbox_phone-Entität, inkl. Abspielen/Löschen.",
  preview: true,
});
