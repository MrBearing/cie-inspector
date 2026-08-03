"""Phase 2: tree-sitter based extraction of rclcpp callback structure.

tree-sitter is used (instead of libclang) so extraction works on sources that
do not compile and without any include paths — the "no build" principle.
Variable tracking is deliberately limited to simple assignments within the
sources of one executable; anything beyond that is reported as unresolved.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import tree_sitter_cpp
from tree_sitter import Language, Node, Parser

from cie_inspector.models import (
    CallbackEntity,
    CallbackGroupReport,
    Confidence,
    UnresolvedItem,
)

_LANGUAGE = Language(tree_sitter_cpp.language())

DEFAULT_GROUP_ID = "default_group"

CREATOR_KINDS: dict[str, str] = {
    "create_subscription": "subscription",
    "create_wall_timer": "timer",
    "create_timer": "timer",
    "create_service": "service",
    "create_client": "client",
    "create_publisher": "publisher",  # holds no callback; recorded as reference info
}

# For each kind: index of the first argument, if any, that *must* be a group
# (or an options object). Arguments before it may still name a group variable
# (checked against the group map) but are not required to.
_DEFINITE_GROUP_ARG = {"subscription": 3, "timer": 2, "service": 3, "client": 2}
_CALLBACK_ARG = {"subscription": 2, "timer": 1, "service": 1}
_NAME_ARG = {"subscription": 0, "service": 0, "client": 0, "publisher": 0}

_IDENT_RE = re.compile(r"[A-Za-z_]\w*")
_CHRONO_SUFFIX_NS = {
    "ns": 1,
    "us": 1_000,
    "ms": 1_000_000,
    "s": 1_000_000_000,
    "min": 60 * 10**9,
    "h": 3600 * 10**9,
}
_CHRONO_FUNC_NS = {
    "nanoseconds": 1,
    "microseconds": 1_000,
    "milliseconds": 1_000_000,
    "seconds": 1_000_000_000,
    "minutes": 60 * 10**9,
    "hours": 3600 * 10**9,
}
_PERIOD_LITERAL_RE = re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*(ns|us|ms|s|min|h)")
_PERIOD_CHRONO_RE = re.compile(
    r"(?:std::)?chrono::(nanoseconds|microseconds|milliseconds|seconds|minutes|hours)"
    r"\s*\(\s*([0-9]+)\s*\)"
)


def _make_parser() -> Parser:
    try:
        return Parser(_LANGUAGE)
    except TypeError:  # tree-sitter < 0.22
        parser = Parser()
        parser.set_language(_LANGUAGE)  # type: ignore[attr-defined]
        return parser


# --------------------------------------------------------------------------
# Per-file facts
# --------------------------------------------------------------------------


@dataclass
class GroupDef:
    var: str
    group_type: str  # MutuallyExclusive | Reentrant | unknown
    declared_at: str


@dataclass
class ArgRef:
    text: str  # normalized expression text ("this->" stripped)
    is_simple: bool  # a plain variable name
    definite: bool  # positionally, this argument must be a group/options


@dataclass
class CreatorCall:
    kind: str
    declared_at: str
    declared_name: str | None = None  # topic/service name when literal
    name_expr: str | None = None  # raw expression when not literal
    msg_type: str | None = None
    callback: str | None = None
    callback_kind: str | None = None
    period: str | None = None
    period_ns: int | None = None
    group_args: list[ArgRef] = field(default_factory=list)
    malformed: bool = False


@dataclass
class FileFacts:
    groups: list[GroupDef] = field(default_factory=list)
    calls: list[CreatorCall] = field(default_factory=list)
    options_map: dict[str, str] = field(default_factory=dict)
    node_classes: list[str] = field(default_factory=list)
    node_names: list[str] = field(default_factory=list)
    had_parse_errors: bool = False


# --------------------------------------------------------------------------
# tree helpers
# --------------------------------------------------------------------------


def _text(src: bytes, node: Node) -> str:
    return src[node.start_byte : node.end_byte].decode("utf-8", "replace")


def _line(node: Node) -> int:
    return node.start_point[0] + 1


def _normalize_expr(text: str) -> str:
    return text.strip().removeprefix("this->").strip()


def _callee(node: Node) -> tuple[Node | None, Node | None]:
    """Resolve the function part of a call to (name node, template args node)."""
    t = node.type
    if t in ("identifier", "field_identifier"):
        return node, None
    if t in ("template_function", "template_method", "template_type"):
        return node.child_by_field_name("name"), node.child_by_field_name("arguments")
    if t == "field_expression":
        inner = node.child_by_field_name("field")
        return _callee(inner) if inner is not None else (None, None)
    if t == "qualified_identifier":
        inner = node.child_by_field_name("name")
        return _callee(inner) if inner is not None else (None, None)
    return None, None


def _string_value(src: bytes, node: Node) -> str | None:
    if node.type == "string_literal":
        text = _text(src, node)
        if len(text) >= 2:
            return text[1:-1]
    return None


def _rightmost_identifier(src: bytes, node: Node) -> str | None:
    result: str | None = None
    stack = [node]
    while stack:
        n = stack.pop(0)
        if n.type in ("identifier", "field_identifier"):
            result = _text(src, n)
        stack.extend(n.children)
    return result


def _assignment_target(src: bytes, call: Node) -> str | None:
    parent = call.parent
    if parent is None:
        return None
    if parent.type == "init_declarator":
        declarator = parent.child_by_field_name("declarator")
        if declarator is not None:
            return _rightmost_identifier(src, declarator)
    if parent.type == "assignment_expression":
        left = parent.child_by_field_name("left")
        if left is not None:
            return _normalize_expr(_text(src, left))
    if (
        parent.type == "argument_list"
        and parent.parent is not None
        and parent.parent.type == "field_initializer"
    ):
        for child in parent.parent.children:
            if child.type == "field_identifier":
                return _text(src, child)
    return None


def _parse_period_ns(expr: str) -> int | None:
    text = expr.strip()
    m = _PERIOD_LITERAL_RE.fullmatch(text)
    if m:
        return int(float(m.group(1)) * _CHRONO_SUFFIX_NS[m.group(2)])
    m = _PERIOD_CHRONO_RE.fullmatch(text)
    if m:
        return int(m.group(2)) * _CHRONO_FUNC_NS[m.group(1)]
    return None


def _classify_callback(src: bytes, node: Node) -> tuple[str, str | None]:
    t = node.type
    if t == "lambda_expression":
        return "lambda", None
    if t == "pointer_expression":
        inner = node.child_by_field_name("argument")
        if inner is not None:
            return "member_function", _text(src, inner)
        return "anonymous", None
    if t == "call_expression":
        fn = node.child_by_field_name("function")
        if fn is not None and "bind" in _text(src, fn):
            stack = list(node.children)
            while stack:
                n = stack.pop(0)
                if n.type == "pointer_expression":
                    inner = n.child_by_field_name("argument")
                    if inner is not None:
                        return "bind", _text(src, inner)
                stack.extend(n.children)
        return "anonymous", None
    if t in ("identifier", "qualified_identifier", "field_expression"):
        return "function", _normalize_expr(_text(src, node))
    return "anonymous", None


# --------------------------------------------------------------------------
# Per-file extraction
# --------------------------------------------------------------------------


def extract_file(path: Path, rel: str) -> FileFacts:
    facts = FileFacts()
    try:
        src = path.read_bytes()
    except OSError:
        facts.had_parse_errors = True
        return facts
    tree = _make_parser().parse(src)

    # Only ERROR nodes that actually swallow source text count as parse
    # errors. Zero-width "missing" nodes (e.g. the absent ';' after a
    # file-scope RCLCPP_COMPONENTS_REGISTER_NODE macro) are ubiquitous in
    # ROS code and do not hide any content.
    error_bytes = 0
    stack = [tree.root_node]
    while stack:
        node = stack.pop()
        stack.extend(reversed(node.children))
        if node.type == "ERROR":
            error_bytes += node.end_byte - node.start_byte
        if node.type == "call_expression":
            _handle_call(src, node, rel, facts)
        elif node.type == "class_specifier":
            _handle_class(src, node, facts)
        elif node.type == "assignment_expression":
            _handle_assignment(src, node, facts)
        elif node.type == "field_initializer":
            _handle_field_initializer(src, node, facts)
    facts.had_parse_errors = error_bytes > 0
    return facts


def _handle_class(src: bytes, node: Node, facts: FileFacts) -> None:
    name_node = node.child_by_field_name("name")
    if name_node is None:
        return
    for child in node.children:
        if child.type == "base_class_clause" and "Node" in _text(src, child):
            facts.node_classes.append(_text(src, name_node))
            return


def _handle_assignment(src: bytes, node: Node, facts: FileFacts) -> None:
    """Track `options.callback_group = group;` style assignments."""
    left = node.child_by_field_name("left")
    right = node.child_by_field_name("right")
    if left is None or right is None or left.type != "field_expression":
        return
    field_node = left.child_by_field_name("field")
    if field_node is None or _text(src, field_node) != "callback_group":
        return
    obj = left.child_by_field_name("argument")
    if obj is None:
        return
    facts.options_map[_normalize_expr(_text(src, obj))] = _normalize_expr(_text(src, right))


def _handle_field_initializer(src: bytes, node: Node, facts: FileFacts) -> None:
    """Pick up the node name from `: Node("name", ...)` base initializers."""
    named = node.named_children
    if len(named) < 2:
        return
    if not _text(src, named[0]).endswith("Node"):
        return
    args = next((c for c in node.children if c.type == "argument_list"), None)
    if args is None:
        return
    for arg in args.named_children:
        value = _string_value(src, arg)
        if value is not None:
            facts.node_names.append(value)
        return


def _handle_call(src: bytes, call: Node, rel: str, facts: FileFacts) -> None:
    fn = call.child_by_field_name("function")
    if fn is None:
        return
    name_node, template_args = _callee(fn)
    if name_node is None:
        return
    name = _text(src, name_node)
    declared_at = f"{rel}:{_line(call)}"

    if name == "create_callback_group":
        group_type = "unknown"
        call_text = _text(src, call)
        if "Reentrant" in call_text:
            group_type = "Reentrant"
        elif "MutuallyExclusive" in call_text:
            group_type = "MutuallyExclusive"
        var = _assignment_target(src, call) or f"cg_line{_line(call)}"
        facts.groups.append(GroupDef(var=var, group_type=group_type, declared_at=declared_at))
        return

    if name == "make_shared" and template_args is not None:
        if "Node" in _text(src, template_args):
            args = call.child_by_field_name("arguments")
            if args is not None:
                for arg in args.named_children:
                    value = _string_value(src, arg)
                    if value is not None:
                        facts.node_names.append(value)
                    break
        return

    kind = CREATOR_KINDS.get(name)
    if kind is None:
        return

    result = CreatorCall(kind=kind, declared_at=declared_at)
    if template_args is not None:
        result.msg_type = _text(src, template_args)[1:-1].strip()

    arg_list = call.child_by_field_name("arguments")
    args: list[Node] = list(arg_list.named_children) if arg_list is not None else []

    name_idx = _NAME_ARG.get(kind)
    if name_idx is not None:
        if len(args) > name_idx:
            value = _string_value(src, args[name_idx])
            if value is not None:
                result.declared_name = value
            else:
                result.name_expr = _text(src, args[name_idx])
        else:
            result.malformed = True

    if kind == "timer":
        if args:
            result.period = _text(src, args[0])
            result.period_ns = _parse_period_ns(result.period)
        else:
            result.malformed = True

    cb_idx = _CALLBACK_ARG.get(kind)
    if cb_idx is not None:
        if len(args) > cb_idx:
            result.callback_kind, result.callback = _classify_callback(src, args[cb_idx])
        else:
            result.malformed = True

    if cb_idx is not None:
        first_group_idx = cb_idx + 1
    elif kind == "client":  # create_client<T>(name [, qos [, group]])
        first_group_idx = 1
    else:  # publisher: no callback, no group tracking
        first_group_idx = len(args)
    definite_idx = _DEFINITE_GROUP_ARG.get(kind)
    for i in range(first_group_idx, len(args)):
        text = _normalize_expr(_text(src, args[i]))
        result.group_args.append(
            ArgRef(
                text=text,
                is_simple=_IDENT_RE.fullmatch(text) is not None,
                definite=definite_idx is not None and i >= definite_idx,
            )
        )
    facts.calls.append(result)


# --------------------------------------------------------------------------
# Executable-level aggregation
# --------------------------------------------------------------------------


@dataclass
class ExecAnalysis:
    callback_groups: list[CallbackGroupReport] = field(default_factory=list)
    publishers: list[CallbackEntity] = field(default_factory=list)
    unresolved: list[UnresolvedItem] = field(default_factory=list)
    node_hint: str | None = None
    node_name: str | None = None


def _resolve_group(
    call: CreatorCall,
    groups: dict[str, GroupDef],
    options_map: dict[str, str],
) -> tuple[str | None, str | None]:
    """Return (group var, unresolved reason). (None, None) means default group."""
    for arg in call.group_args:
        if arg.text == "nullptr":
            return None, None
        if arg.text in groups:
            return arg.text, None
        if arg.text in options_map:
            target = options_map[arg.text]
            if target in groups:
                return target, None
            return None, (
                f"callback group assigned via options '{arg.text}' "
                f"is not traceable (expression: {target})"
            )
        if arg.definite:
            if arg.is_simple:
                return None, (
                    f"callback group variable '{arg.text}' was not seen "
                    "at any create_callback_group site"
                )
            return None, f"callback group argument is not a simple variable: {arg.text}"
    return None, None


def analyze_executable_sources(pkg_dir: Path, sources: list[str]) -> ExecAnalysis:
    analysis = ExecAnalysis()
    all_facts = [extract_file(pkg_dir / rel, rel) for rel in sources]

    groups: dict[str, GroupDef] = {}
    options_map: dict[str, str] = {}
    for facts in all_facts:
        for group in facts.groups:
            groups.setdefault(group.var, group)
        options_map.update(facts.options_map)
        if analysis.node_hint is None and facts.node_classes:
            analysis.node_hint = facts.node_classes[0]
        if analysis.node_name is None and facts.node_names:
            analysis.node_name = facts.node_names[0]

    reports: dict[str, CallbackGroupReport] = {}
    for group in groups.values():
        reports[group.var] = CallbackGroupReport(
            id=group.var,
            type=group.group_type if group.group_type != "unknown" else "unknown",
            declared_at=group.declared_at,
            confidence=(
                Confidence.resolved if group.group_type != "unknown" else Confidence.partial
            ),
        )

    def _bucket(group_id: str, group_type: str, confidence: Confidence) -> CallbackGroupReport:
        if group_id not in reports:
            reports[group_id] = CallbackGroupReport(
                id=group_id, type=group_type, confidence=confidence
            )
        return reports[group_id]

    for rel, facts in zip(sources, all_facts, strict=True):
        if facts.had_parse_errors:
            analysis.unresolved.append(
                UnresolvedItem(
                    kind="parse",
                    reason="C++ parse errors; extraction results may be incomplete",
                    declared_at=rel,
                )
            )
        for call in facts.calls:
            entity, group_var, group_reason = _build_entity(call, groups, options_map)
            if entity.kind == "publisher":
                analysis.publishers.append(entity)
            elif group_var is not None:
                reports[group_var].members.append(entity)
            elif group_reason is not None:
                bucket_id = "unresolved:" + (call.group_args[0].text if call.group_args else "?")
                _bucket(bucket_id, "unknown", Confidence.unresolved).members.append(entity)
            else:
                _bucket(DEFAULT_GROUP_ID, "MutuallyExclusive", Confidence.resolved).members.append(
                    entity
                )
            if entity.confidence is not Confidence.resolved:
                analysis.unresolved.append(
                    UnresolvedItem(
                        kind=entity.kind,
                        reason="; ".join(entity.notes) or "unresolved",
                        declared_at=entity.declared_at,
                    )
                )
    ordered = [r for r in reports.values() if r.members or not r.id.startswith("unresolved:")]
    ordered.sort(key=lambda r: (r.id == DEFAULT_GROUP_ID, r.id.startswith("unresolved:")))
    analysis.callback_groups = ordered
    return analysis


def _build_entity(
    call: CreatorCall,
    groups: dict[str, GroupDef],
    options_map: dict[str, str],
) -> tuple[CallbackEntity, str | None, str | None]:
    notes: list[str] = []
    confidence = Confidence.resolved

    group_var, group_reason = _resolve_group(call, groups, options_map)
    if group_reason is not None:
        notes.append(group_reason)
        confidence = Confidence.partial

    if call.kind in _NAME_ARG and call.declared_name is None:
        label = "topic" if call.kind in ("subscription", "publisher") else "service"
        notes.append(f"{label} name is runtime expression: {call.name_expr or '?'}")
        confidence = Confidence.partial

    if call.kind == "timer" and call.period_ns is None:
        notes.append(f"timer period is not a literal: {call.period or '?'}")
        confidence = Confidence.partial

    if call.kind in _CALLBACK_ARG and call.callback_kind in (None, "anonymous"):
        notes.append("callback could not be identified")
        confidence = Confidence.partial

    if call.malformed:
        notes.append("call arguments could not be analyzed")
        confidence = Confidence.unresolved

    entity = CallbackEntity(
        kind=call.kind,  # type: ignore[arg-type]
        declared_topic=call.declared_name,
        msg_type=call.msg_type,
        callback=call.callback,
        callback_kind=call.callback_kind,  # type: ignore[arg-type]
        period=call.period,
        period_ns=call.period_ns,
        declared_at=call.declared_at,
        confidence=confidence,
        notes=notes,
    )
    return entity, group_var, group_reason
