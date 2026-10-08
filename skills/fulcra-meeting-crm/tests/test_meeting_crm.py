"""Regression tests for the failures codex-reviewer found at head 2120c380.

Each test names the defect it pins. All three P1s were data-loss shaped: a read
that failed open, a write that forgot itself, and a guard applied to the wrong
set — the same family the design notes are written about, arriving through
paths the notes did not cover.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import meeting_crm as mc  # noqa: E402


class FakeFulcra:
    """Stands in for the CLI: scripted list/download/upload outcomes."""

    def __init__(self, *, names=(), fail_list=False, fail_download=None,
                 bodies=None):
        self.names = list(names)
        self.fail_list = fail_list
        self.fail_download = fail_download or set()
        self.bodies = bodies or {}
        self.uploads = []

    def list(self, remote):
        if self.fail_list:
            raise mc.FulcraUnavailable(f"file list {remote} failed (rc=1): boom")
        return list(self.names)

    def download(self, remote, dest):
        name = remote.rsplit("/", 1)[-1]
        if name in self.fail_download:
            return False
        # Model the store, not a generous mock: a file that was never listed
        # nor uploaded DOES NOT EXIST, and download fails. The first version
        # invented a default body for any name, which made the write-time
        # re-read (round 3) read fiction and fail a correct implementation.
        if name not in self.bodies and name not in self.names:
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(self.bodies.get(name, f"# {name[:-3]}\n"))
        return True

    def upload(self, tmp, remote):
        body = Path(tmp).read_text()
        self.uploads.append((remote, body))
        # An upload changes what a later download returns — that is the point
        # of a store.
        self.bodies[remote.rsplit("/", 1)[-1]] = body
        return True


def _crm(fake, tmp_path):
    cfg = {"vault": {"people_dir": "/vault/people", "note_source_label": "meeting-crm"}}
    return mc.VaultCRM(fake, cfg, tmp_path / "cache")


# --- P1: a failed read must never look like an empty CRM ---------------------

def test_a_failed_listing_aborts_instead_of_reporting_an_empty_crm(tmp_path):
    """THE DATA-LOSS PATH. list() mapped any nonzero result to an empty list,
    so a transient auth or network failure was indistinguishable from an empty
    people directory — and the next live run resolved every existing person as
    new and wrote over their real note."""
    crm = _crm(FakeFulcra(fail_list=True), tmp_path)
    with pytest.raises(mc.FulcraUnavailable):
        crm.build_index()


def test_a_partial_download_aborts_rather_than_indexing_some_of_the_people(tmp_path):
    """A partial index carries the same hazard as an empty one: the people it
    could not read resolve as new, and a live run writes over exactly them."""
    fake = FakeFulcra(names=["Ada Lovelace.md", "Alan Turing.md"],
                      fail_download={"Alan Turing.md"})
    crm = _crm(fake, tmp_path)
    with pytest.raises(mc.FulcraUnavailable) as excinfo:
        crm.build_index()
    assert "Alan Turing" in str(excinfo.value)


def test_a_clean_listing_still_indexes(tmp_path):
    """POSITIVE CONTROL: the failure paths above must not be the only outcome."""
    fake = FakeFulcra(names=["Ada Lovelace.md"],
                      bodies={"Ada Lovelace.md": "# Ada Lovelace\n- **Email:** ada@example.com\n"})
    crm = _crm(fake, tmp_path)
    assert crm.build_index() == 1
    assert crm.resolve(email="ada@example.com")["match"] == "email"


# --- P1: a create must land in the index ------------------------------------

def test_a_second_meeting_for_a_new_person_appends_rather_than_overwriting(tmp_path):
    """codex-reviewer reproduced this directly: two upserts for the same new
    title in one run, and the second body carried only the second meeting.
    The in-memory index is the only record of this run's own writes."""
    fake = FakeFulcra()
    crm = _crm(fake, tmp_path)
    crm.build_index()
    first = crm.upsert(title="Grace Hopper", email="grace@example.com",
                       note_line="2026-08-01 — first meeting: one")
    second = crm.upsert(title="Grace Hopper", email="grace@example.com",
                        note_line="2026-08-02 — second meeting: two")
    assert first["action"] == "created"
    assert second["action"] == "updated", "the second write must not re-create"
    body = fake.uploads[-1][1]
    assert "first meeting" in body and "second meeting" in body


def test_a_new_person_is_resolvable_immediately_after_being_created(tmp_path):
    fake = FakeFulcra()
    crm = _crm(fake, tmp_path)
    crm.build_index()
    crm.upsert(title="Grace Hopper", email="grace@example.com", note_line="x")
    assert crm.resolve(email="grace@example.com")["match"] == "email"


def test_a_failed_upload_does_not_enter_the_index(tmp_path):
    """NEGATIVE CONTROL: only a write that actually landed may be remembered,
    or the next run treats a note that does not exist as existing."""
    fake = FakeFulcra()
    fake.upload = lambda tmp, remote: False
    crm = _crm(fake, tmp_path)
    crm.build_index()
    assert crm.upsert(title="Nobody", email="n@example.com",
                      note_line="x")["action"] == "failed"
    assert crm.resolve(email="n@example.com")["match"] == "none"


