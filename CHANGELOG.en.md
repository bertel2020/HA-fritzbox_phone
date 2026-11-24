# Changelog

All notable changes to this integration are recorded here.

## 2.6.0 – 2026-11-24

### New

- New option "Per-number sensors" (off by default): with more than one own number, the
  other sensors are split per number as well, like the call list: **Call monitor**, **Ringing**, **Calls today**, **Missed calls**,
  **Talk time today**, **Unread messages** and, with PhoneBlock, **Spam calls today** and
  **Spam calls detected**. Each gets one extra sensor per number, named like the original
  plus the number (e.g. "Missed calls 030 1111"); the existing sensors are unchanged and
  still cover everything. The numbers are found in the call list, as for the call list.
  Unread messages are matched by the number the message was left on. Not tried on a box
  with several numbers.
- New option "Hide phones": hidden phones (e.g. FON sockets with nothing plugged in)
  are left out of the call back choices, `call_phone` and `dial_phones`.
- The card shows which phone a call is on, or last was on, in the call monitor view
  (attribute `phone`).
- New action `probe_phones` ("Read the phone data raw"): returns the box's raw answers
  to the phone requests, without passwords or SIP credentials. For diagnosis when a
  phone is shown wrongly (Developer tools → Actions).
- New action `call_phone` ("Call a phone"): places an internal call to one of the
  box's phones through the dial help (`target_phone`, e.g. "Mobilteil 1"). The dial
  help phone (or `phone`) rings first, and the target phone once you pick up. The box
  cannot ring a single phone without a far end. Not tried on a real FRITZ!Box.
- The call monitor now names the phone of a call (attribute `phone`): who picked up
  or which phone places the call. FON sockets, DECT handsets and IP phones are
  recognised; not tried on a real FRITZ!Box with every kind of phone.
- One sensor "... radio link" per DECT handset ("Active" while the handset has a radio
  link to the box, otherwise "Idle"; attributes `name`, `model`). The box only reports
  whether a radio link exists right now: a resting handset, especially with DECT Eco,
  shows "Idle" without being unreachable. The state is read on every poll.
- New selection "Phone for call backs" (configuration): sets the phone of the dial
  help that rings first, as under Telephony → Telephony devices on the box.

### Fixed

- The "Phones" sensor now reads what a real box returns: the dial help phones
  (numbering starts at 1), the IP phones with their numbers (name, outgoing and
  internal number) and only real handsets under DECT (no FRITZ!DECT sockets).
- The "Phones" sensor stayed unavailable when the box refused even one of the phone
  requests. Each group (dial help, DECT, IP phones) is now read on its own; what
  cannot be read stays empty.
- The telephone lines showed "Disconnected" although the provider had them
  registered: some boxes report the status as a number (`2` = registered) instead
  of a word. During a call the box reports `connected` or `3`; that counts as
  registered too, and the new attribute `in_use` shows the running call. Unknown
  statuses show as "Unknown" and are logged once.
- After a Home Assistant restart the "Call monitor" sensor was unavailable for as
  long as the first poll of the box took. The connection to the call monitor is now
  opened while that poll runs.

### Changed

- Lines now read "Registered" / "Not registered" instead of "Connected" / "Disconnected"; a number the box has switched off shows "Unknown".
- When reading the phones, forwarding rules, alarm clocks, telephone lines or the
  call barring fails, the log shows a warning with the error type once (before,
  only on debug level).
- The diagnostic sensors "Online reverse lookup" and "PhoneBlock" show "No lookup
  yet" before the first query instead of "Unknown".

## 2.5.0 – 2026-11-24

### New

- New sensor "Blocked numbers": count and list of the box's call barring
  (attributes `numbers`, `entries`). It appears only if the box offers call
  barring, and is read again every 15 minutes and after `block_number` and
  `unblock_number`.
- The card has the option "Phone for call backs": the call back button then rings
  exactly this phone (`dial` with `phone`) instead of the one set on the box. The
  choice comes from the "Phones" sensor.
