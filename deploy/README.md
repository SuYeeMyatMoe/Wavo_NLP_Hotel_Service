# Wavo free hosted demo

The UI and API run on two **Free** Render web services in Su Yee's workspace.
The existing Supabase project stores all durable data. LiveKit Cloud's **Build**
plan runs the `hotel-reception` agent; Gemini provides live audio, translation,
and transcription. No laptop worker is required for the hosted app.

## Build and configure

1. Validate `render.yaml` with `render blueprints validate render.yaml` in the
   intended workspace. Commit and push before creating/syncing the Blueprint.
2. Supply the required variables through Render's secret settings. Use the
   existing Supabase TLS **session pooler** connection, not a new database.
3. After Render assigns URLs, set the frontend's `HOTEL_API_URL` and
   `WAVO_BROWSER_API_URL` to the API HTTPS URL. Set the backend's
   `WAVO_BROWSER_ORIGINS` to the exact frontend HTTPS origin, without a trailing
   slash. Free services must communicate through public URLs.
4. Preserve `HOTEL_MODE=connected`, `WAVO_LANGUAGE_PROVIDER=gemini`,
   `WAVO_RUN_OPERATIONS=true` on the API and `WAVO_WAKE_API=true` on the UI.
   Keep one Uvicorn process. Do not also start a separate operations worker.
5. Frontend: Supabase URL and publishable key only. Backend: database URL,
   Supabase server secret, LiveKit credentials, and Gemini key. Never put these
   secrets in browser component data, Git, or deployment logs.
6. Authenticate the LiveKit CLI to the existing project. Use the repository's
   Dockerfile and `lk agent create --secrets-file <private-file> --region <region>`.
   Keep the generated `livekit.toml` for subsequent deployments. LiveKit supplies
   project credentials; the private secrets file needs `HOTEL_API_URL`,
   `GOOGLE_API_KEY`, `GEMINI_LIVE_MODEL=gemini-3.1-flash-live-preview`,
   `WAVO_VOICE_IDLE_WORKERS=0`, `WAVO_VOICE_MAX_CALLS=2`, and
   `WAVO_VOICE_ADMISSION=calls`. Never upload the full local `.env` to the agent.
7. Confirm guest and staff live calls use the cloud agent. Stop local workers
   connected to the same project during this check to prevent competing dispatch.

The agent image intentionally excludes model weights, training data, UI assets,
local environments, and database libraries. `record=False` disables SDK audio,
transcript, trace, and log uploads. Application transcript consent remains
enforced separately by the backend.

## Operation and limits

- Render sleeps after 15 idle minutes; initial loading may take about a minute.
  The UI retries only readiness reads for up to 120 seconds. Calls allow another
  60 seconds for the voice agent to join. Ending a connecting call stops the mic.
- Both Render services share 750 free instance hours per workspace per month.
  Do not use keep-alive pings. Two services cannot both run continuously all month
  within that allowance. Monitor Render Billing for bandwidth/build allowances.
- Operations run every 15 seconds while the API is awake, with immediate catch-up
  after restart. Deadlines and outbox jobs persist in Supabase; sleep delays their
  processing. Guest silence never resolves a task.
- LiveKit Build currently includes one agent deployment and 1,000 agent-session
  minutes. Free limits and Gemini quotas can reject new work. No paid fallback is
  enabled. Confirm account plans and remaining usage before a demonstration.
- `gemini-3.1-flash-lite` handles language conversion; trained scikit-learn models
  still classify English input. Provider errors do not produce fabricated text
  or work confirmation. Messages that cannot be assessed go to reception review.
- This is an academic demo using public demo accounts. Gemini's free API tier has
  provider data-use terms; app transcript consent is not a provider-retention guarantee.

## Verify and redeploy

Run `python -m pytest -q tests`. For a clean Linux check without local speech models:

```sh
docker build -f deploy/Dockerfile.check -t wavo-linux-check .
docker run --rm --memory=512m wavo-linux-check
```

Check API `/healthz` and frontend `/_stcore/health`. Verify real Auth, guest/staff
isolation, a multilingual request, assignment, staff report, guest confirmation,
recorded audio, and a live call. Check microphone denial, mute, hang-up, consent,
provider quota errors, duplicate submissions, and sleep/restart recovery.
Measure each service against its 512 MB budget under guest and staff use.

Automatic deployment is disabled to control free build usage. After pushing,
manually deploy the intended commit for the two Render services. Redeploy the
agent using `lk agent deploy --secrets-file <private-file>` and check
`lk agent status`. Watch each deployment until it is live, then repeat smoke tests.

For rollback, use Render's retained prior deployment and deploy the last known
working Git revision to LiveKit (Build does not include instant rollback).
Application rollback does not undo database changes. Never reinstall the fresh
Supabase schema over the existing hotel data.

References: [Render free limits](https://render.com/docs/free),
[LiveKit quotas](https://docs.livekit.io/deploy/admin/quotas-and-limits/),
[Gemini pricing](https://aistudio.google.com/docs/pricing).
