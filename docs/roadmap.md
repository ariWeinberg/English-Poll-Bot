# R&D Roadmap

This document turns the one-year R&D plan into an execution artifact for this repository.
It is intentionally pragmatic: the goal is to make the platform pilot-ready in small, reviewable steps
while preserving the current working system.

## Delivery Principles

- Keep each change scoped to one product track or one dependency boundary.
- Prefer reversible work first: docs, tests, read-only diagnostics, and additive storage.
- Make operational state observable before adding more automation.
- Preserve tenant isolation and provider neutrality as non-negotiable constraints.
- Treat every release as a validation step, not just a deployment step.

## Current Baseline

The repository already contains a meaningful slice of the roadmap:

- Authenticated app access and protected API docs
- Secret-redacted request logging with stdout visibility
- Tenant-scoped connector records with a provider-neutral model
- Persisted webhook inbox storage with raw payload retention
- Scheduler worker separation and basic health reporting
- Learner summary, poll, text, and webhook operator views
- Documentation and test coverage for the above behaviors

The remaining work is primarily about hardening, expanding diagnostics, and turning existing product primitives into coherent workflows.

## Suggested Execution Order

1. Security and production hardening
2. Provider reliability and connector diagnostics
3. Webhook and scheduler operations
4. Learning analytics and question quality
5. Curriculum and teacher workflows
6. Scale architecture and pilot readiness

That order matters because later tracks depend on trusted authentication, stable connector behavior, and visible operational state.

## Micro-Commit Shape

The work should land in commits that are narrow enough to review without diff fatigue.

Recommended commit granularity:

1. Documentation and tests for the target behavior
2. Database schema or model additions
3. Backend helpers and route wiring
4. Frontend surfaces and copy
5. Regression tests and release notes

When a track spans multiple concerns, commit the observability layer before the workflow layer so failures are easier to diagnose.

## Track 1: Security and Production Hardening

### Objective

Make the application safe to operate in production with authenticated access, tenant isolation, reliable startup behavior, clear logs, and repeatable release verification.

### Existing State

- Public Swagger is already disabled.
- Signed short-lived docs sessions already exist.
- Request logging already includes redaction and request IDs.
- Scheduler and webhook behavior already write durable records.

### Gaps to Close

- Formalize protected app surfaces and internal operator pages.
- Add readiness checks separate from liveness.
- Make startup failure modes explicit when configuration is missing.
- Expand release smoke checks into a documented operator runbook.
- Review tenant isolation in API, background jobs, and analytics queries.

### Deliverables

- Authenticated access policy for operational surfaces
- Readiness endpoint or readiness contract
- Startup failure reporting for missing dependencies and configuration
- Release verification checklist
- Runbook for deploy, rollback, and provider outage handling

### Acceptance Checks

- Unauthenticated users cannot access protected operational routes.
- Tenant A cannot infer or modify Tenant B data through API or background flows.
- Production startup fails clearly when required configuration is missing.
- Logs contain enough context to debug failures without exposing secrets.
- Release verification can be run consistently after every deploy.

### Risk Notes

- Retrofitting auth can break internal tooling unless the route inventory is explicit.
- Aggressive redaction can remove useful diagnostics unless request IDs and tenant IDs remain visible.

## Track 2: Provider Reliability Lab

### Objective

Create a provider-neutral reliability layer for WhatsApp delivery, webhook ingestion, status tracking, and provider comparison.

### Existing State

- Connector rows are already tenant-scoped and provider-neutral.
- WAHA and GreenAPI adapters already exist.
- Provider message identity is already retained in outbound and inbound records.

### Gaps to Close

- Better connector diagnostics in Settings.
- Repeatable provider test scripts.
- A reliability matrix that captures provider-specific quirks and recovery paths.
- Validation for malformed connector state when switching providers.

### Deliverables

- One active connector per tenant with clear state and timestamps
- Normalized outbound and inbound provider identities
- Settings diagnostics for provider, status, last success, and last failure
- Provider reliability checklist

### Acceptance Checks

- Existing product flows work without knowing the active provider.
- Provider switch validation catches malformed or incomplete connector state.
- Failed provider operations are visible in logs and diagnostics.
- Provider-native and provider-neutral IDs are preserved.

## Track 3: Webhook and Scheduler Operations

### Objective

Make asynchronous message ingestion and scheduled delivery observable, recoverable, and trustworthy.

### Existing State

- Every webhook request is already persisted in the inbox.
- Incoming rows already retain raw payload, normalized identity fields, and final decision state.
- Scheduler activity is already recorded in the database and visible through health data.

### Gaps to Close

- Richer status taxonomy for duplicate, pending, and retry states.
- Operator search and filter ergonomics for inbox inspection.
- Retry policies for transient provider and database failures.
- Reconciliation between scheduled intent, outbound sends, and webhook outcomes.

### Deliverables

- Webhook inbox pages and APIs that support explainability
- Scheduler history and send-attempt records
- Retry and reconciliation workflows
- Stdout-visible scheduler lifecycle logs with debug tracing behind a toggle

### Acceptance Checks

- All webhook payloads are retained even when ignored or invalid.
- Operators can explain why a webhook did or did not affect learner state.
- Scheduler activity is visible without enabling special debug mode.
- Retry behavior is idempotent.

## Track 4: Question Quality System

### Objective

Create a measurable quality loop for generated and reused questions so learners receive useful, level-appropriate, non-repetitive practice.

### Existing State

- Question preview and generation flows already exist.
- Polls and question history already persist provider identity and correctness data.

### Gaps to Close

