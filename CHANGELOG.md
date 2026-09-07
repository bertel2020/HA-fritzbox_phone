# Änderungsverlauf

Alle nennenswerten Änderungen an dieser Integration werden hier festgehalten.

Das Format orientiert sich an [Keep a Changelog](https://keepachangelog.com/de/1.1.0/),
die Versionierung an [Semantic Versioning](https://semver.org/lang/de/).

## Unveröffentlicht

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
