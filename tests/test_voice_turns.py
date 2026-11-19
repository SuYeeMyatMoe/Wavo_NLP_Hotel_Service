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
        assert (await turns.run("one", "request")) == {"status": "no_reply"}
        ready.set()
        await asyncio.gather(*turns.watchers)
        assert processed == ["one"] and spoken == [{"reply": "Verified hotel guidance"}]
        assert (await turns.run("one", "request")) == {"status": "no_reply"}
        assert len(spoken) == 1
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
        for _ in range(2):
            assert (await turns.run("ok", "request")) == {"status": "no_reply"}
        result = await turns.run("failure", "request")
        assert result["status"] == "unavailable" and not result["action_confirmed"]
        assert "private" not in str(result) and not spoken
        await turns.close()

    asyncio.run(scenario())


def test_concurrent_retries_have_only_one_speech_owner():
    async def scenario():
        processed = []

        async def process(key, text):
            processed.append(key)
            return {"reply": "Reception has your request"}

        async def notify(result):
            raise AssertionError("Fast result should not need a follow-up")

        turns = VoiceTurns(process, notify)
        results = await asyncio.gather(*(turns.run("one", "request") for _ in range(3)))
        assert sum("reply" in result for result in results) == 1
        assert results.count({"status": "no_reply"}) == 2
        assert processed == ["one"]
        await turns.close()

    asyncio.run(scenario())
