"""The edition, as a browser gets it.

M5 renders an edition to Markdown and says, in as many words, that an HTML
template living there would be a hosting decision taken in the wrong milestone.
This is that milestone, so this is where the template lives.

It renders from the **structured edition**, not from the Markdown. Going
payload -> HTML rather than payload -> Markdown -> HTML matters for three
reasons and only one of them is tidiness:

* every block kind is handled explicitly and an unknown one raises, exactly as
  :mod:`newspaper.render` does -- a new department cannot quietly render as a
  paragraph of literal asterisks;
* nothing has to parse anything, and a Markdown parser is a place where an
  export a mayor wrote could turn into markup;
* every string that reaches the page goes through :func:`html.escape` at the
  leaf, so an export containing ``<script>`` is text on the page rather than a
  thing that happens to a reader.

The chrome -- what the archive calls itself, what it says about privacy, the
navigation labels -- comes from ``content/newspaper.json``'s ``site`` block,
for the reason the rest of the paper's words do: which words the paper uses is
a writing decision, and a writing decision in Python is one nobody can revise
without a programmer.

Three page kinds and one rule about which is where (spec #30a)
--------------------------------------------------------------
* :data:`FRONT_PAGE_NAME` -- ``index.html``, the file the paper's one address
  answers with. It carries the **newest available edition**, so a mayor who
  opens the link they were given in round 1 reads today's paper rather than a
  table of contents they then have to shop in.
* ``round-NN.html`` / :data:`FINAL_PAGE_NAME` -- every issue's own permanent
  address, which is what spec #27 promises and what the front page must not
  replace. The newest edition is therefore published twice: once as itself, and
  once as the front page. Two files, deliberately, because a redirect at the
  root would still have to resolve to one of them and a mayor who bookmarks the
  root should get the current issue rather than a hop.
* :data:`ARCHIVE_PAGE_NAME` -- ``archive.html``, the shelf: every issue ever
  printed, newest or oldest first as config says.

Every page carries the same navigation set -- latest, archive, and the adjacent
issues where they exist -- at the head and at the foot, because a reader who has
finished an edition is at the bottom of it.

The markup is structural rather than decorative: departments are sections with
their own ids, the lead department is marked as the lead, a department that
contains a table or a figure says so in its class, and the first paragraph of
the lead is marked as the opener. ``content/site.css`` is what turns that into
columns, a drop cap and a masthead; none of those decisions are taken here,
which is the same division of labour the copy already has.

Nothing here emits a link to another origin. Not a font, not an analytics tag,
not an icon. A private URL is one ``Referer`` header away from being a public
one, so the pages are self-contained and :mod:`hosting.guard` fails the build if
that ever stops being true.
"""

import re
from html import escape

from newspaper.voice import PLAYER

#: The paper's copy uses two inline marks and no others: ``**PUBLIC NOTICE**``
#: for a lede in small caps and ``*a quoted brief*`` for emphasis. That is a
#: convention of the *payload*, not of Markdown -- ``newspaper.render`` happens
#: to pass them through because Markdown already means that by them, and a page
#: that printed them as asterisks would be a page rendering the convention
#: rather than obeying it.
#:
#: Applied strictly *after* :func:`html.escape`, so the only tags that can come
#: out of it are the two written here. An export a mayor wrote containing an
#: asterisk gets the same treatment it gets in the Markdown edition, which is
#: the point: both renderings of one payload should say the same thing.
_STRONG = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*", re.DOTALL)
_EM = re.compile(r"(?<!\*)\*(?=[^\s*])([^*]+?)(?<=\S)\*(?!\*)", re.DOTALL)


def inline(text):
    """Escape, then apply the copy's two inline marks."""
    marked = _STRONG.sub(r"<strong>\1</strong>", escape(text))
    return _EM.sub(r"<em>\1</em>", marked)


#: Block heading levels to tags. A department's own title is an ``h2``, so a
#: level-3 heading inside it is an ``h3`` -- the mapping is the same one
#: :mod:`newspaper.render` uses for ``#`` characters.
_HEADING_TAGS = {1: "h1", 2: "h2", 3: "h3", 4: "h4"}

DOCTYPE = "<!DOCTYPE html>"


