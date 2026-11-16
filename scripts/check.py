"""Everything that stops a push from publishing, checked before you push.

NOT A BUILDER TASK. Builders do not install Python and do not open a terminal.
The build runs this file on every push, after it installs the Pippa SDK; it
does not run locally, because the SDK is not in this repository. Do not put it
back into the builder instructions.

It is worth reading if a build fails, because the message it prints is the one
in the Actions log, and it names the exact line to change.

**Scope.** Everything fatal here is fatal for one reason: it is the set of
things that make the publish step refuse. It deliberately says nothing about
whether your app will ever be *chosen* — that is `scripts/routing_check.py`,
which is advice rather than a gate, because a weak example phrase is a bad app
rather than an invalid one and blocking a push for it would help nobody.

**WARNINGS, and they are deliberately not gates.** Who owns your app is not in
this repository at all: Pippa Labs created the repository for your Pippa
account, and Pippa knows which repository a push came from. What IS in here is
public: `app_author_name`, the name shown with your app, and anything else you
commit. The rules for those — a valid author name, no `owner_email`, no email
address in any file or on any commit — are enforced by Pippa and by the build
itself, which refuse the push. This file is a copy that lives in your
repository and is never updated, so a gate here could go on refusing pushes
long after Pippa had changed its mind. It warns instead, early, so that a
refusal is never the first you hear of it. Each warning is printed twice,
because the test output in between is long enough to hide it.

It never prints an email address it finds, only its first letter and its
domain (`s***@college.example`): the build log is as readable as the
repository.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

# Windows consoles still default to a legacy code page on many machines, and
# an em dash or a tick in a message is then either mangled or raises
# UnicodeEncodeError mid-print. Forcing UTF-8 here is cheaper than policing
# every string, and `errors="replace"` means the worst case is one odd
# character rather than a traceback instead of the thing you were being told.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
REPO_PREFIX = "pippa-hack-"

# Colour only where it will render. On a plain Windows console, or when the
# output is piped into a file, the escape codes are shown literally and make
# the result harder to read rather than easier.
if sys.stdout.isatty() and os.environ.get("TERM") != "dumb":
    GREEN, RED, YELLOW, PLAIN = "\033[32m", "\033[31m", "\033[33m", "\033[0m"
else:
    GREEN = RED = YELLOW = PLAIN = ""


def ok(message: str) -> bool:
    # Flushed, because the test run below is a subprocess writing to the same
    # terminal. Without this, Python's buffering holds everything back and the
    # tests appear above the checks that ran before them.
    print(f"{GREEN}  OK{PLAIN}  {message}", flush=True)
    return True


def bad(message: str, fix: str = "") -> bool:
    print(f"{RED} FAIL{PLAIN} {message}", flush=True)
    if fix:
        print(f"       {YELLOW}{fix}{PLAIN}", flush=True)
    return False


#: Warnings, kept so they can be said twice. See `warn`.
warnings: list[str] = []


def warn(message: str, fix: str = "") -> None:
    """Something that will not stop the publish, but will cost you an hour.

    Deliberately NOT appended to `results`, so it cannot change the exit code:
    the build runs this file, and a warning that failed the build would refuse
    a push the publisher would have accepted.

    It is collected rather than only printed because of what comes after it —
    the test run writes several screens of its own output, and a warning seen
    only above that has not really been seen. `main` prints the list again
    immediately before the verdict.
    """
    warnings.append(message)
    print(f"{YELLOW} WARN{PLAIN} {message}", flush=True)
    for line in fix.splitlines():
        # rstrip, so a blank line between paragraphs is blank rather than
        # seven spaces — which some terminals show as a stray mark.
        print(f"       {line}".rstrip(), flush=True)


def git(*args: str) -> str:
    """One git command's output, or "" if git is missing or the command fails."""
    try:
        done = subprocess.run(
            ["git", *args], cwd=ROOT, capture_output=True, timeout=10,
        )
    except Exception:
        return ""
    if done.returncode != 0:
        return ""
    return done.stdout.decode("utf-8", errors="replace")


def repo_name() -> str | None:
    """This repository's name on GitHub.

    Taken from the git remote rather than the folder, because the folder can
    be renamed on your machine and the publisher only ever sees the remote.
    """
    url = git("remote", "get-url", "origin").strip()
    match = re.search(r"/([^/]+?)(?:\.git)?$", url)
    return match.group(1) if match else None


