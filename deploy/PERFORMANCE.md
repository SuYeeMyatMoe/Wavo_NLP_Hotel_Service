# Startup and login verification — 21 November 2026

All dates in this record use Asia/Rangoon unless a timestamp explicitly ends in
`Z` (UTC). Existing hosting, application design, accounts, data, endpoint formats,
authorization, call permissions, and model behavior are preserved.

## Changes

- The public entrance starts a bounded API readiness task without blocking the
  page. Concurrent visitors share it; successful readiness is reused for 60
  seconds. There are no timer-based keep-alive requests.
- Readiness reads can remain open for up to 60 seconds within the existing
  120-second total deadline and bypass stale intermediary caches.
- Natural-idle trials exposed a separate routing problem: the Render frontend
  received immediate HTTP 502 responses with `x-render-routing: no-deploy`, and
  the API did not start. Longer read timeouts and cache-busting alone did not fix
  this. An external request woke the optimized API in 24.53 seconds.
- The coordinator therefore grants one visitor a browser-originated, credential-
  free GET wake hint per active task. It survives navigation to sign-in and uses
  the remaining shared deadline. The server still verifies readiness; browser
  responses never grant authentication or call permission. There are no browser
  retries or scheduled pings.
- Sign-in authenticates while the API is waking, waits only after credentials
  succeed, and reuses the verified workspace response. Existing session timing
  fields now separate authentication from `readiness_seconds`.
- API startup validates configuration and starts lifecycle-managed operations
  and resource warmup. Health and workspace routes do not wait for NLP resources.
  Resource accessors serialize initialization and cache only successful loads.
- NumPy/joblib imports are deferred to inference. The API no longer installs
  pandas, which is only used by the frontend. Frontend pandas remains pinned.
- Loading-card styling is preserved; its text identifies sign-in, service
  startup, or workspace loading.

## Observations

These are individual measurements, not latency guarantees or percentile estimates.

| Measurement | Result |
|---|---|
| Previous idle API first health request | 58.74 s; next request 1.13 s |
| Previous blocking application startup in Render logs | Approximately 35 s |
| Optimized blocking application startup in Render logs | 0.20 s, from `18:14:47.557Z` to `18:14:47.756Z` |
| Final smaller API build blocking startup | 0.20 s, from `18:23:35.951Z` to `18:23:36.149Z` |
| Model-bundle background initialization before/after removing backend pandas | 25.89 s / 16.59 s in the respective deployment logs |
| Local Linux process launch → health, 512 MiB cap | 3.27 s |
| Local immediate workspace request while resources warmed | HTTP 200 in 2.36 s |
| Local immediate first classification while resources warmed | HTTP 200 in 12.33 s; Maintenance classification preserved |
| Hosted warm guest workspace read | 2.46 s |
| Hosted warm staff workspace read | 1.23 s |
| Hosted warm classification | 1.19 s |
| Hosted repeated health request on reused transport | 0.08 s |
| Browser guest Sign in → reception control visible | 11.26 s on the newly deployed frontend |
| Browser staff Sign in → workspace visible | 3.06 s; assigned-work table and live updates subsequently verified |
| Final public entrance ready while API slept, frontend awake | 9.75 s, including first frontend script and browser automation |
| Final natural-cold guest Sign in → reception control visible | **21.97 s**; **40.45 s** from opening the public entrance, including navigation and credential entry |
| First classification after that cold browser login | **1.11 s**, HTTP 200; Maintenance result and evidence preserved |
| Final warm staff Sign in → workspace visible | **2.41 s**; work queue and live updates verified |
| Earlier trial with both Render services asleep: public page ready | 35.25 s, before the browser wake-hint fix |

For the successful final trial, the API shut down naturally at
`2026-11-20T18:58:31Z` and stayed asleep until the public-page browser visit.
It started at `19:13:50.154Z` and completed application startup at `19:13:50.348Z`.
No external health probe was sent before the successful guest login. The earlier
58.74-second baseline is a cold health-request measurement, not an end-to-end
browser login; those two numbers should not be presented as identical metrics.

The browser measurements include client rendering and automation overhead.
Screenshots of both finished workspaces were captured locally. No physical
microphone checks were performed, as requested.

## Checks

- **256 tests passed** in the final complete Linux suite under `--memory=512m`
  in 347.66 s, including authentication, workflows, consent, calls, notifications,
  and lifecycle regressions. One existing Starlette/anyio deprecation warning remains.
- **104 backend tests passed** in a disposable Linux container with pandas
  uninstalled, covering startup, cloud handling, workflow, call start, voice
  turns, and service consent.
- **53 focused tests passed on both Windows and Linux** after the longer
  readiness-read adjustment, including simulated slow cold responses and the
  unchanged total deadline. The Linux run used `--memory=512m` and took 27.04 s.
- Four simultaneous first classifications in a fresh 512 MiB Linux container
  loaded the model bundle exactly once. All results equaled the subsequent warm
  result, including Maintenance classification and evidence; observed process
  RSS was 217.7 MiB.
- Browser wake-hint tests verify one claim across eight visitors, the remaining
  shared deadline, successful hidden-component mounting, no authentication state,
  and JavaScript handling of both shadow-root and ordinary component hosts.
  `node tests/api_wake.mjs` verifies one credential-free GET, rerun deduplication,
  timeout cancellation, and no retries. Final focused login/call checks passed.
- New tests cover concurrent wake-up sharing, the 60-second expiry, failed-wake
  retry on demand, nonblocking website entry, immediate credential rejection,
  authenticated workspace access during delayed warmup, one-time resource
  initialization, resource failure retry, and warmup shutdown.
- Ruff and whitespace checks passed. New startup/readiness modules and changed
  service/client modules pass type checking. The broader type check still reports
  two pre-existing diagnostics in the navigation formatter and evidence sorting;
  those unrelated expressions were left unchanged.
- The isolated running Streamlit agent API returned a ready guest workspace with
  no exceptions. The local-only verification server was stopped afterward.
- Observed hosted memory during startup and guest/staff checks: approximately
  **327 MiB API** and **197 MiB frontend**, below each Free service's 512 MiB limit.

Render's idle spin-up remains outside application control. Earlier wake-up and
shorter application startup reduce login delays; they do not make sleeping Free
instances continuously available. See the [runbook](README.md).

## Rollout and rollback

The API optimization was deployed before the frontend changes. The API runs
revision `172b645f579d3f01af91087745fba34551da02bd` (deployment
`dep-dc08vlu1egvs738cvmmg`); the frontend runs
`47c0d4578f6073f6b24b53e63853a492b4d8e3b2` (deployment
`dep-dc09mno8v5cc7390pka0`). Automatic deployments remain disabled. Both services
remain on Free in Singapore. Browser verification tabs were closed afterward
so their ordinary live-update traffic would not keep the demo awake.

For an authentication, workflow, or memory regression, roll back only the affected
Render service to its retained deployment before `c405d57`. The preceding
deployment record is [VERIFICATION.md](VERIFICATION.md). No database migration or
LiveKit agent redeployment is part of this optimization.
