#!/usr/bin/env python3
"""meeting_crm.py — keep a Fulcra Vault CRM fed from meetings.

The calendar says WHO was in the room; a meeting-summary email says WHAT was
discussed. This joins them and writes person notes to Fulcra Vault.

Everything user-, machine- or account-specific comes from --config (see
config.example.json). Nothing of the sort belongs in this file.

Dry-run by default. --live writes. Read references/design-notes.md before
relaxing any guard: each exists because it corrupted real data.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# `fulcra-api file list` may emit a bare name or a stat row:
#   "6KiB    2026-08-01 10:39AM UTC  <name>"
_STAT_ROW = re.compile(r"^\s*\S+\s+\d{4}-\d{2}-\d{2}\s+\d{1,2}:\d{2}[AP]M\s+\S+\s+(.+?)\s*$")
_FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)
_EMAIL = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)


class ConfigError(RuntimeError):
    pass


# --------------------------------------------------------------------------- config
def load_config(path: str) -> dict:
    cfg = json.loads(Path(path).read_text())
    if not cfg.get("identity", {}).get("self_emails"):
        raise ConfigError("identity.self_emails is required: without it you write yourself into your own CRM")
    return cfg


def cli_base(cfg: dict) -> list[str]:
    """Resolve the fulcra-api CLI: env first, then config, then PATH.

    Env wins so a deployment can pin a CLI without editing config, which is the
    same precedence the fulcra-vault store uses.
    """
    env_cli = os.environ.get("FULCRA_CLI_COMMAND", "").strip()
    if env_cli:
        return env_cli.split()
    pinned = (cfg.get("cli") or {}).get("fulcra_api")
    if pinned:
        return [pinned]
    found = shutil.which("fulcra-api")
    if found:
        return [found]
    raise ConfigError("no fulcra-api found: set $FULCRA_CLI_COMMAND or cli.fulcra_api")


def cli_version(base: list[str]) -> str | None:
    """Read the CLI's installed version.

    `fulcra-api` exposes NO `--version` flag (verified 0.1.40), so asking it
    directly yields a usage banner and any regex over that silently returns
    None — a version guard that never fires is worse than none at all. Instead
    resolve the executable, find its sibling interpreter, and read the dist
    metadata. Returns None only when the layout is genuinely unrecognisable.
    """
    exe = shutil.which(base[0]) or base[0]
    try:
        real = Path(exe).resolve()
    except OSError:
        return None
    for py in (real.parent / "python", real.parent / "python3"):
        if not py.exists():
            continue
        r = subprocess.run(
            [str(py), "-c",
             "import importlib.metadata as m;print(m.version('fulcra-api'))"],
            capture_output=True, text=True, timeout=30)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    return None


def check_version(cfg: dict, base: list[str]) -> str | None:
    """A stale CLI fails in ways that look like missing DATA, not a broken tool.

    One stale client crashed on a changed API shape and the vault reported
    'download failed for /vault/meta.json' -- which reads as a missing file. It
    cost hours; the file was there the whole time. Fail loudly here instead.
    """
    got_s = cli_version(base)
    want = (cfg.get("cli") or {}).get("min_version")
    if not want:
        return got_s
    if got_s is None:
        # Unknown is not OK when a minimum was demanded -- say so rather than
        # proceeding on an unverified tool.
        raise ConfigError(
            f"cannot determine fulcra-api version (min {want} required). "
            f"Pin a known-good CLI with $FULCRA_CLI_COMMAND, or clear "
            f"cli.min_version to proceed unchecked.")
    got = tuple(int(x) for x in re.findall(r"\d+", got_s)[:3])
    need = tuple(int(x) for x in want.split("."))
    if got < need:
        raise ConfigError(
            f"fulcra-api {got_s} is older than the required {want}. A stale CLI "
            f"surfaces as MISSING DATA, not a broken tool. Pin a newer one with "
            f"$FULCRA_CLI_COMMAND.")
    return got_s


# --------------------------------------------------------------------------- fulcra io
class FulcraUnavailable(RuntimeError):
    """A store read FAILED. It is not evidence that the store is empty.

    The distinction is the whole point: `list` used to map any nonzero result
    to an empty list, so a transient auth or network failure was indistinguishable
    from an empty people directory. The next live run then resolved every
    existing person as new and wrote a fresh note over their real one — the
    self-reinforcing bad write this tool is built to refuse, arriving through
    the read path instead of the resolver.

    This is design-notes rule 9 turned on the tool itself: a traceback is never
    a missing file, and absence must be proven rather than inferred.
    """


class Fulcra:
    def __init__(self, base: list[str]):
        self.base = base

    def run(self, args: list[str], timeout: int = 180) -> subprocess.CompletedProcess:
        return subprocess.run(self.base + args, capture_output=True, text=True, timeout=timeout)

    def list(self, remote: str) -> list[str]:
        r = self.run(["file", "list", remote])
        if r.returncode != 0:
            raise FulcraUnavailable(
                f"file list {remote} failed (rc={r.returncode}): "
                f"{(r.stderr or r.stdout or '').strip().splitlines()[0][:200] if (r.stderr or r.stdout).strip() else 'no output'}")
        out = []
        for line in r.stdout.splitlines():
            if not line.strip():
                continue
            m = _STAT_ROW.match(line)
            out.append((m.group(1) if m else line).strip())
        return out

    def download(self, remote: str, dest: Path) -> bool:
        dest.parent.mkdir(parents=True, exist_ok=True)
        return self.run(["file", "download", remote, str(dest)]).returncode == 0 and dest.exists()

    def upload(self, local: Path, remote: str) -> bool:
        return self.run(["file", "upload", str(local), remote]).returncode == 0

    def calendar(self, start: str, end: str) -> list[dict]:
        r = self.run(["calendar-events", start, end])
        if r.returncode != 0:
            return []
        evs, seen = [], set()
        for line in r.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except Exception:
                continue
            if not ev.get("participants"):
                continue
            key = (ev.get("title"), ev.get("start_date"))
            if key in seen:          # the same event is mirrored across calendars
                continue
            seen.add(key)
            evs.append(ev)
        return sorted(evs, key=lambda e: e.get("start_date") or "")


# --------------------------------------------------------------------------- identity
class Identity:
    def __init__(self, cfg: dict):
        i = cfg["identity"]
        self.self_emails = {e.lower() for e in i.get("self_emails", [])}
        self.internal = {d.lower() for d in i.get("internal_domains", [])}
        bots = "|".join(re.escape(b) for b in i.get("bot_domains", []))
        locals_ = "|".join(re.escape(b) for b in i.get("bot_local_parts", []))
        res = "|".join(re.escape(b) for b in i.get("resource_domains", []))
        pat = []
        if locals_:
            pat.append(rf"^({locals_})[-_.@]")
        if bots or res:
            pat.append(rf"@({bots}{'|' if bots and res else ''}{res})$")
        self._bot = re.compile("|".join(pat), re.I) if pat else None

    def is_bot(self, email: str) -> bool:
        email = (email or "").strip().lower()
        return bool(email) and bool(self._bot and self._bot.search(email))

    def is_self(self, email: str) -> bool:
        return (email or "").strip().lower() in self.self_emails


def display_name_from_email(email: str) -> str:
    """"kate.freedman@x.com" -> "Kate Freedman"; "brad@x.com" -> "Brad"."""
    local = (email or "").split("@")[0]
    local = re.sub(r"\d+$", "", local)
    parts = [p for p in re.split(r"[._\-+]+", local) if p and not p.isdigit()]
    if len(parts) > 1 and len(parts[-1]) == 1:
        parts = parts[:-1]              # "mathieu.r" -> "Mathieu", not "Mathieu R"
    return " ".join(p.capitalize() for p in parts)


def is_confident_name(name: str) -> bool:
    """A single token is not an identity. See design-notes.md #5."""
    parts = [p for p in (name or "").split() if p]
    return len(parts) >= 2 and all(len(p) > 1 for p in parts)


