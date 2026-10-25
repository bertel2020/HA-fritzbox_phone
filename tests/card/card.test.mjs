import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import { JSDOM } from "jsdom";

const here = dirname(fileURLToPath(import.meta.url));
const SOURCE = readFileSync(
  process.env.CARD_FILE ||
    join(here, "../../custom_components/fritzbox_phone/www/fritzbox-phone-card.js"),
  "utf-8"
);

// A stand-in for <audio>: remembers what happened to it, plays instantly.
class FakeAudio extends EventTarget {
  constructor() {
    super();
    this.paused = true;
    this.ended = false;
    this.duration = 10;
    this.currentTime = 0;
    this.src = "";
    FakeAudio.instances.push(this);
  }
  async play() {
    this.paused = false;
    this.dispatchEvent(new Event("play"));
  }
  pause() {
    if (this.paused) return;
    this.paused = true;
    this.dispatchEvent(new Event("pause"));
  }
}
FakeAudio.instances = [];

function load() {
  const dom = new JSDOM("<!doctype html><body></body>", { runScripts: "outside-only", pretendToBeVisual: true });
  const { window } = dom;
  window.Audio = FakeAudio;
  FakeAudio.instances = [];
  window.eval(SOURCE);
  return window;
}

function makeHass(states, extra = {}) {
  const calls = [];
  return {
    states,
    language: "en",
    locale: { language: "en" },
    entities: { "sensor.calls": { device_id: "dev1" } },
    calls,
    async callService(domain, service, data, target) {
      calls.push({ domain, service, data, target });
    },
    async callWS(msg) {
      calls.push({ ws: msg });
      return { path: `${msg.path}?authSig=abc` };
    },
    ...extra,
  };
}

function state(entityId, value, attributes = {}) {
  return { entity_id: entityId, state: value, attributes: { friendly_name: entityId, ...attributes } };
}

function mount(window, config, hass) {
  const card = window.document.createElement("fritzbox-phone-card");
  window.document.body.appendChild(card);
  card.setConfig(config);
  card.hass = hass;
  return card;
}

const call = (id, extra = {}) => ({
  id,
  type: "incoming",
  name: null,
  caller_number: "030123456",
  called_number: "0301111",
  device: "Phone",
  date: "01.01.26 10:00",
  duration: "0:01",
  is_fax: false,
  is_answering_machine: false,
  ...extra,
});

const message = (index, extra = {}) => ({
  index,
  number: "030123456",
  date: `01.01.26 10:0${index}`,
  duration: "0:10",
  new: true,
  in_phonebook: false,
  recording_path: `/api/fritzbox_phone/recording/e1/0/${index}`,
  ...extra,
});

const root = (card) => card.shadowRoot;
const text = (card) => root(card).textContent;

test("caller data is rendered as text, never as markup", () => {
  const window = load();
  const evil = '<img src=x onerror="alert(1)"><script>alert(2)</script>';
  const hass = makeHass({
    "sensor.calls": state("sensor.calls", "1", {
      calls: [
        call("1", {
          name: evil,
          caller_number: evil,
          device: evil,
          area_name: evil,
          spam_location: evil,
          reverse_category: evil,
        }),
      ],
    }),
  });
  const card = mount(window, { entity: "sensor.calls" }, hass);
  assert.equal(root(card).querySelectorAll("img, script").length, 0);
  assert.ok(text(card).includes(evil));
});

test("redraws keep opened rows and legend filters", () => {
  const window = load();
  const calls = [call("1"), call("2", { type: "outgoing" })];
  const hass = makeHass({ "sensor.calls": state("sensor.calls", "2", { calls }) });
  const card = mount(window, { entity: "sensor.calls" }, hass);

  root(card).querySelector('.fb-row[data-type="fb-in"] .fb-main').click();
  root(card).querySelector(".fb-legend-item.fb-out").click();

  // Home Assistant delivers a new state object.
  card.hass = makeHass({ "sensor.calls": state("sensor.calls", "2", { calls: [...calls] }) });

  const incoming = root(card).querySelector('.fb-row[data-type="fb-in"]');
  assert.ok(incoming.classList.contains("is-expanded"));
  assert.equal(incoming.querySelector(".fb-main").getAttribute("aria-expanded"), "true");
  const outgoing = root(card).querySelector('.fb-row[data-type="fb-out"]');
  assert.ok(outgoing.classList.contains("fb-limit-hidden"));
  assert.equal(root(card).querySelector(".fb-legend-item.fb-out").getAttribute("aria-pressed"), "false");
});

