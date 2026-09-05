"""The last thing that runs before anything becomes public.

Everything in :mod:`hosting.manifest` is a *declaration*: somebody said this
file is public and said why. This module is the check on that declaration, and
it is deliberately not the same person's opinion twice -- the manifest says what
was intended, the guard reads the bytes and says what is actually there.

Four questions, in order of how badly the answer would go:

1. **Is the address in it?** The unguessable subdomain is the paper's only
   credential (spec #26). A page that printed its own URL would be a page that
   published the credential, and the built site is committed to a repo, so this
   is the rule that keeps that safe.
2. **Is anybody's identity in it?** Handles, player ids, and any non-winning
   export traced to its city (spec #21, #28). Not reimplemented here:
   :mod:`newspaper.redact` and :mod:`engine.audit` already decide this and are
   run again over the *rendered HTML*, which is a thing neither of them has seen
   before -- M5 checked the markdown, and this is a different rendering of the
   same edition.
3. **Is something private in it?** Credentials, keys, facilitator-only views,
   unfinished milestone stubs -- and, structurally, anything whose declared
   source is a part of this repo that is nobody's business
   (:data:`DENY_SOURCES`).
4. **Does it reach off-site?** A private URL leaks through ``Referer`` the
   moment a page loads a font, an analytics script or an image from somewhere
   else. So published pages may reference no external origin at all, and that is
   checked here rather than left to the CSP header to catch at runtime.

None of it is configurable, on purpose. ``config.json`` is the single source for
every *parameter* the spec calls configurable, and it is deliberately not a
source for whether the paper checks that it is not leaking -- the same carve-out
:mod:`engine.economy` makes for spec #21. :func:`assert_no_config_can_disable`
is the test-facing statement of that, and it fails if a knob ever appears.
"""

import os
import re

from engine import audit
from engine.errors import RuleViolation
from newspaper import redact

from .manifest import edition_key

#: Parts of this repo that may never be the source of a published file. Matched
#: as substrings of the declared ``source``, so a nested path is caught too.
#: These are the "no inboxes, raw verdicts, credentials or private repo data"
#: half of the milestone, expressed as a structural rule rather than as a hope
#: about what the builder happened to pass in.
DENY_SOURCES = (
    ".git", ".site-id", ".env", "config.json", "credential", "secret", "password",
    "inbox", "inboxes", "verdict", "evaluation", "evaluator", "grading", "feedback",
    "decisions.md", "spec.md", "milestones.md", "coordinator/", "harness/", "roles/",
    "tests/", "engine/state.py", "ledger",
)

#: Content patterns that are never publishable whatever they are attached to.
#: Each is a shape that only means one thing: a credential, an authorisation
#: header, or a private key.
DENY_PATTERNS = (
    (
        "private_key",
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
        "a private key",
    ),
    (
        "credential_assignment",
        re.compile(
            r"(?i)\b(?:api[_-]?key|secret[_-]?key|client[_-]?secret|access[_-]?token"
            r"|auth[_-]?token|password|passwd)\b\s*[:=]"
        ),
        "something assigning a credential",
    ),
    (
        "authorization_header",
        re.compile(r"(?im)^\s*authorization\s*:\s*\S"),
        "an Authorization header",
    ),
    (
        "aws_access_key",
        re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
        "an AWS access key id",
    ),
    (
        "github_token",
        re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
        "a GitHub token",
    ),
    (
        "external_reference",
        re.compile(r"""(?i)\b(?:href|src|url)\s*[=(]\s*["']?(?:[a-z][a-z0-9+.-]*:)?//"""),
        "a reference to an external origin, which would hand this paper's private "
        "address to somebody else's referrer log (spec #26)",
    ),
    (
        "milestone_stub",
        re.compile(r"\[\[M\d"),
        "an unfinished milestone stub, which is a note to the build and not a "
        "thing to print",
    ),
    (
        "facilitator_view",
        re.compile(r"""["']?audience["']?\s*[:=]\s*["']facilitator"""),
        "a facilitator-only view, which is not a newspaper payload",
    ),
)


class PublicationRefused(RuleViolation):
    """Something in the build would have been published that must not be."""


def scan_text(text, where, site_id=None):
    """Every rule :data:`DENY_PATTERNS` and the address make about one file."""
    problems = []
    if site_id and site_id in text:
        problems.append(
            {
                "file": where,
                "rule": "site_id_published",
                "why": "the unguessable subdomain is this paper's only credential "
                       "(spec #26); a published file containing it publishes the paper",
            }
        )
    for name, pattern, why in DENY_PATTERNS:
        match = pattern.search(text)
        if match:
            problems.append(
                {
                    "file": where,
                    "rule": name,
                    "why": why,
                    "matched": match.group(0)[:80],
                }
            )
    return problems


def scan_source(source, where):
    lowered = str(source).lower()
    return [
        {
            "file": where,
            "rule": "forbidden_source",
            "why": "%r derives from %r, which is private repo data and never "
                   "publishable" % (source, fragment),
        }
        for fragment in DENY_SOURCES
        if fragment in lowered
    ]


