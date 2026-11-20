# Hosted deployment verification — 20 November 2026

App: https://wavo-web-zcip.onrender.com

API health: https://wavo-api-zcip.onrender.com/healthz

API revision: `3e0e068d585bc1202142eae1934eee3db9e0e012`, deployment
`dep-dc07tq0m7kps73d67g2g`, confirmed live. Frontend revision remains `7f6e536`;
the subsequent changes affect the API, agent packaging, tests, and documentation.
LiveKit agent `CA_kYoPba5fTViK`, version `kJ4Kq9ZVWHd9`, is Running in `ap-south`
with dispatch name `hotel-reception`. No local voice worker was running during
the cloud-call checks.

## Code and automated checks

- Fixed dispatch of unverified public reviews: a room number alone does not
  establish a guest reservation. These records remain unassigned and escalate
  for reception verification. The regression covers both missing and supplied
  room numbers; the deployed API also passed this check.
- Gemini uses default sampling, one retry owner, up to three attempts, and a
  25-second total budget. Primary requests are capped at 12 seconds so a slow
  primary cannot consume all recovery time. The optional free-tier fallback is
  `gemini-3.5-flash-lite`; the primary remains `gemini-3.1-flash-lite`.
- Actual provider recovery was observed: the primary returned 504 for a Burmese
  sentence after 11.7 seconds; the fallback succeeded in 1.3 seconds.
- Quota, authentication, invalid-input, and malformed-output errors are not
  retried. Failed assessment preserves evidence and requires reception review.
- Final self-contained Linux test image: **240 passed**, one dependency
  deprecation warning, in 318.68 seconds with `docker run --rm --memory=512m
  wavo-linux-check`. No local speech or translation models were installed.
- Focused cloud/workflow checks also passed on Windows: **44 passed**. Ruff and
  `git diff --check` passed.

## Hosted checks

| Check | Observed result |
|---|---|
| All eight demo accounts | Authenticated using existing Supabase Auth |
| English, Mandarin, Hindi, Malay, Burmese text | All five completed request → assignment → staff completion → guest confirmation; final status Resolved |
| Original and translated evidence | Original input retained; non-English classifier evidence marked translated English |
| Recorded messages in all five languages | All five transcribed; all five have successful translation/classification results, with the Mandarin retry described below |
| Guest live call | Cloud greeting, synthetic spoken Wi-Fi question, returned audio, backend turn processing, and hang-up verified |
| Staff live call | Cloud greeting, synthetic assigned-task question, returned audio, and authenticated backend tool calls verified; database session confirmed Ended |
| Consent and duplicate operations | Consent withdrawal, idempotent call start/end, duplicate completion, room-scoped 180-second call tokens verified |
| Authorization and CORS | Missing worker auth rejected; guest record isolation enforced; preview header rejected; only the exact UI origin allowed |
| Restart and persistence | Three earlier resolved Supabase records survived service restarts; notifications resumed; no duplicate operation-action keys found |
| Secrets | Frontend has public configuration only; database uses TLS; shared worker authentication matches; no configured secret values found in tracked files |

The final five-language recording sweep had one Mandarin translation timeout
after successful transcription. It correctly required reception review. A
separate isolated replay of the same synthetic fixture then transcribed and
classified successfully. The original failure receipt was retained locally.
This is evidence of intermittent provider availability, **not** a claim of a
failure-free batch. Earlier checks also encountered provider 400/503/504 errors.
No billing upgrade was used to work around them.

Physical microphone permission, mute, and physical-device audio checks were
**skipped at the user's request**. Synthetic RTC calls validate the hosted audio
path, but do not replace those browser/device checks. Browser call cancellation
while microphone permission was pending was checked earlier.

## Free plans and resource limits

- Both Render services were reconfirmed on **Free**, in Singapore, with automatic
  deploy disabled. Observed one-minute memory samples peaked at approximately
  **294 MiB API** and **200 MiB frontend**, below each 512 MiB limit. These are
  sampled observations under verification traffic, not a guarantee for all loads.
- The existing Supabase organization was reconfirmed on **Free**. No database
  replacement or migration reset was performed.
- LiveKit remains on **Build**, with one deployed agent. The account dashboard
  showed no upcoming charge and usage well below the included session allowance.
- Gemini uses the existing free-tier project and free-tier models. No paid
  service, disk, database, worker, or upgrade was created.
- SDK recording and project Agent observability are disabled. Application
  transcript consent is enforced separately; provider free-tier data-use terms
  still apply.

Free Render sleep and provider quotas remain intentional demo constraints.
Use the [runbook](README.md) for startup delays, redeployment, and rollback.
