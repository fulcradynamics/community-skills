# M10 — the reading experience, and where the front door goes

Spec #30a, with #21 and #26–#30 standing behind it. M6 put the paper at one
private address and kept every edition browsable there. This milestone is about
what happens when somebody actually opens that address: it should hand them
**today's paper**, it should let them get anywhere else in one click, and it
should look like a newspaper rather than like a report with headings.

| # | Rule | Where it is settled |
| --- | --- | --- |
| #30a | the stable URL opens the newest available edition | `hosting/build.py:_front_page`, `hosting/page.py:FRONT_PAGE_NAME` |
| #30a | latest / archive / previous / next on every edition | `hosting/page.py:_issue_links`, `_nav` |
| #30a | editorial hierarchy, columns, department treatment | `hosting/page.py:department_to_html`, `content/site.css` |
| #30a | images materially more expressive than a placeholder | `newspaper/svg.py` (halftone sky, boat at the mooring) |
| #27 | prior editions still at their own permanent names | `hosting/build.py`, `hosting/guard.py` |
| #21, #28 | the new page is audited like any other rendering | `hosting/guard.py:assert_publishable` |

```
python3 run_tests.py reading      # 36 tests: routing, navigation, layout, images
python3 run_tests.py hosting      # M6's tests, retargeted at the new shelf
python3 -m hosting.serve          # open it and read it
```

## Three page kinds, and which one the address answers with

Before this milestone `index.html` was the archive: the one URL every mayor
holds answered with a list of twelve links, and a reader had to shop before they
could read. Spec #30a says the stable URL opens the newest available edition, so
the files are now:

| File | What it is | Category in `hosting.publish` |
| --- | --- | --- |
| `index.html` | the newest available edition, entire | `front_page` |
| `round-NN.html` | that round's issue, at its permanent name | `editions` |
| `final.html` | the last edition (spec #31), permanent | `final_edition` |
| `archive.html` | the shelf: every issue ever printed | `archive_index` |

"Newest available" means the final edition once the game has ended and the last
published round before that — the same order the shelf lists them in.

The newest edition is therefore published **twice**, under two names, and that
is deliberate rather than accidental duplication:

- spec #27 promises that an edition stays where it was put, so the issue must
  keep its own permanent page whatever else happens;
- spec #30a wants the root to open it, and a redirect at the root would still
  have to resolve to one of the two — it would just cost the reader a hop and
  make the root's contents a header rather than a document.

The two copies are provably the same issue: the front page's `front-flag` line
sits *outside* `<article class="edition">`, so the article element is
byte-identical at both names and
`tests/test_reading_experience.py:FrontDoorTest` asserts exactly that. When the
game grows, the front page moves on and the back issues do not — also asserted,
by building a 3-round game and a 6-round game into the same directory.

`front_page` is the one category in `hosting.publish` that may not be dropped.
The others are things a deployment can choose not to serve; this one *is* the
URL, and a build asked to leave it out is refused with #26 and #30a quoted at it
rather than publishing a 404 at the only address anybody has. `archive_index`
stays optional, and when it is absent the navigation omits the shelf instead of
linking a page the build did not write — the rule the stylesheet and the images
already followed.

Before the first round closes there is no newest edition. The address still has
to answer, so it answers with the shelf, empty, saying the presses are warm.
Printing "round zero" would be inventing an edition.

## Navigation

Every page carries the same strip at its head **and** its foot, because a reader
who has finished an edition is at the bottom of it:

```
← Previous edition   Next edition →   Latest edition   All back issues   The final edition
```

- adjacent issues first, because that is how a reader moves through a run, and
  never invented: the first issue has no "previous" and the last has no "next";
- the last round hands the reader on to the final edition; the final edition
  does not link itself;
- on the front page, "latest edition" would point at the page the reader is
  already on, so it is replaced by *this issue's own address* — the link worth
  keeping (spec #27);
- link *kind* is a class (`nav-previous`, `nav-latest`, …), so the stylesheet
  puts the arrow on the correct side without matching on a label. The labels are
  content, in `content/newspaper.json`'s `site.nav`, and may be rewritten in any
  voice without touching CSS or Python.

Each issue also prints an **Inside this issue** strip — anchors to its own
departments — once it has three or more of them. `ServedRoutingTest` fetches
every page over real HTTP and asserts that every `href` and `src` on it is a
file the manifest actually publishes: no dangling navigation, checked from the
outside rather than trusted.

That property has to survive a reduced `hosting.publish` too, which is where a
front door that is always published gets interesting. So the build knows which
issue pages it is writing and nothing links one it is not: with `editions` left
out, the shelf lists every issue by name and date without linking it, the front
page carries the newest issue but offers no permanent address for it, and the
"previous edition" link is absent rather than broken. Two tests cover the two
directions of that rule.

## Looking like a newspaper

The markup is structural; `content/site.css` does the design. `hosting/page.py`
emits what a layout needs to be *possible*, and every part of it is a fact about
the issue rather than a decoration:

| Markup | Fact it states | What the stylesheet does with it |
| --- | --- | --- |
| `header.masthead`, `h1.nameplate`, `div.folio` | this is a paper's front matter | double rule over the nameplate, folio strip under the dateline |
| `div.pages` | the departments of one issue | a grid: one column narrow, two wide |
| `section.department.lead` | the first department is the lead | full width, larger type, drop cap |
| `p.opener` | the lead's first paragraph | `::first-letter` drop cap in the accent colour |
| `has-table` / `has-figures` | it carries the standings or a portrait | stays in one column and spans the grid |
| everything else | prose | `columns: 20rem` — the window decides how many |

The column count comes from a column *width*, not from a media query, so a
phone gets one column, a laptop two and a wide window three without this file
guessing where the boundaries are. The two media queries are for the things that
genuinely change shape: the department grid at `62rem`, the shelf's cards at
`42rem` and `72rem`. There is a dark newsprint palette and a print stylesheet.

The shelf is a shelf rather than a bulleted list: one card per issue with the
edition's own picture as a thumbnail, its edition line as a headline, its date,
and a teaser lifted from the issue itself: its **lead** department's headline,
or that department's opening line when it printed no headline — which on a
quiet round is "The Wanted column is empty today, for the first time since this
paper was founded, which was recently." Taking the first heading from *anywhere*
in the issue teases every issue with a city name off the back page, and printing
headline *and* standfirst puts the same boilerplate tail on twelve cards; both
were tried and both read as a template rather than as a run of newspapers.
`page.issue_teaser` strips inline marks before truncating, because cutting
`**PUBLIC NOTICE**` in half would print the asterisks. Nothing new is written for the shelf and nothing new is exposed: a
teaser is a string from a department that is published in full one click away,
and it passed the tone and redaction gates as part of that edition. The final
issue's card is marked and set larger, because a shelf where the ending looks
like issue thirteen buries the ending.

## What did not get weaker

Presentation work is the easiest place to lose a privacy rule, so the ones that
matter are re-checked rather than assumed:

- **the front page is audited as a rendering of its edition.** `hosting/build.py`
  files the front page's HTML alongside the permanent page's in the
  `rendered_by_round` map, so `hosting/guard.py` re-runs the identity, blind
  voting and exposure audits over it. The most-read page on the site must not be
  the least-checked one (#21, #28).
- **no page reaches another origin.** The stylesheet is still gradients and
  rules — no web font, no icon, no `@import`. M6's guard rule stands and
  `NewspaperLayoutTest` scans the published CSS again, with comments stripped so
  that the file's own explanation of the rule is not what trips it (#26).
- **the archive is still append-only.** `round-NN.html` and `final.html` names
  are untouched; `assert_archive_is_append_only` still refuses a build that
  would drop one, and M6's byte-for-byte comparison of an earlier build's
  articles still passes.
- **every issue still carries a game-informed image** (#29), and the harbour
  gained two things. A **halftone dot screen** in the sky, so the picture looks
  printed rather than filled — one `<pattern>` and one rectangle, about two
  hundred bytes, instead of four hundred `<circle>` elements in a file that is
  committed twelve times per game. And a **boat at the mooring**, drawn only
  when offers actually arrived that round, because a quay stacked with crates
  and no boat anywhere is a still life and a round where nothing arrived should
  not print a delivery. The boat carries no label, no flag and no count: a boat
  that said whose crates those were would say the one thing this game spends
  every round not saying (#21). A test now also asserts each edition's picture
  names a city from that game, carries that edition's own edition line, and is
  built out of dozens of elements rather than being a placeholder — the
  mechanical floor under #30a's "materially more expressive".
- **`config.json` is still the only source of parameters.** The one new key is
  `front_page` in `hosting.publish`; nothing about the layout is hardcoded that
  config had an opinion about, and the new copy — `site.front_title`,
  `site.front_flag`, `site.nav.title`, `site.nav.permalink`,
  `site.labels.inside`, `site.labels.endgame_kicker` — is content in
  `content/newspaper.json`, validated by `NewspaperCopy.site()` so a missing
  label fails at load rather than printing a page with a hole in it.

## The judged half

Spec #30a has a half no script can settle: whether the rendered pages read as a
convincing newspaper. `playtest/conformance.py` reports what it can decide as
finding **#30a** — the front door opens the newest issue, every issue can be
navigated — and says in its evidence that the visual judgement is the
Evaluator's, the same split #30's tone bar already has. The pages to look at are
`site/public/index.html`, `site/public/archive.html` and any `round-NN.html`,
at a desktop width and at a phone width.
