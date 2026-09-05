"""What may be published, stated file by file before anything is written.

The milestone this module exists for is graded on "only intentionally curated
public files are published (no inboxes, raw verdicts, credentials, or private
repo data)". There are two ways to build a static site and only one of them can
be graded that way:

* copy a directory and hope nothing private is in it -- the set of published
  files is then whatever happened to be on disk, and the answer to "why is this
  public?" is "it was in the folder";
* declare each file, its category, where it came from and why it is public, and
  then write **exactly** that set -- the answer to "why is this public?" is a
  field, and a file with no answer cannot be written because nothing put it in
  the list.

This module is the second one. :class:`PublicationManifest` is built in memory,
checked by :mod:`hosting.guard`, and only then does :mod:`hosting.build` write
it out; afterwards the public root is compared against it again, so a stray file
from an earlier build is a failure rather than a leak. The server then serves
*the manifest* rather than the directory (:mod:`hosting.serve`), which is what
makes path traversal structurally impossible rather than merely handled.

The manifest itself is not published. It lives beside the public root, not in
it: it is the audit record of a publication decision, and an audit record is a
facilitator's document.
"""

import hashlib
import json

from engine.errors import ConfigError

#: Every kind of thing this paper is willing to put on the open web, and the
#: reason it is public. ``hosting.publish`` names which of these a given game
#: actually publishes; a name not in here is a config error rather than an
#: unrecognised-and-therefore-ignored entry, because "I typo'd the category and
#: it silently stopped publishing the archive" and "I typo'd the category and it
#: silently published something else" are both worse than a refusal to build.
CATEGORIES = {
    "front_page": "the file the paper's one address answers with: the newest "
                  "available edition, so a link handed out in round one opens "
                  "today's paper (spec #26, #30a). The same issue keeps its own "
                  "permanent page under 'editions' or 'final_edition'; this is a "
                  "second rendering of it, not its only home (spec #27)",
    "archive_index": "the shelf -- every edition ever printed, listed at one page "
                     "that the front door and every issue link back to (spec #27, "
                     "#30a)",
    "editions": "one page per published round, kept forever and never overwritten "
                "by a later one (spec #27)",
    "edition_images": "the one generated image each edition carries (spec #29)",
    "final_edition": "the last edition -- the crown, the twist article and the "
                     "per-city portraits, published once when the game ends and "
                     "then kept like any other issue (spec #31, #32, #27)",
    "city_images": "one portrait per city in the last edition, drawn from that "
                   "city's own history (spec #32)",
    "archive_json": "the same curated editions in machine-readable form, for a "
                    "reader that is not a browser",
    "stylesheet": "presentation only; carries no game state",
    "robots": "the crawler exclusion that keeps the address non-discoverable "
              "(spec #26)",
}

#: Content types, by extension. An extension not listed here cannot be published:
#: the server serves what the manifest says and nothing may go out with a guessed
#: or absent type.
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
}


#: The key an edition's rendered bytes are filed under while a build is in
#: progress. Rounds are unique among round editions, but the final edition is
#: published in the last round and would collide with that round's own edition
#: (spec #31), so it gets a key of its own. Defined here rather than in either
#: caller because :mod:`hosting.build` writes the mapping and
#: :mod:`hosting.guard` reads it, and a key computed two ways is a key that will
#: eventually disagree with itself.
FINAL_EDITION_KEY = "final"


def edition_key(edition):
    """How :mod:`hosting.build` and :mod:`hosting.guard` refer to one edition."""
    return FINAL_EDITION_KEY if edition.get("endgame") else edition["round"]


def resolve_categories(config):
    """The categories this game publishes, in config order.

    Read from ``hosting.publish`` -- the curated allowlist. Returned as a dict
    of category to reason so the caller can put the reason in the manifest
    rather than restating it.
    """
    declared = config.require("hosting.publish")
    if not isinstance(declared, list) or not declared:
        raise ConfigError(
            "config.hosting.publish must be a non-empty list naming which of %s "
            "this game publishes" % sorted(CATEGORIES)
        )
    unknown = [name for name in declared if name not in CATEGORIES]
    if unknown:
        raise ConfigError(
            "config.hosting.publish names %s; publishable categories are %s. A "
            "category this build does not know about is refused rather than "
            "ignored." % (unknown, sorted(CATEGORIES))
        )
    return {name: CATEGORIES[name] for name in declared}


