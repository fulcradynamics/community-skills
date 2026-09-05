"""The whole game, end to end, in one command.

    python3 -m playtest.run              # replay, publish, build the site, report
    python3 -m playtest.run --check      # report only; write nothing
    python3 -m playtest.run --json       # the report as JSON

Three steps, in the order a real game night actually happens in:

1. **replay** the recorded game through the engine (:mod:`playtest.replay`),
   with the facilitator's desk (:mod:`facilitator`) attached to it, so every
   completed round publishes its own edition and announces it as the round ends
   -- which is the shape spec #26 requires and the shape a real game night has;
2. **verify** that the recorded game is the game the mayors were briefed on --
   see :func:`assert_schedule_matches`, which is the one integrity check this
   module owns rather than borrows;
3. **check** all thirty-five requirements against the result at once
   (:mod:`playtest.conformance`).

Publishing used to be steps of its own here, run after the game finished. It is
not any more, and the difference is the requirement: half the requirements in
step 3 -- the archive, the identity rules, the images, the exposure policy --
are properties of *published bytes*, and the other half of spec #26 is that
those bytes appear without anybody running this script. So this module no
longer publishes anything; it plays the game and reads what the desk did.
"""

import json
import os
import shutil
import sys

from engine import Config, Content
from engine.config import repo_root
from facilitator import Facilitator
from hosting.build import MANIFEST_FILENAME

from . import conformance
from .replay import replay
from .transcript import StandIns, load_transcript

def _label(config):
    """Where this game's rendered editions land, beside the sample run's.

    A label rather than a directory: :mod:`newspaper.publish` takes the parent
    from ``config.newspaper.output.editions_dir``.
    """
    return config.require_str("playtest.editions_label")


def _site_dir(config, root=None):
    """This game's own published address, which is not the live game's.

    Spec #27 makes an address an append-only archive -- an edition published
    there stays there -- so two different games cannot be built into one
    directory without one of them proposing to delete the other's back issues.
    The guard in :mod:`hosting.guard` says so out loud, which is how this was
    found. So the recorded game gets ``config.playtest.site_dir`` and the live
    game keeps ``hosting.site_dir``; the build, the manifest and the privacy
    policy are identical, and only the directory differs.
    """
    return os.path.join(root or repo_root(), config.require_str("playtest.site_dir"))


def assert_schedule_matches(game, journal, transcript=None):
    """The recorded game must be the game the mayors were briefed on.

    Each mayor's agent was shown, in advance, the notices their check-ins would
    put in front of them -- which is the only way anybody can write an export.
    That briefing came from a stand-in pass through this same engine, and it is
    only honest if the *schedule* is a function of the seed and the seating plan
    rather than of anything the mayors wrote.

    It is: which need a city opens is the one its mayor ordered (spec #13) and
    the archive records those orders; when a rotation closes depends on who is
    in the queue. Neither depends on a word anybody wrote. So a stand-in game
    and the real game must agree, need for need and round for round, and they
    differ only in what was said and who won. This asserts exactly that,
    because if it ever stopped being true the briefs would be describing a game
    nobody played.

    The stand-ins are handed the recorded *orders* and nothing else. Before
    spec #13 they needed nothing: the schedule was a function of the seed. Now
    an order is a decision, so the reference pass has to be given the same
    decisions -- otherwise this would be comparing two different games and
    finding, correctly, that they differ.
    """
    stand_ins = StandIns(
        import_choices=transcript.import_orders() if transcript is not None else None
    )
    reference, _ = replay(stand_ins, config=game.config, content=game.content)
    ours = {
        key: (need.importing_city, need.category, need.opened_round, need.closed_round)
        for key, need in game.needs.items()
    }
    theirs = {
        key: (need.importing_city, need.category, need.opened_round, need.closed_round)
        for key, need in reference.needs.items()
    }
    if ours != theirs or sorted(game.rounds) != sorted(reference.rounds):
        raise AssertionError(
            "the recorded game's schedule no longer matches the one the mayors were "
            "briefed on; the briefs describe a game nobody played. ours=%r theirs=%r"
            % (sorted(ours.items()), sorted(theirs.items()))
        )
    return True


def read_public_files(public_root):
    """Every byte the site actually serves, as text, keyed by filename."""
    files = {}
    for name in sorted(os.listdir(public_root)):
        path = os.path.join(public_root, name)
        if not os.path.isfile(path):
            continue
        with open(path, "rb") as fh:
            files[name] = fh.read().decode("utf-8", "replace")
    return files


def play(write=True, label=None, root=None):
    """Play the recorded game and check everything about the result.

    Returns ``(game, journal, report, artifacts)``. With ``write=False`` the
    editions and the site are still *built* -- they have to be, or half the
    requirements could not be checked -- but into a temporary directory, so a
    check run leaves the repository alone.

    Nothing in here publishes anything. The desk attached in
    :func:`_played_with_a_desk` does, one round at a time, as each round ends
    (spec #26); what is left afterwards is reading what it produced.
    """
    import tempfile

    config = Config.load()
    label = label if label is not None else _label(config)
    if write:
        return _played_with_a_desk(config, label, root, editions_dir=None,
                                   site_dir=_site_dir(config, root))
    with tempfile.TemporaryDirectory() as tmp:
        return _played_with_a_desk(
            config, label, root,
            editions_dir=os.path.join(tmp, "editions"),
            site_dir=os.path.join(tmp, "site"),
        )


