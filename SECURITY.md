# Security Policy

## Reporting a vulnerability

Report vulnerabilities privately through GitHub Security Advisories: on
[Atomz-org/claude-copilot-skills](https://github.com/Atomz-org/claude-copilot-skills),
open the **Security** tab and use **Report a vulnerability**. Do not open a
public issue for a suspected vulnerability — a public issue is a disclosure.

Expect a first response within 7 days.

## Supported versions

The latest `main` is the supported version. There are no maintained release
branches; fixes land on `main`.

## Scope

This repository ships agent skills, commands, and hooks that Claude Code
executes locally on the machine that adopts them. The primary threat model is
therefore a malicious or subtly altered skill file — a `SKILL.md`, command
playbook, or hook script that instructs an agent to do something its adopter
did not intend. Treat any pull request that touches `skill-packs/`, `scripts/`,
or the generated `.claude/` mirror as code review, not documentation review:
read what the changed instructions would make an agent do, the same way you
would read a changed shell script.
