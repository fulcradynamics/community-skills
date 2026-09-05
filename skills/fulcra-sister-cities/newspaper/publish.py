"""Writing editions to disk.

    python3 -m newspaper.publish                  # simulate a game, publish it
    python3 -m newspaper.publish --label my-game  # ... under editions/my-game/

This module stops at the filesystem, deliberately: it writes the run as files a
person can read in the repository. Serving the same editions at the paper's
fixed, unguessable, non-publicly-discoverable URL with the whole archive
browsable (spec #26, #27) is :func:`hosting.build_site`, which renders the same
edition payloads as HTML rather than reading these files -- so neither output is
downstream of the other, and a page is never a parsed Markdown document.

Layout, under ``config.newspaper.output.editions_dir``::

    editions/<label>/index.md          the archive index (spec #27)
    editions/<label>/round-01.md       the edition, as it reads
    editions/<label>/round-01.json     the same edition, structured
    editions/<label>/round-01.svg      that edition's image (spec #29)
    editions/<label>/final.md          the last edition (spec #31, #32)
    editions/<label>/endgame.svg       its finale illustration
    editions/<label>/city-hobart.svg   one portrait per city (spec #32)
    editions/<label>/archive.json      every edition plus the run's provenance

Which of those three per-edition formats are written is
``config.newspaper.output.formats``. The final edition takes the same three and
adds its portraits to the image format, because a portrait is an image and
switching images off should switch all of them off.
"""

import copy as copy_module
import json
import os
import sys

from engine.config import repo_root
from engine.errors import ConfigError

from .edition import Paper
from .render import FINAL_STEM, archive_index_to_markdown, to_markdown

FORMAT_JSON = "json"
FORMAT_MARKDOWN = "markdown"
FORMAT_IMAGE = "image"
KNOWN_FORMATS = (FORMAT_JSON, FORMAT_MARKDOWN, FORMAT_IMAGE)


def _formats(config):
    formats = config.require("newspaper.output.formats")
    if not isinstance(formats, list) or not formats:
        raise ConfigError(
            "config.newspaper.output.formats must be a non-empty list of %s"
            % list(KNOWN_FORMATS)
        )
    unknown = [name for name in formats if name not in KNOWN_FORMATS]
    if unknown:
        raise ConfigError(
            "config.newspaper.output.formats names %s; known formats are %s"
            % (unknown, list(KNOWN_FORMATS))
        )
    return formats


def without_image_content(edition):
    """The edition, minus the image bytes.

    The JSON artifact records the image's provenance -- modality, provider, the
    whole list of what was considered and why (spec #29) -- and points at the
    file. It does not inline a 30KB SVG into every payload; the picture is next
    to it on disk.
    """
    trimmed = copy_module.deepcopy(edition)
    for image in [trimmed.get("image")] + list(trimmed.get("city_images") or ()):
        if isinstance(image, dict):
            image.pop("content", None)
            image["file"] = image.get("filename")
    return trimmed


def _write_edition(root, stem, edition, formats):
    """One edition's files on disk, in whichever formats config asks for.

    Shared by the round editions and the final one, which differ in their stem
    and in the fact that the final edition also carries a portrait per city
    (spec #32). Portraits are written under ``image``, not a format of their
    own: a portrait is an image, and a facilitator who turned images off did not
    mean "except the last twelve".
    """
    files = {}
    if FORMAT_MARKDOWN in formats:
        files["markdown"] = _write(root, "%s.md" % stem, to_markdown(edition))
    if FORMAT_JSON in formats:
        files["json"] = _write(
            root, "%s.json" % stem,
            json.dumps(without_image_content(edition), indent=2, ensure_ascii=False) + "\n",
        )
    if FORMAT_IMAGE in formats:
        images = [edition.get("image")] + list(edition.get("city_images") or ())
        written = [
            _write(root, image["filename"], image["content"])
            for image in images
            if isinstance(image, dict) and image.get("filename") and image.get("content")
        ]
        if written:
            files["image"] = written[0]
        if len(written) > 1:
            files["city_images"] = written[1:]
    return files


