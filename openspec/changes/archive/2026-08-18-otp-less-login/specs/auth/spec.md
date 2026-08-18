# auth Specification (otp-less addition — archived 2026-08-18)

## Requirements

### Requirement: PIN-only login (opt-in header)

The CLI SHALL support `tr-cli login --otp-less` (or `TR_OTP_LESS=1` env) which
adds the `X-TR-OTP-Less: true` header to `POST /api/v2/auth/web/login`
alongside `{phoneNumber, pin}`. The rest of the flow (poll processes until
CONFIRMED, harvest cookies) is unchanged; if the server still requires
app-approval, the poll simply waits as normal.

#### Scenario: otp-less accepted

- **WHEN** the user runs `tr-cli login --otp-less` on a trusted device and TR
  honours the header
- **THEN** the login confirms without an approval push and the session is saved

#### Scenario: otp-less ignored (fallback)

- **WHEN** the user runs `tr-cli login --otp-less` and TR still sends an
  approval push
- **THEN** the CLI waits for the app approval exactly like the default flow

#### Scenario: default login unchanged

- **WHEN** the user runs `tr-cli login` without the flag
- **THEN** no `X-TR-OTP-Less` header is sent (behaviour identical to ≤0.4.4)