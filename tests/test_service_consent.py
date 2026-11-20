import pytest
from hotel.service_consent import service_consent


@pytest.mark.parametrize(
    "text",
    [
        "Yes",
        "OK",
        "O.K.",
        "O K",
        "Uh... O.K.",
        "That's okay.",
        "It is OK.",
        "Yup.",
        "Yep, please.",
        "Oh, yes.",
        "Sure",
        "Go ahead",
        '"Yes, send maintenance."',
        "Please send maintenance.",
        "Can you send the maintenance team?",
        "You can send them.",
        "Yes, send maintenance. The AC still doesn't work.",
        "Yes, the AC is not cooling.",
    ],
)
def test_explicit_agreement_to_pending_offer(text):
    assert service_consent(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "No",
        "O.K., don't send anyone",
        "O K, but not yet",
        "Not now",
        "Yes, but not yet",
        "Maybe",
        "Yes, wait",
        "Yes, don't send maintenance",
        "Please do not send anyone",
        "Yes, I don't want anyone to enter",
        "Yes, no maintenance visit",
        "Yes, but later",
        "Cancel that",
        "Don't send them",
        "Yes, I do not consent to a visit",
        "Yes, no need to send anyone",
    ],
)
def test_refusal_or_deferral_does_not_dispatch(text):
    assert service_consent(text) is False


@pytest.mark.parametrize(
    "text",
    [
        "The AC is broken",
        "Did you send maintenance?",
        "How much will it cost?",
        "I said yes yesterday",
        "",
        "O.K.?",
        "O.K., if it is free",
        "I do not know",
        "Yes, if it is free",
        "Yes, but how much does it cost?",
    ],
)
def test_unclear_replies_require_clarification(text):
    assert service_consent(text) is None
