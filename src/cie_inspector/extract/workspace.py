"""Phase 1: workspace scan — map packages to executables to source files.

CMakeLists.txt is parsed lightweight (comment stripping + paren matching +
token substitution of simple ``set()`` variables). Anything that still
contains an unexpanded ``${...}`` is recorded as unresolved, never guessed.
"""

from __future__ import annotations

import configparser
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from cie_inspector.models import (
    ExecutableInfo,
    PackageInfo,
    PythonEntryPoint,
    ScanReport,
    UnresolvedItem,
)

SOURCE_EXTS = {".c", ".cc", ".cpp", ".cxx"}

_CMAKE_CMD_RE = re.compile(r"(?m)^[ \t]*([A-Za-z_][A-Za-z0-9_]*)[ \t]*\(")
_CMAKE_VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
_ADD_EXECUTABLE_KEYWORDS = {"WIN32", "MACOSX_BUNDLE", "EXCLUDE_FROM_ALL"}
_ADD_LIBRARY_KEYWORDS = {"STATIC", "SHARED", "MODULE", "OBJECT", "INTERFACE", "EXCLUDE_FROM_ALL"}


def find_package_xmls(src_dir: Path) -> list[Path]:
    """All package.xml files under src_dir, skipping hidden and ignored dirs."""
    results: list[Path] = []
    for path in sorted(src_dir.rglob("package.xml")):
        rel_parts = path.relative_to(src_dir).parts
        if any(part.startswith(".") for part in rel_parts):
            continue
        pkg_dir = path.parent
        if (pkg_dir / "COLCON_IGNORE").exists() or (pkg_dir / "AMENT_IGNORE").exists():
            continue
        results.append(path)
    return results


def parse_package_xml(path: Path) -> tuple[str | None, str | None]:
    """Return (package name, build_type) — either may be None on malformed input."""
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return None, None
    name_el = root.find("name")
    name = name_el.text.strip() if name_el is not None and name_el.text else None
    build_type = None
    bt_el = root.find("./export/build_type")
    if bt_el is not None and bt_el.text:
        build_type = bt_el.text.strip()
    return name, build_type


# --------------------------------------------------------------------------
# CMakeLists.txt lightweight parsing
# --------------------------------------------------------------------------


def _strip_cmake_comments(text: str) -> str:
    out_lines = []
    for line in text.splitlines():
        in_quote = False
        cut = len(line)
        for i, ch in enumerate(line):
            if ch == '"':
                in_quote = not in_quote
            elif ch == "#" and not in_quote:
                cut = i
                break
        out_lines.append(line[:cut])
    return "\n".join(out_lines)


def iter_cmake_commands(text: str) -> list[tuple[str, list[str]]]:
    """Yield (command, args) pairs. Multi-line commands are handled; nesting
    inside argument lists (generator expressions etc.) is paren-counted."""
    text = _strip_cmake_comments(text)
    commands: list[tuple[str, list[str]]] = []
    pos = 0
    while True:
        m = _CMAKE_CMD_RE.search(text, pos)
        if m is None:
            break
        depth = 1
        i = m.end()
        in_quote = False
        while i < len(text) and depth > 0:
            ch = text[i]
            if ch == '"':
                in_quote = not in_quote
            elif not in_quote:
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
            i += 1
        body = text[m.end() : i - 1]
        tokens = [t.strip('"') for t in re.findall(r'"(?:[^"\\]|\\.)*"|[^\s()]+', body)]
        commands.append((m.group(1).lower(), tokens))
        pos = i
    return commands


class _CMakeScope:
    """Simple variable scope for token substitution."""

    def __init__(self, pkg_dir: Path) -> None:
        self.vars: dict[str, list[str]] = {
            "CMAKE_CURRENT_SOURCE_DIR": ["."],
            "CMAKE_SOURCE_DIR": ["."],
            "CMAKE_CURRENT_LIST_DIR": ["."],
        }
        self.pkg_dir = pkg_dir

    def expand(self, token: str) -> list[str] | None:
        """Expand a token; None means an unknown variable is involved."""
        if "${" not in token:
            return [token]
        m = _CMAKE_VAR_RE.fullmatch(token)
        if m:  # whole-token reference may expand to a list
            return self.vars.get(m.group(1))
        unknown = False

        def _sub(mm: re.Match[str]) -> str:
            nonlocal unknown
            values = self.vars.get(mm.group(1))
            if values is None or len(values) != 1:
                unknown = True
                return mm.group(0)
            return values[0]

        result = _CMAKE_VAR_RE.sub(_sub, token)
        if unknown or "${" in result:
            return None
        return [result]


