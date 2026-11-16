"""Day Countdown: how many days until a date somebody names.

Pippa pulls the date out of the message ("how many sleeps until Christmas?"
gives "Christmas") and hands it over as `call.inputs["date"]`. This file turns
that text into a calendar date, counts the days from the person's today, and
returns the numbers. Pippa writes the sentence around them.

Nothing here touches the network or keeps anything between calls: every answer
is worked out from the text and `call.context.now`.

What the date can look like (`_parse` handles each in turn):

    today, tomorrow
    Christmas, Halloween, Easter 2027       holidays with one date everywhere
    Friday, next Friday, this Friday        the coming weekday
    2027-01-01                              year first, all numbers
    25/12/2026, 12/25/2026, 25.12           numbers, year last or left out
    25 December, December 25th 2027         words, year optional
    the 25th                                the next 25th of a month

Anything else is refused with a sentence saying what to type instead, rather
than guessed: a wrong date said confidently is worse than no answer.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from pippa_agentapp_sdk import (
    AgentAppError,
    Call,
    Manifest,
    Result,
    load_manifest_file,
    validate_manifest,
)

MANIFEST_PATH = Path(__file__).with_name("manifest.yaml")

# English names, written out rather than taken from `calendar` or
# `strftime("%A")`, which follow the server's language settings.
MONTH_NAMES = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)
WEEKDAY_NAMES = (
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
)

#: "december" and "dec" -> 12. No month abbreviation is also a weekday one.
MONTHS = {name.lower(): number for number, name in enumerate(MONTH_NAMES, start=1)}
MONTHS.update({name[:3].lower(): number for number, name in enumerate(MONTH_NAMES, start=1)})
MONTHS["sept"] = 9

#: "friday" and "fri" -> 4, counting Monday as 0 like `date.weekday()`.
WEEKDAYS = {name.lower(): number for number, name in enumerate(WEEKDAY_NAMES)}
WEEKDAYS.update({name[:3].lower(): number for number, name in enumerate(WEEKDAY_NAMES)})
WEEKDAYS.update({"tues": 1, "weds": 2, "thur": 3, "thurs": 3})

#: Holidays on the same date in every country that keeps them. Ones that move
#: from country to country (Mother's Day, Thanksgiving) are left out on
#: purpose: a confident wrong date is worse than asking for the date.
FIXED_HOLIDAYS = {
    "christmas": (12, 25),
    "christmas day": (12, 25),
    "xmas": (12, 25),
    "christmas eve": (12, 24),
    "boxing day": (12, 26),
    "new year": (1, 1),
    "new years": (1, 1),
    "new years day": (1, 1),
    "new years eve": (12, 31),
    "halloween": (10, 31),
    "valentines": (2, 14),
    "valentines day": (2, 14),
}
EASTER = {"easter", "easter day", "easter sunday"}

#: Words people put round a date that carry no date of their own.
FILLER = {"the", "of", "on", "until", "till", "til", "to"}

#: What to suggest whenever a date cannot be read.
EXAMPLES = "something like 25 December or 2027-01-01"


class CannotReadDate(AgentAppError):
    """The message did not contain a date this app can work with."""

    # The default sentence a user may be shown. `_cannot` below replaces it
    # with one that names what was wrong, which tells them what to retype.
    user_message = "I could not work out which date you meant."
    retryable = False


def _cannot(user_message: str, detail: str) -> CannotReadDate:
    """A CannotReadDate with its own sentence for the user.

    `detail` goes to the logs only; `user_message` is what a person may see.
    """
    error = CannotReadDate(detail)
    error.user_message = user_message
    return error


class App:
    """Count the days until a date, and say which weekday it falls on."""

    def __init__(self) -> None:
        # Validated at construction, so an app whose manifest is wrong fails
        # immediately and loudly rather than on some later call.
        self._manifest = validate_manifest(load_manifest_file(MANIFEST_PATH))

    @property
    def manifest(self) -> Manifest:
        return self._manifest

    def handle(self, call: Call) -> Result:
        if call.outcome_id != "days.until":
            raise AgentAppError(f"this app cannot do {call.outcome_id!r}")

        # A missing or unreadable date is the only thing this app refuses for,
        # which is right whether Pippa chose the app or the person picked it
        # with @. So it never needs to read `call.context.explicit`.
        text = (call.inputs.get("date") or "").strip()
        if not text:
            raise _cannot(
                f"Which date should I count down to? Try {EXAMPLES}.",
                "no date in the message",
            )

        today = self._today(call)
        target = self._parse(text, today)
        difference = (target - today).days

        return Result(
            data={
                "days": abs(difference),
                "target_date": target.isoformat(),
                "weekday": WEEKDAY_NAMES[target.weekday()],
                "already_passed": difference < 0,
            },
            # One plain sentence Pippa may use when she writes her reply.
            narrative=self._sentence(target, difference),
        )

    @staticmethod
    def _today(call: Call) -> date:
        """The person's today, not the server's.

        A server in UTC and a person in Auckland disagree about the date for
        half of every day, and "how many days until" is exactly the question
        that notices. `call.context.now` rather than `datetime.now()`, so the
        tests can say what "now" is.
        """
        # No try/except round ZoneInfo: the manifest declares this input as
        # `type: timezone`, so the platform has already refused anything that
        # is not a real time zone before this code runs.
        zone = call.inputs.get("timezone")
        moment: datetime = call.context.now
        if zone:
            moment = moment.astimezone(ZoneInfo(zone))
        return moment.date()

    @staticmethod
    def _parse(text: str, today: date) -> date:
        """Turn what the person wrote into a date, or refuse to guess."""
        words = _normalise(text)
        shown = text if len(text) <= 60 else text[:57] + "..."
        unreadable = _cannot(
            f'I could not work out which date "{shown}" is. Try {EXAMPLES}.',
            f"could not parse {text!r} as a date",
        )
        if not words:
            raise unreadable

        if words == "today":
            return today
        if words == "tomorrow":
            return today + timedelta(days=1)

        # A holiday, perhaps with a year: "christmas", "next easter", "easter 2027".
        match = re.fullmatch(r"(?:next |this )?(.+?)(?: (\d{4}))?", words)
        name, year = match.group(1), _number(match.group(2))
        if name in FIXED_HOLIDAYS:
            month, day = FIXED_HOLIDAYS[name]
            return _next_date(today, day, month, year)
        if name in EASTER:
            if year is not None:
                return _easter(year)
            this_year = _easter(today.year)
            return this_year if this_year >= today else _easter(today.year + 1)

        # A weekday: "friday" and "next friday" mean the coming one, never
        # today; "this friday" said on a Friday means today.
        match = re.fullmatch(r"(?:(this|next|coming) )?([a-z]+)", words)
        if match and match.group(2) in WEEKDAYS:
            ahead = (WEEKDAYS[match.group(2)] - today.weekday()) % 7
            if ahead == 0 and match.group(1) != "this":
                ahead = 7
            return today + timedelta(days=ahead)

        # Year first, all numbers: 2027-01-01 or 2027/1/1. A time after it, as
        # in 2027-01-01T09:00, is ignored.
        match = re.fullmatch(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?:[t ].*)?", words)
        if match:
            year, month, day = (int(group) for group in match.groups())
            return _next_date(today, day, month, year)

        # Numbers with the year last or left out: 25/12/2026, 12/25/2026, 25.12.
        # Read day-first or month-first, whichever makes a real date. When
        # both do (03/04/2027), ask rather than guess.
        match = re.fullmatch(r"(\d{1,2})[-/.](\d{1,2})(?:[-/.](\d{4}))?", words)
        if match:
            first, second = int(match.group(1)), int(match.group(2))
            year = _number(match.group(3))
            day_first = _exists(first, second, year)
            month_first = _exists(second, first, year)
            if day_first and month_first and first != second:
                raise _cannot(
                    f'"{shown}" could mean {first} {MONTH_NAMES[second - 1]} or '
                    f"{second} {MONTH_NAMES[first - 1]}. Please write the month "
                    "as a word.",
                    f"ambiguous numeric date {text!r}",
                )
            if day_first:
                return _next_date(today, first, second, year)
            if month_first:
                return _next_date(today, second, first, year)
            raise unreadable

        # Words: "25 december", "december 25 2027", "friday 25 december".
        tokens = words.split()
        if len(tokens) > 1 and tokens[0] in WEEKDAYS:
            # A weekday in front of a full date is decoration: the date decides.
            tokens = tokens[1:]
        rest = " ".join(tokens)

        match = re.fullmatch(r"(\d{1,2}) ([a-z]+)(?: (\d{4}))?", rest)
        if match and match.group(2) in MONTHS:
            day, month = int(match.group(1)), MONTHS[match.group(2)]
            return _next_date(today, day, month, _number(match.group(3)))

        match = re.fullmatch(r"([a-z]+) (\d{1,2})(?: (\d{4}))?", rest)
        if match and match.group(1) in MONTHS:
            month, day = MONTHS[match.group(1)], int(match.group(2))
            return _next_date(today, day, month, _number(match.group(3)))

        # A day of the month on its own: "the 25th" has become "25" by now.
        if re.fullmatch(r"\d{1,2}", rest):
            return _next_day_of_month(today, int(rest))

        raise unreadable

    @staticmethod
    def _sentence(target: date, difference: int) -> str:
        # Built by hand rather than with `%-d`, which raises on Windows.
        pretty = (
            f"{WEEKDAY_NAMES[target.weekday()]} {target.day} "
            f"{MONTH_NAMES[target.month - 1]} {target.year}"
        )
        if difference == 0:
            return f"That is today, {pretty}."
        if difference == 1:
            return f"{pretty} is tomorrow."
        if difference == -1:
            return f"{pretty} was yesterday."
        if difference < 0:
            return f"{pretty} was {-difference} days ago."
        return f"There are {difference} days until {pretty}."


# ── Helpers ──────────────────────────────────────────────────────────────────


def _normalise(text: str) -> str:
    """Lower case, without the punctuation and filler words people add.

    "New Year's Eve" -> "new years eve", "the 25th of Dec." -> "25 dec".
    """
    words = re.sub(r"['’]", "", text.lower())
    words = re.sub(r"(?<=[a-z])\.", " ", words)          # "dec." -> "dec"
    words = re.sub(r"[,?!;]", " ", words)
    words = re.sub(r"\b(\d{1,2})(?:st|nd|rd|th)\b", r"\1", words)  # 25th -> 25
    kept = [word for word in words.split() if word not in FILLER]
    return " ".join(kept).strip(".")


def _number(digits: str | None) -> int | None:
    return int(digits) if digits else None


def _exists(day: int, month: int, year: int | None = None) -> bool:
    """Whether this day and month make a real date (in `year`, if given).

    With no year, 29 February counts: it exists, just not every year.
    """
    try:
        date(2000 if year is None else year, month, day)  # 2000 was a leap year
    except ValueError:
        return False
    return True


def _next_date(today: date, day: int, month: int, year: int | None = None) -> date:
    """This day and month in `year`; with no year, the next one from today on."""
    if not 1 <= month <= 12:
        raise _cannot(
            f"There is no month number {month}. Try {EXAMPLES}.",
            f"month {month} out of range",
        )
    named = f"{day} {MONTH_NAMES[month - 1]}"
    if year is not None:
        if not _exists(day, month, year):
            raise _cannot(f"There is no {named} {year}.", f"no such date {year}-{month}-{day}")
        return date(year, month, day)
    if not _exists(day, month):
        raise _cannot(f"There is no {named}.", f"no such date --{month}-{day}")
    # This year's, or the first one still to come. Up to eight years ahead,
    # because the next 29 February can be that far off (2100 is not a leap year).
    for candidate_year in range(today.year, today.year + 9):
        if _exists(day, month, candidate_year):
            candidate = date(candidate_year, month, day)
            if candidate >= today:
                return candidate
    raise _cannot(f"There is no {named} coming up.", f"no future {named}")


def _next_day_of_month(today: date, day: int) -> date:
    """The next date with this day number, from today on. "The 31st" asked in
    November skips November, which has no 31st, and means 31 December."""
    if not 1 <= day <= 31:
        raise _cannot(f"No month has a day {day}. Try {EXAMPLES}.", f"day {day} out of range")
    year, month = today.year, today.month
    for _ in range(13):
        if _exists(day, month, year) and date(year, month, day) >= today:
            return date(year, month, day)
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    raise _cannot(f"There is no day {day} coming up.", f"no future day {day}")


def _easter(year: int) -> date:
    """Western Easter Sunday in `year`.

    The "anonymous Gregorian algorithm", a long-published recipe that needs
    nothing but arithmetic. The one-letter names follow the recipe, so it can
    be checked against it line by line.
    """
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7  # noqa: E741 - the recipe's own name
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)
