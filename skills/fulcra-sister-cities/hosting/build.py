"""Turning a rendered archive into a site, and refusing to if it would leak.

Spec #26 and #27, which are one requirement in two sentences: **one** fixed,
non-publicly-discoverable URL, and **every** edition still browsable at it. The
build is therefore not "write the latest issue"; it is "write the whole shelf,
and prove that nothing that was on it has fallen off".

The order of operations is the design:

1. **Render** every edition M5 will give us to HTML, plus the archive index,
   the images, the curated JSON, the stylesheet and ``robots.txt``.
2. **Declare** each of those in a :class:`~hosting.manifest.PublicationManifest`
   with its category, its source and the reason it is public. Nothing is written
   yet, so nothing has been published yet.
3. **Check** -- :mod:`hosting.guard` reads the actual bytes, and the previous
   manifest is checked for editions this build would drop.
4. **Write**, and then remove anything in the public root the manifest does not
   name, so a file from an earlier build cannot linger into this one.
5. **Compare** the directory back against the manifest. If they differ, the
   build failed, even though the files are already on disk -- better a failed
   build with a correct tree than a successful one nobody checked.

Steps 3 and 5 are the ones that make step 4 safe to have written to a directory
somebody might serve.

Deployment
----------
``hosting.publishers`` names remote deploy adapters, and this deployment
registers none, so the site is built and served locally
(:mod:`hosting.serve`) and the build record says exactly that rather than
implying a deployment that did not happen. Naming a publisher that is not
registered is a :class:`ConfigError`, not a quiet fallback -- the same rule
:mod:`newspaper.imagery` applies to raster providers, for the same reason: a
typo must not present as "we tried and it wasn't there".
"""

import json
import os

from engine.config import repo_root
from engine.errors import ConfigError

from newspaper.copy import NewspaperCopy
from newspaper.edition import Paper

from . import guard, identity as identity_module, page
from .manifest import (
    PublicationManifest, PublicFile, edition_key, load_manifest_json, resolve_categories,
)

#: Name of the audit record, written *beside* the public root and never in it.
MANIFEST_FILENAME = "publication-manifest.json"

#: What the paper's one address answers with, and where the shelf lives. Fixed
#: rather than configurable: spec #26 says one URL and spec #30a says that URL
#: opens the newest edition, and "which file the URL's directory serves" is not
#: a game parameter. Both names come from :mod:`hosting.page`, which is the
#: module that writes the links between them -- a name defined twice is a name
#: that will eventually disagree with itself.
INDEX_FILENAME = page.FRONT_PAGE_NAME
ARCHIVE_FILENAME = page.ARCHIVE_PAGE_NAME
ARCHIVE_JSON_FILENAME = "archive.json"
STYLESHEET_FILENAME = "style.css"
ROBOTS_FILENAME = "robots.txt"

#: Where the stylesheet is authored. In ``content/`` because it is a design
#: decision, not machinery -- see the comment at the top of the file itself.
STYLESHEET_SOURCE = "content/site.css"

#: Remote deploy adapters, by id. An adapter needs ``available()`` and
#: ``deploy(manifest, public_root, identity)``. None are registered here: this
#: deployment has no hosting provider wired up, and an empty registry that says
#: so is more honest than a stub that pretends.
PUBLISHERS = {}

#: Which orders the archive index may be listed in.
ARCHIVE_ORDERS = ("newest_first", "oldest_first")

#: Exactly the fields of an edition that go into the curated ``archive.json``.
#: An allowlist rather than a blocklist: a field added to the edition payload by
#: a later milestone is not published until somebody puts it here on purpose.
PUBLIC_EDITION_FIELDS = (
    "round", "publication", "game", "edition_line", "motto", "dateline", "closes",
    "price_line", "weather_line", "standing_line", "departments", "endgame",
    "foot_line",
)


