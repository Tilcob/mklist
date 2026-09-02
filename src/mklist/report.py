"""Report-Erzeugung (Phase 7).

Definiert ein formatneutrales, internes Report-Datenmodell (ReportData) und
zwei Renderer (Markdown + HTML), siehe mklist-report-konzept.md.

Design-Hinweis zur Reihenfolge: Der Implementierungsplan sieht vor, das
Report-Modell "während der Phasen 3-5" zu befüllen. Da diese Phasen bereits
saubere, eigenständige Ergebnisobjekte zurückgeben (FileValidationResult,
AggregationResult, ResultValidationResult), wird build_report() stattdessen
NACH Abschluss dieser Phasen aus deren Ergebnisobjekten zusammengesetzt –
inhaltlich gleichwertig ("nicht aus Logs rekonstruiert", sondern aus
strukturierten Objekten), aber ohne die Validierungs-/Aggregationsmodule
mit Report-Belangen zu koppeln.

--strict-Eskalation (Warnungen -> Fehler) ist NICHT Aufgabe dieses Moduls:
das entscheidet die Orchestrierung in Phase 8, bevor build_report()
aufgerufen wird (z. B. indem Warnungen vor dem Aufruf in Fehler
umgewandelt werden). ReportData.header.strict ist hier nur Information für
die Anzeige im Kopfbereich.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .aggregator import AggregationResult
from .loader import FileLoadError
from .template import TemplateConfig
from .validation_input import FileValidationResult
from .validation_result import ResultValidationResult, check_sum_consistency

_SUM_DISPLAY_DECIMALS = 2


# ---------------------------------------------------------------------------
# Datenmodell
# ---------------------------------------------------------------------------


@dataclass
class ReportHeader:
    template_name: str
    template_version: str
    timestamp: datetime
    input_dir: str
    file_count: int
    dry_run: bool
    strict: bool
    output_path: str | None  # tatsächlicher ODER bei --dry-run geplanter Pfad


@dataclass
class ReportFileEntry:
    filename: str
    row_count: int | None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        if self.errors:
            return "error"
        if self.warnings:
            return "warning"
        return "ok"


@dataclass
class ReportAggregationSummary:
    input_row_count: int
    result_row_count: int
    sums_before: dict[str, float]
    sums_after: dict[str, float]
    sum_check_passed: bool

    @property
    def duplicates_merged(self) -> int:
        return self.input_row_count - self.result_row_count


@dataclass
class ReportData:
    header: ReportHeader
    files: list[ReportFileEntry] = field(default_factory=list)
    aggregation: ReportAggregationSummary | None = None
    # Fehler ohne Bezug zu einer einzelnen Datei, z. B. Duplikat-Check oder
    # Summen-Check aus Phase 5, oder Dateien, die gar nicht erst lesbar waren.
    abort_errors: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        if self.abort_errors or any(f.status == "error" for f in self.files):
            return "error"
        if self.total_warnings > 0:
            return "success_with_warnings"
        return "success"

    @property
    def total_warnings(self) -> int:
        return sum(len(f.warnings) for f in self.files)


_STATUS_LABELS = {
    "success": "Erfolg",
    "success_with_warnings": "Erfolg mit Warnungen",
    "error": "Fehler",
    "ok": "OK",
    "warning": "Warnung",
}


# ---------------------------------------------------------------------------
# build_report – ReportData aus den Ergebnisobjekten der Phasen 2-6 bauen
# ---------------------------------------------------------------------------


def build_report(
    *,
    template: TemplateConfig,
    input_dir: Path | str,
    dry_run: bool,
    strict: bool,
    file_load_errors: list[FileLoadError],
    file_validation_results: list[FileValidationResult],
    aggregation_result: AggregationResult | None,
    output_path: Path | str | None,
    timestamp: datetime | None = None,
) -> ReportData:
    """Baut ReportData aus den Ergebnissen der vorangegangenen Phasen.

    result_validation wird hier NICHT als Parameter übernommen, sondern
    der Summen-Check wird über check_sum_consistency() direkt aus
    aggregation_result neu berechnet – das ist dieselbe reine, seiteneffekt-
    freie Funktion, die auch Phase 5 verwendet, vermeidet aber, Fehler-
    Strings aus ResultValidationResult per Text-Matching wieder in
    "war es der Summen-Check?" zurückübersetzen zu müssen.
    """
    files = [
        ReportFileEntry(
            filename=fvr.filename,
            row_count=len(fvr.df) if fvr.df is not None else None,
            errors=[e.message for e in fvr.errors],
            warnings=[w.message for w in fvr.warnings],
        )
        for fvr in file_validation_results
    ]

    abort_errors = [str(exc) for exc in file_load_errors]

    aggregation_summary = None
    if aggregation_result is not None:
        sum_issues = check_sum_consistency(aggregation_result)
        aggregation_summary = ReportAggregationSummary(
            input_row_count=aggregation_result.input_row_count,
            result_row_count=aggregation_result.result_row_count,
            sums_before=aggregation_result.sums_before,
            sums_after=aggregation_result.sums_after,
            sum_check_passed=not sum_issues,
        )
        abort_errors.extend(issue.message for issue in sum_issues)

    header = ReportHeader(
        template_name=template.template_name,
        template_version=template.version,
        timestamp=timestamp or datetime.now(),
        input_dir=str(input_dir),
        file_count=len(file_validation_results) + len(file_load_errors),
        dry_run=dry_run,
        strict=strict,
        output_path=str(output_path) if output_path else None,
    )

    return ReportData(
        header=header,
        files=files,
        aggregation=aggregation_summary,
        abort_errors=abort_errors,
    )


def add_result_validation_errors(
    report_data: ReportData, result_validation: ResultValidationResult
) -> None:
    """Trägt zusätzliche Ebene-3-Fehler (z. B. Duplikat-Check, validation_rules)
    aus Phase 5 in einen bereits gebauten ReportData ein. Separat von
    build_report(), da result_validation erst nach dem eigentlichen Schreib-
    Entscheid (Phase 6) vollständig vorliegt und nicht jeder Aufrufer beide
    Schritte in einem Zug hat."""
    report_data.abort_errors.extend(e.message for e in result_validation.errors)


# ---------------------------------------------------------------------------
# Markdown-Renderer
# ---------------------------------------------------------------------------


def render_markdown(report_data: ReportData) -> str:
    h = report_data.header
    lines: list[str] = []

    lines.append(f"# mklist Report – {h.template_name}")
    lines.append("")
    if h.dry_run:
        lines.append("**DRY RUN – es wurde keine Ausgabedatei geschrieben.**")
        lines.append("")

    lines.append("## Kopfbereich")
    lines.append(f"- Vorlage: {h.template_name} (Version {h.template_version})")
    lines.append(f"- Zeitpunkt: {h.timestamp:%Y-%m-%d %H:%M:%S}")
    lines.append(f"- Eingabeordner: {h.input_dir}")
    lines.append(f"- Gefundene Dateien: {h.file_count}")
    mode_parts = []
    if h.dry_run:
        mode_parts.append("dry-run")
    if h.strict:
        mode_parts.append("strict")
    lines.append(f"- Modus: {', '.join(mode_parts) if mode_parts else 'normal'}")
    if h.output_path:
        label = "Geplanter Ausgabepfad" if h.dry_run else "Ausgabepfad"
        lines.append(f"- {label}: {h.output_path}")
    lines.append("")

    lines.append("## Zusammenfassung")
    lines.append(f"- Status: {_STATUS_LABELS[report_data.status]}")
    lines.append(f"- Verarbeitete Dateien: {len(report_data.files)}")
    lines.append(f"- Warnungen gesamt: {report_data.total_warnings}")
    if report_data.aggregation:
        lines.append(
            f"- Zusammengeführte Duplikate: {report_data.aggregation.duplicates_merged}"
        )
        check_label = (
            "bestanden"
            if report_data.aggregation.sum_check_passed
            else "fehlgeschlagen"
        )
        lines.append(f"- Summen-Check: {check_label}")
    lines.append("")

    lines.append("## Datei-Details")
    if not report_data.files:
        lines.append("Keine Dateien verarbeitet.")
    for f in report_data.files:
        lines.append(f"### {f.filename} – {_STATUS_LABELS[f.status]}")
        if f.row_count is not None:
            lines.append(f"- Zeilen: {f.row_count}")
        for err in f.errors:
            lines.append(f"- Fehler: {err}")
        for warn in f.warnings:
            lines.append(f"- Warnung: {warn}")
        lines.append("")

    if report_data.aggregation:
        agg = report_data.aggregation
        lines.append("## Aggregations-Ergebnis")
        lines.append(f"- Zeilen vor Aggregation: {agg.input_row_count}")
        lines.append(f"- Zeilen im Ergebnis: {agg.result_row_count}")
        for column, before in agg.sums_before.items():
            after = agg.sums_after.get(column)
            lines.append(
                f"- Summe '{column}': vorher = {round(before, _SUM_DISPLAY_DECIMALS)}, "
                f"nachher = {round(after, _SUM_DISPLAY_DECIMALS) if after is not None else 'n/a'}"
            )
        lines.append("")

    if report_data.abort_errors:
        lines.append("## Abbruch-Fehler")
        for err in report_data.abort_errors:
            lines.append(f"- {err}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# HTML-Renderer
# ---------------------------------------------------------------------------


_HTML_STYLE = """
body { font-family: sans-serif; margin: 2rem; color: #1a1a1a; }
h1 { border-bottom: 2px solid #ccc; padding-bottom: 0.3rem; }
h2 { margin-top: 2rem; }
.status-success { color: #1a7a1a; font-weight: bold; }
.status-success_with_warnings { color: #b36b00; font-weight: bold; }
.status-error { color: #b30000; font-weight: bold; }
.status-ok { color: #1a7a1a; }
.status-warning { color: #b36b00; }
.file-block { border-left: 4px solid #ccc; padding-left: 1rem; margin-bottom: 1rem; }
.file-block.status-error { border-left-color: #b30000; }
.file-block.status-warning { border-left-color: #b36b00; }
.file-block.status-ok { border-left-color: #1a7a1a; }
.dry-run-banner { background: #fff3cd; border: 1px solid #f0c674; padding: 0.75rem; margin-bottom: 1.5rem; }
table { border-collapse: collapse; margin-top: 0.5rem; }
td, th { border: 1px solid #ccc; padding: 0.3rem 0.6rem; text-align: left; }
"""


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def render_html(report_data: ReportData) -> str:
    h = report_data.header
    parts: list[str] = []

    parts.append("<!DOCTYPE html>")
    parts.append('<html lang="de"><head><meta charset="utf-8">')
    parts.append(f"<title>mklist Report – {_escape(h.template_name)}</title>")
    parts.append(f"<style>{_HTML_STYLE}</style></head><body>")

    parts.append(f"<h1>mklist Report – {_escape(h.template_name)}</h1>")

    if h.dry_run:
        parts.append(
            '<div class="dry-run-banner">DRY RUN – es wurde keine Ausgabedatei geschrieben.</div>'
        )

    parts.append("<h2>Kopfbereich</h2><ul>")
    parts.append(
        f"<li>Vorlage: {_escape(h.template_name)} (Version {_escape(h.template_version)})</li>"
    )
    parts.append(f"<li>Zeitpunkt: {h.timestamp:%Y-%m-%d %H:%M:%S}</li>")
    parts.append(f"<li>Eingabeordner: {_escape(h.input_dir)}</li>")
    parts.append(f"<li>Gefundene Dateien: {h.file_count}</li>")
    mode_parts = []
    if h.dry_run:
        mode_parts.append("dry-run")
    if h.strict:
        mode_parts.append("strict")
    parts.append(f"<li>Modus: {', '.join(mode_parts) if mode_parts else 'normal'}</li>")
    if h.output_path:
        label = "Geplanter Ausgabepfad" if h.dry_run else "Ausgabepfad"
        parts.append(f"<li>{label}: {_escape(h.output_path)}</li>")
    parts.append("</ul>")

    parts.append("<h2>Zusammenfassung</h2><ul>")
    parts.append(
        f'<li>Status: <span class="status-{report_data.status}">'
        f"{_STATUS_LABELS[report_data.status]}</span></li>"
    )
    parts.append(f"<li>Verarbeitete Dateien: {len(report_data.files)}</li>")
    parts.append(f"<li>Warnungen gesamt: {report_data.total_warnings}</li>")
    if report_data.aggregation:
        parts.append(
            f"<li>Zusammengeführte Duplikate: {report_data.aggregation.duplicates_merged}</li>"
        )
        check_label = (
            "bestanden"
            if report_data.aggregation.sum_check_passed
            else "fehlgeschlagen"
        )
        check_class = (
            "status-ok" if report_data.aggregation.sum_check_passed else "status-error"
        )
        parts.append(
            f'<li>Summen-Check: <span class="{check_class}">{check_label}</span></li>'
        )
    parts.append("</ul>")

    parts.append("<h2>Datei-Details</h2>")
    if not report_data.files:
        parts.append("<p>Keine Dateien verarbeitet.</p>")
    for f in report_data.files:
        parts.append(f'<div class="file-block status-{f.status}">')
        parts.append(
            f'<h3>{_escape(f.filename)} – <span class="status-{f.status}">'
            f"{_STATUS_LABELS[f.status]}</span></h3>"
        )
        if f.row_count is not None:
            parts.append(f"<p>Zeilen: {f.row_count}</p>")
        if f.errors or f.warnings:
            parts.append("<ul>")
            for err in f.errors:
                parts.append(f'<li class="status-error">Fehler: {_escape(err)}</li>')
            for warn in f.warnings:
                parts.append(
                    f'<li class="status-warning">Warnung: {_escape(warn)}</li>'
                )
            parts.append("</ul>")
        parts.append("</div>")

    if report_data.aggregation:
        agg = report_data.aggregation
        parts.append("<h2>Aggregations-Ergebnis</h2>")
        parts.append(f"<p>Zeilen vor Aggregation: {agg.input_row_count}<br>")
        parts.append(f"Zeilen im Ergebnis: {agg.result_row_count}</p>")
        if agg.sums_before:
            parts.append(
                "<table><tr><th>Spalte</th><th>Summe vorher</th><th>Summe nachher</th></tr>"
            )
            for column, before in agg.sums_before.items():
                after = agg.sums_after.get(column)
                after_display = (
                    round(after, _SUM_DISPLAY_DECIMALS) if after is not None else "n/a"
                )
                parts.append(
                    f"<tr><td>{_escape(column)}</td>"
                    f"<td>{round(before, _SUM_DISPLAY_DECIMALS)}</td>"
                    f"<td>{after_display}</td></tr>"
                )
            parts.append("</table>")

    if report_data.abort_errors:
        parts.append("<h2>Abbruch-Fehler</h2><ul>")
        for err in report_data.abort_errors:
            parts.append(f'<li class="status-error">{_escape(err)}</li>')
        parts.append("</ul>")

    parts.append("</body></html>")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Schreiben: --report Basisname -> <basis>.md + <basis>.html
# ---------------------------------------------------------------------------


def default_report_base(input_dir: Path | str, template: TemplateConfig) -> Path:
    """Default-Basisname für den Report, falls --report nicht angegeben ist:
    <input-dir>/report_<template_name> (ohne Endung – write_report() hängt
    .md/.html an). Nutzt denselben Dateinamen-Sanitizer wie
    writer.default_output_path(), damit beide Default-Pfade konsistent
    denselben Namen verwenden."""
    from .writer import _sanitize_filename

    input_dir = Path(input_dir)
    safe_name = _sanitize_filename(template.template_name)
    return input_dir / f"report_{safe_name}"


def _resolve_report_base(path: Path) -> Path:
    """Falls der übergebene Pfad bereits mit .md/.html endet, wird die
    Endung entfernt, um Doppel-Endungen wie 'report.md.md' zu vermeiden.
    Ansonsten wird der Pfad unverändert als Basisname verwendet."""
    if path.suffix.lower() in (".md", ".html"):
        return path.with_name(path.stem)
    return path


def write_report(report_data: ReportData, base_path: Path | str) -> tuple[Path, Path]:
    """Schreibt Markdown- und HTML-Report aus einem gemeinsamen Basisnamen.
    Erstellt den Zielordner, falls er noch nicht existiert."""
    base = _resolve_report_base(Path(base_path))
    md_path = Path(f"{base}.md")
    html_path = Path(f"{base}.html")

    base.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(render_markdown(report_data), encoding="utf-8")
    html_path.write_text(render_html(report_data), encoding="utf-8")

    return md_path, html_path
