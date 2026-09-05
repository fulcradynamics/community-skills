"""The edition's illustration, drawn from the edition (spec #29).

A harbour, because that is what this game is about: one city puts out a notice,
the world sends things by sea, and somebody at the quayside decides what came
off the boat. Every element in the drawing is a fact of the round rather than
decoration:

    the crates on the quay      the number of offers that arrived (Sealed Bids)
    the ribboned crate          the winning offer, labelled with its city
    the boat at the mooring     that the offers came by sea at all -- drawn when
                                any arrived, absent from a quiet round
    the dice on the dockside    the actual profit roll, pips and all
    the skyline behind          the live leaderboard, one tower per city
    the fog bank instead        the leaderboard, when config hides it (#22)
    the bunting overhead        the mayoral question's distribution: one pennant
                                per reply, the leading bucket picked out
    the rubber stamp            the open need's category and title
    the cutline                 written by content/newspaper.json, per outcome

Two elements are texture rather than information -- the halftone screen in the
sky and the gulls -- and both are here on purpose: spec #30's tone bar is part
of the requirement, and a harbour printed on flat colour with no birds in it
reads as a diagram of a harbour.

The unlabelled crates matter as much as the labelled one: a losing offer's city
is never drawn, never counted separately, and never distinguishable from any
other crate (spec #21). The palette comes from the open need's category, so
consecutive editions do not look alike, and collapses to monochrome when
``newspaper.tone.colorful`` is false (spec #30).

It is deterministic. The same game, replayed from the same seed, draws the same
picture -- which is what makes an illustration something a test can assert
about.
"""

_HEADER = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" height="%d" '
    'role="img" aria-label="%s">'
)

#: Type stack for the masthead strip. Generic families only: the SVG has to
#: render the same on a facilitator's laptop and in a player's browser.
_SERIF = "Georgia, 'Times New Roman', serif"
_SANS = "'Helvetica Neue', Helvetica, Arial, sans-serif"


def escape(text):
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


class Canvas:
    """A very small SVG builder. Enough for a harbour, and nothing else."""

    def __init__(self, width, height, alt):
        self.width = width
        self.height = height
        self.parts = [_HEADER % (width, height, width, height, escape(alt))]

    def rect(self, x, y, w, h, fill, rx=0, opacity=None, stroke=None, stroke_width=1):
        extra = ""
        if opacity is not None:
            extra += ' opacity="%s"' % opacity
        if stroke:
            extra += ' stroke="%s" stroke-width="%s"' % (stroke, stroke_width)
        self.parts.append(
            '<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="%s" fill="%s"%s/>'
            % (x, y, w, h, rx, fill, extra)
        )

    def circle(self, cx, cy, r, fill, opacity=None):
        extra = '' if opacity is None else ' opacity="%s"' % opacity
        self.parts.append(
            '<circle cx="%.1f" cy="%.1f" r="%.1f" fill="%s"%s/>' % (cx, cy, r, fill, extra)
        )

    def poly(self, points, fill, opacity=None):
        extra = '' if opacity is None else ' opacity="%s"' % opacity
        coords = " ".join("%.1f,%.1f" % (x, y) for x, y in points)
        self.parts.append('<polygon points="%s" fill="%s"%s/>' % (coords, fill, extra))

    def path(self, d, stroke, width=2, fill="none"):
        self.parts.append(
            '<path d="%s" stroke="%s" stroke-width="%s" fill="%s"/>' % (d, stroke, width, fill)
        )

    def line(self, x1, y1, x2, y2, stroke, width=2):
        self.parts.append(
            '<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" stroke-width="%s"/>'
            % (x1, y1, x2, y2, stroke, width)
        )

    def text(self, x, y, content, fill, size=16, family=_SANS, weight="normal",
             anchor="start", spacing=None, transform=None, style=None):
        extra = ""
        if spacing is not None:
            extra += ' letter-spacing="%s"' % spacing
        if transform:
            extra += ' transform="%s"' % transform
        if style:
            extra += ' font-style="%s"' % style
        self.parts.append(
            '<text x="%.1f" y="%.1f" fill="%s" font-family="%s" font-size="%s" '
            'font-weight="%s" text-anchor="%s"%s>%s</text>'
            % (x, y, fill, family, size, weight, anchor, extra, escape(content))
        )

    def halftone(self, name, spacing, radius, fill, opacity="0.4"):
        """Declare a dot-screen pattern, for filling a rect with newsprint tooth.

        A ``<pattern>`` and one filled rectangle rather than four hundred
        ``<circle>`` elements: the same screen, about two hundred bytes instead
        of twenty thousand, in a file that is committed to a repository twelve
        times per game. ``url(#name)`` is a reference into this document and
        reaches no other origin, which is the rule
        :mod:`hosting.guard` enforces over every published byte (spec #26).
        """
        self.parts.append(
            '<defs><pattern id="%s" width="%s" height="%s" patternUnits="userSpaceOnUse">'
            '<circle cx="%s" cy="%s" r="%s" fill="%s" opacity="%s"/></pattern></defs>'
            % (name, spacing, spacing, spacing / 2.0, spacing / 2.0, radius, fill, opacity)
        )
        return "url(#%s)" % name

    def group(self, transform):
        self.parts.append('<g transform="%s">' % transform)

    def ungroup(self):
        self.parts.append("</g>")

    def done(self):
        self.parts.append("</svg>")
        return "\n".join(self.parts)


