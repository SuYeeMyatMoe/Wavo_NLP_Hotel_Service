"""Keep tool retries and delayed realtime transcripts on the same user turn."""

from uuid import uuid4


class VoiceInput:
    def __init__(self):
        self.item = None
        self.key = str(uuid4())
        self.submitted = False

    def observe(self, item_id, text, final):
        # Gemini's final transcript arrives AFTER its reply/tool call. Resetting
        # at that point can suppress the next confirmation or replay this turn.
        if item_id != self.item:
            if self.item is not None:
                self.key = str(uuid4())
                self.submitted = False
            self.item = item_id
        if final and text.strip() and not self.submitted:
            self.submitted = True
            return self.key, text
        return None

    def tool_key(self):
        self.submitted = True
        return self.key