def block_to_html(block, extra_class=None, with_city_images=True):
    """One typed block from an edition payload. Mirrors ``block_to_markdown``.

    ``extra_class`` is a hook for the layout rather than for the payload: the
    lead department's first paragraph is marked ``opener`` so the stylesheet can
    set a drop cap on it. Which paragraph that is depends on what the department
    happens to contain, which is why it is decided in
    :func:`department_to_html` and passed in rather than guessed at in CSS.
    """
    kind = block["kind"]
    if kind == "heading":
        tag = _HEADING_TAGS.get(block.get("level", 2), "h2")
        return "<%s>%s</%s>" % (tag, inline(block["text"]), tag)
    if kind == "standfirst":
        return '<p class="standfirst">%s</p>' % inline(block["text"])
    if kind == "para":
        classes = [name for name in (extra_class, _player_voice_class(block)) if name]
        if classes:
            return '<p class="%s">%s</p>' % (escape(" ".join(classes)), inline(block["text"]))
        return "<p>%s</p>" % inline(block["text"])
    if kind == "quote":
        lines = block["text"].splitlines() or [""]
        quote = "<blockquote>%s</blockquote>" % "".join(
            "<p>%s</p>" % inline(line) for line in lines
        )
        return _in_player_voice(quote, block)
    if kind in ("aside", "note"):
        # Same on the page, different in kind -- an aside is an editorial joke
        # that config can switch off, a note is a factual footnote that always
        # prints. The class keeps that distinction available to a stylesheet
        # even though today it styles them alike.
        return '<p class="%s">%s</p>' % (kind, inline(block["text"]))
    if kind == "figure":
        # An illustration belonging to one article rather than to the edition --
        # today, a city's portrait in the last edition (spec #32). No width or
        # height, for the same reason the masthead image carries none: the
        # payload does not know them and config's would be a guess.
        if not with_city_images:
            return ""
        return (
            '<figure class="city-portrait">\n<img src="%s" alt="%s">\n'
            "<figcaption>%s</figcaption>\n</figure>"
            % (escape(block["image"]), escape(block["alt"]), inline(block["caption"]))
        )
    if kind == "list":
        items = "<ul>%s</ul>" % "".join(
            "<li>%s</li>" % inline(item) for item in block["items"]
        )
        return _in_player_voice(items, block)
    if kind == "table":
        head = "".join("<th>%s</th>" % inline(str(column)) for column in block["columns"])
        body = "".join(
            "<tr>%s</tr>" % "".join("<td>%s</td>" % inline(str(cell)) for cell in row)
            for row in block["rows"]
        )
        return "<table><thead><tr>%s</tr></thead><tbody>%s</tbody></table>" % (head, body)
    raise ValueError("no HTML renderer for block kind %r" % kind)


#: The class the stylesheet sets the mayors' own writing in, and the class on a
#: paper sentence that quotes some inside itself. Two classes rather than one
#: because they are different things on the page: a figure whose contents are
#: entirely somebody else's words, and a paragraph of the paper's that contains
#: a quotation (spec #30b).
PLAYER_VOICE_CLASS = "player-voice"
QUOTES_PLAYER_CLASS = "quotes-player"


def _player_voice_class(block):
    return QUOTES_PLAYER_CLASS if block.get("player_spans") else None


def _in_player_voice(html, block):
    """Wrap a quotation in the attribution that says whose words it is (#30b).

    A ``figure``/``figcaption`` pair, which is what HTML has for "this content
    and the line that credits it" -- the same structure the city portraits use.
    Blocks the payload does not mark as player voice are returned untouched:
    the paper's own copy needs no byline, being the paper's.
    """
    if block.get("voice") != PLAYER:
        return html
    return (
        '<figure class="%s">\n%s\n<figcaption>%s</figcaption>\n</figure>'
        % (PLAYER_VOICE_CLASS, html, inline(block["cite"]))
    )


def department_to_html(department, lead=False, with_city_images=True):
    """One department as a newspaper section (spec #30a).

    The class list is what the stylesheet lays out from, and every part of it is
    a fact about the department's own contents:

    ``lead``
        the first department in the issue -- the front-page story, set wider and
        with the opener's drop cap
    ``has-table``
        it contains the standings, which must not be broken across columns
    ``has-figures``
        it contains a city portrait (spec #32), for the same reason

    A department with neither is prose, and prose is what columns are for.
    """
    blocks = [
        block for block in department["blocks"]
        if with_city_images or block["kind"] != "figure"
    ]
    kinds = {block["kind"] for block in blocks}
    classes = ["department"]
    if lead:
        classes.append("lead")
    if "table" in kinds:
        classes.append("has-table")
    if "figure" in kinds:
        classes.append("has-figures")

    opener = None
    if lead:
        opener = next(
            (index for index, block in enumerate(blocks) if block["kind"] == "para"), None
        )
    body = "\n".join(
        block_to_html(
            block, extra_class="opener" if index == opener else None,
            with_city_images=with_city_images,
        )
        for index, block in enumerate(blocks)
    )
    return (
        '<section class="%s" id="%s">\n<h2 class="dept-title">%s</h2>\n'
        '<div class="dept-body">\n%s\n</div>\n</section>'
        % (
            " ".join(classes),
            escape(str(department["id"])),
            escape(department["title"]),
            body,
        )
    )


