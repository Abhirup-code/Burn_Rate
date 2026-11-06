# Postmortem: <short title>

**Date:** YYYY-MM-DD  **Severity:** page | ticket  **Author:** <name>  **Status:** draft | final

> Blameless: this is about how the system and process let the problem happen, not about who.

## Summary

Two or three sentences: what broke, for how long, and how many users noticed.

## Impact

| | |
|---|---|
| User-facing effect | e.g. checkout failed for every user |
| Duration | from first failure to recovery |
| Error budget used | from the Grafana "budget left" panel, before and after |
| Alert that fired | `CheckoutAvailabilityBudgetBurn` (page) |

## Timeline (UTC)

Paste the timeline printed by `scripts/game-day.sh`, or build it from the alert history.

| Time | Event |
|---|---|
| | First failure |
| | Alert fired (time to detect) |
| | Deploy gate blocked feature releases |
| | Mitigation applied |
| | Alert cleared (time to recover) |

## Root cause

What actually broke, and why the system allowed it. Ask "why" until the answer is something
the team can change.

## Detection

Did the right alert fire, at the right severity, fast enough? Would a user have noticed first?

## What went well

-

## What went badly

-

## Action items

| Action | Type (prevent, detect, mitigate) | Owner | Due |
|---|---|---|---|
| | | | |
