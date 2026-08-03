"""Output schema (pydantic v2). All JSON output is generated from these models."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel

from cie_inspector import SCHEMA_VERSION


class Confidence(str, Enum):
    """How far static analysis got.

    resolved   — fully determined from literals / simple variables
    partial    — the entity is certain, but some attribute could not be resolved
    unresolved — the entity was detected but its main attributes are unknown
    """

    resolved = "resolved"
    partial = "partial"
    unresolved = "unresolved"


class UnresolvedItem(BaseModel):
    kind: str
    reason: str
    declared_at: str | None = None


# --------------------------------------------------------------------------
# Phase 1: workspace scan
# --------------------------------------------------------------------------


class ExecutableInfo(BaseModel):
    name: str
    kind: Literal["executable", "component"] = "executable"
    plugin_class: str | None = None
    sources: list[str] = []
    dependencies: list[str] = []
    link_libraries: list[str] = []
    unresolved: list[UnresolvedItem] = []


class PythonEntryPoint(BaseModel):
    name: str
    target: str
    supported: bool = False  # rclpy source analysis is out of scope for v1


class PackageInfo(BaseModel):
    name: str
    path: str
    build_type: str
    executables: list[ExecutableInfo] = []
    python_entry_points: list[PythonEntryPoint] = []
    unresolved: list[UnresolvedItem] = []


class ScanReport(BaseModel):
    schema_version: str = SCHEMA_VERSION
    workspace: str
    packages: list[PackageInfo] = []


# --------------------------------------------------------------------------
# Phase 2/3: callback inventory
# --------------------------------------------------------------------------


class CallbackEntity(BaseModel):
    kind: Literal["subscription", "timer", "service", "client", "publisher"]
    declared_topic: str | None = None  # topic (or service name) as written in source
    resolved_topic: str | None = None  # after applying launch remaps (resolve mode only)
    msg_type: str | None = None
    callback: str | None = None
    callback_kind: Literal["lambda", "bind", "member_function", "function", "anonymous"] | None = (
        None
    )
    period: str | None = None  # timer period expression as written
    period_ns: int | None = None  # parsed period, when the expression is a literal
    declared_at: str
    confidence: Confidence
    notes: list[str] = []


class CallbackGroupReport(BaseModel):
    id: str
    type: Literal["MutuallyExclusive", "Reentrant", "unknown"]
    declared_at: str | None = None
    confidence: Confidence
    members: list[CallbackEntity] = []


class LaunchInfo(BaseModel):
    node_name: str
    namespace: str = "/"
    remaps: dict[str, str] = {}


class NodeReport(BaseModel):
    package: str
    executable: str
    kind: Literal["executable", "component"] = "executable"
    plugin_class: str | None = None
    node_hint: str | None = None  # class deriving from rclcpp::Node, if found
    node_name: str | None = None  # literal name passed to the Node base constructor
    launch: LaunchInfo | None = None  # present in resolve mode for matched nodes
    callback_groups: list[CallbackGroupReport] = []
    publishers: list[CallbackEntity] = []  # reference info; publishers hold no callback
    unresolved: list[UnresolvedItem] = []


class UnmatchedLaunchNode(BaseModel):
    package: str
    executable: str
    node_name: str | None = None
    reason: str


class Inventory(BaseModel):
    schema_version: str = SCHEMA_VERSION
    workspace: str
    nodes: list[NodeReport] = []
    scan_unresolved: list[UnresolvedItem] = []  # Phase 1 issues (CMake variables etc.)
    unsupported: list[UnresolvedItem] = []  # e.g. rclpy entry points (v1: recorded only)
    unmatched_launch_nodes: list[UnmatchedLaunchNode] = []

    def has_unresolved(self) -> bool:
        """True if anything needs human attention (used by --strict)."""
        if self.unmatched_launch_nodes or self.scan_unresolved:
            return True
        for node in self.nodes:
            if node.unresolved:
                return True
            for group in node.callback_groups:
                if group.confidence is Confidence.unresolved:
                    return True
                for member in group.members:
                    if member.confidence is not Confidence.resolved:
                        return True
        return False
