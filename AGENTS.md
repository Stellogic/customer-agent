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

## Deliberately unresolved

Architecture and implementation details have not yet been designed or approved. In particular, do not treat any previously generated service boundaries, domain model, workflow, storage choice, API or event protocol, security model, MVP scope, or test matrix as a user requirement.

Resolve consequential decisions through the configured engineering workflow and record the evidence and trade-offs before implementation. Add detailed project rules to this file only after the user has confirmed them or they have been accepted through that workflow.

## Agent skills

### Issue tracker

Issues and PRDs live in this repository's GitHub Issues. See `docs/agents/issue-tracker.md`.

### Triage labels

Default five-role triage vocabulary is used. See `docs/agents/triage-labels.md`.

### Domain docs

This repository uses a single-context documentation layout. See `docs/agents/domain.md`.