# --------------------------------------------------------------------------- vault CRM
class VaultCRM:
    """Minimal person store on top of Fulcra Vault notes."""

    def __init__(self, fulcra: Fulcra, cfg: dict, cache: Path):
        self.f = fulcra
        self.dir = cfg["vault"]["people_dir"].rstrip("/")
        self.label = cfg["vault"].get("note_source_label", "meeting-crm")
        self.cache = cache
        self.index: list[dict] = []

    def build_index(self) -> int:
        """Read every person note. ANY failure aborts — a partial index is the
        same hazard as an empty one: the people it failed to read resolve as
        new, and a live run writes over them."""
        self.index = []
        for name in self.f.list(self.dir):
            if not name.endswith(".md"):
                continue
            dest = self.cache / name
            # ALWAYS re-download, never trust the cache as the current body.
            # `upsert` composes the next upload FROM the indexed body, so a note
            # another writer changed since the last run would be re-uploaded in
            # its stale form with only our line appended — silently removing
            # their edits. Reproduced by codex-reviewer: a cached note kept
            # `stale cached line` and dropped `external fresh line`. The cache
            # is scratch space for this run, not a source of truth about the
            # store, and one extra read per person is the cheapest possible
            # price for not overwriting somebody's durable data.
            if not self.f.download(f"{self.dir}/{name}", dest):
                raise FulcraUnavailable(
                    f"download failed for {self.dir}/{name}: the index would be "
                    "partial, and a partial index writes over the people it "
                    "could not read")
            try:
                body = dest.read_text()
            except Exception as exc:
                raise FulcraUnavailable(
                    f"cannot read cached note {dest}: {exc}") from exc
            title = name[:-3]
            emails = {e.lower() for e in _EMAIL.findall(body)}
            self.index.append({"title": title, "note": f"{self.dir}/{name}",
                               "emails": emails, "body": body})
        return len(self.index)

    def resolve(self, name: str | None = None, email: str | None = None) -> dict:
        """email -> exact title -> unique token. Returns match='ambiguous' on ties."""
        if email:
            hits = [p for p in self.index if email.lower() in p["emails"]]
            if len(hits) == 1:
                return {"match": "email", "person": hits[0]}
            if len(hits) > 1:
                return {"match": "ambiguous", "candidates": [h["title"] for h in hits]}
        if name:
            n = name.strip().lower()
            hits = [p for p in self.index if p["title"].strip().lower() == n]
            if len(hits) == 1:
                return {"match": "name", "person": hits[0]}
            if len(hits) > 1:
                return {"match": "ambiguous", "candidates": [h["title"] for h in hits]}
            toks = [t for t in re.findall(r"[a-z]+", n) if len(t) > 1]
            if toks:
                hits = [p for p in self.index
                        if all(t in p["title"].lower() for t in toks)]
                if len(hits) == 1:
                    return {"match": "unique_token", "person": hits[0]}
                if len(hits) > 1:
                    return {"match": "ambiguous", "candidates": [h["title"] for h in hits]}
        return {"match": "none"}

    def _current_body(self, remote: str) -> str | None:
        """The note's body AS OF NOW, or None when it does not exist.

        Round-3 finding (codex-reviewer, reproduced): refreshing the index at
        run start does not make the body current at WRITE time. The index scan
        is N downloads long, so a note changed by another writer between its
        index download and this upsert was composed-over and silently lost.
        One more read per actual write closes that window to the read-compose-
        upload gap, which is the narrowest this store's API allows: it has no
        compare-and-swap and no versioned put (verified live 2026-07-04 —
        last-write-wins, per-upload version UUID, no conditional write), so a
        zero-width window is not implementable here and we do not claim it.
        Raises nothing; a failed re-read returns the INDEXED body rather than
        None, because "unreadable now" must not be treated as "does not exist"
        and turned into a fresh CREATE over a real note.
        """
        dest = self.cache / f"_cur_{re.sub(r'[^A-Za-z0-9]', '_', remote.rsplit('/', 1)[-1])}"
        try:
            if self.f.download(remote, dest):
                return dest.read_text()
        except Exception:
            pass
        finally:
            dest.unlink(missing_ok=True)
        return None

    def upsert(self, *, title: str, email: str | None, note_line: str | None) -> dict:
        remote = f"{self.dir}/{title}.md"
        existing = next((p for p in self.index if p["note"] == remote), None)
        now = datetime.now(timezone.utc).isoformat()
        if existing:
            fresh = self._current_body(remote)
            if fresh is None:
                # FAIL CLOSED (codex-reviewer, round 4, overturning my round-4
                # availability choice — correctly): a failed re-read is exactly
                # when we cannot know whether another writer changed the note,
                # so composing from the index snapshot can still erase their
                # edits. A skipped CRM log line is recoverable; overwritten
                # durable note content is not.
                return {"action": "skipped_unreadable", "note": remote}
            if fresh != existing["body"]:
                # Another writer moved the note since the index scan. Compose
                # from THEIR body, not our snapshot.
                existing["body"] = fresh
                existing["emails"] = {e.lower() for e in _EMAIL.findall(fresh)}
            body = existing["body"]
            changed = False
            if email and email.lower() not in existing["emails"]:
                body = body.rstrip() + f"\n- **Email:** {email}\n"
                changed = True
            if note_line and note_line not in body:
                body = body.rstrip() + f"\n- {now} {self.label}: {note_line}\n"
                changed = True
            if not changed:
                return {"action": "unchanged", "note": remote}
        else:
            body = (f"---\ntitle: \"{title}\"\nupdated_at: {now}\n---\n\n# {title}\n\n"
                    f"## Contact\n\n" + (f"- **Email:** {email}\n" if email else "") +
                    "\n## Log\n" + (f"- {now} {self.label}: {note_line}\n" if note_line else ""))
        tmp = self.cache / f"_up_{re.sub(r'[^A-Za-z0-9]', '_', title)}.md"
        # Only `download` created this directory, so a first run against a
        # legitimately EMPTY people directory downloads nothing and then dies
        # here on its very first write.
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(body)
        ok = self.f.upload(tmp, remote)
        tmp.unlink(missing_ok=True)
        if ok:
            # THE IN-MEMORY INDEX IS THE ONLY RECORD OF THIS RUN'S WRITES.
            # Without this, the same previously-unknown attendee appearing in
            # two events of one run takes the `existing is None` branch twice
            # and the second note REPLACES the first — reproduced by
            # codex-reviewer: the second body carried only the second meeting.
            emails = set(existing["emails"]) if existing else set()
            if email:
                emails.add(email.lower())
            if existing:
                existing["body"] = body
                existing["emails"] = emails
            else:
                self.index.append({"title": title, "note": remote,
                                   "emails": emails, "body": body})
        return {"action": ("updated" if existing else "created") if ok else "failed",
                "note": remote}


