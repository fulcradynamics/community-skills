"""Spec #25's data side: what a round's answers actually add up to.

The newspaper phrases mayor answers "in clever aggregate ways" -- "the world",
"most nations", "some countries". The judged criterion attached to that (see
spec.md, Evaluation Criteria) is not whether the sentence *sounds* clever but
whether it is *true of the distribution it describes*: present-looking language
over an actually-wrong aggregate is a fail.

So the choice is made here, arithmetically, before any prose exists. This module
owns the numbers and the set of wordings those numbers license;
:mod:`newspaper.wire` owns the sentence it writes from them, and may use no
wording this module has not licensed. Nothing in here returns a sentence.

The rules are not invented here either. ``content/questions.json`` ships the
ladder -- ordered selection steps, tiers, the tie and fragmented cases, the
low-respondent floor, and the integrity rules -- and this module is the
implementation of that document, selected by
``config.facilitator_questions.aggregate_phrasing_ladder``. A conditional
wording carries a machine-checkable ``only_if_test`` alongside its English
``only_if``, evaluated against the actual counts, so "the world, with one
hold-out" cannot be used on a distribution with two hold-outs.

Two things this module deliberately does not do:

* **It does not cluster freeform answers.** Deciding that "the fish counter" and
  "the market" are the same answer is a judgement, not arithmetic. Until a
  clustering is supplied (``GameEngine.record_answer_buckets``), the report says
  so and offers no outcome -- rather than bucketing verbatim, which would
  manufacture a confident "no two nations agree" out of everyone phrasing the
  same answer differently.
* **It does not decide what the newspaper prints.** Whether the item is
  published at all is ``facilitator_questions.answers_shared_in_newspaper``,
  taken in one place: :func:`engine.views.newspaper_mayor_question`.
"""

import ast
from fractions import Fraction

from .errors import ContentError, RuleViolation

# -- outcome kinds ---------------------------------------------------------

TIER = "tier"
TIE_CASE = "tie_case"
FRAGMENTED_CASE = "fragmented_case"
LOW_RESPONDENT_FLOOR = "low_respondent_floor"
NO_RESPONSES = "no_responses"

# -- bucketing status ------------------------------------------------------

#: A clustering was supplied and the share arithmetic ran.
BUCKETING_SUPPLIED = "supplied"
#: Answers exist but nobody has clustered them, so no share can be measured.
BUCKETING_PENDING = "pending"
#: Too few answers for aggregate framing at all -- the floor needs no buckets.
BUCKETING_NOT_NEEDED = "not_needed"

# -- a bucket's part in the item -------------------------------------------

ROLE_HEADLINE = "headline"      # what the aggregate claim is about
ROLE_SUBGROUP = "subgroup"      # a non-leading bucket of 2 or more
ROLE_OUTLIER = "outlier"        # a bucket of exactly one
ROLE_UNMEASURED = "unmeasured"  # buckets exist but the outcome ignores shares

#: Variables an ``only_if_test`` may mention. R is respondents, ``largest`` the
#: size of the largest bucket, ``buckets`` how many buckets there are, ``tied``
#: how many buckets share the largest size.
PREDICATE_VARS = ("R", "largest", "buckets", "tied")


# -- only_if_test evaluation ----------------------------------------------

