"""The Wire: writing spec #25's aggregate item.

The judged criterion attached to spec #25 is not whether the sentence sounds
clever. It is whether the sentence is *true of the distribution it describes* --
"present-looking language over an actually-wrong aggregate" is an explicit fail.
So this module is written so that it cannot make that mistake, rather than
carefully avoiding it:

* The claim is not chosen here. :mod:`engine.aggregate` selects exactly one
  outcome arithmetically -- a tier, a tie, a fragmented world, or the
  low-respondent floor -- and reports the wordings that outcome licenses.
* This module may use no other wording. :func:`choose_phrase` draws only from
  ``outcome.phrases`` (true of *every* distribution that can select the outcome)
  and from ``conditional_phrases`` entries the ladder marked ``licensed`` for
  these actual counts. :func:`assert_licensed` re-checks the phrase after the
  fact, so a future frame that interpolated its own aggregate language would
  fail rather than publish.
* Every number in the item -- respondents, the size of the leading bucket, the
  cities quoted -- comes out of the report, never out of the prose.

The frames themselves live in ``content/newspaper.json`` under ``wire_styles``,
selected by ``config.facilitator_questions.aggregate_phrasing_style``. They are
all written to work with a singular aggregate phrase ("the world") and a plural
one ("most nations") alike, which is why none of them places a verb directly
after the phrase.

One further rule, from the content file's own integrity list: this item never
mentions an export, a ballot ref or a submission. The questions channel and the
blind-voting channel do not cross-reference each other, because an answer
printed beside an export is a way of working out who sent what (spec #18, #21).
"""

from engine.aggregate import (
    FRAGMENTED_CASE,
    LOW_RESPONDENT_FLOOR,
    ROLE_HEADLINE,
    ROLE_OUTLIER,
    ROLE_SUBGROUP,
    TIE_CASE,
    TIER,
)
from engine.errors import RuleViolation

from . import voice

#: Where a chosen phrase came from. Recorded in the item's provenance so a
#: reviewer can see at a glance whether the sharper wording was earned.
FROM_PHRASES = "phrases"
FROM_CONDITIONAL = "conditional_phrases"


def join_phrases(items, final="and"):
    """``["a", "b", "c"] -> "a, b and c"`` -- a newspaper list, not a JSON one."""
    items = [str(item) for item in items]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return "%s %s %s" % (", ".join(items[:-1]), final, items[-1])


def licensed_phrases(outcome):
    """Every wording this distribution has actually earned, sharper ones first.

    A conditional phrase is preferred when it is licensed: it is the more
    specific line, and being licensed means the ladder has already checked its
    ``only_if`` against the real counts. An unlicensed conditional is not merely
    deprioritised -- it never enters the pool.
    """
    conditional = [
        entry["phrase"]
        for entry in outcome.get("conditional_phrases", [])
        if entry.get("licensed")
    ]
    return conditional, list(outcome["phrases"])


def choose_phrase(outcome, chooser, key, where):
    """One licensed wording for this outcome, and where it came from."""
    conditional, safe = licensed_phrases(outcome)
    pool = conditional if conditional else safe
    source = FROM_CONDITIONAL if conditional else FROM_PHRASES
    phrase = chooser.pick(pool, key, where)
    assert_licensed(phrase, outcome)
    return phrase, source


def assert_licensed(phrase, outcome):
    """Raise unless ``phrase`` is one this outcome licenses for these counts.

    The belt to :func:`choose_phrase`'s braces. It exists because the failure it
    catches is invisible in the output: an unlicensed phrase reads exactly as
    well as a licensed one and is simply false.
    """
    conditional, safe = licensed_phrases(outcome)
    if phrase not in conditional and phrase not in safe:
        unlicensed = [
            entry["phrase"]
            for entry in outcome.get("conditional_phrases", [])
            if not entry.get("licensed")
        ]
        raise RuleViolation(
            "the aggregate item tried to use %r, which outcome %r does not license for "
            "this distribution (spec #25). Licensed: %s. Refused: %s."
            % (phrase, outcome["id"], sorted(conditional + safe), sorted(unlicensed))
        )
    return True


def _capitalized(phrase):
    return phrase[:1].upper() + phrase[1:] if phrase else phrase


def _buckets_with_role(report, role):
    return [row for row in report.get("buckets", []) if row.get("role") == role]


def licenses_aggregate_heading(report):
    """Whether this item may be headlined at world scale (spec #25).

    A question's ``newspaper_hook`` is written as an aggregate claim -- "Contents
    of the world's desks" -- so it is only true of a round that actually produced
    an aggregate. Two rounds do not:

    * nothing reportable at all (nobody replied, or the answers are not yet
      clustered), where the body says the paper has no distribution to describe
    * the low-respondent floor, where the ladder's own integrity rule is that one
      or two replies license *no* aggregate framing

    Printing the hook over either is the exact judged failure attached to #25:
    present-looking aggregate language above a body that disclaims it.
    """
    if not report["reportable"]:
        return False
    return report["outcome"]["kind"] != LOW_RESPONDENT_FLOOR


