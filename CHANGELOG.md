# Änderungsverlauf

Alle nennenswerten Änderungen an dieser Integration werden hier festgehalten.

## Unveröffentlicht

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