- The answering machine sensor now also shows `mode`, `ring_seconds`,
  `phone_numbers` and `stick` (operating mode, after how many seconds it picks up,
  for which numbers it answers, where it stores). Read-only: the box cannot be
  changed for this through TR-064. Not tried on a real FRITZ!Box.
- The "Phones" sensor now also shows `internal_number` and `incoming_numbers` for
  IP phones: for which own numbers a phone rings (empty = all). Not tried on a
  real FRITZ!Box; the format of the list is checked for both known spellings.
- One switch "Alarm clock …" per alarm clock of the box (disabled by default; turn
  it on under Settings → Entities; attributes `time`, `weekdays`, `phone_name`).
  Switching was not tried on a real FRITZ!Box; the actions are present in a box's
  service description. The box offers no "Do not disturb" through TR-064.
- If the box has several phone numbers, there is one sensor "Call list …" per
  number with exactly the calls of that number (attributes `own_number` and
  `calls`).

## 2.4.0 – 2026-11-20

### New

- The action `dial` has an optional field `max_ring_seconds` (1–300): if nobody
  picks up in that time, the connection setup is cancelled automatically, like
  `fritz.dial`.
- The call forwarding switches now also show `outgoing` (which calls are
  forwarded) and `phonebook_id` as attributes.
- One sensor "Line …" per phone number of the box, showing whether the provider
  has registered it (attribute `status`). A failure of the telephone line is thus
  noticed. Not tried on a real FRITZ!Box.
- New sensor "Phones" (diagnostic): its attributes name the box's phones
  (`dial_phones`, `dect`, `ip`) and the one currently selected for the dial help
  (`dial_phone`). For this the action `dial` has the optional field `phone`: it
  rings the named phone for this one call; the box's setting is reset afterwards.
  Not tried on a real FRITZ!Box.
- New action `turn_on_for` for the answering machine and call forwarding
  switches: turns on for 1 to 1440 minutes and off again afterwards. The timer is
  stored and survives a restart of Home Assistant; turning off by hand cancels it.
- New blueprint `scheduled_forwarding.yaml`: turns a call forwarding on at one
  time and off at another, on selectable weekdays.
- English user guide (`docs/USER-GUIDE.en.md`), switching notes from the core
  integrations `fritz` and `fritzbox_callmonitor` in the readmes.

## 2.3.3 – 2026-11-17

### New

- New actions `update_contact` (change a contact's name, numbers, e-mail
  addresses and VIP flag) and `delete_contact`. `add_contact` now takes several
  numbers (`numbers`, each with a type, also `fax_work`), e-mail addresses
  (`emails`) and the VIP flag (`vip`). The contacts (attribute and websocket
  command `contacts`) now also show their e-mail addresses. All four actions were
  tried on a real FRITZ!Box. When a contact is changed, the box sometimes assigns
  a new `uniqueid`; anyone who stored an id permanently should re-read it from the
  `contacts` attribute after a change. `update_contact` and `delete_contact` may
  only be called by an administrator (automations without a user are allowed).

### Fixed

- A contact's e-mail addresses are read and written where AVM stores them
  (`telephony/services`); changing a contact keeps speed dial, vanity, door
  intercom and other number types (for example internal).
- If the box answers a write-back with a different id, it is first checked whether
  the old entry is still there: if it is gone, the box replaced it; if it is still
  there, it is deleted (if that fails, the new one is removed).
- `add_number_to_contact` rejected a contact that the box has but that was not yet
  in the most recently fetched phonebook ("is not in this phonebook"). The box is
  now asked for the entry itself.

## 2.3.2 – 2026-11-14

### Fixed

- The total spam counter no longer counts old calls again when the online lookup
  answers only later after a restart or failed briefly. All calls on the list at
  startup count as known.
- Reauth and reconfigure no longer fail with "different device" when the entry
  was created under the hostname (serial number was not readable).
- Reauth and reconfigure no longer reload the entry twice; this avoids an error
  from Home Assistant 2026.12.
- The box's session identifier (`sid`) no longer ends up in error messages and
  the log; the name of the lookup task no longer contains a phone number.