class Predicate:
    """A conditional phrase's guard, e.g. ``"R - largest == 1"``.

    Parsed at load time (a malformed guard is a content error, not a round-7
    surprise) and interpreted node by node rather than ``eval``-ed: the grammar
    is integers, the four names in :data:`PREDICATE_VARS`, ``+ - *``, the six
    comparisons, ``and``/``or``/``not``. Anything else is refused.
    """

    _COMPARE = {
        ast.Eq: lambda a, b: a == b,
        ast.NotEq: lambda a, b: a != b,
        ast.Lt: lambda a, b: a < b,
        ast.LtE: lambda a, b: a <= b,
        ast.Gt: lambda a, b: a > b,
        ast.GtE: lambda a, b: a >= b,
    }
    _BINOP = {
        ast.Add: lambda a, b: a + b,
        ast.Sub: lambda a, b: a - b,
        ast.Mult: lambda a, b: a * b,
    }

    def __init__(self, source):
        if not isinstance(source, str) or not source.strip():
            raise ContentError("an only_if_test must be a non-empty expression")
        self.source = source.strip()
        try:
            self._tree = ast.parse(self.source, mode="eval")
        except SyntaxError as exc:
            raise ContentError("only_if_test %r does not parse: %s" % (self.source, exc))
        self._check()

    def _check(self):
        """Every node legal, checked at load time -- not while evaluating.

        Validating during an evaluation would only reach the nodes that
        evaluation happens to visit: in ``1 == 2 == R.__class__`` the first
        comparison already settles the answer, and the attribute access behind it
        would never be looked at.
        """
        for node in ast.walk(self._tree):
            if isinstance(node, ast.Expression):
                continue
            if isinstance(node, ast.Constant):
                if isinstance(node.value, bool) or not isinstance(node.value, int):
                    raise ContentError(
                        "only_if_test %r may only use whole numbers, got %r"
                        % (self.source, node.value)
                    )
            elif isinstance(node, ast.Name):
                if node.id not in PREDICATE_VARS:
                    raise ContentError(
                        "only_if_test %r may only mention %s, got %r"
                        % (self.source, list(PREDICATE_VARS), node.id)
                    )
            elif isinstance(node, (ast.BinOp, ast.UnaryOp, ast.Compare, ast.BoolOp)):
                pass
            elif isinstance(node, (ast.Load, ast.And, ast.Or, ast.Not, ast.USub)):
                pass
            elif type(node) in self._BINOP or type(node) in self._COMPARE:
                pass
            else:
                raise ContentError(
                    "only_if_test %r uses %s, which this grammar does not allow"
                    % (self.source, type(node).__name__)
                )
        # A second pass with placeholder counts, so an operator this grammar
        # rejects inside an otherwise-legal shape (``R / largest``) is refused
        # here rather than at the first round that consults it.
        self._dispatch(self._tree.body, {name: 1 for name in PREDICATE_VARS})

    def holds(self, **counts):
        missing = set(PREDICATE_VARS) - set(counts)
        if missing:
            raise ContentError(
                "only_if_test %r needs %s" % (self.source, sorted(missing))
            )
        return bool(self._dispatch(self._tree.body, counts))

    def _dispatch(self, node, env):
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(node.value, int):
                raise ContentError(
                    "only_if_test %r may only use whole numbers, got %r"
                    % (self.source, node.value)
                )
            return node.value
        if isinstance(node, ast.Name):
            if node.id not in PREDICATE_VARS:
                raise ContentError(
                    "only_if_test %r may only mention %s, got %r"
                    % (self.source, list(PREDICATE_VARS), node.id)
                )
            return env[node.id]
        if isinstance(node, ast.BinOp) and type(node.op) in self._BINOP:
            return self._BINOP[type(node.op)](
                self._dispatch(node.left, env), self._dispatch(node.right, env)
            )
        if isinstance(node, ast.UnaryOp):
            if isinstance(node.op, ast.USub):
                return -self._dispatch(node.operand, env)
            if isinstance(node.op, ast.Not):
                return not self._dispatch(node.operand, env)
        if isinstance(node, ast.Compare):
            left = self._dispatch(node.left, env)
            for op, comparator in zip(node.ops, node.comparators):
                if type(op) not in self._COMPARE:
                    break
                right = self._dispatch(comparator, env)
                if not self._COMPARE[type(op)](left, right):
                    return False
                left = right
            else:
                return True
        if isinstance(node, ast.BoolOp):
            values = [self._dispatch(value, env) for value in node.values]
            return all(values) if isinstance(node.op, ast.And) else any(values)
        raise ContentError(
            "only_if_test %r uses %s, which this grammar does not allow"
            % (self.source, type(node).__name__)
        )

    def __repr__(self):
        return "Predicate(%r)" % self.source


def _phrases(node, where):
    phrases = node.get("phrases")
    if not isinstance(phrases, list) or not phrases:
        raise ContentError("%s must offer a non-empty phrases list" % where)
    for phrase in phrases:
        if not isinstance(phrase, str) or not phrase.strip():
            raise ContentError("%s has an empty phrase" % where)
    return list(phrases)