def resolve_publishers(config):
    """The remote publishers this game deploys to, refusing unknown names."""
    declared = config.require("hosting.publishers")
    if not isinstance(declared, list):
        raise ConfigError("config.hosting.publishers must be a list of adapter ids")
    unknown = [name for name in declared if name not in PUBLISHERS]
    if unknown:
        raise ConfigError(
            "config.hosting.publishers names %s, which %s does not register. A "
            "publisher that is not wired up is a config error rather than a silent "
            "fall back to local-only serving." % (unknown, __name__)
        )
    return [PUBLISHERS[name] for name in declared]


def resolve_archive_order(config):
    order = config.require_str("hosting.archive_order")
    if order not in ARCHIVE_ORDERS:
        raise ConfigError(
            "config.hosting.archive_order is %r; this site lists %s"
            % (order, list(ARCHIVE_ORDERS))
        )
    return order


def resolve_privacy(config):
    """The delivery policy: noindex in three places, and no sideways leaks.

    Every field is required. A missing one is a :class:`MissingConfigKey` from
    :meth:`Config.require`, which is the point of there being no defaults --
    "the referrer policy quietly reverted to the browser's" is not a thing that
    should be possible to do by deleting a line.
    """
    return {
        "robots_txt": config.require_bool("hosting.privacy.robots_txt"),
        "meta_robots": config.require_str("hosting.privacy.meta_robots"),
        "x_robots_tag": config.require_str("hosting.privacy.x_robots_tag"),
        "referrer_policy": config.require_str("hosting.privacy.referrer_policy"),
        "cache_control": config.require_str("hosting.privacy.cache_control"),
        "content_security_policy": config.require_str(
            "hosting.privacy.content_security_policy"
        ),
    }


def curated_edition(edition):
    """The edition, reduced to what a public JSON feed may carry.

    Built by naming fields rather than by deleting them. The image keeps its
    provenance -- which modality actually drew it and why (spec #29) -- because
    that disclosure is part of the edition, and drops its inline content, which
    is the file sitting next to it.
    """
    public = {field: edition[field] for field in PUBLIC_EDITION_FIELDS if field in edition}
    public["page"] = page.page_name_for(edition)
    image = edition.get("image") or {}
    if image.get("filename"):
        provenance = image.get("provenance") or {}
        public["image"] = {
            "file": image["filename"],
            "alt": image["alt"],
            "cutline": image["cutline"],
            "modality": provenance.get("modality"),
            "provider": provenance.get("provider"),
        }
    portraits = [entry for entry in edition.get("city_images") or () if entry.get("filename")]
    if portraits:
        # Spec #32's images, named the same way the edition's own is. The city
        # is public (spec #28 prints cities), the file is public, and neither
        # says anything about who sent an offer nobody chose.
        public["city_images"] = [
            {
                "city": entry["city"],
                "file": entry["filename"],
                "alt": entry["alt"],
                "cutline": entry["cutline"],
                "modality": (entry.get("provenance") or {}).get("modality"),
                "provider": (entry.get("provenance") or {}).get("provider"),
            }
            for entry in portraits
        ]
    return public


def curated_archive(archive, editions, final=None):
    newest = final if final is not None else (editions[-1] if editions else None)
    return {
        "publication": archive["publication"],
        "game": archive["game"],
        "motto": archive["motto"],
        "cadence": archive["cadence"],
        "archive_prior_editions": archive["archive_prior_editions"],
        "ended": bool(final),
        "spec": "#26, #27, #30a, #31",
        # Where a reader that is not a browser should look, so it does not have
        # to know the site's naming convention: the front door, the shelf, and
        # which issue the front door is currently carrying (spec #30a).
        "front_page": INDEX_FILENAME,
        "archive_page": ARCHIVE_FILENAME,
        "latest": page.page_name_for(newest) if newest is not None else None,
        "editions": [curated_edition(edition) for edition in editions],
        "final": curated_edition(final) if final else None,
    }