- The actions accept all targets of the target selector, including floors and
  labels.
- A recording download that is too slow aborts after 120 s instead of occupying
  the connection to the box permanently.
- The call monitor notices the silent reconnection by FritzMonitor; a hang-up
  missed in the process no longer leaves a call as "talking" permanently.
- An empty cache that was passed in was silently replaced by the lookup clients.

### Added

- Repair notice when the box's CallMonitor is unreachable after three attempts in
  a row (with the hint about `#96*5*`).
- The results of PhoneBlock and Tellows are kept across a restart (6 hours, in
  `.storage`, without failures). Spam threshold or country code changed: the
  stored PhoneBlock ratings are dropped.
- An action without a target names the available boxes when there are several.

## 2.3.1 – 2026-11-09

### Removed

- The action `download_message` is removed. It wrote recordings to
  `config/www/fritzbox_tam/`, and everything under `config/www` can be fetched at
  `/local/` without signing in. The card and `play_message` still play recordings
  signed in (signed addresses). Files already exported to
  `config/www/fritzbox_tam/` stay where they are and should be deleted.

## 2.3.0 – 2026-11-07

### Added

- Websocket API for panels (administrators only): `fritzbox_phone/entries`,
  `phonebooks`, `contacts`, `calls`, `tams`, `blocklist` and `stats` return
  entries, phonebooks, contacts, calls (with paging), answering machines, call
  barring and statistics, without the panel having to know entity ids or
  attribute names. The "Box > Phone" page of the `fritzbox_network` integration
  uses it. The option "Hide names and numbers" is passed along.
- Optional call history ("Keep call history on disk", days, 0 = off, at most 365):
  merges the call lists into a longer history for the statistics, without
  duplicates. Off by default; when on, the calls (numbers, names, times) are in
  `.storage` and therefore in backups. With 0 the stored history is deleted.
- New attributes: the call monitor sensor shows `call_list_days`,
  `call_list_max` and `call_history_days`, the phonebook `phonebook_id`, the
  answering machine switch `tam_index`.

- New action `add_number_to_contact`: adds another number to a contact in the
  phonebook (`contact_id`, `number`, optionally `number_type` and `phonebook_id`).
  The entry is read, extended and written back with its id so that nothing of the
  contact is lost. (Since 2.3.3: if the box gives the entry a new id in the
  process, that is fine; a second entry is cleaned up.)

### Changed

- Internal: the conversion of calls, contacts and messages is in `payloads.py` and
  is shared by the sensors and the websocket API. The sensors' attributes stay the
  same.
- The integration now depends on `websocket_api`.

### Documentation

- User guide: new sections "Call history (optional)" and "Websocket API for
  panels"; the readmes mention both.

## 2.2.0 – 2026-11-05

### Changed

- The diagnostic sensors "PhoneBlock" and "Online reverse lookup" are disabled by
  default on new installations. Existing installations keep them on; an outage
  still appears as a repair notice.

### Documentation

- User guide: new sections "Supported devices", "Data updates" and "Known
  limitations". The quality scale self-assessment thus covers all Gold rules.

## 2.1.1 – 2026-11-05

### Fixed

- Card: in the sections view the call monitor was cut to one row of height and
  covered by the card below it, so an ongoing call could not be seen. It now sets
  its height from its content.

## 2.1.0 – 2026-11-01

### Added

- Card: with the new option `show_manage`, an expanded row shows the buttons
  "Block" (with a confirmation) and "Add to phonebook" (asks for the name, only
  for callers without a name). Both use the actions `block_number` and
  `add_contact`. Off by default.
- Switches for the FRITZ!Box's call forwardings: every forwarding set up there
  appears as a switch ("Forwarding to …") and can be turned on and off, for
  example for "forward to the mobile at night" in an automation. A box without
  forwardings gets no switches. The ring lock is not reachable through the box's
  interface and is therefore not included.
- Action `add_contact`: creates a contact with name and number in the FRITZ!Box's
  phonebook (default: phonebook 0), for example for a caller who appears as
  unknown in the call list. Known numbers are rejected, also in another spelling.
  Afterwards the integration reloads the phonebooks at once instead of only after
  the update interval.