def publish_round(engine, round_index, label="game", out_dir=None, paper=None,
                  edition=None):
    """Write **one** completed round's edition, and refresh the index (spec #26).

    The per-round door, for the facilitator's completed-round transaction: it
    writes the files for exactly one edition, leaves every earlier edition
    untouched on disk (spec #27 -- an archive, not an overwrite), and rewrites
    only the two documents that describe the whole run, the index and
    ``archive.json``.

    :func:`publish_game` remains the whole-run door, for a game that is being
    republished from scratch. The two agree by construction: both write the
    same payloads through :func:`_write_edition`.
    """
    paper = paper or Paper(engine)
    formats = _formats(engine.config)
    configured_dir = engine.config.require_str("newspaper.output.editions_dir")
    root = out_dir or os.path.join(repo_root(), configured_dir, label)
    os.makedirs(root, exist_ok=True)

    edition = edition if edition is not None else paper.edition(round_index)
    files = _write_edition(root, "round-%02d" % round_index, edition, formats)
    image = edition.get("image") or {}
    written = {
        "round": round_index,
        "files": files,
        "image_modality": (image.get("provenance") or {}).get("modality"),
        "image_provider": (image.get("provenance") or {}).get("provider"),
        "departments": [department["id"] for department in edition["departments"]],
    }

    archive = paper.archive()
    final = archive.get("final")
    final_written = None
    if final is not None:
        # The game ended with this round, so the last edition goes out beside it
        # (spec #31) rather than waiting for somebody to run a script.
        final_files = _write_edition(root, FINAL_STEM, final, formats)
        final_image = final.get("image") or {}
        final_written = {
            "round": final["round"],
            "files": final_files,
            "image_modality": (final_image.get("provenance") or {}).get("modality"),
            "image_provider": (final_image.get("provenance") or {}).get("provider"),
            "departments": [department["id"] for department in final["departments"]],
            "cities": [entry["city"] for entry in final.get("city_images") or ()],
        }

    index = _write(root, "index.md", archive_index_to_markdown(archive))
    archive_json = _write(
        root, "archive.json",
        json.dumps(
            dict(
                archive,
                editions=[without_image_content(e) for e in archive["editions"]],
                final=None if final is None else without_image_content(final),
            ),
            indent=2, ensure_ascii=False,
        ) + "\n",
    )
    return {
        "label": label,
        "directory": root,
        "index": index,
        "archive": archive_json,
        "edition": written,
        "final": final_written,
        "formats": formats,
        "editions_on_disk": len(archive["editions"]),
        "spec": "#26, #27",
    }


def publish_game(engine, label="game", out_dir=None, paper=None):
    """Render and write every edition of ``engine``'s game so far.

    Returns a manifest of what was written -- paths, the image modality actually
    used per edition, and the round each edition covers -- so a caller (or a
    test) can assert on the result without re-reading the files.
    """
    paper = paper or Paper(engine)
    formats = _formats(engine.config)
    # Read whether or not it is used, so that config.json stays the single source
    # for where editions live even when a caller (a test, a facilitator trying
    # something out) points somewhere else for one run.
    configured_dir = engine.config.require_str("newspaper.output.editions_dir")
    root = out_dir or os.path.join(repo_root(), configured_dir, label)
    os.makedirs(root, exist_ok=True)

    archive = paper.archive()
    written = []
    for edition in archive["editions"]:
        files = _write_edition(root, "round-%02d" % edition["round"], edition, formats)
        image = edition.get("image") or {}
        written.append(
            {
                "round": edition["round"],
                "files": files,
                "image_modality": (image.get("provenance") or {}).get("modality"),
                "image_provider": (image.get("provenance") or {}).get("provider"),
                "departments": [department["id"] for department in edition["departments"]],
            }
        )

    # The last edition, written beside the round editions and never over one
    # (spec #27, #31). `None` while the game is still running, which is most of
    # the time this function is called.
    final = archive.get("final")
    final_written = None
    if final is not None:
        files = _write_edition(root, FINAL_STEM, final, formats)
        image = final.get("image") or {}
        final_written = {
            "round": final["round"],
            "files": files,
            "image_modality": (image.get("provenance") or {}).get("modality"),
            "image_provider": (image.get("provenance") or {}).get("provider"),
            "departments": [department["id"] for department in final["departments"]],
            "cities": [entry["city"] for entry in final.get("city_images") or ()],
        }

    index = _write(root, "index.md", archive_index_to_markdown(archive))
    archive_json = _write(
        root, "archive.json",
        json.dumps(
            dict(
                archive,
                editions=[without_image_content(e) for e in archive["editions"]],
                final=None if final is None else without_image_content(final),
            ),
            indent=2, ensure_ascii=False,
        ) + "\n",
    )
    return {
        "label": label,
        "directory": root,
        "index": index,
        "archive": archive_json,
        "editions": written,
        "final": final_written,
        "formats": formats,
        "archive_prior_editions": archive["archive_prior_editions"],
    }


def _write(root, name, content):
    path = os.path.join(root, name)
    mode, encoding = ("wb", None) if isinstance(content, bytes) else ("w", "utf-8")
    with open(path, mode, encoding=encoding) as fh:
        fh.write(content)
    return path


def main(argv=None):
    from .sample import sample_game

    argv = list(sys.argv[1:] if argv is None else argv)
    label = "sample-game"
    if "--label" in argv:
        label = argv[argv.index("--label") + 1]
    manifest = publish_game(sample_game(), label=label)
    print("wrote %d editions to %s" % (len(manifest["editions"]), manifest["directory"]))
    for entry in manifest["editions"]:
        print(
            "  round %s -> %s (image: %s via %s)"
            % (
                entry["round"],
                os.path.basename(entry["files"].get("markdown", "-")),
                entry["image_modality"],
                entry["image_provider"],
            )
        )
    final = manifest["final"]
    if final:
        print(
            "  final -> %s (%s; %d city portrait%s)"
            % (
                os.path.basename(final["files"].get("markdown", "-")),
                ", ".join(final["departments"]),
                len(final["cities"]),
                "" if len(final["cities"]) == 1 else "s",
            )
        )
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI
    sys.exit(main())