def expected_app_id(repo: str) -> str:
    return "hack." + repo[len(REPO_PREFIX):].replace("-", "_")


# ── The public author name ───────────────────────────────────────────────────
#
# The rules Pippa applies when it registers your app, applied the same way:
# the same order, and one sentence, for the first rule broken. The sentences
# are the ones Pippa refuses the push with, so a warning here reads exactly
# like the refusal it saves you from.

AUTHOR_NAME_KEY = "app_author_name"
AUTHOR_NAME_MIN, AUTHOR_NAME_MAX = 3, 30
#: Words an author name may not contain, in any capitals: each one makes an app
#: look as if Pippa itself vouches for it. The same rule as for `app.name`.
RESERVED_WORDS = ("pippa", "official", "verified")

AUTHOR_NAME_NOT_TEXT = "app_author_name must be text: put the name in quotes."
AUTHOR_NAME_LENGTH = "app_author_name must be 3 to 30 characters."
AUTHOR_NAME_CHARACTERS = (
    "app_author_name can only use letters, numbers, spaces, dots, hyphens and "
    "underscores."
)
AUTHOR_NAME_START = "app_author_name must start with a letter or a number."
AUTHOR_NAME_ADDRESS = "app_author_name must not be an email address or a web address."
AUTHOR_NAME_RESERVED = 'app_author_name can\'t contain "pippa", "official" or "verified".'
#: Pippa's warning for a manifest written before `app_author_name` existed.
ADD_AUTHOR_NAME = (
    "Add app_author_name to manifest.yaml: the public name shown with your "
    "app. Until then it shows `publisher`."
)


def normalise_author_name(value: str) -> str:
    """Trimmed, with every run of spaces inside collapsed to one."""
    return " ".join((value or "").split())


def _folded(value: str) -> str:
    # What the address and reserved-word rules compare: a full-width
    # "ｐｉｐｐａ" is still "pippa".
    return unicodedata.normalize("NFKC", normalise_author_name(value)).casefold()


def _allowed_in_name(character: str) -> bool:
    # A letter of any alphabet with the marks some alphabets need to spell a
    # name at all (`str.isalnum` alone refuses half a Hindi name), a decimal
    # digit, a space, `.`, `_` or `-`. Invisible characters are refused.
    category = unicodedata.category(character)
    return category[0] in ("L", "M") or category == "Nd" or character in " ._-"


def _starts_a_name(character: str) -> bool:
    category = unicodedata.category(character)
    return category[0] == "L" or category == "Nd"


def author_name_problem(value) -> str | None:
    """Why `value` is not an acceptable `app_author_name`, or None.

    The first rule it breaks, in the order that gives the most useful answer:
    "me@example.com" is told it is an address, not that `@` is an unusual
    character. No attempt at telling a real name from an invented one,
    because nothing can. That is why Claude asks for a pseudonym.
    """
    if not isinstance(value, str):
        return AUTHOR_NAME_NOT_TEXT
    name = normalise_author_name(value)
    folded = _folded(name)
    if "@" in folded or "://" in folded or "www." in folded:
        return AUTHOR_NAME_ADDRESS
    if any(word in folded for word in RESERVED_WORDS):
        return AUTHOR_NAME_RESERVED
    if not AUTHOR_NAME_MIN <= len(name) <= AUTHOR_NAME_MAX:
        return AUTHOR_NAME_LENGTH
    if not all(_allowed_in_name(c) for c in name):
        return AUTHOR_NAME_CHARACTERS
    if not _starts_a_name(name[0]):
        return AUTHOR_NAME_START
    return None


def author_name_unset(manifest_data) -> bool:
    """Whether `app_author_name` is there but empty, as the template ships it.

    The build publishes nothing in that state ("Nothing to publish yet").
    """
    if not isinstance(manifest_data, dict) or AUTHOR_NAME_KEY not in manifest_data:
        return False
    value = manifest_data[AUTHOR_NAME_KEY]
    return value is None or (isinstance(value, str) and not value.strip())


def legacy_publisher(manifest_data) -> str:
    """`app.publisher`, from manifests written before `app_author_name`."""
    if not isinstance(manifest_data, dict) or not isinstance(manifest_data.get("app"), dict):
        return ""
    value = manifest_data["app"].get("publisher")
    return value.strip() if isinstance(value, str) else ""


