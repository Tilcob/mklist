# mklist – Pandera-Validierung Konzept (Ebene 2 & 3)

Konzept für die Rohdaten- und Ergebnis-Validierung von `mklist`, aufbauend auf der geladenen und validierten `TemplateConfig` (siehe `mklist-pydantic-model-konzept.md`).

---

## Ebene 2: Rohdaten-Validierung (pro Excel-Datei)

Ziel: **jede einzelne** eingelesene Excel-Datei wird geprüft, ob sie zur `TemplateConfig` passt — bevor irgendetwas zusammengeführt wird.

### Prüfungen

1. **Spalten-Existenz** — alle `required_columns` müssen in der Datei vorhanden sein (inkl. Whitespace-/Unicode-Normalisierung der Spaltennamen).
2. **Typkonformität** — jede Spalte aus `column_types` muss sich sauber in den angegebenen Typ konvertieren lassen (`float`, `int`, `string`, `date`).
3. **Missing Values** — wenn `allow_missing_values[spalte] == false`, dürfen dort keine leeren/NaN-Zellen vorkommen.
4. **Unbekannte/zusätzliche Spalten** — werden **nicht** abgelehnt, lösen aber eine **Warnung** aus (landet im Report). Grund: könnte ein Hinweis auf eine falsche/nicht passende Datei sein, soll die Verarbeitung aber nicht blockieren.

### Dynamisches Schema

Da `column_types` und `allow_missing_values` erst zur Laufzeit aus der Vorlage kommen, ist das Pandera-Schema **nicht statisch**, sondern wird dynamisch aus der `TemplateConfig` gebaut:

```
build_input_schema(template: TemplateConfig) -> pandera.DataFrameSchema
```

Pro Spalte aus `required_columns` wird ein `pandera.Column(...)` mit passendem `dtype` (aus `ColumnType`-Enum) und `nullable`-Flag (aus `allow_missing_values`) erzeugt.

### Fehlersammlung

- `lazy=True` — **alle** Validierungsfehler einer Datei werden gesammelt zurückgegeben (`SchemaErrors`), nicht nur der erste. So enthält der Report z. B. „Zeile 15: Laufmeter ist leer“ **und** „Zeile 42: Farbe fehlt“ in einem Durchlauf, statt dass Fehler nacheinander bei jedem erneuten Lauf einzeln auftauchen.
- **Datei-Zuordnung** — da mehrere Dateien verarbeitet werden, muss jeder gesammelte Fehler zusätzlich mit dem **Dateinamen** anreichert werden (Pandera kennt den Dateinamen selbst nicht — das übernimmt der Aufrufer beim Einsammeln der Fehler).

---

## Ebene 3: Ergebnis-Validierung (nach Aggregation)

Deutlich schlanker, da das Ergebnis-DataFrame nur noch `duplicate_keys`- und `aggregate[].column`-Spalten enthält.

### Prüfungen

1. **`validation_rules` aus der Vorlage** (z. B. `Laufmeter.min = 0`) — ebenfalls dynamisch aus der Vorlage gebautes Schema, nach demselben Prinzip wie in Ebene 2.
2. **Duplikat-Check nach der Aggregation** — nach `groupby` dürfen **keine** doppelten `duplicate_keys`-Kombinationen mehr existieren (das ist der Zweck der Aggregation). Tritt das doch auf, ist die Aggregations-Logik grundsätzlich fehlerhaft → **harter Fehler**, keine Warnung.
3. **Summen-Sanity-Check** — die Summe der aggregierten Spalte(n) über alle Eingabedateien muss exakt der Summe im Ergebnis nach der Aggregation entsprechen. Kein inhaltlicher Toleranzbereich: die Zahlen müssen zu 100 % stimmen, da auf ihrer Basis reale Bestellungen ausgelöst werden. Abweichung → **harter Fehler**, Verarbeitung wird nicht als erfolgreich gewertet.
   - **Technische Rundung:** Der Vergleich erfolgt auf **2 Nachkommastellen** gerundet. Das ist keine inhaltliche Toleranz, sondern rein technisch nötig, da Fließkomma-Arithmetik (`float`) durch reine Rechenungenauigkeit minimale Abweichungen erzeugen kann (z. B. `123.45000000000001` statt `123.45`), ohne dass dabei tatsächlich Daten verloren gehen. Zwei Nachkommastellen sind für den Anwendungsfall ausreichend genau, um echten Datenverlust zuverlässig von Rundungsartefakten zu unterscheiden.

---

## Gemeinsamer Baustein für Ebene 2 & 3

Da beide Ebenen **dynamisch aus der Vorlage generierte** Pandera-Schemas benötigen, wird eine gemeinsame Hilfsfunktion vorgesehen, die aus `ColumnType`-Enum + `nullable`-Flag ein `pandera.Column` baut. Sie wird an beiden Stellen wiederverwendet, lediglich mit unterschiedlicher Spaltenauswahl:

- **Ebene 2:** Spalten aus `required_columns`
- **Ebene 3:** Spalten aus `duplicate_keys` + `aggregate[].column`

---

## Zusammenfassung der Entscheidungen

| Punkt | Entscheidung |
|---|---|
| Unbekannte Spalten in Excel-Datei | Erlaubt, aber Warnung im Report |
| Pandera-Fehlersammlung | `lazy=True` — alle Fehler auf einmal, mit Datei- und Zeilenangabe |
| Summen-Sanity-Check (Ebene 3) | Vergleich auf 2 Nachkommastellen gerundet; jede Abweichung darüber hinaus ist ein harter Fehler |
| Duplikat-Check nach Aggregation | Harter Fehler, falls nach `groupby` noch doppelte `duplicate_keys`-Kombinationen existieren |

---

## Noch offen für die nächste Ausarbeitungsstufe

- Konkrete Implementierung von `build_input_schema()` / `build_result_schema()`
- Format der Warnung bei unbekannten Spalten im Report (welche Spalten, welche Datei)
- Genauer Ablauf, wie Pandera-`SchemaErrors` pro Datei gesammelt und mit Dateinamen anreichert an den Report weitergereicht werden
