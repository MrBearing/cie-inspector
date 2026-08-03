"""Click entry point."""

from __future__ import annotations

import sys
from pathlib import Path

import click

from cie_inspector import CLI_NAME, __version__

# Exit codes (see README):
#   0 = success (unresolved entries are still success)
#   1 = input error (bad paths, unreadable inputs)
#   2 = analysis could not proceed at all
#   3 = --strict was given and unresolved entries exist
EXIT_OK = 0
EXIT_INPUT_ERROR = 1
EXIT_FATAL = 2
EXIT_STRICT_UNRESOLVED = 3


class InputError(click.ClickException):
    exit_code = EXIT_INPUT_ERROR


class FatalAnalysisError(click.ClickException):
    exit_code = EXIT_FATAL


def _workspace_path(value: str) -> Path:
    path = Path(value)
    if not path.is_dir():
        raise InputError(f"workspace source directory not found: {value}")
    return path


def _emit(text: str, output: str | None) -> None:
    if output:
        Path(output).write_text(text, encoding="utf-8")
    else:
        click.echo(text)


@click.group(name=CLI_NAME)
@click.version_option(__version__, prog_name=CLI_NAME)
def cli() -> None:
    """Extract ROS 2 callback/CallbackGroup structure from source, without building."""


@cli.command()
@click.argument("workspace_src")
@click.option("--format", "fmt", type=click.Choice(["json", "table"]), default="json")
@click.option("-o", "--output", default=None, help="Write output to a file instead of stdout.")
def scan(workspace_src: str, fmt: str, output: str | None) -> None:
    """Phase 1 only: map packages to executables and source files."""
    from cie_inspector.extract.workspace import scan_workspace
    from cie_inspector.render import render_scan_table

    report = scan_workspace(_workspace_path(workspace_src))
    if fmt == "table":
        _emit(render_scan_table(report), output)
    else:
        _emit(report.model_dump_json(indent=2, exclude_none=True), output)


@cli.command()
@click.argument("workspace_src")
@click.option(
    "--package",
    "packages",
    multiple=True,
    help="Limit extraction to these packages (repeatable).",
)
@click.option("--format", "fmt", type=click.Choice(["json", "table", "cie-yaml"]), default="json")
@click.option("-o", "--output", default=None, help="Write output to a file instead of stdout.")
@click.option(
    "--strict",
    is_flag=True,
    help="Exit with a non-zero status when unresolved entries exist.",
)
@click.pass_context
def extract(
    ctx: click.Context,
    workspace_src: str,
    packages: tuple[str, ...],
    fmt: str,
    output: str | None,
    strict: bool,
) -> None:
    """Phase 1+2: full callback/CallbackGroup inventory for all C++ nodes."""
    from cie_inspector.extract.inventory import build_inventory

    workspace = _workspace_path(workspace_src)
    try:
        inventory = build_inventory(workspace, packages)
    except Exception as exc:  # tree-sitter runtime failure etc.
        raise FatalAnalysisError(f"analysis failed: {exc}") from exc
    _emit_inventory(inventory, fmt, output)
    if strict and inventory.has_unresolved():
        ctx.exit(EXIT_STRICT_UNRESOLVED)


def _emit_inventory(inventory, fmt: str, output: str | None) -> None:
    from cie_inspector.render import render_cie_yaml, render_inventory_table

    if fmt == "table":
        _emit(render_inventory_table(inventory), output)
    elif fmt == "cie-yaml":
        _emit(render_cie_yaml(inventory), output)
    else:
        _emit(inventory.model_dump_json(indent=2, exclude_none=True), output)


@cli.command()
@click.argument("workspace_src")
@click.option(
    "--roscope-xml",
    required=True,
    help="Resolved launch XML produced by roscope.",
)
@click.option(
    "--package",
    "packages",
    multiple=True,
    help="Limit extraction to these packages (repeatable).",
)
@click.option("--format", "fmt", type=click.Choice(["json", "table", "cie-yaml"]), default="json")
@click.option("-o", "--output", default=None, help="Write output to a file instead of stdout.")
@click.option(
    "--strict",
    is_flag=True,
    help="Exit with a non-zero status when unresolved entries exist.",
)
@click.pass_context
def resolve(
    ctx: click.Context,
    workspace_src: str,
    roscope_xml: str,
    packages: tuple[str, ...],
    fmt: str,
    output: str | None,
    strict: bool,
) -> None:
    """Phase 1+2+3: inventory narrowed to launched nodes, with remaps applied."""
    from cie_inspector.extract.integrate import RoscopeXmlError, integrate, load_roscope_nodes
    from cie_inspector.extract.inventory import build_inventory

    workspace = _workspace_path(workspace_src)
    xml_path = Path(roscope_xml)
    if not xml_path.is_file():
        raise InputError(f"roscope XML not found: {roscope_xml}")
    try:
        launch_nodes = load_roscope_nodes(xml_path)
    except RoscopeXmlError as exc:
        raise InputError(str(exc)) from exc
    try:
        inventory = integrate(build_inventory(workspace, packages), launch_nodes)
    except Exception as exc:  # tree-sitter runtime failure etc.
        raise FatalAnalysisError(f"analysis failed: {exc}") from exc
    _emit_inventory(inventory, fmt, output)
    if strict and inventory.has_unresolved():
        ctx.exit(EXIT_STRICT_UNRESOLVED)


def main() -> None:
    sys.exit(cli.main(standalone_mode=True))


if __name__ == "__main__":
    main()
