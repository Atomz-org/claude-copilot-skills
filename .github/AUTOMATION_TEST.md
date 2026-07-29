# Automation Test Notes

This note documents the expected automation test flow for this repository and how Claude and Copilot-oriented automation should be validated.

## Verification
- Run pytest from the repository root.
- Ensure the virtual environment is activated before running tests.
- Confirm that the Git guardrails, review commands, workflow scaffolding, label conventions, and template set remain present before promoting changes.

## Example
```bash
source .venv/bin/activate
pytest -q
```

## When to use this note
Use this document when you are updating automation-related scripts, workflows, branch rules, commit guards, or contributor checks and want a quick reminder of the standard verification step.