def _conditional_phrases(node, where):
    out = []
    for entry in node.get("conditional_phrases", []) or []:
        if not entry.get("phrase") or not entry.get("only_if"):
            raise ContentError("%s has a conditional phrase without phrase/only_if" % where)
        if not entry.get("only_if_test"):
            raise ContentError(
                "%s: conditional phrase %r has no only_if_test, so its guard cannot be "
                "checked against the counts. Every conditional wording needs a "
                "machine-checkable sibling to its English only_if."
                % (where, entry["phrase"])
            )
        out.append(
            {
                "phrase": entry["phrase"],
                "only_if": entry["only_if"],
                "predicate": Predicate(entry["only_if_test"]),
            }
        )
    return out


class _Case:
    """One selectable outcome: its wordings, and the guards on the sharper ones."""

    def __init__(self, kind, case_id, node, where):
        self.kind = kind
        self.id = case_id
        self.phrases = _phrases(node, where)
        self.conditional = _conditional_phrases(node, where)
        self.min_share = None
        self.min_respondents = None

    def licensed(self, counts):
        """The conditional wordings whose only_if actually holds of ``counts``."""
        return [
            {
                "phrase": entry["phrase"],
                "only_if": entry["only_if"],
                "only_if_test": entry["predicate"].source,
                "licensed": entry["predicate"].holds(**counts),
            }
            for entry in self.conditional
        ]


class _Tier(_Case):
    def __init__(self, node, where):
        for field in ("id", "min_share", "min_respondents"):
            if node.get(field) is None:
                raise ContentError("%s is missing %r" % (where, field))
        super().__init__(TIER, node["id"], node, where)
        # Fraction(str(...)) so 0.4 is exactly two fifths: a 2-of-5 distribution
        # sits exactly on the plurality floor and must not fall through it on a
        # binary rounding artefact.
        self.min_share = Fraction(str(node["min_share"]))
        self.min_respondents = int(node["min_respondents"])
        if not 0 < self.min_share <= 1:
            raise ContentError("%s: min_share must be in (0, 1]" % where)


class _Garnish:
    """subgroup_phrasing / outlier_phrasing -- never a headline (integrity rule)."""

    def __init__(self, node, where):
        if node.get("min_bucket_size") is None:
            raise ContentError("%s is missing min_bucket_size" % where)
        self.min_bucket_size = int(node["min_bucket_size"])
        self.phrases = _phrases(node, where)