def owner_email_present(manifest_data) -> bool:
    """Whether an old `owner_email` line still names somebody, at the top or
    in `app`.

    Ownership no longer comes from this file. Pippa refuses the line in a
    public repository and ignores it in a private one. An empty one names
    nobody, so it counts as gone, as it does for Pippa.
    """
    if not isinstance(manifest_data, dict):
        return False
    for holder in (manifest_data, manifest_data.get("app")):
        if isinstance(holder, dict) and "owner_email" in holder:
            value = holder["owner_email"]
            if not (value is None or (isinstance(value, str) and not value.strip())):
                return True
    return False


# ── Email addresses ──────────────────────────────────────────────────────────

#: An email address, as this file and `.githooks/pre-commit` find one. The
#: patterns here are the hook's, character for character, so the hook refuses
#: exactly the lines this file warns about (scripts/test_pre_commit.py
#: compares the hook's copies). The build's own scan is a separate program
#: with a pattern of its own: it allows the same domains and skips the same
#: file names (FILE_SUFFIXES), so on ordinary text the three agree. On a
#: made-up string they can differ, and then the build is the one that counts.
#: Stricter than "anything round an @" on purpose: `mermaid@11/dist/...` in
#: docs/builder-guide.html, a font address's `wght@400` and Python's
#: `@pytest.mark.network` are not addresses.
EMAIL_PATTERN = r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}"
#: Addresses that cannot belong to anybody: GitHub's no-reply addresses, and
#: the domains reserved for examples and tests (RFC 2606). Matched against an
#: address found by EMAIL_PATTERN, ignoring capitals.
ALLOWED_PATTERN = (
    r"@(users\.noreply\.github\.com"
    r"|([A-Za-z0-9-]+\.)*example\.(com|org|net)"
    r"|([A-Za-z0-9-]+\.)*(example|test|invalid|localhost))$"
)
#: File names that EMAIL_PATTERN mistakes for an address: a picture drawn at
#: twice the size is `logo@2x.png`, a library is `lib@1.2.3.min.js`. A match
#: whose last part is one of these is a file name, as it is for the build,
#: whose list this is.
FILE_SUFFIXES = (
    "avif", "bmp", "cjs", "css", "csv", "gif", "heic", "htm", "html", "ico",
    "jpeg", "jpg", "js", "json", "jsx", "lock", "map", "mjs", "png", "scss",
    "svg", "tif", "tiff", "toml", "ts", "tsx", "txt", "webp", "whl", "xml",
    "yaml", "yml",
)
#: FILE_SUFFIXES as the hook matches them, ignoring capitals.
FILE_SUFFIX_PATTERN = r"\.(" + "|".join(FILE_SUFFIXES) + r")$"
#: Pippa's own test for an address in `manifest.yaml`, which is looser than
#: EMAIL_PATTERN and has no allowed domains: everything in the manifest is
#: shown to people, so even an example address does not belong there.
MANIFEST_EMAIL_PATTERN = r"[^\s@]+@[^\s@]+\.[^\s@]+"
#: The addresses a commit may carry, ignoring capitals: a GitHub no-reply
#: address, or GitHub's own `noreply` address at `github.com`, which GitHub
#: puts on the edits made on its website. The build accepts the same two.
#: (The second is not written out whole anywhere in this repository: it is not
#: at an allowed domain, so the build would refuse the file.)
NOREPLY_PATTERN = r"^([^@]+@users\.noreply\.github\.com|noreply@github\.com)$"
#: Files larger than this are skipped by the scan, as the build skips them.
SCAN_LIMIT_BYTES = 1024 * 1024

_EMAIL = re.compile(EMAIL_PATTERN)
_ALLOWED = re.compile(ALLOWED_PATTERN, re.IGNORECASE)
_FILE_SUFFIX = re.compile(FILE_SUFFIX_PATTERN, re.IGNORECASE)
_MANIFEST_EMAIL = re.compile(MANIFEST_EMAIL_PATTERN)
_NOREPLY = re.compile(NOREPLY_PATTERN, re.IGNORECASE)


def mask(address: str) -> str:
    """`s***@college.example`: enough to recognise your own, not to copy it."""
    local, _, domain = address.partition("@")
    return f"{local[:1]}***@{domain}"


def is_allowed_address(address: str) -> bool:
    return bool(_ALLOWED.search(address))


def is_file_name(address: str) -> bool:
    """Whether a match is really a file name, such as `logo@2x.png`."""
    return bool(_FILE_SUFFIX.search(address))


