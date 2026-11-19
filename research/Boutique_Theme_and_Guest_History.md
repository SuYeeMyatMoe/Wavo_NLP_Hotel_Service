# Wavo: boutique theme and unified guest history

Implemented 18 November 2026 from the supplied welcome and hotel-service references. The user chose direct implementation without the 12ui converter.

## Guest experience

The landing page has the bear-and-arch hero, four service shortcuts, two hotel image cards and the existing Guest/Staff entrances. Service shortcuts preserve their context through login and open a draft; they never submit automatically. Existing photographs and the bear remain local assets. Four simple decorative SVG icons are served locally.

Guest navigation is **Reception · My requests**. Staff navigation is unchanged. The cream/espresso/brown theme applies to forms, navigation, request views, calls, staff screens, NLP Studio and Insights. Semantic warnings and safety states retain distinct colours.

**My requests** combines service requests and calls in a paginated table. Each service request appears once, with every associated call in **Reference & related calls**. Calls without a ticket remain separate records. A text request stays a text request when reception calls back. Voice messages have their own source label. Table references are shortened for scanning; details include full IDs.

Call duration measures connected elapsed time and is separate from expected service completion. Historical durations are unavailable; never-connected calls are identified separately. The service estimate continues counting down from its saved timestamp.

The request popup shows the actual owner and service-specific estimate together after text, voice-message or call submission. **Close** dismisses it and returns to the complete **My requests** table without resolving the request. **Track request** opens details below the table, keeping other requests visible. The recently acknowledged open request is also prioritised in the home progress card. Only explicit **Yes, fixed** confirms a repair.

## Interfaces

- `GET /guest/activity`: guest-only, hotel/guest scoped; `source`, `state`, `search`, `page`, and `page_size` filters. Returns grouped records, related-call metadata, staff assignment and completion estimates, without transcript text.
- `GET /guest/requests/{id}/calls`: authorized linked calls with full IDs, date, direction, outcome and individual duration.
- `GET /calls/{id}/result`: adds call duration and creation time to the existing outcome contract.
- Existing staff call and request APIs are preserved. Legacy guest navigation to Calls is mapped to My requests.

## Storage and installation

`20261118144013_guest_activity_timing.sql` adds a protected `call_timing` table. Database triggers record new call creation, first connection and first terminal status. Retries and reconnects do not reset timestamps. No historical timing rows are backfilled. Trigger writes are scoped to the changed call; application reads inherit the call's RLS authorization. SQLite uses equivalent triggers.

The migration was applied to the configured Supabase demo. The psql installer and regenerated SQL Editor installer include completion estimates and call timing. Existing installations should apply only missing migrations, not rerun the fresh installer.

## Verification

- Automated tests cover call/text grouping, callback origin, voice-message labels, standalone Wi-Fi resolution, ID search, pagination, guest/hotel isolation, transcript exclusion, timing retries, missing historical timing, receipt acknowledgment and service context through login.
- Existing completion/startup tests and browser media-state checks passed, including immediate microphone shutdown and retry behaviour.
- Desktop and 390px mobile checks covered landing layout, the unified table, opening linked request details, and a typed local call followed by assignment summary and OK returning home. This was explicitly Test mode, not a new LiveKit/Gemini microphone call.
- Hosted authenticated history and anonymous denial passed. PostgreSQL trigger/retry verification ran under the application role in a transaction that was rolled back; no hosted fixture calls remain.
- The regenerated fresh installer passed an isolated PostgreSQL-compatible check: 35 tables with RLS, private storage, Broadcast authorization and repeat-install refusal.

Browser proof files are in `.runtime/boutique-*`. Test fixtures use a separate SQLite database; they are not production service records.