def assert_publishable(engine, manifest, editions, identity=None, rendered_by_round=None,
                       payloads=()):
    """Raise :class:`PublicationRefused` unless every published byte may be public.

    ``editions`` are the structured editions behind the pages and
    ``rendered_by_round`` maps a round to the HTML it was rendered to, so the
    redaction audit sees the actual published rendering rather than the payload
    it was built from. A leak that exists only in the HTML is still published.

    ``payloads`` are any *structured* things being published -- the curated
    ``archive.json``. They are audited as structures rather than as text,
    because :func:`engine.audit.find_exposure_violations` asks whether a payload
    has a gated key, and a key is a thing a dict has and a string does not.
    """
    site_id = identity.site_id if identity is not None else None
    rendered_by_round = rendered_by_round or {}
    problems = []

    for entry in manifest.files:
        problems.extend(scan_source(entry.source, entry.path))
        problems.extend(scan_text(entry.text, entry.path, site_id=site_id))
        if not entry.why_public or not str(entry.why_public).strip():
            problems.append(
                {
                    "file": entry.path,
                    "rule": "undeclared_reason",
                    "why": "nothing may be published without a stated reason",
                }
            )

    # Spec #28 over every published byte, not just over the editions: a handle
    # in the stylesheet's comments or in a curated JSON blob is as printed as a
    # handle in the prose. Same check the paper already applies to an edition,
    # imported rather than rewritten.
    printed = redact.find_printed_identities(
        engine, [entry.text for entry in manifest.files]
    )
    for label, hits in printed.items():
        problems.append(
            {
                "file": "<published>",
                "rule": label,
                "why": "spec #28 -- mayors are named by city and office only",
                "matched": hits,
            }
        )

    # An edition per round, one page each, nothing overwriting anything (#26, #27).
    pages = manifest.by_category("editions")
    rounds = [page.round for page in pages]
    if len(set(rounds)) != len(rounds):
        problems.append(
            {
                "file": "<manifest>",
                "rule": "duplicate_edition",
                "why": "more than one page claims the same round; an edition would be "
                       "replacing an edition (spec #26, #27)",
            }
        )

    if problems:
        raise PublicationRefused("publication refused: %r" % problems)

    # Identity, blind voting and exposure policy, re-run over the HTML. Raises
    # its own (differently typed) error, which is the right one to see: it says
    # which spec rule broke, and this module would only be able to say "a file".
    for edition in editions:
        redact.assert_edition_is_redacted(
            engine, edition, rendered=rendered_by_round.get(edition_key(edition), [])
        )
    published = {
        "published_text": [entry.text for entry in manifest.files],
        "published_payloads": list(payloads),
    }
    audit.assert_blind(engine, published)
    audit.assert_exposure_policy(engine, published)
    return True


def assert_public_root_matches(manifest, public_root):
    """The directory on disk is the manifest, exactly -- no more, no less.

    The "no more" half is the one that matters. A file left behind by an earlier
    build, a scratch copy, an editor's backup: none of them were curated and all
    of them would be served by a host that serves a directory.
    """
    on_disk = set()
    for base, _, names in os.walk(public_root):
        for name in names:
            on_disk.add(os.path.relpath(os.path.join(base, name), public_root))
    declared = set(manifest.paths())
    undeclared = sorted(on_disk - declared)
    missing = sorted(declared - on_disk)
    if undeclared or missing:
        raise PublicationRefused(
            "the public root does not match the manifest: undeclared=%r missing=%r"
            % (undeclared, missing)
        )
    return True


def assert_archive_is_append_only(previous, manifest):
    """A round published once stays published (spec #27).

    ``previous`` is the last build's manifest as JSON, or ``None``. The check is
    on rounds and on paths: an edition that was reachable must still be
    reachable, and at the same name, because "prior editions remain browsable at
    that same URL" is a promise about links a mayor already has.
    """
    if not previous:
        return True
    kept = {entry["path"] for entry in previous.get("files", [])
            if entry.get("category") in ("editions", "edition_images")}
    dropped = sorted(kept - set(manifest.paths()))
    lost_rounds = sorted(set(previous.get("published_rounds") or []) - set(manifest.published_rounds()))
    if dropped or lost_rounds:
        raise PublicationRefused(
            "this build would remove already-published editions: files=%r rounds=%r "
            "(spec #27 -- an archive, not an overwrite)" % (dropped, lost_rounds)
        )
    return True


def assert_no_config_can_disable(config_data):
    """No key in ``config.json`` may switch any of this off.

    Spec #22 makes exposure policy configurable; it does not make *leaking*
    configurable, and the rules above are the ones with no legitimate "off".
    Same carve-out :mod:`engine.economy` makes for spec #21, checked the same
    way: over the raw config document, because a knob nothing reads yet is still
    a knob somebody will wire up.
    """
    banned = re.compile(
        r"(?i)(allow|permit|skip|disable|ignore|bypass|suppress).*"
        r"(leak|guard|redact|scan|secret|site_id|publication_check|audit)"
        r"|(leak|guard|redact|scan|secret|site_id|audit).*"
        r"(allowed|permitted|disabled|skipped|ignored|off)"
    )
    offenders = []
    for path, node in _walk(config_data):
        if not isinstance(node, dict):
            continue
        for key in node:
            if isinstance(key, str) and banned.search(key):
                offenders.append({"path": "%s.%s" % (path, key), "spec": "#21, #26"})
    return offenders


def _walk(node, path="$"):
    yield path, node
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _walk(value, "%s.%s" % (path, key))
    elif isinstance(node, (list, tuple)):
        for index, value in enumerate(node):
            yield from _walk(value, "%s[%d]" % (path, index))