#: The last edition's permanent name. Not ``round-NN.html``: the final edition
#: is published in the same round as that round's own edition and is a different
#: document, so sharing a name would make one of them overwrite the other --
#: exactly what spec #27 forbids.
FINAL_PAGE_NAME = "final.html"

#: What the paper's one address answers with: the newest available edition
#: (spec #26, #30a). Its own permanent page keeps its own name.
FRONT_PAGE_NAME = "index.html"

#: The shelf. It used to be ``index.html``; the front door is now the current
#: issue, and "every prior edition still browsable" (spec #27) is this page plus
#: the permanent names it links, neither of which moved.
ARCHIVE_PAGE_NAME = "archive.html"


def edition_page_name(round_index):
    return "round-%02d.html" % round_index


def page_name_for(edition):
    """The permanent name of any edition, round or final (spec #27, #31)."""
    if edition.get("endgame"):
        return FINAL_PAGE_NAME
    return edition_page_name(edition["round"])


def _head(title, site, privacy, stylesheet=None):
    """The parts of every page that are about privacy rather than about news.

    ``noindex`` appears here *and* in ``robots.txt`` *and* in the ``X-Robots-Tag``
    header. Three copies of one instruction, because a crawler that ignores one
    of them is a normal crawler and spec #26's requirement is that the paper not
    be publicly discoverable, not that it have asked politely once.

    ``stylesheet`` is a filename or ``None``. It is a parameter rather than a
    constant because ``hosting.publish`` decides whether the stylesheet is
    published at all, and a page that linked one that was not published would be
    a page asking for a file that is not there.
    """
    lines = [
        DOCTYPE,
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        '<meta name="robots" content="%s">' % escape(privacy["meta_robots"]),
        '<meta name="referrer" content="%s">' % escape(privacy["referrer_policy"]),
        '<meta http-equiv="Content-Security-Policy" content="%s">'
        % escape(privacy["content_security_policy"]),
        "<title>%s</title>" % escape(title),
    ]
    if stylesheet:
        lines.append('<link rel="stylesheet" href="%s">' % escape(stylesheet))
    lines.append("</head>")
    return "\n".join(lines)


def _footer(site):
    return (
        '<footer class="colophon">\n'
        "<p>%s</p>\n<p>%s</p>\n<p class=\"privacy\">%s</p>\n</footer>"
        % (
            escape(site["colophon"]),
            escape(site["identity_notice"]),
            escape(site["privacy_notice"]),
        )
    )


def _document(parts):
    """Join a page's parts, dropping the ones that rendered to nothing.

    A page assembles itself out of sections that are sometimes absent -- a nav
    with no links on it, a contents strip in a two-department issue -- and an
    absent section should leave no trace rather than a blank line. The trailing
    newline is added here instead of being carried as an empty part, so "this
    section is not on this page" and "the file ends" cannot be confused.
    """
    return "\n".join(part for part in parts if part) + "\n"


def _nav(links, site, position):
    """Relative links only. Every one stays inside the private address.

    ``links`` are ``(kind, label, href)``; the kind becomes a class so the
    stylesheet can put the arrow on the right side of "previous" without
    matching on the label, which is content and may be rewritten.

    Rendered twice per page -- ``position`` is ``head`` or ``foot``. A reader who
    has just finished an edition is at the bottom of it, and a reader who has
    just arrived is at the top; making them scroll to the other end to find the
    next issue is the thing spec #30a calls a plain document.
    """
    items = "".join(
        '<a class="nav-%s" href="%s">%s</a>' % (escape(kind), escape(href), escape(label))
        for kind, label, href in links
    )
    if not items:
        return ""
    return '<nav class="issue-nav %s" aria-label="%s">%s</nav>' % (
        escape(position), escape(site["nav"]["title"]), items,
    )