- Action `play_message`: plays an answering machine recording on a media player,
  for example to announce new messages in the living room. The recording is
  delivered through a signed address (valid for ten minutes); this needs an
  internal URL to be set in Home Assistant.
- Three more blueprints: "Action when the phone rings" (once per call, with
  optional pausing of media players), "Action when a VIP contact calls" and
  "Action on a new answering machine message".
- Sensors "Spam calls today" and "Detected spam calls" (only with PhoneBlock
  enabled). The second is a running counter for long-term statistics and survives
  restarts: it counts how many calls newly show up as spam, even if they have long
  since disappeared from the box's call list.
- Actions `block_number` and `unblock_number`: add a phone number to the
  FRITZ!Box's call barring or remove it (TR-064 `SetCallBarringEntry` and
  `DeleteCallBarringEntryUID`). A number that is already blocked is not added
  twice, also not in another spelling. Both appear in the logbook. The entry is a
  phonebook contact with the number; the integration's user account needs the
  right for telephony settings.
- Card: the daily summary can be switched between "Today", "7 days" and
  "30 days". For the longer periods it shows a bar per day, with missed calls
  marked in colour. What counts is what the FRITZ!Box still has in its call list.
  The line now also appears on a quiet day ("Today: no calls") as soon as there
  are calls in the last 30 days.
- Status sensors for PhoneBlock and the online reverse lookup (category
  diagnostic, only with the service enabled). Until now an outage or a wrong
  PhoneBlock password stayed invisible and looked like "no spam found". After
  three failed queries in a row the sensor is on `error`, and the log contains a
  warning once per outage (with a hint for rejected credentials). The diagnostics
  data also contains the status of the services, the last error of the box query
  and the call monitor's failed attempts - without phone numbers.
- Repair notice in Home Assistant when PhoneBlock rejects the login several times
  in a row (HTTP 401/403). It disappears as soon as a query succeeds again or the
  integration is unloaded. A mere outage of the service does not trigger it.
- Option "Hide names and numbers in the dashboard card" (default: off). The card
  then shows dots until a row is tapped; afterwards name and number are readable
  for 15 seconds. Applies to the call list, answering machine and phonebook, not
  to the call monitor. Can be overridden per card with `privacy` (`auto`, `on`,
  `off`). It is only a display option: sensor attributes, logbook and automations
  still contain the real data.
- Card: if the FRITZ!Box is unreachable and the sensors become "unavailable", the
  last list seen stays visible. A notice "Connection to the FRITZ!Box lost - as of
  …" shows how old it is. Without a list seen before, the message about the
  entity appears as before. Playing, deleting and calling back are locked in the
  meantime, with a hint in the tooltip; an open delete question closes.

### Fixed

- Card: the daily summary switches to the new day at midnight even if the sensor
  does not change. Until now it still showed the previous day after midnight until
  the next state change.
- Answering machine: playing, deleting and marking as read check the message
  before the action against the freshly loaded list by date and phone number
  (`message_key`). If the FRITZ!Box renumbers after a deletion, the action no
  longer hits a different message but is cancelled or follows the message to its
  new index. Without `message_key` the services behave as before.
- Card: on narrow cards and at 200 % zoom the buttons of the answering machine row
  covered the text; the rows now wrap.
- Card: contrast of "Call back", the spam label, "1 new" and the delete question
  raised to at least 4.5:1 (light and dark mode).
- Card: confirming "Delete" several times now sends only one request.
- Card: a failed mark-as-read after playing is reported.

### Changed

- Card: in the phonebook the button is called "Call" instead of "Call back", the
  option `show_dial` "Show call buttons".
- Card: the progress bar is a slider and can be operated by keyboard.
- Card: Esc closes the delete question, and after deleting the focus moves to the
  next row.
- Recordings are loaded only up to 25 MB (otherwise HTTP 413), at most two at a
  time.
