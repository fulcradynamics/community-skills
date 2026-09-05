# M6 — publishing the paper, and the address it is published to

Spec #26 and #27. One requirement in two sentences: **one** fixed URL that is
not publicly discoverable but reachable by every player, and **every** prior
edition still browsable at it.

| # | Rule | Where it is settled |
| --- | --- | --- |
| #26 | one fixed, unguessable, `noindex` address, reachable by all players | `hosting/identity.py`, `hosting/page.py`, `hosting/serve.py` + `hosting.*` |
| #27 | prior editions stay browsable at that same address | `hosting/build.py`, `hosting/guard.py`, `engine/views.py:published_rounds` |

```
python3 run_tests.py                     # 422 tests, standard library only
hosting.build_site(engine)               # the whole archive, checked, written
python3 -m hosting.serve                 # ... and served, and it prints the URL
```

The built site is committed at [`site/`](../site): `site/public/` is exactly
what is served, and `site/publication-manifest.json` is the record of why each
of those files is in there. It is safe to commit because the address is not in
any of it — see below, since that is the whole design.

## The address is the credential

Spec #26 asks for something not publicly discoverable *and* reachable by every
player. Those two together rule out a login: there is nobody to log in as. So
knowing the URL **is** the credential, and the rest follows from taking that
literally rather than treating the address as a URL that happens to be obscure.

`hosting/identity.py` mints `hosting.site_id_bytes` (16, so 128 bits) from
`secrets`, renders them as a DNS label, and writes them down once — *fixed* is
as much a requirement as *unguessable*, because a mayor's round-1 bookmark has
to work in round 12. From there it is handled the way a secret is handled:

- not in `config.json` and not in the repo — `.gitignore` excludes it and the
  file is created `0600` with `os.open`, not `open()`-then-`chmod`;
- **not in anything published.** `hosting/guard.py` fails the build if the id
  appears in a single published byte, and every link inside the site is
  relative. That rule is what makes committing the site safe;
- not in a log: `hosting/serve.py` silences `BaseHTTPRequestHandler`, whose
  default is to write every request line — each containing the credential — to
  stderr;
- not in a *referrer*. This is the one that is easy to miss. A page that loads a
  font, an icon or an analytics script hands its own URL to another server's
  logs, so the pages reference no external origin at all. `Referrer-Policy:
  no-referrer`, a CSP with no external sources, and a guard rule that refuses to
  publish any `href`/`src`/`url()` pointing off-site — because a header is a
  request and the absence of the reference is the guarantee;
- where a record needs to identify *which* site a build belongs to, it uses a
  truncated SHA-256 rather than the id. Even that stays out of the committed
  manifest: every game has its own address, and a field that changes per machine
  turns this repo's "rebuilding changed nothing" check into noise.

`noindex` is stated three times — `robots.txt`, a `<meta>` tag, and the
`X-Robots-Tag` header — because a crawler that ignores one of them is a normal
crawler, and #26 asks that the paper not be discoverable, not that it have asked
politely once. `robots.txt` is the one thing served without the address in front
of it: it holds no secret, and a crawler that has reached the host should be
able to read the word `Disallow`.

## Only curated files are published, in three places

There are two ways to build a static site and only one of them can be reviewed.
Copy a directory and the answer to "why is this file public?" is "it was in the
folder". So nothing here copies a directory:

1. **`hosting/manifest.py` declares.** Every file, with its category (from the
   `hosting.publish` allowlist), the repo artifact it derives from, and the
   sentence justifying it — written up front, not reconstructed at review time.
   Nothing is on disk at this point, so nothing is published yet.
2. **`hosting/guard.py` checks the bytes.** The declaration is what somebody
   intended; the guard reads what is actually there. Credentials and private
   keys, `Authorization` headers, external references, facilitator-only views,
   unfinished `[[M…]]` stubs, the site id, and — structurally — any file whose
   declared source names inboxes, verdicts, evaluations, `.git`, `config.json`
   or the tests. Then it re-runs `newspaper.redact` over the **rendered HTML**,
   which neither M5 nor the engine has ever seen: an edition that passed as
   Markdown is a different rendering, and a leak in one is not a leak in the
   other until it is checked.
3. **`hosting/build.py` writes exactly that, and unwrites everything else**, and
   then compares the directory back against the manifest. The removal pass is
   the half that matters — a scratch file from an earlier build was never
   curated, and a host serving a directory would serve it anyway.

Then `hosting/serve.py` **serves the manifest, not the directory**. Path
traversal, dotfiles, the manifest itself, a file dropped into the public root
after the build: all the same 404, structurally, with no rule to get wrong.

