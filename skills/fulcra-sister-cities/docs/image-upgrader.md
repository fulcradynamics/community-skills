# Image Upgrader integration

Sister Cities prefers a colourful raster illustration when a working provider
exists, but it must always publish a completed round. Its deterministic SVG is
therefore the local fallback, not a placeholder to be silently replaced.

The external [Image Upgrader](https://github.com/kubla/a-particular-set-of-skills/tree/main/skills/image-upgrader)
skill provides a safe, asynchronous route to better raster artwork. It uses the
owner-scoped Fulcra `image-upgrade/v1` typed blackboard: a requester records an
Image Upgrade Request and an image-capable producer records one or more linked
Contributions after publishing and digest-verifying their artifacts.

## Boundary

Image Upgrader is not a `RasterProvider` implementation for
`newspaper/imagery.py`. It can involve a different agent, later execution, a
publisher, and review. Adding its name to `newspaper.image.raster_providers`
would correctly fail because no synchronous adapter is registered. The local
renderer must retain `svg_procedural` as its last modality preference.

This boundary preserves two properties of the game:

1. A missing producer, failed generation, or unavailable network cannot block a
   round's automatic publication.
2. A published edition is historical. A newly-arrived candidate does not rewrite
   it and cannot accidentally invalidate its redaction or provenance record.

## Request a candidate

Use Image Upgrader only after its owner configuration and producer publication
route have been set up according to the upstream skill. Create a Request for a
future edition, finale, or city portrait with an exact visual brief. Include:

- the image kind and target dimensions (`1200×700` for a round image;
  `900×560` for a city portrait);
- public, city-only scene facts that are safe to depict;
- the Daily Manifest style: warm, colourful, witty, pointed at systems rather
  than people, and never mean; and
- concrete acceptance criteria: original work, legible focal point, no readable
  invented news copy, no logos or real people, and an appropriate PNG/WebP
  representation.

Never provide a raw game snapshot, player ID or handle, exporter mapping,
ballot reference/order, non-winning export origin, private Workspace record,
or the unguessable paper URL. An already-redacted edition and its public,
city-only scene summary are the maximum safe inputs.

Image Upgrader should receive the exact Request ID. It may generate and publish
a candidate only after its configured rules verify the source and destination.
The requester then checks Contributions with that exact ID, authorises an
untrusted final host only with explicit approval, and accepts bytes only when
the declared SHA-256 digest matches.

## Adopt deliberately

Before publication, a facilitator reviews a verified candidate against the
brief and runs normal Sister Cities redaction/tone checks on all neighbouring
caption and edition copy. Record the candidate's representation URL, media
type, digest, request ID, contribution record, and review decision in the
curated publication record. Treat the image as unavailable when any verification
or review step fails, and render the built-in SVG instead.

Do not replace a completed issue's image. If a candidate arrives late, it can
be a style reference for the next game or a separately labelled future feature;
it is not evidence that the original edition used raster artwork.