def _expand_all(scope: _CMakeScope, tokens: list[str]) -> tuple[list[str], list[str]]:
    """Expand tokens; returns (resolved, unresolved_raw_tokens)."""
    resolved: list[str] = []
    unresolved: list[str] = []
    for token in tokens:
        values = scope.expand(token)
        if values is None:
            unresolved.append(token)
        else:
            resolved.extend(values)
    return resolved, unresolved


def parse_cmake(
    pkg_dir: Path, cmake_path: Path, rel_prefix: str = ""
) -> tuple[
    dict[str, ExecutableInfo],
    dict[str, list[str]],
    list[UnresolvedItem],
]:
    """Parse one CMakeLists.txt.

    Returns (executables by target, library sources by target, unresolved items).
    """
    executables: dict[str, ExecutableInfo] = {}
    libraries: dict[str, list[str]] = {}
    unresolved: list[UnresolvedItem] = []
    where = f"{rel_prefix}CMakeLists.txt"

    try:
        text = cmake_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        unresolved.append(UnresolvedItem(kind="cmake", reason=str(exc), declared_at=where))
        return executables, libraries, unresolved

    scope = _CMakeScope(pkg_dir)

    def _collect_sources(target: str, tokens: list[str], keywords: set[str]) -> list[str]:
        sources: list[str] = []
        resolved, raw_unresolved = _expand_all(scope, tokens)
        for token in raw_unresolved:
            unresolved.append(
                UnresolvedItem(
                    kind="source",
                    reason=f"unresolved variable in source list of '{target}': {token}",
                    declared_at=where,
                )
            )
        for value in resolved:
            if value in keywords:
                continue
            if Path(value).suffix.lower() not in SOURCE_EXTS:
                continue
            src_path = value.removeprefix("./")
            if not (pkg_dir / src_path).is_file():
                unresolved.append(
                    UnresolvedItem(
                        kind="source",
                        reason=f"source file of '{target}' not found: {src_path}",
                        declared_at=where,
                    )
                )
                continue
            sources.append(rel_prefix + src_path)
        return sources

    def _attach(target: str, attr: str, values: list[str]) -> None:
        exe = executables.get(target)
        if exe is not None:
            getattr(exe, attr).extend(v for v in values if v not in getattr(exe, attr))

    for cmd, args in iter_cmake_commands(text):
        if not args:
            continue
        if cmd == "project":
            scope.vars["PROJECT_NAME"] = [args[0]]
        elif cmd == "set":
            values, raw_unresolved = _expand_all(scope, args[1:])
            if not raw_unresolved:
                scope.vars[args[0]] = values
            else:
                scope.vars.pop(args[0], None)  # partially unknown → treat as unknown
        elif cmd in ("add_executable", "ament_auto_add_executable"):
            target_values = scope.expand(args[0])
            if target_values is None or len(target_values) != 1:
                unresolved.append(
                    UnresolvedItem(
                        kind="executable",
                        reason=f"unresolved executable target name: {args[0]}",
                        declared_at=where,
                    )
                )
                continue
            target = target_values[0]
            if "IMPORTED" in args or "ALIAS" in args:
                continue
            sources = _collect_sources(target, args[1:], _ADD_EXECUTABLE_KEYWORDS)
            executables[target] = ExecutableInfo(name=target, sources=sources)
        elif cmd in ("add_library", "ament_auto_add_library"):
            target_values = scope.expand(args[0])
            if target_values is None or len(target_values) != 1:
                continue
            if "IMPORTED" in args or "ALIAS" in args or "INTERFACE" in args:
                continue
            target = target_values[0]
            libraries[target] = _collect_sources(target, args[1:], _ADD_LIBRARY_KEYWORDS)
        elif cmd == "ament_target_dependencies":
            _attach(args[0], "dependencies", args[1:])
        elif cmd == "target_link_libraries":
            _attach(args[0], "link_libraries", [a for a in args[1:] if not a.isupper()])
        elif cmd == "rclcpp_components_register_node":
            lib = args[0]
            plugin_class = exec_name = None
            for i, token in enumerate(args):
                if token == "PLUGIN" and i + 1 < len(args):
                    plugin_class = args[i + 1]
                elif token == "EXECUTABLE" and i + 1 < len(args):
                    exec_name = args[i + 1]
            if exec_name is None:
                unresolved.append(
                    UnresolvedItem(
                        kind="component",
                        reason=f"component registered without EXECUTABLE (lib '{lib}')",
                        declared_at=where,
                    )
                )
                continue
            exec_values = scope.expand(exec_name)
            exec_name = exec_values[0] if exec_values and len(exec_values) == 1 else exec_name
            lib_sources = libraries.get(lib)
            if lib_sources is None:
                unresolved.append(
                    UnresolvedItem(
                        kind="component",
                        reason=f"component library '{lib}' has no known sources",
                        declared_at=where,
                    )
                )
            executables[exec_name] = ExecutableInfo(
                name=exec_name,
                kind="component",
                plugin_class=plugin_class,
                sources=list(lib_sources or []),
            )
        elif cmd == "rclcpp_components_register_nodes":
            unresolved.append(
                UnresolvedItem(
                    kind="component",
                    reason=(
                        f"rclcpp_components_register_nodes on '{args[0]}' declares components "
                        "without an EXECUTABLE; executable mapping unknown"
                    ),
                    declared_at=where,
                )
            )
    return executables, libraries, unresolved


