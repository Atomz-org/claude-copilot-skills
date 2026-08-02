# Reference data

Values that generated sample data is allowed to use, and the only ones it is allowed to use.

The convention is taken from [microsoft/Ontology-Playground](https://github.com/microsoft/Ontology-Playground/tree/main/data/reference),
whose README states it plainly:

> When a person name is needed, use the `FullName` column from this file. Do not invent new
> person names in code, docs, catalogue content, or generated examples.

That rule is worth more here than it first appears. Sample data drifts into three places —
seeds, unit-test fixtures, and documentation examples — and once a plausible-looking
`Acme AB` exists in two of them with different customer numbers, nobody can tell whether a
mismatch in a test is a bug or a typo. A single file makes the answer checkable.

It also lines up with [rule 5](../../../../../../.claude/rules/analytics-engineering-rules.md):
never invent a number or a name. A generator that fabricates company names is doing exactly
what that rule forbids, just faster.

## Files

| File | Used for |
|---|---|
| `organisations.csv` | tenant names and org ids — the `OrgId` every model carries |
| `parties.csv` | customer, supplier, and employee names |
| `articles.csv` | product names, numbers, and units |
| `accounts.csv` | BAS chart-of-accounts entries |
| `currencies.csv` | ISO 4217 codes and the regions that use them |

Every column is real: BAS account numbers are the actual Swedish chart, currency codes are
ISO 4217. Where a value would have to be invented to fill a column, the column is left out
of the reference file and the generator emits `[NEEDS INPUT]` rather than a guess.

## Using it

`scripts/dbt_seed_generator.py` reads these files and never generates a name from anywhere
else. If it needs a kind of value that has no reference file, that is a signal to add one
here, not to add a random-value branch to the generator.
