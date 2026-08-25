# FRITZ!Box Telefon (custom_component)

Home-Assistant-Integration für **Telefonbuch**, **Anrufliste**,
**Anrufbeantworter** und **Echtzeit-Anrufstatus** einer FRITZ!Box – über
TR-064 (`X_AVM-DE_OnTel`, `X_AVM-DE_TAM`) und das CallMonitor-Protokoll
(Port 1012).

Schnittstellenbeschreibung: https://fritz.com/pages/schnittstellen
(TR-064_Contact_SCPD.pdf, TR-064_TAM.pdf).

> Dieser Ordner liegt nur lokal in diesem Repo – es wurden **keine
> Änderungen an einer laufenden Home-Assistant-Instanz vorgenommen**. Die
> Integration (bzw. Updates daran) muss manuell installiert werden.

## Inhalt

- [Voraussetzungen auf der FRITZ!Box](#voraussetzungen-auf-der-fritzbox)
- [Installation](#installation)
- [Optionen](#optionen)
- [Spam-Erkennung (PhoneBlock)](#spam-erkennung-phoneblock)
- [Rückwärtssuche (Tellows)](#rückwärtssuche-tellows)
- [Orts-/Länderkennung (offline)](#orts-länderkennung-offline)
- [Entitäten](#entitäten)
- [Services](#services)
- [Dashboard-Karte: fritzbox-phone-card](#dashboard-karte-fritzbox-phone-card)
- [Dateien](#dateien)
- [Hinweise](#hinweise)

## Voraussetzungen auf der FRITZ!Box

| # | Was | Wo |
|---|-----|----|
| 1 | TR-064 aktivieren | Heimnetz → Netzwerk → Netzwerkeinstellungen → „Zugriff für Anwendungen zulassen" |
| 2 | Benutzer mit Telefonie-Berechtigung | System → FRITZ!Box-Benutzer → Berechtigung „FRITZ!Box Einstellungen" |
| 3 | Mindestens ein eingerichteter Anrufbeantworter (nur für TAM-Sensoren nötig) | Telefonie → Anrufbeantworter |
| 4 | CallMonitor aktivieren (nur für den Anrufmonitor-Sensor nötig) | einmalig `#96*5*` von einem angeschlossenen Telefon wählen (`#96*4*` deaktiviert wieder) |

## Installation

1. Diesen Ordner (`fritzbox_phone`) nach
   `<HA-Konfigurationsverzeichnis>/custom_components/fritzbox_phone` kopieren
   (bei Updates: den kompletten Ordner überschreiben).
2. Home Assistant neu starten.
3. **Einstellungen → Geräte & Dienste → Integration hinzufügen** → „FRITZ!Box
   Telefon" suchen.
4. Host/IP, Benutzername und Kennwort eingeben. TLS ist optional; der Port
   wird automatisch anhand der TLS-Einstellung gewählt, kann aber
   überschrieben werden.

## Optionen

Über **Einstellungen → Geräte & Dienste → FRITZ!Box Telefon →
Konfigurieren** nachträglich änderbar:

| Option | Standard | Bedeutung |
|--------|----------|-----------|
| Abfrageintervall | 120 s | Polling-Takt für Telefonbuch/Anrufliste/Anrufbeantworter |
| Anruflisten-Zeitraum | 7 Tage | wie weit `sensor.*_anrufliste` zurückschaut |
| Maximale Anzahl Anrufe | 50 | Obergrenze der geladenen Anrufliste |
| Anrufmonitor aktivieren | an | schaltet `sensor.*_anrufmonitor` komplett ab/an |
| Anrufmonitor-Port | 1012 | CallMonitor-Port |
| Vorwahl-Präfixe | leer | kommagetrennt, z. B. `+49`; gleicht lokale und internationalisierte Rufnummern beim Anrufmonitor-Telefonbuchabgleich ab; erster Eintrag wird auch für die PhoneBlock-Nummernnormalisierung verwendet (Standard `+49`) |
| PhoneBlock aktivieren | aus | schaltet die Spam-Erkennung an/aus, siehe unten |
| PhoneBlock-Benutzername / -Kennwort | leer | Zugangsdaten eines kostenlosen Accounts auf [phoneblock.net](https://phoneblock.net) |
| Spam-Schwellwert | 50 % | ab welcher PhoneBlock-Spam-Wahrscheinlichkeit `is_spam` gesetzt wird |
| Online-Rückwärtssuche (Tellows) aktivieren | aus | schaltet die Namensauflösung unbekannter Nummern über Tellows an/aus, siehe unten |

## Spam-Erkennung (PhoneBlock)

Optionale, standardmäßig deaktivierte Anreicherung unbekannter Anrufer mit
einer Spam-Einschätzung von [PhoneBlock](https://phoneblock.net) (kostenlos,
Open Source, community-gepflegte Spam-Nummern-Datenbank, extra für
FRITZ!Box-Anwendungsfälle gebaut).

**Datenschutz:** Es wird **nie die Rufnummer selbst** an PhoneBlock
geschickt, sondern nur ihr SHA1-Hash (`GET /api/check?sha1=...`) – exakt so,
wie es PhoneBlocks eigener mobiler Client macht, und laut deren eigener
Dokumentation bewusst so gebaut, "ohne die Nummer preiszugeben". Angefragt
wird nur bei Anrufen/Nachrichten, die die FritzBox selbst keinem
Telefonbuch-Kontakt zuordnen konnte; Ergebnisse werden 6 Stunden lang lokal
zwischengespeichert, um nicht bei jedem Abfragezyklus erneut nachzufragen.

**Einrichten:**
1. Kostenlosen Account auf [phoneblock.net](https://phoneblock.net) anlegen.
2. Einstellungen → Geräte & Dienste → FRITZ!Box Telefon → Konfigurieren →
   „PhoneBlock-Spamerkennung aktivieren" + Benutzername/Kennwort eintragen.

**Was wird angereichert:** `sensor.*_anrufliste` (Einträge ohne
Telefonbuch-Namen), `sensor.*_<anrufbeantworter>` (Nachrichten ohne
Telefonbuch-Namen) sowie `sensor.*_anrufmonitor` bei eingehenden Anrufen
unbekannter Nummern – jeweils um `is_spam`, `spam_confidence` (0–100),
`spam_rating` (PhoneBlock-Einstufung wie `E_ADVERTISING`) und
`spam_location` (Ort, falls bekannt). Die `fritzbox-phone-card` zeigt dafür
automatisch ein rotes „Spam"-Badge neben dem Namen an.

Diese API liefert **keinen Namen** zu einer Nummer (nur Spam-Bewertung) –
für eine echte Namensauflösung siehe [Rückwärtssuche (Tellows)](#rückwärtssuche-tellows).

## Rückwärtssuche (Tellows)

Optionale, standardmäßig deaktivierte Namensauflösung unbekannter Anrufer
über [Tellows](https://www.tellows.de) – eine öffentliche, community-
gepflegte Anrufer-/Spam-Datenbank. Tellows bietet dafür eine kostenlos
nutzbare API **ohne Account/Login** (`GET /basic/num/{nummer}?xml=1`) – das
ist dieselbe Datenquelle, die AVM selbst für die eingebaute
Anrufererkennung mancher FRITZ!OS-Märkte lizenziert.

**Datenschutz:** Anders als bei der PhoneBlock-Spam-Erkennung wird hier die
**Rufnummer im Klartext** an Tellows geschickt – das ist der Zweck der
Rückwärtssuche und lässt sich technisch nicht vermeiden. Deshalb ist diese
Option bewusst **getrennt** von der PhoneBlock-Option und standardmäßig
deaktiviert. Angefragt wird nur bei Anrufen/Nachrichten ohne
Telefonbuch-Namen; Ergebnisse werden 6 Stunden lokal zwischengespeichert.

**Einrichten:** Einstellungen → Geräte & Dienste → FRITZ!Box Telefon →
Konfigurieren → „Online-Rückwärtssuche (Tellows) aktivieren". Kein Account
nötig.

**Was wird angereichert:** `sensor.*_anrufliste`, `sensor.*_<anrufbeantworter>`
und `sensor.*_anrufmonitor` (bei unbekannten eingehenden Anrufen) um
`reverse_name` und `reverse_category` (z. B. „Bestattungen", falls Tellows
das weiß). Die `fritzbox-phone-card` zeigt `reverse_name` direkt als Namen
an (statt „Unbekannt"), mit Quellenangabe „Tellows (Online-Rückwärtssuche)"
in den aufklappbaren Details, sobald kein Telefonbuch-Name vorliegt.

## Orts-/Länderkennung (offline)

Zusätzlich zur Namensauflösung zeigt jeder Anruf/jede Nachricht (in den
aufklappbaren Details der `fritzbox-phone-card`, Feld „Ort/Land") eine
Ortsangabe wie „Berlin" oder „Köln" bzw. bei internationalen Nummern das
Land. Das läuft **immer** und ganz ohne FritzBox- oder Internet-Abfrage:

TR-064 bietet dafür keine direkte Abfrage für beliebige Rufnummern –
geprüft wurde das gegen die Spezifikationen von `X_AVM-DE_OnTel` und
`X_AVM-DE_TAM`. Stattdessen nutzt die Integration
[`phonenumbers`](https://pypi.org/project/phonenumbers/) (die Python-Portierung
von Googles libphonenumber), die eine eigene Vorwahl-Datenbank mitbringt –
exakt die Art von Zuordnung, die auch die FritzBox-Weboberfläche selbst
lokal berechnet. Rein lokale Berechnung, keine Rufnummer verlässt den
Rechner. Für deutsche Mobilfunknummern liefert das nur "Deutschland"
(Mobilfunk-Vorwahlen sind nicht regional gebunden); für Festnetznummern
die Stadt/Region.

**Anrufe aus dem eigenen Ortsnetz:** Die FRITZ!Box meldet Rufnummern aus
ihrem eigenen lokalen Vorwahlbereich ohne jede Vorwahl (z. B. „954934"
statt „07527954934") – ohne Korrektur würde `phonenumbers` das falsch
oder unplausibel deuten (z. B. einen völlig falschen Ort raten). Die
Integration fragt dafür einmalig (und dann dauerhaft zwischengespeichert)
die eigene Vorwahl der Box über TR-064 ab (`X_VoIP` /
`X_AVM-DE_GetVoIPCommonAreaCode`) und ergänzt sie automatisch, wenn eine
Rufnummer ohne führende „0" bzw. „+" ankommt.

## Entitäten

| Entität | Zustand | Wichtigste Attribute |
|---------|---------|----------------------|
| `sensor.*_telefonbuch_<id>` (je Telefonbuch) | Anzahl Kontakte | `contacts`: Name, Rufnummern inkl. Typ, VIP-Flag, Bild-URL |
| `sensor.*_anrufliste` | Anzahl geladener Anrufe | `calls`: Typ, Name, Nummern, Datum, Dauer, Gerät/Port, Fax-/Anrufbeantworter-Flag, Aufnahme-URL, `area_name` (Ort/Land, offline), PhoneBlock-Spamfelder, `reverse_name`/`reverse_category` (Tellows, jeweils falls aktiviert) |
| `sensor.*_verpasste_anrufe` | Anzahl verpasster Anrufe | `calls`: nur verpasste Anrufe |
| `sensor.*_<anrufbeantworter>` (je TAM) | Anzahl neuer Nachrichten | `messages`: Anrufer, Datum, Dauer, gelesen/neu, Download-URL, `area_name` (Ort/Land, offline), PhoneBlock-Spamfelder, `reverse_name`/`reverse_category` (Tellows, jeweils falls aktiviert) |
| `switch.*_<anrufbeantworter>_aktiv` | an/aus | – |
| `sensor.*_anrufmonitor` | `idle` / `ringing` / `dialing` / `talking` | je nach Zustand `from`/`to`/`with`, `from_name`/`to_name`/`with_name`, `vip`, `area_name` (Ort/Land, offline), `device`, `duration`, bei unbekannten eingehenden Anrufen zusätzlich PhoneBlock-Spamfelder und `reverse_name`/`reverse_category` (Tellows, jeweils falls aktiviert); im Zustand `idle` bleiben die Felder des zuletzt beendeten Gesprächs erhalten, ergänzt um `initiated` (Klingel-/Wählbeginn), `accepted` (Annahmezeitpunkt), `started` (Gesprächsbeginn = `accepted`, falls vorhanden), `closed` (Auflegen), `duration_formatted` (exakte Gesprächsdauer inkl. Sekunden, z. B. `1:09:18`) und `ring_duration_formatted` (Klingeldauer bis zur Annahme, z. B. `0:11`, nur falls der Anruf angenommen wurde) |

Der Anrufmonitor-Sensor hält eine dauerhafte Socket-Verbindung zum
CallMonitor (Port 1012) und aktualisiert sich unabhängig vom
Abfrageintervall der anderen Sensoren in Echtzeit – Zustände und
Attributschema entsprechen dem Core-Sensor `fritzbox_callmonitor`, nutzt
aber die bereits konfigurierten Zugangsdaten und Telefonbücher dieser
Integration statt eines eigenen Config-Eintrags.

## Services

| Service | Zweck | Felder |
|---------|-------|--------|
| `fritzbox_phone.mark_message_read` | Anrufbeantworter-Nachricht als (un)gelesen markieren | `message_index`, `read` |
| `fritzbox_phone.delete_message` | Nachricht auf der Box löschen | `message_index` |
| `fritzbox_phone.download_message` | Sprachnachricht nach `config/www/fritzbox_tam/<Dateiname>` herunterladen (danach z. B. über `/local/fritzbox_tam/<Dateiname>` abspielbar) | `message_index`, `filename` |

Alle drei werden auf einer `sensor.*_<anrufbeantworter>`-Entität aufgerufen;
`message_index` steht im Attribut `messages` des jeweiligen Sensors.

## Dashboard-Karte: fritzbox-phone-card

Die Integration bringt eine eigene, native Lovelace-Karte als JS-Ressource
mit (`www/fritzbox-phone-card.js`, wird beim Setup automatisch unter
`/fritzbox_phone_static/fritzbox-phone-card.js` bereitgestellt). Sie
erkennt anhand der Entität automatisch, ob es sich um eine Anrufliste
(`calls`-Attribut), einen Anrufbeantworter (`messages`-Attribut) oder den
Anrufmonitor (Zustand `idle`/`ringing`/`dialing`/`talking`) handelt, und
rendert die passende Ansicht. Anrufliste und Anrufbeantworter teilen sich
dabei denselben Zeilenaufbau (Icon | Name + Datum [· Endgerät nur bei der
Anrufliste] · Dauer | ggf. Abspielen/Löschen). Bei unbekannten Anrufern
erscheint die Rufnummer in Klammern hinter „Unbekannt" (z. B. „Unbekannt
(030123456)"); ist ein Name bekannt, steht die Rufnummer nur noch in den
aufklappbaren Details einer Zeile. Play/Löschen rufen dabei Services ganz
regulär über `this.hass.callService(...)` auf.

**Aktiver Anruf:** Zeigt die Karte auf `sensor.*_anrufmonitor`, rendert sie
statt einer Liste eine einzelne, groß hervorgehobene Zeile mit dem aktuell
laufenden Anruf – Name/Nummer (inkl. VIP- und Spam-Badge, Tellows-Name bei
unbekannten Anrufern), Zustand („Klingelt"/„Wählt"/„Gespräch", farblich
abgesetzt, Icon pulsiert bei „Klingelt") sowie Ort/Land und eine laufende
Zeit seit Klingeln/Wählen/Gesprächsbeginn (aktualisiert sich selbst jede
Sekunde, unabhängig vom Abfrageintervall, da der Anrufmonitor Ereignisse
in Echtzeit über die eigene CallMonitor-Verbindung erhält). Ist kein Anruf
aktiv, steht dort „Kein aktiver Anruf" plus – falls vorhanden – eine Zeile
zum zuletzt beendeten Gespräch: Name/Nummer, Beginn–Ende (z. B.
„16:17–17:26"), Ort/Land und die exakte Gesprächsdauer inkl. Sekunden
(z. B. „1:09:18" statt der auf Minuten gerundeten Dauer aus der
Anrufliste).

**Anrufbeantworter in die Anrufliste integrieren:** Über die optionale
Option `tam_entity` lässt sich ein Anrufbeantworter-Sensor mit der
Anrufliste verknüpfen – **nicht** als zusätzliche Liste, sondern direkt in
der jeweiligen Zeile: Ein Anruf, der auf den Anrufbeantworter ging,
bekommt zusätzlich zum Aufklapp-Pfeil Play-/Löschen-Buttons (inkl.
Fortschrittsbalken beim Abspielen), ein Voicemail-Icon und einen
„Neu"-Punkt bei ungehörten Nachrichten – die zwei Ereignisse (Anruf und
Anrufbeantworter-Nachricht) verschmelzen so zu einer einzigen Zeile, ohne
die Aufklapp-Details zu verlieren. Die Legende bekommt dafür einen
zusätzlichen Filter „AB“ (eigene Kategorie, analog zu „Verpasst“), und der
Kartenkopf zeigt dieselbe „X neu“-Pille wie die eigenständige
Anrufbeantworter-Karte (zählt alle neuen Nachrichten der verknüpften
Entität, nicht nur die in der Anrufliste sichtbaren).

Die Zuordnung erfolgt clientseitig über die Rufnummer (toleriert dabei
nationale/internationale Schreibweisen wie `030123456` vs. `+4930123456`)
und, falls mehrere Nachrichten derselben Nummer infrage kommen, den
zeitlich nächstliegenden Zeitstempel – FRITZ!Box-intern gibt es keine
gemeinsame ID zwischen Anrufliste und Anrufbeantworter. Nachrichten ohne
passenden Eintrag in der (zeitlich/mengenmäßig begrenzten) Anrufliste
erscheinen hier nicht – dafür bleibt die eigenständige
Anrufbeantworter-Karte (`entity` direkt auf den Anrufbeantworter-Sensor
gesetzt, ohne `tam_entity`) weiterhin vollständig nutzbar, inkl. aller
Nachrichten unabhängig vom Anrufliste-Zeitraum.

**Einmalig einrichten:** Einstellungen → Dashboards → oben rechts ⋮ →
Ressourcen → Ressource hinzufügen:
- URL: `/fritzbox_phone_static/fritzbox-phone-card.js`
- Typ: JavaScript-Modul

Danach per **"Karte hinzufügen" → "FRITZ!Box Anrufliste / Anrufbeantworter /
Anrufmonitor"** mit grafischem Editor (Entität, Titel, Zeilenanzahl, …)
hinzufügen, oder direkt per YAML:

```yaml
type: custom:fritzbox-phone-card
entity: sensor.DEINE_FRITZBOX_ANRUFLISTE
rows: 8
```

```yaml
# Anrufliste + Anrufbeantworter in einer Karte
type: custom:fritzbox-phone-card
entity: sensor.DEINE_FRITZBOX_ANRUFLISTE
tam_entity: sensor.DEIN_ANRUFBEANTWORTER
rows: 8
```

```yaml
type: custom:fritzbox-phone-card
entity: sensor.DEIN_ANRUFBEANTWORTER
rows: 8
mark_read_on_play: true
```

```yaml
type: custom:fritzbox-phone-card
entity: sensor.DEIN_ANRUFMONITOR
```

| Option | Standard | Bedeutung |
|--------|----------|-----------|
| `entity` | – (Pflichtfeld) | `sensor.*_anrufliste`, `sensor.*_<anrufbeantworter>` oder `sensor.*_anrufmonitor` |
| `title` | Name der Entität | Kartentitel überschreiben |
| `rows` | 8 | Nur Anrufliste/Anrufbeantworter: maximale Anzahl angezeigter Zeilen |
| `show_legend` | an | Nur Anrufliste: farbige Legende (Ausgehend/Eingehend/Verpasst) über der Liste |
| `tam_entity` | – (optional) | Nur Anrufliste: verknüpfter `sensor.*_<anrufbeantworter>` - Anrufe, die dorthin gingen, bekommen Play/Löschen direkt in ihrer Zeile |
| `mark_read_on_play` | an | Nur Anrufbeantworter (auch als `tam_entity`): Nachricht beim Abspielen automatisch als gelesen markieren |

Die Legende ist klickbar: ein Klick auf einen Eintrag blendet alle Anrufe
dieses Typs aus der Liste aus (nochmal klicken zeigt sie wieder) – rein
clientseitiger Filter, wird nicht in der Karten-Konfiguration gespeichert.
`rows` bezieht sich dabei auf die *sichtbaren* Einträge: ausgeblendete
Zeilen werden durch weiter unten stehende, passende Anrufe nachgefüllt,
sodass weiterhin bis zu `rows` Zeilen zu sehen sind (statt einfach weniger
anzuzeigen).

Ein Klick auf eine Zeile (bei Anrufbeantworter-Nachrichten: auf den Namen/
die Metazeile, nicht auf Abspielen/Löschen) klappt weitere Details auf –
u. a. die Rufnummer, Ort/Land (offline ermittelt, siehe unten), bei
Anrufen zusätzlich Anruftyp, Beginn, Ende und Dauer des Gesprächs sowie
Fax-/Anrufbeantworter-Flag, bei Nachrichten Status und ob die Nummer im
Telefonbuch steht. Beginn/Ende werden minutengenau angezeigt (die
FRITZ!Box liefert sowohl den Anrufzeitpunkt als auch die Dauer selbst nur
auf die Minute genau – die Dauer im Format `hh:mm`, aufgerundet; Ende wird
daraus berechnet).

Nach Integrations-Updates, die `fritzbox-phone-card.js` ändern, ggf.
Browser-Cache der Seite leeren (`cache_headers` ist bewusst deaktiviert,
Browser können die Datei aber trotzdem kurzzeitig cachen).

## Dateien

| Pfad | Inhalt |
|------|--------|
| `api.py` | TR-064-Client (Telefonbuch, Anrufliste, Anrufbeantworter) |
| `callmonitor.py` | CallMonitor-Client (Port 1012, Echtzeit-Anrufstatus) |
| `coordinator.py` | Polling-Koordinator + Kontakt-Auflösung für den Anrufmonitor |
| `phoneblock.py` | PhoneBlock-Client für die optionale Spam-Erkennung |
| `tellows.py` | Tellows-Client für die optionale Online-Rückwärtssuche |
| `geocoding.py` | Offline Ort-/Länderkennung (`phonenumbers`) |
| `config_flow.py` | Einrichtung + Optionen (UI) |
| `sensor.py` / `switch.py` | Entitäten |
| `services.yaml`, `strings.json`, `translations/de.json` | Service- und UI-Texte |
| `www/fritzbox-phone-card.js` | Lovelace-Karte (Anrufliste/Anrufbeantworter, siehe oben) |
| `brand/` | Icon/Logo für Geräteseite und Integrationsübersicht |

## Hinweise

- Abhängigkeit: [`fritzconnection`](https://github.com/kbr/fritzconnection)
  (wird von Home Assistant automatisch installiert; dieselbe Bibliothek
  nutzen auch die Core-Integrationen `fritz` und `fritzbox_callmonitor`).
- Neue Telefonbücher oder zusätzlich aktivierte Anrufbeantworter werden erst
  nach einem Neuladen der Integration als Entität angelegt.
- Nach AVM-Spezifikation bedeutet `New=0` in der
  Anrufbeantworter-Nachrichtenliste „neu/ungelesen" – das ist in `api.py`
  entsprechend invertiert, damit der Sensorzustand intuitiv „Anzahl neuer
  Nachrichten" zeigt.
