# Tasks

- [x] Port `X-TR-OTP-Less` header through `auth.initiate_login(otp_less=...)`
- [x] Add `otp_less` pass-through to `auth.login_flow`
- [x] Add `--otp-less` typer option + `TR_OTP_LESS=1` env in `cli.login`
- [x] Mock: record header, first-poll CONFIRMED under otp-less
- [x] Tests: otp-less header + instant confirm; default keeps old flow
- [x] Wire notes update
- [x] Bump 0.4.4 -> 0.5.0 (pyproject + __init__)
- [x] ruff clean (also fixed pre-existing F401/I001 debt)
- [x] pytest 77/77 green
- [x] uv tool install --force (cache-safe version bump)
- [x] Commit + push (Daniel Wallner)