def content_type_for(path):
    for extension, value in CONTENT_TYPES.items():
        if path.endswith(extension):
            return value
    raise ConfigError(
        "no content type for %r; publishable extensions are %s"
        % (path, sorted(CONTENT_TYPES))
    )


class PublicFile:
    """One file, and the four things that have to be true before it ships.

    ``category`` -- which curated kind it is, checked against
    ``hosting.publish``. ``source`` -- what in this repo it was derived from,
    checked against :data:`hosting.guard.DENY_SOURCES`. ``why_public`` -- the
    sentence somebody would have to write to justify it, written up front rather
    than reconstructed at review time. ``content`` -- the bytes themselves,
    which are then scanned.
    """

    __slots__ = ("path", "category", "source", "why_public", "content", "round")

    def __init__(self, path, category, source, why_public, content, round=None):
        if "/" in path or path.startswith("."):
            raise ConfigError(
                "published file %r must be a plain name in the public root: the "
                "tree is flat so that a path can never mean a directory that was "
                "not curated" % path
            )
        if category not in CATEGORIES:
            raise ConfigError("published file %r has unknown category %r" % (path, category))
        self.path = path
        self.category = category
        self.source = source
        self.why_public = why_public
        self.content = content
        self.round = round

    @property
    def data(self):
        """The bytes as they will be written."""
        return self.content.encode("utf-8") if isinstance(self.content, str) else self.content

    @property
    def text(self):
        """The bytes as text, for scanning. Empty for anything undecodable."""
        if isinstance(self.content, str):
            return self.content
        try:
            return self.content.decode("utf-8")
        except UnicodeDecodeError:  # pragma: no cover - nothing binary is published yet
            return ""

    @property
    def content_type(self):
        return content_type_for(self.path)

    @property
    def sha256(self):
        return hashlib.sha256(self.data).hexdigest()

    def to_json(self):
        entry = {
            "path": self.path,
            "category": self.category,
            "source": self.source,
            "why_public": self.why_public,
            "content_type": self.content_type,
            "bytes": len(self.data),
            "sha256": self.sha256,
        }
        if self.round is not None:
            entry["round"] = self.round
        return entry


class PublicationManifest:
    """The complete, ordered list of what this publication puts on the web."""

    def __init__(self, publication, game, identity, categories, public_root):
        self.publication = publication
        self.game = game
        self.identity = identity
        self.categories = categories
        self.public_root = public_root
        self.files = []

    def add(self, public_file):
        if public_file.path in self.paths():
            raise ConfigError(
                "two files claim the path %r; an edition would be overwriting "
                "another edition (spec #27)" % public_file.path
            )
        if public_file.category not in self.categories:
            raise ConfigError(
                "%r is category %r, which config.hosting.publish does not include (%s)"
                % (public_file.path, public_file.category, sorted(self.categories))
            )
        self.files.append(public_file)
        return public_file

    def paths(self):
        return [entry.path for entry in self.files]

    def by_category(self, category):
        return [entry for entry in self.files if entry.category == category]

    def published_rounds(self):
        return sorted({entry.round for entry in self.files if entry.round is not None})

    def get(self, path):
        for entry in self.files:
            if entry.path == path:
                return entry
        return None

    def to_json(self, provenance=None):
        """The audit record. Safe to commit -- see :meth:`SiteIdentity.describe`."""
        return {
            "publication": self.publication,
            "game": self.game,
            "spec": "#26, #27",
            "what_this_is": "every file published to the paper's private address, and "
                            "nothing else. The public root is rebuilt to match this list "
                            "exactly; a file not named here is removed rather than served.",
            "address": self.identity.describe(),
            "public_root": self.public_root,
            "published_rounds": self.published_rounds(),
            "categories": self.categories,
            "files": [entry.to_json() for entry in self.files],
        }

    def to_text(self, provenance=None):
        return json.dumps(self.to_json(provenance), indent=2, ensure_ascii=False) + "\n"


def load_manifest_json(path):
    """A previous build's manifest, or ``None`` if this is the first build."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, ValueError):
        return None