class Ladder:
    """``content/questions.json``'s aggregate_phrasing ladder, made executable."""

    def __init__(self, ladder_id, data, integrity_rules=()):
        where = "aggregate_phrasing ladder %r" % ladder_id
        if not isinstance(data, dict):
            raise ContentError("%s must be an object" % where)
        selection = data.get("selection")
        if not isinstance(selection, dict):
            raise ContentError("%s has no selection block" % where)

        self.id = ladder_id
        self.steps = list(selection.get("steps", []))
        if not self.steps:
            raise ContentError("%s: selection.steps documents the order; it may not be empty" % where)
        self.min_respondents = selection.get("min_respondents_for_aggregate")
        if not isinstance(self.min_respondents, int) or self.min_respondents < 1:
            raise ContentError("%s: min_respondents_for_aggregate must be a positive int" % where)
        # Both sit on the ladder itself, not inside its selection block.
        self.measure = data.get("measure")
        self.denominator = data.get("denominator")
        if not self.measure or not self.denominator:
            raise ContentError(
                "%s must state its denominator and its measure -- an aggregate whose "
                "denominator is unstated cannot be checked against the answers" % where
            )

        tiers = data.get("tiers")
        if not isinstance(tiers, list) or not tiers:
            raise ContentError("%s has no tiers" % where)
        self.tiers = [_Tier(node, "%s tier %r" % (where, node.get("id"))) for node in tiers]
        previous = None
        for tier in self.tiers:
            if previous is not None and tier.min_share >= previous.min_share:
                raise ContentError(
                    "%s: tiers must be ordered by descending min_share -- the walk in "
                    "selection step 5 takes the first match, so an out-of-order tier "
                    "would silently shadow a stricter one (%s after %s)"
                    % (where, tier.id, previous.id)
                )
            if tier.min_respondents < self.min_respondents:
                raise ContentError(
                    "%s: tier %s declares min_respondents %d, below the aggregate floor "
                    "of %d. R >= %d is already guaranteed by step 2, so a lower value is "
                    "vestigial and misleading."
                    % (where, tier.id, tier.min_respondents, self.min_respondents,
                       self.min_respondents)
                )
            previous = tier
        floor_tier = self.tiers[-1]
        if floor_tier.min_respondents != self.min_respondents:
            raise ContentError(
                "%s: the lowest tier (%s) must accept every distribution that gets past "
                "step 2, so its min_respondents must equal min_respondents_for_aggregate "
                "(%d), else step 5's walk can end with no tier selected."
                % (where, floor_tier.id, self.min_respondents)
            )
        #: Below this share no bucket leads -- step 3's fragmented threshold,
        #: read off the lowest tier rather than restated as a literal.
        self.plurality_floor = floor_tier.min_share

        self.tie_case = _Case(TIE_CASE, TIE_CASE, self._require(data, "tie_case", where),
                              "%s tie_case" % where)
        self.fragmented_case = _Case(
            FRAGMENTED_CASE, FRAGMENTED_CASE, self._require(data, "fragmented_case", where),
            "%s fragmented_case" % where,
        )
        self.floor_case = _Case(
            LOW_RESPONDENT_FLOOR, LOW_RESPONDENT_FLOOR,
            self._require(selection, "low_respondent_floor", where),
            "%s low_respondent_floor" % where,
        )
        self.subgroup = _Garnish(
            self._require(data, "subgroup_phrasing", where), "%s subgroup_phrasing" % where
        )
        self.outlier = _Garnish(
            self._require(data, "outlier_phrasing", where), "%s outlier_phrasing" % where
        )
        if self.outlier.min_bucket_size >= self.subgroup.min_bucket_size:
            raise ContentError(
                "%s: outlier_phrasing is the bucket-of-one sibling of subgroup_phrasing, "
                "so its min_bucket_size (%d) must be smaller than subgroup's (%d)"
                % (where, self.outlier.min_bucket_size, self.subgroup.min_bucket_size)
            )
        self.integrity_rules = list(integrity_rules)

    @staticmethod
    def _require(node, key, where):
        value = node.get(key)
        if not isinstance(value, dict):
            raise ContentError("%s has no %s block" % (where, key))
        return value

    @classmethod
    def from_config(cls, config, content):
        """The ladder ``config.facilitator_questions.aggregate_phrasing_ladder`` names."""
        ladder_id = config.require_str("facilitator_questions.aggregate_phrasing_ladder")
        return cls(
            ladder_id,
            content.phrasing_ladder(ladder_id),
            content.phrasing_integrity_rules(),
        )

    # -- selection --------------------------------------------------------

    def select(self, respondents, largest, tied):
        """Steps 2-5, in the order content declares them. Exactly one outcome.

        Returns ``(case, selected_by)``. ``largest``/``tied`` are ignored when
        the respondent count alone decides it, which is why the floor can be
        reported before anyone has clustered the answers.
        """
        if respondents <= 0:
            return None, "no answers were given, so there is no distribution to describe"
        if respondents < self.min_respondents:
            return self.floor_case, (
                "step 2: %d respondent(s) is below min_respondents_for_aggregate=%d, so no "
                "aggregate framing" % (respondents, self.min_respondents)
            )
        share = Fraction(largest, respondents)
        if share < self.plurality_floor:
            return self.fragmented_case, (
                "step 3: largest share %s is below the plurality floor %s, so no bucket leads"
                % (share, self.plurality_floor)
            )
        if tied > 1:
            return self.tie_case, (
                "step 4: %d buckets tie for largest at %d each, so nothing leads" % (tied, largest)
            )
        for tier in self.tiers:
            if share >= tier.min_share and respondents >= tier.min_respondents:
                return tier, (
                    "step 5: share %s >= %s and R %d >= %d selects tier %s"
                    % (share, tier.min_share, respondents, tier.min_respondents, tier.id)
                )
        raise ContentError(  # unreachable while the ladder validates (see __init__)
            "ladder %r selected no outcome for R=%d largest=%d; the tier walk is not "
            "exhaustive" % (self.id, respondents, largest)
        )

    def describe(self):
        return {
            "id": self.id,
            "denominator": self.denominator,
            "measure": self.measure,
            "min_respondents_for_aggregate": self.min_respondents,
            "plurality_floor": _share_json(
                self.plurality_floor.numerator, self.plurality_floor.denominator
            ),
            "tiers": [tier.id for tier in self.tiers],
            # The steps themselves are not repeated into every edition's payload:
            # they live in content/questions.json, and each report says which one
            # fired in its own ``selection`` line.
            "selection_steps": "content/questions.json aggregate_phrasing.ladders.%s" % self.id,
        }


