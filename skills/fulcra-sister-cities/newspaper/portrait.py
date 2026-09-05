"""The last edition's two pictures: the finale, and one portrait per city.

Spec #31 asks the endgame to crown a winner; spec #32 asks for a description
*and an image* per city, informed by that city's actual history, with its
non-chosen exports treated as excess -- and says to use spec #29's modality
policy, which is raster where a provider exists and a deterministic,
game-state-informed illustration otherwise. So these are drawn the way
:mod:`newspaper.svg` draws a round: from facts, deterministically, with nothing
decorative that the game did not contain.

    the finale                        the whole world on the last day
      the towers                      final cumulative profit, one per city
      the crown                       over the tallest, or over both when shared
      the fog bank instead            the standings, when config withholds them
      the stack on the quay           every offer sent and not chosen, in total,
                                      unlabelled and unattributed (spec #21)

    a city portrait                   one city at the end of its game
      the skyline                     that city's own final standing
      the stamps                      the notices it opened
      the ribboned crates             the offers of its own the world kept
      the plain crates                the offers it received and declined
      the shed, door shut and sealed  the offers it sent that nobody chose

That last element is the whole argument of this milestone in one drawing. A
city's own unchosen exports are real, and they are the one part of its excess
that cannot be itemised without naming the sender of a losing offer, which spec
#21 forbids permanently. So the portrait draws the door and stops: no count, no
label, no crate. Everything else in the picture is public.
"""

from .svg import _SANS, _SERIF, Canvas, _truncate

#: How many crates a pile is willing to draw before it starts counting instead.
#: A picture of forty crates is a picture of a texture; the number is printed
#: beside it either way, so nothing is lost but the drawing stays legible.
MAX_DRAWN_CRATES = 18


def _masthead(canvas, scene, palette, height=60):
    ink = palette["ink"]
    canvas.rect(0, 0, canvas.width, canvas.height, palette["paper"])
    canvas.rect(0, 0, canvas.width, height, ink)
    canvas.text(24, height - 20, scene["publication"].upper(), palette["paper"],
                size=26, family=_SERIF, weight="bold", spacing="3")
    canvas.text(canvas.width - 24, 26, scene["edition_line"], palette["paper"],
                size=14, anchor="end")
    canvas.text(canvas.width - 24, 46, scene["dateline"], palette["paper"], size=12,
                anchor="end", style="italic")
    return height


def _cutline(canvas, scene, palette, band=54):
    canvas.rect(0, canvas.height - band, canvas.width, band, palette["ink"])
    canvas.text(24, canvas.height - band + 26, _truncate(scene["cutline"], 112),
                palette["paper"], size=14, family=_SERIF, style="italic")
    canvas.text(24, canvas.height - 12, scene["identity_note"], palette["paper"], size=10)


def _water(canvas, palette, horizon, quay):
    canvas.rect(0, horizon, canvas.width, canvas.height - horizon, palette["water"])
    canvas.rect(0, horizon, canvas.width, 20, palette["spot"], opacity="0.5")
    for index in range(5):
        y = horizon + 36 + index * 20
        canvas.path(
            "M %d %d q 22 -8 44 0 t 44 0 t 44 0" % (26 + (index % 2) * 22, y),
            palette["paper"], width=2,
        )
    canvas.rect(0, quay, canvas.width, 10, palette["ink"])


def _crate(canvas, x, y, size, palette, ribboned=False):
    canvas.rect(x, y, size, size, palette["accent"] if ribboned else palette["spot"],
                rx=3, stroke=palette["ink"], stroke_width=2)
    canvas.line(x + 3, y + size / 2, x + size - 3, y + size / 2, palette["paper"], 2)
    canvas.line(x + size / 2, y + 3, x + size / 2, y + size - 3, palette["paper"], 2)
    if ribboned:
        canvas.poly(
            [(x + size / 2, y - 14), (x + size / 2 - 11, y - 1), (x + size / 2 + 11, y - 1)],
            palette["accent"],
        )
        canvas.circle(x + size / 2, y - 17, 6, palette["paper"])
        canvas.circle(x + size / 2, y - 17, 4, palette["accent"])


def _pile(canvas, x0, base, count, palette, label, per_row=6, size=34, ribboned=False):
    """``count`` crates, stacked, with the real number printed above them."""
    drawn = min(count, MAX_DRAWN_CRATES)
    rows = 0
    for index in range(drawn):
        column = index % per_row
        row = index // per_row
        rows = max(rows, row + 1)
        _crate(
            canvas,
            x0 + column * (size + 8),
            base - size - row * (size + 6),
            size, palette, ribboned=ribboned,
        )
    top = base - size * max(rows, 1) - 6 * max(rows - 1, 0)
    canvas.text(x0, top - 22, "%s: %d" % (label, count), palette["ink"], size=13,
                weight="bold")
    if count > drawn:
        canvas.text(x0, top - 6, "(%d drawn)" % drawn, palette["ink"], size=11,
                    style="italic")
    return top


