# mklist – Implementierungsplan

Konkreter Umsetzungsplan, aufbauend auf den fünf Konzept-Dokumenten:
`mklist-konzept.md`, `mklist-pydantic-model-konzept.md`, `mklist-pandera-validierung-konzept.md`, `mklist-cli-konzept.md`, `mklist-report-konzept.md`.

Alle inhaltlichen Entscheidungen sind getroffen — dieser Plan beschreibt nur noch die technische Umsetzung in sinnvoller Reihenfolge.

---

## Grundprinzip der Reihenfolge

Von innen nach außen bauen: zuerst die Datenmodelle (was ist eine gültige Vorlage?), dann die Validierung der Rohdaten, dann die eigentliche Verarbeitungslogik, dann Ausgabe/Report, zuletzt das CLI als dünne Hülle darüber. So ist jede Phase für sich testbar, bevor die nächste darauf aufbaut.

---

## Phase 0 — Projekt-Grundgerüst

- Projektstruktur gemäß Gesamtkonzept anlegen (`src/`, `templates/`, `tests/`)
- `pyproject.toml` mit Abhängigkeiten: `pandas`, `openpyxl`, `pydantic`, `pandera`, `click`
- Virtuelle Umgebung, Basis-`README.md`
- Leeres `template.schema.json` (JSON-Schema, optional parallel zu Pydantic für Editor-Unterstützung beim Vorlagen-Erstellen)

**Ergebnis:** Projekt startet, `mklist --help` zeigt eine leere Befehlsstruktur.

---

## Phase 1 — Vorlagen-Modell (`template.py`)

Umsetzung des Pydantic-Konzepts.

1. Enums definieren: `ColumnType` (`string`, `float`, `int`, `date`), `AggregateMethod` (`sum`, `mean`, `count`, ...)
2. Sub-Models: `InputConfig`, `AggregateRule`, `OutputConfig`, `ValueRange`
3. Top-Level-Model `TemplateConfig`, `extra="forbid"` auf allen Models
4. `duplicate_keys`: `min_length=1`
5. `model_validator(mode="after")` mit allen 5 Cross-Field-Regeln (siehe Pydantic-Konzept, Abschnitt 3) — Regel 5 als Teil desselben Validators (Variante A)
6. Ladefunktion `load_template(path: Path) -> TemplateConfig`, die JSON liest und Pydantic-Fehler in verständliche Meldungen übersetzt (Feldpfad + Klartext)

**Test-Fokus:** je ein Testfall pro Cross-Field-Regel (bewusst kaputte Vorlagen), plus ein Testfall für `extra="forbid"` (Tippfehler im Feldnamen).

**Ergebnis:** `mklist validate-template --template x.json` ist funktional nutzbar (auch ohne fertiges CLI, erstmal als Funktion/Skript testbar).

---

## Phase 2 — Datei-Einlesen (`loader.py`)

1. Verzeichnis nach unterstützten Dateien durchsuchen (`.xlsx`, `.xls`, `.csv`), gemischt oder einheitlich
2. Excel-Einlesen (wie in der bestehenden GUI-App: `pd.read_excel`, Spaltennamen normalisieren via `unicodedata`)
3. CSV-Einlesen mit fixen Parametern: `sep=";"`, `encoding="utf-8"`, `decimal="."`, Header-Zeile Pflicht — **kein** Auto-Sniffing
4. Bei Format-Verstoß (z. B. Datei nicht lesbar, falsches Trennzeichen erkennbar an Parsing-Fehler): klarer Abbruch-Fehler mit Dateiname
5. Rückgabe: eine Liste von `(dateiname, DataFrame)`-Paaren — noch **ungeprüft**, das übernimmt Phase 3

**Ergebnis:** beliebiger Ordner mit Excel-/CSV-Dateien lässt sich einlesen, unabhängig vom Rest der Pipeline testbar.

---

## Phase 3 — Rohdaten-Validierung (`validation_input.py`)

Umsetzung von Pandera-Konzept, Ebene 2.

