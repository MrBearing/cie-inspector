"""Smoke test against the real ros2/demos repository (shallow-cloned in CI).

Set CIE_DEMO_NODES_CPP to a checkout of https://github.com/ros2/demos to run.
"""

import os
from pathlib import Path

import pytest

DEMOS = os.environ.get("CIE_DEMO_NODES_CPP", "")

pytestmark = pytest.mark.skipif(
    not DEMOS or not Path(DEMOS).is_dir(),
    reason="CIE_DEMO_NODES_CPP not set to a ros2/demos checkout",
)


def test_demo_nodes_cpp_inventory() -> None:
    from cie_inspector.extract.inventory import build_inventory

    inventory = build_inventory(Path(DEMOS), packages=("demo_nodes_cpp",))
    executables = {n.executable for n in inventory.nodes}
    assert {"talker", "listener"} <= executables

    talker = next(n for n in inventory.nodes if n.executable == "talker")
    members = [m for g in talker.callback_groups for m in g.members]
    kinds = {m.kind for m in members}
    assert "timer" in kinds  # talker publishes on a wall timer
    assert any(p.declared_topic == "chatter" for p in talker.publishers)

    listener = next(n for n in inventory.nodes if n.executable == "listener")
    subs = [m for g in listener.callback_groups for m in g.members if m.kind == "subscription"]
    assert any(s.declared_topic == "chatter" for s in subs)
