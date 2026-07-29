# Repository Standards

This repository is designed to behave as an independent, reusable module that can be embedded into other repositories as a submodule.

## Core expectations
- Keep the module self-contained, documented, and easy to adopt.
- Preserve a consistent Git workflow with Conventional Commits and branch naming.
- Favor focused changes, explicit documentation, and auditable review steps.
- Keep shared github-skills discoverable and intent-based through `skills-index.md`.

## Git rules
- Do not commit directly to main or master.
- Use branch names matching the form `<type>/<ticket>-<description>`.
- Use commit messages matching the form `type: summary`.

## Review rules
- Review the diff before merging.
- Ensure new behavior is documented and verified.
- Keep changes compatible with submodule-based consumption.

## Shared git-skill lifecycle rules
- Every new shared git skill must include a `SKILL.md` and a matching command playbook when practical.
- Every new shared git skill must be indexed by intent in `.claude/commands/skills-index.md`.
- Tests must verify presence of required shared git skill files and playbooks.
- CI workflows must validate the shared-pack scaffold and active stack activation.