test("rows can be operated with the keyboard", () => {
  const window = load();
  const hass = makeHass({ "sensor.calls": state("sensor.calls", "1", { calls: [call("1")] }) });
  const card = mount(window, { entity: "sensor.calls" }, hass);
  const main = root(card).querySelector(".fb-main");
  assert.equal(main.getAttribute("role"), "button");
  assert.equal(main.tabIndex, 0);
  main.dispatchEvent(new window.KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
  assert.equal(main.getAttribute("aria-expanded"), "true");
  main.dispatchEvent(new window.KeyboardEvent("keydown", { key: " ", bubbles: true }));
  assert.equal(main.getAttribute("aria-expanded"), "false");
});

test("audio keeps playing when the state is redrawn", async () => {
  const window = load();
  const messages = [message(1), message(2, { number: "030999" })];
  const first = makeHass({ "sensor.tam": state("sensor.tam", "2", { messages }) });
  const card = mount(window, { entity: "sensor.tam" }, first);

  root(card).querySelector(".fb-play").click();
  await new Promise((resolve) => setTimeout(resolve, 0));

  assert.equal(FakeAudio.instances.length, 2); // one player per message, none in the DOM
  const player = FakeAudio.instances[0];
  assert.equal(player.paused, false);
  assert.match(player.src, /authSig=abc$/);
  assert.ok(first.calls.some((c) => c.ws && c.ws.type === "auth/sign_path"));
  assert.ok(first.calls.some((c) => c.service === "mark_message_read"));

  // marking it read changes the state -> the card is redrawn
  const read = [message(1, { new: false }), message(2, { number: "030999" })];
  card.hass = makeHass({ "sensor.tam": state("sensor.tam", "1", { messages: read }) });

  assert.equal(player.paused, false, "playback must survive the redraw");
  assert.ok(root(card).querySelector(".fb-row.is-playing"));
  assert.equal(root(card).querySelector(".fb-play").getAttribute("aria-label"), "Pause");

  // pausing works on the redrawn button
  root(card).querySelector(".fb-play").click();
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.equal(player.paused, true);
  assert.equal(root(card).querySelector(".fb-row.is-playing"), null);
});

test("a message without a recording says so instead of failing", async () => {
  const window = load();
  const hass = makeHass({
    "sensor.tam": state("sensor.tam", "1", { messages: [message(1, { recording_path: null })] }),
  });
  const card = mount(window, { entity: "sensor.tam" }, hass);
  const notices = [];
  card.addEventListener("hass-notification", (e) => notices.push(e.detail.message));
  root(card).querySelector(".fb-play").click();
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.deepEqual(notices, ["This message has no recording."]);
});

test("delete asks first, then removes the row", async () => {
  const window = load();
  const hass = makeHass({ "sensor.tam": state("sensor.tam", "1", { messages: [message(1)] }) });
  const card = mount(window, { entity: "sensor.tam" }, hass);
  const row = root(card).querySelector(".fb-row");

  root(card).querySelector(".fb-del").click();
  assert.ok(row.classList.contains("is-confirming"));
  // a redraw while the question is open keeps it open
  const redrawn = makeHass({ "sensor.tam": state("sensor.tam", "1", { messages: [message(1)] }) });
  card.hass = redrawn;
  assert.ok(root(card).querySelector(".fb-row").classList.contains("is-confirming"));

  root(card).querySelector(".fb-confirm-yes").click();
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.ok(redrawn.calls.some((c) => c.service === "delete_message" && c.data.message_index === 1));
  assert.equal(root(card).querySelectorAll(".fb-row").length, 0);
});

test("a call is linked to its message by the integration's index", () => {
  const window = load();
  const calls = [
    call("1", { is_answering_machine: true, caller_number: "999", tam_index: 0, tam_message_index: 2 }),
  ];
  const messages = [message(1, { number: "999" }), message(2, { number: "000" })];
  const hass = makeHass({
    "sensor.calls": state("sensor.calls", "1", { calls }),
    "sensor.tam": state("sensor.tam", "2", { tam_index: 0, messages }),
  });
  const card = mount(window, { entity: "sensor.calls", tam_entity: "sensor.tam" }, hass);
  const row = root(card).querySelector(".fb-row");
  // message 2 is the exact match even though message 1 has the caller's number
  assert.ok(row.dataset.key.includes("01.01.26 10:02|000"));
  assert.match(text(card), /2 new/);
});

test("call back dials through the integration, targeted at the box", async () => {
  const window = load();
  const hass = makeHass({ "sensor.calls": state("sensor.calls", "1", { calls: [call("1")] }) });
  const card = mount(window, { entity: "sensor.calls" }, hass);
  const notices = [];
  card.addEventListener("hass-notification", (e) => notices.push(e.detail.message));

  root(card).querySelector(".fb-link-btn").click();
  await new Promise((resolve) => setTimeout(resolve, 0));
  // (round-tripped: the card's objects come from the jsdom realm)
  assert.deepEqual(JSON.parse(JSON.stringify(hass.calls[0])), {
    domain: "fritzbox_phone",
    service: "dial",
    data: { number: "030123456" },
    target: { device_id: "dev1" },
  });
  assert.equal(notices.length, 1);
});

test("the button says call back for callers and call again for outgoing calls", () => {
  const window = load();
  const calls = [call("1"), call("2", { type: "outgoing", called_number: "0301111", caller_number: "075271" })];
  const card = mount(
    window,
    { entity: "sensor.calls" },
    makeHass({ "sensor.calls": state("sensor.calls", "2", { calls }) }),
  );
  const label = (type) =>
    root(card).querySelector(`.fb-row[data-type="${type}"] .fb-link-btn`).textContent.trim();
  assert.equal(label("fb-in"), "Call back");
  assert.equal(label("fb-out"), "Call again");
});

test("no call back button for a caller without a dialable number", () => {
  const window = load();
  const hass = makeHass({
    "sensor.calls": state("sensor.calls", "1", {
      calls: [call("1", { caller_number: null, caller: "Anonymous" })],
    }),
  });
  const card = mount(window, { entity: "sensor.calls" }, hass);
  assert.equal(root(card).querySelector(".fb-link-btn"), null);
});

test("phonebook view searches by name and number", () => {
  const window = load();
  const contacts = [
    { name: "Anna", vip: false, numbers: [{ number: "030 123456", type: "home" }] },
    { name: "Bernd", vip: true, numbers: [{ number: "0171 999", type: "mobile" }] },
  ];
  const hass = makeHass({ "sensor.book": state("sensor.book", "2", { contacts }) });
  const card = mount(window, { entity: "sensor.book" }, hass);
  assert.equal(root(card).querySelectorAll(".fb-contact").length, 2);

  const input = root(card).querySelector(".fb-search");
  input.value = "bern";
  input.dispatchEvent(new window.Event("input"));
  assert.equal(root(card).querySelectorAll(".fb-contact").length, 1);
  assert.match(text(card), /Bernd/);

  input.value = "123456";
  input.dispatchEvent(new window.Event("input"));
  assert.match(text(card), /Anna/);

  input.value = "zzz";
  input.dispatchEvent(new window.Event("input"));
  assert.match(text(card), /No matches/);
});

test("texts follow the Home Assistant language", () => {
  const window = load();
  const states = { "sensor.calls": state("sensor.calls", "0", { calls: [] }) };
  const card = mount(window, { entity: "sensor.calls" }, makeHass(states));
  assert.match(text(card), /No calls/);
  card.hass = makeHass(states, { language: "de", locale: { language: "de" } });
  assert.match(text(card), /Keine Anrufe/);
});

test("an unavailable entity is reported, not drawn", () => {
  const window = load();
  const hass = makeHass({ "sensor.calls": state("sensor.calls", "unavailable") });
  const card = mount(window, { entity: "sensor.calls" }, hass);
  assert.match(text(card), /unavailable/);
});

test("the call monitor timer is rebuilt after the card was re-attached", () => {
  const window = load();
  const hass = makeHass({
    "sensor.cm": state("sensor.cm", "talking", { with: "030", accepted: new Date().toISOString() }),
  });
  const card = mount(window, { entity: "sensor.cm" }, hass);
  assert.ok(card._cmInterval);
  card.remove();
  assert.equal(card._cmInterval, null);
  window.document.body.appendChild(card);
  assert.ok(card._cmInterval, "timer must run again after re-attaching");
  card.remove();
});

test("the elements are only defined once", () => {
  const window = load();
  assert.doesNotThrow(() => window.eval(SOURCE));
  assert.equal(window.customCards.filter((c) => c.type === "fritzbox-phone-card").length, 1);
});

test("a player is signed again when the message behind it changed", async () => {
  const window = load();
  const first = makeHass({ "sensor.tam": state("sensor.tam", "1", { messages: [message(1)] }) });
  const card = mount(window, { entity: "sensor.tam" }, first);
  root(card).querySelector(".fb-play").click();
  await new Promise((resolve) => setTimeout(resolve, 0));
  const player = FakeAudio.instances[FakeAudio.instances.length - 1];
  player.pause();

  // The box renumbered its messages: same date and number, other index.
  const moved = makeHass({
    "sensor.tam": state("sensor.tam", "1", {
      messages: [message(1, { recording_path: "/api/fritzbox_phone/recording/e1/0/5" })],
    }),
  });
  card.hass = moved;
  root(card).querySelector(".fb-play").click();
  await new Promise((resolve) => setTimeout(resolve, 0));
  const paths = moved.calls.filter((c) => c.ws).map((c) => c.ws.path);
  assert.deepEqual(paths, ["/api/fritzbox_phone/recording/e1/0/5"]);
});

test("players and opened rows of vanished messages are dropped", async () => {
  const window = load();
  const both = [message(1), message(2, { number: "030999" })];
  const card = mount(
    window,
    { entity: "sensor.tam" },
    makeHass({ "sensor.tam": state("sensor.tam", "2", { messages: both }) }),
  );
  root(card).querySelector(".fb-row .fb-main").click();
  assert.equal(card._players.size, 2);
  assert.equal(card._ui.expanded.size, 1);

  card.hass = makeHass({ "sensor.tam": state("sensor.tam", "1", { messages: [both[1]] }) });
  assert.equal(card._players.size, 1);
  assert.equal(card._ui.expanded.size, 0);
});
