from pathlib import Path

from cie_inspector.extract.inventory import build_inventory


def test_inventory_snapshot(ws_basic: Path, snapshot) -> None:
    inventory = build_inventory(ws_basic)
    data = inventory.model_dump(mode="json", exclude_none=True)
    data["workspace"] = "<workspace>"
    assert data == snapshot
