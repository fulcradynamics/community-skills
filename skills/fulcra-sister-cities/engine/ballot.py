"""Blind ballots (spec #18).

When an export window closes, the collected submissions are shuffled and given
short refs (A, B, C, ...). The importer then votes by ref.

Two details matter for blindness:

* The shuffle is keyed off the need, so ballot order carries no trace of
  submission order -- otherwise "ref A" would reliably mean "whoever answers
  fastest", which is an identity leak dressed as a coincidence.
* The importer's pick API takes a ref, not a city. There is no argument they
  could pass that names an exporter, so the interface itself is blind rather
  than relying on the caller to be discreet.
"""

import string

from .errors import PickRejected

_LETTERS = string.ascii_uppercase


def ref_for_index(index):
    """0 -> 'A', 25 -> 'Z', 26 -> 'AA' (never reached at 10 players, but total)."""
    if index < len(_LETTERS):
        return _LETTERS[index]
    first, second = divmod(index, len(_LETTERS))
    return _LETTERS[first - 1] + _LETTERS[second]


def assign_refs(rng, submissions):
    """Shuffle ``submissions`` and stamp each with its ballot ref."""
    shuffled = sorted(submissions, key=lambda s: s.submission_id)
    rng.shuffle(shuffled)
    for index, submission in enumerate(shuffled):
        submission.ballot_ref = ref_for_index(index)
    return shuffled


def build(submissions):
    """The importer's view: refs and export text, and nothing else.

    Returned dicts are constructed field by field from a two-field whitelist.
    Adding a field to :class:`~engine.state.Submission` therefore cannot widen
    this payload by accident.
    """
    entries = []
    for submission in sorted(submissions, key=lambda s: s.ballot_ref or ""):
        entries.append({"ballot_ref": submission.ballot_ref, "export": submission.text})
    return entries


def resolve_ref(submissions, ballot_ref):
    for submission in submissions:
        if submission.ballot_ref == ballot_ref:
            return submission
    raise PickRejected(
        "ballot ref %r is not on this ballot; choices are %s"
        % (ballot_ref, sorted(s.ballot_ref for s in submissions))
    )