# --------------------------------------------------------------------------- summary mail
def summary_text(payload: dict) -> str:
    b = payload.get("bodies") or {}
    plain = b.get("text/plain") or re.sub(r"<[^>]+>", " ", b.get("text/html") or "")
    return html.unescape(plain)


# Vendor-neutral defaults. Every note-taker phrases its mail slightly
# differently; none of them are privileged in code. Override via
# config.detection to support a service these do not cover.
DEFAULT_SUBJECT_PATTERNS = [
    r"meeting\s+summary", r"meeting\s+notes", r"shared\s+notes",
    r"notes\s+from", r"recap\s+of", r"summary\s+of", r"transcript",
]
DEFAULT_TITLE_STRIP = [
    r"^(re|fwd|fw)\s*:\s*",
    r"^(meeting\s+summary|meeting\s+notes|notes|recap|summary|transcript)\s+(from|for|of)\s*",
    r"^(your|shared)\s+(meeting\s+)?(notes|summary)\s*[:\-]?\s*",
]
# `(?P<name>…)` is required. First pattern that matches wins.
DEFAULT_SHARER_PATTERNS = [
    r"^\s*(?P<name>.+?)\s+via\s+\S+",          # "Christine Acoba via Otter.ai"
    r"^\s*(?P<name>.+?)\s+shared\s+",           # "Alice shared notes from…"
    r"^\s*(?P<name>.+?)\s*<[^>]+>\s*$",         # plain "Name <addr>"
]


