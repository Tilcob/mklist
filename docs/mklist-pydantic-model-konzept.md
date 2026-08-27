# mklist – Pydantic-Model Konzept (Vorlagen-Validierung, Ebene 1)

Konzept für das Pydantic-Model, das die Template-JSON-Dateien von `mklist` lädt und validiert, bevor irgendeine Excel-Datei angefasst wird (Ebene 1 der Validierungsstrategie).

---

## 1. Grundgerüst: verschachtelte Models

Die Vorlage wird nicht als ein flaches Model abgebildet, sondern als mehrere verschachtelte Sub-Models entlang der bestehenden Bereiche (`input`, `aggregate`, `output`, `validation_rules`). Vorteil: jedes Sub-Model kann eigene Feld-Validierung tragen, und Fehlermeldungen von pydantic zeigen automatisch den genauen Pfad (z. B. `input.column_types.Laufmeter`).

```
TemplateConfig
├── template_name: str
├── version: str                          # rein informativ, siehe Punkt 5
├── input: InputConfig
│   ├── required_columns: list[str]
│   ├── column_types: dict[str, ColumnType]      (Enum: string/float/int/date)
│   └── allow_missing_values: dict[str, bool]
├── duplicate_keys: list[str]             # min. 1 Element
├── aggregate: list[AggregateRule]
│   ├── column: str
│   └── method: AggregateMethod           (Enum: sum/mean/count/...)
├── output: OutputConfig
│   ├── columns_order: list[str]
│   ├── sort_by: list[str]
│   └── filename_suffix: str
└── validation_rules: dict[str, ValueRange] = {}   # optional, Default leer
    ├── min: float | None
    └── max: float | None
```

---

## 2. Festgelegte Design-Entscheidungen

| Punkt | Entscheidung | Begründung |
|---|---|---|
| **Typen** | Enums für `column_types` und `aggregate.method`, keine freien Strings | Tippfehler in der Vorlage (z. B. `"flaot"`) fallen sofort beim Laden auf, nicht erst zur Laufzeit |
| **Cross-Field-Validierung** | Ja, via `model_validator(mode="after")` | Prüft Beziehungen zwischen Feldern, nachdem alle Einzelfelder validiert wurden |
| **Unbekannte Felder** | `extra="forbid"` (mit Fehlermeldung) | Tippfehler in Feldnamen (z. B. `"duplicate_key"` statt `"duplicate_keys"`) führen zu explizitem Fehler statt stillem Ignorieren |
| **`validation_rules`** | Optional, Default: leeres Dict | Nicht jede Vorlage braucht zwingend Plausibilitätsgrenzen |
| **`version`** | Rein informativ | Keine Migrations- oder versionsabhängige Parser-Logik – nur eine erkennbare Kennzeichnung der Vorlage |
| **`duplicate_keys`** | Mindestens 1 Element Pflicht | Eine leere Liste wäre sinnlos – jede Zeile wäre dann ihr eigenes „Duplikat“ |

---

## 3. Cross-Field-Validierungsregeln (`model_validator`)

Diese Regeln werden geprüft, nachdem alle Einzelfelder strukturell bereits korrekt sind:

1. Jeder Eintrag in `duplicate_keys` muss auch in `required_columns` vorkommen.
2. Jeder Key in `column_types` muss auch in `required_columns` vorkommen.
3. Jede `aggregate[].column` muss:
   - in `required_columns` vorkommen,
   - laut `column_types` numerisch sein (`float`/`int`), wenn `method` `sum`/`mean` ist.
4. Jeder Eintrag in `output.sort_by` und `output.columns_order` muss entweder ein `duplicate_keys`-Feld oder eine `aggregate[].column` sein (also tatsächlich im Ergebnis-DataFrame existieren).
5. Jeder Key in `validation_rules` (falls vorhanden) muss laut `column_types` numerisch sein — `min`/`max` auf einer `string`-Spalte ergibt keinen Sinn.

### Entscheidung zu Regel 5
Regel 5 wird als **nachträgliche Prüfung im `model_validator`** umgesetzt (Variante A), zusammen mit den Regeln 1–4 in derselben Cross-Field-Validierung.

**Begründung:**
- Konsistent mit den anderen 4 Cross-Field-Regeln — alle Beziehungsprüfungen an einem Ort, ein Validator, eine Fehlerquelle im Code
- Einfacheres, "dümmeres" Datenmodell für `ValueRange` (`{min, max}`) — kein Spezialfall nötig
- Die Alternative (`validation_rules` strukturell direkt an numerische Spalten aus `column_types` koppeln) hätte den behaupteten Vorteil "technisch unmöglich statt nur geprüft" in der Praxis nicht wirklich eingelöst: `input.column_types` und `validation_rules` sind zwei unabhängige Top-Level-Felder, deren Kopplung sich in pydantic ohnehin nur sauber über einen `model_validator` lösen lässt — der Mehraufwand hätte sich nicht ausgezahlt.
- Einheitlicher Fehler-Sammel-Mechanismus für alle 5 Regeln möglich (z. B. alle Cross-Field-Fehler in einer Liste sammeln statt einzeln zu werfen)

---

## 4. Noch offen für die nächste Ausarbeitungsstufe

- Konkrete pydantic-Feldtypen und `model_validator`-Implementierung
- Enum-Werte final festlegen (`ColumnType`, `AggregateMethod`)
- Entscheidung zu Regel 5 (nachträgliche Prüfung vs. strukturelle Einschränkung)
- Beispiel-Fehlermeldungen für jede Cross-Field-Regel (verständlich für Nicht-Entwickler, die Vorlagen pflegen)