def site_paths(config, root=None):
    """``(site_dir, public_root, manifest_path)``, all under the repo root."""
    base = os.path.join(root or repo_root(), config.require_str("hosting.site_dir"))
    public_root = os.path.join(base, config.require_str("hosting.public_subdir"))
    return base, public_root, os.path.join(base, MANIFEST_FILENAME)


def build_manifest(archive, copy, config, identity, privacy):
    """Everything this publication will contain, declared and not yet written."""
    site = copy.site()
    categories = resolve_categories(config)
    order = resolve_archive_order(config)

    editions = list(archive["editions"])
    rounds = [edition["round"] for edition in editions]
    # The last edition is published only if the game has ended *and*
    # `final_edition` is one of the categories this game publishes. It is listed
    # in the archive alongside the round editions -- it is an issue of the same
    # paper at the same address (spec #26, #27) -- and it sorts last in reading
    # order, so newest_first puts it first.
    final = archive.get("final") if "final_edition" in categories else None
    listed = list(reversed(editions)) if order == "newest_first" else editions
    if final is not None:
        listed = [final] + listed if order == "newest_first" else listed + [final]
    # A page may only link a file this build actually publishes. `hosting.publish`
    # can leave the stylesheet or the images out, and a link to something that is
    # not there is a broken page rather than a graceful degradation.
    stylesheet = STYLESHEET_FILENAME if "stylesheet" in categories else None
    with_images = "edition_images" in categories
    with_city_images = "city_images" in categories
    with_archive = "archive_index" in categories
    # The issue pages this build writes, so that nothing links one it did not.
    # Normally all of them; a publish list without `editions` is the case this
    # exists for, and a shelf that linked twelve missing files would be a worse
    # answer than a shelf that lists twelve issues it cannot offer.
    published_pages = set()
    if "editions" in categories:
        published_pages.update(page.edition_page_name(index) for index in rounds)
    if final is not None:
        published_pages.add(page.FINAL_PAGE_NAME)

    manifest = PublicationManifest(
        archive["publication"], archive["game"], identity, categories,
        config.require_str("hosting.public_subdir"),
    )
    rendered = {}

    # The front door, first, because it is the only file whose name a mayor
    # ever types (spec #26) and spec #30a says what it contains: the newest
    # available edition -- the final one if the game has ended, otherwise the
    # last round to go to press. Rendered a second time under a second name,
    # deliberately: the issue keeps its own permanent page (spec #27), so the
    # front page is a copy of the current issue rather than its only home.
    newest = final if final is not None else (editions[-1] if editions else None)
    front = _front_page(
        archive, newest, listed, site, privacy, stylesheet, with_images, with_city_images,
        with_archive, rounds, categories, published_pages,
    )
    if front is not None:
        manifest.add(front)

    if with_archive:
        manifest.add(PublicFile(
            ARCHIVE_FILENAME, "archive_index", "hosting.page.archive_page",
            "the shelf: every edition ever printed, still at its own name, so a link "
            "handed out in round one still works in the last one (spec #27), and the "
            "page the front door and every issue link back to (spec #30a)",
            page.archive_page(
                archive, listed, site, privacy, stylesheet, with_images,
                page_names=published_pages, with_city_images=with_city_images,
            ),
        ))

    for index, edition in enumerate(editions):
        previous_round = rounds[index - 1] if index > 0 else None
        next_round = rounds[index + 1] if index + 1 < len(rounds) else None
        html = page.edition_page(
            edition, site, privacy, previous_round, next_round, stylesheet, with_images,
            final_page=final is not None and index == len(editions) - 1,
            with_archive=with_archive, with_city_images=with_city_images,
        )
        rendered[edition_key(edition)] = [html]
        if "editions" in categories:
            manifest.add(PublicFile(
                page.edition_page_name(edition["round"]), "editions",
                "newspaper.build_edition(round=%d)" % edition["round"],
                "the edition for round %d, at a permanent name so a link handed out "
                "in that round still works in the last one (spec #27)" % edition["round"],
                html, round=edition["round"],
            ))
        image = edition.get("image") or {}
        if "edition_images" in categories and image.get("filename") and image.get("content"):
            rendered[edition_key(edition)].append(
                image["content"] if isinstance(image["content"], str) else ""
            )
            manifest.add(PublicFile(
                image["filename"], "edition_images",
                "newspaper.imagery.make_image(round=%d)" % edition["round"],
                "the one image this edition carries (spec #29); drawn from the round's "
                "own facts and from ballot positions only, never from who sent what",
                image["content"], round=edition["round"],
            ))

    if final is not None:
        _add_final_edition(
            manifest, rendered, final, site, privacy, stylesheet, with_images,
            with_city_images, categories, rounds, with_archive,
        )

    if front is not None and newest is not None:
        # The front page is another rendering of an edition that already has
        # one, so it is filed with that edition's other renderings rather than
        # on its own. That is not bookkeeping: hosting.guard re-runs the
        # redaction audit over every rendering of an edition, and a copy of the
        # newest issue that nothing had audited would be the least-checked page
        # on the site and the most-read one.
        rendered[edition_key(newest)].append(front.content)

    if "archive_json" in categories:
        payload = curated_archive(archive, editions, final)
        manifest.add(PublicFile(
            ARCHIVE_JSON_FILENAME, "archive_json", "hosting.build.curated_archive",
            "the same editions for a reader that is not a browser, assembled from an "
            "allowlist of fields so a later milestone cannot widen it by accident",
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        ))
    else:
        payload = None

    if "stylesheet" in categories:
        manifest.add(PublicFile(
            STYLESHEET_FILENAME, "stylesheet", STYLESHEET_SOURCE,
            "presentation only; it carries no game state and reaches no other origin",
            _read_stylesheet(config),
        ))

    if "robots" in categories:
        if not privacy["robots_txt"]:
            raise ConfigError(
                "config.hosting.publish includes 'robots' but "
                "config.hosting.privacy.robots_txt is false. Spec #26 wants the paper "
                "non-discoverable; publishing an empty exclusion would be worse than "
                "not publishing one, so this is refused rather than resolved."
            )
        manifest.add(PublicFile(
            ROBOTS_FILENAME, "robots", "hosting.page.robots_txt",
            "the crawler exclusion; the half of 'not publicly discoverable' that is "
            "asked for politely, the other half being the unguessable address (spec #26)",
            page.robots_txt(site, privacy),
        ))

    return manifest, rendered, payload


