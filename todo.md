# TODO: Chrome Profile Locking Fix (v0.3.26)

## Bug
Token Factory Chrome competes for SingletonLock with `gemcli login`/`gemcli chat` CLI.

## Fix: Layered Defense
- [x] **Fix D**: Token Factory uses `<profile>_tf/` copy — eliminates all contention
- [x] **Fix A**: Improved `_kill_stale_chrome` — SIGKILL fallback + wait for exit
- [x] **Fix C**: SIGTERM/SIGINT signal handlers — cleanup when subprocess killed
- [x] Test (8 unit + 5 E2E — all pass)
- [x] Update CHANGELOG
- [x] Bump version → 0.3.26
- [x] Push + tag v0.3.26
- [x] CI: lint ✅ tests ✅ build ✅ PyPI ✅ GitHub Release ✅
