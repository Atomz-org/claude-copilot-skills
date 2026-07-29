# Repository Standards

This repository is designed to behave as an independent, reusable module that can be embedded into other repositories as a submodule.

## Core expectations
- Keep the module self-contained, documented, and easy to adopt.
- Preserve a consistent Git workflow with Conventional Commits and branch naming.
- Favor focused changes, explicit documentation, and auditable review steps.

## Git rules
- Do not commit directly to main or master.
- Use branch names matching the form `<type>/<ticket>-<description>`.
- Use commit messages matching the form `type: summary`.

## Review rules
- Review the diff before merging.
- Ensure new behavior is documented and verified.
- Keep changes compatible with submodule-based consumption.
