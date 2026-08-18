# auth Specification

## Purpose
TBD - created by archiving change initial-cli. Update Purpose after archive.
## Requirements
### Requirement: v2 push-approval login
The CLI SHALL implement the Trade Republic v2 web-login flow: `POST /api/v2/auth/web/login` with `{phoneNumber, pin}` and the required TR headers (`x-tr-device-info` base64-encoded device payload, `x-tr-app-version`, `x-tr-platform`, Chrome `User-Agent`), then poll `GET /api/v2/auth/web/login/processes/{processId}` until the user approves in the TR mobile app, then harvest the session cookies (`JSESSIONID`, `tr_refresh`, `tr_device`) from `Set-Cookie` headers.

#### Scenario: successful login with app approval
- **WHEN** the user runs `tr-cli login` with valid phone/PIN and approves the push in the TR mobile app within the timeout
- **THEN** the CLI prints a confirmation, harvests the session cookies, and persists them to the session file

#### Scenario: approval timeout
- **WHEN** the user does not approve the push within the login window (~120s)
- **THEN** the CLI exits with a clear timeout error and leaves any existing session untouched

#### Scenario: invalid credentials
- **WHEN** TR responds with `PIN_INVALID` or `NUMBER_INVALID`
- **THEN** the CLI reports the rejection without retrying

### Requirement: rate-limit handling with cooldown
The CLI SHALL detect `429 TOO_MANY_REQUESTS` responses, parse `errors[0].meta.nextAttemptTimestamp` / `nextAttemptInSeconds` when present, print a clear cooldown message with the suggested wait time, and MUST NOT automatically retry the login.

#### Scenario: login blocked by rate limit
- **WHEN** TR responds 429 with a next-attempt timestamp
- **THEN** the CLI prints a cooldown message including the wait time and exits non-zero

#### Scenario: no retry burst
- **WHEN** a login attempt fails with 429
- **THEN** the CLI makes no further network requests on that invocation

### Requirement: persisted session
The CLI SHALL persist harvested session cookies to a session file under `~/.tr-cli/` with 0600 permissions, load them on subsequent invocations, and validate them against `GET /api/v2/auth/account` before use.

#### Scenario: resume saved session
- **WHEN** the user runs a data command with a valid saved session
- **THEN** the CLI uses the saved session without prompting for login

#### Scenario: expired session
- **WHEN** the saved session fails validation (401)
- **THEN** the CLI reports that re-login is required and does not fall back to an interactive login without an explicit command

#### Scenario: credentials never stored in git
- **WHEN** the CLI persists any credentials, cookies, or session data
- **THEN** the data lives outside the repository (home directory) and all relevant paths are covered by `.gitignore`

### Requirement: session refresh
The CLI SHALL support refreshing a session via `GET /api/v1/auth/web/session`, which rotates the session cookies server-side, and persist the rotated cookies.

#### Scenario: refresh command
- **WHEN** the user runs `tr-cli session refresh`
- **THEN** the CLI calls the session endpoint and persists any rotated cookies, reporting which cookie values changed

### Requirement: session status reporting
The CLI SHALL expose a session status command that reports whether a saved session exists and which required cookies are present, without contacting TR.

#### Scenario: status of no session
- **WHEN** the user runs `tr-cli session status` with no session file
- **THEN** the CLI reports that no session is saved

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

