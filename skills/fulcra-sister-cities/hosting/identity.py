"""The paper's address, which is the whole of its privacy (spec #26).

Spec #26 asks for "a single fixed URL that is not publicly discoverable
(unguessable subdomain + robots noindex, per the ``fulcra-dashboard`` pattern)
but reachable by all players". Those three clauses pull in different directions
and this module is where the tension is resolved:

* **fixed** -- the address is generated once and then persists. A mayor who
  bookmarks it in round 1 must still reach the paper in round 12, so the id is
  written down on first use and re-read forever after, never re-derived.
* **unguessable** -- ``hosting.site_id_bytes`` bytes from :mod:`secrets`,
  rendered as a DNS label. At the configured 16 bytes that is 128 bits, which is
  not a thing anybody enumerates.
* **reachable by all players** -- so it cannot be an authentication wall. There
  is no login; knowing the URL *is* the credential.

That last point is what makes the rest of this milestone's paranoia
proportionate. If the address is the credential then the address is a secret,
and a secret has exactly the properties a secret has:

* it is not in ``config.json`` and not in the repo (``.gitignore`` excludes
  :data:`DEFAULT_SITE_ID_FILE`, and the file is written ``0600``);
* it is not in anything published -- :mod:`hosting.guard` fails the build if it
  appears in a single published byte, which is what makes the built site safe to
  commit while this file is not;
* it is not in the server's access log (:mod:`hosting.serve` prints nothing),
  and not in any page's outbound requests, because the pages make none;
* where a build record needs to say *which* site it is, it says
  :func:`fingerprint` -- a truncated SHA-256, which identifies the address
  without being it.

A deployment that keeps its secrets somewhere else (an env var injected by the
host, say) is expected, and ``hosting.site_id_env_var`` is the door for it: an
environment value wins over the file, and nothing is written to disk when one is
present.
"""

import base64
import hashlib
import hmac
import os
import re
import secrets

from engine.config import repo_root
from engine.errors import ConfigError

#: A DNS label: lowercase alphanumerics and hyphens, not starting or ending with
#: one, at most 63 characters. Checked rather than assumed, because the id ends
#: up in a hostname and a hostname that does not resolve is not a fixed URL.
DNS_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")

#: The floor under ``hosting.site_id_bytes``. The address is the only thing
#: between a private game and the open internet (there is no login by design --
#: spec #26 wants it reachable by every player), so a short id is not a
#: convenience trade-off, it is the whole failure. 12 bytes = 96 bits.
MIN_SITE_ID_BYTES = 12

#: Where the id lives when config does not say otherwise. Only used in error
#: messages and in the ``.gitignore`` cross-check; the path itself comes from
#: ``hosting.site_id_file`` like every other parameter.
DEFAULT_SITE_ID_FILE = ".site-id"

#: Enough of the digest to tell two sites apart in a build record, and nowhere
#: near enough to be the address. Preimage resistance does the rest.
FINGERPRINT_CHARS = 12


class SiteIdentity:
    """One game's address, and where it came from.

    Deliberately not a plain string. Everything that handles the id has to make
    a decision about whether it may write it down, and a type with a
    :meth:`describe` that is safe and a :attr:`site_id` that is not makes that
    decision visible at every call site.
    """

    __slots__ = ("site_id", "source", "path", "scheme", "base_domain")

    def __init__(self, site_id, source, path=None, scheme="https", base_domain=""):
        self.site_id = site_id
        self.source = source
        self.path = path
        self.scheme = scheme
        self.base_domain = base_domain

    # -- the address ------------------------------------------------------

    @property
    def host(self):
        return "%s.%s" % (self.site_id, self.base_domain)

    def url(self, path=""):
        """The canonical URL. **Secret** -- do not write this into a file."""
        return "%s://%s/%s" % (self.scheme, self.host, path.lstrip("/"))

    def local_url(self, host, port, path=""):
        """The same paper on a local server, gated by the same id.

        A subdomain is not available from a bare ``http.server``, so the local
        mount uses the id as a path prefix instead. It is the same secret doing
        the same job, which is the point: nothing is reachable locally that
        would not be reachable in the deployed shape, and nothing is reachable
        without the id in either.
        """
        return "http://%s:%d/%s/%s" % (host, port, self.site_id, path.lstrip("/"))

    # -- the safe half ----------------------------------------------------

    @property
    def fingerprint(self):
        return fingerprint(self.site_id)

    def describe(self, with_fingerprint=False):
        """What a build record, a manifest or a log line may say about this.

        The address is not in it, and the absence is *stated* rather than
        implied -- a reader of a manifest should be able to tell the address was
        withheld on purpose rather than wonder whether the build forgot it.

        ``with_fingerprint`` is off by default and the distinction is not
        paranoia about the digest, which is a truncated SHA-256 of 128 random
        bits and is not going anywhere. It is about what a *committed* file
        should contain: the manifest is reviewed in a repository, every game has
        its own address, and a field that changes per machine turns the
        repository's drift check ("rebuilding changed nothing") into noise. So
        the fingerprint goes to the facilitator's own build record, where the
        real address already is, and the committed manifest says only that there
        is one and it is not being printed.
        """
        described = {
            "url_style": "unguessable_subdomain",
            "base_domain": self.base_domain,
            "scheme": self.scheme,
            "address_withheld": True,
            "why_withheld": "the subdomain label is the only credential this paper has "
                            "(spec #26); publishing it would publish the paper",
        }
        if with_fingerprint:
            described["site_id_fingerprint"] = self.fingerprint
            described["site_id_source"] = self.source
        return described

    def matches(self, candidate):
        """Constant-time comparison, for routing a request.

        The server compares a path segment against the id on every request; a
        comparison that returns early tells a patient stranger how many
        characters they got right.
        """
        if not isinstance(candidate, str):
            return False
        return hmac.compare_digest(candidate, self.site_id)


