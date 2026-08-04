---
name: jinja-and-macros
description: Use Jinja and macros to write DRY, maintainable, and cross-database compatible dbt code. Covers macro definition, arguments, return values, adapter.dispatch for dialect-specific SQL, and common anti-patterns. Use when you find yourself repeating SQL, when you need to support multiple databases, or when you want to abstract complex logic.
---

# Jinja and Macros

Jinja is the templating engine dbt uses. Macros are dbt's way of letting you write reusable functions for your SQL. Master them, and you move from writing SQL to engineering a data platform.

## The rule that governs all of it

> A macro is for abstracting *how* something is done, not *what* is being done.

The business logic — the *what* — should remain readable in the model. The implementation detail — the *how* — can be abstracted into a macro. If a macro makes a model *less* readable, it's the wrong abstraction.

## What is a macro?

A macro is a reusable piece of Jinja code, much like a function in Python or JavaScript. You define it once, with arguments, and call it anywhere you need it. It can return a value (like a calculated string or number) or a whole chunk of SQL.

## Why use a macro?

| Reason | Why it matters |
|---|---|
| **DRY (Don't Repeat Yourself)** | A complex `CASE` statement for mapping statuses appears in 10 models. A change requires editing 10 files. With a macro, you edit one. |
| **Consistency** | Ensures that a specific calculation (e.g., "active user") is defined identically everywhere it's used. |
| **Abstraction** | Hides complex or ugly SQL, like a long formula for a surrogate key, behind a simple name like