def _patterns(cfg: dict, key: str, fallback: list[str]) -> list[str]:
    return (cfg.get("detection") or {}).get(key) or fallback


def is_summary(payload: dict, cfg: dict | None = None) -> bool:
    h = payload.get("headers") or {}
    subject = (h.get("Subject") or "")
    pats = _patterns(cfg or {}, "subject_patterns", DEFAULT_SUBJECT_PATTERNS)
    return any(re.search(p, subject, re.I) for p in pats)


def parse_summary(payload: dict, cfg: dict) -> dict:
    """Title, date, prose and sharer. The sharer is PROVENANCE, never an attendee."""
    h = payload.get("headers") or {}
    text = summary_text(payload)
    title = h.get("Subject") or ""
    for pat in _patterns(cfg, "title_strip_patterns", DEFAULT_TITLE_STRIP):
        title = re.sub(pat, "", title, flags=re.I)
    if cfg.get("guards", {}).get("strip_tracking_urls_from_titles", True):
        title = re.sub(r"\s*\(?\s*https?://\S*.*$", "", title)
    title = title.strip(" \"'()")

    date = ""
    raw = h.get("Date") or ""
    m = re.search(r"(\d{1,2})\s+(\w{3})\s+(\d{4})", raw)
    if m:
        try:
            date = datetime.strptime(" ".join(m.groups()), "%d %b %Y").strftime("%Y-%m-%d")
        except ValueError:
            pass

    # Provenance only. Whoever shared the notes is NOT an attendee -- see
    # references/ingest-format.md.
    shared_by = ""
    frm = (h.get("From") or "").strip()
    for pat in _patterns(cfg, "sharer_patterns", DEFAULT_SHARER_PATTERNS):
        m2 = re.search(pat, frm, re.I)
        if m2 and "name" in (m2.groupdict() or {}):
            shared_by = (m2.group("name") or "").strip().strip('"')
            if shared_by:
                break

    prose = re.sub(r"\s+", " ", text)
    prose = re.sub(r"https?://\S+", "", prose)
    limit = cfg.get("limits", {}).get("summary_chars", 1200)
    return {"title": title, "date": date, "shared_by": shared_by,
            "summary": prose.strip()[:limit]}


