"""Loading and drawing from the seeded game content (spec #13, #14, #33).

The content itself (import needs, gazetteer, mayor questions) was produced in
M1 and lives in ``content/``. This module only loads it and implements the
*draw* rules: which needs a given city is still eligible to receive, and which
questions have not been asked yet.

File locations come from config.json (``content.*_file``) -- the engine does not
know the paths.
"""

import json
import os
import unicodedata

from .config import repo_root
from .errors import ConfigError, ContentError, NoEligibleImportNeed
from .trade import TradePolicy

SOURCE_SEED = "seed"
SOURCE_PLAYER = "player"

#: What ``config.facilitator_questions.framing`` permits a question to be.
#:
#: Spec #24 requires v1's questions to be framed as questions *to or about "the
#: mayor"* -- the persona, never the person behind it -- and says the framing is
#: configurable for a future domain-specific run. So the config key names a
#: *mode*, and a mode says which per-question ``framing`` values are legal. A
#: mode this table does not know is refused rather than treated as "anything
#: goes": that is how an unnoticed typo in config.json would quietly switch off
#: the one requirement this key exists to enforce.
FRAMING_MODES = {
    "questions_to_about_the_mayor": ("to_the_mayor", "about_the_mayor"),
}


def normalize_city(name):
    """Fold a city name to a comparison key, per gazetteer.resolution_rules.

    Case-folded, trimmed, diacritics stripped, internal whitespace collapsed.
    A parenthetical qualifier is *kept* -- "Athens (Georgia)" and "Athens" are
    deliberately different keys, because treating them as one puts a mayor on
    the wrong continent.
    """
    if not isinstance(name, str) or not name.strip():
        raise ValueError("city name must be a non-empty string, got %r" % (name,))
    decomposed = unicodedata.normalize("NFKD", name)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(stripped.casefold().split())


def _read_json(path, what):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        raise ContentError("%s not found at %s" % (what, path))
    except ValueError as exc:
        raise ContentError("%s at %s is not valid JSON: %s" % (what, path, exc))