def _front_page(archive, newest, listed, site, privacy, stylesheet, with_images,
                with_city_images, with_archive, rounds, categories, published_pages):
    """``index.html``: the newest edition, or an honest empty shelf (spec #30a).

    Two cases, and the second one is why this is a function rather than a line:

    * there is a newest edition, and the front door carries it, with a link to
      that issue's own permanent address so a reader who wants to keep *this*
      issue rather than *the current* issue can;
    * no round has finished yet, so there is no newest edition. The address
      still has to answer with something (spec #26), and the honest something is
      the shelf, empty, saying so. A front page that carried round zero would be
      inventing an edition.

    ``front_page`` is required rather than optional in ``hosting.publish``: the
    other categories are things a deployment can choose not to serve, and this
    one is the URL itself.
    """
    if "front_page" not in categories:
        raise ConfigError(
            "config.hosting.publish must include 'front_page': it is the file the "
            "paper's one address answers with, and spec #26 (\"reachable by all "
            "players\") and spec #30a (\"the stable paper URL opens the newest "
            "available edition by default\") are not satisfied by a 404. Categories "
            "asked for: %s" % sorted(categories)
        )
    if newest is None:
        return PublicFile(
            INDEX_FILENAME, "front_page", "hosting.page.archive_page",
            "the one address every mayor holds, before the first round has closed: "
            "an empty shelf that says the presses are still warm, rather than an "
            "invented edition or a 404 (spec #26, #30a)",
            page.archive_page(
                archive, listed, site, privacy, stylesheet, with_images, front=True,
                page_names=published_pages, with_city_images=with_city_images,
            ),
        )
    # What "previous" means on the front page: the issue before the newest one.
    # For the final edition that is the last round; for a round edition it is the
    # round before it. Only if that page is one this build writes.
    if newest.get("endgame"):
        previous_round = rounds[-1] if rounds else None
    else:
        previous_round = rounds[-2] if len(rounds) > 1 else None
    if previous_round is not None and "editions" not in categories:
        previous_round = None
    permalink = page.page_name_for(newest)
    if permalink not in published_pages:
        # The front door is carrying an issue whose own page this build does not
        # publish, so there is no permanent address to offer a reader. Saying
        # nothing beats linking a file that is not there.
        permalink = None
    return PublicFile(
        INDEX_FILENAME, "front_page", "hosting.page.edition_page(newest)",
        "the one address every mayor holds, answering with the newest edition so a "
        "link handed out in round one opens today's paper (spec #26, #30a); the same "
        "issue keeps its own permanent page, which this one links (spec #27)",
        page.edition_page(
            newest, site, privacy, previous_round=previous_round, next_round=None,
            stylesheet=stylesheet, with_image=with_images, final_page=False,
            front=True, permalink=permalink, with_archive=with_archive,
            with_city_images=with_city_images,
        ),
    )