# --------------------------------------------------------------------------- sources
#
# A meeting summary can reach this skill three ways, and Fulcra is only one of
# them. An agent that already holds an Otter/Fireflies API key, or an MCP
# connection in the bot it runs inside, must be able to feed the loop directly
# WITHOUT the data transiting Fulcra Files.
#
# All adapters emit the same NORMALIZED RECORD, which is the actual contract:
#
#   {"title": str, "date": "YYYY-MM-DD", "summary": str, "shared_by": str?,
#    "attendees": [{"name": str?, "email": str?}]?}
#
# `attendees` is optional and ADVISORY everywhere: the calendar remains the
# attendee authority (design-notes.md #1). A source that supplies real invitee
# addresses (a calendar-aware API) may still be trusted for emails, but a
# source that only has prose must not be.

def _norm_record(rec: dict, cfg: dict) -> dict | None:
    """Coerce any source's record into the normalized shape."""
    if not isinstance(rec, dict):
        return None
    # A raw collected email still carries headers/bodies; parse it.
    if "headers" in rec and "bodies" in rec:
        return parse_summary(rec, cfg) if is_summary(rec, cfg) else None
    title = (rec.get("title") or rec.get("subject") or "").strip()
    date = (rec.get("date") or rec.get("start") or rec.get("created_at") or "")[:10]
    body = rec.get("summary") or rec.get("text") or rec.get("notes") or ""
    if not title or not date:
        return None
    limit = cfg.get("limits", {}).get("summary_chars", 1200)
    atts = []
    for a in (rec.get("attendees") or rec.get("participants") or []):
        if isinstance(a, str):
            atts.append({"name": "" if "@" in a else a, "email": a if "@" in a else ""})
        elif isinstance(a, dict):
            atts.append({"name": (a.get("name") or "").strip(),
                         "email": (a.get("email") or "").strip().lower()})
    return {"title": title, "date": date,
            "summary": re.sub(r"\s+", " ", str(body)).strip()[:limit],
            "shared_by": rec.get("shared_by", ""), "attendees": atts,
            "source": rec.get("source", ""),
            "external_id": rec.get("external_id", ""),
            # ingest-format.md lists `url` ("link back to the source record");
            # the normalizer dropped it — the same promised-but-dropped class
            # external_id was in before round 2.
            "url": (rec.get("url") or "").strip(),
            # Only a calendar-aware source may be trusted for attendees; a source
            # that derives them from prose is guessing (see ingest-format.md).
            "attendees_authoritative": bool(rec.get("attendees_authoritative"))}