# -- bucketing -------------------------------------------------------------

def verbatim_buckets(answers_by_city):
    """Bucket by the answer text itself, case- and space-insensitively.

    Only honest for answers that are genuinely categorical (``coriander: yes``,
    ``phone or walk``). It is offered as an explicit opt-in for a caller who has
    looked at the answers, never as this module's default: applied to freeform
    answers it reports a fragmented world every time, which is a false claim
    about the distribution rather than a missing one.
    """
    return {city: " ".join(str(answer).casefold().split())
            for city, answer in answers_by_city.items()}


def _bucket_rows(answers_by_city, buckets_by_city):
    grouped = {}
    for city, answer in answers_by_city.items():
        grouped.setdefault(buckets_by_city[city], []).append((city, answer))
    rows = []
    for label, members in grouped.items():
        members.sort()
        rows.append(
            {
                "label": label,
                "size": len(members),
                "cities": [city for city, _ in members],
                "answers": [answer for _, answer in members],
            }
        )
    # Biggest first, then alphabetically: a stable order for a template to walk.
    rows.sort(key=lambda row: (-row["size"], row["label"]))
    return rows


def _share_json(numerator, denominator):
    frac = Fraction(numerator, denominator)
    return {
        "exact": "%d/%d" % (frac.numerator, frac.denominator),
        "approx": round(float(frac), 4),
        "percent": round(float(frac) * 100, 1),
    }


def validate_bucketing(answers_by_city, buckets_by_city):
    """Every respondent bucketed exactly once, and nobody else bucketed at all.

    A clustering that quietly drops a mayor changes the denominator, which
    changes the outcome -- so a partial clustering is refused rather than
    measured.
    """
    if not isinstance(buckets_by_city, dict):
        raise RuleViolation("a bucketing must be a mapping of city -> bucket label")
    missing = sorted(set(answers_by_city) - set(buckets_by_city))
    if missing:
        raise RuleViolation(
            "these cities answered but were not bucketed: %s. A clustering that drops a "
            "respondent moves the denominator and so changes the outcome (spec #25)."
            % missing
        )
    extra = sorted(set(buckets_by_city) - set(answers_by_city))
    if extra:
        raise RuleViolation(
            "these cities were bucketed but did not answer this round: %s. A silent mayor "
            "leaves the denominator; they are not a bucket of their own." % extra
        )
    for city, label in buckets_by_city.items():
        if not isinstance(label, str) or not label.strip():
            raise RuleViolation("bucket label for %s must be a non-empty string" % city)
    return {city: label.strip() for city, label in buckets_by_city.items()}


# -- the report ------------------------------------------------------------