- `download_message` writes a warning to the log that the file can be fetched at
  `/local/fritzbox_tam/` without signing in.

## 2.0.3 – 2026-10-31

### Fixed

- Card: answering machine messages that cannot be matched to an entry in the call
  list now appear as their own answering machine row and can therefore be played,
  even when "1 new" is shown.

### Changed

- Card: stronger status colours and darker legend text for better readability; the
  call monitor takes up less space when idle.

## 2.0.2 – 2026-10-25

### Changed

- Card: for outgoing calls the button is called "Call again" instead of "Call
  back" (German "Erneut anrufen").

## 2.0.1 – 2026-10-25

### Fixed

- Automatic discovery also offered FRITZ! repeaters, powerline adapters and other
  devices without a telephone part as "FRITZ!Box Phone". Such devices are now
  skipped (recognised by name and by the TR-064 services).

## 2.0.0 – 2026-10-25

> **Update note:** This version needs Home Assistant 2025.10 or newer and removes
> the attributes `recording_url`, `download_url` and `image_url`. Details under
> "Update notes".

### Security

- Dashboard card: caller data (name, phone number, device, results of
  Tellows/PhoneBlock) was inserted as HTML. Since a SIP display name is chosen by
  the caller, a crafted call could run script in the dashboard. Everything is now
  shown as text.
- The FRITZ!Box's session identifier (`sid=`) is no longer in entity attributes
  (`recording_url`, `download_url`, `image_url` are dropped, replaced by
  `has_recording`, `has_image`, `recording_path`) and therefore no longer in the
  database and backups.
- Recordings are no longer copied to `config/www` and delivered at `/local`
  without signing in, but streamed signed in by the integration
  (`/api/fritzbox_phone/recording/...`, the card uses signed addresses).
  `download_message` is deprecated and only accepts file names ending in `.wav`,
  `.mp3` or `.ogg`.
- Wrong credentials were accepted during setup; they now lead to "Sign-in failed".
- Passwords: the box password is a password field, the stored PhoneBlock password
  is no longer sent back to the browser.
- Tellows responses are parsed with `defusedxml` and limited to 64 KB.
- GitHub action `Release`: tag name and tag message no longer reach shell scripts
  directly; `hacs/action` is pinned to `22.5.0`.

### Fixed

- A failed query (timeout, box briefly gone) counted as "call list is empty":
  afterwards the integration reported all calls as removed and, on the next
  success, all as new. Errors now mean "update failed", the last data is kept.
- With the call monitor "ringing" appeared up to 16 s late because PhoneBlock and
  Tellows were queried first. The state appears at once, the enrichment follows.
- Simultaneous calls (call waiting) reset each other; each call is now tracked by
  its connection id.
- After a failed start or after exhausted reconnection attempts the call monitor
  gave up permanently; it now retries with growing intervals and is "unavailable"
  until then.
- Phone numbers from the own local area (without an area code) found neither a
  phonebook contact nor PhoneBlock/Tellows data; all numbers are now brought to
  E.164 uniformly, the box's area code is added.
- Card: playing a message aborted as soon as marking it as read changed the state;
  expanded rows and filters were lost with every update. The call monitor's timer
  stopped after the card was reattached. Errors appear as a notice instead of a
  dialog.
- The answering machine actions on a different sensor produced an
  `AttributeError`; they now answer with an understandable message. Errors from
  the box are reported as `HomeAssistantError`.
- Empty or faulty number fields in the box's XML responses no longer cause an
  error.

### Added

- Actions `fritzbox_phone.dial` (dial help), `fritzbox_phone.hangup` and
  `fritzbox_phone.lookup_number` (response with contact, place, spam and reverse
  lookup result).
- Entities: `event.*_call`, `binary_sensor.*_ringing`,
  `binary_sensor.*_unread_messages`, `sensor.*_calls_today`,
  `sensor.*_talk_time_today`.
- Discovery via SSDP, re-authentication (reauth) and reconfiguration (host, port,
  TLS, credentials) in the interface; diagnostics without credentials and phone
  numbers.
