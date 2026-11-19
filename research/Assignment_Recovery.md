# Assignment recovery

The previous dispatcher escalated unfinished calls without assigning anyone to
the follow-up. Hang-up also attached a physical-service permission question to
Wi-Fi cases, and the hosted demo roster had only maintenance workers.

The dispatcher now uses the approved procedure's department for service routing.
The original trained department prediction and immutable analysis snapshots are
preserved. Missing permission, missing guidance, conflicting rooms, denied access,
or unavailable service staff produce an owned reception review. Critical and
Unassessed cases retain immediate escalation and require an eligible supervisor.
Roster availability, hotel, role, skills, shift, capacity and deterministic load
ordering still apply. If no reception worker qualifies, escalation stays visible;
the system never invents an assignment.

Approved Wi-Fi guidance is reception work, not a room visit. Staff can deliver it
and report completion; only guest confirmation resolves the request. A reception
review cannot be submitted as a completed repair. Its owner can ask for details
or recheck assignment after the guidance/roster is corrected.

Guests open **My requests → Open request → Update this request** to clarify an
incomplete issue. The checkbox records permission to arrange service; access
restrictions still take precedence. The same request ID is retained, earlier
assignment attempts remain in history, and a new minimal NLP snapshot records
the clarification. Original conversation evidence is never overwritten. The
update requires the linked guest, an active unchanged reservation, current
version and an idempotency key. Concurrent updates cannot double-dispatch.

Text discarded by earlier consent-off calls cannot be reconstructed. These
records remain labelled **Issue details unavailable** until the guest clarifies.
The update stores a controlled service summary, not the guest's raw wording.

## Demo accounts

All staff use the existing Staff login portal and **Use demo account** autofill.
Maintenance: `maintenance@wavo.demo` and `backup@wavo.demo`.
Reception: `reception@wavo.demo`. Housekeeping: `housekeeping@wavo.demo`.
Supervisor: `staff@wavo.demo`. Public demo password: `Staff123!`.
The broad demo shifts/capacities are demonstration configuration, not real rosters.

`supabase/provision_demo.py` adds missing tagged demo accounts/rosters without
resetting passwords. `supabase/recover_assignments.py` previews affected records;
`--apply` rechecks unowned escalations through the real dispatcher and makes
already-approved remote guidance actionable. It is restricted to the configured
Wavo demo project, refuses active calls, preserves history and is safe to rerun.

## Verification

`tests/test_dispatch_recovery.py` covers recovery of the same request through
guest clarification, automatic maintenance assignment, repair, guest rejection,
second repair and confirmed resolution. It checks unauthorized/stale/duplicate
updates, immutable snapshots, minimal retention, denied access, approved
department routing, Wi-Fi follow-up and supervisor ownership of safety cases.
`tests/test_app.py` exercises the actual guest clarification form. Existing
autonomy, intelligence, concierge, UI and insights regression tests remain in use.
Hosted data repair and browser checks verify persistence/ownership separately
from the isolated SQLite end-to-end tests; they do not assert a real repair or
real guest confirmation occurred.
