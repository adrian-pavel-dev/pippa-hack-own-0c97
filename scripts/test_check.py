"""Tests for the warnings in scripts/check.py.

NOT a test of your app, and not a file you need to touch. Your app's tests go
in `test_app.py` at the top level; this one covers the checker that ships with
the template, which is why it lives next to it. `pytest` finds it because
`testpaths` in pytest.ini is the whole repository.

It exists because the things these warnings guard are public. Your author name
is shown to everybody, and an email address in a file or on a commit can be
read by anybody who can read the repository. A warning that has quietly
stopped firing looks exactly like a warning with nothing to report.
"""

from __future__ import annotations

import sys
from pathlib import Path

# `scripts/` is not a package, and importing by path keeps this working
# whichever directory pytest is started from.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import check  # noqa: E402

# Every address written out in this file is at a domain reserved for examples
# (RFC 2606), so it can never be anybody's. An address the checks must catch
# has to be at some other domain, so those are put together while the test
# runs and never appear in the file: written out, they would be exactly what
# the build refuses. `.local` is a machine's name on its own network, which is
# what git puts on a commit when nobody has set an address.
AT = "@"


def personal(local: str = "pat") -> str:
    return f"{local}{AT}laptop.local"


def manifest(**extra) -> dict:
    """A manifest mapping with only the parts this file cares about."""
    return {"manifest_version": 1, "app": {"id": "hack.tide_times"}, **extra}


# ── app_author_name ──────────────────────────────────────────────────────────
#
# The sentences are Pippa's own, word for word: the warning has to read like
# the refusal it saves you from.

def test_a_good_pseudonym_has_no_problem():
    for name in ("Tidewatcher", "tide.watcher", "Night_Owl-42", "x7 builds", "Zoë Quill"):
        assert check.author_name_problem(name) is None, name


def test_letters_of_any_alphabet_are_letters():
    """Including the marks some alphabets write letters with: `str.isalnum`
    alone refuses most names written in Devanagari."""
    for name in ("Ночная сова", "रात का उल्लू", "夜のフクロウ"):
        assert check.author_name_problem(name) is None, name


def test_spaces_are_trimmed_and_collapsed_before_counting():
    assert check.normalise_author_name("  Tide   watcher ") == "Tide watcher"
    assert check.author_name_problem("  ab  ") == "app_author_name must be 3 to 30 characters."
    assert check.author_name_problem("a" * 30) is None
    assert check.author_name_problem("a" * 31) == "app_author_name must be 3 to 30 characters."


def test_the_shipped_placeholder_is_unset_and_publishes_nothing():
    """`app_author_name: ""` is what every repository starts with. The build
    skips such a push, so the warning says that rather than quoting a rule."""
    for value in ("", "   ", None):
        assert check.author_name_unset(manifest(app_author_name=value)), value
    assert not check.author_name_unset(manifest(app_author_name="Tidewatcher"))
    assert not check.author_name_unset(manifest())
    assert check.author_name_problem("") == "app_author_name must be 3 to 30 characters."


def test_a_value_that_is_not_text_is_a_problem():
    """`app_author_name: 1337` is a number to YAML."""
    assert check.author_name_problem(1337) == "app_author_name must be text: put the name in quotes."


def test_only_letters_numbers_spaces_dots_hyphens_and_underscores():
    sentence = (
        "app_author_name can only use letters, numbers, spaces, dots, hyphens "
        "and underscores."
    )
    for name in ("Tide!", "Tide/Times", "Tide (beta)", "Tide's", "Tide²"):
        assert check.author_name_problem(name) == sentence, name


def test_it_starts_with_a_letter_or_a_number():
    for name in ("-Tide", ".Tide", "_Tide"):
        assert check.author_name_problem(name) == (
            "app_author_name must start with a letter or a number."
        ), name


