import asyncio
from hotel.voice_turns import VoiceTurns


def test_slow_result_acknowledged_then_spoken_once_and_deduplicated():
    async def scenario():
        ready = asyncio.Event()
        processed, spoken = [], []

        async def process(key, text):
            processed.append(key)
            await ready.wait()
            return {"reply": "Verified hotel guidance"}

        async def notify(result):
            spoken.append(result)

        turns = VoiceTurns(process, notify, grace=0.001)
        assert (await turns.run("one", "request"))["status"] == "processing"
        assert not (await turns.run("one", "request"))["action_confirmed"]
        ready.set()
        await asyncio.gather(*turns.watchers)
        assert processed == ["one"] and spoken == [{"reply": "Verified hotel guidance"}]
        await turns.close()
        assert not turns.tasks and not turns.watchers

    asyncio.run(scenario())


def test_hangup_cancels_queued_processing_and_late_speech():
    async def scenario():
        processed, spoken = [], []

        async def process(key, text):
            processed.append(key)
            await asyncio.Event().wait()

        async def notify(result):
            spoken.append(result)

        turns = VoiceTurns(process, notify, grace=0.001)
        await turns.run("one", "request")
        await turns.run("two", "follow-up")
        await turns.close()
        assert processed == ["one"] and not spoken
        assert (await turns.run("three", "late"))["status"] == "ended"

    asyncio.run(scenario())


def test_fast_result_does_not_trigger_second_reply_and_error_is_honest():
    async def scenario():
        spoken = []

        async def process(key, text):
            if key == "failure":
                raise RuntimeError("private provider details")
            return {"reply": "Verified result"}

        async def notify(result):
            spoken.append(result)

        turns = VoiceTurns(process, notify)
        assert (await turns.run("ok", "request"))["reply"] == "Verified result"
        result = await turns.run("failure", "request")
        assert result["status"] == "unavailable" and not result["action_confirmed"]
        assert "private" not in str(result) and not spoken
        await turns.close()

    asyncio.run(scenario())
