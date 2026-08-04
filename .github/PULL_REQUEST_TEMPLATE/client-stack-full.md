## Summary
What client-facing outcome does this PR deliver?
Client: <client-name>
Use case: <connector, dashboard pack, report enhancement, etc.>

## Stack Position
Stack name: CLIENT-<client-name>-YYYY-MM-<topic>
Layer number in stack: <1 of N, 2 of N, ...>
Bottom PR: #<number>
This PR: #<number>
Top PR: #<number>
Base branch for this PR: <branch-name>
Head branch for this PR: <branch-name>

## Dependencies
Blocked by PRs: #<number>, #<number>
Blocks PRs: #<number>, #<number>
Depends on platform stack layer(s): #<number>, #<number> or none
Can this PR ship for this client without upper layers: <yes/no>

## Merge Order
Planned merge order for this stack:
1. #<bottom-pr>
2. #<next-pr>
3. #<this-pr>
4. #<top-pr>

Delivery intent:
- [ ] Merge full client stack
- [ ] Merge through this layer only
- [ ] Hold for client sign-off

If partial stack merge happens, expected retargeting:
<state exactly which remaining PRs retarget and to which branch>

## Scope
In scope:
- <client connector/model/dashboard item>
- <client connector/model/dashboard item>
- <client connector/model/dashboard item>

Out of scope:
- <cross-client platform refactor>
- <unrelated client requests>

## Client Acceptance Criteria
- [ ] Metric definitions match agreed business logic
- [ ] Dashboard/report answers agreed decision questions
- [ ] Required filters, dimensions, and time grain validated
- [ ] Stakeholder sign-off obtained or scheduled

## Validation
Build and test checks run:
- [ ] Check 1: <name and result>
- [ ] Check 2: <name and result>
- [ ] Check 3: <name and result>

Data quality checks run:
- [ ] Primary key uniqueness and not-null checks
- [ ] Relationship checks on foreign keys
- [ ] Accepted values/domain checks where applicable

## Generated Artifacts and Regeneration
- [ ] Regenerated derived artifacts after latest merge/rebase
- [ ] No hand-merged generated outputs
- [ ] Freshness and consistency checks passed

## Risk and Rollback
Risk level: <low/medium/high>
Client impact if reverted: <one sentence>
Rollback plan: <one sentence with exact reversal path>

## Reviewer Focus
Please focus review on:
1. <client-specific correctness>
2. <dependency safety with platform layers>
3. <release readiness for this client>

## Stack Governance
- [ ] This PR is part of a native stacked PR chain in one repository
- [ ] Branch and PR scope are single-concern and reviewable
- [ ] No duplicate-checkout parallel edits for same change
- [ ] Merge order above is current and accurate