None of the guard is configurable, deliberately. `config.json` is the single
source for every parameter the spec calls configurable, and spec #22 makes
*exposure* policy configurable; it does not make *leaking* configurable. Same
carve-out `engine/economy.py` makes for spec #21, checked the same way —
`guard.assert_no_config_can_disable` walks the raw config document, because a
knob nothing reads yet is still a knob somebody will wire up.

## An archive is a promise about links people already have

Spec #27's "prior editions remain browsable at that same URL" is not "keep the
files". It is: a link handed out in round 3 keeps showing round 3's paper.
Two things enforce it and one M5 groundwork makes it possible.

- `guard.assert_archive_is_append_only` compares this build's manifest against
  the previous one and refuses a build that would drop a published round or
  rename its page. It stands down when `newspaper.archive_prior_editions` is
  false, because publishing only the latest issue is then a facilitator's
  decision rather than a build breaking its word.
- The edition itself must not *change*. `test_a_later_build_leaves_the_earlier_editions_exactly_where_they_were`
  plays one game to three rounds, publishes, plays it to six, republishes, and
  asserts round 3's `<article>` is byte-identical. Its navigation is allowed to
  grow — a "next edition" link appearing when round 4 goes to press is the
  archive working, not the issue being rewritten — so the article and the
  chrome are asserted separately.
- M5 froze each round's closing standings for exactly this reason; without it an
  archive of twelve editions prints the final table twelve times.

M10 later moved the *front door* without touching any of this: `index.html` now
carries the newest available edition and the shelf of back issues moved to
`archive.html`, while every `round-NN.html` and `final.html` kept its name and
its bytes. See [`docs/m10-reading-experience.md`](m10-reading-experience.md);
the append-only check and the byte-identical-article test above are unchanged
and still pass, which is how that move was shown to have cost nothing.

### One engine change this milestone needed

`Paper.archive()` used to publish every round in `engine.rounds`, which includes
the round the game is **currently in**. Spec #26 says once per *completed*
round, and an edition for a round still open would say something different an
hour later — which is precisely the promise #27 makes to a bookmark. So
`engine/views.published_rounds` names the completed rounds and the paper asks
for those. "Completed" has one definition rather than two: a round's standing is
frozen the instant the next one begins, so a frozen standing *is* the round
having ended.

Nothing changed for a finished game, which is why `editions/sample-game/` is
unmoved.

## The page, and the two inline marks

`hosting/page.py` renders from the **structured edition**, not from M5's
Markdown. Payload → HTML rather than payload → Markdown → HTML, for three
reasons and only one of them is tidiness: every block kind is handled explicitly
and an unknown one raises (a new department cannot silently render as literal
asterisks); nothing parses anything, and a Markdown parser is where an export a
mayor wrote turns into markup; and every leaf goes through `html.escape`, so an
export containing `<script>` is text on the page.

The copy uses two inline marks and no others — `**PUBLIC NOTICE**` for a lede,
`*a quoted brief*` for emphasis. That is a convention of the payload, not of
Markdown; `newspaper/render.py` passes them through because Markdown already
means that by them. `page.inline` applies them **after** escaping, so the only
tags it can emit are the two written in it, and both renderings of one payload
say the same thing.

The chrome — what the archive calls itself, the privacy notice, the navigation
labels — is `content/newspaper.json`'s `site` block, and the stylesheet is
[`content/site.css`](../content/site.css). Both are content for the reason the
rest of the paper's words are: which words the paper uses, and what it looks
like, are decisions somebody should be able to revise without being a
programmer.

## Deployment, honestly

`hosting.publishers` names remote deploy adapters and **this deployment
registers none**, so the paper is built and served locally and the build record
says `resolves_today: false` rather than implying a deployment that did not
happen. Naming an unregistered publisher is a `ConfigError`, not a quiet
fallback — the same rule `newspaper/imagery.py` applies to raster providers, for
the same reason: a typo must not present as "we tried and it wasn't there".

What *is* real today is the local server, and it is gated by the same secret:
`http.server` has one hostname, so the id becomes the first path segment instead
of the subdomain. `tests/test_hosting.py:ServingTest` starts it and fetches over
real HTTP — "the file is on disk" and "the URL answers" are different claims and
only the second one is the requirement. It checks that every back issue still
answers, that the headers are on the 404 as well as the 200, and that `/`,
`/index.html` *without the id in front of it*, a wrong id, an id missing its
last character, `..`, and the manifest are all 404. Pointing this at a real domain is a one-line config change
plus an adapter with `available()` and `deploy()`.