def fingerprint(site_id):
    return hashlib.sha256(site_id.encode("utf-8")).hexdigest()[:FINGERPRINT_CHARS]


def generate(nbytes):
    """A fresh id: ``nbytes`` of CSPRNG output, as a lowercase DNS label.

    base32 rather than base64: a hostname is case-insensitive and has no ``_``
    or ``+``, so base64 would either collide on case or need escaping. base32
    lowercased is 8 characters per 5 bytes and legal as written.
    """
    if not isinstance(nbytes, int) or isinstance(nbytes, bool) or nbytes < MIN_SITE_ID_BYTES:
        raise ConfigError(
            "config.hosting.site_id_bytes must be an integer >= %d; got %r. The "
            "subdomain is the paper's only credential (spec #26), so this is a "
            "floor rather than a suggestion." % (MIN_SITE_ID_BYTES, nbytes)
        )
    label = base64.b32encode(secrets.token_bytes(nbytes)).decode("ascii").rstrip("=").lower()
    if not DNS_LABEL.match(label):  # pragma: no cover - base32 cannot produce this
        raise ConfigError("generated site id %r is not a legal DNS label" % label)
    return label


def validate(site_id, where):
    if not isinstance(site_id, str) or not DNS_LABEL.match(site_id):
        raise ConfigError(
            "%s is not a legal DNS label (lowercase letters, digits and hyphens, "
            "not starting or ending with one, <= 63 characters)" % where
        )
    return site_id


def site_id_path(config, root=None):
    return os.path.join(root or repo_root(), config.require_str("hosting.site_id_file"))


def load_or_create(config, root=None, env=None):
    """This game's address, from the environment, the file, or freshly minted.

    The order is deliberate. A deployment that injects the id has decided where
    its secrets live and this module must not second-guess it by also writing a
    copy to disk; only the "nobody has told us" case creates a file.
    """
    env = os.environ if env is None else env
    scheme = config.require_str("hosting.scheme")
    base_domain = config.require_str("hosting.base_domain")
    variable = config.require_str("hosting.site_id_env_var")
    path = site_id_path(config, root=root)

    injected = (env.get(variable) or "").strip()
    if injected:
        validate(injected, "$%s" % variable)
        return SiteIdentity(injected, "env:%s" % variable, None, scheme, base_domain)

    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as fh:
            stored = fh.read().strip()
        validate(stored, "the site id in %s" % path)
        return SiteIdentity(stored, "file", path, scheme, base_domain)

    site_id = generate(config.require_int("hosting.site_id_bytes"))
    _write_secret(path, site_id)
    return SiteIdentity(site_id, "file (created)", path, scheme, base_domain)


def _write_secret(path, site_id):
    """Write the id where only this user can read it.

    ``os.open`` with an explicit mode rather than ``open()`` then ``chmod``:
    between those two calls the file exists and is world-readable, which is a
    short window and still a window.
    """
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    handle = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(handle, "w", encoding="utf-8") as fh:
        fh.write(site_id + "\n")
