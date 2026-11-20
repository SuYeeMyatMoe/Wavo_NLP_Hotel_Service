"""Session-local handoff between browser finalization and the receipt dialog."""

from copy import deepcopy


def accept_finalization(state, cache, event):
    if not event:
        return
    signature = (event["key"], event["status"], event.get("call_id"))
    if signature == state.get("last_finalization"):
        return
    state["last_finalization"] = signature
    key, call = event["key"], event.get("call_id")
    dismissed = state.get("dismissed_finalization") == key
    if event["status"] == "complete":
        state.pop("finalizing_call", None)
        if dismissed:
            state["dismissed_call"] = call
            return
        if call:
            result = event.get("result")
            if result and result.get("finalized") and result.get("call_id") == call:
                cache[("receipt", f"/calls/{call}/result")] = deepcopy(result)
            state["completed_call"] = call
    elif not dismissed:
        state["finalizing_call"] = event


def dismiss_pending(state):
    pending = state.pop("finalizing_call", None)
    if pending:
        state["dismissed_finalization"] = pending["key"]
        if pending.get("call_id"):
            state["dismissed_call"] = pending["call_id"]
