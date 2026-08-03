import json
from pathlib import Path

from click.testing import CliRunner

from cie_inspector import __version__
from cie_inspector.cli import EXIT_INPUT_ERROR, EXIT_STRICT_UNRESOLVED, cli


def test_version() -> None:
    result = CliRunner().invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_scan_json(ws_basic: Path) -> None:
    result = CliRunner().invoke(cli, ["scan", str(ws_basic)])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert {p["name"] for p in data["packages"]} == {"demo_pkg", "component_pkg", "py_pkg"}


def test_extract_json(ws_basic: Path) -> None:
    result = CliRunner().invoke(cli, ["extract", str(ws_basic)])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["schema_version"] == "0.1"
    talker = next(n for n in data["nodes"] if n["executable"] == "talker")
    assert {g["id"] for g in talker["callback_groups"]} >= {
        "sensor_group_",
        "worker_group_",
        "default_group",
    }


def test_extract_package_filter(ws_basic: Path) -> None:
    result = CliRunner().invoke(cli, ["extract", str(ws_basic), "--package", "demo_pkg"])
    data = json.loads(result.output)
    assert {n["package"] for n in data["nodes"]} == {"demo_pkg"}


def test_extract_table(ws_basic: Path) -> None:
    result = CliRunner().invoke(cli, ["extract", str(ws_basic), "--format", "table"])
    assert result.exit_code == 0
    assert "demo_pkg/talker" in result.output
    assert "sensor_group_" in result.output


def test_missing_workspace_is_input_error() -> None:
    result = CliRunner().invoke(cli, ["extract", "/nonexistent/path"])
    assert result.exit_code == EXIT_INPUT_ERROR


def test_strict_flags_unresolved(ws_edge: Path, ws_basic: Path) -> None:
    result = CliRunner().invoke(cli, ["extract", str(ws_edge), "--strict"])
    assert result.exit_code == EXIT_STRICT_UNRESOLVED
    result = CliRunner().invoke(cli, ["extract", str(ws_basic), "--strict"])
    assert result.exit_code == 0


def test_output_file(ws_basic: Path, tmp_path: Path) -> None:
    out = tmp_path / "inv.json"
    result = CliRunner().invoke(cli, ["extract", str(ws_basic), "-o", str(out)])
    assert result.exit_code == 0
    assert json.loads(out.read_text())["nodes"]
