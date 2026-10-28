# Security Policy

## Supported versions

Security fixes are provided on a best-effort basis for the `2.0.x` line. Older
snapshots and forks are not supported.

## Reporting a vulnerability

Please use GitHub's private vulnerability reporting on the repository
("Security" → "Report a vulnerability"). Do not open a public issue for a
suspected vulnerability.

Include:

- A description of the issue and its impact.
- Steps to reproduce, ideally with a minimal proof of concept.
- Affected version or commit.
- Any suggested mitigation.

Do not attach real user data, screenshots, API keys, or tokens. Redact
identifiers and production hostnames.

There is no bug bounty. Reports are handled on a best-effort basis; we aim to
acknowledge valid reports and coordinate disclosure after a fix is available.

## Scope

In scope:

- Browser authentication and authorization, session handling, and rate limiting.
- Android bearer-token storage and use.
- Screenshot handling, temporary files, and log contents.
- Path traversal and unsafe file handling in JSON storage and evaluation tools.
- Proxy-header trust and HTTPS enforcement.
- Dependency vulnerabilities in pinned direct dependencies.

Out of scope:

- Findings that require physical access to an unlocked device.
- Denial-of-service testing against hosts you do not own.
- Social engineering of maintainers or users.
- Reports based solely on missing security headers without a demonstrated impact.

## Known limitations

This is a prototype, not a hardened multi-tenant service:

- No CSRF framework. Browser routes rely on `SameSite=Lax`, `Secure` cookies, and
  same-origin deployment. Add CSRF protection before exposing the app publicly.
- Rate limiting is in-process and assumes a single worker. Multiple workers or
  instances need a shared rate-limit store.
- Active sessions live in process memory and are lost on restart.
- Runtime data is stored in JSON files. File permissions are set to `0600` on
  POSIX, but there is no database-level access control.
- No certificate pinning in the Android client and no Android instrumentation
  tests.
- Evaluation capture is off by default. When enabled, it writes raw goal text and
  screenshots to disk with no automatic expiry; operators must define retention
  and deletion.
- Screen frames and goal text are sent to a third-party vision provider. Operators
  and users must review that provider's terms and applicable privacy law.

Before any public deployment, add CSRF protection, shared rate limiting, backup
and monitoring, and a retention policy. The project is not intended to be exposed
directly to the public internet.

## Fixed before the first public release

The initial public release added authentication to the browser recommendation and
history endpoints, replaced raw exception text in client error responses, added
browser login/registration rate limiting, removed full runtime snapshots from
templates and health responses, redacted goal text and provider errors from logs,
and set `0600` permissions on POSIX runtime files.