def test_an_email_address_or_a_web_address_is_a_problem():
    """Said first, so an address is told it is an address, and not that `@` is
    an unusual character or that it is too long."""
    sentence = "app_author_name must not be an email address or a web address."
    for name in ("sam@college.example", "https://tide.example", "www.tide.example",
                 "a@", "sam@pippa.example"):
        assert check.author_name_problem(name) == sentence, name


def test_it_cannot_claim_to_be_pippa_in_any_capitals_or_any_width():
    sentence = 'app_author_name can\'t contain "pippa", "official" or "verified".'
    for name in ("Pippa Labs", "The OFFICIAL Tides", "verifiedtides", "ｐｉｐｐａ fan"):
        assert check.author_name_problem(name) == sentence, name


def test_a_legacy_publisher_is_read_from_inside_app():
    data = manifest()
    data["app"]["publisher"] = "  Tidewatcher "
    assert check.legacy_publisher(data) == "Tidewatcher"
    assert check.legacy_publisher(manifest()) == ""
    assert check.legacy_publisher(None) == ""


# ── owner_email and other addresses in the manifest ──────────────────────────

def test_owner_email_is_found_at_the_top_and_inside_app():
    assert check.owner_email_present(manifest(owner_email="you@example.com"))
    data = manifest()
    data["app"]["owner_email"] = "you@example.com"
    assert check.owner_email_present(data)
    assert not check.owner_email_present(manifest())
    assert not check.owner_email_present(None)


def test_an_empty_owner_email_names_nobody():
    """As for Pippa: an empty line leaks nothing, so it is not a warning."""
    data = manifest(owner_email="")
    data["app"]["owner_email"] = None
    assert not check.owner_email_present(data)


def test_an_address_anywhere_in_the_manifest_is_found_with_its_path():
    """Pippa refuses an address in any string of the manifest, at any depth,
    with no allowed domains: even an example address is shown to people."""
    data = manifest(
        outcomes=[{"id": "tide.times", "example_phrases": ["tides", "mail sam@college.example"]}],
    )
    data["app"]["summary"] = "Tides. Questions to sam@college.example."
    assert check.manifest_address_paths(data) == [
        "app.summary",
        "outcomes[0].example_phrases[1]",
    ]


def test_a_key_that_is_an_address_is_named_by_where_it_is():
    """So that the place can be named without repeating the address."""
    data = manifest(contact={"sam@college.example": "yes"})
    data["sam@college.example"] = 1
    assert check.manifest_address_paths(data) == ["contact", "the top level"]


def test_owner_email_has_its_own_warning_and_is_not_counted_twice():
    data = manifest(owner_email="you@example.com")
    data["app"]["owner_email"] = "you@example.com"
    assert check.manifest_address_paths(data) == []


def test_a_manifest_with_no_address_is_clean():
    data = manifest(app_author_name="Tidewatcher")
    data["app"].update(name="Tide Times", summary="When the next high tide is.")
    assert check.manifest_address_paths(data) == []


# ── Addresses in files ───────────────────────────────────────────────────────

def test_an_address_in_text_is_found_with_its_line():
    text = f"line one\nwrite to {personal()} today\n"
    assert check.addresses_in(text) == [(2, personal())]


def test_example_and_no_reply_addresses_are_allowed():
    for address in (
        "you@example.com", "sam@mail.example.org", "SAM@EXAMPLE.NET",
        "sam@college.example", "sam@build.test", "sam@nowhere.invalid",
        "sam@printer.localhost", "12345+tidewatcher@users.noreply.github.com",
    ):
        assert check.is_allowed_address(address), address
        assert check.addresses_in(f"x {address} y") == [], address


