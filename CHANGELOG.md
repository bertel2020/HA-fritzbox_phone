# Änderungsverlauf

Alle nennenswerten Änderungen an dieser Integration werden hier festgehalten.

## Unveröffentlicht

### Sicherheit

- Dashboard-Karte: Anrufer-Daten (Name, Rufnummer, Gerät, Ergebnisse von
  Tellows/PhoneBlock) wurden als HTML eingefügt. Da ein SIP-Anzeigename vom
  Anrufer selbst gewählt wird, konnte ein präparierter Anruf Skript im
  Dashboard ausführen. Alles wird jetzt als Text dargestellt.
- Die Sitzungskennung der FRITZ!Box (`sid=`) steht nicht mehr in
  Entitätsattributen (`recording_url`, `download_url`, `image_url` entfallen,
  stattdessen `has_recording`, `has_image`, `recording_path`) und damit auch
  nicht mehr in Datenbank und Backups.
- Aufnahmen werden nicht mehr nach `config/www` kopiert und unter `/local`
  ohne Anmeldung ausgeliefert, sondern angemeldet von der Integration
  gestreamt (`/api/fritzbox_phone/recording/...`, Karte nutzt signierte
  Adressen). `download_message` ist veraltet und akzeptiert nur noch
  Dateinamen mit Endung `.wav`, `.mp3` oder `.ogg`.
- Falsche Zugangsdaten wurden bei der Einrichtung akzeptiert; sie führen jetzt
  zu „Anmeldung fehlgeschlagen".
- Passwörter: Das Box-Kennwort ist ein Passwortfeld, das gespeicherte
  PhoneBlock-Kennwort wird nicht mehr an den Browser zurückgeschickt.
- Tellows-Antworten werden mit `defusedxml` ausgewertet und auf 64 KB begrenzt.
- GitHub-Action `Release`: Tag-Name und Tag-Nachricht gelangen nicht mehr
  direkt in Shell-Skripte; `hacs/action` ist auf `22.5.0` festgelegt.

### Behoben

- Ein fehlgeschlagener Abruf (Timeout, Box kurz weg) galt als „Anrufliste ist
  leer": danach meldete die Integration alle Anrufe als entfernt und beim
  nächsten Erfolg alle als neu. Fehler bedeuten jetzt „Aktualisierung
  fehlgeschlagen", die letzten Daten bleiben erhalten.
- Beim Anrufmonitor erschien „klingelt" bis zu 16 s verspätet, weil
  PhoneBlock und Tellows zuerst abgefragt wurden. Der Zustand erscheint
  sofort, die Anreicherung folgt.
- Gleichzeitige Gespräche (Anklopfen) setzten sich gegenseitig zurück; jedes
  Gespräch wird jetzt über seine Verbindungs-ID verfolgt.
- Der Anrufmonitor gab nach einem fehlgeschlagenen Start oder nach
  erschöpften Wiederverbindungsversuchen dauerhaft auf; er versucht es jetzt
  mit wachsendem Abstand erneut und ist bis dahin „nicht verfügbar".
- Rufnummern aus dem eigenen Ortsnetz (ohne Vorwahl) fanden weder einen
  Telefonbuchkontakt noch PhoneBlock/Tellows-Daten; alle Nummern werden jetzt
  einheitlich auf E.164 gebracht, die Vorwahl der Box wird ergänzt.
- Karte: Das Abspielen einer Nachricht brach ab, sobald das Markieren als
  gelesen den Zustand änderte; aufgeklappte Zeilen und Filter gingen bei
  jeder Aktualisierung verloren. Der Timer des Anrufmonitors blieb nach dem
  erneuten Einhängen der Karte stehen. Fehler erscheinen als Hinweis statt als
  Dialog.
- Die Anrufbeantworter-Aktionen auf einem anderen Sensor lieferten einen
  `AttributeError`; sie antworten jetzt mit einer verständlichen Meldung.
  Fehler der Box werden als `HomeAssistantError` gemeldet.
- Leere oder fehlerhafte Zahlenfelder in den XML-Antworten der Box lösen keinen
  Fehler mehr aus.

### Hinzugefügt

- Aktionen `fritzbox_phone.dial` (Wählhilfe), `fritzbox_phone.hangup` und
  `fritzbox_phone.lookup_number` (Antwort mit Kontakt, Ort, Spam- und
  Rückwärtssuche-Ergebnis).
- Entitäten: `event.*_anruf`, `binary_sensor.*_klingelt`,
  `binary_sensor.*_ungelesene_nachrichten`, `sensor.*_anrufe_heute`,
  `sensor.*_gespraechszeit_heute`.
- Entdeckung per SSDP, Neu-Anmeldung (Reauth) und Neu-Konfiguration (Host,
  Port, TLS, Zugangsdaten) in der Oberfläche; Diagnosedaten ohne
  Zugangsdaten und Rufnummern.
- Anrufe, die auf den Anrufbeantworter gingen, werden über die gemeinsame
  Aufnahmedatei der Nachricht zugeordnet (`tam_index`, `tam_message_index`),
  die Zuordnung per Nummer/Zeit bleibt Rückfall.
- Karte: Telefonbuch-Ansicht mit Suche, „Zurückrufen"-Knöpfe, Tageszusammenfassung,
  `tap_action`, Tastaturbedienung und Beschriftungen für Screenreader,
  Deutsch/Englisch, Anpassung an die Sections-Ansicht, Editor mit nur den
  passenden Optionen; sie wird von der Integration selbst bei Home Assistant
  angemeldet (keine Dashboard-Ressource mehr nötig).