def addresses_in(text: str) -> list[tuple[int, str]]:
    """(line number, address) for every address in `text` that is not allowed."""
    found = []
    for number, line in enumerate(text.splitlines(), start=1):
        for match in _EMAIL.finditer(line):
            address = match.group(0)
            if not (is_allowed_address(address) or is_file_name(address)):
                found.append((number, address))
    return found


def manifest_address_paths(manifest_data) -> list[str]:
    """Where in the manifest there is an email address, as Pippa names the
    place: `app.summary`, `outcomes[0].example_phrases[2]`.

    Every string at any depth, keys of mappings as well as values, by Pippa's
    own looser test. A key that is itself an address is named by where it is
    (its parent, or "the top level"), so the address is never repeated.
    `owner_email` is left out: it has a warning of its own. Pippa stops at the
    first place; this lists them all, so they can be fixed in one go.
    """
    found: list[str] = []

    def walk(value, path: str) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if isinstance(key, str) and _MANIFEST_EMAIL.search(key):
                    found.append(path or "the top level")
                    continue
                if key == "owner_email" and path in ("", "app"):
                    continue
                walk(item, f"{path}.{key}" if path else str(key))
        elif isinstance(value, (list, tuple)):
            for index, item in enumerate(value):
                walk(item, f"{path}[{index}]")
        elif isinstance(value, str) and _MANIFEST_EMAIL.search(value):
            found.append(path or "the top level")

    walk(manifest_data, "")
    return list(dict.fromkeys(found))


def tracked_files() -> list[str]:
    """The files git tracks here: the ones a push publishes."""
    return [name for name in git("ls-files", "-z").split("\0") if name]


def scan_files(root: Path, names: list[str]) -> list[tuple[str, int, str]]:
    """(file, line, masked address) for every address in these files.

    Binary files and files over a megabyte are skipped, as the build skips
    them.
    """
    found = []
    for name in names:
        path = root / name
        try:
            if not path.is_file() or path.stat().st_size > SCAN_LIMIT_BYTES:
                continue
            data = path.read_bytes()
        except OSError:
            continue
        if b"\0" in data[:8192]:
            continue
        text = data.decode("utf-8", errors="replace")
        for number, address in addresses_in(text):
            found.append((name, number, mask(address)))
    return found


def identity_email(ident: str) -> str:
    """The address out of git's `Name <address> 1700000000 +0000`."""
    match = re.search(r"<([^>]*)>", ident)
    return match.group(1).strip() if match else ""


def commit_emails() -> dict[str, str]:
    """The addresses on the commit: author and committer.

    In the build, the commit that was pushed. Here, the next commit you make,
    which is the one worth hearing about while it can still be changed.
    """
    if os.environ.get("GITHUB_ACTIONS") == "true":
        lines = git("log", "-1", "--format=%ae%n%ce").splitlines()
        lines += ["", ""]
        return {"author": lines[0].strip(), "committer": lines[1].strip()}
    return {
        "author": identity_email(git("var", "GIT_AUTHOR_IDENT")),
        "committer": identity_email(git("var", "GIT_COMMITTER_IDENT")),
    }


def identity_problems(emails: dict[str, str]) -> list[str]:
    """One sentence per address that is not a GitHub no-reply address.

    An empty address is not a problem here: git refuses to commit without one
    and says so better than this could. Nor is GitHub's own `noreply`
    address, the committer of an edit made on github.com: the build accepts
    it, and nobody can change it.
    """
    problems, seen = [], set()
    for role, address in emails.items():
        if not address or _NOREPLY.search(address) or address in seen:
            continue
        seen.add(address)
        problems.append(
            f"the commit's {role} email is {mask(address)}, not a GitHub no-reply address"
        )
    return problems


