/**
 * fritzbox-phone-card
 *
 * Lovelace custom card for the "fritzbox_phone" integration. Detects from
 * the configured entity what to show:
 *   - call list / missed calls  (`calls` attribute)      -> call log
 *   - answering machine         (`messages` attribute)   -> messages
 *   - phonebook                 (`contacts` attribute)   -> searchable contacts
 *   - call monitor              (idle/ringing/dialing/talking) -> current call
 *
 * Everything that comes from a call (names, numbers, lookups) is rendered as
 * text, never as HTML. A redraw (new state from Home Assistant) keeps what the
 * user was doing: opened rows, legend filters, a pending delete confirmation
 * and - above all - audio that is playing.
 */

const CARD_TAG = "fritzbox-phone-card";
const EDITOR_TAG = "fritzbox-phone-card-editor";

const DEFAULT_ROWS = 8;
// A signed recording URL is valid for an hour; reuse it for a bit less.
const SIGN_EXPIRES_SECONDS = 3600;
const SIGN_REUSE_MS = 50 * 60 * 1000;

const TEXTS = {
  de: {
    choose_entity:
      "Bitte eine Entität auswählen (Anrufliste, Anrufbeantworter, Telefonbuch oder Anrufmonitor der Integration).",
    entity_missing: "Entität {entity} nicht gefunden.",
    entity_unavailable: "Entität {entity} ist nicht verfügbar.",
    wrong_entity:
      "Diese Entität liefert weder Anrufe, Nachrichten, Kontakte noch einen Anrufmonitor-Status - falsche Entität ausgewählt?",
    today: "heute",
    yesterday: "gestern",
    type_incoming: "Eingehend",
    type_outgoing: "Ausgehend",
    type_missed: "Verpasst",
    type_active_incoming: "Aktiv eingehend",
    type_rejected_incoming: "Abgewiesen",
    type_active_outgoing: "Aktiv ausgehend",
    cm_ringing: "Klingelt",
    cm_dialing: "Wählt",
    cm_talking: "Gespräch",
    cm_idle: "Kein aktiver Anruf",
    last_call: "Letzter Anruf: {name}",
    unknown: "Unbekannt",
    unknown_number: "Unbekannt ({number})",
    spam: "Spam",
    vip: "VIP",
    legend_out: "Ausgehend",
    legend_in: "Eingehend",
    legend_miss: "Verpasst",
    legend_ab: "AB",
    no_calls: "Keine Anrufe",
    no_filter_match: "Keine Anrufe für diese Auswahl",
    no_messages: "Keine Nachrichten",
    all_read: "Alles gelesen",
    n_new: "{n} neu",
    stats: "Heute: {calls} Anrufe, {missed} verpasst",
    d_call_type: "Anruftyp",
    d_number: "Rufnummer",
    d_begin: "Beginn",
    d_end: "Ende",
    d_duration: "Dauer",
    d_place: "Ort/Land",
    d_own_extension: "Eigene Nebenstelle",
    d_own_number: "Eigene Nummer",
    d_fax: "Fax",
    d_tam: "Anrufbeantworter",
    d_message: "Nachricht",
    d_status: "Status",
    d_in_phonebook: "In Telefonbuch",
    d_spam_probability: "Spam-Wahrscheinlichkeit",
    d_rating: "Einstufung",
    d_phoneblock_place: "Ort (PhoneBlock)",
    d_source: "Quelle",
    d_category: "Kategorie",
    yes: "Ja",
    no: "Nein",
    msg_new: "Neu",
    msg_read: "Gelesen",
    source_tellows: "Tellows (Online-Rückwärtssuche)",
    rating_A_LEGITIMATE: "Unauffällig",
    rating_B_MISSED: "Negativ bewertet",
    rating_C_PING: "Ping-Anruf",
    rating_D_POLL: "Umfrage",
    rating_E_ADVERTISING: "Werbung",
    rating_F_GAMBLE: "Gewinnspiel",
    rating_G_FRAUD: "Betrugsversuch",
    play: "Abspielen",
    pause: "Pause",
    delete: "Löschen",
    cancel: "Abbrechen",
    confirm_delete: "Nachricht endgültig löschen?",
    seek: "Position in der Aufnahme",
    err_load: "Fehler beim Laden der Nachricht: {error}",
    err_delete: "Fehler beim Löschen: {error}",
    no_recording: "Zu dieser Nachricht gibt es keine Aufnahme.",
    callback: "Zurückrufen",
    dial_started: "Wählhilfe gestartet - das Telefon klingelt gleich.",
    dial_failed: "Anruf konnte nicht gestartet werden: {error}",
    search: "Kontakte durchsuchen",
    no_contacts: "Keine Kontakte",
    no_matches: "Keine Treffer",
    more_contacts: "{n} weitere - die Suche eingrenzen",
    contacts_count: "{n} Kontakte",
    card_name: "FRITZ!Box Anrufliste / Anrufbeantworter / Telefonbuch / Anrufmonitor",
    card_description:
      "Zeigt Anrufliste, Anrufbeantworter-Nachrichten, Telefonbuch oder den aktiven Anruf einer fritzbox_phone-Entität, inkl. Abspielen, Löschen und Rückruf.",
    e_entity: "Entität",
    e_title: "Titel (optional, Standard: Name der Entität)",
    e_rows: "Anzahl Zeilen",
    e_show_legend: "Filter-Legende anzeigen",
    e_show_stats: "Tageszusammenfassung anzeigen",
    e_show_dial: "Rückruf-Knöpfe anzeigen",
    e_tam_entity:
      "Verknüpfter Anrufbeantworter (optional) - zeigt dessen Nachrichten in derselben Karte",
    e_mark_read_on_play: "Beim Abspielen als gelesen markieren",
    e_tap_action: "Antippen einer Zeile",
    e_tap_expand: "Details aufklappen",
    e_tap_more_info: "Entität öffnen",
  },
  en: {
    choose_entity:
      "Please choose an entity (call list, answering machine, phonebook or call monitor of the integration).",
    entity_missing: "Entity {entity} not found.",
    entity_unavailable: "Entity {entity} is unavailable.",
    wrong_entity:
      "This entity provides neither calls, messages, contacts nor a call monitor state - wrong entity selected?",
    today: "today",
    yesterday: "yesterday",
    type_incoming: "Incoming",
    type_outgoing: "Outgoing",
    type_missed: "Missed",
    type_active_incoming: "Active incoming",
    type_rejected_incoming: "Rejected",
    type_active_outgoing: "Active outgoing",
    cm_ringing: "Ringing",
    cm_dialing: "Dialing",
    cm_talking: "In a call",
    cm_idle: "No active call",
    last_call: "Last call: {name}",
    unknown: "Unknown",
    unknown_number: "Unknown ({number})",
    spam: "Spam",
    vip: "VIP",
    legend_out: "Outgoing",
    legend_in: "Incoming",
    legend_miss: "Missed",
    legend_ab: "Voicemail",
    no_calls: "No calls",
    no_filter_match: "No calls match this selection",
    no_messages: "No messages",
    all_read: "All read",
    n_new: "{n} new",
    stats: "Today: {calls} calls, {missed} missed",
    d_call_type: "Call type",
    d_number: "Phone number",
    d_begin: "Start",
    d_end: "End",
    d_duration: "Duration",
    d_place: "Place/country",
    d_own_extension: "Own extension",
    d_own_number: "Own number",
    d_fax: "Fax",
    d_tam: "Answering machine",
    d_message: "Message",
    d_status: "Status",
    d_in_phonebook: "In phonebook",
    d_spam_probability: "Spam probability",
    d_rating: "Rating",
    d_phoneblock_place: "Place (PhoneBlock)",
    d_source: "Source",
    d_category: "Category",
    yes: "Yes",
    no: "No",
    msg_new: "New",
    msg_read: "Read",
    source_tellows: "Tellows (online reverse lookup)",
    rating_A_LEGITIMATE: "Legitimate",
    rating_B_MISSED: "Rated negatively",
    rating_C_PING: "Ping call",
    rating_D_POLL: "Survey",
    rating_E_ADVERTISING: "Advertising",
    rating_F_GAMBLE: "Gambling",
    rating_G_FRAUD: "Fraud attempt",
    play: "Play",
    pause: "Pause",
    delete: "Delete",
    cancel: "Cancel",
    confirm_delete: "Delete this message for good?",
    seek: "Position in the recording",
    err_load: "Could not load the message: {error}",
    err_delete: "Could not delete: {error}",
    no_recording: "This message has no recording.",
    callback: "Call back",
    dial_started: "Dial help started - your phone is about to ring.",
    dial_failed: "Could not start the call: {error}",
    search: "Search contacts",
    no_contacts: "No contacts",
    no_matches: "No matches",
    more_contacts: "{n} more - narrow the search",
    contacts_count: "{n} contacts",
    card_name: "FRITZ!Box call list / answering machine / phonebook / call monitor",
    card_description:
      "Shows the call list, answering machine messages, phonebook or the active call of a fritzbox_phone entity, with play, delete and call back.",
    e_entity: "Entity",
    e_title: "Title (optional, default: entity name)",
    e_rows: "Number of rows",
    e_show_legend: "Show filter legend",
    e_show_stats: "Show today's summary",
    e_show_dial: "Show call back buttons",
    e_tam_entity:
      "Linked answering machine (optional) - shows its messages in the same card",
    e_mark_read_on_play: "Mark as read when played",
    e_tap_action: "Tapping a row",
    e_tap_expand: "Expand details",
    e_tap_more_info: "Open the entity",
  },
};

