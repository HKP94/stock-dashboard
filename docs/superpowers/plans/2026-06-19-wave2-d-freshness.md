# Wave 2-D Freshness Labels Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Distinguish 06:00 KST full updates from 18:00 KST lightweight refreshes in exported dashboard data and UI labels.

**Architecture:** Add a small export-side helper that infers refresh context from market-specific latest price dates plus generated time, then surface that context in the React shell and Market tab. Keep workflow schedules unchanged but rename them to match the operating model.

**Tech Stack:** Python 3.12, React/Vite, GitHub Actions YAML, pytest, node test, vite build

## Global Constraints

- Show only display-layer labels; do not change internal quant/news contracts.
- Keep 06:00 KST = UTC 21:00 previous day and 18:00 KST = UTC 09:00.
- 18:00 refresh must explicitly state that KR price/news are freshest while US price remains previous close.
- Update PRD §11 and change history plus CLAUDE.md in this PR.

---