def _iter_json(text: str):
    """Accept a JSON array, a single object, or JSON-lines."""
    text = text.strip()
    if not text:
        return
    try:
        loaded = json.loads(text)
        yield from (loaded if isinstance(loaded, list) else [loaded])
        return
    except json.JSONDecodeError:
        pass
    for line in text.splitlines():
        line = line.strip()
        if line:
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def load_summaries(cfg: dict, f: "Fulcra", cache: Path, months: list[str],
                   report: dict) -> list[dict]:
    """Collect normalized summaries from every configured source."""
    sources = list(cfg.get("sources") or [])
    # Back-compat: a bare `collect` block is the Fulcra Files source.
    if cfg.get("collect") and not any(s.get("type") == "fulcra_files" for s in sources):
        sources.insert(0, dict(cfg["collect"], type="fulcra_files"))

    out: list[dict] = []
    for src in sources:
        kind = src.get("type")
        try:
            if kind == "fulcra_files":
                if not months:
                    continue
                tmpl = src.get("path_template", "/collect/{provider}/{account_id}/{month}")
                for month in months:
                    root = tmpl.format(provider=src.get("provider", "gmail"),
                                       account_id=src["account_id"], month=month)
                    for name in f.list(root):
                        if not name.endswith(".json"):
                            continue
                        dest = cache / "collect" / month / name
                        if not dest.exists() and not f.download(f"{root}/{name}", dest):
                            report["errors"].append(f"fetch failed {month}/{name}")
                            continue
                        try:
                            rec = _norm_record(json.loads(dest.read_text()), cfg)
                        except Exception:
                            rec = None
                        if rec:
                            out.append(rec)

            elif kind == "command":
                # Any API or MCP bridge: emit normalized records on stdout.
                # This is how a bot feeds the loop from its OWN connection.
                r = subprocess.run(src["argv"], capture_output=True, text=True,
                                   timeout=src.get("timeout", 300))
                if r.returncode != 0:
                    report["errors"].append(
                        f"source command failed ({r.returncode}): "
                        f"{(r.stderr or '').strip().splitlines()[:1]}")
                    continue
                for raw in _iter_json(r.stdout):
                    rec = _norm_record(raw, cfg)
                    if rec:
                        out.append(rec)

            elif kind == "mcp":
                # GENERAL MCP SOURCE — server-agnostic by design.
                #
                # A skill process cannot speak MCP itself: MCP connections live
                # in the AGENT runtime that hosts this skill, not in a script.
                # So the contract is inverted and stays generic: the agent calls
                # whichever MCP tool it has (Otter, Fireflies, Granola, Gong,
                # anything), writes NORMALIZED RECORDS, and points this source at
                # them. Nothing here knows or cares which server produced them,
                # and no data transits Fulcra.
                #
                # Two shapes, both optional:
                #   "bridge_argv": argv the agent provides that emits records on
                #                  stdout (use when the agent can be invoked).
                #   "inbox":       a directory the agent drops records into
                #                  (use when the agent runs on its own cadence).
                bridge = src.get("bridge_argv")
                if bridge:
                    r = subprocess.run(bridge, capture_output=True, text=True,
                                       timeout=src.get("timeout", 300))
                    if r.returncode != 0:
                        report["errors"].append(
                            f"mcp bridge failed ({r.returncode}) "
                            f"{src.get('server','')}".strip())
                    else:
                        for raw in _iter_json(r.stdout):
                            rec = _norm_record(raw, cfg)
                            if rec:
                                out.append(rec)
                inbox = src.get("inbox")
                if inbox:
                    p = Path(os.path.expanduser(inbox))
                    if p.exists():
                        for fp in sorted(p.glob(src.get("glob", "*.json*"))):
                            for raw in _iter_json(fp.read_text()):
                                rec = _norm_record(raw, cfg)
                                if rec:
                                    out.append(rec)
                if not bridge and not inbox:
                    report["errors"].append(
                        "mcp source needs either bridge_argv or inbox")

            elif kind in ("file", "directory"):
                # An agent holding an MCP connection can dump normalized records
                # here; the skill needs no MCP client of its own.
                p = Path(os.path.expanduser(src["path"]))
                files = sorted(p.glob(src.get("glob", "*.json*"))) if p.is_dir() else [p]
                for fp in files:
                    for raw in _iter_json(fp.read_text()):
                        rec = _norm_record(raw, cfg)
                        if rec:
                            out.append(rec)
            else:
                report["errors"].append(f"unknown source type: {kind!r}")
        except Exception as exc:
            report["errors"].append(f"source {kind}: {str(exc).splitlines()[0][:140]}")

    # Same meeting from two sources: keep the richer summary.
    # `external_id`, when a source supplies one, is the identity — that is what
    # references/ingest-format.md promises makes re-ingest idempotent, and it
    # was being carried but never used. Records without one fall back to
    # (date, title), which is all the contract guarantees for them.
    # PASS 1 dedupes WITHIN-SOURCE identity only: external_id namespaced by
    # source (provider-local ids — Otter's 123 and Fireflies' 123 are unrelated,
    # reproduced by codex-reviewer in round 3). Records without an external_id
    # pass straight through: their only identity is (date, title), which is
    # pass 2's key, and deduping them here would DISCARD their metadata before
    # the merge could keep it (the shared_by-lost case, caught by test).
    def _merge_pair(a: dict, b: dict) -> dict:
        """Merge two records for the SAME meeting: richer summary wins the
        body, missing metadata is filled from the other, and authoritative
        attendees travel WITH their authority — even against a richer record
        whose list is only advisory. Round-4 finding: pass 1 kept only the
        longer-summary record, so a short record's authoritative attendee
        list was silently replaced by an advisory one."""
        richer, other = (a, b) if len(a["summary"]) >= len(b["summary"]) else (b, a)
        merged = dict(richer)
        for field in ("attendees", "shared_by", "external_id", "source", "url"):
            if not merged.get(field) and other.get(field):
                merged[field] = other[field]
        if other.get("attendees_authoritative") and not merged.get("attendees_authoritative"):
            merged["attendees"] = other.get("attendees")
            merged["attendees_authoritative"] = True
        return merged

    best: dict[tuple, dict] = {}
    passthrough: list[dict] = []
    for rec in out:
        ext = str(rec.get("external_id") or "").strip()
        if not ext:
            passthrough.append(rec)
            continue
        src_ns = str(rec.get("source") or "").strip().lower()
        key = ("ext", src_ns, ext)
        best[key] = _merge_pair(best[key], rec) if key in best else rec

    # SECOND PASS - cross-source coalescing (round-3 finding, reproduced):
    # namespacing external_id fixed provider collisions but broke the README's
    # composition promise the other way. The same meeting seen by two sources
    # naturally carries two DIFFERENT provider-local ids, so the first pass
    # keeps both, and match_summary resolves equal title scores first-seen -
    # a short gmail-relay record could shadow a richer Otter record for the
    # same meeting. Pass 1 is within-source identity (external_id); pass 2 is
    # cross-source meeting identity (date + normalized title), keeping the
    # richer summary and filling in metadata the richer record lacks. Records
    # whose titles differ across sources are NOT merged here - title fuzz is
    # match_summary's job at join time, with the calendar as the anchor.
    merged = {}
    for rec in list(best.values()) + passthrough:
        mkey = (rec["date"], rec["title"].strip().lower())
        prev = merged.get(mkey)
        if prev is None:
            merged[mkey] = dict(rec)
            continue
        merged[mkey] = _merge_pair(prev, rec)
    return list(merged.values())


