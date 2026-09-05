"""One completed round, published, without anybody asking (spec #26).

See :mod:`facilitator` for why this is not a script.
"""

import os

import hosting
from engine import views
from engine.config import repo_root
from engine.errors import ConfigError
from hosting import identity as identity_module
from newspaper.copy import Chooser
from newspaper.edition import Paper
from newspaper.publish import publish_round

#: The steps a completed-round transaction may name, in the order they must run.
#: ``config.facilitator.completed_round_transaction`` chooses among these; it may
#: not reorder them (publishing before rendering is not a preference) and it may
#: not drop the ones spec #26 requires -- see :func:`resolve_steps`.
TRANSACTION_STEPS = ("render_edition", "publish_editions", "build_site", "notify_group")

#: Stands in for the paper's address while a notice is being written, and is
#: replaced by the real one at the end. No full stops in it, on purpose: see
#: :meth:`Facilitator.notify`.
ADDRESS_SENTINEL = "PAPER-ADDRESS-HERE"

#: The three spec #26 asks for by name: an edition is rendered, it is published,
#: and the group is told. ``build_site`` is the only optional one, and only
#: because ``config.hosting.enabled`` already governs whether this deployment
#: serves a site at all.
REQUIRED_STEPS = ("render_edition", "publish_editions", "notify_group")


def resolve_steps(config):
    """The transaction's steps, in canonical order, checked against spec #26."""
    declared = config.require("facilitator.completed_round_transaction")
    if not isinstance(declared, list) or not declared:
        raise ConfigError(
            "config.facilitator.completed_round_transaction must be a non-empty list "
            "of %s" % list(TRANSACTION_STEPS)
        )
    unknown = [step for step in declared if step not in TRANSACTION_STEPS]
    if unknown:
        raise ConfigError(
            "config.facilitator.completed_round_transaction names %s; the steps this "
            "desk can run are %s" % (unknown, list(TRANSACTION_STEPS))
        )
    missing = [step for step in REQUIRED_STEPS if step not in declared]
    if missing:
        # config.json is the single source for every *parameter* the spec calls
        # configurable. Whether a completed round produces an edition and a
        # notice is not one of those -- it is the requirement itself (spec #26),
        # and the same carve-out hosting.guard makes for the leak checks.
        raise ConfigError(
            "config.facilitator.completed_round_transaction is missing %s. Spec #26 "
            "requires that every completed round automatically produces one redacted "
            "edition and a notice that it is available; these steps are not "
            "switchable." % missing
        )
    return [step for step in TRANSACTION_STEPS if step in declared]


class Notice:
    """What the group is told, and what may be written down about it.

    Deliberately not a string, for the same reason
    :class:`hosting.identity.SiteIdentity` is not: the text contains the
    paper's address, the address is the paper's only credential, and a type
    whose ``text`` is secret and whose :meth:`describe` is not makes every call
    site state which one it meant.
    """

    __slots__ = ("text", "round", "kind", "channel", "carries_url", "url")

    def __init__(self, text, round_index, kind, channel, url=None):
        self.text = text
        self.round = round_index
        self.kind = kind
        self.channel = channel
        self.url = url
        self.carries_url = url is not None and url in text

    def describe(self):
        """The notice with the address taken out, for anything persisted."""
        text = self.text
        if self.url:
            text = text.replace(self.url, "<the paper's private address>")
        return {
            "round": self.round,
            "kind": self.kind,
            "channel": self.channel,
            "text": text,
            "carries_url": self.carries_url,
            "address_withheld": True,
            "spec": "#26",
        }

    def __repr__(self):
        return "Notice(round=%s, kind=%s, address withheld)" % (self.round, self.kind)


class RoundTransaction:
    """The receipt for one completed round: what ran, and what it produced."""

    __slots__ = ("round", "steps", "edition", "published", "site", "notice", "ended")

    def __init__(self, round_index, steps):
        self.round = round_index
        self.steps = list(steps)
        self.edition = None
        self.published = None
        self.site = None
        self.notice = None
        self.ended = False

    def describe(self):
        """A record safe to write to disk -- no address, no player identity."""
        published = self.published or {}
        site = self.site or {}
        return {
            "round": self.round,
            "steps": list(self.steps),
            "edition": {
                "round": self.round,
                "departments": [d["id"] for d in (self.edition or {}).get("departments", [])],
                "image": ((self.edition or {}).get("image") or {}).get("filename"),
            },
            "editions_written": [published.get("edition", {}).get("round")],
            "final_edition_written": bool(published.get("final")),
            "site": {
                "published": site.get("published", False),
                "rounds": site.get("rounds"),
                "address": (site.get("address") or {}).get("url_style"),
            },
            "notice": None if self.notice is None else self.notice.describe(),
            "game_ended": self.ended,
            "spec": "#26, #27, #31",
        }


