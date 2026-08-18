## 1. Implementation

- [x] 1.1 Add `otp_less` parameter to `auth.initiate_login` (sets `X-TR-OTP-Less: true`) and pass through `auth.login_flow`
- [x] 1.2 Add `--otp-less` typer option + `TR_OTP_LESS=1` env support in `cli.login`
- [x] 1.3 Mock: record the header on login POST; first-poll CONFIRMED under otp-less; default path unchanged

## 2. Tests & Docs

- [x] 2.1 Tests: otp-less sends header + confirms without approval; default flow does not send the header (77/77 passed)
- [x] 2.2 Wire notes: document `X-TR-OTP-Less` (endpoint, header, fallback semantics)
- [x] 2.3 Lint clean (ruff; also fixed pre-existing F401/I001 debt)

## 3. Release

- [x] 3.1 Bump version 0.4.4 → 0.5.0 (`pyproject.toml`, `__init__.py`)
- [x] 3.2 Reinstall global tool (`uv tool install --force`; cache-safe via version bump)
- [x] 3.3 Commit + push origin/main (Daniel Wallner), archive change via openspec CLI