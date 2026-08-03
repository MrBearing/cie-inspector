"""Combine Phase 1 (workspace scan) and Phase 2 (C++ extraction) into an Inventory."""

from __future__ import annotations

import re
from pathlib import Path

from cie_inspector.extract.cpp import analyze_executable_sources
from cie_inspector.extract.workspace import scan_workspace
from cie_inspector.models import ExecutableInfo, Inventory, NodeReport, UnresolvedItem


def _narrow_component_sources(pkg_dir: Path, exe: ExecutableInfo) -> list[str]:
    """A component library often holds several plugins; keep only the sources
    that clearly belong to this plugin class (register macro, else class
    definition). Falls back to all library sources — best-effort by design."""
    if exe.kind != "component" or not exe.plugin_class or len(exe.sources) <= 1:
        return exe.sources
    class_name = exe.plugin_class.rsplit("::", 1)[-1]
    macro_re = re.compile(
        r"RCLCPP_COMPONENTS_REGISTER_NODE\s*\(\s*" + re.escape(exe.plugin_class) + r"\s*\)"
    )
    class_re = re.compile(r"\bclass\s+" + re.escape(class_name) + r"\b")
    macro_hits: list[str] = []
    class_hits: list[str] = []
    for rel in exe.sources:
        try:
            text = (pkg_dir / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if macro_re.search(text):
            macro_hits.append(rel)
        if class_re.search(text):
            class_hits.append(rel)
    return macro_hits or class_hits or exe.sources


def build_inventory(src_dir: Path, packages: tuple[str, ...] = ()) -> Inventory:
    scan = scan_workspace(src_dir)
    inventory = Inventory(workspace=str(src_dir))
    for pkg in scan.packages:
        if packages and pkg.name not in packages:
            continue
        pkg_dir = src_dir / pkg.path
        for item in pkg.unresolved:
            inventory.scan_unresolved.append(
                UnresolvedItem(
                    kind=item.kind,
                    reason=item.reason,
                    declared_at=f"{pkg.path}/{item.declared_at}" if item.declared_at else pkg.path,
                )
            )
        for exe in pkg.executables:
            analysis = analyze_executable_sources(pkg_dir, _narrow_component_sources(pkg_dir, exe))
            inventory.nodes.append(
                NodeReport(
                    package=pkg.name,
                    executable=exe.name,
                    kind=exe.kind,
                    plugin_class=exe.plugin_class,
                    node_hint=analysis.node_hint,
                    node_name=analysis.node_name,
                    callback_groups=analysis.callback_groups,
                    publishers=analysis.publishers,
                    unresolved=list(exe.unresolved) + analysis.unresolved,
                )
            )
        for ep in pkg.python_entry_points:
            inventory.unsupported.append(
                UnresolvedItem(
                    kind="python_node",
                    reason=(
                        f"rclpy source analysis is not supported in v1 "
                        f"(entry point '{ep.name} = {ep.target}')"
                    ),
                    declared_at=pkg.path,
                )
            )
    inventory.nodes.sort(key=lambda n: (n.package, n.executable))
    return inventory
