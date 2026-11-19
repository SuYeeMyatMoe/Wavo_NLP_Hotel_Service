# Wavo hotel operations

Wavo combines a Streamlit guest concierge, an explainable NLP Studio and automatic staff coordination and a conversational work assistant. Google Colab owns training, model comparisons and research charts. The deployed analysis engine contains the selected urgency and department classifiers, deterministic context rules and NLTK VADER sentiment.

## Run locally

Use Python 3.11 from this project directory:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m hotel.language_models
.\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501
```

Open http://127.0.0.1:8501 in separate guest and staff tabs. Each sign-in form has **Use demo account**, which fills the fields, followed by **Sign in**.

After a text request, voice message or ended call, a **Request update** popup shows the actual assigned team member and the service procedure's completion estimate. **Close** (or the popup's X) returns to **My requests** without resolving the work. **Track request** opens details below the full history table. The table remains visible while reviewing progress, activity and guest confirmation. Estimates count down from the stored assignment timestamp; services without a configured estimate say the team will confirm it. Configure service durations under Supervisor → Hotel settings → Procedures; only the demo AC procedure has a seeded 15-minute estimate.

| Role | Email | Password |
|---|---|---|
| Guest, Room 305 | guest@wavo.demo | Guest305! |
| Guest, Room 402 | guest402@wavo.demo | Guest402! |
| Guest, Room 512 | guest512@wavo.demo | Guest512! |
| Maintenance worker | maintenance@wavo.demo | Staff123! |
| Supervisor (same Staff portal) | staff@wavo.demo | Staff123! |

These public demo accounts simulate local authentication. Preview uses SQLite and a local identity header and is intended for loopback demonstrations. Hosted mode uses Supabase Auth and server-verified identity. Existing local records are preserved when the additive tables are initialized.

Supervisors open **All tasks** in the Staff portal to see every guest request in their hotel. Filter by department, assigned worker, problem category, status, or room/request ID. The hotel-wide counts stay unchanged by filters, and the table refreshes every 10 seconds. **Completed** shows task history; **Open** includes escalated and unassigned requests. Open any row to review constraints, work attempts and guest confirmation. Regular workers still see only **My work**. Completion estimates are separate from internal deadlines; missing estimates show **Not set** and elapsed estimates show **Overdue**, never automatic resolution.

Guest sign-in includes a **Demo reservation** selector. Choose a guest, then **Use demo account → Sign in**. Rooms shown there come from current reservations, so supervisor changes are reflected automatically. The selection fills credentials; the account actually signed in determines the room.

To use another room number, sign in as the supervisor and open **Staff workspace → Hotel settings → Reservations**. Select the guest, enter the verified room and stay dates, and save. New complaints, calls and assignments use that room; existing requests retain their original room for an accurate service history. A room mentioned in complaint text cannot override the reservation. Hosted accounts follow the same reservation lookup, without the demo selector.

## Room 305 demonstration

1. Guest → **Reception → Call AI Reception**. For the local fallback the screen says **Test mode**. With LiveKit and Gemini configured, this is a real two-way live call. Accept transcript storage only if you want to retain detailed call evidence.
2. Say: **The AC is not cooling. My child is asleep. Can someone help without us having to move?** When asked, agree to send maintenance. Alternatively send a text request including “Please send maintenance.” The verified reservation supplies Room 305.
3. Staff → **My work**. Eligible maintenance staff receive an automatic assignment and an in-app notification. Open the task to see room, priority rank, waiting time, constraints, approved instructions and the internal service deadline. No status/routing buttons are required.
4. In **Work assistant**, type or say **I'm starting the AC repair in Room 305.** Then report **I repaired the AC in Room 305 and checked the cooling.** Only the assigned worker may report. Completion is recorded as staff-reported, awaiting guest verification.
5. Guest → **My requests → Open request → Still not working**. Wavo reopens the same request and creates another assignment attempt. The next eligible worker can be different; check the supervisor overview or the new assignee's inbox.
6. The new assignee reports the second repair through the assistant. Guest chooses **Yes, fixed**. Show the completed record, work history, verified agent actions and Insights. Silence never resolves a request.
7. **NLP Studio → Analyze** runs the same deployed engine on the original complaint. Walk through all eight evidence stages. Analysis never creates a task.

For a two-tab presentation, the seeded backup worker is visible to the supervisor. To continue as the second worker locally, use the test API identity `demo-maintenance-2` or the backup login `backup@wavo.demo` / `Staff123!`. Both workers use the same Staff login portal.

**NLP Studio → What-if** compares two wordings without creating tickets. Try “The AC is not cooling” and “The AC works, but the shower leaks.” **Evaluation** shows the deployed models only. Model comparisons remain in Colab and the technical report.

## Calls and structured notes

Guests select **Call AI Reception**, enable their microphone, speak and pause. **Test mode** uses Whisper, translation, the shared NLP engine, approved hotel responses and synthetic speech. The focused bear screen supports mute, replay, typed replies and immediate hang-up. Background inference cannot dispatch work after the call ends.

Demonstrate Wi-Fi guidance followed by “Yes, I am online.” It saves a resolved call note without a work ticket. Demonstrate AC repair followed by consent to send Maintenance. The task appears during the call. Service estimates and ready rooms come from Hotel availability; room moves require front-desk approval.

Supervisors → **Calls → History** shows all hotel calls; regular staff see calls linked to their own tasks. History includes with room, issue and outcome. Open a record for the structured service note, consented speaker turns, conversation NLP timeline and versioned note corrections. Supervisors retain reception handoff controls under Calls.

Text and speech can switch between English, Mandarin Chinese, Hindi, Malay and Burmese. Interface language is a separate setting. Non-English classification uses an English working translation, labeled accordingly. Small functional checks do not establish language-specific recognition accuracy.

## Transcript privacy

Transcript storage is **off by default**. The guest can opt in before calling or change it under **Call privacy** during the call. Without consent, Wavo processes speech transiently and retains only necessary service fields such as issue category, room, access constraints, operational predictions and outcome. It does not retain detailed word evidence or raw conversation text in new call records. Hang-up clears queued jobs and browser/session audio buffers.

Turning transcript storage off removes stored conversation evidence and sanitizes linked voice-ticket snapshots. Staff-reviewed service notes and work outcomes remain necessary service records. Callback permission is separate. Previously stored legacy records are preserved by migration; they do not acquire retroactive consent. Contact patterns are masked in saved transcripts, but names and contextual identifiers are not comprehensively anonymized. LiveKit recording is explicitly disabled; app-owned transcript writes check guest consent. Cloud voice providers have separate processing terms.

## Approved hotel procedures

Staff account menu → **Hotel settings → Procedures**. Managers choose a category, responsible team, approved actions, optional constraint conditions, clarification questions and approval requirements. Clarification rows use `field | question`. Known room, issue, equipment and extracted constraint fields are skipped.

A single most-specific matching procedure is used. Conflicting rules, unknown categories and multiple active issue categories go to reception review. Safety escalation takes precedence. Legacy Knowledge notes remain available for manager categorization and are not automatically executable guidance. There is no runtime RAG or vector database. TF-IDF remains part of classification.

## Colab and assessment

Open `research/Hotel_NLP_CRISP_DM.ipynb` in Google Colab, upload `research/colab-project.zip` when prompted, and run all cells. The notebook covers all six CRISP-DM phases, preprocessing, stemming/lemmatization comparison, unigram/bigram TF-IDF, stratified partitioning, training-only tuning, evaluation, actual errors, dialect audit and deployment export. The included outputs were executed locally using Jupyter.

Logistic Regression and LinearSVC train on the same original 835 reviews and validation folds. Weighted logistic regression is tested both on that cohort and with 31 separate safety training rows. The 210-review holdout and 16-review challenge remain excluded from fitting and tuning. The holdout has been inspected historically and must not be represented as newly unseen data.

The validation-selected urgency model reaches **0.938 macro F1**, compared with the historical LinearSVC baseline's **0.660**. Critical holdout detection is **2/2**, and the separate challenge is **3/5**, with zero false Critical alerts. Department macro F1 is **0.861**. The separate augmented experiment scores 0.962 on the holdout but was not selected by validation. All labels remain provisional. Independent annotation and a fresh final evaluation are still required. No accuracy claim is made for the rule-based extraction or VADER sentiment.

The report is `research/Technical_Report.md`. Export and replace the entire trusted artifact bundle together, then restart API and Streamlit. Never load untrusted joblib files. The previous deployed bundle is preserved locally in `.runtime/model-before-studio/`.

## Supabase setup

Copy `.env.example` to `.env` only if `.env` does not exist. Set `HOTEL_MODE=connected`, `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, and a TLS direct/session-pooler `DATABASE_URL`. Keep database and voice secrets on backend services.