1. `build_input_schema(template: TemplateConfig) -> pandera.DataFrameSchema` — pro `required_columns`-Eintrag ein `pandera.Column` mit `dtype` aus `column_types` und `nullable` aus `allow_missing_values`
2. Validierungsfunktion pro Datei: `lazy=True`, Fehler als `SchemaErrors` einsammeln
3. Unbekannte Spalten (nicht in `required_columns`) separat erkennen → **eine Warnung pro Spalte**, kein Abbruch
4. Alle Fehler/Warnungen mit Dateiname anreichern und in einer gemeinsamen Ergebnisstruktur sammeln (z. B. `ValidationResult` je Datei: Liste von Fehlern, Liste von Warnungen)

**Test-Fokus:** fehlende Pflichtspalte, falscher Typ, Leerwert trotz `allow_missing_values=false`, unbekannte Spalte (→ Warnung statt Fehler), mehrere Fehler gleichzeitig (prüft `lazy=True`-Sammlung).

**Ergebnis:** jede Datei liefert ein strukturiertes Validierungsergebnis, bevor irgendetwas zusammengeführt wird.

---

## Phase 4 — Zusammenführen & Aggregation (`aggregator.py`)

1. Nur Dateien ohne Abbruch-Fehler aus Phase 3 werden weiterverarbeitet (bei `--strict` bricht das Programm hier schon ab, falls Warnungen vorhanden sind)
2. `pd.concat` aller validierten DataFrames
3. `groupby(duplicate_keys)` mit den in `aggregate` definierten Methoden (`sum`, `mean`, `count`, ...) pro Spalte
4. Spalten gemäß `output.columns_order` anordnen, nach `output.sort_by` sortieren
5. Zwischenergebnis: Summe der aggregierten Spalte(n) **vor** und **nach** der Gruppierung getrennt festhalten (wird in Phase 5 verglichen)

**Ergebnis:** ein sauberes, aggregiertes Ergebnis-DataFrame plus die für den Summen-Check nötigen Zwischenwerte.

---

## Phase 5 — Ergebnis-Validierung (`validation_result.py`)

Umsetzung von Pandera-Konzept, Ebene 3.

1. `build_result_schema(template: TemplateConfig)` — Spalten aus `duplicate_keys` + `aggregate[].column`, `validation_rules` als `Check`s (min/max)
2. Duplikat-Check: nach `groupby` dürfen keine doppelten `duplicate_keys`-Kombinationen mehr existieren → harter Fehler bei Verstoß
3. Summen-Sanity-Check: Summe vorher/nachher aus Phase 4, verglichen auf 2 Nachkommastellen gerundet → harter Fehler bei Abweichung

**Test-Fokus:** absichtlich manipuliertes Aggregat (z. B. gefälschte Summenabweichung simulieren), um sicherzustellen, dass der Check zuverlässig greift.

**Ergebnis:** Aggregations-Ergebnis ist entweder vollständig geprüft und vertrauenswürdig, oder die Verarbeitung bricht mit klarer Begründung ab.

---

## Phase 6 — Ausgabe schreiben (`writer.py`)

1. Ergebnis-DataFrame als `.xlsx` schreiben (`pandas.ExcelWriter` / `openpyxl`)
2. Dateiname aus `--output` oder Default (`<input-dir>/ergebnis_<template_name>.xlsx`)
3. Bei `--dry-run`: dieser Schritt wird übersprungen, aber die Information „hätte geschrieben nach: ...“ fließt in den Report

**Ergebnis:** fertige `.xlsx`-Datei im Zielordner (außer bei `--dry-run`).

---

## Phase 7 — Report-Erzeugung (`report.py`)

Umsetzung des Report-Konzepts.

1. Internes, formatneutrales Report-Datenmodell definieren (z. B. eigenes Pydantic- oder Dataclass-Model: Kopfdaten, Zusammenfassung, Liste von Datei-Ergebnissen, Aggregations-Ergebnis, Fehlerliste)
2. Während der Phasen 3–5 wird dieses Modell befüllt (nicht erst am Ende aus Logs rekonstruiert)
3. Zwei Renderer:
   - `render_markdown(report_data) -> str`
   - `render_html(report_data) -> str` (inkl. eingebettetem CSS für die Farbcodierung Grün/Gelb-Orange/Rot, keine Emojis)
