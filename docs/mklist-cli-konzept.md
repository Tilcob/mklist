# mklist – CLI-Interface Konzept

Konzept für die Kommandozeilen-Oberfläche von `mklist`, aufbauend auf dem Gesamtplan, dem Pydantic-Model (Ebene 1) und der Pandera-Validierung (Ebene 2 & 3).

---

## 1. Subcommand-Struktur

```
mklist
├── run                  → Hauptverarbeitung
├── validate-template    → nur Vorlage prüfen, ohne Excel/CSV-Dateien anzufassen
└── list-templates       → verfügbare Vorlagen in einem Ordner auflisten
```

### `mklist list-templates`
Listet alle Template-Dateien in einem angegebenen Ordner mit `template_name` + `version` auf, damit man nicht raten muss, welche Datei welche Vorlage enthält.

```bash
mklist list-templates --template-dir ./templates/
```

---

## 2. `mklist run` — Argumente

```bash
mklist run \
  --template templates/standard.json \
  --input-dir ./messwerte/ \
  [--output ./ergebnis.xlsx] \
  [--report ./report.txt] \
  [--dry-run] \
  [--strict]
```

| Flag | Pflicht? | Beschreibung |
|---|---|---|
| `--template` | ✅ Pflicht | Pfad zur Template-JSON-Datei |
| `--input-dir` | ✅ Pflicht | Ordner mit den einzulesenden Dateien (`.xlsx`, `.xls`, `.csv` — gemischt oder einheitlich, beides erlaubt) |
| `--output` | Optional | Default: `<input-dir>/ergebnis_<template_name>.xlsx`. Ausgabe ist **immer** `.xlsx`, unabhängig vom Input-Format |
| `--report` | Optional | Default: gleicher Pfad/Name wie `--output`, mit `.report.txt` |
| `--dry-run` | Flag | Zeigt an, was passieren würde, ohne `--output` zu schreiben |
| `--strict` | Flag | Siehe Abschnitt 5 |

### Input-Dateitypen
- Unterstützte Formate: `.xlsx`, `.xls`, `.csv`
- `--input-dir` darf gemischte Dateitypen enthalten **oder** nur einen Typ — beide Fälle werden unterstützt, alle passenden Dateien im Ordner werden eingelesen und zusammengeführt.
- **CSV-Format:** fest erwartetes Format, **keine** automatische Erkennung von Trennzeichen/Encoding/Dezimalformat. Erwartung:
  - Trennzeichen: Semikolon (`;`)
  - Encoding: `utf-8`
  - Dezimaltrennzeichen: **Punkt (`.`)**, fix — kein Komma, keine Tausendertrennzeichen, keine Erkennungslogik
  - Header-Zeile: Pflicht (erste Zeile enthält die Spaltennamen — ohne Header kann `mklist` die `required_columns` aus der Vorlage nicht zuordnen)
  - Spaltenzuordnung: **namensbasiert**, nicht positionsbasiert — die Spalten dürfen in beliebiger Reihenfolge stehen, `mklist` sucht anhand der Spaltennamen aus `required_columns` in der Header-Zeile (konsistent mit dem bestehenden Excel-Verhalten)
  - Quoting: Standard-CSV-Quoting (`"..."`) für Textfelder mit Sonderzeichen — als Ausgangspunkt festgelegt, bei Bedarf später anpassbar
  - Entspricht eine Datei diesem Format nicht (z. B. falsches Trennzeichen, fehlender Header, Komma statt Punkt als Dezimaltrennzeichen), wird ein klarer Fehler ausgegeben (Dateiname + Grund).
  - Begründung gegen Auto-Erkennung: Bei Rand-Fällen (z. B. Dezimaltrennzeichen `,` vs. `.`) besteht das Risiko stiller Fehlinterpretationen — nicht vertretbar angesichts des Anspruchs, dass Summen nach der Aggregation exakt stimmen müssen (siehe Pandera-Konzept, Ebene 3).

---

## 3. Exit Codes

| Code | Bedeutung |
|---|---|
| `0` | Erfolg, keine Probleme |
| `1` | Abbruch-Fehler (ungültige Vorlage, fehlende Pflichtspalte, Summen-Sanity-Check fehlgeschlagen etc.) |
| `2` | Erfolgreich abgeschlossen, aber mit Warnungen (z. B. unbekannte Spalten, übersprungene leere Zeilen) — nur relevant, wenn `--strict` **nicht** gesetzt ist, da mit `--strict` Warnungen ohnehin zu Code `1` eskalieren |

Ermöglicht eine saubere Einbindung in Batch-Skripte/Automatisierung, bei der Erfolg/Warnung/Fehler unterscheidbar sein müssen.

---

## 4. Konsolen-Ausgabe zur Laufzeit

Zusätzlich zum `--report` (Datei) wird während des Laufs direkt in der Konsole mitgegeben, was passiert — **eine Zeile pro verarbeiteter Datei**, keine Fortschrittsbalken/Prozentanzeige. Beispiel:

```
Lese messwerte_juli.xlsx ... OK
Lese messwerte_august.csv ... OK (2 Warnungen)
Lese messwerte_september.xlsx ... Fehler: Pflichtspalte 'Laufmeter' fehlt
```

**Begründung für die schlichte Variante** (statt Fortschrittsbalken via `rich`/`tqdm`): weniger Abhängigkeiten, robuster in verschiedenen Terminal-Umgebungen (z. B. wenn `mklist` in einer Pipeline läuft oder die Ausgabe in eine Log-Datei umgeleitet wird, statt in einem interaktiven Terminal).

---

## 5. `--strict`-Verhalten

`--strict` wandelt **alle** Warnungen (unabhängig von Kategorie — unbekannte Spalten, übersprungene leere Zeilen etc.) in harte Abbruch-Fehler um. Keine Sonderbehandlung einzelner Warnungs-Kategorien.

→ Einfache Regel, leicht zu dokumentieren: *"Mit `--strict` führt jede Abweichung von der Vorlage zum Abbruch."*

---

## 6. Zusammenfassung der Entscheidungen

| Punkt | Entscheidung |
|---|---|
| Subcommands | `run`, `validate-template`, `list-templates` |
| `--output`/`--report` | Optional mit sinnvollen Defaults, überschreibbar |
| Input-Formate | `.xlsx`, `.xls`, `.csv` — gemischt oder einheitlich, beides möglich |
| CSV-Format | Fest erwartet (`;`-Trennzeichen, `utf-8`), keine Auto-Erkennung |
| Output-Format | Immer `.xlsx` |
| Exit Codes | `0` Erfolg / `1` Fehler / `2` Erfolg mit Warnungen |
| Konsolen-Ausgabe | Eine Zeile pro Datei, kein Fortschrittsbalken |
| `--strict` | Alle Warnungen werden zu Abbruch-Fehlern (Variante a) |

---

## 7. Noch offen für die nächste Ausarbeitungsstufe

- Genaues Format der Report-Datei (Text vs. strukturiert, siehe Gesamtkonzept Punkt 8)
- ~~Exaktes CSV-Format dokumentieren~~ → erledigt (siehe Abschnitt 2, CSV-Format)
- `click`-Implementierung der drei Subcommands
- Fehlermeldungstexte für den Konsolen-Output (Vorlage für Klarheit/Konsistenz)
