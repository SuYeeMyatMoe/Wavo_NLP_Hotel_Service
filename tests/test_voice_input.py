from hotel.voice_input import VoiceInput


def test_final_transcript_does_not_reset_submitted_turn():
    inputs = VoiceInput()
    assert inputs.observe("first", "Toilet blocked", False) is None
    first = inputs.tool_key()
    assert inputs.observe("first", "Toilet blocked", True) is None
    assert inputs.tool_key() == first
    assert inputs.observe("second", "Yes", False) is None
    assert inputs.tool_key() != first
    assert inputs.observe("second", "Yes", True) is None


def test_confirmation_without_tool_is_forwarded_once():
    inputs = VoiceInput()
    inputs.observe("first", "Toilet blocked", False)
    first = inputs.tool_key()
    inputs.observe("first", "Toilet blocked", True)
    inputs.observe("second", "Yes", False)
    key, text = inputs.observe("second", "Yes, send maintenance.", True)
    assert key != first and text == "Yes, send maintenance."
    assert inputs.observe("second", text, True) is None
    assert inputs.tool_key() == key  # A late model tool call is deduplicated.


def test_tool_preceding_transcript_is_not_replayed():
    inputs = VoiceInput()
    first = inputs.tool_key()
    assert inputs.observe("first", "Toilet blocked", True) is None
    assert inputs.tool_key() == first


def test_no_consent_inferred_from_empty_or_negative_transcript():
    inputs = VoiceInput()
    assert inputs.observe("empty", "", True) is None
    _, text = inputs.observe("next", "No, do not send anyone.", True)
    assert text == "No, do not send anyone."