# --------------------------------------------------------------------------
# Python packages (v1: record entry points only, no rclpy analysis)
# --------------------------------------------------------------------------

_SETUP_PY_EP_RE = re.compile(r"console_scripts['\"]?\s*[:=]\s*\[(.*?)\]", re.S)
_SETUP_PY_ENTRY_RE = re.compile(r"['\"]([^'\"=]+?)\s*=\s*([^'\"]+)['\"]")


def parse_python_entry_points(pkg_dir: Path) -> list[PythonEntryPoint]:
    entries: dict[str, str] = {}
    setup_cfg = pkg_dir / "setup.cfg"
    if setup_cfg.is_file():
        parser = configparser.ConfigParser()
        try:
            parser.read(setup_cfg)
            raw = parser.get("options.entry_points", "console_scripts", fallback="")
            for line in raw.splitlines():
                if "=" in line:
                    name, _, target = line.partition("=")
                    if name.strip():
                        entries[name.strip()] = target.strip()
        except configparser.Error:
            pass
    setup_py = pkg_dir / "setup.py"
    if setup_py.is_file():
        text = setup_py.read_text(encoding="utf-8", errors="replace")
        m = _SETUP_PY_EP_RE.search(text)
        if m:
            for name, target in _SETUP_PY_ENTRY_RE.findall(m.group(1)):
                entries.setdefault(name.strip(), target.strip())
    return [PythonEntryPoint(name=n, target=t) for n, t in sorted(entries.items())]


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def scan_package(package_xml: Path) -> PackageInfo | None:
    pkg_dir = package_xml.parent
    name, build_type = parse_package_xml(package_xml)
    if name is None:
        return None
    cmake_path = pkg_dir / "CMakeLists.txt"
    has_cmake = cmake_path.is_file()
    has_setup = (pkg_dir / "setup.py").is_file() or (pkg_dir / "setup.cfg").is_file()
    if build_type is None:
        build_type = "ament_cmake" if has_cmake else ("ament_python" if has_setup else "unknown")

    info = PackageInfo(name=name, path=str(pkg_dir), build_type=build_type)
    if has_cmake:
        executables, _libraries, unresolved = parse_cmake(pkg_dir, cmake_path)
        info.executables = sorted(executables.values(), key=lambda e: e.name)
        info.unresolved = unresolved
    if has_setup:
        info.python_entry_points = parse_python_entry_points(pkg_dir)
    return info


def scan_workspace(src_dir: Path) -> ScanReport:
    report = ScanReport(workspace=str(src_dir))
    for package_xml in find_package_xmls(src_dir):
        info = scan_package(package_xml)
        if info is not None:
            info.path = str(package_xml.parent.relative_to(src_dir))
            report.packages.append(info)
    report.packages.sort(key=lambda p: p.name)
    return report
