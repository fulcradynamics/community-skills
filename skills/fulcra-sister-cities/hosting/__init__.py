"""Where The Daily Manifest lives (spec #26, #27).

M5 renders editions and stops at the filesystem. This package takes them the
last step: one fixed URL that is not publicly discoverable, with every prior
edition still browsable at it.

    from hosting import build_site, load_or_create, make_server

    record = build_site(game)          # the whole archive, checked, written
    print(record["url"])               # ... and where it is. Private.

The requirement has three clauses that pull against each other, and most of this
package is the resolution:

* **fixed** -- the address is minted once and persists, so a link handed out in
  round 1 still works in round 12 (:mod:`hosting.identity`).
* **not publicly discoverable** -- an unguessable subdomain, ``robots noindex``
  in three places, and no page reaching another origin to leak the address
  through a referrer log (:mod:`hosting.page`, :mod:`hosting.serve`).
* **reachable by all players** -- so there is no login. Knowing the URL is the
  credential, which is precisely why the URL is treated as one everywhere in
  here and never written into anything published.

And #27's clause is a promise about links people already have: a round that has
been published stays published, at the name it was published under.
:func:`hosting.guard.assert_archive_is_append_only` is that promise as a check.

What is published is a declared list and not a directory
(:mod:`hosting.manifest`), the declaration is checked against the actual bytes
before anything is written (:mod:`hosting.guard`), and the server answers from
the list rather than from the disk (:mod:`hosting.serve`). Those three are the
same idea three times: the set of public files is something somebody decided,
not something that accumulated.
"""

from .build import build_site, build_manifest, site_paths
from .guard import PublicationRefused
from .identity import SiteIdentity, load_or_create
from .serve import make_server

__all__ = [
    "build_site",
    "build_manifest",
    "site_paths",
    "make_server",
    "load_or_create",
    "SiteIdentity",
    "PublicationRefused",
]
