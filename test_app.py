"""Tests for Day Countdown. The build runs them on every push.

A repository whose tests fail does not deploy, which is the fastest feedback
there is: the alternative is finding out from a user that the app answers
wrongly.

Every call goes through `LocalRunner`, the same code the live runtime uses to
call the app, so a `Result` that breaks the manifest fails here exactly as it
would after deploying. That is the reason to test through the runner rather
than calling `App().handle(...)` directly.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from pippa_agentapp_sdk import LocalRunner, OutputShapeViolation

from app import App, CannotReadDate

# A fixed "now", so a test that passes today still passes next March.
# Thursday 22 October 2026, 21:00 UTC. The hour is on purpose: it is already
# Friday the 23rd in New Zealand, which is what makes the time zone test mean
# anything.
NOW = datetime(2026, 10, 22, 21, 0, tzinfo=timezone.utc)
TODAY = date(2026, 10, 22)


def call(inputs: dict, outcome: str = "days.until", *, explicit: bool = False):
    """Run one outcome the way the runtime does, and return the Result.

    `granted_secrets` is required even though this app never has any: an
    empty dict is how you say "none". `explicit=True` calls the app the way
    Pippa does when the person picked it with @ instead of Pippa choosing it.
    """
    return LocalRunner(App()).call(
        outcome, inputs, granted_secrets={}, now=NOW, request_id="test-1",
        explicit=explicit,
    ).result


def target(text: str) -> str:
    """The date the app counted to, for the date as a person wrote it."""
    return call({"date": text}).data["target_date"]


def refusal(text: str) -> str:
    """The sentence a person is shown when the app cannot read the date."""
    with pytest.raises(CannotReadDate) as failure:
        call({"date": text})
    return failure.value.user_message


# ── The contract ─────────────────────────────────────────────────────────────


def test_the_manifest_is_valid():
    """`App()` validates manifest.yaml, so this fails first if it is malformed."""
    app = App()
    assert app.manifest.app_id.startswith("hack.")
    assert [o.id for o in app.manifest.outcomes] == ["days.until"]


def test_the_runner_enforces_the_manifest(monkeypatch):
    """Returning a field the manifest does not declare is refused."""
    from pippa_agentapp_sdk import Result

    monkeypatch.setattr(
        App, "handle", lambda self, c: Result(data={"surprise": "hello"})
    )
    with pytest.raises(OutputShapeViolation):
        call({"date": "2026-12-25"})


# ── Counting ─────────────────────────────────────────────────────────────────


def test_it_counts_the_days():
    result = call({"date": "2026-12-25"})
    assert result.data == {
        "days": 64,
        "target_date": "2026-12-25",
        "weekday": "Friday",
        "already_passed": False,
    }
    assert result.narrative == "There are 64 days until Friday 25 December 2026."


def test_a_date_that_has_passed_counts_days_ago():
    result = call({"date": "1 January 2020"})
    assert result.data["already_passed"] is True
    assert result.data["days"] == (TODAY - date(2020, 1, 1)).days
    assert result.narrative.endswith("days ago.")


def test_today_and_tomorrow():
    assert call({"date": "today"}).data["days"] == 0
    tomorrow = call({"date": "tomorrow"})
    assert tomorrow.data["target_date"] == "2026-10-23"
    assert tomorrow.narrative == "Friday 23 October 2026 is tomorrow."


def test_the_users_timezone_decides_what_today_is():
    """21:00 UTC on the 22nd is already the 23rd in Auckland.

    The bug every date app has, which only shows up for people in some parts
    of the world and is invisible if you only ever test from one place.
    """
    here = call({"date": "2026-10-23"}).data["days"]
    there = call({"date": "2026-10-23", "timezone": "Pacific/Auckland"}).data["days"]
    assert here == 1    # still the 22nd in UTC
    assert there == 0   # already the 23rd in Auckland


def test_a_made_up_timezone_never_reaches_the_app():
    """`type: timezone` in the manifest means the platform checks it first."""
    from pippa_agentapp_sdk import InputShapeViolation

    with pytest.raises(InputShapeViolation):
        call({"date": "2026-12-25", "timezone": "Mars/Olympus"})


# ── Ways of writing a date ───────────────────────────────────────────────────


@pytest.mark.parametrize("text, expected", [
    ("2026-12-25", "2026-12-25"),
    ("2027/1/1", "2027-01-01"),
    ("2026-12-25T09:00:00", "2026-12-25"),
    ("25 December", "2026-12-25"),
    ("December 25", "2026-12-25"),
    ("25th of December", "2026-12-25"),
    ("Dec. 25th, 2027", "2027-12-25"),
    ("Friday 25 December 2026", "2026-12-25"),
    ("25/12/2026", "2026-12-25"),     # only day-first makes a real date
    ("12/25/2026", "2026-12-25"),     # only month-first makes a real date
    ("25.12", "2026-12-25"),
])
def test_dates_written_in_different_ways(text, expected):
    assert target(text) == expected


def test_a_date_without_a_year_that_has_gone_means_next_year():
    """`1 January` asked in October means the January that is coming."""
    result = call({"date": "1 January"})
    assert result.data["target_date"] == "2027-01-01"
    assert result.data["already_passed"] is False


def test_29_february_without_a_year_means_the_next_leap_day():
    assert target("29 February") == "2028-02-29"


@pytest.mark.parametrize("text, expected", [
    ("Christmas", "2026-12-25"),
    ("christmas eve", "2026-12-24"),
    ("Christmas Day 2027", "2027-12-25"),
    ("New Year's Eve", "2026-12-31"),
    ("new year", "2027-01-01"),
    ("Halloween", "2026-10-31"),
    ("Valentine's Day", "2027-02-14"),
    ("Easter", "2027-03-28"),         # Easter 2026 (5 April) has passed
    ("Easter 2028", "2028-04-16"),
])
def test_holidays(text, expected):
    assert target(text) == expected


@pytest.mark.parametrize("text, expected", [
    ("Friday", "2026-10-23"),
    ("next Friday", "2026-10-23"),
    ("Thursday", "2026-10-29"),       # it is Thursday: the coming one, not today
    ("this Thursday", "2026-10-22"),  # ...unless they say "this"
    ("mon", "2026-10-26"),
])
def test_weekdays(text, expected):
    assert target(text) == expected


@pytest.mark.parametrize("text, expected", [
    ("the 25th", "2026-10-25"),
    ("the 1st", "2026-11-01"),
    ("the 22nd", "2026-10-22"),
])
def test_a_day_of_the_month_on_its_own(text, expected):
    assert target(text) == expected


# ── Refusing rather than guessing ────────────────────────────────────────────


def test_no_date_asks_for_one():
    assert refusal("") == (
        "Which date should I count down to? "
        "Try something like 25 December or 2027-01-01."
    )


def test_nonsense_is_refused_and_named():
    """The sentence names what they typed, so they know what to retype."""
    message = refusal("a week on Thursday-ish")
    assert '"a week on Thursday-ish"' in message
    assert "25 December" in message


def test_a_date_that_does_not_exist_is_refused():
    assert refusal("31 February 2027") == "There is no 31 February 2027."
    assert refusal("29 February 2027") == "There is no 29 February 2027."
    assert refusal("31 April") == "There is no 31 April."


def test_an_ambiguous_numeric_date_is_refused_not_guessed():
    """03/04/2027 is 3 April in Britain and 4 March in the United States."""
    message = refusal("03/04/2027")
    assert "3 April" in message and "4 March" in message
    assert "month as a word" in message


def test_the_same_day_and_month_is_not_ambiguous():
    assert target("05/05/2027") == "2027-05-05"


# ── Picked by name with @ ────────────────────────────────────────────────────


def test_picked_by_name_it_answers_and_refuses_as_usual():
    """`@Day Countdown ...` in the chat: the person picked this app themselves.

    It answers exactly as it would if Pippa had chosen it, and refuses only
    for a missing or unreadable date. It never reads `call.context.explicit`,
    because it never needs to.
    """
    picked = call({"date": "2026-12-25"}, explicit=True)
    assert picked.data == call({"date": "2026-12-25"}).data

    with pytest.raises(CannotReadDate) as failure:
        call({"date": ""}, explicit=True)
    assert failure.value.user_message.startswith("Which date should I count down to?")
