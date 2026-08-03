"""Phase 3: merge a roscope-resolved launch XML into the inventory.

roscope (https://github.com/paulsohn/roscope) emits fully-resolved launch XML
(includes inlined, conditionals evaluated, substitutions applied). We read the
<node> elements, match them to scanned executables by (pkg, exec), apply the
remaps to declared topic names, and keep everything that cannot be matched as
`unmatched_launch_nodes` — nothing is silently dropped.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from cie_inspector.models import Inventory, LaunchInfo, UnmatchedLaunchNode


class RoscopeXmlError(Exception):
    """The resolved XML could not be read at all."""


@dataclass
class LaunchNode:
    package: str
    executable: str
    name: str
    namespace: str = "/"
    remaps: dict[str, str] = field(default_factory=dict)


def _tag(el: ET.Element) -> str:
    return el.tag.rsplit("}", 1)[-1]


def load_roscope_nodes(xml_path: Path) -> list[LaunchNode]:
    try:
        root = ET.parse(xml_path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise RoscopeXmlError(f"cannot read resolved launch XML {xml_path}: {exc}") from exc
    nodes: list[LaunchNode] = []
    for el in root.iter():
        if _tag(el) != "node":
            continue
        pkg = el.get("pkg") or el.get("package")
        exe = el.get("exec") or el.get("executable")
        if pkg is None or exe is None:
            continue
        remaps: dict[str, str] = {}
        for child in el:
            if _tag(child) == "remap":
                src = child.get("from")
                dst = child.get("to")
                if src and dst:
                    remaps[src] = dst
        nodes.append(
            LaunchNode(
                package=pkg,
                executable=exe,
                name=el.get("name") or exe,
                namespace=el.get("namespace") or el.get("ns") or "/",
                remaps=remaps,
            )
        )
    return nodes


def resolve_topic(declared: str, launch: LaunchNode) -> str:
    """Best-effort ROS name resolution: fully qualify with the namespace,
    then apply remaps matched against both the declared and qualified form."""
    if declared.startswith("/"):
        qualified = declared
    else:
        ns = launch.namespace.rstrip("/")
        qualified = f"{ns}/{declared}"
    return launch.remaps.get(declared) or launch.remaps.get(qualified) or qualified


def integrate(inventory: Inventory, launch_nodes: list[LaunchNode]) -> Inventory:
    """Narrow the inventory to launched nodes; one report per launch instance."""
    index = {(n.package, n.executable): n for n in inventory.nodes}
    result = inventory.model_copy(deep=True)
    result.nodes = []
    for launch in launch_nodes:
        base = index.get((launch.package, launch.executable))
        if base is None:
            result.unmatched_launch_nodes.append(
                UnmatchedLaunchNode(
                    package=launch.package,
                    executable=launch.executable,
                    node_name=launch.name,
                    reason="no matching executable found in the workspace scan",
                )
            )
            continue
        node = base.model_copy(deep=True)
        node.launch = LaunchInfo(
            node_name=launch.name, namespace=launch.namespace, remaps=dict(launch.remaps)
        )
        for group in node.callback_groups:
            for member in group.members:
                if member.declared_topic:
                    member.resolved_topic = resolve_topic(member.declared_topic, launch)
        for pub in node.publishers:
            if pub.declared_topic:
                pub.resolved_topic = resolve_topic(pub.declared_topic, launch)
        result.nodes.append(node)
    result.nodes.sort(
        key=lambda n: (n.package, n.executable, n.launch.node_name if n.launch else "")
    )
    return result
