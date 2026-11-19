# Service insights definitions

The dashboard is operational decision support, not a claim of financial ROI.
It uses authorized records from the current hotel. Regular staff see records
for their own current assignments; supervisors see hotel-wide records.

- Current workload includes all unresolved requests, even when created before
  the selected performance period. Needs-attention counts distinct requests;
  their reasons can overlap. Order is urgency, then creation time and stable ID.
- Service overdue means an active assignment has a recorded service deadline
  in the past. Awaiting-confirmation work is excluded. Missing deadlines are
  counted separately, never considered on time. Targets are internal, not ETAs.
- Historical periods use UTC calendar days including today. Confirmed resolution
  is currently closed requests with an explicit guest/manager confirmation,
  divided by requests opened in that period. A plain Resolved event is not proof.
- Typical resolution is the median creation-to-final-confirmation duration for
  those confirmed requests. Sample sizes appear alongside the metrics.
- Reopening counts distinct requests with a guest rejection, not every attempt.
- The demand chart uses actual opening dates and final confirmation dates;
  confirmations may relate to requests opened before the selected period.
- Calls resolved without a task require an ended inbound call, guest-confirmed
  resolution, no linked service ticket, and no recorded staff join. This does
  not estimate minutes saved, labor cost, guest satisfaction or revenue.
- Repeated room requests can involve different problems or guests. They prompt
  investigation; they are not evidence of a failed repair on their own.
- Sentiment is secondary, counted per request rather than per spoken turn.
  Missing evidence remains missing. Demo/test records remain included and labelled.

The API batches event and lifecycle reads instead of issuing one history query
per request. Analysis, calls and work history are preserved. The What-if screen
was removed from navigation; shared analysis and historical research are unchanged.

Verification: 32 tests passed across business metrics, Streamlit, intelligence
and autonomy, including own-assignment scope, missing deadlines, old backlog,
explicit confirmation, reopened work and the call-resolution denominator.
