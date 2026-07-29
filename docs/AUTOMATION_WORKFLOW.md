# Automation Workflow

This document describes the expected workflow for validating repository automation changes.

## 1. Prepare the environment

Activate the repository virtual environment before running tests or scripts.

```bash
source .venv/bin/activate
```

## 2. Run the checks

Use the repository test suite as the primary verification step.

```bash
pytest -q
```

## 3. Review repository guidance

Consult the contributor guidance in the following places:

- [Ways of Working](WAY_OF_WORKING.md)
- [.github/AUTOMATION_SETUP.md](../.github/AUTOMATION_SETUP.md)
- [.github/AUTOMATION_TEST.md](../.github/AUTOMATION_TEST.md)

## 4. Keep documentation current

When scripts, commands, or validation steps change, update both the workflow document and the automation notes so future contributors can follow the same path.
