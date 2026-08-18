# auth Specification — delta (otp-less-login)

## ADDED Requirements

### Requirement: PIN-only login (opt-in)

The CLI SHALL support `tr-cli login --otp-less` (or `TR_OTP_LESS=1` env), which adds the `X-TR-OTP-Less: true` header to `POST /api/v2/auth/web/login` alongside `{phoneNumber, pin}`. The rest of the flow (poll the login process until CONFIRMED, harvest session cookies) is unchanged; if the server still requires app approval, the poll waits for it as in the default push flow.

#### Scenario: otp-less accepted

- **WHEN** the user runs `tr-cli login --otp-less` on a trusted device and TR honours the header
- **THEN** the login confirms without an approval push and the session cookies are saved

#### Scenario: otp-less ignored (fallback)

- **WHEN** the user runs `tr-cli login --otp-less` and TR still sends an approval push
- **THEN** the CLI waits for the app approval exactly like the default flow and completes

#### Scenario: default login unchanged

- **WHEN** the user runs `tr-cli login` without the flag and without `TR_OTP_LESS`
- **THEN** no `X-TR-OTP-Less` header is sent and behaviour is identical to ≤0.4.4