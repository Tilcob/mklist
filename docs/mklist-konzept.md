# mklist – Konzeptplan

CLI-Tool zum Zusammenführen mehrerer gleich aufgebauter Excel-Listen anhand einer wählbaren Vorlage: Duplikate werden erkannt, Werte (z. B. Laufmeter, Anzahl) aggregiert und das Ergebnis wird in eine neue Liste geschrieben. Vor jedem Verarbeitungsschritt wird geprüft, ob die Daten zur Vorlage passen.

---

## 1. Grobarchitektur

```
Vorlage (JSON)  ─┐
                  ├─→  [1] Vorlage laden & validieren
Excel-Dateien ────┘         │
                             ▼
                    [2] Excel-Dateien einlesen
                             │
                             ▼
                    [3] Struktur-Validierung
                        (Spalten vorhanden? Typen korrekt?)
                             │
                             ▼
                    [4] Zusammenführen (concat)
                             │
                             ▼
                    [5] Duplikate gruppieren & aggregieren
                             │
                             ▼
                    [6] Ergebnis-Validierung
                        (Plausibilität, z. B. keine negativen Summen)
                             │
                             ▼
                    [7] Neue Excel-Datei schreiben
                             │
                             ▼
                    [8] Report/Log ausgeben
                        (was wurde zusammengefasst, was übersprungen)
```

**Grundprinzip:** Jeder Schritt kann fehlschlagen, und das muss an genau der Stelle erkennbar sein, an der er auftritt — nicht erst als kryptischer Fehler ganz am Ende.

---

## 2. Vorlagen-Schema (JSON)

```json
{
  "template_name": "Standard-Auswertung",
  "version": "1.0",

  "input": {
    "required_columns": ["Artikelnummer", "Farbe", "Laufmeter"],
    "column_types": {
      "Artikelnummer": "string",
      "Farbe": "string",
      "Laufmeter": "float"
    },
    "allow_missing_values": {
      "Artikelnummer": false,
      "Farbe": false,
      "Laufmeter": false
    }
  },

  "duplicate_keys": ["Artikelnummer", "Farbe"],

  "aggregate": [
    { "column": "Laufmeter", "method": "sum" }
  ],

  "output": {
    "columns_order": ["Artikelnummer", "Farbe", "Laufmeter"],
    "sort_by": ["Artikelnummer"],
    "filename_suffix": "_zusammengefasst"
  },

  "validation_rules": {
    "Laufmeter": { "min": 0 }
  }
}
```

### Designentscheidungen

- **`aggregate` ist eine Liste**, kein Einzelobjekt → erlaubt später mehrere aggregierte Spalten (z. B. `Laufmeter` summieren **und** `Anzahl` summieren), ohne das Schema brechend zu ändern.
- **`column_types` und `allow_missing_values` getrennt von `required_columns`** → klare Trennung zwischen „muss existieren“ und „darf leer sein“.
- **`validation_rules` als eigener Block** → Plausibilitätsgrenzen (z. B. keine negativen Werte), unabhängig vom reinen Typ-Check.
- **`duplicate_keys`** sind die Spalten, anhand derer zur Laufzeit entschieden wird, ob zwei Zeilen (aus beliebigen Eingabedateien) als Duplikat gelten und zusammengefasst werden — die Duplikate selbst entstehen erst beim Einlesen, nicht in der Vorlage.

---

## 3. Validierungsstrategie – drei Ebenen

### Ebene 1: Ist die Vorlage selbst gültig?
JSON-Schema-Validierung der Template-Datei, **bevor** irgendeine Excel-Datei angefasst wird. Verhindert, dass eine unvollständige oder fehlerhafte Vorlage überhaupt verwendet wird.

### Ebene 2: Passen die Excel-Daten zur Vorlage?
Für **jede** eingelesene Excel-Datei einzeln prüfen:
- Existieren alle `required_columns`?
- Stimmen die Datentypen (bzw. lassen sie sich sauber konvertieren)?
- Gibt es unerlaubte Leerwerte in Pflichtfeldern?
- Gibt es Spaltennamen-Probleme (Tippfehler, Whitespace, Unicode-Normalisierung)?