def _truncate(text, limit):
    text = str(text)
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def render(scene, palette, size, labels):
    """The whole illustration, as one SVG document."""
    width, height = size
    canvas = Canvas(width, height, scene["alt"])
    ink = palette["ink"]

    # -- paper and masthead strip -----------------------------------------
    canvas.rect(0, 0, width, height, palette["paper"])
    canvas.rect(0, 0, width, 66, ink)
    canvas.text(28, 44, scene["publication"].upper(), palette["paper"], size=30,
                family=_SERIF, weight="bold", spacing="3")
    canvas.text(width - 28, 30, scene["edition_line"], palette["paper"], size=15,
                anchor="end")
    canvas.text(width - 28, 52, scene["dateline"], palette["paper"], size=13,
                anchor="end", style="italic")

    horizon = int(height * 0.62)
    quay = horizon + 26

    # -- sky, sun, water, quay --------------------------------------------
    canvas.rect(0, 66, width, horizon - 66, palette["sky"])
    # The dot screen a newspaper's own presses would have left in the sky. Under
    # everything else, so the sun, the skyline and the stamp print over it.
    canvas.rect(0, 66, width, horizon - 66,
                canvas.halftone("tooth", 14, 1.6, palette["paper"], "0.5"))
    canvas.circle(width * 0.82, 170, 54, palette["accent"], opacity="0.9")
    _skyline(canvas, scene, palette, horizon, labels)
    canvas.rect(0, horizon, width, height - horizon, palette["water"])
    canvas.rect(0, horizon, width, 26, palette["spot"], opacity="0.55")
    for index in range(7):
        y = horizon + 46 + index * 22
        canvas.path(
            "M %d %d q 24 -9 48 0 t 48 0 t 48 0 t 48 0" % (30 + (index % 2) * 26, y),
            palette["paper"], width=2,
        )
    canvas.rect(0, quay, width, 12, ink)

    _bunting(canvas, scene, palette, labels)
    _boat(canvas, scene, palette, quay)
    _crates(canvas, scene, palette, quay, labels)
    _dice(canvas, scene, palette, quay, labels)
    _crane(canvas, palette, quay)
    _gulls(canvas, palette)
    _stamp(canvas, scene, palette, width)
    _cutline(canvas, scene, palette, width, height)
    return canvas.done()


