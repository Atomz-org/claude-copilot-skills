> **Frozen provenance copy — not live guidance.** The original root manual from the
> `git-skills` source repository, preserved for history per
> [README.md § Feature provenance](../../README.md). It may contradict current behavior and
> must not be followed or edited to match. The live graphify policy is
> [CLAUDE.md § Graphify-first rule](../../CLAUDE.md); the live standards are
> [.claude/rules/standards.md](../../.claude/rules/standards.md).

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