def _add_final_edition(manifest, rendered, final, site, privacy, stylesheet,
                       with_images, with_city_images, categories, rounds, with_archive=True):
    """Declare the last edition, its finale picture and its portraits (#31, #32).

    The page is filed under its own category rather than under ``editions``,
    which is not bookkeeping: ``editions`` is checked for one page per round
    (:func:`hosting.guard.assert_publishable`), the final edition shares the last
    round's number, and a page with a duplicate round in that category would --
    correctly -- be refused as an edition overwriting an edition. Giving it its
    own category says what it is instead of arguing with the check.
    """
    html = page.edition_page(
        final, site, privacy,
        previous_round=rounds[-1] if rounds and "editions" in categories else None,
        next_round=None, stylesheet=stylesheet, with_image=with_images,
        with_archive=with_archive, with_city_images=with_city_images,
    )
    rendered[edition_key(final)] = [html]

    if "final_edition" in categories:
        manifest.add(PublicFile(
            page.FINAL_PAGE_NAME, "final_edition", "newspaper.build_final_edition",
            "the last edition -- the crown, the consequences and a portrait of every "
            "city (spec #31, #32) -- at a permanent name beside the round editions, "
            "so the archive gains an issue rather than losing one (spec #27)",
            html,
        ))

    image = final.get("image") or {}
    if "edition_images" in categories and image.get("filename") and image.get("content"):
        rendered[edition_key(final)].append(
            image["content"] if isinstance(image["content"], str) else ""
        )
        manifest.add(PublicFile(
            image["filename"], "edition_images", "newspaper.endgame.finale_scene",
            "the closing illustration (spec #29, #31): final standings, the crown, and "
            "the world's unchosen offers as an unlabelled stack that names no sender",
            image["content"],
        ))

    if "city_images" not in categories:
        return
    for portrait in final.get("city_images") or ():
        if not portrait.get("filename") or not portrait.get("content"):
            continue
        rendered[edition_key(final)].append(
            portrait["content"] if isinstance(portrait["content"], str) else ""
        )
        manifest.add(PublicFile(
            portrait["filename"], "city_images",
            "newspaper.endgame.city_scene(city=%r)" % portrait["city"],
            "the portrait of %s (spec #32), drawn from that city's own notices, the "
            "offers the world kept from it, and the offers it declined -- the offers "
            "it *sent* and nobody chose are a shut door in the picture and a number "
            "nowhere in it (spec #21)" % portrait["city"],
            portrait["content"],
        ))


