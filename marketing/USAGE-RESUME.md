# SEO work: usage guard and continuation

Prepared 2026-10-22. This is the continuation contract, not evidence that a
scheduled task was created or that a future run succeeded. The root agent records
the actual automation result in `sejedarules.md`.

## Owner instruction

**2026-10-23 extension:** after the current cooldown and launch backlog, keep the
same automation running for ongoing useful SEO, legitimate relevant placements,
original illustrated articles and visual stories. Use the specialist agent team
within available capacity. This replaces the old instruction below to disable
after initial launch completion. Read sejedarules.md first and project Markdown
before work. Do not repeat unchanged submissions or create filler to satisfy a
posting cadence. If nothing useful is actionable, stay quiet until a later run.
Keep a publication/placement/asset ledger with real URLs, canonical original,
image rights/provenance and descriptive alt text. Use generated nonconfidential
fixtures for screenshots and the imagegen skill for original bitmap illustrations;
inspect visuals/rendered outputs. Respect platform AI/affiliation policies and
required confirmations. No guaranteed ranking, paid placement or fake endorsement.

Automation `continue-pdf-seo-after-usage-cooldown` updated in place, active,
330-minute cadence, same chat. Owner's specific SaaSHub terms consent is saved.
Existing cooldown and exact330-minute minimum remain; no Windows background
script or auth scraping. Future execution remains untested/best effort.

At 10% or less Codex usage remaining, save completed and incomplete work to
`sejedarules.md`, stop promotion work, and attempt continuation after 5 hours
30 minutes. Authorization is limited to the current PDF app branding, technical
SEO, truthful content, and relevant legitimate registrations/publications.

## Supported mechanism

Use the Codex app's current-chat scheduled task (`automation_update`, heartbeat)
and read-only `get_usage_limits`. No Windows process needs to scrape app state,
read credentials, or invoke undocumented account endpoints. Read every returned
active coding window; prefer `rateLimitsByLimitId` over legacy `rateLimits`.
Remaining percentage is `max(0, min(100, 100 - usedPercent))`; missing values are
unknown, not zero. A value of 90% used is the owner's 10% remaining threshold.

A regular heartbeat checks the persisted deadline and current usage before
resuming. It cannot guarantee an exact-time wakeup or preempt an active model
turn. The working agent must check usage at bounded work boundaries as well.
Keep the local computer powered on, the app running, and the repository
available. Scheduled runs require the same access needed for their work.
See [official scheduled-task documentation](https://learn.chatgpt.com/docs/automations?surface=app).

Do not keep moving the deadline on every low-usage observation. Once recorded,
the deadline is the original checkpoint time plus exactly 330 minutes. When it
has elapsed but usage remains low, keep that deadline and wait for recovery.
Account windows can reset on different schedules; 330 minutes does not promise
that all windows recovered.

## Durable heartbeat prompt

Continue the existing Prarit Sidana PDF branding, SEO and legitimate promotion
task in E:\coding\Sejda copy using this chat's context. Read sejedarules.md first,
then the project Markdown and current git status. Treat sejedarules.md as the
handover. Preserve unrelated changes and app/server isolation. Do not begin a
second copy of work already running in this chat.

Before substantive work and at bounded work boundaries, call get_usage_limits.
Prefer rateLimitsByLimitId, inspect every applicable coding usage window, and
calculate remaining as 100 minus usedPercent, clamped to 0 through 100. If usage
cannot be read, record that limitation and do not claim the usage guard passed.

If any applicable window has 10% or less remaining, stop starting promotion
actions. Save a truthful checkpoint in sejedarules.md with changes, actual
validation, deployment/publication results, public evidence links, unfinished
tasks and dependencies. Record checkpoint_at_utc and resume_not_before_utc,
where the latter is exactly checkpoint_at_utc plus 330 minutes. Preserve an
existing active deadline instead of resetting it. Save work safely; do not
commit credentials, private account values, documents, signatures or raw logs.
Then end the work turn until the deadline. This is the user's conditional pause
instruction, not a claim the task is complete.

On a later scheduled run, if an active deadline has not elapsed, do no SEO work
and stay quiet. Once the deadline has elapsed, read usage again. Resume only
when all available applicable windows have more than 10% remaining, retaining
the checkpoint if a window is still low or the necessary reading is unavailable.
Record resumed_at_utc when work actually resumes. Continue pending authorized
work and reapply the same guard at each bounded work boundary.

Use truthful original articles and relevant platforms; do not fabricate reviews,
endorsements, product capabilities, indexing, backlinks or rankings. Do not pay
fees, bypass login/CAPTCHA/security checks, or mass-submit duplicate material.
Record published, submitted, draft, failed and blocked results separately. Count
only externally verifiable public links as published backlinks. Resolve routine
implementation choices autonomously. If required human-only access is blocked,
record the exact dependency and continue independent useful work.

Before ending any work turn, update sejedarules.md including a dated section 8
entry and actual check results, with no repeated entries for unchanged cooldown
checks. Stay quiet while the state is unchanged or non-actionable; notify the
owner only on meaningful progress, completion, failure or required human action.
After initial launch work, continue the owner's ongoing program described above.
When only human-dependent or unchanged items remain, stay quiet and select a
different useful authorized opportunity on a later run. Do not repeat submissions
or endlessly check rankings. Disable on owner cancellation or document persistent
tool/platform impossibility before stopping the recurring program.

## Validation and limits

- Read-only tool schema inspected: both supported app tools exist in this session.
- Official documentation checked: chat schedules support minute intervals and
  local schedules require the computer and app to be available.
- No Windows scheduled task, background Codex process, credential inspection or
  account-access helper was created by this workstream.
- No application code changed. Runtime tests and a real delayed continuation
  have not been run by this workstream. Automation creation is owned by the root
  agent and must be reported from its actual tool result.