class Content:
    """The seeded content, plus anything players added during play."""

    def __init__(self, needs, categories, questions, gazetteer, root, question_doc=None,
                 trade_policy=None):
        self.needs = list(needs)
        self.categories = {c["id"]: c for c in categories}
        self.questions = list(questions)
        self.gazetteer = gazetteer
        self.root = root
        #: Spec #13a's rule about what may be ordered. Content, not code -- see
        #: :mod:`engine.trade`. Every need in this object has passed it, whether
        #: it was seeded, suggested by a player, or written freehand by an
        #: importing mayor.
        self.trade = TradePolicy(trade_policy)
        #: The whole questions document. The engine needs more of it than the
        #: question list -- the aggregate phrasing ladder (spec #25) lives here
        #: too, and is content, not code.
        self.question_doc = question_doc or {"questions": self.questions}
        self._validate()

    @classmethod
    def load(cls, config, root=None):
        root = root or repo_root()
        needs_doc = _read_json(
            os.path.join(root, config.require_str("content.import_needs_file")),
            "import needs",
        )
        gaz_doc = _read_json(
            os.path.join(root, config.require_str("content.gazetteer_file")), "gazetteer"
        )
        q_doc = _read_json(
            os.path.join(root, config.require_str("content.questions_file")), "questions"
        )
        expected_set = config.require_str("content.question_set_id")
        if q_doc.get("set_id") != expected_set:
            raise ContentError(
                "questions file declares set_id %r but config.content.question_set_id "
                "is %r" % (q_doc.get("set_id"), expected_set)
            )
        content = cls(
            needs=needs_doc.get("needs", []),
            categories=needs_doc.get("categories", []),
            questions=q_doc.get("questions", []),
            gazetteer=gaz_doc,
            root=root,
            question_doc=q_doc,
            trade_policy=needs_doc.get("trade_policy"),
        )
        # Checked at load, so a question bank that does not match the configured
        # scope or framing refuses to start a game rather than being discovered
        # in round 3, when the aggregate it feeds is already half-built.
        content.check_question_policy(config)
        return content

    def _validate(self):
        if not self.needs:
            raise ContentError("import-need list is empty; spec #13 needs a seeded list")
        if not self.questions:
            raise ContentError("question bank is empty; spec #24 needs a seeded set")
        seen = set()
        for need in self.needs:
            for field in ("id", "category", "need_brief", "exporter_prompt"):
                if not need.get(field):
                    raise ContentError("import need %r is missing %r" % (need.get("id"), field))
            if need["id"] in seen:
                raise ContentError("duplicate import-need id %r" % need["id"])
            seen.add(need["id"])
            if need["category"] not in self.categories:
                raise ContentError(
                    "import need %r references unknown category %r"
                    % (need["id"], need["category"])
                )
            # Spec #13a, at the door where the seeded list comes in. A seed that
            # asks for advice rather than for goods refuses to start a game --
            # which is the only moment at which finding out is cheap.
            self.trade.check_need(need, where="import need %r" % need["id"])
        q_seen = set()
        for question in self.questions:
            if not question.get("id") or not question.get("text"):
                raise ContentError("question %r is missing id/text" % (question.get("id"),))
            if question["id"] in q_seen:
                raise ContentError("duplicate question id %r" % question["id"])
            q_seen.add(question["id"])

    # -- import needs -----------------------------------------------------

    def add_need(self, need):
        """Add one need to the pool, checked (spec #13, #13a, #33).

        The pool a mayor orders from is the pool players extend, so a
        player-suggested need and an importing mayor's freeform order come in
        through the same door and meet the same validation -- including spec
        #13a's trade policy, via :meth:`_validate`.
        """
        if not isinstance(need, dict) or not need.get("id"):
            raise ContentError("an import need is a mapping with an id; got %r" % (need,))
        if any(existing["id"] == need["id"] for existing in self.needs):
            raise ContentError("import-need id %r already exists" % need["id"])
        if need.get("category") not in self.categories:
            raise ContentError(
                "import need %r must use a known category; got %r"
                % (need["id"], need.get("category"))
            )
        self.needs.append(need)
        self._validate()
        return need

    def add_player_need(self, need):
        """Append a player-suggested need (spec #13, #33).

        Checked against spec #13a's trade policy by :meth:`_validate` like every
        other need in the pool: the list players extend is the list mayors order
        from, so it obeys the same rule.
        """
        need = dict(need)
        need.setdefault("source", SOURCE_PLAYER)
        return self.add_need(need)

    def eligible_needs(
        self,
        used_need_ids,
        categories_used_by_city,
        categories_used_anywhere,
        allow_repeat_for_same_city,
        allow_repeat_across_cities,
        allow_need_reuse,
    ):
        """Needs a city may still be given, per spec #14 and its config knobs.

        ``categories_used_by_city`` is the set of categories that *this* city has
        already imported. ``categories_used_anywhere`` is every category drawn so
        far in the game -- only consulted when config forbids cross-city repeats.
        """
        out = []
        for need in self.needs:
            if not allow_need_reuse and need["id"] in used_need_ids:
                continue
            category = need["category"]
            if not allow_repeat_for_same_city and category in categories_used_by_city:
                continue
            if not allow_repeat_across_cities and category in categories_used_anywhere:
                continue
            out.append(need)
        return out

    def suggest_needs(self, rng, city, count, **rules):
        """A slate of eligible seeds to put in front of an importing mayor (#13).

        There is deliberately no ``draw_need`` beside this. Spec #13 (user
        decision, 2026-08-31) replaced the hidden random draw with the importing
        mayor's own choice, and the way to be sure a city can never receive a
        need nobody picked is for the engine to own no function that picks one.
        What the randomness decides now is only *which eligible seeds get shown*
        -- the mayor may take any of them, take an eligible seed that is not on
        the slate, or file a freeform order instead.

        The slate spreads across categories before it doubles up on one, so a
        mayor is offered a choice rather than three shades of the same thing.
        """
        if count < 1:
            raise ConfigError(
                "config.imports.suggestions_offered_to_importer must be at least 1; "
                "spec #13 requires a small set of eligible suggestions"
            )
        candidates = self.eligible_needs(**rules)
        if not candidates:
            raise NoEligibleImportNeed(
                "no import need left for %s under the current repetition rules "
                "(spec #14 / config.imports)" % city
            )
        # Sorted first so the slate depends only on the seed, never on dict or
        # file ordering that a content edit could quietly change.
        candidates.sort(key=lambda n: n["id"])
        rng.shuffle(candidates)
        slate, seen_categories, spares = [], set(), []
        for need in candidates:
            if need["category"] in seen_categories:
                spares.append(need)
                continue
            seen_categories.add(need["category"])
            slate.append(need)
            if len(slate) == count:
                return slate
        return (slate + spares)[:count]

    def need_by_id(self, need_id):
        for need in self.needs:
            if need["id"] == need_id:
                return need
        raise ContentError("unknown import need %r" % need_id)

    def render_need(self, need, city):
        """Substitute the declared placeholders (content/import_needs.json)."""
        def sub(text):
            return (text or "").replace("{city}", city).replace("{mayor}", "the Mayor of %s" % city)

        return {
            "title": need.get("title", ""),
            "need_brief": sub(need.get("need_brief")),
            "exporter_prompt": sub(need.get("exporter_prompt")),
        }

    # -- questions --------------------------------------------------------

    def check_question_policy(self, config):
        """The question bank must match what config.json asks for (spec #23-#25).

        Three things, none of which the engine may decide for itself:

        * ``facilitator_questions.scope`` -- v1 is freeform getting-to-know-you
          (spec #24) and a later domain-specific run points config at a
          different bank. Pointing it at a bank of the wrong scope is a
          misconfiguration, not a silent downgrade.
        * ``facilitator_questions.framing`` -- names a mode in
          :data:`FRAMING_MODES`; every question must declare one of the framings
          that mode allows, so spec #24's "to/about the mayor" is checked over
          the whole bank rather than trusted per question.
        * every question actually declares a framing. There is no default: a
          question with no framing would silently inherit one, which is how an
          unframed question ends up addressed to the person rather than the
          persona.
        """
        scope = config.require_str("facilitator_questions.scope")
        declared = self.question_doc.get("scope")
        if declared != scope:
            raise ContentError(
                "questions file declares scope %r but config.facilitator_questions.scope "
                "is %r; point config at a bank of the right scope rather than reusing "
                "this one (spec #24)" % (declared, scope)
            )
        mode = config.require_str("facilitator_questions.framing")
        try:
            allowed = FRAMING_MODES[mode]
        except KeyError:
            raise ConfigError(
                "config.facilitator_questions.framing is %r; known modes are %s"
                % (mode, sorted(FRAMING_MODES))
            )
        for question in self.questions:
            framing = question.get("framing")
            if framing not in allowed:
                raise ContentError(
                    "question %r is framed %r; config.facilitator_questions.framing=%r "
                    "allows only %s -- spec #24 requires questions to/about the mayor, "
                    "never to the person behind them"
                    % (question["id"], framing, mode, list(allowed))
                )
        return True

    def phrasing_ladder(self, ladder_id):
        """One aggregate-phrasing ladder from the questions file (spec #25).

        Returned raw; :class:`engine.aggregate.Ladder` is what validates and
        executes it. The ladder is content -- the wordings and the thresholds are
        writing decisions -- so it lives here and not in code.
        """
        ladders = (self.question_doc.get("aggregate_phrasing") or {}).get("ladders") or {}
        try:
            return ladders[ladder_id]
        except KeyError:
            raise ContentError(
                "config.facilitator_questions.aggregate_phrasing_ladder names %r, but "
                "%s ships ladders %s"
                % (ladder_id, self.question_doc.get("set_id"), sorted(ladders))
            )

    def phrasing_integrity_rules(self):
        """The rules a written aggregate item must not break (spec #25, #30)."""
        return list((self.question_doc.get("aggregate_phrasing") or {}).get(
            "integrity_rules", []
        ))

    def asking_rules(self):
        """The content-side rules the check-in and the aggregate implement."""
        return list((self.question_doc.get("asking_rules") or {}).get("rules", []))

    def draw_question(self, rng, asked_ids):
        """One unasked question (content/questions.json asking_rules)."""
        remaining = sorted(
            (q for q in self.questions if q["id"] not in asked_ids), key=lambda q: q["id"]
        )
        if not remaining:
            return None
        return rng.choice(remaining)

    def question_by_id(self, question_id):
        for question in self.questions:
            if question["id"] == question_id:
                return question
        raise ContentError("unknown question %r" % question_id)

    # -- gazetteer --------------------------------------------------------

    def gazetteer_entry(self, city):
        key = normalize_city(city)
        for entry in self.gazetteer.get("cities", []):
            if normalize_city(entry["name"]) == key:
                return entry
            if any(normalize_city(alias) == key for alias in entry.get("aliases", [])):
                return entry
        return None

    def nearby_names(self, city):
        entry = self.gazetteer_entry(city)
        return list(entry.get("nearby", [])) if entry else []
