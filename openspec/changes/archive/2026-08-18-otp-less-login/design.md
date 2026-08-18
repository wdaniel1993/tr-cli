## Context

The v2 login POST currently sends only `{phoneNumber, pin}` plus the standard
TR headers (`x-tr-device-info`, `x-tr-app-version`, `x-tr-platform`).
`X-TR-OTP-Less: true` is the header used by handelsrepublik to request
PIN-only auth.

## Decisions

### D1: `--otp-less` flag + env, not default
Keep default login identical (push flow). OTP-less is opt-in until TR's
behaviour with the header on a linked device is verified live (Daniel's
keepalive scenario). `TR_OTP_LESS=1` lets the keepalive adopt it without CLI
flag changes.

### D2: Header forwarded through `initiate_login`
`login_headers()` stays untouched (it is shared with other calls); the header
is added in `initiate_login` only when requested, so no other request changes.

### D3: Mock confirms instantly under otp-less
A first-poll CONFIRMED stands in for "no approval needed". The header flag is
recorded on `MockTransport` so tests can assert it was sent.

## Risks / Trade-offs

- [TR may ignore the header] -> The flow falls back to the normal push; no
  breakage, by construction (poll waits for CONFIRMED regardless).
- [TR may reject the header] -> Server error surfaces as a normal login error;
  the option stays documented as experimental until a live success is observed.
- [Mock != live semantics] -> Acceptable: mock confirms immediately, which is
  the optimistic reading; the pessimistic reading (push still arrives) is the
  existing default path already covered by tests.