// The card follows Home Assistant's UI language; German and English are
// available, everything else falls back to English.
function makeTranslator(hass) {
  const raw = (hass && ((hass.locale && hass.locale.language) || hass.language)) || "en";
  const lang = String(raw).toLowerCase().startsWith("de") ? "de" : "en";
  const table = TEXTS[lang];
  const t = (key, vars) => {
    let text = table[key] ?? TEXTS.en[key] ?? key;
    if (vars) {
      for (const [name, value] of Object.entries(vars)) {
        text = text.split(`{${name}}`).join(String(value));
      }
    }
    return text;
  };
  t.lang = lang;
  return t;
}

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

  button:focus-visible,
  .fb-main[role="button"]:focus-visible,
  .fb-search:focus-visible {
    outline: 2px solid var(--primary-color); outline-offset: 2px;
  }
  .fb-progress { height: 6px; cursor: pointer; }
  .fb-stats { font-size: 12px; color: var(--secondary-text-color); margin: 0 0 8px; }

  .fb-search {
    width: 100%; box-sizing: border-box; font: inherit; font-size: 13px; padding: 8px 10px;
    margin: 0 0 8px; border-radius: 8px; border: 1px solid var(--divider-color);
    background: var(--card-background-color); color: var(--primary-text-color);
  }
  .fb-link-btn {
    display: inline-flex; align-items: center; gap: 4px; font: inherit; font-size: 11.5px;
    font-weight: 600; border: none; border-radius: 999px; padding: 4px 10px; margin-top: 4px;
    cursor: pointer; color: var(--primary-color);
    background: color-mix(in srgb, var(--primary-color) 14%, transparent);
  }
  .fb-link-btn:disabled { opacity: .5; cursor: default; }
  .fb-link-btn ha-icon { --mdc-icon-size: 14px; }
  .fb-contact .fb-numbers { display: flex; flex-direction: column; gap: 2px; margin-top: 2px; }
  .fb-number-line {
    display: flex; align-items: center; justify-content: space-between; gap: 8px;
    font-size: 11.5px; color: var(--secondary-text-color); font-variant-numeric: tabular-nums;
  }
  .fb-number-line .fb-link-btn { margin-top: 0; padding: 2px 8px; }
  .fb-pill-quiet {
    color: var(--secondary-text-color); background: var(--secondary-background-color);
  }
  .fb-more { padding: 8px 0 0; font-size: 12px; color: var(--secondary-text-color); }

  @media (prefers-reduced-motion: reduce) {
    .fb-cm-icon.fb-cm-ringing { animation: none; }
    .fb-chevron { transition: none; }
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

function pad2(value) {
  return String(value).padStart(2, "0");
}

function formatDateObj(dt, t) {
  const now = new Date();
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  const hhmm = `${pad2(dt.getHours())}:${pad2(dt.getMinutes())}`;
  if (isSameDay(dt, now)) return `${t("today")} ${hhmm}`;
  if (isSameDay(dt, yesterday)) return `${t("yesterday")} ${hhmm}`;
  const yy = String(dt.getFullYear()).slice(-2);
  return `${pad2(dt.getDate())}.${pad2(dt.getMonth() + 1)}.${yy} ${hhmm}`;
}

function formatClockTime(dt) {
  return `${pad2(dt.getHours())}:${pad2(dt.getMinutes())}`;
}

function formatDatum(value, t) {
  const dt = parseAvmDate(value);
  return dt ? formatDateObj(dt, t) : value || "";
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

// Only digits can be dialed; a caller "name" in the number slot cannot.
function dialableNumber(value) {
  const cleaned = String(value || "").replace(/[^\d+*#]/g, "");
  return /\d/.test(cleaned) ? cleaned : "";
}

function displayName(t, name, reverseName, number) {
  if (name) return name;
  if (reverseName) return reverseName;
  return number ? t("unknown_number", { number }) : t("unknown");
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

// Fallback for calls the integration could not link to a message by the shared
// recording path (older integration versions, or a box that words the two
// paths differently): match on caller number (tolerantly, see
// numbersLikelyMatch), then - if several messages came from that number - pick
// whichever is closest in time to the call. AVM's Date fields only have minute
// precision and the TAM records only after playing its announcement, so the
// call's and the message's Date commonly land in different minutes. `claimed`
// prevents the same message being linked to more than one call row.
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

// Everything shown in the card that originates from the call itself (caller
// name/number, device, third-party lookups) is attacker-controlled - a SIP
// display name is chosen by the caller - so it is only ever inserted as
// text, never parsed as HTML.
function textSpan(text) {
  const span = document.createElement("span");
  span.textContent = String(text);
  return span;
}

function metaLine(parts) {
  const meta = document.createElement("div");
  meta.className = "fb-meta";
  parts.filter(Boolean).forEach((part, index) => {
    if (index > 0) meta.appendChild(textSpan("·"));
    meta.appendChild(textSpan(part));
  });
  return meta;
}

function emptyNotice(text) {
  const box = document.createElement("div");
  box.className = "fb-empty";
  box.textContent = text;
  return box;
}

function haIcon(name, className) {
  const icon = document.createElement("ha-icon");
  icon.setAttribute("icon", name);
  if (className) icon.className = className;
  return icon;
}

function formatElapsed(seconds) {
  const s = Math.max(0, Math.floor(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  const ss = String(sec).padStart(2, "0");
  return h > 0 ? `${h}:${pad2(m)}:${ss}` : `${m}:${ss}`;
}

const CALLMONITOR_STATES = ["idle", "ringing", "dialing", "talking"];

const CALLMONITOR_VISUALS = {
  ringing: { icon: "mdi:phone-ring", cls: "fb-cm-ringing" },
  dialing: { icon: "mdi:phone-outgoing", cls: "fb-cm-dialing" },
  talking: { icon: "mdi:phone-in-talk", cls: "fb-cm-talking" },
  idle: { icon: "mdi:phone-hangup", cls: "" },
};

function spamDetailItems(t, entity) {
  const items = [];
  if (entity.spam_confidence != null) {
    items.push([t("d_spam_probability"), `${entity.spam_confidence}% (PhoneBlock)`]);
  }
  if (entity.spam_rating) {
    const known = `rating_${entity.spam_rating}`;
    items.push([t("d_rating"), TEXTS.en[known] ? t(known) : entity.spam_rating]);
  }
  if (entity.spam_location) {
    items.push([t("d_phoneblock_place"), entity.spam_location]);
  }
  return items;
}

function reverseDetailItems(t, entity) {
  const items = [];
  if (!entity.name && entity.reverse_name) {
    items.push([t("d_source"), t("source_tellows")]);
    if (entity.reverse_category) items.push([t("d_category"), entity.reverse_category]);
  }
  return items;
}

function callTypeLabel(t, type) {
  const key = `type_${type}`;
  return TEXTS.en[key] ? t(key) : type || "-";
}

function callDetails(t, call, tamMessage) {
  const items = [
    [t("d_call_type"), callTypeLabel(t, call.type)],
    [t("d_number"), callNumber(call) || "-"],
  ];
  if (call.date) items.push([t("d_begin"), formatDatum(call.date, t)]);
  if (call.type !== "missed") {
    const end = callEndTime(call);
    if (end) items.push([t("d_end"), formatDateObj(end, t)]);
    if (call.duration) items.push([t("d_duration"), call.duration]);
  }
  if (call.area_name) items.push([t("d_place"), call.area_name]);
  if (call.type === "outgoing") {
    const own = call.caller_number || call.caller;
    if (own) items.push([t("d_own_extension"), own]);
  } else {
    const own = call.called_number || call.called;
    if (own) items.push([t("d_own_number"), own]);
  }
  if (call.is_fax) items.push([t("d_fax"), t("yes")]);
  if (call.is_answering_machine) items.push([t("d_tam"), t("yes")]);
  if (tamMessage) {
    items.push([t("d_message"), tamMessage.new ? t("msg_new") : t("msg_read")]);
    items.push([t("d_in_phonebook"), tamMessage.in_phonebook ? t("yes") : t("no")]);
  }
  items.push(...spamDetailItems(t, call));
  items.push(...reverseDetailItems(t, call));
  return items;
}

function messageDetails(t, message) {
  const items = [
    [t("d_number"), message.number || "-"],
    [t("d_status"), message.new ? t("msg_new") : t("msg_read")],
  ];
  if (message.area_name) items.push([t("d_place"), message.area_name]);
  if (message.called) items.push([t("d_own_number"), message.called]);
  items.push([t("d_in_phonebook"), message.in_phonebook ? t("yes") : t("no")]);
  items.push(...spamDetailItems(t, message));
  items.push(...reverseDetailItems(t, message));
  return items;
}

function buildDetails(items) {
  const box = document.createElement("div");
  box.className = "fb-details";
  for (const [label, value] of items) {
    const line = document.createElement("div");
    const labelEl = document.createElement("b");
    labelEl.textContent = `${label}:`;
    line.appendChild(labelEl);
    line.appendChild(document.createTextNode(` ${value}`));
    box.appendChild(line);
  }
  return box;
}

function buildNameLine(t, text, isSpam) {
  const wrap = document.createElement("div");
  wrap.className = "fb-name-row";
  const name = document.createElement("span");
  name.className = "fb-name";
  name.textContent = text;
  wrap.appendChild(name);
  if (isSpam) {
    const badge = document.createElement("span");
    badge.className = "fb-spam-badge";
    badge.textContent = t("spam");
    wrap.appendChild(badge);
  }
  return wrap;
}

class FritzboxPhoneCard extends HTMLElement {
  constructor() {
    super();
    this._t = makeTranslator(null);
    // What the user is doing, kept across redraws (see _render).
    this._ui = { expanded: new Set(), confirming: new Set(), filters: null };
    this._search = "";
    // Audio lives outside the DOM so a redraw cannot interrupt it.
    this._players = new Map();
    this._rows = new Map();
  }

  static getStubConfig(hass) {
    const entity = Object.keys(hass.states || {}).find((id) => {
      if (!id.startsWith("sensor.")) return false;
      const attrs = hass.states[id].attributes || {};
      return (
        Array.isArray(attrs.calls) ||
        Array.isArray(attrs.messages) ||
        Array.isArray(attrs.contacts) ||
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
      throw new Error(makeTranslator(null)("choose_entity"));
    }
    this._config = {
      rows: DEFAULT_ROWS,
      mark_read_on_play: true,
      show_legend: true,
      show_stats: true,
      show_dial: true,
      tap_action: "expand",
      ...config,
    };
    this._lastStateObj = undefined;
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._t = makeTranslator(hass);
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

  // Sections-view sizing (Home Assistant 2024.11+).
  getGridOptions() {
    const entityId = this._config && this._config.entity;
    const stateObj = this._hass && entityId && this._hass.states[entityId];
    if (stateObj && CALLMONITOR_STATES.includes(stateObj.state)) {
      return { columns: 12, rows: 1, min_columns: 6, min_rows: 1 };
    }
    return { columns: 12, min_columns: 6, min_rows: 2 };
  }

  connectedCallback() {
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    // The call monitor's running timer is stopped on disconnect and has to
    // be rebuilt, even though the state itself did not change.
    this._lastStateObj = undefined;
    this._render();
  }

  disconnectedCallback() {
    this._stopCallMonitorTimer();
    // A card that left the page must not keep playing.
    for (const player of this._players.values()) player.pause();
    this._players.clear();
  }

  _stopCallMonitorTimer() {
    if (this._cmInterval) {
      clearInterval(this._cmInterval);
      this._cmInterval = null;
    }
  }

  _toast(message) {
    this.dispatchEvent(
      new CustomEvent("hass-notification", { detail: { message }, bubbles: true, composed: true })
    );
  }

  _entityKind(stateObj) {
    const attrs = (stateObj && stateObj.attributes) || {};
    if (Array.isArray(attrs.calls)) return "calls";
    if (Array.isArray(attrs.messages)) return "messages";
    if (Array.isArray(attrs.contacts)) return "phonebook";
    if (stateObj && CALLMONITOR_STATES.includes(stateObj.state)) return "monitor";
    return "unknown";
  }

  _render() {
    if (!this._hass || !this._config || !this.shadowRoot) return;
    const t = this._t;
    const entityId = this._config.entity;
    const stateObj = this._hass.states[entityId];
    const tamEntityId = this._config.tam_entity;
    const tamStateObj = tamEntityId ? this._hass.states[tamEntityId] : undefined;

    // Skip the redraw if neither this entity's nor the linked TAM entity's
    // state object (nor the language) changed.
    if (
      stateObj === this._lastStateObj &&
      tamStateObj === this._lastTamStateObj &&
      t.lang === this._lastLang
    ) {
      return;
    }
    this._lastStateObj = stateObj;
    this._lastTamStateObj = tamStateObj;
    this._lastLang = t.lang;
    this._stopCallMonitorTimer();
    this._rows = new Map();

    this.shadowRoot.replaceChildren();
    const style = document.createElement("style");
    style.textContent = STYLE_CSS;
    this.shadowRoot.appendChild(style);

    const card = document.createElement("ha-card");
    const attrs = (stateObj && stateObj.attributes) || {};
    const kind = this._entityKind(stateObj);
    const unavailable = !!stateObj && ["unavailable", "unknown"].includes(stateObj.state);
    const tamContext =
      kind === "calls" && tamStateObj && Array.isArray(tamStateObj.attributes.messages)
        ? {
            entityId: tamStateObj.entity_id,
            tamIndex: tamStateObj.attributes.tam_index,
            messages: tamStateObj.attributes.messages,
          }
        : null;

    const title =
      this._config.title || (stateObj && (attrs.friendly_name || entityId)) || entityId;
    const header = document.createElement("div");
    header.className = "fb-header";
    const h2 = document.createElement("h2");
    h2.textContent = title;
    header.appendChild(h2);
    if (!unavailable && (kind === "messages" || tamContext)) {
      // Same "X new" pill as the standalone answering machine card - counts
      // ALL new messages on the (linked) TAM entity, not just the ones that
      // happened to get matched to a currently-visible call row.
      const messages = kind === "messages" ? attrs.messages : tamContext.messages;
      const newCount = messages.filter((m) => m.new).length;
      const pill = document.createElement("span");
      pill.className = "fb-pill";
      pill.textContent = newCount > 0 ? t("n_new", { n: newCount }) : t("all_read");
      header.appendChild(pill);
    } else if (!unavailable && kind === "phonebook") {
      const pill = document.createElement("span");
      pill.className = "fb-pill fb-pill-quiet";
      pill.textContent = t("contacts_count", { n: attrs.contacts.length });
      header.appendChild(pill);
    }
    card.appendChild(header);

    const content = document.createElement("div");
    content.className = "fb-content";
    if (!stateObj) {
      content.appendChild(emptyNotice(t("entity_missing", { entity: entityId })));
    } else if (unavailable) {
      content.appendChild(emptyNotice(t("entity_unavailable", { entity: entityId })));
    } else if (kind === "calls") {
      content.appendChild(this._buildCallsList(attrs.calls, tamContext, entityId));
    } else if (kind === "messages") {
      content.appendChild(this._buildMessagesList(attrs.messages, entityId));
    } else if (kind === "phonebook") {
      content.appendChild(this._buildPhonebook(attrs.contacts, entityId));
    } else if (kind === "monitor") {
      content.appendChild(this._buildCallMonitor(stateObj));
    } else {
      content.appendChild(emptyNotice(t("wrong_entity")));
    }
    card.appendChild(content);
    this.shadowRoot.appendChild(card);
  }

  // ------------------------------------------------------------------
  // Shared row behaviour
  // ------------------------------------------------------------------

  // Makes the clickable part of a row reachable and operable by keyboard.
  _makeToggle(main, row, key, entityId) {
    main.setAttribute("role", "button");
    main.tabIndex = 0;
    main.setAttribute("aria-expanded", String(row.classList.contains("is-expanded")));
    const activate = () => {
      if (this._config.tap_action === "more-info") {
        this.dispatchEvent(
          new CustomEvent("hass-more-info", {
            detail: { entityId },
            bubbles: true,
            composed: true,
          })
        );
      } else {
        this._toggleExpanded(row, main, key);
      }
    };
    main.addEventListener("click", activate);
    main.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        activate();
      }
    });
  }

  _toggleExpanded(row, main, key) {
    const open = row.classList.toggle("is-expanded");
    if (open) this._ui.expanded.add(key);
    else this._ui.expanded.delete(key);
    main.setAttribute("aria-expanded", String(open));
  }

  _buildChevron(row, main, key) {
    const chevron = haIcon("mdi:chevron-down", "fb-chevron");
    chevron.setAttribute("aria-hidden", "true");
    chevron.addEventListener("click", () => this._toggleExpanded(row, main, key));
    return chevron;
  }

  _deviceId(entityId) {
    const entry = this._hass.entities && this._hass.entities[entityId];
    return entry ? entry.device_id : undefined;
  }

  // "Call back" - rings the phone chosen in the box's dial help first.
  _buildDialButton(number, entityId) {
    const t = this._t;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "fb-link-btn";
    button.appendChild(haIcon("mdi:phone-outgoing"));
    button.appendChild(textSpan(t("callback")));
    button.setAttribute("aria-label", `${t("callback")}: ${number}`);
    button.addEventListener("click", async (event) => {
      event.stopPropagation();
      button.disabled = true;
      try {
        const deviceId = this._deviceId(entityId);
        await this._hass.callService(
          "fritzbox_phone",
          "dial",
          { number },
          deviceId ? { device_id: deviceId } : undefined
        );
        this._toast(t("dial_started"));
      } catch (err) {
        this._toast(t("dial_failed", { error: (err && err.message) || err }));
      } finally {
        button.disabled = false;
      }
    });
    return button;
  }

  // ------------------------------------------------------------------
  // Call monitor
  // ------------------------------------------------------------------

  _buildCallMonitor(stateObj) {
    const t = this._t;
    const state = stateObj.state;
    const attrs = stateObj.attributes || {};
    const visuals = CALLMONITOR_VISUALS[state] || CALLMONITOR_VISUALS.idle;

    const wrap = document.createElement("div");
    wrap.className = `fb-cm${state === "idle" ? " fb-cm-idle" : ""}`;
    // Screen readers announce a call as it starts ringing.
    wrap.setAttribute("role", "status");
    wrap.setAttribute("aria-live", "polite");

    const iconEl = document.createElement("div");
    iconEl.className = `fb-cm-icon ${visuals.cls}`;
    iconEl.appendChild(haIcon(visuals.icon));
    wrap.appendChild(iconEl);

    const main = document.createElement("div");
    main.className = "fb-cm-main";

    if (state === "idle") {
      const stateLine = document.createElement("div");
      stateLine.className = "fb-cm-state";
      stateLine.textContent = t("cm_idle");
      main.appendChild(stateLine);

      // The last DISCONNECT keeps the previous call's context (see
      // callmonitor.py) - "with"/"to"/"from" cover talking->idle, an
      // unanswered outgoing call, and a missed incoming call respectively.
      const lastNumber = attrs.with || attrs.to || attrs.from;
      if (lastNumber) {
        const lastName = attrs.with_name || attrs.to_name || attrs.from_name;
        const nameRow = document.createElement("div");
        nameRow.className = "fb-cm-name-row";
        const nameEl = document.createElement("span");
        nameEl.className = "fb-cm-name";
        nameEl.textContent = t("last_call", {
          name: displayName(t, lastName, attrs.reverse_name, lastNumber),
        });
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
      reverseName = attrs.reverse_name;
      number = attrs.with;
      timestampKey = "accepted";
    }

    const nameRow = document.createElement("div");
    nameRow.className = "fb-cm-name-row";
    const nameEl = document.createElement("span");
    nameEl.className = "fb-cm-name";
    nameEl.textContent = displayName(t, name, reverseName, number);
    nameRow.appendChild(nameEl);
    if (attrs.vip) {
      const vipBadge = document.createElement("span");
      vipBadge.className = "fb-vip-badge";
      vipBadge.textContent = t("vip");
      nameRow.appendChild(vipBadge);
    }
    if (attrs.is_spam) {
      const spamBadge = document.createElement("span");
      spamBadge.className = "fb-spam-badge";
      spamBadge.textContent = t("spam");
      nameRow.appendChild(spamBadge);
    }
    main.appendChild(nameRow);

    const stateLine = document.createElement("div");
    stateLine.className = `fb-cm-state fb-cm-state-${state}`;
    stateLine.textContent = t(`cm_${state}`);
    main.appendChild(stateLine);

    const meta = metaLine([attrs.area_name].filter(Boolean));
    if (timestampKey && attrs[timestampKey]) {
      if (meta.childElementCount > 0) meta.appendChild(textSpan("·"));
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

  // ------------------------------------------------------------------
  // Call list
  // ------------------------------------------------------------------

  _callKey(entityId, call) {
    return `${entityId}|call|${call.id || `${call.date}|${callNumber(call)}`}`;
  }

  // The message holding a call's recording: exact via the recording path the
  // integration matched, else the number/time heuristic.
  _messageForCall(call, tamContext, claimed) {
    if (!tamContext || !call.is_answering_machine) return null;
    const sameMachine =
      call.tam_index == null ||
      tamContext.tamIndex == null ||
      call.tam_index === tamContext.tamIndex;
    if (call.tam_message_index != null && sameMachine) {
      const exact = tamContext.messages.find((m) => m.index === call.tam_message_index);
      if (exact) {
        claimed.add(exact.index);
        return exact;
      }
    }
    return findMatchingTamMessage(call, tamContext.messages, claimed);
  }

  _buildCallsList(calls, tamContext, entityId) {
    const t = this._t;
    const body = document.createElement("div");
    body.className = "fb-calls-body";
    const allTypes = ["fb-out", "fb-in", "fb-miss", ...(tamContext ? ["fb-ab"] : [])];
    if (!this._ui.filters) this._ui.filters = new Set(allTypes);
    const activeTypes = this._ui.filters;
    // The AB filter appears once an answering machine is known; switch it on
    // only that first time so the user can still turn it off.
    if (tamContext && !this._ui.abFilterSeen) {
      this._ui.abFilterSeen = true;
      activeTypes.add("fb-ab");
    }

    const list = document.createElement("div");
    list.className = "fb-list";

    if (this._config.show_stats !== false && calls.length > 0) {
      const today = new Date();
      const todays = calls.filter((c) => {
        const dt = parseAvmDate(c.date);
        return dt && isSameDay(dt, today);
      });
      if (todays.length > 0) {
        const stats = document.createElement("div");
        stats.className = "fb-stats";
        stats.textContent = t("stats", {
          calls: todays.length,
          missed: todays.filter((c) => c.type === "missed").length,
        });
        body.appendChild(stats);
      }
    }
    if (this._config.show_legend !== false) {
      body.appendChild(
        this._buildLegend(activeTypes, () => this._applyCallFilter(list, activeTypes), !!tamContext)
      );
    }
    body.appendChild(list);

    if (calls.length === 0) {
      list.appendChild(emptyNotice(t("no_calls")));
      return body;
    }

    // Each matched TAM message can only be linked to one call row.
    const claimedMessages = tamContext ? new Set() : null;
    for (const call of calls) {
      const tamMessage = this._messageForCall(call, tamContext, claimedMessages);
      list.appendChild(
        this._buildCallRow(call, entityId, tamMessage ? tamContext.entityId : null, tamMessage)
      );
    }

    const filterEmpty = emptyNotice(t("no_filter_match"));
    filterEmpty.classList.add("fb-filter-empty");
    filterEmpty.style.display = "none";
    list.appendChild(filterEmpty);

    this._applyCallFilter(list, activeTypes);
    return body;
  }

  _buildCallRow(call, entityId, tamEntityId, tamMessage) {
    const t = this._t;
    const visuals = callVisuals(call);
    // A call that went to the answering machine gets its own filter/color
    // category ("AB"), same idea as "Missed" already being its own category
    // instead of just staying tagged "Incoming".
    const cls = tamMessage ? "fb-ab" : visuals.cls;
    const icon = tamMessage ? "mdi:voicemail" : visuals.icon;
    const key = tamMessage ? this._messageKey(tamEntityId, tamMessage) : this._callKey(entityId, call);

    const row = document.createElement("div");
    row.className = `fb-row ${cls}${tamMessage ? " fb-vm" : ""}${
      tamMessage && tamMessage.new ? " is-new" : ""
    }${this._ui.expanded.has(key) ? " is-expanded" : ""}`;
    row.dataset.type = cls;
    row.dataset.key = key;

    const iconEl = document.createElement("div");
    iconEl.className = `fb-icon ${cls}`;
    iconEl.appendChild(haIcon(icon));
    row.appendChild(iconEl);

    const main = document.createElement("div");
    main.className = "fb-main";
    main.appendChild(
      buildNameLine(
        t,
        displayName(t, call.name, call.reverse_name, callNumber(call)),
        call.is_spam
      )
    );
    main.appendChild(
      metaLine([
        formatDatum(call.date, t),
        call.device,
        call.type !== "missed" ? call.duration : null,
      ])
    );
    row.appendChild(main);
    this._makeToggle(main, row, key, entityId);
    const chevron = this._buildChevron(row, main, key);

    if (tamMessage) {
      // Play/Delete sit next to the chevron in the same row-end area, so
      // both the expand affordance and the AB controls stay available.
      const endWrap = document.createElement("div");
      endWrap.className = "fb-row-end";
      row.appendChild(endWrap);
      this._appendTamActions(row, tamEntityId, tamMessage, key, endWrap);
      endWrap.appendChild(chevron);
    } else {
      row.appendChild(chevron);
    }

    const details = buildDetails(callDetails(t, call, tamMessage));
    const number = dialableNumber(callNumber(call));
    if (this._config.show_dial !== false && number && !call.is_fax) {
      details.appendChild(this._buildDialButton(number, entityId));
    }
    row.appendChild(details);
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
    const t = this._t;
    const legend = document.createElement("div");
    legend.className = "fb-legend";
    const types = [
      { cls: "fb-out", label: t("legend_out") },
      { cls: "fb-in", label: t("legend_in") },
      { cls: "fb-miss", label: t("legend_miss") },
    ];
    if (includeAb) types.push({ cls: "fb-ab", label: t("legend_ab") });
    for (const type of types) {
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = `fb-legend-item ${type.cls}`;
      const active = activeTypes.has(type.cls);
      chip.classList.toggle("inactive", !active);
      chip.setAttribute("aria-pressed", String(active));
      chip.appendChild(document.createElement("i"));
      chip.appendChild(document.createTextNode(type.label));
      chip.addEventListener("click", () => {
        const nowInactive = chip.classList.toggle("inactive");
        chip.setAttribute("aria-pressed", String(!nowInactive));
        if (nowInactive) activeTypes.delete(type.cls);
        else activeTypes.add(type.cls);
        onChange();
      });
      legend.appendChild(chip);
    }
    return legend;
  }

  // ------------------------------------------------------------------
  // Answering machine
  // ------------------------------------------------------------------

  // Messages are renumbered by the box when one is deleted, so the index is
  // no identity; date and caller are.
  _messageKey(entityId, message) {
    return `${entityId}|msg|${message.date}|${message.number}`;
  }

  _buildMessagesList(messages, entityId) {
    const t = this._t;
    const rows = messages.slice(0, this._config.rows);
    const list = document.createElement("div");
    list.className = "fb-list";

    if (rows.length === 0) {
      list.appendChild(emptyNotice(t("no_messages")));
      return list;
    }
    for (const message of rows) {
      list.appendChild(this._buildMessageRow(message, entityId));
    }
    return list;
  }

  _buildMessageRow(message, entityId) {
    const t = this._t;
    const key = this._messageKey(entityId, message);
    const row = document.createElement("div");
    row.className =
      "fb-row fb-vm" + (message.new ? " is-new" : "") + (this._ui.expanded.has(key) ? " is-expanded" : "");
    row.dataset.key = key;

    const iconEl = document.createElement("div");
    iconEl.className = "fb-icon";
    iconEl.appendChild(haIcon("mdi:voicemail"));
    row.appendChild(iconEl);

    const main = document.createElement("div");
    main.className = "fb-main";
    main.appendChild(
      buildNameLine(
        t,
        displayName(t, message.name, message.reverse_name, message.number),
        message.is_spam
      )
    );
    main.appendChild(metaLine([formatDatum(message.date, t), message.duration]));
    row.appendChild(main);
    this._makeToggle(main, row, key, entityId);

    this._appendTamActions(row, entityId, message, key);
    const details = buildDetails(messageDetails(t, message));
    const number = dialableNumber(message.number);
    if (this._config.show_dial !== false && number) {
      details.appendChild(this._buildDialButton(number, entityId));
    }
    row.appendChild(details);
    return row;
  }

  _getPlayer(key) {
    let player = this._players.get(key);
    if (!player) {
      player = new Audio();
      player.preload = "none";
      for (const name of ["play", "pause", "ended", "timeupdate", "loadedmetadata"]) {
        player.addEventListener(name, () => this._syncPlayerUi(key));
      }
      this._players.set(key, player);
    }
    return player;
  }

  _syncPlayerUi(key) {
    const player = this._players.get(key);
    const row = this._rows.get(key);
    if (player && row && row.isConnected) this._applyPlayerUi(row, player);
  }

  _applyPlayerUi(row, player) {
    const t = this._t;
    const playing = !player.paused && !player.ended;
    row.classList.toggle("is-playing", playing);
    const percent = player.duration ? (player.currentTime / player.duration) * 100 : 0;
    const bar = row.querySelector(".fb-progress > span");
    if (bar) bar.style.width = `${percent}%`;
    const progress = row.querySelector(".fb-progress");
    if (progress) progress.setAttribute("aria-valuenow", String(Math.round(percent)));
    const playBtn = row.querySelector(".fb-play");
    if (playBtn) {
      const label = playing ? t("pause") : t("play");
      playBtn.setAttribute("aria-label", label);
      playBtn.title = label;
      playBtn.setAttribute("aria-pressed", String(playing));
    }
  }

  // Play/Delete buttons, playback progress bar and delete-confirm box -
  // shared between a standalone TAM message row and a call-list row for a
  // call that went to the answering machine (linked via the card's optional
  // `tam_entity` option). `actionsContainer` lets the play/delete buttons land
  // in a different element than `row` itself (the merged call-row view groups
  // them with the chevron in a small end-of-row wrapper).
  _appendTamActions(row, entityId, message, key, actionsContainer) {
    const t = this._t;
    this._rows.set(key, row);
    const player = this._getPlayer(key);

    const actions = document.createElement("div");
    actions.className = "fb-actions";

    const playBtn = document.createElement("button");
    playBtn.type = "button";
    playBtn.className = "fb-btn fb-play";
    playBtn.appendChild(haIcon("mdi:play", "icon-play"));
    playBtn.appendChild(haIcon("mdi:pause", "icon-pause"));

    const delBtn = document.createElement("button");
    delBtn.type = "button";
    delBtn.className = "fb-btn fb-del";
    delBtn.title = t("delete");
    delBtn.setAttribute("aria-label", t("delete"));
    delBtn.appendChild(haIcon("mdi:trash-can-outline"));

    actions.appendChild(playBtn);
    actions.appendChild(delBtn);
    (actionsContainer || row).appendChild(actions);

    const progress = document.createElement("div");
    progress.className = "fb-progress";
    progress.setAttribute("role", "progressbar");
    progress.setAttribute("aria-label", t("seek"));
    progress.setAttribute("aria-valuemin", "0");
    progress.setAttribute("aria-valuemax", "100");
    progress.appendChild(document.createElement("span"));
    progress.addEventListener("click", (event) => {
      if (!player.duration) return;
      const box = progress.getBoundingClientRect();
      player.currentTime = ((event.clientX - box.left) / box.width) * player.duration;
    });
    row.appendChild(progress);

    const confirm = document.createElement("div");
    confirm.className = "fb-confirm";
    confirm.setAttribute("role", "alertdialog");
    confirm.setAttribute("aria-label", t("confirm_delete"));
    confirm.appendChild(textSpan(t("confirm_delete")));
    const buttons = document.createElement("span");
    const no = document.createElement("button");
    no.type = "button";
    no.className = "fb-confirm-no";
    no.textContent = t("cancel");
    const yes = document.createElement("button");
    yes.type = "button";
    yes.className = "fb-confirm-yes";
    yes.textContent = t("delete");
    buttons.appendChild(no);
    buttons.appendChild(yes);
    confirm.appendChild(buttons);
    row.appendChild(confirm);
    if (this._ui.confirming.has(key)) row.classList.add("is-confirming");

    this._applyPlayerUi(row, player);

    playBtn.addEventListener("click", () => this._handlePlay(entityId, message, key, playBtn));
    delBtn.addEventListener("click", () => {
      row.classList.add("is-confirming");
      this._ui.confirming.add(key);
      yes.focus();
    });
    no.addEventListener("click", () => {
      row.classList.remove("is-confirming");
      this._ui.confirming.delete(key);
      delBtn.focus();
    });
    yes.addEventListener("click", () => this._handleDelete(entityId, message, key, row));
  }

  async _handlePlay(entityId, message, key, playBtn) {
    const t = this._t;
    const player = this._getPlayer(key);
    if (!player.paused) {
      player.pause();
      return;
    }
    if (!message.recording_path) {
      this._toast(t("no_recording"));
      return;
    }
    for (const other of this._players.values()) {
      if (other !== player) other.pause();
    }
    playBtn.disabled = true;
    try {
      // The recording is streamed from the box by the integration, behind
      // Home Assistant's login. A plain <audio> element cannot send the
      // auth header, so it gets a short-lived signed URL instead.
      if (
        !player.src ||
        !player._signedAt ||
        player._path !== message.recording_path ||
        Date.now() - player._signedAt > SIGN_REUSE_MS
      ) {
        const signed = await this._hass.callWS({
          type: "auth/sign_path",
          path: message.recording_path,
          expires: SIGN_EXPIRES_SECONDS,
        });
        player.src = signed.path;
        player._signedAt = Date.now();
        player._path = message.recording_path;
      }
      await player.play();
      if (this._config.mark_read_on_play !== false && message.new) {
        this._hass
          .callService("fritzbox_phone", "mark_message_read", {
            entity_id: entityId,
            message_index: message.index,
            read: true,
          })
          .catch(() => {});
      }
    } catch (err) {
      this._toast(t("err_load", { error: (err && err.message) || err }));
    } finally {
      playBtn.disabled = false;
    }
  }

  async _handleDelete(entityId, message, key, row) {
    const t = this._t;
    try {
      await this._hass.callService("fritzbox_phone", "delete_message", {
        entity_id: entityId,
        message_index: message.index,
      });
      const player = this._players.get(key);
      if (player) {
        player.pause();
        this._players.delete(key);
      }
      this._ui.confirming.delete(key);
      this._ui.expanded.delete(key);
      row.remove();
    } catch (err) {
      row.classList.remove("is-confirming");
      this._ui.confirming.delete(key);
      this._toast(t("err_delete", { error: (err && err.message) || err }));
    }
  }

  // ------------------------------------------------------------------
  // Phonebook
  // ------------------------------------------------------------------

  _buildPhonebook(contacts, entityId) {
    const t = this._t;
    const body = document.createElement("div");
    body.className = "fb-phonebook";

    const input = document.createElement("input");
    input.type = "search";
    input.className = "fb-search";
    input.placeholder = t("search");
    input.setAttribute("aria-label", t("search"));
    input.value = this._search;
    body.appendChild(input);

    const list = document.createElement("div");
    list.className = "fb-list";
    body.appendChild(list);

    const sorted = [...contacts].sort((a, b) =>
      String(a.name).localeCompare(String(b.name), this._t.lang)
    );
    const renderList = () => {
      list.replaceChildren();
      const query = this._search.trim().toLowerCase();
      const queryDigits = query.replace(/\D/g, "");
      const matches = sorted.filter(
        (contact) =>
          !query ||
          String(contact.name).toLowerCase().includes(query) ||
          (queryDigits.length > 0 &&
            contact.numbers.some((n) => normalizeNumberForMatch(n.number).includes(queryDigits)))
      );
      if (matches.length === 0) {
        list.appendChild(emptyNotice(contacts.length === 0 ? t("no_contacts") : t("no_matches")));
        return;
      }
      const shown = matches.slice(0, this._config.rows);
      for (const contact of shown) list.appendChild(this._buildContactRow(contact, entityId));
      if (matches.length > shown.length) {
        const more = document.createElement("div");
        more.className = "fb-more";
        more.textContent = t("more_contacts", { n: matches.length - shown.length });
        list.appendChild(more);
      }
    };
    input.addEventListener("input", () => {
      this._search = input.value;
      renderList();
    });
    renderList();
    return body;
  }

  _buildContactRow(contact, entityId) {
    const row = document.createElement("div");
    row.className = "fb-row fb-contact";

    const iconEl = document.createElement("div");
    iconEl.className = "fb-icon";
    iconEl.appendChild(haIcon(contact.vip ? "mdi:star" : "mdi:account"));
    row.appendChild(iconEl);

    const main = document.createElement("div");
    main.className = "fb-main";
    const nameRow = document.createElement("div");
    nameRow.className = "fb-name-row";
    const name = document.createElement("span");
    name.className = "fb-name";
    name.textContent = contact.name;
    nameRow.appendChild(name);
    if (contact.vip) {
      const badge = document.createElement("span");
      badge.className = "fb-vip-badge";
      badge.textContent = this._t("vip");
      nameRow.appendChild(badge);
    }
    main.appendChild(nameRow);

    const numbers = document.createElement("div");
    numbers.className = "fb-numbers";
    for (const entry of contact.numbers) {
      const line = document.createElement("div");
      line.className = "fb-number-line";
      line.appendChild(textSpan(entry.type ? `${entry.type}: ${entry.number}` : entry.number));
      const dialable = dialableNumber(entry.number);
      if (this._config.show_dial !== false && dialable) {
        line.appendChild(this._buildDialButton(dialable, entityId));
      }
      numbers.appendChild(line);
    }
    main.appendChild(numbers);
    row.appendChild(main);
    return row;
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

  // Only the options that mean something for the chosen entity are offered.
  _kind() {
    const stateObj = this._hass && this._config && this._hass.states[this._config.entity];
    const attrs = (stateObj && stateObj.attributes) || {};
    if (Array.isArray(attrs.calls)) return "calls";
    if (Array.isArray(attrs.messages)) return "messages";
    if (Array.isArray(attrs.contacts)) return "phonebook";
    if (stateObj && CALLMONITOR_STATES.includes(stateObj.state)) return "monitor";
    return "unknown";
  }

  _schema() {
    const t = makeTranslator(this._hass);
    const ownEntities = { entity: { domain: "sensor", integration: "fritzbox_phone" } };
    const kind = this._kind();
    const schema = [
      { name: "entity", selector: ownEntities },
      { name: "title", selector: { text: {} } },
    ];
    if (["calls", "messages", "phonebook"].includes(kind)) {
      schema.push({ name: "rows", selector: { number: { min: 1, max: 50, mode: "box" } } });
    }
    if (kind === "calls") {
      schema.push(
        { name: "show_legend", selector: { boolean: {} } },
        { name: "show_stats", selector: { boolean: {} } },
        { name: "tam_entity", selector: ownEntities }
      );
    }
    if (kind === "messages") {
      schema.push({ name: "mark_read_on_play", selector: { boolean: {} } });
    }
    if (["calls", "messages", "phonebook"].includes(kind)) {
      schema.push({ name: "show_dial", selector: { boolean: {} } });
    }
    if (["calls", "messages"].includes(kind)) {
      schema.push({
        name: "tap_action",
        selector: {
          select: {
            mode: "dropdown",
            options: [
              { value: "expand", label: t("e_tap_expand") },
              { value: "more-info", label: t("e_tap_more_info") },
            ],
          },
        },
      });
    }
    return schema;
  }

  _render() {
    if (!this._hass || !this._config) return;
    const t = makeTranslator(this._hass);
    let form = this.querySelector("ha-form");
    if (!form) {
      this.replaceChildren();
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
      show_stats: true,
      show_dial: true,
      tap_action: "expand",
      ...this._config,
    };
    form.computeLabel = (schemaItem) => t(`e_${schemaItem.name}`);
  }
}

// The integration loads this file itself and an older setup may have added it
// as a dashboard resource too: defining the elements twice would throw.
if (!customElements.get(CARD_TAG)) {
  customElements.define(CARD_TAG, FritzboxPhoneCard);
  customElements.define(EDITOR_TAG, FritzboxPhoneCardEditor);
}

window.customCards = window.customCards || [];
if (!window.customCards.some((card) => card.type === CARD_TAG)) {
  // No hass object exists at load time; the browser language picks the text.
  const t = makeTranslator({ language: navigator.language });
  window.customCards.push({
    type: CARD_TAG,
    name: t("card_name"),
    description: t("card_description"),
    preview: true,
  });
}