For a fresh project, open `supabase/wavo_sql_editor.sql`, copy its entire contents into **Supabase Dashboard → SQL Editor → New query**, and run as `postgres`. This standalone installer creates the schema in one transaction, with no psql include commands. It refuses to run over existing Wavo tables; use the upgrades below for an existing installation. Select the **hotel** schema in Table Editor afterward. Rebuild the standalone file after schema changes with `node supabase/build_sql_editor.mjs`.

Guest navigation now combines calls and requests in **My requests**, with separate call-duration and service-completion columns. After a request or call, **Close** dismisses the assignment popup and returns to the full **My requests** table without resolving work. See `research/Boutique_Theme_and_Guest_History.md`. Existing databases also need the completion-estimate migration (`20261118134808_completion_estimates.sql`) and call-timing migration (`20261118144013_guest_activity_timing.sql`) if not already applied; both are included in the current fresh installer. Historical call durations and completion estimates remain empty.

Alternatively, run in psql as the database owner:

```sql
\i 'supabase/install.sql'
```

For an existing installation, apply missing earlier upgrades first, then:

```sql
\i 'supabase/guest_messages.sql'
\i 'supabase/concierge.sql'
\i 'supabase/work.sql'
\i 'supabase/intelligence.sql'
```

The new SQL is also in `supabase/migrations/20261118021606_intelligence.sql`. The psql wrapper sets up its transaction. It preserves existing records and unused vector tables, and fresh installations need no vector extension. The private hotel schema uses restricted-role grants and RLS. Transcript erasure uses the trusted backend only after authenticating the linked guest. Note revisions and analysis snapshots are append-only for the application role.