def _skyline(canvas, scene, palette, horizon, labels):
    """The leaderboard as a skyline -- or a fog bank when it is withheld (#22)."""
    board = scene.get("leaderboard")
    left, right = int(canvas.width * 0.46), canvas.width - 30
    span = right - left

    if board is None:
        # The exposure policy hides the figures, so the picture hides them too.
        # Drawing flat towers of an arbitrary height would be inventing a
        # standing, which is worse than drawing weather.
        for index in range(5):
            canvas.rect(left + index * 34, horizon - 90 - index * 8, span * 0.55,
                        70 + index * 8, palette["spot_alt"], rx=34, opacity="0.5")
        canvas.text(left + span / 2, horizon - 130, labels["no_leaderboard"],
                    palette["ink"], size=15, anchor="middle", style="italic")
        return

    tallest = max([row["profit"] for row in board] + [1])
    slot = span / max(len(board), 1)
    bar = min(slot * 0.62, 58)
    for index, row in enumerate(board):
        fraction = row["profit"] / tallest if tallest else 0
        tower = 34 + fraction * (horizon - 200)
        x = left + index * slot + (slot - bar) / 2
        fill = palette["spot"] if index % 2 == 0 else palette["spot_alt"]
        canvas.rect(x, horizon - tower, bar, tower, fill)
        # Lit windows, so a tall tower reads as a tall building rather than a bar
        # in a chart. Two columns, one row per three units of profit.
        rows = max(int(tower // 26), 1)
        for row_index in range(rows):
            for column in (0.22, 0.58):
                canvas.rect(x + bar * column, horizon - tower + 12 + row_index * 26,
                            bar * 0.2, 11, palette["accent"], opacity="0.85")
        canvas.text(x + bar / 2, horizon - tower - 20, str(row["profit_display"]),
                    palette["ink"], size=14, anchor="middle", weight="bold")
        canvas.text(x + bar / 2, horizon - 8, _truncate(row["city"], 11),
                    palette["paper"], size=12, anchor="middle")


def _bunting(canvas, scene, palette, labels):
    """One pennant per reply to the mayoral question; the leading bloc picked out."""
    wire = scene.get("wire")
    if not wire or not wire.get("answered"):
        return
    total = wire["answered"]
    leading = wire.get("largest") or 0
    x0, x1, y0, sag = 90, canvas.width * 0.62, 104, 42
    canvas.path(
        "M %.1f %.1f Q %.1f %.1f %.1f %.1f" % (x0, y0, (x0 + x1) / 2, y0 + sag, x1, y0),
        palette["ink"], width=2,
    )
    for index in range(total):
        t = (index + 1) / (total + 1)
        x = x0 + (x1 - x0) * t
        # The quadratic the string is drawn along, evaluated so the pennants hang
        # off the rope rather than near it.
        y = (1 - t) ** 2 * y0 + 2 * (1 - t) * t * (y0 + sag) + t ** 2 * y0
        fill = palette["accent"] if index < leading else palette["spot_alt"]
        canvas.poly([(x - 11, y), (x + 11, y), (x, y + 30)], fill)
    canvas.text(x0, y0 - 14, "%s: %d" % (labels["replies"], total),
                palette["ink"], size=13, style="italic")


def _crates(canvas, scene, palette, quay, labels):
    """The offers that arrived. Identical, except the one that won."""
    offers = scene.get("offers")
    if not offers:
        canvas.text(46, quay - 26, labels["quiet_quay"], palette["paper"], size=15,
                    style="italic")
        return
    size = 54
    gap = 12
    base = quay - 4
    rows = (offers - 1) // 5 + 1
    winners = set(scene.get("winner_indices") or ())
    for index in range(offers):
        column = index % 5
        row = index // 5
        x = 46 + column * (size + gap)
        y = base - size - row * (size + 8)
        won = index in winners
        canvas.rect(x, y, size, size, palette["spot"] if not won else palette["accent"],
                    rx=3, stroke=palette["ink"], stroke_width=2)
        canvas.line(x + 4, y + size / 2, x + size - 4, y + size / 2, palette["paper"], 3)
        canvas.line(x + size / 2, y + 4, x + size / 2, y + size - 4, palette["paper"], 3)
        if won:
            # A ribbon, and the only city named anywhere near the crates.
            canvas.poly(
                [(x + size / 2, y - 20), (x + size / 2 - 16, y - 2),
                 (x + size / 2 + 16, y - 2)], palette["accent"]
            )
            canvas.circle(x + size / 2, y - 24, 9, palette["paper"])
            canvas.circle(x + size / 2, y - 24, 6, palette["accent"])
    top = base - size * rows - 8 * (rows - 1)
    canvas.text(46, top - 16, "%s: %d" % (labels["offers"], offers), palette["ink"],
                size=14, weight="bold")
    # The one caption near the crates that names anybody. A losing crate has no
    # label, no distinguishing mark and no count of its own (spec #21).
    if scene.get("winner_caption"):
        canvas.text(46, quay + 34, scene["winner_caption"], palette["ink"],
                    size=15, weight="bold")


def _dice(canvas, scene, palette, quay, labels):
    """The actual roll, drawn as dice, because it is more fun than a number."""
    dice = scene.get("dice") or []
    if not dice:
        return
    size = 46
    gap = 12
    y = quay + 56
    total_width = len(dice) * size + (len(dice) - 1) * gap
    x0 = canvas.width - 40 - total_width
    canvas.text(x0 + total_width, y - 12, "%s: %s" % (labels["roll"], scene.get("profit", "")),
                palette["paper"], size=14, anchor="end", weight="bold")
    pips = {
        1: [(0.5, 0.5)],
        2: [(0.28, 0.28), (0.72, 0.72)],
        3: [(0.26, 0.26), (0.5, 0.5), (0.74, 0.74)],
        4: [(0.28, 0.28), (0.72, 0.28), (0.28, 0.72), (0.72, 0.72)],
        5: [(0.26, 0.26), (0.74, 0.26), (0.5, 0.5), (0.26, 0.74), (0.74, 0.74)],
        6: [(0.28, 0.24), (0.72, 0.24), (0.28, 0.5), (0.72, 0.5), (0.28, 0.76), (0.72, 0.76)],
    }
    for index, face in enumerate(dice):
        x = x0 + index * (size + gap)
        canvas.rect(x, y, size, size, palette["paper"], rx=8, stroke=palette["ink"],
                    stroke_width=2)
        spots = pips.get(face)
        if spots is None:
            # A die this drawing has no face for (config allows any NdS), so the
            # paper prints the number rather than guessing at a pattern.
            canvas.text(x + size / 2, y + size * 0.68, str(face), palette["ink"],
                        size=24, anchor="middle", weight="bold")
            continue
        for fx, fy in spots:
            canvas.circle(x + size * fx, y + size * fy, 4.4, palette["ink"])


def _boat(canvas, scene, palette, quay):
    """A hull at the mooring, when anything arrived by sea this round.

    Game state rather than scenery, and the smallest possible amount of it: a
    quay stacked with crates and no boat anywhere is a still life, and a round
    where nothing arrived should not print a delivery. It carries no label, no
    flag and no count -- a boat that said how many crates it brought, or whose
    they were, would be saying something spec #21 spent this whole game not
    saying.
    """
    if not scene.get("offers"):
        return
    x, y = canvas.width * 0.47, quay + 46
    canvas.poly(
        [(x - 78, y), (x + 78, y), (x + 56, y + 30), (x - 58, y + 30)], palette["ink"]
    )
    canvas.rect(x - 78, y - 7, 156, 7, palette["spot"])
    canvas.rect(x - 34, y - 34, 62, 27, palette["paper"], rx=2, stroke=palette["ink"],
                stroke_width=2)
    canvas.rect(x - 24, y - 28, 14, 13, palette["sky"])
    canvas.rect(x - 2, y - 28, 14, 13, palette["sky"])
    canvas.rect(x + 34, y - 46, 15, 39, palette["accent"], rx=2)
    canvas.line(x - 60, y - 8, x - 60, y - 62, palette["ink"], 3)
    canvas.path("M %.1f %.1f q 40 22 0 44" % (x - 57, y - 58), palette["ink"], width=2,
                fill=palette["spot_alt"])
    # A wake, so the hull sits in the water rather than on it.
    for offset in (0, 16):
        canvas.path(
            "M %.1f %.1f q 22 -8 44 0 t 44 0" % (x - 96, y + 40 + offset),
            palette["paper"], width=2,
        )


def _crane(canvas, palette, quay):
    x = canvas.width * 0.40
    canvas.rect(x, quay - 210, 12, 210, palette["ink"])
    canvas.rect(x - 76, quay - 210, 150, 11, palette["ink"])
    canvas.line(x - 60, quay - 199, x - 60, quay - 140, palette["ink"], 2)
    canvas.rect(x - 74, quay - 140, 28, 22, palette["accent"], rx=2)


def _gulls(canvas, palette):
    """Two gulls and an ambitious third. The only element that is not game state.

    Kept because a harbour without gulls does not read as a harbour, and because
    the tone bar (spec #30) is part of the requirement rather than a garnish on
    it.
    """
    for cx, cy, scale in ((250, 150, 1.0), (302, 126, 0.72), (958, 252, 0.86)):
        canvas.path(
            "M %.1f %.1f q %.1f %.1f %.1f 0 q %.1f %.1f %.1f 0"
            % (cx, cy, 9 * scale, -11 * scale, 18 * scale, 9 * scale, -11 * scale,
               18 * scale),
            palette["ink"], width=2.5,
        )


def _stamp(canvas, scene, palette, width):
    """A rubber stamp bearing the round's category and the need it opened."""
    if not scene.get("category_label"):
        return
    x, y = width * 0.585, 128
    canvas.group("rotate(-4 %.1f %.1f)" % (x + 150, y + 44))
    canvas.rect(x, y, 306, 88, "none", rx=6, stroke=palette["ink"], stroke_width=3,
                opacity="0.8")
    canvas.text(x + 153, y + 36, _truncate(scene["category_label"].upper(), 30),
                palette["ink"], size=15, anchor="middle", weight="bold", spacing="1.5")
    canvas.text(x + 153, y + 64, _truncate(scene.get("need_title") or "", 34),
                palette["ink"], size=14, anchor="middle", style="italic")
    canvas.ungroup()


def _cutline(canvas, scene, palette, width, height):
    canvas.rect(0, height - 58, width, 58, palette["ink"])
    canvas.text(28, height - 32, _truncate(scene["cutline"], 118), palette["paper"],
                size=15, family=_SERIF, style="italic")
    canvas.text(28, height - 12, scene["identity_note"], palette["paper"], size=11)
