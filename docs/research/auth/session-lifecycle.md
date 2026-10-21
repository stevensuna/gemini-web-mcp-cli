# Session Lifecycle: Why Google Sessions Die and How to Keep Them Alive

Findings from investigating issue #3 (Sep 23, 2026, Chrome 153, macOS).
Evidence levels are marked: **verified** (reproduced or measured live) vs
**hypothesis** (consistent with the evidence but not proven).

## Summary

- Sessions stay alive when **one browser owns them** and keeps using them.
- Sessions get **revoked server-side** (RotateCookies → 401) when the same
  session is used from several clients that each rotate cookies.
- A saved `auth.json` can be rejected minutes after it was written while the
  owning Chrome is still signed in. A dead `auth.json` ≠ a dead account.
- The signed-out Gemini page also carries an `SNlM0e` token. Only the account
  email (`WIZ_global_data.oPEP7c`) proves a signed-in session.

## Observations

### 1. Copying a session into several clients gets it revoked (verified outcome, hypothesis cause)

gemcli 0.7.0 used one Google session from three places: the login Chrome
profile, a `<profile>_tf` **copy** of it for Token Factory, and Python HTTP
requests. It also injected `auth.json` cookies back into Chrome.

- `mail4jbd2` was freshly logged in at 13:46 and revoked by 13:59:
  `RotateCookies` returned **401**, and the owning Chrome profile was signed
  out too.
- After the 0.7.1 fixes (Token Factory reused the daemon on the **login
  profile itself**, no `_tf` copy launched), the same account survived a
  35-minute soak with 6 Pro requests and 12 health checks.

**Hypothesis:** Device Bound Session Credentials (DBSC). The login profile and
its `_tf` copy both contain a `Default/Device Bound Sessions` store; the one
profile that never had it (`eltanium`) kept working on 3-day-old cookies. A
copied profile carries the device-bound registration but cannot prove
possession of the key, which looks like cookie theft to Google.

### 2. `auth.json` goes stale while Chrome stays signed in (verified)

While the daemon ran on `mail4jbd2`, the `auth.json` saved at 15:54 was
rejected over HTTP by 16:20, but the daemon's live session and its current
cookies both worked. Chrome had renewed its short-lived cookies in the
meantime. Idle profiles (no Chrome running) kept a working `auth.json` for
hours, because nothing replaced their cookies.

**Consequence:** read live cookies from the owning Chrome when it is running;
treat `auth.json` as a mirror.

### 3. The signed-out page has `SNlM0e` (verified)

A headless Chrome with no Google cookies loads `gemini.google.com/app` with a
guest `SNlM0e` and a "Sign in" button. Token Factory's auto sign-in used
`SNlM0e` as its success signal and reported success on the signed-out page.
The account email `oPEP7c` is empty when signed out and is the reliable
signal (also present in the HTML as `"oPEP7c":"user@gmail.com"`).

### 4. Deleting Google cookies signs Chrome itself out (verified)

Deleting a profile's `Default/Cookies` file also removed Chrome's own account
sign-in (the `token_service` row in `Web Data` and `account_info` in
`Preferences`), and the web session was signed out. `gemcli login --force`
deletes the same file, so it has the same effect. After it, Google asks for
the email again instead of offering one-click "Continue as".

### 5. One-click re-sign-in needs Chrome's own account sign-in (partly verified)

A profile whose Chrome was signed in to the Google account at the browser
level (avatar, `token_service` entry) signed back into Gemini with a single
click in a visible window. Every `gemcli login` gives the profile this
browser-level sign-in. Whether one click is enough after a **natural**
expiry is not yet verified; a password, passkey, or "verify it's you"
challenge always needs a human (accounts using passkeys cannot be
automated).

## Design rules derived from this

1. One Chrome user-data-dir owns each session. Never copy a profile directory,
   never inject saved cookies into a Chrome that owns a session.
2. Mirror cookies from Chrome into `auth.json`, never the other way.
3. Keep idle sessions alive by loading Gemini in the profile's own Chrome
   periodically (`gemcli keepalive run`), and close Chrome cleanly
   (`Browser.close`) so renewed cookies are flushed to disk.
4. Decide "signed in" by the account email, not `SNlM0e`.
5. Recovery may click, never type. Anything beyond an account chooser needs a
   human, and the tool should say which profile.

## Open questions

- How long a keep-alive-maintained session survives (soak running since
  Sep 23, 2026; results in `~/.gemini-web-mcp-cli/logs/keepalive.jsonl`).
- Whether one-click recovery works after a natural expiry.

## Follow-up (Sep 23, 2026, evening)

`mail4jbd2` and `mail4jbd` both died between 18:34 and 21:06, after the
0.7.1/0.8.0 fixes. Two remaining paths still mixed sessions:

- **The daemon ignored `-p`.** Any browser-cookie call (e.g. `gemcli -p gns
  limits`) read cookies from whatever profile the daemon held, so other
  profiles showed the daemon account's usage under their own name. When the
  daemon looked signed out, it injected the *requested* profile's saved cookies
  into the daemon's Chrome, which put two accounts' sessions into one browser.
- **Token Factory still copied the profile** (`<profile>_tf`, a full
  `copytree` including `Device Bound Sessions`) whenever no daemon was running
  for the profile, and injected saved cookies into it.

Both were removed in 0.8.1: Token Factory runs on the profile's own
user-data-dir, nothing injects cookies into Chrome, the daemon serves only its
own profile, and a Chrome signed in to another account is refused. Whether
these paths caused the two deaths is not proven, but they match the pattern.