Create guest/staff users in Supabase Auth and provision their `hotel.profiles` rows administratively using real Auth UUIDs, hotel, role, room and stay dates. Guests cannot choose their own roles or rooms. Start FastAPI independently with `python -m uvicorn hotel.service:app --host 127.0.0.1 --port 8000`, set `HOTEL_API_URL=http://127.0.0.1:8000`, and restart Streamlit.

The persistent backend reuses a small PostgreSQL connection pool (`WAVO_DB_POOL_MAX=4` per process) and HTTPS connections to Auth. Every backend request still validates its bearer token; database roles and actor identifiers are transaction-local and reset before reuse. Streamlit caches only session-scoped display metadata, clears it on writes, sign-out/account changes and realtime events, and fetches operational record versions fresh. One lightweight workspace refresh replaces separate history/notification polls. The centered bell belongs to foreground navigation; background updates do not show a loading overlay.

For the connected **Wavo demo project**, add `DATABASE_URL` and `SUPABASE_SECRET_KEY` to `.env`, then run `.\.venv\Scripts\python.exe supabase/provision_demo.py`. It creates six confirmed demo Auth users through the server-only Admin API and links three guest reservations, two maintenance workers and a supervisor. Repeating it preserves existing passwords, room changes and roster edits; unrelated existing accounts are not adopted. Set `WAVO_DEMO_LOGIN=true` to show account autofill in both hosted login portals. This still uses real Supabase authentication, rather than local preview identities.

If Gemini Live is unavailable, explicitly set `WORK_ASSISTANT_MODE=test` for the staff report parser. The staff screen labels this **Test mode**, while authentication, assignments and work updates still use the configured Supabase database. Set it back to `live` after verifying the Gemini integration. Database mode and conversation mode are independent.

Local PostgreSQL-compatible tests cover migrations and RLS. The configured Wavo demo's hosted Auth, automatic assignment, repair/reopening/confirmation and notification publication were verified on 18 November 2026. Live audio is a separate check; database verification alone does not verify calls.

## LiveKit and Gemini

- LiveKit project URL and keys: https://cloud.livekit.io/ → project settings → Keys.
- Gemini key: https://aistudio.google.com/apikey → create a key.

Set `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`, `GOOGLE_API_KEY` and `GEMINI_LIVE_MODEL` in `.env`. Keep keys out of source control and browser code. Then:

```powershell
.\.venv\Scripts\python.exe -m pip install -r hotel/voice-requirements.txt
.\.venv\Scripts\python.exe -m hotel.voice_worker dev
```

Keep the worker running and restart Streamlit after changing environment values. Local SQLite demo mode can use live voice without Supabase credentials. Hosted deployments require persistent API/worker processes, HTTPS microphone access, verified tenant isolation and real audio tests. Background jobs use one API process or sticky routing.

The Gemini Live integration explicitly uses `v1alpha`; the installed SDK's stable `v1` default does not expose the live preview endpoint. `WAVO_VOICE_IDLE_WORKERS=1` keeps one warm call worker on a local machine. Increase this on a dedicated host as needed.

Keep the host clock synchronized. Guest call tokens last three minutes: a computer clock several minutes behind the provider can cause `401 Unauthorized — invalid token` even with correct keys. On Windows, use **Settings → Time & language → Date & time → Sync now**. Do not extend token permissions or expiry to work around a clock mismatch.

## Verification and interfaces

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
.\.venv\Scripts\python.exe -m pytest -q tests
```

`POST /analyze` returns classifier outputs, intent, scoped issues, sentiment, extraction, provenance and procedure selection. Existing ticket and call endpoints remain available. New interfaces are `/procedures`, `/insights`, `/calls/{id}/transcript-consent`, and `/calls/{id}/note-review`. Staff call records include consented turns, analysis snapshots and review history. The API documentation is at `/docs` on the FastAPI host.

## Models, imagery and attribution

Local speech uses `Systran/faster-whisper-small`. Translation uses the int8 conversion of Meta NLLB-200 distilled 600M, licensed CC BY-NC 4.0 for this academic demonstration. The app uses scikit-learn classifiers, not DistilBERT. Earlier encoder experiments remain archived under `research/archive`; they are not deployed or loaded by the app.

VADER lexicon attribution is in `artifacts/VADER_NOTICE.md`. Wavo retains its generated bronze bell logo and brown bear concierge. Pexels photography is credited to Faheem Ahamad (photo 40624417), Roshan Patel (20653866), and Musa Ortaç (31080809).

## Autonomous service operations

Run the persistent monitor/outbox worker in another terminal, even when Streamlit is closed:

```powershell
.\.venv\Scripts\python.exe -m hotel.operations_worker
```

Use `--once` for a single diagnostic cycle. Preview uses SQLite transactions and polling inboxes. Connected mode uses PostgreSQL row locks and private Supabase Broadcast invalidations. Notifications remain in the database if delivery fails; the worker retries up to six times with bounded backoff. Published and read are separate states. Service records remain available during a Realtime outage.

Dispatch checks verified hotel, department, equipment skills, active shift, availability and capacity. Eligible workers are sorted by active workload, oldest previous assignment and stable ID. Default demo acknowledgment/service targets are Urgent 2/15, Moderate 5/30 and Low 10/60 minutes. Critical and Unassessed require immediate supervisor review. One reminder precedes at most one automatic replacement per service attempt. Work already started is never automatically reassigned. Confirmation reminders occur after 30 minutes; after 24 hours the supervisor reviews the still-open case.

Supervisor account menu → Hotel settings contains approved Procedures, Staff roster, Deadlines and Reservations. Existing unresolved records are preserved for review instead of unexpectedly assigning them. After correcting missing guidance or roster data, a supervisor can tell the work assistant “retry assignment VF-…”. Eligibility is checked again. No free-form request can bypass safety escalation.

Operational interfaces include `/work-assistant/turns`, `/work-assistant/sessions`, `/notifications`, `/work-history`, `/agent-actions`, `/tickets/{ref}/assignments` and manager-only `/operations/*`. Mutations use turn identifiers or optimistic versions. Legacy ticket endpoints remain compatible with assigned-worker authorization.

## Connected deployment

Use separate persistent services for FastAPI, the operations worker and LiveKit. Streamlit Community Cloud hosts only the UI. Do not run background monitoring inside a Streamlit session. No Docker is required.

1. Apply `supabase/install.sql` for a fresh database, or `supabase/operations.sql` to upgrade the previous installation. The CLI migration is `supabase/migrations/20261118043215_autonomous_service_recovery.sql`. Back up existing data first. Historical tickets and evidence remain intact.
2. Create Guest, maintenance, backup maintenance and supervisor users through Supabase Auth. Link their IDs to profiles. `supabase/seed.sql` accepts those four UUIDs as psql variables and creates **demo-only** roster, reservation, policy and availability fixtures.
3. Backend environment: `HOTEL_MODE=connected`, `DATABASE_URL`, Supabase URL/publishable key, `SUPABASE_SECRET_KEY` for private Broadcast, and LiveKit/Gemini keys. Start `python -m uvicorn hotel.service:app --host 0.0.0.0 --port 8000` behind HTTPS. The backend needs the optional voice requirements for live tokens and Gemini work-report interpretation.
4. Operations worker: same database mode/URL and Broadcast credentials; start `python -m hotel.operations_worker` with automatic process restart.
5. Voice worker: `HOTEL_API_URL` pointing to the HTTPS backend plus LiveKit/Gemini credentials; start `python -m hotel.voice_worker start`. It performs all service actions through call-scoped authenticated APIs and has no direct database access. Provider log bodies and recording are disabled to protect unconsented text.
6. Streamlit environment: `HOTEL_MODE=connected`, `HOTEL_API_URL`, `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`. Never place service-role, Gemini or LiveKit secret keys in component data. Private channels are scoped to the authenticated user's ID; only notification identifiers are broadcast.
7. Verify live audio, interruption, hang-up, consent, assignment, notification delivery and worker restart on the deployed services. These checks require configured accounts; local tests are not evidence of hosted success.

The bundled browser dependency is Supabase JS 2.119.0 from its official jsDelivr package distribution. Refresh user authentication when the access token expires; the notification inbox continues to recover persisted updates after reconnect.

### Browser call startup and recovery

Apply the additive `supabase/call_start.sql` upgrade (also saved as
`supabase/migrations/20261118105627_reliable_browser_calls.sql`). Fresh installers
already include it. SQLite creates the matching `hotel/call_start.sql` table.
The private startup table is backend-only, with RLS and no client grants.

Set `WAVO_BROWSER_API_URL` to the API address reachable **from the guest browser**
and `WAVO_BROWSER_ORIGINS` to the exact Streamlit origin(s), comma-separated.
The local defaults are `http://127.0.0.1:8000` and
`http://localhost:8501,http://127.0.0.1:8501`. Hosted UI/API URLs must use HTTPS.
Do not use wildcard origins. The browser receives its user's access token and a
three-minute room token, never provider or database secrets.

The browser's single call button activates audio and requests microphone access
before making `/calls/start`. That endpoint atomically records the call, consent
and retry key. `/calls/start/{key}/cancel` also handles hang-up before startup
finishes. Existing call endpoints remain available. Mic tracks and playback stop
locally before network cleanup. Background Streamlit rerenders keep the media
component mounted. An `Audio check` disclosure exposes only timing/device state.

The voice worker uses `report_turn` for both NLP and approved hotel guidance.
Slow work receives a short acknowledgement, then an explicit spoken result after
the backend commits. No assignment or ordering claim is made while processing.
This does not make the underlying operation instant. Provider interruption,
network latency and database distance still affect response time.

`WAVO_VOICE_IDLE_WORKERS=1` keeps a worker warm. On the local laptop,
`WAVO_VOICE_ADMISSION=calls` and `WAVO_VOICE_MAX_CALLS=2` use active-call load
instead of unrelated whole-machine CPU bursts. A dedicated production host can
select `WAVO_VOICE_ADMISSION=cpu`. TLS certificates are verified and their context
is warmed once per worker. A single missed heartbeat no longer ends a call;
four consecutive failures do. Explicit ended status still shuts it down.

Verification and measured limitations: `research/Call_Reliability_Checks.md`.

## Label review and reproducibility

`research/label_review_worksheet.csv` contains 1,045 provisional records with frozen partition/hash provenance and blank reviewer fields. To create a fresh worksheet without overwriting existing annotations:

```powershell
.\.venv\Scripts\python.exe research/label_review.py research/review_batch_02.csv
```

Reviewers supply identity, UTC timestamp, revised urgency/department and rationale. Keep original labels, texts and partition hashes unchanged. Reviewed labels must be published as a separately versioned dataset and evaluated separately, not used to silently rewrite historical scores or tune against the frozen test set. The notebook has been executed locally and is Colab-ready; execution in a Google Colab account is a separate verification step. This operations upgrade does not claim new model performance.
