## Context

The v2 login POST currently sends only `{phoneNumber, pin}` plus the standard TR headers. `X-TR-OTP-Less: true` is the header used by handelsrepublik (openinstruments-xyz/handelsrepublik, `src/auth.ts`) to request PIN-only auth. Verified live 2026-08-18: a login with the header succeeded with NO approval push on Daniel's trusted device; the minted `tr_refresh` still has the 24 h TTL.

## Goals / Non-Goals

**Goals:**
- Optional `--otp-less` PIN-only login mode (flag + env).
- Safe fallback: if the server ignores the header, the existing push flow still completes the login.
- Mock coverage for both header paths; default behaviour byte-identical to ≤0.4.4.

**Non-Goals:**
- Changing the 24 h refresh-token TTL (server-imposed; out of scope).
- QR/instant-login login flows (separate change, later).

## Decisions

### D1: `--otp-less` opt-in, never default
The header changes authentication semantics; keeping it opt-in lets the keepalive adopt it via `TR_OTP_LESS=1` without changing the interactive default. Alternative considered: always-on — rejected because the header's server behaviour was unverified at design time.

### D2: header added in `initiate_login`, not `login_headers()`
`login_headers()` is shared with other calls (session, WAF); adding the header there would leak it into non-login requests. Adding it only in the login path keeps blast radius minimal.

### D3: mock confirms on first poll under otp-less
`MockTransport` records the header and returns CONFIRMED on the first process poll when present — standing in for "no approval needed". The pessimistic reading (server still pushes) is the existing default path, already covered by tests.

## Risks / Trade-offs

- [TR may ignore the header] → The poll waits for the normal push; flow completes as today. No breakage by construction.
- [TR may reject the header] → Surfaces as a normal login error; option documented as experimental until live success observed (it has now been observed 2026-08-18).
- [Mock semantics ≠ live semantics] → First-poll CONFIRMED is the optimistic reading; the pessimistic one is the pre-existing test path.

## Migration Plan

Version bump 0.4.4 → 0.5.0 (`pyproject.toml` + `__init__.py`), reinstall (uv cache requires a version bump), keepalive opts in by adding `TR_OTP_LESS=1` to `~/.tr-cli/env`. Rollback: unset the env var / omit the flag — default flow unchanged.

## Open Questions

- None blocking. (Whether TR accepts the header forever on trusted devices is empirical — the keepalive's ONE-attempt-per-token + reminder fallback covers rejection.)