def _inside_this_issue(departments, site):
    """A contents strip: every department in the issue, by name, as an anchor.

    What a newspaper prints on its front page and what a long single-column
    document usually lacks. Only worth the space once an issue has enough
    sections to get lost in, so short issues get nothing rather than a strip
    with two entries in it.
    """
    if len(departments) < 3:
        return ""
    items = "".join(
        '<a href="#%s">%s</a>' % (escape(str(department["id"])), escape(department["title"]))
        for department in departments
    )
    return '<nav class="inside" aria-label="%s"><span class="inside-label">%s</span>%s</nav>' % (
        escape(site["labels"]["inside"]), escape(site["labels"]["inside"]), items,
    )


def _issue_links(edition, site, previous_round, next_round, final_page, front,
                 permalink, with_archive):
    """The navigation every edition carries (spec #30a).

    Adjacent issues first, because that is how a reader moves through a run;
    then the two fixed destinations -- the latest issue and the shelf -- and then
    the last edition, when there is one and this is not it.

    On the front page the "latest edition" link would point at the page the
    reader is already on, so it is replaced by the one link only the front page
    needs: this issue's own permanent address, which is the link worth keeping
    (spec #27).
    """
    links = []
    if previous_round is not None:
        links.append(("previous", site["nav"]["previous"], edition_page_name(previous_round)))
    if next_round is not None:
        links.append(("next", site["nav"]["next"], edition_page_name(next_round)))
    if front:
        if permalink:
            links.append(("permalink", site["nav"]["permalink"], permalink))
    else:
        links.append(("latest", site["nav"]["latest"], FRONT_PAGE_NAME))
    if with_archive:
        links.append(("archive", site["nav"]["archive"], ARCHIVE_PAGE_NAME))
    if final_page and not edition.get("endgame"):
        links.append(("endgame", site["nav"]["endgame"], FINAL_PAGE_NAME))
    return links


def edition_page(edition, site, privacy, previous_round=None, next_round=None,
                 stylesheet=None, with_image=True, final_page=False,
                 front=False, permalink=None, with_archive=True, with_city_images=True):
    """One edition, complete, at its own permanent name.

    ``final_page`` links the last edition (spec #31) from a round edition's nav.
    It is a flag rather than another ``*_round`` argument because the final
    edition has no round of its own to name -- it shares the last one's -- and
    threading a sentinel round number through here would be a lie the nav would
    then have to decode.

    ``front`` renders the same edition as the paper's front door
    (:data:`FRONT_PAGE_NAME`, spec #30a): the copy says which issue it is and
    that it has its own permanent address, ``permalink`` is that address, and the
    "latest edition" link drops out because the reader is on it.

    ``with_archive`` is false when ``hosting.publish`` does not publish the
    shelf. The nav then omits it rather than linking a page this build did not
    write -- the same rule the stylesheet and the images already follow.
    """
    title = site["front_title"] if front else "%s — %s" % (
        edition["publication"], edition["edition_line"],
    )
    links = _issue_links(
        edition, site, previous_round, next_round, final_page, front, permalink,
        with_archive,
    )

    parts = [
        _head(title, site, privacy, stylesheet),
        '<body class="%s">' % ("front-page" if front else "issue-page"),
        _nav(links, site, "head"),
    ]
    if front:
        # The one line on the front page that is about the paper's plumbing
        # rather than about the game: which issue this is, and that the next
        # round will land beside it rather than on top of it (spec #27).
        #
        # Outside the <article>, deliberately. The article is the issue, and the
        # issue is the same document at both of its names -- a test can hold the
        # front page's article against the permanent page's and require them
        # byte-identical, which is the strongest available statement that the
        # front door really opens the newest edition rather than a summary of it.
        parts.append('<p class="front-flag">%s</p>' % escape(site["front_flag"]))
    parts.extend([
        '<article class="edition">',
        '<header class="masthead">',
        '<h1 class="nameplate">%s</h1>' % escape(edition["publication"]),
        '<p class="motto">%s</p>' % escape(edition["motto"]),
        '<p class="dateline"><strong>%s</strong> · %s · %s</p>'
        % (
            escape(edition["edition_line"]),
            escape(edition["dateline"]),
            escape(edition["price_line"]),
        ),
        '<div class="folio">',
        '<p class="weather">%s</p>' % escape(edition["weather_line"]),
        '<p class="standing">%s</p>' % escape(edition["standing_line"]),
        "</div>",
        "</header>",
    ])

    image = edition.get("image") or {}
    if with_image and image.get("filename"):
        # No width/height attributes: the edition payload does not carry the
        # image's dimensions (a raster provider's need not match the configured
        # ones), and attributes guessed from config would be wrong exactly when
        # a provider is doing something interesting.
        parts.append(
            '<figure class="edition-image">\n'
            '<img src="%s" alt="%s">\n'
            "<figcaption>%s</figcaption>\n</figure>"
            % (
                escape(image["filename"]),
                escape(image["alt"]),
                escape(image["cutline"]),
            )
        )

    departments = edition["departments"]
    parts.append(_inside_this_issue(departments, site))
    parts.append('<div class="pages">')
    parts.extend(
        department_to_html(
            department, lead=index == 0, with_city_images=with_city_images,
        )
        for index, department in enumerate(departments)
    )
    parts.append("</div>")
    if edition.get("endgame"):
        # No deadline on the last page: there is no notice open and no window
        # closing, and printing one would be the paper inviting offers it has
        # just spent three articles closing the books on (spec #31).
        parts.append('<p class="issue-foot">%s</p>' % escape(edition["foot_line"]))
    else:
        parts.append(
            '<p class="issue-foot">%s. %s %s. Offers for the current notice close %s.</p>'
            % (
                escape(edition["publication"]),
                escape(site["labels"]["round"]),
                escape(str(edition["round"])),
                escape(edition["closes"]),
            )
        )
    parts.append("</article>")
    parts.append(_nav(links, site, "foot"))
    parts.append(_footer(site))
    parts.extend(["</body>", "</html>"])
    return _document(parts)


