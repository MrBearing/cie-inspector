import json
from pathlib import Path

from click.testing import CliRunner

from cie_inspector.cli import cli
from cie_inspector.extract.integrate import integrate, load_roscope_nodes
from cie_inspector.extract.inventory import build_inventory

ROSCOPE_XML = Path(__file__).parent / "fixtures" / "roscope" / "resolved.launch.xml"


def _resolved(ws_basic: Path):
    return integrate(build_inventory(ws_basic), load_roscope_nodes(ROSCOPE_XML))


def test_launch_nodes_parsed() -> None:
    nodes = load_roscope_nodes(ROSCOPE_XML)
    assert [(n.package, n.executable) for n in nodes] == [
        ("demo_pkg", "talker"),
        ("component_pkg", "listener"),
        ("other_pkg", "ghost"),
    ]
    assert nodes[0].remaps == {"/scan": "/lidar/scan", "chatter": "chatter_out"}


def test_inventory_narrowed_to_launched_nodes(ws_basic: Path) -> None:
    inventory = _resolved(ws_basic)
    assert {(n.package, n.executable) for n in inventory.nodes} == {
        ("demo_pkg", "talker"),
        ("component_pkg", "listener"),
    }
    talker = next(n for n in inventory.nodes if n.executable == "talker")
    assert talker.launch is not None
    assert talker.launch.node_name == "talker"
    assert talker.launch.namespace == "/robot1"


def test_remap_applied(ws_basic: Path) -> None:
    talker = next(n for n in _resolved(ws_basic).nodes if n.executable == "talker")
    members = {(m.kind, m.declared_topic): m for g in talker.callback_groups for m in g.members}
    scan = members[("subscription", "/scan")]
    assert scan.resolved_topic == "/lidar/scan"
    cmd = members[("subscription", "cmd")]
    assert cmd.resolved_topic == "/robot1/cmd"  # namespace applied, no remap
    (pub,) = talker.publishers
    assert pub.resolved_topic == "chatter_out"


def test_unmatched_node_is_kept(ws_basic: Path) -> None:
    inventory = _resolved(ws_basic)
    (unmatched,) = inventory.unmatched_launch_nodes
    assert (unmatched.package, unmatched.executable) == ("other_pkg", "ghost")
    assert inventory.has_unresolved()


def test_resolve_cli(ws_basic: Path) -> None:
    result = CliRunner().invoke(cli, ["resolve", str(ws_basic), "--roscope-xml", str(ROSCOPE_XML)])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert len(data["nodes"]) == 2
    assert data["unmatched_launch_nodes"][0]["executable"] == "ghost"


def test_resolve_missing_xml_is_input_error(ws_basic: Path) -> None:
    result = CliRunner().invoke(cli, ["resolve", str(ws_basic), "--roscope-xml", "/nope.xml"])
    assert result.exit_code == 1


def test_cie_yaml_output(ws_basic: Path) -> None:
    result = CliRunner().invoke(
        cli,
        ["resolve", str(ws_basic), "--roscope-xml", str(ROSCOPE_XML), "--format", "cie-yaml"],
    )
    assert result.exit_code == 0
    out = result.output
    assert "callback_groups:" in out
    assert "- id: /robot1/talker@Subscription(/lidar/scan)" in out
    assert "- id: /robot1/talker@Timer(500000000)" in out
    assert (
        "- id: /robot1/talker@Subscription(/robot1/cmd)"
        "@Service(/robot1/add_two_ints)@Client(/robot1/add_two_ints)" in out
    )
    assert "policy: TODO" in out
    assert "Publisher(" not in out  # publishers are not group members