# --------------------------------------------------------------------------- join
def title_tokens(t: str) -> set:
    return {w for w in re.findall(r"[a-z0-9]+", (t or "").lower()) if len(w) > 2}


def match_summary(ev: dict, summaries: list[dict], threshold: float) -> dict | None:
    day = (ev.get("start_date") or "")[:10]
    ek = title_tokens(ev.get("title"))
    best, score = None, 0.0
    for s in summaries:
        if s.get("date") != day or not ek:
            continue
        sk = title_tokens(s.get("title"))
        if not sk:
            continue
        v = len(ek & sk) / max(1, min(len(ek), len(sk)))
        if v > score:
            best, score = s, v
    return best if score >= threshold else None


def external_attendees(ev: dict, ident: Identity) -> list[dict]:
    people, seen = [], set()
    for p in (ev.get("participants") or []):
        if p.get("is_current_user"):
            continue
        if (p.get("participant_type") or "person").lower() != "person":
            continue
        url = (p.get("url") or "")
        email = url[7:].strip().lower() if url.lower().startswith("mailto:") else ""
        if not email:
            nm = (p.get("name") or "").strip()
            email = nm.lower() if "@" in nm else ""
        if not email or ident.is_self(email) or ident.is_bot(email) or email in seen:
            continue
        seen.add(email)
        name = (p.get("name") or "").strip()
        people.append({"name": "" if "@" in name else name, "email": email})
    return people