def test_things_that_only_look_like_addresses_are_not_found():
    """Real lines from this template. The build scans every file with the same
    pattern, so a false match here would stop every repository publishing."""
    lines = [
        '  import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs";',
        '<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500'
        ';9..144,700&family=Public+Sans:wght@400;600&display=swap">',
        '    example = f"@{manifest.name} {first}".rstrip()',
        "@pytest.mark.network",
        "Start the message with `@` and pick the app.",
        'gh api user --jq \'"\\(.id)+\\(.login)@users.noreply.github.com"\'',
        'git config user.email "<id>+<login>@users.noreply.github.com"',
    ]
    for line in lines:
        assert check.addresses_in(line) == [], line


def test_a_file_name_that_looks_like_an_address_is_not_one():
    """A picture drawn at twice the size is `logo@2x.png`. The build skips
    these, so a warning here, or a refusal from the hook, would stop a line
    that publishes perfectly well."""
    lines = [
        '<img src="img/logo@2x.png" srcset="img/logo@3X.WEBP 3x">',
        '<script src="vendor/lib@1.2.3.min.js"></script>',
        "background: url(icons/arrow@2x.svg);",
        "data/tides@2026.json and notes@v2.txt",
    ]
    for line in lines:
        assert check.addresses_in(line) == [], line


def test_only_the_last_part_makes_a_file_name():
    """`.png` must END the match: an address whose domain merely contains
    one of the endings is still an address."""
    assert check.addresses_in(f"x {personal()} y") == [(1, personal())]
    assert check.addresses_in(f"pat{AT}png.laptop.local") == [(1, f"pat{AT}png.laptop.local")]
    assert check.addresses_in(f"pat{AT}laptop.pngs") == [(1, f"pat{AT}laptop.pngs")]
    assert check.addresses_in(f'<img src="logo{AT}2x.png"> {personal()}') == [(1, personal())]


def test_an_address_is_never_shown_whole():
    assert check.mask(personal("sam")) == "s***@laptop.local"


def test_the_file_scan_skips_binary_and_large_files(tmp_path):
    (tmp_path / "notes.md").write_text(f"a\nb {personal()}\n", encoding="utf-8")
    (tmp_path / "logo.png").write_bytes(b"\x89PNG\0\0" + personal().encode())
    (tmp_path / "big.json").write_text(
        personal() + " " + "x" * check.SCAN_LIMIT_BYTES, encoding="utf-8",
    )
    found = check.scan_files(tmp_path, ["notes.md", "logo.png", "big.json", "gone.txt"])
    assert found == [("notes.md", 2, "p***@laptop.local")]


# ── The address on the commit ────────────────────────────────────────────────

def test_the_address_is_read_out_of_a_git_identity():
    ident = f"Tidewatcher <{personal()}> 1700000000 +0000"
    assert check.identity_email(ident) == personal()
    assert check.identity_email("") == ""


def test_a_no_reply_commit_address_is_fine():
    noreply = "12345+tidewatcher@users.noreply.github.com"
    assert check.identity_problems({"author": noreply, "committer": noreply}) == []
    assert check.identity_problems({"author": "", "committer": ""}) == []


def test_githubs_own_address_on_an_edit_made_on_the_website_is_fine():
    """An edit made on github.com is committed by GitHub itself, from its own
    `noreply` address. The build accepts it, and nobody can change it, so a
    warning about it would ask for a fix that cannot be made. Put together
    here: it is not at an allowed domain, so written out in this file it would
    be refused by the build's file scan."""
    web = f"noreply{AT}github.com"
    noreply = "12345+tidewatcher@users.noreply.github.com"
    assert check.identity_problems({"author": noreply, "committer": web}) == []
    assert check.identity_problems({"author": noreply, "committer": web.upper()}) == []
    assert check.identity_problems({"author": f"sam{AT}github.com", "committer": web}) == [
        "the commit's author email is s***@github.com, not a GitHub no-reply address"
    ]


def test_any_other_commit_address_is_a_problem_said_once_and_masked():
    problems = check.identity_problems({"author": personal(), "committer": personal()})
    assert problems == [
        "the commit's author email is p***@laptop.local, not a GitHub no-reply address"
    ]
    assert personal() not in problems[0]
