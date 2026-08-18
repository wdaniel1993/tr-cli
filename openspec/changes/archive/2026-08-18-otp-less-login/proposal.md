## Why

The Trade Republic web refresh token (`tr_refresh`) has a hard 24 h TTL (verified by decoding the JWT: exp−iat = 86400 s, never rotated by `GET /api/v1/auth/web/session`), forcing a daily re-login. The current login always triggers an app-approval push whose ~120 s window is wasted when Daniel is away. Handelsrepublik (most current TS client) sends `X-TR-OTP-Less: true` on the v2 login POST — apparently PIN-only auth on trusted devices, no push.

## What Changes

- `tr-cli login --otp-less` (+ `TR_OTP_LESS=1` env) sends `X-TR-OTP-Less: true` on `POST /api/v2/auth/web/login`; the rest of the flow (poll until CONFIRMED, harvest cookies) is unchanged.
- Safe by construction: if the server ignores the header, the normal approval push is sent and the poll waits for it.
- Mock records the header and confirms on the FIRST poll when present; the default path is unchanged.
- Docs: wire-notes entry for the header; version 0.4.4 → 0.5.0.

## Capabilities

### New Capabilities

- None.

### Modified Capabilities

- `auth` — the login requirement gains an optional PIN-only mode via the `X-TR-OTP-Less` header.

## Impact

- `src/tr_cli/auth.py` (`initiate_login` / `login_flow` signatures + header), `src/tr_cli/cli.py` (`--otp-less` option + env), `src/tr_cli/mock.py` (header handling + first-poll confirm), `tests/test_auth.py`, `docs/wire-notes.md`, `pyproject.toml`/`__init__.py` version bump. No dependency changes.