- Calls that went to the answering machine are matched through the message's
  shared recording file (`tam_index`, `tam_message_index`); matching by
  number/time remains the fallback.
- Card: phonebook view with search, "Call back" buttons, daily summary,
  `tap_action`, keyboard operation and labels for screen readers, German/English,
  adaptation to the sections view, editor with only the matching options; it is
  registered with Home Assistant by the integration itself (no dashboard resource
  needed any more).
- English translation (`translations/en.json`; `strings.json` is now the English
  base), icons in `icons.json`, real device info (model, serial number, firmware).
- Blueprints `notify_missed_call` and `spam_call_alert`.
- Tests (`pytest-homeassistant-custom-component`, card with jsdom) and the GitHub
  action `Tests`.

### Changed

- PhoneBlock/Tellows run asynchronously and in parallel over Home Assistant's
  shared HTTP session, with a time budget per query cycle (20 s, 5 s at startup).
  Caches have a size limit, failures are remembered for only 5 minutes (formerly
  6 hours).
- Phonebooks are loaded only every 15 minutes, the contact match uses an index.
- The country comes from the Home Assistant configuration; the option "Area code
  prefixes" remains as an override.
- New phonebooks and answering machines appear without a reload.
- The call monitor is an object of its own in the integration (no longer part of a
  sensor); its entities are "unavailable" as long as the connection is not up.
- The list attributes (`calls`, `contacts`, `messages`) are no longer stored in
  the recorder.
- Minimum Home Assistant version 2025.10; runtime data lives in
  `entry.runtime_data`.
- `numbers.py` is now `phone_numbers.py` (name clash with the standard library).

### Update notes

- Automations and templates that read `recording_url`, `download_url` or
  `image_url` from the attributes must be adapted (see "Security").
- Anyone using `download_message` and `/local/fritzbox_tam/...` should switch to
  the card or the signed-in address; the old files stay unchanged and can still
  be fetched without signing in.
- The entity ids of the phonebook, answering machine and switch entities stay
  (the unique ids do not change).

## 1.15.1 – 2026-10-07

### Fixed

- Removed `requests` from the `requirements` in `manifest.json`: Home Assistant
  ships the library itself, so Hassfest rejects the entry and the nightly
  validation run failed. The integration's behaviour does not change.

### Added

- GitHub action `Release`: pushing a `v*` tag creates the GitHub release
  automatically. The release notes come from the matching section of this file,
  the title from the annotation of the annotated tag. The workflow aborts if the
  tag and `version` in `manifest.json` do not match or the changelog section is
  missing; tags with a suffix (e.g. `v1.16.0-beta1`) are published as a
  pre-release.

### Changed

- Installation section in the readme switched to the My Home Assistant badges: one
  click opens the repository in HACS or starts the setup directly in your own Home
  Assistant instance.

## 1.15.0 – 2026-09-08

### Added

- **Plain-language reasons in the logbook.** The activity dialog of an entity
  used to show "No reason was recorded for this activity". All entities with
  notable activity now write their state in the context of an event of their own,
  which the new `logbook.py` translates into plain German - for example "Incoming
  call from Max Mustermann (+49301234567)" or "Call ended after 2:31". This
  covers the call monitor, call list, missed calls and the answering machine
  sensors.
- Four new events, also usable as automation triggers: `fritzbox_phone_call`,
  `fritzbox_phone_call_list_changed`, `fritzbox_phone_missed_call` and
  `fritzbox_phone_tam_message`. Besides the call data they contain
  `config_entry_id` and `host`, to filter with several FRITZ!Boxes.
- Change detection in the coordinator: new and removed calls and answering machine
  messages are compared from query to query. Messages are matched by timestamp and
  phone number instead of the message index, which the FRITZ!Box reassigns when
  deleting.

### Changed

- The call monitor no longer writes its state directly from the reading thread but
  hands the fully resolved event to the event loop. The blocking enrichment
  (PhoneBlock, Tellows) stays in the thread. This matches the thread-safety rules
  of current Home Assistant versions.

## 1.14.1

- State at the time the repository was published; older changes are not
  documented.