def main() -> int:
    print("\nChecking your app before you push\n")
    results = []

    # ── The files that must exist ────────────────────────────────────────────
    for name in ("app.py", "manifest.yaml"):
        path = ROOT / name
        results.append(
            ok(f"{name} is present") if path.exists()
            else bad(f"{name} is missing",
                     f"The publisher expects {name} at the top level of the repository.")
        )
    if not all(results):
        return 1

    # ── The manifest parses, and says what it must ───────────────────────────
    try:
        from pippa_agentapp_sdk import load_manifest_file, validate_manifest

        # The raw mapping is kept as well as the validated object: the checks
        # below read fields the SDK does not keep.
        manifest_data = load_manifest_file(ROOT / "manifest.yaml")
        manifest = validate_manifest(manifest_data)
        results.append(ok(f"manifest.yaml is valid ({manifest.app_id} v{manifest.version})"))
    except ImportError:
        bad(
            "the Pippa SDK is not installed",
            "The build installs it before this check; it is not in this "
            "repository. Do not change .github/. If the build says this, "
            "ask an organiser.",
        )
        return 1
    except Exception as exc:
        results.append(bad(f"manifest.yaml is not valid: {exc}"))
        return 1

    # ── The app id matches the repository ────────────────────────────────────
    repo = repo_name()
    if repo is None:
        print(f"{YELLOW}  --  no git remote yet, so the app id cannot be checked{PLAIN}",
              flush=True)
    elif not repo.startswith(REPO_PREFIX):
        results.append(bad(
            f"the repository is called {repo!r}, which does not start with {REPO_PREFIX!r}",
            "Only repositories created for the hackathon can publish.",
        ))
    else:
        expected = expected_app_id(repo)
        if manifest.app_id == expected:
            results.append(ok(f"the app id matches the repository ({expected})"))
        else:
            results.append(bad(
                f"manifest.yaml declares {manifest.app_id!r}, but this repository "
                f"publishes {expected!r}",
                f"Change `app.id` in manifest.yaml to: {expected}",
            ))

    # ── The public author name ───────────────────────────────────────────────
    #
    # Warnings, not gates; the module docstring says why. Pippa refuses a push
    # whose name breaks a rule, so the build would stop there anyway.
    if author_name_unset(manifest_data):
        warn("app_author_name is empty, so nothing publishes yet.",
             "It is the public name shown with your app. The build skips every\n"
             'push until it is filled in ("Nothing to publish yet"). A pseudonym,\n'
             "never your real name or an email address: CLAUDE.md, step 1.")
    elif manifest_data.get(AUTHOR_NAME_KEY) is not None:
        problem = author_name_problem(manifest_data[AUTHOR_NAME_KEY])
        if problem:
            warn(problem,
                 "It is shown to everybody next to your app, so make it a pseudonym:\n"
                 "never your real name, never an email address. Pippa refuses the\n"
                 "push until it fits. CLAUDE.md, step 1, has the rules.")
        else:
            results.append(ok(
                f"app_author_name is {normalise_author_name(manifest_data[AUTHOR_NAME_KEY])!r}"
            ))
    elif legacy_publisher(manifest_data):
        warn(ADD_AUTHOR_NAME,
             'One line at the top of manifest.yaml, above `app:`, and take\n'
             '`publisher:` out of `app:`:\n'
             "\n"
             '    app_author_name: "Tidewatcher"\n'
             "\n"
             "A pseudonym, never your real name or an email address.")

    # ── Nothing personal in the manifest ─────────────────────────────────────
    #
    # Who owns the app comes from the repository. An `owner_email` line is
    # left over from an older template, and Pippa refuses it in a public
    # repository and ignores it in a private one.
    has_owner_email = owner_email_present(manifest_data)
    if has_owner_email:
        warn("Remove `owner_email` from manifest.yaml.",
             "Pippa knows who owns this app from your repository, so nothing in\n"
             "this file says who you are. In a public repository Pippa refuses the\n"
             "push while the line is there; in a private one it ignores it.")
    places = manifest_address_paths(manifest_data)
    for place in places:
        warn(f"manifest.yaml contains an email address (at {place}). Remove it: "
             "everything in manifest.yaml is shown to people or stored with your app.")
    if not places and not has_owner_email:
        results.append(ok("manifest.yaml has no email address in it"))

    # ── No email address in the repository, or on the commits ───────────────
    #
    # The build refuses an address in any file, and Pippa shows the name and
    # address on every commit to anyone who can read the repository.
    # `.githooks/pre-commit` stops both before the commit exists; this is the
    # same check for a clone where the hook was never switched on.
    names = tracked_files()
    if names:
        found = scan_files(ROOT, names)
        for name, number, masked in found:
            warn(f"{name}:{number} contains the email address {masked}",
                 "Take it out. Every file here can end up public, and the build\n"
                 "refuses a push with an email address in any file. Addresses at\n"
                 "example.com, or a .example or .test domain, are fine.")
        if not found:
            results.append(ok("no file contains an email address"))
    for problem in identity_problems(commit_emails()):
        warn(problem,
             "Everybody who can read this repository can read it, for good. Set\n"
             "your GitHub no-reply address for this repository (CLAUDE.md, step 1,\n"
             "says how to find it), and your pseudonym as the name on commits:\n"
             "\n"
             '    git config user.email "<id>+<login>@users.noreply.github.com"\n'
             '    git config user.name "<your app_author_name>"\n'
             "\n"
             "A commit not pushed yet can then be fixed with\n"
             "`git commit --amend --no-edit --reset-author`.")

    # ── The summary must not contain " by " ──────────────────────────────────
    #
    # The badge under a reply is built as "[via <name> <version> by <author>]"
    # and split on the FIRST " by ". A summary containing the word steals the
    # split, and the badge then shows a fragment of your summary where your
    # author name belongs. Nothing else notices, which is why it has to be
    # caught here: the symptom appears days later, on somebody else's screen.
    if " by " in f" {manifest.summary} ".lower():
        results.append(bad(
            'app.summary contains the word "by"',
            'The store badge is parsed as "... by <author name>" and splits on '
            'the first "by", so the badge would show your summary text as the '
            "author. Reword the summary without it.",
        ))
    else:
        results.append(ok('app.summary does not contain "by"'))

    # ── No credentials ───────────────────────────────────────────────────────
    #
    # Registration refuses any hackathon app that asks for a connector or a
    # secret: granting a stranger's app a real user's Google account is not
    # something a workshop can consent to on that user's behalf. Without this
    # check the refusal arrives from the publisher, after the push, in a log.
    for field in ("connectors", "secrets"):
        declared = getattr(manifest, field, None) or ()
        if declared:
            results.append(bad(
                f"manifest.yaml declares {field}",
                f"Hackathon apps may not ask for credentials, and publishing "
                f"refuses any app that does. Remove the `{field}:` block. Your "
                f"app can still call a public API that needs no key, or one "
                f"whose provider publishes a demo key for everyone. Never use a "
                f"key tied to your own account: this repository is public. "
                f"See docs/API_APPS.md.",
            ))
    if not (getattr(manifest, "connectors", None) or getattr(manifest, "secrets", None)):
        results.append(ok("no connectors or secrets are declared"))

    # ── The app class is where the handler expects it ────────────────────────
    sys.path.insert(0, str(ROOT))
    try:
        import app as app_module

        App = getattr(app_module, "App", None)
        if App is None:
            results.append(bad(
                "app.py does not define a class called App",
                "The handler imports `App` from app.py. The name matters.",
            ))
        elif not hasattr(App, "handle"):
            results.append(bad("App has no handle() method"))
        else:
            results.append(ok("app.py defines App with a handle() method"))
    except Exception as exc:
        results.append(bad(f"app.py could not be imported: {type(exc).__name__}: {exc}"))

    # ── The outcomes have what routing needs ─────────────────────────────────
    for outcome in manifest.outcomes:
        phrases = list(getattr(outcome, "example_phrases", ()) or ())
        if len(phrases) >= 3:
            results.append(ok(f"{outcome.id} has {len(phrases)} example phrases"))
        else:
            results.append(bad(
                f"{outcome.id} has {len(phrases)} example phrase(s)",
                "Pippa chooses your app by comparing the user's message against "
                "these. With fewer than about three, your app will rarely be "
                "picked. Five to ten is a good number.",
            ))

    # ── The tests ────────────────────────────────────────────────────────────
    print(flush=True)
    tests = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=ROOT)
    results.append(
        ok("the tests pass") if tests.returncode == 0
        else bad("the tests fail", "Publishing runs them too, and will stop here.")
    )

    print()
    # Said again, last. Everything above has scrolled past the test output by
    # now, and on a green run this is the only thing left that needs doing.
    for message in warnings:
        print(f"{YELLOW} WARN{PLAIN} {message}", flush=True)
    if warnings:
        print()

    if all(results):
        print(f"{GREEN}Ready to push.{PLAIN}")
        # Passing here means it will publish. It says nothing about whether
        # the app will ever be reached, and that is the failure builders
        # actually hit, so point at the tool that measures it.
        print("  Next: check manifest.yaml against scripts/routing_check.py — "
              "whether Pippa will ever choose it.\n")
        return 0
    print(f"{RED}Not ready yet — fix the FAIL lines above.{PLAIN}\n")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