# --- P1: the mass-meeting cap binds the FINAL attendee set -------------------

def test_the_cap_counts_authoritative_attendees_too():
    """A 12-invitee event plus a trusted record carrying 40 more addresses wrote
    52 CRM records straight past the mass-meeting guard, because the cap was
    checked before the merge and never again."""
    src = Path(mc.__file__).read_text()
    after_merge = src.index('known.add(em)')
    second_check = src.index('skipped_mass', after_merge)
    assert second_check > after_merge, (
        "the cap must be re-applied after authoritative attendees are merged")


# --- the ingest contract, exercised through the real code path ---------------
# codex-reviewer, round 2, and the criticism was correct: the first version of
# these tests re-implemented the key expression in the test body, so it could
# only ever agree with itself. A test that copies the algorithm cannot catch a
# defect in the algorithm. These call load_summaries().

def _summaries(tmp_path, records, fake=None):
    """Run the real loader over a `file` source containing `records`."""
    src = tmp_path / "in"
    src.mkdir()
    (src / "records.json").write_text(json.dumps(records))
    cfg = {"sources": [{"type": "file", "path": str(src)}],
           "detection": {}, "vault": {"people_dir": "/vault/people"}}
    report = {"errors": []}
    return mc.load_summaries(cfg, fake or FakeFulcra(), tmp_path / "c", [], report), report


def test_external_id_makes_re_ingest_idempotent_within_one_source(tmp_path):
    """The promise ingest-format.md makes: the same record seen twice is one
    meeting, even if its title was edited between ingests."""
    got, report = _summaries(tmp_path, [
        {"date": "2026-08-01", "title": "Sync", "summary": "short",
         "external_id": "123", "source": "otter"},
        {"date": "2026-08-01", "title": "Sync (renamed)", "summary": "a much longer body",
         "external_id": "123", "source": "otter"},
    ])
    assert report["errors"] == []
    assert len(got) == 1
    assert "much longer" in got[0]["summary"]


def test_the_same_external_id_from_two_providers_is_two_meetings(tmp_path):
    """THE ROUND-2 DEFECT. External ids are provider-local, so Otter's 123 and
    Fireflies' 123 are unrelated. Keying on the bare id merged them and
    discarded one — reproduced by codex-reviewer, pinned here through the real
    loader rather than a copy of its key expression."""
    got, report = _summaries(tmp_path, [
        {"date": "2026-08-01", "title": "Board meeting", "summary": "short",
         "external_id": "123", "source": "otter"},
        {"date": "2026-08-02", "title": "Customer call", "summary": "a much longer body",
         "external_id": "123", "source": "fireflies"},
    ])
    assert report["errors"] == []
    assert len(got) == 2, "two providers' record 123 are different meetings"
    assert {r["title"] for r in got} == {"Board meeting", "Customer call"}


def test_records_without_an_external_id_still_dedupe_on_date_and_title(tmp_path):
    got, _ = _summaries(tmp_path, [
        {"date": "2026-08-01", "title": "Sync", "summary": "short"},
        {"date": "2026-08-01", "title": "sync", "summary": "a much longer body"},
        {"date": "2026-08-02", "title": "Sync", "summary": "different day"},
    ])
    assert len(got) == 2


# --- the cache must never be trusted as the current body ---------------------

def test_a_stale_cache_entry_is_refreshed_rather_than_re_uploaded(tmp_path):
    """THE ROUND-2 DATA-LOSS PATH. build_index downloaded only when the cache
    file was absent, while upsert composes the next upload FROM the indexed
    body — so a note another writer changed since the last run was re-uploaded
    stale, dropping their edits. Reproduced by codex-reviewer."""
    fake = FakeFulcra(names=["Ada Lovelace.md"],
                      bodies={"Ada Lovelace.md": "# Ada Lovelace\n- external fresh line\n"})
    crm = _crm(fake, tmp_path)
    stale = (tmp_path / "cache") / "Ada Lovelace.md"
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_text("# Ada Lovelace\n- stale cached line\n")

    crm.build_index()
    crm.upsert(title="Ada Lovelace", email=None, note_line="2026-08-29 — new: n")

    body = fake.uploads[-1][1]
    assert "external fresh line" in body, "the other writer's edit was dropped"
    assert "stale cached line" not in body


# --- round 3: the write-time staleness window --------------------------------

def test_a_note_changed_after_the_index_scan_is_recomposed_from_the_fresh_body(tmp_path):
    """THE ROUND-3 INTERLEAVING, exactly as codex reproduced it: index from
    `first store body`, another writer changes the store, then upsert. The
    upload must carry the concurrent writer's line."""
    fake = FakeFulcra(names=["Ada Lovelace.md"],
                      bodies={"Ada Lovelace.md": "# Ada Lovelace\n- first store body\n"})
    crm = _crm(fake, tmp_path)
    crm.build_index()
    fake.bodies["Ada Lovelace.md"] = "# Ada Lovelace\n- concurrent writer line\n"
    crm.upsert(title="Ada Lovelace", email=None, note_line="2026-08-29 — new: n")
    body = fake.uploads[-1][1]
    assert "concurrent writer line" in body
    assert "first store body" not in body


