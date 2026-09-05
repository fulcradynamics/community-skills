"""Serving the manifest -- not a directory (spec #26).

A static site is usually served by pointing a web server at a folder. That is
the one thing this module does not do, because "what is public" would then be a
property of the filesystem rather than a decision anybody made, and the whole of
:mod:`hosting.manifest` exists to make it a decision anybody made.

So the server loads the publication manifest into memory and answers from it. A
path that is not a manifest entry is a 404 -- not because it was checked and
rejected, but because there is nothing to return. Directory traversal, dotfiles,
the manifest itself, a stray file somebody dropped in the public root after the
build: all the same 404, structurally, with no rule to get wrong.

The address does the authorising, because spec #26 says the paper is reachable
by all players and says nothing about anybody logging in: knowing the URL *is*
the credential. Deployed, that means an unguessable subdomain. Here it means an
unguessable first path segment, which is the same secret doing the same job --
``http.server`` has one hostname and a local mount that ignored the id would be
a local mount that tested nothing.

Three details that are the actual privacy work rather than decoration:

* **the comparison is constant-time**. A prefix match that returns early tells a
  patient stranger how many characters they got right.
* **nothing is logged**. ``BaseHTTPRequestHandler`` writes every request line to
  stderr by default, and every request line here contains the credential.
* **``robots.txt`` answers without it.** It is the exclusion notice, it holds no
  secret, and a crawler that has somehow reached the host should be able to read
  the word ``Disallow`` without first knowing the address it is being told to
  stay out of.
"""

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from engine.config import repo_root
from engine.errors import ConfigError

from .build import MANIFEST_FILENAME, INDEX_FILENAME, ROBOTS_FILENAME, resolve_privacy, site_paths


class ServedSite:
    """One built site, in memory: path -> (bytes, content type)."""

    def __init__(self, files, identity, privacy):
        self.files = files
        self.identity = identity
        self.privacy = privacy

    @classmethod
    def load(cls, public_root, manifest_path, identity, privacy):
        with open(manifest_path, "r", encoding="utf-8") as fh:
            manifest = json.load(fh)
        files = {}
        for entry in manifest["files"]:
            with open(os.path.join(public_root, entry["path"]), "rb") as handle:
                files[entry["path"]] = (handle.read(), entry["content_type"])
        return cls(files, identity, privacy)

    def get(self, name):
        return self.files.get(name)


def _handler_for(site):
    class ManifestHandler(BaseHTTPRequestHandler):
        server_version = "DailyManifest/1.0"
        sys_version = ""  # do not advertise the interpreter

        def log_message(self, *args):
            """Silence. Every request line here contains the paper's address."""

        def do_HEAD(self):
            self._respond(body=False)

        def do_GET(self):
            self._respond(body=True)

        # -- routing ------------------------------------------------------

        def _respond(self, body):
            path = self.path.split("?", 1)[0].split("#", 1)[0]
            entry = self._resolve(path)
            if entry is None:
                return self._not_found(body)
            content, content_type = entry
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self._privacy_headers()
            self.end_headers()
            if body:
                self.wfile.write(content)

        def _resolve(self, path):
            if path == "/%s" % ROBOTS_FILENAME:
                return site.get(ROBOTS_FILENAME)
            segments = [segment for segment in path.split("/") if segment]
            if not segments or not site.identity.matches(segments[0]):
                return None
            rest = segments[1:]
            if not rest:
                # The address itself, with or without a trailing slash: the
                # current issue (spec #30a). `hosting.build` is what decides
                # which edition that is; this only knows the filename.
                return site.get(INDEX_FILENAME)
            if len(rest) > 1:
                # The public tree is flat, so a nested path is not a path.
                return None
            return site.get(rest[0])

        def _not_found(self, body):
            message = b"404\n"
            self.send_response(404)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(message)))
            self._privacy_headers()
            self.end_headers()
            if body:
                self.wfile.write(message)

        def _privacy_headers(self):
            # On the 404 as well as the 200: a response that skipped them would
            # be a response that told a crawler this host is worth revisiting.
            self.send_header("X-Robots-Tag", site.privacy["x_robots_tag"])
            self.send_header("Referrer-Policy", site.privacy["referrer_policy"])
            self.send_header("Cache-Control", site.privacy["cache_control"])
            self.send_header("Content-Security-Policy", site.privacy["content_security_policy"])
            self.send_header("X-Content-Type-Options", "nosniff")

    return ManifestHandler


def make_server(config, identity, site_dir=None, root=None, host=None, port=None):
    """A server for the built site, bound but not yet serving.

    Returns ``(httpd, url)``. The URL is the private one and is returned rather
    than printed, so that whether it reaches a terminal is the caller's decision
    and not a side effect of starting a server.
    """
    base, public_root, manifest_path = site_paths(config, root=root)
    if site_dir is not None:
        base = site_dir
        public_root = os.path.join(site_dir, config.require_str("hosting.public_subdir"))
        manifest_path = os.path.join(site_dir, MANIFEST_FILENAME)
    if not os.path.exists(manifest_path):
        raise ConfigError(
            "no publication manifest at %s; build the site with hosting.build_site "
            "before serving it" % manifest_path
        )

    privacy = resolve_privacy(config)
    site = ServedSite.load(public_root, manifest_path, identity, privacy)
    host = host if host is not None else config.require_str("hosting.local_bind_host")
    port = port if port is not None else config.require_int("hosting.local_bind_port")
    httpd = ThreadingHTTPServer((host, port), _handler_for(site))
    httpd.daemon_threads = True
    bound_host, bound_port = httpd.server_address[0], httpd.server_address[1]
    return httpd, identity.local_url(bound_host, bound_port)


def main(argv=None):  # pragma: no cover - CLI
    """``python3 -m hosting.serve`` -- build if needed, then serve, and say where."""
    from engine import Config

    argv = list(sys.argv[1:] if argv is None else argv)
    config = Config.load()
    from . import identity as identity_module

    identity = identity_module.load_or_create(config)
    httpd, url = make_server(config, identity, root=repo_root())
    print("The Daily Manifest is at %s" % url)
    print("(canonical address: %s -- private, do not paste it anywhere public)"
          % identity.url())
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI
    sys.exit(main())
