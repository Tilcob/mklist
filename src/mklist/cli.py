"""CLI (Phase 8) – bindet Phase 1-7 zu den drei Subcommands zusammen.

Siehe mklist-cli-konzept.md für die vollständige Spezifikation von
Flags, Exit Codes und CSV-Format.

Kernentscheidung zur Fehlerbehandlung (siehe mklist-konzept.md, Abschnitt
"Fehlerbehandlung – Philosophie"): sobald IRGENDEINE Datei einen
Abbruch-Fehler hat (fehlende Pflichtspalte, falscher Typ, nicht lesbare
Datei, oder bei --strict eine eskalierte Warnung), wird der GESAMTE Lauf
abgebrochen – es werden keine "nur die guten Dateien" zusammengeführt.
Grund: ein still übersprungener Teil der Daten würde den Summen-Check
wertlos machen, da dieser dann nur die (unvollständigen) verbliebenen
Daten mit sich selbst vergleicht, ohne dass sichtbar wird, dass ganze
Dateien fehlen.
"""

from __future__ import annotations

import sys
from pathlib import Path

import click

from .aggregator import merge_and_aggregate
from .loader import FileLoadError, load_input_files
from .report import (
    add_result_validation_errors,
    build_report,
    default_report_base,
    write_report,
)
from .template import TemplateLoadError, load_template
from .validation_input import validate_input_file
from .validation_result import validate_result
from .writer import resolve_output_path, write_result

EXIT_SUCCESS = 0
EXIT_ERROR = 1
EXIT_SUCCESS_WITH_WARNINGS = 2


@click.group()
def cli() -> None:
    """mklist – Zusammenführen mehrerer gleich aufgebauter Excel-/CSV-Listen
    anhand einer Vorlage: Duplikate erkennen, Werte aggregieren, Ergebnis
    validieren und als Excel-Datei ausgeben."""


# ---------------------------------------------------------------------------
# mklist validate-template
# ---------------------------------------------------------------------------


@cli.command("validate-template")
@click.option(
    "--template",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Pfad zur Vorlagen-JSON-Datei.",
)
def validate_template_command(template: Path) -> None:
    """Prüft nur die Vorlage, ohne Eingabedateien anzufassen."""
    try:
        config = load_template(template)
    except TemplateLoadError as exc:
        click.echo(str(exc), err=True)
        sys.exit(EXIT_ERROR)

    click.echo(f"Vorlage gültig: {config.template_name} (Version {config.version})")
    sys.exit(EXIT_SUCCESS)


# ---------------------------------------------------------------------------
# mklist list-templates
# ---------------------------------------------------------------------------


@cli.command("list-templates")
@click.option(
    "--template-dir",
    required=True,
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="Ordner mit Vorlagen-JSON-Dateien.",
)
def list_templates_command(template_dir: Path) -> None:
    """Listet alle Vorlagen (*.json) in einem Ordner mit Name und Version auf."""
    json_files = sorted(template_dir.glob("*.json"))

    if not json_files:
        click.echo(f"Keine Vorlagen (*.json) gefunden in: {template_dir}")
        return

    for path in json_files:
        try:
            config = load_template(path)
        except TemplateLoadError as exc:
            click.echo(f"{path.name}: UNGÜLTIG – {exc}", err=True)
            continue
        click.echo(f"{path.name}: {config.template_name} (Version {config.version})")


# ---------------------------------------------------------------------------
# mklist run
# ---------------------------------------------------------------------------


