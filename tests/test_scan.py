from pathlib import Path

from cie_inspector.extract.workspace import scan_workspace


def test_scan_finds_packages(ws_basic: Path) -> None:
    report = scan_workspace(ws_basic)
    names = [p.name for p in report.packages]
    assert names == ["component_pkg", "demo_pkg", "py_pkg"]


def test_scan_cmake_executable(ws_basic: Path) -> None:
    report = scan_workspace(ws_basic)
    demo = next(p for p in report.packages if p.name == "demo_pkg")
    assert demo.build_type == "ament_cmake"
    talker = next(e for e in demo.executables if e.name == "talker")
    assert talker.kind == "executable"
    assert talker.sources == ["src/talker.cpp"]
    assert "rclcpp" in talker.dependencies
    assert not talker.unresolved


def test_scan_component(ws_basic: Path) -> None:
    report = scan_workspace(ws_basic)
    comp = next(p for p in report.packages if p.name == "component_pkg")
    listener = next(e for e in comp.executables if e.name == "listener")
    assert listener.kind == "component"
    assert listener.plugin_class == "component_pkg::Listener"
    assert listener.sources == ["src/listener_component.cpp"]


def test_scan_python_entry_points(ws_basic: Path) -> None:
    report = scan_workspace(ws_basic)
    py = next(p for p in report.packages if p.name == "py_pkg")
    assert py.build_type == "ament_python"
    assert [(e.name, e.target) for e in py.python_entry_points] == [
        ("py_talker", "py_pkg.talker:main")
    ]
    assert not py.python_entry_points[0].supported


def test_scan_set_variable_resolution(ws_edge: Path) -> None:
    report = scan_workspace(ws_edge)
    tricky = next(p for p in report.packages if p.name == "tricky_pkg")
    exe = next(e for e in tricky.executables if e.name == "tricky")
    assert exe.sources == ["src/tricky.cpp"]


def test_scan_unknown_variable_is_unresolved(ws_edge: Path) -> None:
    report = scan_workspace(ws_edge)
    tricky = next(p for p in report.packages if p.name == "tricky_pkg")
    mystery = next(e for e in tricky.executables if e.name == "mystery")
    assert mystery.sources == []
    reasons = " ".join(u.reason for u in tricky.unresolved)
    assert "UNKNOWN_SRCS" in reasons