def _read_stylesheet(config, root=None):
    path = os.path.join(root or repo_root(), STYLESHEET_SOURCE)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    except FileNotFoundError:
        raise ConfigError("the site stylesheet is missing from %s" % path)


def build_site(engine, out_dir=None, paper=None, identity=None, copy=None, root=None):
    """Publish the whole archive to the paper's private address.

    Returns a build record. The record holds the real URL, because the caller is
    the facilitator and the facilitator is who the address is for; nothing in it
    is written to disk except through the manifest, which withholds it.
    """
    config = engine.config
    if not config.require_bool("hosting.enabled"):
        return {
            "published": False,
            "reason": "config.hosting.enabled is false",
            "spec": "#26, #27",
        }

    paper = paper or Paper(engine, copy=copy)
    copy = paper.copy
    identity = identity or identity_module.load_or_create(config, root=root)
    privacy = resolve_privacy(config)
    publishers = resolve_publishers(config)

    archive = paper.archive()
    manifest, rendered, curated = build_manifest(archive, copy, config, identity, privacy)

    site_dir, public_root, manifest_path = site_paths(config, root=root)
    if out_dir is not None:
        site_dir = out_dir
        public_root = os.path.join(out_dir, config.require_str("hosting.public_subdir"))
        manifest_path = os.path.join(out_dir, MANIFEST_FILENAME)

    # The final edition is audited with the rest of them, not after them. It is
    # the edition with the most exposure surface in the game -- a portrait per
    # city, every declined offer on every quay -- so leaving it out of the gate
    # would leave out the one that most needs it (spec #21, #28, #31, #32).
    audited = list(archive["editions"])
    if archive.get("final") is not None:
        audited.append(archive["final"])
    guard.assert_publishable(
        engine, manifest, audited, identity=identity,
        rendered_by_round=rendered, payloads=[curated] if curated else [],
    )
    previous = load_manifest_json(manifest_path)
    if archive["archive_prior_editions"]:
        guard.assert_archive_is_append_only(previous, manifest)

    _write_tree(public_root, manifest)
    with open(manifest_path, "w", encoding="utf-8") as fh:
        fh.write(manifest.to_text())
    guard.assert_public_root_matches(manifest, public_root)

    return {
        "published": True,
        "spec": "#26, #27",
        "site_dir": site_dir,
        "public_root": public_root,
        "manifest_path": manifest_path,
        "url": identity.url(),
        "address": identity.describe(with_fingerprint=True),
        "rounds": manifest.published_rounds(),
        "files": [entry.to_json() for entry in manifest.files],
        "archive_prior_editions": archive["archive_prior_editions"],
        "privacy": privacy,
        "delivery": {
            "publishers": [getattr(p, "publisher_id", str(p)) for p in publishers],
            "resolves_today": bool(publishers),
            "note": "the canonical subdomain is what a registered publisher would deploy "
                    "to; with none registered the paper is served by hosting.serve, "
                    "gated by the same id" if not publishers else
                    "deployed by the publishers named in config.hosting.publishers",
        },
    }


def _write_tree(public_root, manifest):
    """Write exactly the manifest, and unwrite everything else.

    The removal pass is the half that matters. Writing the right files is easy;
    a public root only contains what was curated if something takes out what
    was not.
    """
    os.makedirs(public_root, exist_ok=True)
    declared = set(manifest.paths())
    for base, _, names in os.walk(public_root):
        for name in names:
            full = os.path.join(base, name)
            if os.path.relpath(full, public_root) not in declared:
                os.remove(full)
    for entry in manifest.files:
        with open(os.path.join(public_root, entry.path), "wb") as fh:
            fh.write(entry.data)
