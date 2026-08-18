## Why

Daniel's daily TR renewal chore: the web refresh token (`tr_refresh`) has a hard
24 h TTL (verified by decoding the JWT: exp-iat = 86400 s, never rotated by
`GET /api/v1/auth/web/session`). The keepalive auto-login sends `tr-cli login`,
which currently ALWAYS triggers an app-approval push with a ~120 s window —
wasted if the push fires while Daniel is away.

Handelsrepublik (openinstruments-xyz, most current TS client) sends
`X-TR-OTP-Less: true` on `POST /api/v2/auth/web/login` — apparently requesting
PIN-only auth (no push) for trusted devices. This change ports that header as
an explicit `--otp-less` option. It is a trial: if the server honors it, the
daily renewal becomes fully silent; if not, the poll simply waits for a push
(as today), so the flag is safe either way.

## What Changes

- `tr-cli login --otp-less` (+ `TR_OTP_LESS=1` env) sends `X-TR-OTP-Less: true`
  on the v2 login POST. Flow otherwise identical: initiate -> poll processes
  until CONFIRMED -> harvest cookies.
- Mock `MockTransport` records the header and, when present, confirms on the
  FIRST poll (no approval wait); default path unchanged (PENDING -> CONFIRMED).
- Tests: header sent + instant confirm; default flow does NOT send the header.
- Wire notes: X-TR-OTP-Less documented in `docs/wire-notes.md`.
- Version 0.4.4 -> 0.5.0.

## Capabilities

### New Capabilities

- `login --otp-less`: PIN-only login attempt without app-approval push.

### Modified Capabilities

- `login`: optional header via flag or `TR_OTP_LESS` env.

## Scenario

- **WHEN** Daniel runs `tr-cli login --otp-less` (or the keepalive with
  `TR_OTP_LESS=1`) on a trusted device
- **THEN** TR either confirms PIN-only (silent) or sends the normal approval
  push — either way the CLI completes the session