def _clear_previous_run(config, label, root, editions_dir, site_dir):
    """Empty the directories this replay is about to fill from round 1.

    Spec #27's append-only promise is about a *live* address: an edition a
    mayor was given a link to stays where it was put. This is not that. It is
    the same recorded game being played again from its first round, and the
    editions already on disk are the previous run of it -- so the honest thing
    is to start the address again too, and let git show whether the bytes
    changed. Without it, round 1's build would be refused for removing round
    17, which is the guard being right about a situation that is not this one.

    Only ever the two directories this run publishes into, and only when they
    are the ones config names for the recorded game.
    """
    editions_dir = editions_dir or os.path.join(
        root or repo_root(), config.require_str("newspaper.output.editions_dir"), label
    )
    public = os.path.join(site_dir, config.require_str("hosting.public_subdir"))
    for directory in (editions_dir, public):
        if os.path.isdir(directory):
            shutil.rmtree(directory)
    manifest = os.path.join(site_dir, MANIFEST_FILENAME)
    if os.path.exists(manifest):
        os.remove(manifest)


def _played_with_a_desk(config, label, root, editions_dir, site_dir):
    _clear_previous_run(config, label, root, editions_dir, site_dir)
    transcript = load_transcript(root=root)
    content = Content.load(config)
    desks = []

    def attach(game):
        # Spec #26: the desk is hung on the game before the timer starts, so
        # every edition in this run is the product of a round *ending* rather
        # than of this function calling a publisher afterwards. There is no
        # publish step below to compensate if it fails.
        desks.append(
            Facilitator.attach(
                game, editions_dir=editions_dir, site_dir=site_dir, label=label,
                root=root,
            )
        )

    game, journal = replay(transcript, config=config, content=content, attach=attach)
    desk = desks[0]
    assert_schedule_matches(game, journal, transcript)
    artifacts = _artifacts(desk, transcript)
    return game, journal, conformance.run(game, journal, artifacts), artifacts


def _artifacts(desk, transcript):
    """What the desk published, in the shape the conformance pass reads.

    Assembled from the desk's own receipts rather than by re-publishing the
    game: re-publishing would produce the same bytes and prove a different
    thing (that a renderer *can* be called), which is exactly the distinction
    spec #26 draws.
    """
    published = [t for t in desk.transactions if t.published]
    last = published[-1] if published else None
    editions = {
        "label": desk.label,
        "directory": last.published["directory"] if last else None,
        "index": last.published["index"] if last else None,
        "archive": last.published["archive"] if last else None,
        "editions": [t.published["edition"] for t in published],
        "final": last.published["final"] if last else None,
        "formats": last.published["formats"] if last else None,
        "archive_prior_editions": desk.paper.archive_prior,
    }
    site = desk.transactions[-1].site or {}
    return {
        "archive": desk.paper.archive(),
        "editions": editions,
        "site": site,
        "site_id": desk.identity.site_id,
        "public_files": read_public_files(site["public_root"]),
        "transcript_data": transcript.data,
        "desk": desk,
    }


def report_path(root=None):
    return os.path.join(root or repo_root(), "playtest", "conformance.json")


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    write = "--check" not in argv
    game, journal, report, artifacts = play(write=write)

    if "--json" in argv:
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
        return 1 if report.failures else 0

    print(
        "Sister Cities -- %d mayors, %d rounds, %d import needs, %d offers"
        % (len(game.players), len(game.rounds), len(game.needs), len(game.submissions))
    )
    print(
        "  editions -> %s\n  site     -> %s (%d files at the private address)"
        % (
            os.path.relpath(artifacts["editions"]["directory"], repo_root()),
            os.path.relpath(artifacts["site"]["public_root"], repo_root()),
            len(artifacts["public_files"]),
        )
    )
    print("\nspec conformance, all thirty-five at once:")
    print(report.to_text())
    counts = report.to_dict()["counts"]
    print(
        "\n%d checked: %s"
        % (len(report.findings), ", ".join(
            "%d %s" % (count, status) for status, count in sorted(counts.items())
        ))
    )
    if report.judged:
        print(
            "the %d judged findings carry their evidence and are for the Evaluator, "
            "not for this script" % len(report.judged)
        )
    if write:
        with open(report_path(), "w", encoding="utf-8") as fh:
            fh.write(json.dumps(report.to_dict(), indent=2, ensure_ascii=False) + "\n")
        print("report   -> playtest/conformance.json")
    return 1 if report.failures else 0


if __name__ == "__main__":  # pragma: no cover - CLI
    sys.exit(main())