class Facilitator:
    """The desk that turns "a round finished" into "the paper is out"."""

    def __init__(self, game, editions_dir=None, site_dir=None, label=None,
                 paper=None, identity=None, root=None, publish=True):
        self.game = game
        self.config = game.config
        self.root = root or repo_root()
        self.paper = paper or Paper(game)
        self.copy = self.paper.copy
        self.chooser = self.paper.chooser
        self.steps = resolve_steps(self.config)
        self.label = label if label is not None else self.config.require_str(
            "facilitator.editions_label"
        )
        self.editions_dir = editions_dir
        self.site_dir = site_dir if site_dir is not None else os.path.join(
            self.root, self.config.require_str("hosting.site_dir")
        )
        # Resolved now rather than at the end of round 1: minting the paper's
        # address is the kind of thing that should fail while somebody is still
        # setting up, not while a round is closing.
        self.identity = identity or identity_module.load_or_create(
            self.config, root=self.root
        )
        self.notice_channel = self.config.require_str("facilitator.notice.channel")
        self.notice_includes_url = self.config.require_bool(
            "facilitator.notice.include_url"
        )
        self.publish_enabled = publish
        self.transactions = []
        self.notices = []

    # -- attachment --------------------------------------------------------

    @classmethod
    def attach(cls, game, **kwargs):
        """Build a desk and hang it on the game's round-completed hook (#26).

        The whole of "automatically" is this line. After it, no caller has to
        remember to publish anything: rounds end, editions come out.
        """
        desk = cls(game, **kwargs)
        game.on_round_completed(desk.on_round_completed)
        return desk

    def on_round_completed(self, game, round_index):
        return self.run(round_index)

    # -- the transaction ---------------------------------------------------

    def run(self, round_index):
        """Render, publish, build and announce one completed round."""
        record = self.game.rounds[round_index]
        if not record.completed and self.game._completing_round != round_index:
            raise ConfigError(
                "round %d has not finished; an edition printed from a live round "
                "would say something different an hour later (spec #26)" % round_index
            )
        transaction = RoundTransaction(round_index, self.steps)
        transaction.ended = self.game.phase == "ended"

        for step in self.steps:
            if step == "render_edition":
                # Paper.edition is also the gate: it refuses to return an
                # edition that leaks an exporter or trips the tone register.
                transaction.edition = self.paper.edition(round_index)
            elif step == "publish_editions" and self.publish_enabled:
                transaction.published = publish_round(
                    self.game, round_index, label=self.label,
                    out_dir=self.editions_dir, paper=self.paper,
                    edition=transaction.edition,
                )
            elif step == "build_site" and self.publish_enabled:
                transaction.site = hosting.build_site(
                    self.game, out_dir=self.site_dir, paper=self.paper,
                    identity=self.identity, root=self.root,
                )
            elif step == "notify_group":
                transaction.notice = self.notify(round_index, transaction)

        self.transactions.append(transaction)
        return transaction

    # -- the notice --------------------------------------------------------

    def notify(self, round_index, transaction=None):
        """Tell the group the edition is available (spec #26).

        Written from the same content file as the paper, and returned rather
        than sent: this desk knows what to say and deliberately does not know
        what the group's inbox is. The facilitator's agent posts
        ``notice.text``; anything that gets written down uses
        ``notice.describe()``, which is the same sentence with the address
        taken out.
        """
        bulletin = self.copy.bulletin()
        masthead = self.paper.masthead
        ended = bool(transaction and transaction.ended)
        url = self.identity.url() if self.notice_includes_url else None
        values = {
            "publication": masthead["publication"],
            "game": masthead["game"],
            "round": round_index,
            "lede": self._lede(round_index),
        }
        if ended:
            frames = bulletin["final_notice" if url else "final_notice_without_url"]
            where = "bulletin.final_notice"
            values.pop("lede")
        else:
            frames = bulletin["round_notice" if url else "round_notice_without_url"]
            where = "bulletin.round_notice"
        if url:
            # Substituted *after* the copy machinery has finished with the
            # sentence. ``Chooser.line`` sentence-cases what it fills, and an
            # address is full of full stops -- it came back as
            # "sister-cities.News", which is a broken link and, worse, an
            # address that no longer matches the string Notice.describe()
            # redacts. The paper writes the sentence; the address is pasted in.
            values["url"] = ADDRESS_SENTINEL
        text = self.chooser.line(frames, (round_index, "notice"), where, values)
        if url:
            text = text.replace(ADDRESS_SENTINEL, url)
        notice = Notice(
            text, round_index, "final" if ended else "round", self.notice_channel, url
        )
        self.notices.append(notice)
        return notice

    def _lede(self, round_index):
        """One sentence about what this round's paper leads on.

        Read from :mod:`engine.views`, like everything else that looks at a
        game from outside: an opened notice is public (its city and its order
        are on the front page), and nothing else about the round is quoted here.
        """
        bulletin = self.copy.bulletin()
        briefing = views.round_briefing(self.game, round_index)
        opened = briefing.get("opened")
        if not opened:
            return self.chooser.line(
                bulletin["quiet_lede"], (round_index, "quiet"), "bulletin.quiet_lede"
            )
        return self.chooser.line(
            bulletin["opened_lede"], (round_index, "lede"), "bulletin.opened_lede",
            {"city": opened["importing_city"], "title": opened["title"]},
        )

    # -- reporting ---------------------------------------------------------

    def describe(self):
        """Everything this desk did, in a form safe to commit."""
        return {
            "label": self.label,
            "steps": list(self.steps),
            "rounds_published": [t.round for t in self.transactions],
            "transactions": [t.describe() for t in self.transactions],
            "notice_channel": self.notice_channel,
            "address": self.identity.describe(),
            "spec": "#26, #27",
        }