def test_a_failed_write_time_reread_refuses_the_write_entirely(tmp_path):
    """Round-4 REVERSAL, and codex was right: my previous version of this test
    asserted the write proceeded from the indexed body — which locked in the
    unsafe behaviour. A failed re-read is exactly when we cannot know whether
    another writer changed the note, so the only safe outcome is NO upload.
    A skipped log line is recoverable; an overwritten note is not."""
    fake = FakeFulcra(names=["Ada Lovelace.md"],
                      bodies={"Ada Lovelace.md": "# Ada Lovelace\n- indexed line\n"})
    crm = _crm(fake, tmp_path)
    crm.build_index()
    fake.fail_download = {"Ada Lovelace.md"}
    out = crm.upsert(title="Ada Lovelace", email=None,
                     note_line="2026-08-29 — followup: distinct new line")
    assert out["action"] == "skipped_unreadable"
    assert fake.uploads == [], "nothing may be uploaded over an unreadable note"


# --- round 3: sources must still compose across providers --------------------

def test_the_same_meeting_from_two_sources_keeps_the_richer_summary(tmp_path):
    """THE OTHER ROUND-3 DEFECT: namespacing external_id kept both providers'
    records for one meeting, and the shorter could shadow the richer at join
    time. The composition promise is in the README; test it through the real
    loader."""
    got, report = _summaries(tmp_path, [
        {"date": "2026-08-01", "title": "Board sync", "summary": "short",
         "external_id": "g1", "source": "gmail-relay"},
        {"date": "2026-08-01", "title": "Board sync",
         "summary": "a much longer and richer body", "external_id": "o1",
         "source": "otter", "url": "https://otter.example/o1"},
    ])
    assert report["errors"] == []
    assert len(got) == 1, "one meeting, not one per provider"
    assert "richer" in got[0]["summary"]
    assert got[0]["url"] == "https://otter.example/o1"


def test_metadata_missing_from_the_richer_record_is_filled_from_the_other(tmp_path):
    got, _ = _summaries(tmp_path, [
        {"date": "2026-08-01", "title": "Board sync", "summary": "short",
         "source": "gmail-relay", "shared_by": "Michael Tiffany"},
        {"date": "2026-08-01", "title": "Board sync",
         "summary": "a much longer and richer body", "source": "otter"},
    ])
    assert len(got) == 1
    assert got[0]["shared_by"] == "Michael Tiffany"


def test_different_meetings_on_the_same_day_are_not_merged(tmp_path):
    """NEGATIVE CONTROL for the coalescer: date alone is not identity."""
    got, _ = _summaries(tmp_path, [
        {"date": "2026-08-01", "title": "Board sync", "summary": "one",
         "source": "otter"},
        {"date": "2026-08-01", "title": "Customer call", "summary": "two",
         "source": "otter"},
    ])
    assert len(got) == 2



# --- round 4: pass 1 must merge, not discard ---------------------------------

def test_same_source_duplicate_keeps_the_short_records_metadata(tmp_path):
    """codex reproduced this: two same-(source, external_id) records, the short
    one carrying the authoritative attendee list — the richer record won and
    the authoritative list silently became an advisory one."""
    got, report = _summaries(tmp_path, [
        {"date": "2026-08-01", "title": "Sync", "summary": "short",
         "external_id": "m1", "source": "otter",
         "attendees": [{"name": "T", "email": "trusted@example.com"}],
         "attendees_authoritative": True},
        {"date": "2026-08-01", "title": "Sync",
         "summary": "a much longer and richer body",
         "external_id": "m1", "source": "otter",
         "attendees": [{"name": "A", "email": "advisory@example.com"}]},
    ])
    assert report["errors"] == []
    assert len(got) == 1
    assert "richer" in got[0]["summary"]
    assert got[0]["attendees_authoritative"] is True
    assert [a["email"] for a in got[0]["attendees"]] == ["trusted@example.com"], (
        "authority must travel WITH its list, even against a richer advisory one")


def test_authority_never_arrives_without_its_own_list_cross_source(tmp_path):
    """The same rule through pass 2."""
    got, _ = _summaries(tmp_path, [
        {"date": "2026-08-01", "title": "Board sync", "summary": "short",
         "source": "calendar-bridge",
         "attendees": [{"name": "T", "email": "trusted@example.com"}],
         "attendees_authoritative": True},
        {"date": "2026-08-01", "title": "Board sync",
         "summary": "a much longer and richer body", "source": "otter",
         "attendees": [{"name": "A", "email": "advisory@example.com"}]},
    ])
    assert len(got) == 1
    assert got[0]["attendees_authoritative"] is True
    assert [a["email"] for a in got[0]["attendees"]] == ["trusted@example.com"]