- Explicit question metadata for source span, objective, difficulty, and review status.
- Review states for approve, disable, needs edit, and archive.
- Ranking signals that include content coverage and prior performance.
- Regeneration workflows for weak or rejected questions.

### Deliverables

- Question metadata schema
- Teacher review queue
- Ranking preview and regeneration actions
- Question-level performance reporting

### Acceptance Checks

- Invalid question structures are rejected before active delivery.
- Teachers can review and control question pools without database edits.
- Ranking avoids excessive repetition and improves coverage.
- Underperforming questions are visible for review.

## Track 5: Learning Intelligence

### Objective

Turn poll responses and engagement behavior into actionable insight for teachers, learners, and operators.

### Existing State

- Learner summaries, learner detail, and analytics filters already exist.
- Poll analytics already use a production-safe timestamp fallback.

### Gaps to Close

- Distinct analytics surfaces for executive overview, class progress, learner intervention, and question quality.
- Data sufficiency markers for sparse or incomplete data.
- Exportable reports for pilot review.
- Recommendations that explain their supporting evidence.

### Deliverables

- Learner and cohort summaries
- Dashboard separation between learning metrics and operational metrics
- Pilot reporting exports
- Intervention suggestions with evidence

### Acceptance Checks

- Analytics do not show empty states when valid sent-poll data exists.
- Learner summaries are explainable from underlying responses.
- Teacher views prioritize next actions over raw counts.
- Executive views show both learning progress and reliability.

## Track 6: Curriculum and Content Model

### Objective

Represent learning content as a structured curriculum rather than isolated texts and polls.

### Existing State

- Texts, schedule rules, and poll coverage already form a useful baseline.

### Gaps to Close

- Curriculum, unit, lesson, skill, objective, and assessment tagging.
- Coverage and sequencing rules.
- Import/export for structured curriculum data.
- Backward-compatible migration path for existing texts.

### Deliverables

- Curriculum tables and relationships
- Assignment and progress APIs
- Coverage browsing and correction UI
- Migration path for existing content

### Acceptance Checks

- Existing texts continue to work after the curriculum model is introduced.
- Teachers can assign structured content without manually creating every schedule rule.
- Coverage gaps are visible and correctable.

## Track 7: Teacher Workflow Productization

### Objective

Turn backend capabilities into coherent teacher workflows that can be used during real programs without developer support.

### Existing State

- Settings, texts, polls, learners, and webhooks already expose most operational primitives.

### Gaps to Close

- Guided onboarding for tenant setup, connector connection, roster sync, and first content assignment.
- Review queues for questions, failed sends, webhook issues, and learner intervention.
- Role-aware navigation and less incidental operational complexity.

### Deliverables

- Setup progress tracking
- Batch-friendly teacher APIs
- User-visible workflow state and notifications
- Auditability for teacher actions

### Acceptance Checks

- A teacher can complete setup, sync learners, assign content, approve questions, and schedule delivery through the UI.
- Common errors explain what happened and what action is available.
- Review queues reduce the need to inspect logs or database rows.

## Track 8: Scale Architecture

### Objective

Prepare the platform to handle more tenants, larger classes, and higher message volume without rewriting core flows under pressure.

### Existing State

- The API and scheduler are already split.
- Durable records already exist for core workflows.

### Gaps to Close

- Performance budgets for routes, jobs, and analytics queries.
- Queueing boundaries for retryable work.
- Measured index and summary-table improvements.
- Backup, restore, incident response, and load testing discipline.

### Deliverables

- Performance budgets
- Queue or job boundaries
- Deployment metrics and alerts
- Recovery runbooks

### Acceptance Checks

- Scheduled send batches do not block normal API responsiveness.
- Webhook bursts are processed without data loss.
- Failed jobs are visible and retryable.
- Migrations can be deployed without downtime or data loss for supported flows.

## Track 9: Pilot Readiness and Expansion

### Objective

Package the platform, operations, support, and reporting needed to run controlled pilots and expand based on evidence.

### Existing State

- The app already has the core workspace, learner, poll, webhook, and doc surfaces needed for an internal pilot.

### Gaps to Close

- Pilot success metrics
- Onboarding materials
- Consent, retention, and support processes
- Readiness checklists and reporting exports

### Deliverables

- Pilot configuration fields
- Readiness checklist UI and APIs
- Weekly and end-of-pilot report exports
- Structured feedback capture

### Acceptance Checks

- A pilot can be prepared using a documented checklist.
- Operators can verify tenant, provider, roster, content, schedule, analytics, and support readiness before launch.
- Weekly pilot reports can be generated without manual SQL.
- Expansion decisions are based on measured outcomes and documented feedback.

## Quarter Map

### Quarter 1

- Authenticated operational surfaces
- Tenant isolation review
- Provider-neutral connector foundation
- Baseline webhook and scheduler observability
- Release verification checklist

### Quarter 2

- Webhook inbox and scheduler history
- Question metadata, validation, and review states
- Initial learner and class analytics
- Early curriculum model design

### Quarter 3

- Teacher workflow onboarding
- Curriculum assignment and coverage
- Intervention views
- Queueing and performance budgets
- Provider reliability drills

### Quarter 4

- Pilot readiness checklist
- Reporting exports
- Scale tests and operational runbooks
- Support workflow
- Expansion decision package

## Documentation To Keep In Sync

When changing the plan above, update the following same-PR artifacts:

- `README.md`
- `docs/architecture.md`
- `docs/runbook.md`
- relevant backend and frontend tests

If a change introduces a new operational route, a new background job, or a new workflow state, add a note here and add an acceptance check to the corresponding tests.
