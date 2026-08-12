# Customer Support Agent Project

## User-confirmed project intent

The following points are the current user-confirmed requirements:

- Build a full-stack Agent project.
- Use React for the presentation and interaction layer.
- Use Spring Boot for the backend.
- Use LangGraph for the Agent capability.
- The selected product direction is a customer-ticket investigation and compensation-approval Agent.
- Use `D:\java-agent-\research\agent-fullstack-project-topics.md` as prior discussion material.
- Study relevant mature open-source projects and official documentation before making implementation decisions; do not invent designs without evidence.
- Write project documentation and human-facing engineering artifacts in Chinese by default so they are easy for the user and agents to review together. Keep code identifiers and protocol fields in English where appropriate.

## Engineering decision principles

- Before implementing common or non-differentiating capabilities, investigate whether a mature, actively maintained library or component already provides a natural fit.
- Prefer reuse when the candidate has reliable documentation, an acceptable license, active maintenance, compatible technology, and reasonable security, bundle-size, operational, and lock-in costs.
- Do not introduce a dependency merely to avoid a small amount of straightforward project-specific code.
- Record consequential dependency choices, rejected alternatives, and supporting evidence in the relevant decision issue or ADR before implementation.

## Deliberately unresolved

Architecture and implementation details have not yet been designed or approved. In particular, do not treat any previously generated service boundaries, domain model, workflow, storage choice, API or event protocol, security model, MVP scope, or test matrix as a user requirement.

Resolve consequential decisions through the configured engineering workflow and record the evidence and trade-offs before implementation. Add detailed project rules to this file only after the user has confirmed them or they have been accepted through that workflow.

## 规范化验证

- 完成任何实现任务前，必须从仓库根目录运行 `pwsh ./scripts/check.ps1`。
- 仅在快速、聚焦的迭代中使用 `-Component backend|agent|frontend -SkipAcceptance`。
- 规范化检查属于硬性要求：检查未通过时不得提交变更。
- CI 会调用相同的组件检查，并单独运行全栈验收。

## Agent skills

### Issue tracker

Issues and PRDs live in this repository's GitHub Issues. See `docs/agents/issue-tracker.md`.

### Triage labels

Default five-role triage vocabulary is used. See `docs/agents/triage-labels.md`.

### Domain docs

This repository uses a single-context documentation layout. See `docs/agents/domain.md`.
