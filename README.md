# cie-inspector

Extracts the callback/CallbackGroup structure of ROS 2 nodes from source code —
**no build, no ROS installation, no execution**.

```bash
uvx cie-inspector extract ~/ros2_ws/src --format table
```

## Motivation

[CallbackIsolatedExecutor (CIE)](https://github.com/tier4/callback_isolated_executor)
gives every CallbackGroup its own OS thread, so Linux scheduling attributes
(policy / priority / CPU affinity) can be applied per callback. Writing that
configuration requires knowing, up front: **which nodes exist, which callbacks
they own, and which CallbackGroup each callback belongs to.**

Today that information is only obtainable *by running the system* — CIE's
prerun tool, `ros2 node info`, or tracing. On embedded targets that is heavy,
and it happens too late: you want the topology while writing the config, not
after deployment. `cie-inspector` produces the same structural information
statically, from the source tree alone.

### Layering with roscope

Launch-file resolution is already solved by
[roscope](https://github.com/paulsohn/roscope), which stops deliberately at
the node boundary. `cie-inspector` covers the inside of the node and consumes
roscope's resolved XML as an optional input — launch analysis is not
reimplemented here.

```
launch files ──► roscope ──► resolved.launch.xml ──┐
                                                   ├──► cie-inspector resolve
workspace src/ ────────► cie-inspector extract ────┘         │
        (packages → executables → callbacks/groups)          ▼
                                          inventory (JSON / table)
                                          + CIE thread-config skeleton (YAML)
```

CallbackGroups are the first-class unit: they are pure source structure and
unaffected by remapping. Topic names are carried as reference info — declared
(source) and resolved (after namespace + remap) side by side.

## Install

```bash
uvx cie-inspector --help
```

or:

```bash
pip install cie-inspector
```

## Usage

```bash
# Phase 1: package / executable / source map
cie-inspector scan ~/ros2_ws/src

# Phase 1+2: full callback/CallbackGroup inventory
cie-inspector extract ~/ros2_ws/src [--package my_pkg] [--format json|table|cie-yaml] [-o out]

# Phase 1+2+3: narrow to launched nodes, apply remaps (roscope integration)
cie-inspector resolve ~/ros2_ws/src --roscope-xml resolved.launch.xml --format cie-yaml
```

### roscope integration in two commands

```bash
roscope resolve my_robot.launch.py -o resolved.launch.xml
cie-inspector resolve ~/ros2_ws/src --roscope-xml resolved.launch.xml --format cie-yaml -o cie_config.yaml
```

### Output formats

- `json` (default) — full inventory, schema defined by pydantic models
  ([models.py](src/cie_inspector/models.py)). See
  [examples/inventory.json](examples/inventory.json).
- `table` — human-readable summary: node × group × member count.
- `cie-yaml` — thread-configuration skeleton in the
  [tier4/callback_isolated_executor](https://github.com/tier4/callback_isolated_executor)
  (`cie_thread_configurator`) format, with group ids reconstructed as
  `/<node>@Subscription(/topic)@Timer(<period_ns>)`. `policy` / `priority` /
  `affinity` are emitted as `TODO` — choosing values is deliberately left to a
  human. See [examples/cie_config.yaml](examples/cie_config.yaml).
  Static group ids are best-effort: verify them against the ids the CIE
  prerun tool emits before deployment.

### Exit codes

| code | meaning |
|---|---|
| 0 | success (unresolved entries are still success) |
| 1 | input error |
| 2 | analysis could not proceed |
| 3 | `--strict` given and unresolved entries exist |

## What "best-effort" means

Static analysis cannot decide everything. The tool never guesses: whatever it
cannot determine is emitted as `unresolved`, with the source location and a
reason. Every entity carries a `confidence` attribute:

- `resolved` — fully determined from literals / simple variables
- `partial` — the entity is certain, but some attribute is not (topic name is
  a runtime expression, timer period is a variable, group is not traceable…)
- `unresolved` — detected, but the main attributes are unknown

Drawing the line between "statically certain" and "runtime-dependent" is
itself the point: the unresolved list tells you exactly what you still have to
check by other means.

### Detected patterns (C++ / rclcpp)

`create_callback_group`, `create_subscription`, `create_wall_timer` /
`create_timer`, `create_service`, `create_client`, `create_publisher`
(reference info). Group assignment is resolved through a direct group argument
or through `SubscriptionOptions::callback_group`; callbacks are identified as
lambda / `std::bind` / member-function pointer / free function. Variable
tracking is limited to simple assignments within one executable's sources —
groups passed through functions, containers, or conditionals become
`unresolved`.

### Out of scope in v1

- Python (rclpy) nodes — entry points are detected and reported as
  `unsupported`, sources are not analyzed
- launch analysis — delegated to roscope
- recommending scheduling values — the skeleton contains `TODO`s only
- resolution across templates/macros, full header class hierarchies
- micro-ROS / rclc executors

## Development

```bash
uv sync
uv run pytest
uv run ruff check .
```

The smoke test against [ros2/demos](https://github.com/ros2/demos) runs when
`CIE_DEMO_NODES_CPP` points at a checkout (CI does this automatically).