→ Datei-für-Datei validieren, **nicht erst nach dem Zusammenführen** — sonst ist nicht mehr nachvollziehbar, welche Datei das Problem verursacht hat.

### Ebene 3: Ist das Ergebnis plausibel?
Nach der Aggregation: `validation_rules` anwenden (z. B. keine negativen Summen, keine unrealistisch hohen Werte). Fängt Fehler ab, die erst durch die Aggregation selbst entstehen (z. B. Vorzeichenfehler in einer Quelldatei).

### Tooling-Vorschlag
| Ebene | Werkzeug |
|---|---|
| 1 – Vorlage | `pydantic` (Template als Model) oder `jsonschema` |
| 2 – Rohdaten | `pandera` (DataFrame-Validierung mit präziser Zeilen-/Spaltenangabe) |
| 3 – Ergebnis | `pandera` |

---

## 4. CLI-Interface

```bash
mklist run \
  --template templates/standard.json \
  --input-dir ./messwerte/ \
  --output ./ergebnis.xlsx \
  --report ./report.txt
```

### Subcommands & Flags

| Befehl/Flag | Zweck |
|---|---|
| `mklist run` | Hauptbefehl: Verarbeitung durchführen |
| `mklist validate-template` | Nur die Vorlage prüfen, ohne Excel-Dateien anzufassen (schnelles Feedback beim Erstellen neuer Vorlagen) |
| `--dry-run` | Zeigt an, was passieren würde (welche Zeilen zusammengefasst werden), ohne Ausgabedatei zu schreiben |
| `--strict` | Bricht bei jeder Validierungswarnung ab, statt nur zu loggen |
| `--report` | Schreibt eine Zusammenfassung: Anzahl gefundener Duplikate, Dateien mit Problemen |

**`--dry-run` ist bewusst vorgesehen:** Bei einer Verarbeitung, bei der am Ende Zahlen zusammengezählt werden, soll vor dem „scharfen“ Lauf sichtbar sein, was passieren würde — gerade Duplikat-Logik führt sonst schnell zu unerwarteten Ergebnissen.

---

## 5. Fehlerbehandlung – Philosophie

Drei Kategorien, die unterschiedlich behandelt werden:

1. **Abbruch-Fehler** — Vorlage ungültig, Excel-Datei nicht lesbar, Pflichtspalte fehlt komplett.
   → Programm stoppt sofort, klare Fehlermeldung mit Datei- und ggf. Zeilenangabe.
2. **Warnungen** — z. B. einzelne Zeile mit Leerwert wird übersprungen.
   → Verarbeitung läuft weiter, wird aber im Report vermerkt/gezählt, damit nichts stillschweigend verloren geht.
3. **Info** — z. B. „X Duplikate gefunden und zusammengefasst, Y Zeilen unverändert übernommen“.
   → landet im Abschlussbericht.

---

## 6. Projektstruktur

```
mklist/
├── templates/
│   ├── standard.json
│   └── template.schema.json      # JSON-Schema zur Selbstvalidierung
├── src/
│   ├── cli.py                    # Einstiegspunkt (click)
│   ├── template.py               # Pydantic-Model + Laden/Validieren der Vorlage
│   ├── excel_loader.py           # Excel-Dateien einlesen, Ebene-2-Validierung
│   ├── aggregator.py             # Duplikat-Gruppierung & Aggregation
│   ├── result_validator.py       # Ebene-3-Validierung
│   ├── writer.py                 # Ergebnis als Excel schreiben
│   └── report.py                 # Zusammenfassung/Log erzeugen
└── tests/
    └── ...
```

---

## 7. Technologie-Stack (Zusammenfassung)

- **Sprache:** Python
- **Excel I/O:** `pandas` (+ `openpyxl` als Engine)
- **Vorlagen-Validierung:** `pydantic`
- **DataFrame-Validierung:** `pandera`
- **CLI-Framework:** `click`

---

## 8. Offene Punkte für die nächste Ausarbeitungsstufe

- Genaues Pydantic-Model für die Vorlage
- Konkrete Pandera-Schemas für Ebene 2 und Ebene 3
- Ausformulierung des `cli.py` mit `click`
- Format des Abschlussberichts (Text, JSON, oder beides)