#: How much of an edition's own writing the shelf reprints as a teaser. Long
#: enough to say what the issue was about, short enough that the shelf stays a
#: shelf rather than becoming a worse copy of the paper.
TEASER_LENGTH = 150


def issue_teaser(edition, limit=TEASER_LENGTH):
    """The lead story's own words, for the issue's entry on the shelf.

    Its headline if it printed one, else its opening line, from the issue's
    **lead department** -- not from whichever department happens to print a
    heading first, which is how a shelf ends up teasing every issue with a city
    name from the back page. A lead department with neither hands over to the
    next one, which is what happens on a quiet round.

    Headline *or* opening, not both: a department's standfirst is often the same
    sentence every week ("one city wants something..."), and a shelf of twelve
    cards with the same tail on each reads as a template rather than as a run of
    newspapers.

    Nothing new is written here and nothing is exposed that the edition did not
    already print: the string is copied out of a department that is published in
    full one click away, and it went through the same redaction and tone gates as
    part of that edition (:meth:`newspaper.edition.Paper._check`).

    Inline marks are stripped rather than rendered. A teaser is cut to length,
    and cutting ``**PUBLIC NOTICE**`` in half would print the asterisks.
    """
    for department in edition.get("departments") or ():
        blocks = department.get("blocks") or ()
        headline = next(
            (block["text"] for block in blocks
             if block.get("kind") == "heading" and block.get("level", 2) >= 3),
            None,
        )
        opening = next(
            (block["text"] for block in blocks
             if block.get("kind") in ("standfirst", "para")),
            None,
        )
        if headline or opening:
            return _shorten(headline or opening, limit)
    return None


def _shorten(text, limit):
    return _truncate(re.sub(r"\*+", "", str(text)).strip(), limit)


def _truncate(text, limit):
    if len(text) <= limit:
        return text
    cut = text[:limit].rstrip()
    # Cut at a word rather than mid-word, unless the first word is longer than
    # the whole allowance.
    if " " in cut:
        cut = cut[: cut.rfind(" ")].rstrip(" ,;:—-")
    return cut + "…"