- Englische Übersetzung (`translations/en.json`; `strings.json` ist jetzt die
  englische Basis), Symbole in `icons.json`, echte Geräteinfo (Modell,
  Seriennummer, Firmware).
- Blueprints `notify_missed_call` und `spam_call_alert`.
- Tests (`pytest-homeassistant-custom-component`, Karte mit jsdom) und die
  GitHub-Action `Tests`.

### Geändert

- PhoneBlock/Tellows laufen asynchron und parallel über die gemeinsame
  HTTP-Sitzung von Home Assistant, mit Zeitbudget je Abfragezyklus (20 s, beim
  Start 5 s). Zwischenspeicher haben eine Größenobergrenze, Fehlschläge werden
  nur 5 Minuten gemerkt (bisher 6 Stunden).
- Telefonbücher werden nur noch alle 15 Minuten geladen, der Kontaktabgleich
  nutzt einen Index.
- Das Land stammt aus der Home-Assistant-Konfiguration; die Option
  „Vorwahl-Präfixe" bleibt als Überschreibung.
- Neue Telefonbücher und Anrufbeantworter erscheinen ohne Neuladen.
- Der Anrufmonitor ist ein eigenes Objekt der Integration (nicht mehr Teil
  eines Sensors); seine Entitäten sind „nicht verfügbar", solange die
  Verbindung nicht steht.
- Die Listen-Attribute (`calls`, `contacts`, `messages`) werden nicht mehr im
  Recorder gespeichert.
- Mindestversion Home Assistant 2025.2; Laufzeitdaten liegen in
  `entry.runtime_data`.
- `numbers.py` heißt `phone_numbers.py` (Namensüberschneidung mit der
  Standardbibliothek).

### Hinweise zum Update

- Automationen und Templates, die `recording_url`, `download_url` oder
  `image_url` aus den Attributen lesen, müssen angepasst werden (siehe
  „Sicherheit").
- Wer `download_message` und `/local/fritzbox_tam/...` nutzt, sollte auf die
  Karte bzw. die angemeldete Adresse umsteigen; die alten Dateien bleiben
  unverändert und sind weiterhin ohne Anmeldung abrufbar.
- Die Entity-IDs der Telefonbuch-, Anrufbeantworter- und Schalter-Entitäten
  bleiben bestehen (die eindeutigen IDs ändern sich nicht).

## 1.15.1 – 2026-10-07

### Behoben

- `requests` aus den `requirements` der `manifest.json` entfernt: Home Assistant
  liefert die Bibliothek selbst mit, Hassfest lehnt den Eintrag deshalb ab und
  der nächtliche Validierungslauf schlug fehl. Am Verhalten der Integration
  ändert sich nichts.

### Hinzugefügt

- GitHub-Action `Release`: Beim Push eines `v*`-Tags entsteht das
  GitHub-Release automatisch. Die Release-Notes stammen aus dem passenden
  Abschnitt dieser Datei, der Titel aus der Beschriftung des annotierten Tags.
  Der Workflow bricht ab, wenn Tag und `version` in `manifest.json` nicht
  zusammenpassen oder der Changelog-Abschnitt fehlt; Tags mit Suffix
  (z. B. `v1.16.0-beta1`) werden als Vorabversion veröffentlicht.

### Geändert

- Installationsabschnitt im README auf die My-Home-Assistant-Badges umgestellt:
  ein Klick öffnet das Repository in HACS bzw. startet die Einrichtung direkt
  in der eigenen Home-Assistant-Instanz.

## 1.15.0 – 2026-09-08

### Hinzugefügt

- **Klartext-Begründungen im Logbuch.** Der Aktivitätsdialog einer Entität
  zeigte bisher „Für diese Aktivität wurde kein Grund festgehalten“. Alle
  Entitäten mit nennenswerter Aktivität schreiben ihren Zustand jetzt im
  Kontext eines eigenen Ereignisses, das die neue `logbook.py` in deutschen
  Klartext übersetzt – z. B. „Eingehender Anruf von Max Mustermann
  (+49301234567)“ oder „Gespräch beendet nach 2:31“. Betroffen sind
  Anrufmonitor, Anrufliste, Verpasste Anrufe und die Anrufbeantworter-Sensoren.
- Vier neue Ereignisse, auch als Automations-Auslöser nutzbar:
  `fritzbox_phone_call`, `fritzbox_phone_call_list_changed`,
  `fritzbox_phone_missed_call` und `fritzbox_phone_tam_message`. Sie enthalten
  neben den Anrufdaten `config_entry_id` und `host`, um bei mehreren
  FRITZ!Boxen filtern zu können.
- Änderungserkennung im Koordinator: neue bzw. entfallene Anrufe und
  Anrufbeantworter-Nachrichten werden von Abfrage zu Abfrage verglichen. Der
  Abgleich der Nachrichten erfolgt über Zeitstempel und Rufnummer statt über
  den Nachrichtenindex, den die FRITZ!Box beim Löschen neu vergibt.

### Geändert

- Der Anrufmonitor schreibt seinen Zustand nicht mehr direkt aus dem
  Lesethread, sondern reicht das fertig aufgelöste Ereignis an den Event-Loop
  weiter. Die blockierende Anreicherung (PhoneBlock, Tellows) bleibt im Thread.
  Das entspricht den Thread-Safety-Regeln aktueller Home-Assistant-Versionen.

## 1.14.1

- Stand bei Veröffentlichung des Repositories; ältere Änderungen sind nicht
  dokumentiert.
