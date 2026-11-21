# Startup and login verification — 21 November 2026

All dates in this record use Asia/Rangoon unless a timestamp explicitly ends in
`Z` (UTC). Existing hosting, application design, accounts, data, endpoint formats,
authorization, call permissions, and model behavior are preserved.

## Post-wake login follow-up — 21 November

The API queues the workspace's authorized reads in one PostgreSQL pipeline and
collects their results after synchronization. Invitation expiry still precedes
the active-call read in the same transaction. Ticket-card lifecycle, assignment,
and estimate reads are also pipelined. The full response contracts are unchanged.

The frontend consumes the verified workspace response before page/history reads
can exhaust its ten-second cache. Guest workspace and home-progress fragments use
numeric `15` seconds instead of `"15s"`: the same refresh period without importing
pandas solely to parse an interval. Pandas remains installed for tables and
analytics. No authentication cache, model, schema, hosting, or styling change is
included.

### Controlled checks

All containers used Python 3.11, one CPU and a 512 MiB memory cap. Three fresh
processes were measured per variant. Supabase comparison transactions were rolled
back; no test requests or assignments were created in the hosted database.

| Measurement | Before | After | Interpretation |
|---|---:|---:|---|
| Cold frontend complete login run, median | 2.229 s | 1.333 s | 40% lower; simulated API responses isolate UI work |
| Warm authorized workspace read, median of 15 | 3.585 s | 2.334 s | 35% lower; Linux-to-Supabase test path |
| Immediate cold-process workspace read, median | 6.999 s | 6.639 s | 5% lower; includes first database/TLS connection |
| Immediate cold-process history read, median | 3.541 s | 3.016 s | 15% lower |
| Frontend test peak RSS | 149.0 MiB | 81.4 MiB | Guest render with simulated API |
| API test peak RSS | 381.5 MiB | 381.4 MiB | Including inference warmup |

The isolated cold API result does not meet the 20% reduction target by itself.
The complete cold frontend run does; these measurements are not a guarantee for
every hosted login. Immediate first-NLP waits were variable (median 2.488 s before,
7.488 s after); that request was issued immediately after the differently timed
workspace/history sequence. Equal-startup-time and hosted checks are recorded
separately rather than treating those as an equivalent inference comparison.
An additional pair requested NLP 35 seconds after readiness: 2.067 s before and
3.400 s after, including remote identity/database access. Other endpoint timings
also rose in that latter run, so this single local-network pair does not establish
an inference-speed regression or improvement. Classifier code and warmup ordering
are unchanged; the hosted NLP result is the release-relevant check.

- 130 affected authentication, workflow, consent, voice-turn, call-start,
  notification, lifecycle, startup, cache and UI regressions passed in Linux.
- After the numeric-interval adjustment, 31 UI/history regressions and all 12
  login regressions passed. The login test rejects pandas imports from interval
  parsing and simulates history taking longer than the workspace-cache lifetime.
- Full old/new workspace and ticket responses matched for existing guest,
  staff and supervisor accounts. Time-dependent minute counters were excluded
  from the ticket equality comparison.
- Real PostgreSQL checks passed for simultaneous actor isolation, pipeline
  failure propagation, rollback, subsequent request recovery and transaction-local
  role/actor reset. Preview tests also preserve invitation expiry and rollback.
- Ruff and changed backend/history type checks passed. The existing navigation
  formatter type diagnostic in `app.py` is also present in the saved baseline.
- The localhost-only Streamlit agent API verified valid guest/staff login,
  incorrect passwords, wrong entrances, and loader cleanup. Its server was stopped.

### Hosted warm checks

The API was deployed first and verified before the frontend rollout. One hosted
smoke sample measured guest workspace retrieval at 0.843 s, staff at 1.125 s,
and classification at 0.886 s. Five browser guest logins took 4.084, 4.442, 3.526,
3.642 and 3.347 seconds from click to the reception control (median 3.642 s).
Server-side workspace retrieval plus render for those five runs was 1.280–1.428 s.
Staff controls appeared after 3.944 s. Both screens had no browser console errors.

The initial frontend deploy's first login exposed 7.139 s of render work, leading
to the numeric-interval follow-up. The five warm measurements precede that final
two-interval adjustment; the final cold verification is recorded below.

During overlapping guest/staff browser sessions, sampled Render memory peaked at
approximately 222 MiB for the API and 136 MiB for the frontend, below 512 MiB each.
After the final revision's cold login and follow-up smoke checks, sampled memory
peaked at 217.3 MiB for the API and 116.6 MiB for the frontend (one-minute samples
through 05:05Z). These samples are not an instantaneous peak-memory guarantee.

### Hosted natural cold check

With Wavo tabs closed and no keep-alive traffic, Render logged the API's natural
shutdown at `2026-11-21T05:00:33.418Z`. Opening the public website subsequently
woke a new API instance. Application lifecycle startup completed in 0.198 s;
this excludes Render provisioning and Python imports before lifecycle startup.

On the final frontend revision, guest sign-in click to visible reception controls
took **9.366 s** in this one browser trial. The server separated the stages:

| Stage | Duration |
|---|---:|
| Supabase authentication | 1.526 s |
| Readiness wait at submission | 0.000 s |
| Authorized workspace response | 2.480 s |
| First workspace controls render | 1.045 s |
| Trailing optional guest history | 1.662 s |

The API had awakened during entrance/sign-in navigation, so zero readiness wait
at submission does not mean zero cold provisioning time. Total website-entry
cold-load duration was not reliably captured. Workspace retrieval plus render
took **3.525 s** after authentication. The normal guest controls appeared before
background model initialization finished; consent and call authorization remain
unchanged.

A subsequent smoke check passed guest and staff authentication and workspace
reads (1.130 s and 1.097 s respectively). Its first classification request took
1.155 s after background warmup completed, and repeat health took 0.100 s.
This does not measure inference submitted immediately at readiness. Together with
the variable controlled NLP results above, it leaves immediate-first-inference
non-regression unproven; no NLP behavior or warmup was changed in this rollout.

The natural cold check confirms successful login, not a paired 20% hosted cold
login improvement: the earlier baseline and this trial differ in provisioning
and navigation timing. The controlled frontend and warm workspace improvements
above are the comparable before/after measurements. Physical microphone checks
remain skipped as requested.

### Current rollout and rollback

- API: `c3e2b86f10ace132a7974841106d2554cf780dec`, deployment
  `dep-dc0hve97lnhs738nk3sg`.
- Frontend: `ed109472db4bdc2fe3ca828dc8458ae5150963f7`, deployment
  `dep-dc0i61ks728c73abt81g`.
- Pre-change rollback targets: API `dep-dc08vlu1egvs738cvmmg` at `172b645`; frontend
  `dep-dc0a47d9el5s73fe96v0` at `a7273d2`. Both remain compatible with the unchanged
  database. Retain these deployments; roll back only the affected service if
  authorization, workflow or memory checks regress.
- Both services remain Free in Singapore with automatic deployments disabled.
  No new service, disk, migration, LiveKit deployment or paid upgrade was used.

Runtime timing logs contain durations and query counts only: API `identity`,
`database_acquire`, `workspace_queries`, and `ticket_list`; frontend
`authentication_ms`, `readiness_ms`, `workspace_ms`, `render_ms`, and `history_ms`.
The history field measures the trailing guest history section; staff work-list
rendering is included in `render_ms`. Do not sum readiness with post-ready login
time when comparing the workspace optimization.

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