def _sealed_shed(canvas, x, base, palette, label):
    """A shed with the door shut, for the excess that is never itemised (#21)."""
    width, height = 150, 104
    y = base - height
    canvas.rect(x, y, width, height, palette["spot_alt"], rx=2, stroke=palette["ink"],
                stroke_width=2)
    canvas.poly([(x - 8, y), (x + width + 8, y), (x + width / 2, y - 34)], palette["ink"])
    # The door: shut, and stamped rather than labelled, because a label with a
    # number on it would be the count this drawing exists not to give.
    door_w, door_h = 56, 68
    door_x = x + (width - door_w) / 2
    canvas.rect(door_x, base - door_h, door_w, door_h, palette["paper"],
                stroke=palette["ink"], stroke_width=2)
    canvas.line(door_x + door_w / 2, base - door_h, door_x + door_w / 2, base,
                palette["ink"], 2)
    canvas.circle(door_x + door_w / 2, base - door_h / 2, 11, palette["accent"])
    canvas.text(x + width / 2, y - 42, _truncate(label, 34), palette["ink"], size=12,
                anchor="middle", style="italic")


def _gulls(canvas, palette, positions):
    for cx, cy, scale in positions:
        canvas.path(
            "M %.1f %.1f q %.1f %.1f %.1f 0 q %.1f %.1f %.1f 0"
            % (cx, cy, 8 * scale, -10 * scale, 16 * scale, 8 * scale, -10 * scale,
               16 * scale),
            palette["ink"], width=2.2,
        )


# -- the finale -----------------------------------------------------------

def render_finale(scene, palette, size, labels):
    """The whole world on the last day, with the crown over the tallest tower."""
    width, height = size
    canvas = Canvas(width, height, scene["alt"])
    top = _masthead(canvas, scene, palette, height=66)

    horizon = int(height * 0.60)
    quay = horizon + 24
    canvas.rect(0, top, width, horizon - top, palette["sky"])
    canvas.circle(width * 0.86, 150, 46, palette["accent"], opacity="0.9")
    _final_skyline(canvas, scene, palette, top, horizon, labels)
    _water(canvas, palette, horizon, quay)

    excess = scene.get("excess_total") or 0
    if excess:
        _pile(canvas, 40, quay - 4, excess, palette, labels["excess_pile"], per_row=6)
    else:
        canvas.text(40, quay - 24, labels["quay"], palette["paper"], size=14,
                    style="italic")

    _crowned_names(canvas, scene, palette, quay, labels)
    _gulls(canvas, palette, ((width * 0.30, 130, 1.0), (width * 0.34, 108, 0.7)))
    canvas.text(width - 28, quay + 40, "%s: %d" % (labels["final_standings"],
                                                   scene.get("n_cities") or 0),
                palette["paper"], size=13, anchor="end")
    _cutline(canvas, scene, palette, band=58)
    return canvas.done()


