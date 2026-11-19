import json

import pytest

from hotel.case_notes import minimal
from hotel.intelligence import inspect
from hotel.issue_labels import MISSING, problem_label


@pytest.mark.parametrize(
    "text,expected",
    [
        ("The AC is not cooling. My child is asleep.", "AC not cooling"),
        ("The AC works, but the shower leaks.", "Shower leaking"),
        ("The shower is no longer leaking.", "Plumbing issue (reported resolved)"),
        ("There is no gas leak.", "Safety concern (denied)"),
        ("I'm hungry. Can you order a breakfast for me?", "Breakfast request"),
        ("Can you bring fresh towels?", "Fresh towels requested"),
        ("How do I connect to Wi-Fi?", "Wi-Fi connection help"),
    ],
)
def test_private_summary_keeps_problem_not_transcript(text, expected):
    analysis = inspect(text + " My private code is peach-mountain.")
    saved = minimal(analysis)
    assert problem_label(saved["extraction"]) == expected
    assert "peach-mountain" not in json.dumps(saved)
    assert "evidence" not in json.dumps(saved["issues"])
    assert minimal(saved) == saved


def test_historical_missing_details_are_not_invented():
    assert (
        problem_label({"topic": "General request", "issue": "General request"})
        == MISSING
    )
    assert (
        problem_label(
            {"service_label": "Private text injected here", "topic": "General request"}
        )
        == MISSING
    )
    assert (
        problem_label(
            {
                "topic": "Wi-Fi",
                "issue": "Wi-Fi: uncertain",
                "issues": [{"topic": "Wi-Fi", "state": "uncertain"}],
            }
        )
        == "Wi-Fi connection help — clarify"
    )
