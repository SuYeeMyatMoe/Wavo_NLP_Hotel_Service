"""Give slow service work an acknowledgement, then speak its verified result."""

import asyncio
import logging


class VoiceTurns:
    def __init__(self, process, notify, *, grace=2.0):
        self.process, self.notify, self.grace = process, notify, grace
        self.tasks = {}
        self.followups = set()
        self.watchers = set()
        self.lock = asyncio.Lock()
        self.closed = False

    async def run(self, key, text):
        if self.closed:
            return {"status": "ended"}
        if key not in self.tasks:

            async def ordered():
                async with self.lock:
                    if self.closed:
                        return {"status": "ended"}
                    return await self.process(key, text)

            self.tasks[key] = asyncio.create_task(ordered())
        task = self.tasks[key]
        done, _ = await asyncio.wait({task}, timeout=self.grace)
        if done:
            try:
                return task.result()
            except Exception:
                return {
                    "status": "unavailable",
                    "reply": "I could not confirm the result with the hotel. Please ask reception to check.",
                    "action_confirmed": False,
                }
        if key not in self.followups:
            self.followups.add(key)

            async def followup():
                try:
                    result = await task
                except asyncio.CancelledError:
                    return
                except Exception:
                    logging.getLogger("wavo.voice").warning(
                        "voice_service_result_unavailable"
                    )
                    result = {
                        "reply": "I could not confirm the result with the hotel. Please ask reception to check before assuming anything was arranged."
                    }
                if not self.closed:
                    try:
                        await self.notify(result)
                    except Exception:
                        logging.getLogger("wavo.voice").warning(
                            "voice_followup_playback_unavailable"
                        )

            watcher = asyncio.create_task(followup())
            self.watchers.add(watcher)
            watcher.add_done_callback(self.watchers.discard)
        return {
            "status": "processing",
            "reply": "I'm checking that with the hotel. I'll let you know as soon as I have the result.",
            "action_confirmed": False,
        }

    async def close(self):
        self.closed = True
        for task in [*self.tasks.values(), *self.watchers]:
            task.cancel()
        await asyncio.gather(
            *self.tasks.values(), *self.watchers, return_exceptions=True
        )
        self.tasks.clear()
        self.followups.clear()
        self.watchers.clear()