def _issue_card(edition, site, with_images, with_city_images=True, linked=True):
    """One issue on the shelf: its picture, its name, its date and a teaser.

    ``linked`` is false when ``hosting.publish`` does not publish this issue's
    own page -- an unusual configuration, and one where the shelf should list the
    issue without offering a link to a file that is not there.
    """
    image = edition.get("image") or {}
    final = bool(edition.get("endgame"))
    href = page_name_for(edition)

    thumb = ""
    if linked and with_images and image.get("filename"):
        # The thumbnail links to the *edition*, not to the picture: a reader who
        # clicks a newspaper's front-page photograph wants the story. The
        # picture itself keeps its own small link below, which is where a reader
        # who wants the full illustration goes.
        #
        # Empty alt and hidden from assistive technology, deliberately: it is
        # the same link as the headline immediately beside it, and the picture's
        # real description is on the edition's own page, where it is the
        # edition's illustration rather than a duplicate of a link.
        thumb = (
            '<a class="thumb" href="%s" tabindex="-1" aria-hidden="true">'
            '<img src="%s" alt=""></a>'
            % (escape(href), escape(image["filename"]))
        )

    marks = []
    if with_images and image.get("filename"):
        marks.append(
            '<a class="picture" href="%s">%s</a>'
            % (escape(image["filename"]), escape(site["labels"]["image"]))
        )
    if with_city_images and final:
        marks.extend(
            '<a class="portrait" href="%s">%s</a>'
            % (escape(entry["filename"]), escape(entry["city"]))
            for entry in edition.get("city_images") or ()
            if entry.get("filename")
        )

    teaser = issue_teaser(edition)
    return "\n".join(
        part for part in (
            '<li class="issue-card%s">' % (" final" if final else ""),
            thumb,
            '<div class="issue-meta">',
            '<p class="kicker">%s</p>' % escape(site["labels"]["endgame_kicker"])
            if final else "",
            '<h3><a class="issue" href="%s">%s</a></h3>'
            % (escape(href), escape(edition["edition_line"])) if linked
            else "<h3>%s</h3>" % escape(edition["edition_line"]),
            '<p class="when">%s</p>' % escape(edition["dateline"]),
            '<p class="teaser">%s</p>' % escape(teaser) if teaser else "",
            '<p class="marks">%s</p>' % " ".join(marks) if marks else "",
            "</div>",
            "</li>",
        ) if part
    )


def archive_page(archive, entries, site, privacy, stylesheet=None, with_images=True,
                 front=False, page_names=None, with_city_images=True):
    """The shelf: every edition this paper has printed (spec #27).

    ``entries`` are the editions in the order they should be listed; the order is
    ``hosting.archive_order``'s business, not this function's.

    ``front`` renders it at :data:`FRONT_PAGE_NAME` instead of at
    :data:`ARCHIVE_PAGE_NAME`, which happens in exactly one situation: the game
    has not finished a round yet, so there is no newest edition for the front
    door to carry and the honest thing for the paper's one address to answer
    with is an empty shelf and the reason it is empty. The "latest edition" link
    drops out then, because it would point at this page.

    ``page_names`` are the issue pages this build actually publishes. ``None``
    means "all of them", which is the normal case; a build whose
    ``hosting.publish`` leaves out ``editions`` gets a shelf that lists those
    issues without linking a file it did not write.
    """
    rows = [
        _issue_card(
            edition, site, with_images, with_city_images=with_city_images,
            linked=page_names is None or page_name_for(edition) in page_names,
        )
        for edition in entries
    ]
    body = (
        '<ul class="issues">\n%s\n</ul>' % "\n".join(rows)
        if rows
        else '<p class="empty">%s</p>' % escape(site["empty_archive"])
    )
    links = [] if front or not entries else [
        ("latest", site["nav"]["latest"], FRONT_PAGE_NAME)
    ]

    return _document(
        [
            _head(
                site["front_title"] if front else site["archive_title"],
                site, privacy, stylesheet,
            ),
            '<body class="archive-page">',
            _nav(links, site, "head"),
            '<header class="masthead compact">',
            '<h1 class="nameplate">%s</h1>' % escape(archive["publication"]),
            '<p class="motto">%s</p>' % escape(archive["motto"]),
            "</header>",
            '<section class="archive">',
            '<h2 class="dept-title">%s</h2>' % escape(site["archive_heading"]),
            '<p class="standfirst">%s</p>' % escape(site["archive_blurb"]),
            body,
            '<p class="count">%d %s</p>'
            % (len(entries), escape(site["labels"]["editions_count"])),
            "</section>",
            _nav(links, site, "foot"),
            _footer(site),
            "</body>",
            "</html>",
        ]
    )


def robots_txt(site, privacy):
    """``Disallow: /``, with the paper's own explanation above it.

    The preamble is content because it is the paper talking; the two directives
    under it are mechanical and stay here. ``robots.txt`` is served without the
    address in front of it -- it is the exclusion notice, it contains no secret,
    and a crawler that has somehow found the host should be able to read it.
    """
    lines = list(site["robots_preamble"])
    lines.extend(["", "User-agent: *", "Disallow: /"])
    if privacy.get("meta_robots"):
        lines.append("# Every page also carries: %s" % privacy["meta_robots"])
    return "\n".join(lines) + "\n"