def summarize(
    ladder, round_index, question, answers_by_city, buckets_by_city, asked_of,
    bucket_source=None,
):
    """The aggregate as data: distribution, outcome, and the wordings it licenses.

    ``answers_by_city`` is keyed by city, never by handle (spec #28), and this
    payload never touches the export/submission side of the game -- the two
    channels must not be cross-referenced (spec #21).
    """
    respondents = len(answers_by_city)
    report = {
        "round": round_index,
        "question_id": question["id"],
        "text": question["text"],
        "framing": question["framing"],
        "answer_shape": question.get("answer_shape"),
        "newspaper_hook": question.get("newspaper_hook"),
        "buckets_hint": question.get("buckets"),
        "aggregate_examples": question.get("aggregate_examples"),
        "ladder": ladder.describe(),
        # Answers keyed by city, never by handle (spec #28).
        "answers_by_city": dict(answers_by_city),
        "answered": respondents,
        "asked_of": asked_of,
        "silent": max(asked_of - respondents, 0),
    }

    rows = _bucket_rows(answers_by_city, buckets_by_city) if buckets_by_city is not None else []
    # Shares are only measured once there are enough answers to speak in
    # aggregate at all; below that the floor is selected on the count alone.
    measured = buckets_by_city is not None and respondents >= ladder.min_respondents
    largest = rows[0]["size"] if measured and rows else 0
    tied = sum(1 for row in rows if row["size"] == largest) if measured else 0
    counts = {"R": respondents, "largest": largest, "buckets": len(rows), "tied": tied}

    if buckets_by_city is None and respondents >= ladder.min_respondents:
        # Enough answers to need a share, and no clustering to compute one from.
        bucketing_status = BUCKETING_PENDING
        case, selected_by = None, (
            "no outcome: %d answers need a clustering before any share exists" % respondents
        )
    else:
        bucketing_status = (
            BUCKETING_SUPPLIED if buckets_by_city is not None else BUCKETING_NOT_NEEDED
        )
        case, selected_by = ladder.select(respondents, largest=largest, tied=tied)

    report["measure"] = (
        {
            "largest_bucket_size": largest,
            "share": _share_json(largest, respondents),
            "largest_is_tied": tied > 1,
            "tied_buckets": tied,
            "bucket_count": len(rows),
            "denominator": "respondents (%d), not all mayors (%d)" % (respondents, asked_of),
        }
        if measured
        else None
    )

    report["bucketing"] = {
        "status": bucketing_status,
        "source": bucket_source,
        "clustering_hint": question.get("buckets"),
        "note": {
            BUCKETING_SUPPLIED: "clustered; the share arithmetic below ran on these buckets",
            BUCKETING_NOT_NEEDED: "too few answers for aggregate framing, which needs no "
                                  "clustering (selection step 2)",
            BUCKETING_PENDING: "answers are not clustered yet, so no share can be measured. "
                               "Call GameEngine.record_answer_buckets before writing the "
                               "item; the engine will not guess a distribution.",
        }[bucketing_status],
    }
    report["buckets"] = _with_roles(rows, case, largest, measured)

    # Always present, including when nothing was selected: the reason an item
    # cannot be written is as much a part of the report as the outcome would be.
    report["selection"] = selected_by
    if case is None:
        # Either nobody answered, or nobody has clustered the answers yet.
        # Both are reported as "no item to write", not as a fragmented world.
        report["outcome"] = None
        report["reportable"] = False
        report["no_item_reason"] = (
            BUCKETING_PENDING if bucketing_status == BUCKETING_PENDING else NO_RESPONSES
        )
    else:
        report["outcome"] = {
            "kind": case.kind,
            "id": case.id,
            "phrases": list(case.phrases),
            "conditional_phrases": case.licensed(counts),
            "min_share": (
                None if case.min_share is None
                else _share_json(case.min_share.numerator, case.min_share.denominator)
            ),
        }
        report["reportable"] = True

    report["garnishes"] = _garnishes(ladder, report["buckets"])
    report["integrity"] = {
        # Integrity rule: an aggregate over some of the mayors must say so.
        "must_disclose_partial_response": respondents < asked_of,
        "rules": list(ladder.integrity_rules),
    }
    report["written_by"] = (
        "newspaper.wire: no item to write this round -- %s" % report["no_item_reason"]
        if report["outcome"] is None
        else "newspaper.wire: write this item in the register of outcome %r, using one "
             "of its licensed phrases; the aggregate itself is already decided here "
             "(spec #25)" % report["outcome"]["id"]
    )
    return report


def _with_roles(rows, case, largest, measured):
    out = []
    for row in rows:
        row = dict(row)
        if not measured or case is None:
            row["role"] = ROLE_UNMEASURED
        elif case.kind == TIER and row["size"] == largest:
            row["role"] = ROLE_HEADLINE
        elif case.kind == TIE_CASE and row["size"] == largest:
            row["role"] = ROLE_HEADLINE
        elif row["size"] == 1:
            row["role"] = ROLE_OUTLIER
        else:
            row["role"] = ROLE_SUBGROUP
        out.append(row)
    return out


def _garnishes(ladder, rows):
    """Wordings for the buckets that are not the headline (selection step 6).

    Garnishes, never headlines: the claim belongs to whatever steps 2-5 chose.
    """
    subgroups = [row for row in rows if row["role"] == ROLE_SUBGROUP
                 and row["size"] >= ladder.subgroup.min_bucket_size]
    outliers = [row for row in rows if row["role"] == ROLE_OUTLIER
                and row["size"] >= ladder.outlier.min_bucket_size]
    out = {}
    if subgroups:
        out["subgroup"] = {
            "phrases": list(ladder.subgroup.phrases),
            "buckets": [row["label"] for row in subgroups],
        }
    if outliers:
        out["outlier"] = {
            "phrases": list(ladder.outlier.phrases),
            "buckets": [row["label"] for row in outliers],
        }
    out["note"] = "garnishes only -- a bucket that did not lead never gets the headline"
    return out
