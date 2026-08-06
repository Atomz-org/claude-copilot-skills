# Codebase Skills Inventory

This document provides a comprehensive index of all skills available in the codebase, organized by their functional area or "skill pack". Each entry includes the command to invoke the skill and a sample usage.

## dbt Skills

This pack contains skills for analytics engineering using dbt Core. The primary entry point is `dbt-skill`, which orchestrates a suite of more focused skills.

| Skill | Description | Syntax | Example |
|---|---|---|---|
| `dbt-skill` | The main entrypoint for any task involving dbt, from request framing to deployment and troubleshooting. | (Implicit) | "My dbt build is failing, can you help debug it?" |
| `dbt-project-setup` | Sets up a new dbt project, fixes a broken `profiles.yml`, or resolves adapter/package issues. | (Descriptive) | "My `dbt debug` is failing with a profile error, can you help set up my project correctly?" |
| `analytics-request-framing` | Frames a raw data request into a structured use-case spec. **Always start here.** | `/new-use-case <request>` | `/new-use-case "The finance team needs a weekly report of new customer revenue."` |
| `data-modeling` | Designs entities, ERDs, keys, and star schemas before writing model code. | `/data-model <subject area>` | `/data-model "customer lifetime value"` |
| `dbt-model-design` | Designs sources, layers, and the SQL for staging, intermediate, and mart models. | `/dbt-model <concept>` | `/dbt-model "a new staging model for shopify orders"` |
| `incremental-and-snapshots` | Implements incremental or snapshot strategies for large or historical tables. | (Descriptive) | "The `fct_events` table is too slow to rebuild. How can I make it incremental?" |
| `testing-and-documentation` | Writes data tests, `schema.yml` descriptions, and project documentation. | `/dbt-test <model>` | `/dbt-test "fct_orders"` |
| `dbt-unit-testing` | Proves complex model logic (CASE, windows, regex, etc.) with unit tests. | (Part of `/dbt-test`) | "Write a unit test for the complex CASE statement in `int_order_status_logic`." |
| `semantic-layer-metricflow` | Defines metrics in one place or answers questions with `mf query`. | `/dbt-semantic <metric>` | `/dbt-semantic "monthly active users"` |
| `dbt-mesh-governance` | Implements contracts, access controls, groups, and model versions. | (Descriptive) | "Add a model contract to `fct_orders` to prevent downstream breakages." |
| `running-dbt-commands` | Helps decide which dbt command, selector, or flags to use. | `/dbt-build <selector>` | `/dbt-build "+fct_orders"` |
| `ops-and-deployment` | Manages environments, scheduling, and slim CI with `state:modified+`. | (Descriptive) | "How do I set up slim CI for my dbt project?" |
| `performance-and-cost` | Finds the bottleneck when a dbt build is slow or expensive. | (Descriptive) | "My dbt run is taking over an hour. Can you help me find the bottleneck?" |
| `troubleshooting-dbt` | Finds the cause of a failed dbt run, test, or compile. | `/dbt-debug <error>` | `/dbt-debug "the error message from my failed dbt build"` |
| `migration-and-refactoring` | Migrates legacy SQL to dbt, swaps warehouses, or upgrades dbt versions. | (Descriptive) | "Help me migrate our legacy `sp_daily_revenue` stored procedure into a dbt model." |
| `connector-onboarding` | Onboards a new data source connector into an existing dbt project. | `/new-connector <name>` | `/new-connector stripe --tables charges --use-case my-project` |
| `enhanza-dbt-skill` | Provides dbt implementation guidance specific to the Enhanza Analytics use case. | (Descriptive) | "For the Enhanza project, how should I model the new `sessions` data?" |

## GitHub & Git Skills

This pack provides skills for managing git workflows and interacting with GitHub.

| Skill | Description | Syntax | Example |
|---|---|---|---|
| `git-commit-quality` | Ensures commit messages and content meet project standards. | (Part of `git-standard.sh`) | "Review my staged changes and create a commit that follows our standards." |
| `git-guardrails-claude-code` | Enforces repository-specific guardrails for git operations. | `/setup-git-guardrails` | "Set up the git guardrails for this repository." |
| `pr-review-orchestrator` | Orchestrates the pull request review process. | `/review <branch>` | `/review feature/new-login-flow` |
| `pr-review-terse-comments` | Provides concise, actionable review comments. | (Part of `/review`) | "Review this PR but keep the comments concise and actionable." |
| `pr-reviewability-prep` | Helps prepare a PR to make it easily reviewable. | `/pr-ready` | "Help me prepare this large branch for review." |
| `github-pr-merge-ceremony` | Guides through the process of safely merging a pull request. | `/pr-merge <PR #>` | `/pr-merge 123` |
| `git-flow-branch-planner` | Assists in planning branching strategies based on git-flow. | `/branch-plan <task>` | `/branch-plan "Fix checkout bug JIRA-123"` |
| `github-actions-docs-grounded` | Generates documentation for GitHub Actions workflows. | `/write-docs` | "Write documentation for our `ci.yml` GitHub Actions workflow." |
| `documentation-writer-diataxis` | Writes documentation following the Diátaxis framework. | `/write-docs` | "Write a tutorial for setting up a new dbt project." |
| `architecture-page` | Authors and updates the hand-drawn architecture pages under `public/`, with every figure pinned to a committed artifact. | `/architecture` | "The connector count on the architecture page is stale — update it." |
| `resolve-merge-conflicts` | Resolves merge or rebase conflicts by preserving intent. | `/resolve-conflicts` | "I have merge conflicts on my branch, can you help me resolve them?" |
| `focused-fix` | Applies a small, targeted fix to the codebase. | `/focused-fix <description>` | `/focused-fix "Correct a typo in the main README file."` |
| `sync-submodule` | Synchronizes and updates git submodules within the repository. | `/sync-submodule` | `/sync-submodule` |
| `sync-context` | Synchronizes the AI's context (RTK, Graph, Memory) with the latest codebase state. | `/sync-context <description>` | `/sync-context "Update memory after refactoring the dbt models"` |
| `github-foundation` | Provides foundational skills for working with GitHub repositories. | (Implicit) | "What are the git standards for this repository?" |
| `marketplace-portability-patterns` | Skills for creating portable, marketplace-ready tools. | `/marketplace-portability` | "Check if the `new-skill-pack` I created is portable." |

## Harness & Repository Maintenance

This pack contains skills for analyzing and maintaining the AI harness itself.

| Skill | Description | Syntax | Example |
|---|---|---|---|
| `harness-mapping` | Scans the repository's AI harness (skills, commands, agents) to find structural issues like broken links or name collisions. | `/skill-map [options]` | `/skill-map --summary` |
