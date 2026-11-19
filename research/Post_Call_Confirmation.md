# Wavo post-call confirmation

Implemented 18 November 2026. The receipt reads the saved service outcome; ending a call does not create a second request.

## Demo

1. Sign in as the Room 305 guest and call reception. Describe the AC not cooling, sleeping child and preference to stay in the room. Agree to maintenance.
2. End the call. The microphone stops immediately. After the backend acknowledges hang-up, Reception shows the specific problem, verified room, actual assignment and remaining completion estimate. **Track request** opens that request. **Calls → View outcome** reopens a saved receipt.
3. Sign in as the assigned maintenance worker. Start work, then report the repair and cooling check. The guest receipt replaces the estimate with **Yes, fixed / Still not working**.
4. Reject the first repair. The same request reopens and another eligible assignment is coordinated. A new assignment gets its own procedure estimate. Report the second repair and select **Yes, fixed** to resolve it.

Use the assigned name shown on screen: workload and assignment history can select Aung or Maya. Time passing never confirms a repair.

## Estimate configuration

Managers configure **Expected completion (minutes from assignment)** in approved procedures under hotel settings. Only the demo AC procedure is seeded with 15 minutes. Other procedures and historical assignments have no fabricated estimate.

Each assignment stores an absolute `expected_at`, a source, a revision and the notified revision. Refreshes calculate remaining time from that timestamp. The assigned worker or supervisor can use **Update completion estimate** within the task. Revised durations run from the update time, are version checked, audited and notify the guest. Procedure edits affect future assignments only.

Arrival estimates in call guidance and internal acknowledgment/service deadlines remain separate. An overdue completion estimate sends durable notifications once per revision to the owner and supervisors. The guest sees “the team has been notified” only after those notification records are committed.

## Interfaces and migration

- `GET /calls/{id}/result`: authorized, minimal structured outcome, linked ticket, actual assignment and current completion estimate; no transcript.
- `POST /tickets/{id}/completion-estimate`: staff authorization, active assignment ID, current estimate version (0 when absent), UUID idempotency key and minutes from now.
- Ticket responses include `completion_estimate`; assignment history remains intact.
- PostgreSQL: `supabase/migrations/20261118134808_completion_estimates.sql`. Applied to the configured demo project. Table RLS restricts application-role reads to permitted hotel service records; writes remain backend-controlled.
- SQLite adds the procedure column and creates the estimate table without replacing existing records. Fresh demo fixtures include the AC estimate. Historical estimates remain empty.

Wi-Fi confirmed resolved in the call shows **Resolved during your call**, without a ticket. Reception review shows its actual owner and next question without a repair estimate. Failed finalization retains the same call and cancellation key for retry; it never claims assignment from an unsuccessful response.

## Verification

Automated coverage: full Room 305 repair/rejection/reassignment/confirmation cycle; anchored timestamps; worker/supervisor revisions; stale versions and idempotency; own-task and hotel isolation; missing estimates; one overdue notification per recipient/revision; reception review; Wi-Fi without a ticket; SQLite upgrade compatibility; minimal unconsented results. Browser-component checks cover immediate microphone stop, duplicate hang-up, finalization failure/retry and late events.

Streamlit AppTest covers receipt tracking and confirmation. The final focused pytest run passed 18 tests; earlier dispatch/autonomy regression coverage passed as well. All 10 browser-component check groups passed. Desktop and 390px mobile browser checks use a separate SQLite fixture, including actual guest rejection and final confirmation. Hosted read-only checks verified the authenticated result endpoint, anonymous denial, application-role read policy and absent historical estimates. A transient identity-service failure occurred on one hosted read; the subsequent check passed.

These checks do not represent a new microphone-to-Gemini conversation test. The production voice path is preserved; the receipt is shared by live and local calls. No private transcript or hosted operational test request was created for browser verification.
