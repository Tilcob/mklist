# mklist – Report-Konzept

Konzept für die Abschlussberichte, die `mklist run` (auch bei `--dry-run`) am Ende der Verarbeitung erzeugt.

---

## 1. Format

- Es werden **immer beide** Formate erzeugt: **Markdown (`.md`)** und **HTML (`.html`)**.
- Das `--report`-Flag im CLI gibt nur den **Speicherort/Basisnamen** an, keine Formatwahl. Beispiel:
  ```bash
  mklist run --template templates/standard.json --input-dir ./messwerte/ --report ./report
  ```
  erzeugt:
  ```
  ./report.md
  ./report.html
  ```
- **Korrektur gegenüber dem ursprünglichen CLI-Konzept:** Dort war `--report` noch mit fixer `.report.txt`-Endung vorgesehen — das wird hiermit ersetzt durch obiges Verhalten (zwei Dateien, `.md` + `.html`, aus einem Basisnamen).
- **HTML** ist das primäre Format für die alltägliche Nutzung (Doppelklick öffnet im Browser, farbliche Hervorhebung von Fehlern/Warnungen möglich, auch für nicht-technische Kollegen gut lesbar). **Markdown** ist das sekundäre Format (z. B. für Versionierung in Git, Diffing, einfaches Editieren).
- Beide Formate werden aus einem gemeinsamen, formatneutralen internen Report-Datenmodell erzeugt (erst Daten sammeln, dann in beide Zielformate rendern) — vermeidet doppelte Logik.

---

## 2. Ausführlichkeit

Der Report ist **immer vollständig detailliert**, unabhängig davon, ob der Lauf erfolgreich war, Warnungen enthielt, oder mit einem Abbruch-Fehler endete. Es gibt keine verkürzte Variante für den „alles OK“-Fall — auch bei einem sauberen Lauf soll nachvollziehbar bleiben, was genau passiert ist (welche Dateien, wie viele Zeilen, wie viele Duplikate zusammengeführt wurden).

---

## 3. Struktur des Reports

```
1. Kopfbereich
   - Vorlage: Name, Version
   - Zeitpunkt der Ausführung
   - Eingabeordner, Anzahl gefundener Dateien
   - Modus: normal / --dry-run / --strict
   - Bei --dry-run: deutliche Kennzeichnung „DRY RUN – es wurde keine Ausgabedatei geschrieben“

2. Zusammenfassung (ganz oben, auf einen Blick)
   - Status: Erfolg / Erfolg mit Warnungen / Fehler
   - Anzahl verarbeiteter Dateien
   - Gesamtzahl Warnungen (feingranular gezählt, z. B. eine unbekannte Spalte = eine Warnung)
   - Anzahl gefundener Duplikate
   - Summen-Check: bestanden / fehlgeschlagen

3. Datei-für-Datei-Details (Ebene 2)
   - Pro Datei: Status, Anzahl Zeilen, Warnungen — gruppiert pro Datei aufgelistet, eine Zeile pro Warnung
   - Format für unbekannte Spalten: Datei "<dateiname>": unbekannte Spalte "<spaltenname>" — eine Zeile je unbekannter Spalte, keine Zusammenfassung mehrerer Spalten in einer Zeile
   - Übersprungene leere Zeilen weiterhin mit Zeilennummer (im Gegensatz zu unbekannten Spalten, die sich auf die ganze Spalte beziehen und daher keine Zeilennummer benötigen)

4. Aggregations-Ergebnis (Ebene 3)
   - Anzahl Zeilen im Ergebnis (nach Zusammenfassen)
   - Summen-Vergleich: Summe vorher vs. nachher (muss exakt — auf 2 Nachkommastellen gerundet — übereinstimmen)

5. Abbruch-Fehler (falls vorhanden, prominent hervorgehoben — im HTML farblich in Rot)
```

### Farbcodierung (HTML)

| Status | Farbe |
|---|---|
| Erfolg / OK | Grün |
| Warnung | Gelb/Orange |
| Fehler | Rot |

Keine Emojis oder Symbole — Status wird ausschließlich über Text und Farbcodierung vermittelt, nicht über Icons.

---

## 4. Verhalten bei `--dry-run`

Der Report wird auch bei `--dry-run` vollständig erzeugt (beide Formate), obwohl keine `output.xlsx` geschrieben wird. Der Kopfbereich weist deutlich darauf hin, dass es sich um einen Trockenlauf handelt, damit beim späteren Lesen kein Missverständnis entsteht (z. B. dass eine Datei erzeugt wurde, obwohl das nicht der Fall war).

---

## 5. Sprache

- Nur **Deutsch**. Keine i18n-Struktur, keine Sprachdateien oder Text-Mappings — bewusste Vereinfachung für den aktuellen Bedarf.
- Texte werden direkt im Code/in den Templates verwendet, ohne zusätzliche Abstraktionsebene.
- Eine spätere Erweiterung auf weitere Sprachen würde bei Bedarf ein eigenes Refactoring erfordern — das wird aktuell nicht vorbereitet.

---

## 6. Zusammenfassung der Entscheidungen

| Punkt | Entscheidung |
|---|---|
| Format | Immer beide: `.md` + `.html`, `--report` gibt nur den Basisnamen an |
| Primärformat | HTML (alltägliche Nutzung), Markdown sekundär (Versionierung/Diffing) |
| Ausführlichkeit | Immer vollständig, unabhängig vom Ergebnis |
| `--dry-run` | Report wird trotzdem geschrieben, mit klarer Kennzeichnung |
| Sprache | Nur Deutsch, keine i18n-Vorbereitung |

---

## 7. Noch offen für die nächste Ausarbeitungsstufe

- Konkretes internes Report-Datenmodell (welche Felder/Objekte genau gesammelt werden)
- HTML-Template inkl. einfachem CSS für Farbcodierung (Erfolg/Warnung/Fehler)
- Markdown-Template-Struktur (Tabellen vs. Listen für die Datei-Details)
- Exakte Formulierung der Statustexte und Fehlermeldungen
