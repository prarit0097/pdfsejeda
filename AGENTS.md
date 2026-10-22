# Repository instructions for contributors and coding agents

Read [sejedarules.md](sejedarules.md) before working in this repository. It is the
main project guide and current-state handover; follow its ground rules and scope.

Before reporting any task or unit of work as complete, update **sejedarules.md**:

- Explain what changed and why; update the affected architecture/feature/rule sections.
- Record actual validation results and their limits; distinguish passed, failed,
  skipped and not-run checks. Do not claim verification from implementation alone.
- Record deployment/publication status and relevant revision/evidence links.
- Record owner decisions, deferred work and dependencies; preserve earlier history.
- Add a dated entry to its section 8 change log. Update the plan where applicable.

Detailed reports can live elsewhere, but their outcome and link must also appear
in sejedarules.md. Do this without waiting for the owner to remind you. If work is
incomplete, document its partial status honestly before handing it back.

Never put credentials, private environment values, user documents/signatures or
token-bearing raw logs in the handover or Git. Preserve unrelated work and the
existing app/server isolation rules.
