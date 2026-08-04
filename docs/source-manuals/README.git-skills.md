> **Frozen provenance copy — not live guidance.** The original README from the
> `git-skills` source repository, preserved for history per
> [README.md § Feature provenance](../../README.md). It may contradict current behavior and
> must not be followed or edited to match. The live documentation is
> [README.md](../../README.md).

# GIT Skills

This repository acts as a reusable, standards-oriented module for automation, documentation, and workflow scaffolding.

## Quick start

1. Create or activate the local virtual environment.
2. Run the test suite from the repository root.
3. Review the contributor workflow and automation notes below.

```bash
source .venv/bin/activate
pytest -q
```

## Repository entry points

- [Ways of Working](../../docs/WAY_OF_WORKING.md)
- [Automation Workflow](../../docs/AUTOMATION_WORKFLOW.md)
- [Automation Setup](../../.github/AUTOMATION_SETUP.md)
- [Automation Test Notes](../../.github/AUTOMATION_TEST.md)

## Contribution workflow

- Keep changes focused and documented.
- Preserve submodule-friendly behavior and clear integration guidance.
- Update the automation documentation whenever commands or validation steps change.

## Parent repository integration

This repository is designed to be consumed as a Git submodule in a parent project.

1. Add the submodule to the parent repository:

   ```bash
   git submodule add https://github.com/<ORG>/git-skills-latest.git external/git-skills
   git commit -m "chore: add Claude Skills for git submodule"
   ```

   Example using a specific branch or commit hash:

   ```bash
   git submodule add -b stable https://github.com/<ORG>/git-skills-latest.git external/git-skills
   # or pin to a specific commit after adding:
   cd external/git-skills
   git checkout <commit-hash>
   cd "$(git rev-parse --show-toplevel)"
   git add external/git-skills
   git commit -m "chore: pin Claude Skills for git submodule to <commit-hash>"
   ```

2. Update the submodule from the parent repository:

   ```bash
   git submodule update --remote external/git-skills
   git add external/git-skills
   git commit -m "chore: bump Claude Skills for git submodule"
   ```

3. Remove the submodule cleanly from the parent repository:

   ```bash
   ./scripts/cleanup-submodule.sh external/git-skills
   git commit -m "chore: remove external/git-skills submodule"
   ```

Use a dedicated branch or explicit commit pin to keep parent repo updates predictable:

- Prefer a release branch like `main` or `stable` in this repo for parent repo submodule tracking.
- Alternatively, pin the parent repo to a specific commit hash and update it intentionally.
- Document the chosen strategy in the parent repo so contributors know whether to merge branch updates or bump commits.
- Use `git submodule summary` in the parent repo to audit changed submodule commits before committing updates:

  ```bash
  git submodule summary --recursive external/git-skills
  ```

  This command shows the submodule commits that differ from the parent repository's recorded state and helps verify whether the update is expected.
- As a secondary audit, use `git diff --submodule` to inspect the exact diff within submodule references when a parent repo commit includes a submodule update:

  ```bash
  git diff --submodule
  ```

The parent repository should include the following `.gitmodules` entry:

```ini
[submodule "external/git-skills"]
    path = external/git-skills
    url = https://github.com/<ORG>/git-skills.git
```
