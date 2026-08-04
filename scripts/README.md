# Graphify Makefile

This `Makefile` provides a set of convenient targets for managing the `graphify` graph within this repository. It encapsulates the specific, multi-stage workflows required to correctly build, update, and query the graph, ensuring that dbt project lineage is always merged correctly.

Using this `Makefile` is the recommended way to interact with `graphify` in this project, as it prevents common errors like running build steps in the wrong order, which can lead to a silently corrupted graph.

## Prerequisites

- The `graphify` CLI must be installed and available in your `PATH`.
- `rustc` must be installed to build the TOON serializer dependency (used by most targets).

## Usage

All commands should be run from the repository root.

```bash
make -f scripts/Makefile <target> [VARIABLE=value]
```

## Core Targets

| Target | Description |
|---|---|
| `init` | **Rebuilds the entire graph from scratch.** This is a clean-slate operation that deletes the old graph, builds the Rust dependency, creates a new code graph, and merges dbt lineage. |
| `update` | **(Recommended)** Updates the code graph and merges the latest dbt lineage. Use this after making changes to the codebase to keep the graph current. |
| `query` | Runs a `graphify query` and pipes the output through the TOON serializer for efficient context use. |
| `path` | Finds a path between two nodes in the graph and pipes the output through the TOON serializer. |
| `sync` | Merges dbt lineage into the *existing* graph without rebuilding the entire code graph. Useful for quick updates after only changing dbt models. |
| `build` | Compiles the Rust-based TOON serializer dependency. Most targets run this automatically. |
| `clean` | Deletes the `graphify-out/` directory, removing all graph data. |
| `help` | Displays a help message with all available targets. |

### Examples

**Rebuild from scratch:**
```bash
make -f scripts/Makefile init
```

**Update after code changes:**
```bash
make -f scripts/Makefile update
```

**Query the graph:**
```bash
make -f scripts/Makefile query q="how does the TOON serializer work"
```

## Customization

You can override default variables when running a command.

- **`USE_CASE`**: Specify which dbt use-case to sync (default is `enhanza-analytics`).
  ```bash
  make -f scripts/Makefile update USE_CASE=my-other-case
  ```
- **`q`**: Provide the question for the `query` target.
- **`from`**, **`to`**: Define the start and end nodes for the `path` target.
  ```bash
  make -f scripts/Makefile path from="stg_orders" to="fct_orders"
  ```