def heading(report, department, chooser):
    """The column's heading for this round: the hook only when it is earned."""
    hook = report.get("newspaper_hook")
    if hook and licenses_aggregate_heading(report):
        return hook
    return chooser.line(
        department["headings_without_aggregate"],
        (report["round"], report["question_id"], "heading"),
        "departments.the_wire.headings_without_aggregate",
    )


def write(report, style, department, chooser, max_quotes):
    """The item's prose blocks plus its provenance, or the no-item blocks.

    ``report`` is :func:`engine.views.newspaper_mayor_question`'s payload. It is
    never ``None`` here -- the caller decides whether the department appears at
    all, because when ``answers_shared_in_newspaper`` is false the paper must not
    even mention that a question was asked. ``style`` is the prose register from
    ``wire_styles``; ``department`` is The Wire's own frames, which carry the two
    things to print when there is no item at all.
    """
    key_base = (report["round"], report["question_id"])
    blocks = [
        {"kind": "heading", "level": 3, "text": heading(report, department, chooser)},
        {
            "kind": "para",
            "text": chooser.line(
                style["put_it_to"], key_base + ("put_it_to",), "wire_styles.put_it_to",
                {"question": report["text"]},
            ),
        },
    ]

    if not report["reportable"]:
        # No outcome: either nobody answered, or nobody has clustered the
        # answers yet. Both are reported as what they are. The paper does not
        # get to describe a distribution it has not measured (spec #25).
        family = "pending" if report["no_item_reason"] == "pending" else "no_responses"
        blocks.append(
            {
                "kind": "para",
                "text": chooser.line(
                    department[family], key_base + (family,),
                    "departments.the_wire.%s" % family,
                ),
            }
        )
        return blocks, {
            "outcome": None,
            "no_item_reason": report["no_item_reason"],
            "answered": report["answered"],
            "asked_of": report["asked_of"],
            "bucketing": report["bucketing"]["status"],
            "aggregate_heading_used": False,
            "spec": "#25",
        }

    outcome = report["outcome"]
    phrase, source = choose_phrase(
        outcome, chooser, key_base + ("phrase",), "questions.json outcome %r" % outcome["id"]
    )
    values = {
        "phrase": phrase,
        "Phrase": _capitalized(phrase),
        "answered": report["answered"],
        "asked_of": report["asked_of"],
    }

    claim_family, count_family, label_note, quoted_answers = _claim_for(
        outcome, report, style, values, chooser
    )
    # The claim is the paper's sentence; an answer quoted inside it is the
    # mayor's own words and is exempt from the editorial register (spec #30b).
    blocks.append(
        voice.within({"kind": "para", "text": claim_family}, *quoted_answers)
    )
    if count_family:
        blocks.append({"kind": "para", "text": count_family})

    garnishes = _garnishes(report, style, chooser, key_base, max_quotes)
    blocks.extend(garnishes)

    provenance = {
        "outcome": outcome["id"],
        "kind": outcome["kind"],
        "phrase_used": phrase,
        "phrase_source": source,
        "licensed": True,
        "selection": report["selection"],
        "answered": report["answered"],
        "asked_of": report["asked_of"],
        "silent": report["silent"],
        "measure": report.get("measure"),
        "headline_labels": label_note,
        "aggregate_heading_used": licenses_aggregate_heading(report),
        "partial_response_disclosed": bool(count_family)
        or outcome["kind"] == LOW_RESPONDENT_FLOOR,
        "must_disclose_partial_response": report["integrity"][
            "must_disclose_partial_response"
        ],
        "spec": "#25",
    }
    return blocks, provenance