@cli.command("run")
@click.option(
    "--template",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Pfad zur Vorlagen-JSON-Datei.",
)
@click.option(
    "--input-dir",
    required=True,
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="Ordner mit den einzulesenden .xlsx/.xls/.csv-Dateien.",
)
@click.option(
    "--output",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Pfad der Ausgabedatei (.xlsx). Default: <input-dir>/ergebnis_<template_name>.xlsx",
)
@click.option(
    "--report",
    "report_base",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Basisname für den Report (.md + .html). Default: <input-dir>/report_<template_name>",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Zeigt das Ergebnis an, ohne eine Ausgabedatei zu schreiben. Der Report wird trotzdem erzeugt.",
)
@click.option(
    "--strict",
    is_flag=True,
    default=False,
    help="Jede Warnung führt zum Abbruch statt nur zur Meldung.",
)
def run_command(
    template: Path,
    input_dir: Path,
    output: Path | None,
    report_base: Path | None,
    dry_run: bool,
    strict: bool,
) -> None:
    """Führt Listen anhand einer Vorlage zusammen: Duplikate erkennen,
    aggregieren, validieren, als Excel-Datei ausgeben."""

    # -- Phase 1: Vorlage laden ----------------------------------------
    try:
        config = load_template(template)
    except TemplateLoadError as exc:
        click.echo(str(exc), err=True)
        sys.exit(EXIT_ERROR)

    # -- Phase 2: Dateien einlesen --------------------------------------
    try:
        loaded_files, file_load_errors = load_input_files(input_dir)
    except FileLoadError as exc:
        click.echo(str(exc), err=True)
        sys.exit(EXIT_ERROR)

    for load_error in file_load_errors:
        click.echo(f"Fehler beim Lesen: {load_error}")

    # -- Phase 3: Rohdaten-Validierung pro Datei ------------------------
    file_validation_results = []
    for loaded in loaded_files:
        result = validate_input_file(loaded, config)

        if strict and result.warnings:
            # --strict: Warnungen werden zu Abbruch-Fehlern (Variante a,
            # siehe mklist-cli-konzept.md, Abschnitt 5).
            result.errors.extend(result.warnings)
            result.warnings = []
            result.df = None

        if result.errors:
            first = result.errors[0].message
            extra = (
                f" (+{len(result.errors) - 1} weitere)"
                if len(result.errors) > 1
                else ""
            )
            click.echo(f"Lese {result.filename} ... Fehler: {first}{extra}")
        elif result.warnings:
            click.echo(
                f"Lese {result.filename} ... OK ({len(result.warnings)} Warnungen)"
            )
        else:
            click.echo(f"Lese {result.filename} ... OK")

        file_validation_results.append(result)

    has_file_errors = bool(file_load_errors) or any(
        not r.is_valid for r in file_validation_results
    )

    # -- Phase 4 + 5: Zusammenführen, Aggregation, Ergebnis-Validierung -
    # Läuft nur, wenn KEINE Datei einen Abbruch-Fehler hat (siehe Modul-
    # Docstring: kein teilweises Zusammenführen "nur der guten Dateien").
    aggregation_result = None
    result_validation = None

    if not has_file_errors:
        valid_dfs = [r.df for r in file_validation_results if r.df is not None]
        aggregation_result = merge_and_aggregate(valid_dfs, config)
        result_validation = validate_result(aggregation_result, config)

    # -- Phase 6: Ausgabe schreiben (außer bei --dry-run oder Fehlern) --
    output_path = resolve_output_path(output, input_dir, config)
    file_was_written = False

    if aggregation_result is not None and result_validation is not None:
        if result_validation.is_valid and not dry_run:
            write_result(aggregation_result.df, output_path)
            file_was_written = True

    # -- Phase 7: Report bauen und schreiben -----------------------------
    report_data = build_report(
        template=config,
        input_dir=input_dir,
        dry_run=dry_run,
        strict=strict,
        file_load_errors=file_load_errors,
        file_validation_results=file_validation_results,
        aggregation_result=aggregation_result,
        output_path=output_path,
    )
    if result_validation is not None:
        add_result_validation_errors(report_data, result_validation)

    resolved_report_base = report_base or default_report_base(input_dir, config)
    md_path, html_path = write_report(report_data, resolved_report_base)

    # -- Zusammenfassung + Exit Code --------------------------------------
    click.echo("")
    click.echo(f"Status: {report_data.status}")
    click.echo(f"Verarbeitete Dateien: {len(report_data.files)}")
    click.echo(f"Warnungen gesamt: {report_data.total_warnings}")
    if file_was_written:
        click.echo(f"Ausgabedatei: {output_path}")
    elif dry_run:
        click.echo(f"DRY RUN – keine Ausgabedatei geschrieben (geplant: {output_path})")
    click.echo(f"Report: {md_path}, {html_path}")

    if report_data.status == "error":
        sys.exit(EXIT_ERROR)
    if report_data.status == "success_with_warnings":
        sys.exit(EXIT_SUCCESS_WITH_WARNINGS)
    sys.exit(EXIT_SUCCESS)


if __name__ == "__main__":
    cli()