4. Beide Dateien aus `--report`-Basisnamen schreiben (`<basis>.md`, `<basis>.html`)
5. Report wird **immer** geschrieben — auch bei Erfolg (volle Ausführlichkeit) und bei `--dry-run` (mit Kennzeichnung im Kopfbereich)

**Test-Fokus:** Reports für alle drei Ausgänge (Erfolg / Warnung / Fehler) sowie einmal mit `--dry-run` erzeugen und auf Vollständigkeit der Abschnitte prüfen.

**Ergebnis:** aus jedem `TemplateConfig` + Verarbeitungslauf entsteht ein vollständiges, lesbares Berichtspaar.

---

## Phase 8 — CLI (`cli.py`)

Erst jetzt, wenn alle Bausteine einzeln funktionieren, werden sie hinter dem CLI zusammengeschaltet.

1. `click`-Group `mklist` mit drei Subcommands:
   - `run` — orchestriert Phase 1–7 der Reihe nach, sammelt Exit-Status
   - `validate-template` — nur Phase 1
   - `list-templates` — liest alle `.json`-Dateien in `--template-dir`, zeigt `template_name` + `version`
2. Flags umsetzen: `--template`, `--input-dir`, `--output`, `--report`, `--dry-run`, `--strict`
3. Konsolen-Ausgabe: eine Zeile pro Datei während der Verarbeitung (`Lese <datei> ... OK` / `... Fehler: ...`)
4. Exit Codes setzen: `0` / `1` / `2` je nach Ergebnis, `--strict` eskaliert Warnungen zu `1`

**Test-Fokus:** End-to-End-Test mit einem kleinen Beispielordner (2–3 Testdateien, bewusst mit einer bekannten Warnung und einem bekannten Duplikat), Prüfung von Konsolenausgabe, Exit Code, erzeugter `.xlsx` und beiden Report-Dateien.

**Ergebnis:** `mklist` ist vollständig nutzbar wie im CLI-Konzept beschrieben.

---

## Phase 9 — Abrundung

- Test-Vorlagen (`templates/standard.json` + passendes Beispiel-Datenset) für Doku/Onboarding
- `README.md` mit Nutzungsbeispielen (analog zur GUI-App-README)
- Grober Blick über alle Fehlermeldungen: konsistenter Ton, keine rohen Python-Tracebacks im Report/CLI-Output

---

## Testschema (Übersicht)

| Phase | Testart | Fokus |
|---|---|---|
| 1 | Unit | Cross-Field-Regeln, `extra="forbid"` |
| 2 | Unit | Excel/CSV-Einlesen, Formatfehler |
| 3 | Unit | Pandera-Fehler/Warnungen pro Datei |
| 4 | Unit | Gruppierung, Aggregation, Summenbildung |
| 5 | Unit | Duplikat-Check, Summen-Sanity-Check |
| 6 | Unit | Datei wird geschrieben / bei `--dry-run` nicht |
| 7 | Unit | Beide Report-Formate, alle drei Ausgänge |
| 8 | Integration/E2E | Gesamter Lauf über Beispieldaten, Exit Codes |

---

## Reihenfolge auf einen Blick

```
Phase 0  Projekt-Grundgerüst
Phase 1  Vorlagen-Modell (Pydantic)
Phase 2  Datei-Einlesen (Excel/CSV)
Phase 3  Rohdaten-Validierung (Pandera, Ebene 2)
Phase 4  Zusammenführen & Aggregation
Phase 5  Ergebnis-Validierung (Pandera, Ebene 3)
Phase 6  Ausgabe schreiben (.xlsx)
Phase 7  Report-Erzeugung (.md + .html)
Phase 8  CLI (click) — bindet alles zusammen
Phase 9  Abrundung (Doku, Beispiele, Fehlertexte)
```
