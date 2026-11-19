# Wavo call reliability checks — 18 November 2026

This is engineering verification, not NLP model evaluation. The deployed model,
training partition and academic metrics were not changed.

## Completed checks

- 54 Python regression tests passed across startup, consent, ownership, room
  handling, conversational NLP, autonomous staff workflow, UI caching, heartbeat
  recovery and delayed spoken results.
- Eight JavaScript media-state scenarios passed: gesture activation, stable
  rerenders, mute, blocked playback/recovery, immediate local hang-up, late events,
  pending microphone/startup cancellation, duplicate clicks, idempotent retry,
  reconnect, temporary status failure and missing worker. These are deterministic
  mocked-device tests, not claims about a physical speaker.
- Supabase additive migration applied; startup table RLS enabled and access
  denied to anon/authenticated/hotel_app. The backend verifies ownership before
  writing. Concurrent starts and cancellation-before-start passed in SQLite.
- A test process's own PostgreSQL connection was terminated on the server. The
  pool replaced it on checkout and preserved transaction-scoped actor/role
  isolation. No write was retried.
- The user confirmed the greeting was audible in their normal browser. They then
  reported that the breakfast request was transcribed without a spoken answer.
- The corrected breakfast path was tested with synthetic microphone audio in
  Room 512: an acknowledgement and the final reception-referral answer were both
  received as non-silent audio. The final answer's transcription was checked in
  memory for the appropriate referral, then discarded. The backend recorded the
  request and ended the call. No claim that breakfast was ordered was made.
- Supabase checks for that test showed **zero stored transcript rows** and one
  minimal analysis snapshot with transcript consent off.

## Measurements and limits

Earlier live synthetic check before the database optimization: startup 8.78 s,
first greeting audio 22.31 s, first reply audio 19.59 s.

After batching startup writes and warming NLP, two warm checks measured startup
2.84 / 2.77 s, greeting 13.52 / 13.59 s, Wi-Fi reply 8.39 / 8.70 s. Those trials
preceded the final acknowledgement and worker-admission changes.

The first breakfast test of explicit spoken follow-up measured acknowledgement
4.34 s and verified answer observation 20.06 s. Its greeting took 34.78 s during
a cold/CPU-contention period. This exposed the idle worker's CPU admission
problem; call-capacity admission and prewarmed TLS were added afterward.

Final repeated-call measurements are appended below when available. SDK synthetic
calls verify cloud audio generation/transport and backend behavior; they do not
independently prove playback through the actual Streamlit browser component.
The in-app test browser leaves microphone permission pending, so physical browser
reply playback needs the user's normal-browser check. No target is claimed on
that basis. Full service answers must not be confused with quick acknowledgements.

## Database advisor baseline

The private backend-only startup table intentionally has RLS and no policies or
client grants ([advisor explanation](https://supabase.com/docs/guides/database/database-linter?lint=0008_rls_enabled_no_policy)).
Pre-existing project warnings remain separate from this change: public execution
of `rls_auto_enable` ([guidance](https://supabase.com/docs/guides/database/database-linter?lint=0028_anon_security_definer_function_executable))
and disabled leaked-password protection ([guidance](https://supabase.com/docs/guides/auth/password-security#password-strength-and-leaked-password-protection)).

## Reproduce local checks

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
.\.venv\Scripts\python.exe -m pytest tests/test_call_start.py tests/test_voice_health.py tests/test_voice_turns.py tests/test_concierge.py tests/test_app.py tests/test_ui_cache.py tests/test_dynamic_rooms.py tests/test_intelligence.py tests/test_autonomy.py -q
node tests/phone_state.mjs
```

Live checks use demo accounts and normal tokens, with no clock-alignment bypass.
Wi-Fi confirmation in the synthetic benchmark is submitted as text through the
same engine. Breakfast is an unknown-procedure referral. Real bookings, menus,
orders, refunds and arrival commitments are not simulated as successful actions.

## Final verification, 18 November 2026

Five repeated live synthetic calls before the final transport correction all
returned both acknowledgement and the verified Wi-Fi answer. Startup API time
was 2.64–7.61 s, first greeting audio 11.95–13.58 s, acknowledgement 4.08–4.63 s.
Verified-answer observation was 19.92–22.36 s; this includes answer playback and
polling and is **not** a measurement of first final-answer audio. All five ended
cleanly and created no Wi-Fi tickets.

A remaining SDK stall was traced to separate aiohttp/websocket TLS contexts:
HTTPX uses `verify`, while those transports use `ssl`. All now reuse the
prewarmed, certificate-verified context. The measured worker entry-to-session
stage fell from an earlier 7.55 s to 2.84 s (and 2.67 s on the next call). Token
SDK imports also run at API startup. Three obsolete Wavo preview servers and a
stalled sandbox test were stopped; the current app and monitoring worker stayed
running. These observations do not establish causation for all network variance.

After the final restart, the first end-to-end call still measured startup API
6.25 s, greeting 16.81 s and acknowledgement 5.22 s. It spoke the approved Wi-Fi
answer, created no ticket and ended cleanly. **The five-second greeting and
four-second full-reply targets are not met.** Worker initialization improvements
must not be presented as equivalent end-to-end latency improvements.

The final focused Python suite passed 10 tests, in addition to the earlier
54-test regression run; all eight browser-state scenario groups passed again.
Desktop (1440×900) and mobile (390×844) browser checks confirmed the call card,
privacy disclosure, navigation and live-update recovery after API restart.
Screenshots are in `.runtime/wavo-call-ready-desktop.png` and
`.runtime/wavo-call-ready-mobile.png`. The temporary viewport was reset.

The final warmed breakfast test used the user's exact example with synthetic
speech in Room 512. Startup API: **4.36 s**; first greeting audio: **9.41 s**;
acknowledgement: **4.63 s**; verified-answer observation: **23.44 s** (includes
playback/polling). A reception-referral answer was received as audio, the backend
recorded the request, and hang-up reached Ended. This is one sample, not a latency
percentile or proof of browser speaker playback. The app/voice worker remain
running with these changes. An offline SDK construction check also confirmed no
new TLS contexts were built and certificate/hostname verification stayed enabled.