# --------------------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", required=True)
    ap.add_argument("--calendar", nargs=2, metavar=("START", "END"), required=True)
    ap.add_argument("--month", action="append", help="collect shard YYYY-MM (repeatable)")
    ap.add_argument("--cache", default=".meeting-crm-cache")
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    cfg = load_config(args.config)
    base = cli_base(cfg)
    version = check_version(cfg, base)
    f = Fulcra(base)
    ident = Identity(cfg)
    cache = Path(args.cache)
    crm = VaultCRM(f, cfg, cache / "people")
    indexed = crm.build_index()

    report = {"cli_version": version, "indexed_people": indexed, "live": args.live,
              "summaries": 0, "events": [], "skipped_mass": [], "errors": []}

    # ---- summaries: any configured source (Fulcra Files, API/MCP bridge, files)
    summaries = load_summaries(cfg, f, cache, args.month or [], report)
    report["summaries"] = len(summaries)

    # ---- calendar drives attendees
    limits = cfg.get("limits", {})
    guards = cfg.get("guards", {})
    cap = limits.get("max_attendees", 12)
    for ev in f.calendar(*args.calendar):
        people = external_attendees(ev, ident)
        if not people:
            continue
        if cap and len(people) > cap:
            report["skipped_mass"].append({"title": ev.get("title"),
                                           "attendees": len(people)})
            continue
        hit = match_summary(ev, summaries, limits.get("title_match_threshold", 0.5))
        # The cap is re-applied below, AFTER authoritative attendees are merged.
        # Checking only here let a 12-invitee calendar event plus a trusted
        # record carrying 40 more addresses write 52 CRM records straight past
        # the mass-meeting guard.
        if hit and hit.get("attendees_authoritative"):
            # Trusted source: add invitees the calendar did not carry.
            known = {p["email"] for p in people}
            for extra in hit.get("attendees") or []:
                em = (extra.get("email") or "").lower()
                if em and em not in known and not ident.is_self(em) and not ident.is_bot(em):
                    people.append({"name": extra.get("name") or "", "email": em})
                    known.add(em)
        if cap and len(people) > cap:
            # A 50-person all-hands is not a relationship event however the
            # attendees arrived — calendar, trusted source, or both.
            report["skipped_mass"].append({"title": ev.get("title"),
                                           "attendees": len(people)})
            continue
        # `source` reaches the log line, as references/ingest-format.md promises.
        src = (hit.get("source") or "").strip() if hit else ""
        note_line = (f"{hit['date']} — {hit['title']}"
                     + (f" [{src}]" if src else "")
                     + f": {hit['summary']}") if hit else None
        row = {"date": (ev.get("start_date") or "")[:10], "title": ev.get("title"),
               "summary_joined": bool(hit), "attendees": []}
        for p in people:
            nm = p["name"] or display_name_from_email(p["email"])
            res = crm.resolve(name=nm or None, email=p["email"])
            rec = {"name": nm, "email": p["email"], "match": res["match"]}
            blocked = res["match"] == "ambiguous" and guards.get("block_create_on_ambiguous", True)
            unknown = res["match"] in ("none", "ambiguous")
            if unknown and guards.get("require_multi_token_name", True) and not is_confident_name(nm):
                rec["action"] = "skipped: name not confident"
            elif blocked:
                rec["action"] = "skipped: ambiguous"
                rec["candidates"] = res.get("candidates")
            elif args.live:
                title = res["person"]["title"] if res["match"] != "none" else nm
                try:
                    rec.update(crm.upsert(title=title, email=p["email"], note_line=note_line))
                except Exception as exc:
                    brief = str(exc).splitlines()[0][:160]
                    rec["action"] = f"error: {brief}"
                    report["errors"].append(f"{p['email']}: {brief}")
            else:
                rec["action"] = "would write"
            row["attendees"].append(rec)
        report["events"].append(row)

    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(f"cli={version} people_indexed={indexed} summaries={report['summaries']} "
              f"live={args.live} errors={len(report['errors'])}")
        for ev in report["events"]:
            print(f"\n  {ev['date']} {'[summary]' if ev['summary_joined'] else '[      ]'} {ev['title']}")
            for a in ev["attendees"]:
                print(f"      {a['email']:<36} {a['match']:<12} {a.get('action','')}")
        for m in report["skipped_mass"]:
            print(f"  skipped mass meeting: {m['title']} ({m['attendees']})")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        sys.exit(2)
    except FulcraUnavailable as exc:
        # rc 3, distinct from a config error and from a clean run: a caller
        # scripting this must be able to tell "the store could not be read"
        # from "there was nothing to do". Nothing was written — the index is
        # built before any upload, so aborting here aborts before the writes.
        print(f"store unavailable, nothing written: {exc}", file=sys.stderr)
        sys.exit(3)