def _final_skyline(canvas, scene, palette, top, horizon, labels):
    """One tower per city, ranked by final profit, crowned at the top."""
    board = scene.get("leaderboard")
    left, right = int(canvas.width * 0.36), canvas.width - 34
    span = right - left
    crowned = set(scene.get("crowned_cities") or ())

    if board is None:
        # The standings were never printed, so the last picture does not print
        # them either. The crown still goes somewhere: the winner's name is not a
        # figure (see engine.views.endgame_briefing).
        for index in range(4):
            canvas.rect(left + index * 40, horizon - 110 - index * 10, span * 0.5,
                        86 + index * 10, palette["spot_alt"], rx=36, opacity="0.5")
        canvas.text(left + span / 2, horizon - 150, labels["no_figures"],
                    palette["ink"], size=15, anchor="middle", style="italic")
        return

    tallest = max([row["profit"] for row in board] + [1])
    slot = span / max(len(board), 1)
    bar = min(slot * 0.6, 66)
    for index, row in enumerate(board):
        fraction = row["profit"] / tallest if tallest else 0
        tower = 40 + fraction * (horizon - top - 150)
        x = left + index * slot + (slot - bar) / 2
        fill = palette["spot"] if row["city"] not in crowned else palette["accent"]
        canvas.rect(x, horizon - tower, bar, tower, fill)
        rows = max(int(tower // 24), 1)
        for row_index in range(rows):
            for column in (0.22, 0.58):
                canvas.rect(x + bar * column, horizon - tower + 10 + row_index * 24,
                            bar * 0.2, 10, palette["paper"], opacity="0.8")
        canvas.text(x + bar / 2, horizon - tower - 18, str(row["profit_display"]),
                    palette["ink"], size=13, anchor="middle", weight="bold")
        canvas.text(x + bar / 2, horizon - 8, _truncate(row["city"], 12),
                    palette["paper"], size=11, anchor="middle")
        if row["city"] in crowned:
            _crown(canvas, x + bar / 2, horizon - tower - 34, palette)


def _crown(canvas, cx, base, palette):
    """A small crown: three points, a band, and no pretensions."""
    canvas.poly(
        [(cx - 22, base), (cx - 22, base - 20), (cx - 11, base - 9), (cx, base - 24),
         (cx + 11, base - 9), (cx + 22, base - 20), (cx + 22, base)],
        palette["accent"],
    )
    canvas.rect(cx - 22, base, 44, 7, palette["ink"], rx=2)


def _crowned_names(canvas, scene, palette, quay, labels):
    cities = list(scene.get("crowned_cities") or ())
    if not cities:
        return
    shared = bool(scene.get("crown_shared"))
    text = "%s: %s%s" % (
        labels["crown"], ", ".join(cities), " (%s)" % labels["shared_crown"] if shared else "",
    )
    canvas.text(40, quay + 40, _truncate(text, 78), palette["paper"], size=16,
                family=_SERIF, weight="bold")


# -- one city -------------------------------------------------------------

def render_city(scene, palette, size, labels):
    """One city at the end of its game (spec #32)."""
    width, height = size
    canvas = Canvas(width, height, scene["alt"])
    top = _masthead(canvas, scene, palette, height=58)

    horizon = int(height * 0.58)
    quay = horizon + 22
    canvas.rect(0, top, width, horizon - top, palette["sky"])
    canvas.circle(width * 0.14, 128, 38, palette["accent"], opacity="0.85")

    _city_name(canvas, scene, palette, top)
    _city_towers(canvas, scene, palette, top, horizon, labels)
    _notice_stamps(canvas, scene, palette, top)
    _water(canvas, palette, horizon, quay)

    kept = scene.get("kept") or 0
    declined = scene.get("declined_on_quay") or 0
    if kept:
        _pile(canvas, 30, quay - 4, kept, palette, labels["kept"], per_row=4, size=30,
              ribboned=True)
    plain_x = 30 + (4 * 38 + 24 if kept else 0)
    if declined:
        _pile(canvas, plain_x, quay - 4, declined, palette, labels["excess_pile"],
              per_row=4, size=30)
    if not kept and not declined:
        canvas.text(30, quay - 22, labels["quay"], palette["paper"], size=13,
                    style="italic")

    if scene.get("sealed_shed"):
        _sealed_shed(canvas, width - 190, quay - 4, palette, labels["sealed_shed"])
    _gulls(canvas, palette, ((width * 0.62, 118, 0.9),))
    _cutline(canvas, scene, palette, band=52)
    return canvas.done()


def _city_name(canvas, scene, palette, top):
    canvas.text(28, top + 42, scene["city"], palette["ink"], size=34, family=_SERIF,
                weight="bold")
    standing = scene.get("standing_line")
    if standing:
        canvas.text(28, top + 66, _truncate(standing, 60), palette["ink"], size=14,
                    family=_SANS, style="italic")


def _city_towers(canvas, scene, palette, top, horizon, labels):
    """This city's own standing, as its own skyline. Fog when it is withheld."""
    share = scene.get("profit_share")
    x0 = int(canvas.width * 0.34)
    span = int(canvas.width * 0.42)
    if share is None:
        for index in range(3):
            canvas.rect(x0 + index * 44, horizon - 96 - index * 8, span * 0.5,
                        76 + index * 8, palette["spot_alt"], rx=30, opacity="0.5")
        canvas.text(x0 + span / 2, horizon - 128, labels["no_figures"], palette["ink"],
                    size=13, anchor="middle", style="italic")
        return
    heights = (0.55, 1.0, 0.72, 0.86)
    room = horizon - top - 110
    for index, factor in enumerate(heights):
        tower = 30 + share * factor * room
        bar = span / (len(heights) + 1)
        x = x0 + index * bar
        canvas.rect(x, horizon - tower, bar * 0.78, tower,
                    palette["spot"] if index % 2 == 0 else palette["spot_alt"])
        rows = max(int(tower // 22), 1)
        for row_index in range(rows):
            canvas.rect(x + bar * 0.2, horizon - tower + 9 + row_index * 22,
                        bar * 0.16, 9, palette["paper"], opacity="0.75")
    if scene.get("profit_display") is not None:
        canvas.text(x0, horizon - 30 - share * room, str(scene["profit_display"]),
                    palette["ink"], size=15, weight="bold")


def _notice_stamps(canvas, scene, palette, top):
    """A rubber stamp per notice this city opened, over the sky."""
    notices = list(scene.get("notices") or ())[:2]
    if not notices:
        return
    for index, notice in enumerate(notices):
        x = canvas.width * 0.44 + index * 24
        y = top + 24 + index * 60
        canvas.group("rotate(%d %.1f %.1f)" % (-4 + index * 7, x + 130, y + 34))
        canvas.rect(x, y, 262, 68, "none", rx=5, stroke=palette["ink"], stroke_width=3,
                    opacity="0.75")
        canvas.text(x + 131, y + 28, _truncate(notice["category_label"].upper(), 28),
                    palette["ink"], size=13, anchor="middle", weight="bold", spacing="1.2")
        canvas.text(x + 131, y + 52, _truncate(notice["title"], 32), palette["ink"],
                    size=12, anchor="middle", style="italic")
        canvas.ungroup()
