# mklist

CLI-Tool zum Zusammenführen mehrerer gleich aufgebauter Excel-/CSV-Listen anhand einer wählbaren Vorlage: Duplikate werden erkannt, definierte Spalten aggregiert (z. B. Laufmeter summiert) und das geprüfte Ergebnis als neue Excel-Datei ausgegeben.

## Warum

Wenn mehrere Messwert- oder Bestelllisten mit identischem Aufbau vorliegen und Duplikate (z. B. gleiche Artikelnummer + Farbe) zusammengeführt und aufsummiert werden müssen, übernimmt `mklist` das zuverlässig und nachvollziehbar — inklusive Validierung der Eingabedaten und eines exakten Abgleichs, dass beim Zusammenführen keine Werte verloren gehen.

## Features

- **Vorlagen-gesteuert** — eine JSON-Vorlage legt fest, welche Spalten Pflicht sind, welche Typen sie haben, wonach Duplikate erkannt werden und wie aggregiert wird
- **Mehrere Eingabeformate** — `.xlsx`, `.xls` und `.csv` (auch gemischt in einem Lauf)
- **Dreistufige Validierung** — Vorlage selbst, jede Eingabedatei einzeln, und das Ergebnis nach der Aggregation
- **Exakter Summen-Check** — die Summe der aggregierten Werte vor und nach dem Zusammenführen muss übereinstimmen, sonst bricht der Lauf ab
- **Ausführlicher Report** — als Markdown und HTML, mit Farbcodierung für Erfolg/Warnung/Fehler
- **Dry-Run-Modus** — zeigt, was passieren würde, ohne eine Ausgabedatei zu schreiben
- **Klare Exit Codes** — für die Einbindung in Skripte/Automatisierung

## Installation

```bash
pip install -e ".[dev]"
```

Voraussetzung: Python 3.10 oder neuer.

## Verwendung

### Vorlage prüfen

```bash
mklist validate-template --template templates/standard.json
```

### Verfügbare Vorlagen auflisten

```bash
mklist list-templates --template-dir templates/
```

### Schnellstart mit Beispieldaten

Das Projekt enthält ein fertiges Beispiel unter `examples/messwerte/` (zwei CSV-Dateien, passend zur Vorlage `templates/standard.json`, inklusive eines Duplikats über beide Dateien hinweg und einer absichtlich unbekannten Spalte `Kommentar` zur Demonstration der Warnung):

```bash
mklist run --template templates/standard.json --input-dir examples/messwerte/
```

Erwartetes Ergebnis: `Artikelnummer A100/rot` kommt in beiden Dateien vor (12.5 + 3.25 + 5.0 Laufmeter) und wird zu **20.75** zusammengefasst; die restlichen Artikel bleiben unverändert. Wegen der Spalte `Kommentar` in `messwerte_august.csv` (nicht Teil der Vorlage) endet der Lauf mit **Exit Code 2** (Erfolg mit Warnung) statt `0` — gut geeignet, um den Report einmal in beiden Ausprägungen zu sehen.

### Listen zusammenführen (eigene Daten)

```bash
mklist run \
  --template templates/standard.json \
  --input-dir ./messwerte/ \
  --output ./ergebnis.xlsx \
  --report ./report
```

Erzeugt `ergebnis.xlsx` sowie `report.md` und `report.html`.

**Ohne Angabe von `--output`/`--report`** werden sinnvolle Default-Pfade im Eingabeordner verwendet.

### Nützliche Flags

| Flag | Wirkung |
|---|---|
| `--dry-run` | Zeigt das Ergebnis an, ohne eine Ausgabedatei zu schreiben (Report wird trotzdem erzeugt) |
| `--strict` | Jede Warnung (z. B. unbekannte Spalte) führt zum Abbruch statt nur zur Meldung |

## Vorlagen (Templates)

Eine Vorlage ist eine JSON-Datei, die u. a. festlegt:

- `input.required_columns` — welche Spalten vorhanden sein müssen
- `input.column_types` — welchen Typ jede Spalte hat (`string`, `int`, `float`, `date`)
- `duplicate_keys` — anhand welcher Spalten Zeilen als Duplikat gelten
- `aggregate` — welche Spalte(n) wie zusammengefasst werden (`sum`, `mean`, `count`, ...)
- `output` — Sortierung und Spaltenreihenfolge im Ergebnis
- `validation_rules` — optionale Plausibilitätsgrenzen (z. B. keine negativen Werte)

Ein Beispiel und das zugehörige JSON-Schema liegen unter `templates/`. Editoren mit JSON-Schema-Unterstützung (z. B. VS Code) bieten damit automatisch Validierung und Autovervollständigung beim Bearbeiten einer Vorlage an.

## Eingabeformat

**Excel** (`.xlsx`, `.xls`) — Spalten werden anhand des Namens erkannt, Reihenfolge ist beliebig.

**CSV** — festes Format, keine automatische Erkennung:
- Trennzeichen: `;`
- Encoding: `utf-8`
- Dezimaltrennzeichen: `.` (kein Komma, keine Tausendertrennzeichen)
- Header-Zeile ist Pflicht, Spalten werden namensbasiert zugeordnet

## Validierung

1. **Vorlage** — wird beim Laden strukturell und inhaltlich geprüft (z. B. referenzieren `duplicate_keys` tatsächlich vorhandene Pflichtspalten)
2. **Eingabedaten** — jede Datei wird einzeln gegen die Vorlage geprüft; fehlende Pflichtspalten oder falsche Typen führen zum Abbruch, unbekannte zusätzliche Spalten lösen nur eine Warnung aus
3. **Ergebnis** — nach der Aggregation wird geprüft, dass keine Duplikate mehr übrig sind und die Summen exakt (auf 2 Nachkommastellen) mit den Ausgangsdaten übereinstimmen

## Exit Codes

| Code | Bedeutung |
|---|---|
| `0` | Erfolg, keine Probleme |
| `1` | Abbruch-Fehler |
| `2` | Erfolgreich, aber mit Warnungen |

## Projektstruktur

```
├── src/
│   └── mklist/
│       ├── cli.py               # CLI-Einstiegspunkt (click)
│       ├── template.py          # Vorlagen-Modell & Validierung (pydantic)
│       ├── loader.py            # Excel-/CSV-Einlesen
│       ├── validation_input.py  # Rohdaten-Validierung (pandera, Ebene 2)
│       ├── aggregator.py        # Zusammenführen & Aggregation
│       ├── validation_result.py # Ergebnis-Validierung (pandera, Ebene 3)
│       ├── writer.py            # Ausgabedatei schreiben
│       └── report.py            # Report-Erzeugung (Markdown & HTML)
├── templates/
│   ├── standard.json
│   └── template.schema.json
├── examples/
│   └── messwerte/            # Beispieldaten für den Schnellstart
│       ├── messwerte_juli.csv
│       └── messwerte_august.csv
└── tests/
```

## Entwicklung

```bash
pip install -e ".[dev]"
pytest
```

## License

Internal tool — add license information here if applicable.
