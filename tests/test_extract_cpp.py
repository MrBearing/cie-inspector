from pathlib import Path

from cie_inspector.extract.cpp import analyze_executable_sources
from cie_inspector.models import Confidence


def _analyze(ws: Path, pkg: str, sources: list[str]):
    return analyze_executable_sources(ws / pkg, sources)


def _group(analysis, group_id: str):
    return next(g for g in analysis.callback_groups if g.id == group_id)


def test_callback_group_detection(ws_basic: Path) -> None:
    analysis = _analyze(ws_basic, "demo_pkg", ["src/talker.cpp"])
    sensor = _group(analysis, "sensor_group_")
    worker = _group(analysis, "worker_group_")
    assert sensor.type == "MutuallyExclusive"
    assert worker.type == "Reentrant"
    assert sensor.confidence is Confidence.resolved
    assert sensor.declared_at == "src/talker.cpp:17"


def test_node_hint_and_name(ws_basic: Path) -> None:
    analysis = _analyze(ws_basic, "demo_pkg", ["src/talker.cpp"])
    assert analysis.node_hint == "Talker"
    assert analysis.node_name == "talker"


def test_subscription_group_via_options(ws_basic: Path) -> None:
    analysis = _analyze(ws_basic, "demo_pkg", ["src/talker.cpp"])
    sensor = _group(analysis, "sensor_group_")
    (scan,) = [m for m in sensor.members if m.kind == "subscription"]
    assert scan.declared_topic == "/scan"
    assert scan.msg_type == "sensor_msgs::msg::LaserScan"
    assert scan.callback == "Talker::on_scan"
    assert scan.callback_kind == "bind"
    assert scan.confidence is Confidence.resolved


def test_subscription_default_group_lambda(ws_basic: Path) -> None:
    analysis = _analyze(ws_basic, "demo_pkg", ["src/talker.cpp"])
    default = _group(analysis, "default_group")
    (cmd,) = [m for m in default.members if m.kind == "subscription"]
    assert cmd.declared_topic == "cmd"
    assert cmd.callback_kind == "lambda"
    assert cmd.confidence is Confidence.resolved


def test_wall_timer_direct_group(ws_basic: Path) -> None:
    analysis = _analyze(ws_basic, "demo_pkg", ["src/talker.cpp"])
    worker = _group(analysis, "worker_group_")
    (timer,) = [m for m in worker.members if m.kind == "timer"]
    assert timer.period == "500ms"
    assert timer.period_ns == 500_000_000
    assert timer.callback == "Talker::on_timer"
    assert timer.confidence is Confidence.resolved


def test_runtime_topic_is_partial(ws_edge: Path) -> None:
    analysis = _analyze(ws_edge, "tricky_pkg", ["src/tricky.cpp"])
    default = _group(analysis, "default_group")
    (sub,) = [m for m in default.members if m.kind == "subscription"]
    assert sub.declared_topic is None
    assert sub.confidence is Confidence.partial
    assert any("runtime expression" in n for n in sub.notes)


def test_untraceable_group_is_unresolved(ws_edge: Path) -> None:
    analysis = _analyze(ws_edge, "tricky_pkg", ["src/tricky.cpp"])
    bucket = _group(analysis, "unresolved:group_")
    assert bucket.type == "unknown"
    assert bucket.confidence is Confidence.unresolved
    assert len(bucket.members) == 1
    assert any("group_" in u.reason for u in analysis.unresolved)


def test_non_literal_period_is_partial(ws_edge: Path) -> None:
    analysis = _analyze(ws_edge, "tricky_pkg", ["src/tricky.cpp"])
    default = _group(analysis, "default_group")
    (timer,) = [m for m in default.members if m.kind == "timer"]
    assert timer.period == "period_"
    assert timer.period_ns is None
    assert timer.confidence is Confidence.partial


def test_broken_cpp_yields_partial_results(ws_edge: Path) -> None:
    analysis = _analyze(ws_edge, "broken_pkg", ["src/broken.cpp"])
    default = _group(analysis, "default_group")
    (sub,) = [m for m in default.members if m.kind == "subscription"]
    assert sub.declared_topic == "ok_topic"
    assert any(u.kind == "parse" for u in analysis.unresolved)


def test_service_default_group(ws_basic: Path) -> None:
    analysis = _analyze(ws_basic, "demo_pkg", ["src/talker.cpp"])
    default = _group(analysis, "default_group")
    (srv,) = [m for m in default.members if m.kind == "service"]
    assert srv.declared_topic == "add_two_ints"
    assert srv.msg_type == "example_interfaces::srv::AddTwoInts"
    assert srv.callback == "Talker::on_add"
    assert srv.confidence is Confidence.resolved


def test_client_recorded(ws_basic: Path) -> None:
    analysis = _analyze(ws_basic, "demo_pkg", ["src/talker.cpp"])
    default = _group(analysis, "default_group")
    (client,) = [m for m in default.members if m.kind == "client"]
    assert client.declared_topic == "add_two_ints"
    assert client.confidence is Confidence.resolved


def test_publisher_recorded_as_reference(ws_basic: Path) -> None:
    analysis = _analyze(ws_basic, "demo_pkg", ["src/talker.cpp"])
    (pub,) = analysis.publishers
    assert pub.declared_topic == "chatter"
    assert pub.msg_type == "std_msgs::msg::String"
    assert all(m.kind != "publisher" for g in analysis.callback_groups for m in g.members)