def _claim_for(outcome, report, style, values, chooser):
    """The claim sentence, its supporting count sentence, labels, and any quotes.

    One branch per outcome kind, because the *grammar* of the claim differs: a
    tier has one leading bucket to name, a tie has exactly two, a fragmented
    world has no leader at all, and the floor has too few replies to have a
    shape. Getting this wrong is precisely the failure mode spec #25 is judged
    on, so the branches are explicit rather than one clever template.

    The fourth return value is the answers a branch quoted verbatim inside its
    own sentence -- only the floor does, and only because too few replies is the
    one case where the paper prints the replies instead of a shape. They are
    returned rather than recomputed by the caller because the branch that quotes
    is the branch that knows it quoted (spec #30b).
    """
    key_base = (report["round"], report["question_id"])
    kind = outcome["kind"]
    full = report["answered"] >= report["asked_of"]

    if kind == TIER:
        headline = _buckets_with_role(report, ROLE_HEADLINE)
        if len(headline) != 1:
            raise RuleViolation(
                "outcome %r is a tier, which by construction has exactly one leading "
                "bucket, but the report carries %d (spec #25)"
                % (outcome["id"], len(headline))
            )
        label = headline[0]["label"]
        claim = chooser.line(
            style["tier_claim"], key_base + ("tier",), "wire_styles.tier_claim",
            dict(values, label=label),
        )
        family = style["count_full"] if full else style["count_partial"]
        count = chooser.line(
            family, key_base + ("count",),
            "wire_styles.count_%s" % ("full" if full else "partial"),
            dict(values, label=label, largest=report["measure"]["largest_bucket_size"]),
        )
        return claim, count, [label], []

    if kind == TIE_CASE:
        headline = _buckets_with_role(report, ROLE_HEADLINE)
        if len(headline) < 2:
            raise RuleViolation(
                "outcome %r is a tie, which needs two leading buckets, and the report "
                "carries %d (spec #25)" % (outcome["id"], len(headline))
            )
        labels = [row["label"] for row in headline[:2]]
        claim = chooser.line(
            style["tie_claim"], key_base + ("tie",), "wire_styles.tie_claim",
            dict(values, label_a=labels[0], label_b=labels[1],
                 largest=report["measure"]["largest_bucket_size"]),
        )
        count = chooser.line(
            style["count_tie"], key_base + ("count",), "wire_styles.count_tie",
            dict(values, largest=report["measure"]["largest_bucket_size"]),
        )
        return claim, count, labels, []

    if kind == FRAGMENTED_CASE:
        labels = [row["label"] for row in report["buckets"]]
        claim = chooser.line(
            style["fragmented_claim"], key_base + ("fragmented",),
            "wire_styles.fragmented_claim",
            dict(values, labels=join_phrases(labels)),
        )
        count = chooser.line(
            style["count_fragmented"], key_base + ("count",),
            "wire_styles.count_fragmented", values,
        )
        return claim, count, labels, []

    if kind == LOW_RESPONDENT_FLOOR:
        # Too few replies to describe a distribution, so the paper prints the
        # replies themselves. No clustering is needed or used here -- that is
        # exactly what the floor is for.
        quotes = [
            style["floor_quote"].replace("{quote_city}", city).replace("{answer}", answer)
            for city, answer in sorted(report["answers_by_city"].items())
        ]
        joined = style.get("floor_quote_join", " ").join(quotes)
        claim = chooser.line(
            style["floor_claim"], key_base + ("floor",), "wire_styles.floor_claim",
            dict(values, floor_roll=joined),
        )
        count = chooser.line(
            style["count_floor"], key_base + ("count",), "wire_styles.count_floor", values,
        )
        return claim, count, [], sorted(report["answers_by_city"].values())

    raise RuleViolation(
        "unknown aggregate outcome kind %r; the paper will not improvise a claim "
        "about a distribution it does not understand (spec #25)" % kind
    )


def _garnishes(report, style, chooser, key_base, max_quotes):
    """The buckets that did not lead -- never the headline (content integrity rule).

    A subgroup gets a sentence. An outlier gets a sentence and, budget
    permitting, its answer quoted and attributed to a city hall -- which is the
    one place this item names a single mayor, and it names them by office
    (spec #28).
    """
    blocks = []
    quoted = 0
    garnishes = report.get("garnishes") or {}

    # ``rotate`` rather than ``pick`` for both runs: two outliers quoted one
    # after another in the same frame reads as a template showing through, and
    # the whole point of writing the copy as frames is that it should not.
    for offset, row in enumerate(_buckets_with_role(report, ROLE_SUBGROUP)):
        if "subgroup" not in garnishes:
            break
        # ``pick``, not ``rotate``: a ladder phrase is a fragment, and the frame
        # it lands in decides its case via {phrase} or {Phrase}. Sentence-casing
        # it here produced "And then One lone municipality" mid-sentence.
        phrase = chooser.pick(
            garnishes["subgroup"]["phrases"], key_base + ("subgroup",),
            "questions.json subgroup_phrasing", offset=offset,
        )
        blocks.append(
            {
                "kind": "para",
                "text": chooser.rotate(
                    style["subgroup"], key_base + ("subgroup_frame",),
                    "wire_styles.subgroup", offset,
                    {"phrase": phrase, "Phrase": _capitalized(phrase), "label": row["label"]},
                ),
            }
        )

    for offset, row in enumerate(_buckets_with_role(report, ROLE_OUTLIER)):
        if "outlier" not in garnishes or quoted >= max_quotes:
            break
        phrase = chooser.pick(
            garnishes["outlier"]["phrases"], key_base + ("outlier",),
            "questions.json outlier_phrasing", offset=offset,
        )
        city = row["cities"][0]
        blocks.append(
            voice.within(
                {
                    "kind": "para",
                    "text": chooser.rotate(
                        style["outlier"], key_base + ("outlier_frame",),
                        "wire_styles.outlier", offset,
                        {
                            "phrase": phrase,
                            "Phrase": _capitalized(phrase),
                            "answer": row["answers"][0],
                            "quote_city": city,
                            "quote_mayor": "the Mayor of %s" % city,
                        },
                    ),
                },
                # The sentence is the paper's, the quotation inside it is the
                # mayor's, and only one of the two is the paper's to police
                # (spec #30b).
                row["answers"][0],
            )
        )
        quoted += 1

    return blocks
