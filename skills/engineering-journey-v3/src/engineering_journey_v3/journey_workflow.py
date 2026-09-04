"""Approval-bound GitHub-to-private-v3-evidence journey preparation."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, replace

from engineering_journey_v3.discovery import RepositorySnapshot
from engineering_journey_v3.fulcra_gateway import ApprovedPlan, FulcraGateway, FulcraSchemaError
from engineering_journey_v3.fulcra_registry import RegisteredType
from engineering_journey_v3.github_sources import (
    ContributionRetriever,
    GitHubAPITransport,
    GitHubClient,
    SourceFact,
)
from engineering_journey_v3.progress import ProgressEvent, WorkCounters
from engineering_journey_v3.raw_activity import (
    RawActivityWriter,
    RepositoryVisibility,
    WriteCounts,
    normalize_source_facts,
)
from engineering_journey_v3.run_state import (
    CheckpointJournal,
    RunFiles,
    RunStateError,
    RunStatus,
    utc_now,
)


@dataclass(frozen=True, slots=True)
class IngestionResult:
    """Reconciled counts for one complete frozen repository snapshot."""

    repositories: int
    source_facts: int
    writes: WriteCounts


def _empty_writes() -> WriteCounts:
    return WriteCounts(0, 0, 0, 0, 0, 0, 0, 0, 0)


def _add_writes(left: WriteCounts, right: WriteCounts) -> WriteCounts:
    return WriteCounts(
        source_facts=left.source_facts + right.source_facts,
        source_sightings=left.source_sightings + right.source_sightings,
        normalized=left.normalized + right.normalized,
        duplicates=left.duplicates + right.duplicates,
        batches=left.batches + right.batches,
        attempted=left.attempted + right.attempted,
        written=left.written + right.written,
        already_present=left.already_present + right.already_present,
        reconciled=left.reconciled + right.reconciled,
    )


def ingest_github_snapshot(
    api: GitHubAPITransport,
    gateway: FulcraGateway,
    approval: ApprovedPlan,
    raw_type: RegisteredType,
    snapshot: RepositorySnapshot,
    *,
    run_files: RunFiles | None = None,
) -> IngestionResult:
    """Retrieve, normalize, and durably reconcile all candidates in a frozen snapshot.

    Discovery itself precedes final plan approval because the snapshot digest is part
    of that immutable plan. This boundary verifies the complete frozen discovery result
    before making any source or Fulcra write call.
    """

    plan = approval.plan
    if (
        snapshot.identity != plan.identity
        or snapshot.start_utc != plan.start_utc
        or snapshot.end_utc != plan.end_utc
        or snapshot.digest != plan.repository_snapshot_digest
    ):
        raise FulcraSchemaError("repository snapshot is not bound to the approved plan")

    journal: CheckpointJournal | None = None
    if run_files is not None:
        if run_files.path(RunFiles.CHECKPOINT).exists():
            saved_plan, saved_snapshot, checkpoint = run_files.review_resume()
            if saved_plan.digest != plan.digest or saved_snapshot.digest != snapshot.digest:
                raise RunStateError("saved ingestion state is not bound to this approved plan")
            if checkpoint.status != RunStatus.RUNNING:
                raise RunStateError("interrupted ingestion must be explicitly approved with resume")
        else:
            checkpoint = run_files.initialize(plan, snapshot, str(uuid.uuid4()))
        journal = CheckpointJournal(run_files, checkpoint)
        if checkpoint.stage != "github-ingestion":
            if checkpoint.completed_repository_ids or checkpoint.current_repository_id is not None:
                raise RunStateError("repository checkpoint has an incompatible ingestion stage")
            journal.transition_stage("github-ingestion")

    started = time.monotonic()
    counters = WorkCounters(
        repositories_completed=(
            len(journal.current.completed_repository_ids) if journal is not None else 0
        )
    )

    def emit(event: str, operation: str, repository: str | None = None) -> None:
        if run_files is None or journal is None:
            return
        pages = max(journal.current.page_milestones.values(), default=0)
        run_files.progress.append(
            ProgressEvent(
                run_id=plan.run_id,
                invocation_id=journal.current.invocation_id,
                event=event,
                stage=journal.current.stage,
                timestamp_utc=utc_now(),
                elapsed_seconds=time.monotonic() - started,
                current_operation=operation,
                counters=counters,
                repository_current=repository,
                repository_index=journal.current.repository_index,
                repository_total=len(snapshot.repositories),
                page_current=pages,
                quota_state={},
                terminal_reconciliation=(
                    {
                        "received": counters.writes_attempted,
                        "durable": counters.writes_durable,
                        "deduplicated": counters.deduplicated,
                        "failed": 0,
                    }
                    if event == "terminal"
                    else None
                ),
            )
        )

    client = GitHubClient.from_github_api(api)
    source_fact_count = 0
    writes = _empty_writes()
    writer = RawActivityWriter(gateway, raw_type, approval)
    completed = set(journal.current.completed_repository_ids) if journal is not None else set()
    try:
        for repository in snapshot.repositories:
            if repository.database_id in completed:
                continue
            name = repository.name_with_owner
            if journal is not None:
                if journal.current.current_repository_id is None:
                    journal.begin_repository(repository.database_id)
                elif journal.current.current_repository_id != repository.database_id:
                    raise RunStateError("current checkpoint repository is outside snapshot order")
            progress_repository = (
                f"repository-{journal.current.repository_index}" if journal is not None else None
            )
            emit("repository-started", "retrieving repository", progress_repository)

            def page_observer(
                source: str,
                page: int,
                progress_repository: str | None = progress_repository,
            ) -> None:
                nonlocal counters
                if journal is not None:
                    saved_page = journal.current.page_milestones.get(source, 0)
                    if page > saved_page:
                        journal.complete_page(source, page)
                counters = replace(
                    counters,
                    pages_completed=counters.pages_completed + 1,
                    api_calls=counters.api_calls + 1,
                    retries=client.retry_count,
                )
                emit("page-completed", f"retrieved source page {page}", progress_repository)

            retriever = ContributionRetriever(client, page_observer=page_observer)
            facts: tuple[SourceFact, ...] = retriever.retrieve(
                repository=name,
                identity=plan.identity,
                start_utc=plan.start_utc,
                end_utc=plan.end_utc,
                # GitHub has no complete pre-check surface for line comments. An
                # empty probe set is therefore explicitly UNKNOWN and must take the
                # complete fallback. Avoid six redundant Search requests per
                # repository; a real annual run otherwise exceeds Search's burst
                # limits without proving that any candidate may be skipped.
                probes=(),
            )
            visibility = {
                name: (
                    RepositoryVisibility.PRIVATE
                    if repository.private
                    else RepositoryVisibility.PUBLIC
                )
            }
            repository_writes = writer.write(normalize_source_facts(facts, visibility))
            source_fact_count += len(facts)
            writes = _add_writes(writes, repository_writes)
            counters = replace(
                counters,
                repositories_completed=counters.repositories_completed + 1,
                writes_attempted=counters.writes_attempted + repository_writes.attempted,
                writes_durable=(
                    counters.writes_durable
                    + repository_writes.written
                    + repository_writes.reconciled
                ),
                deduplicated=counters.deduplicated + repository_writes.already_present,
                retries=client.retry_count,
            )
            if journal is not None:
                journal.complete_repository(repository.database_id)
            emit("repository-completed", "completed repository")
        emit("terminal", "ingestion reconciled")
    except BaseException:
        if journal is not None and journal.current.status == RunStatus.RUNNING:
            progress_repository = f"repository-{journal.current.repository_index}"
            journal.fail()
            emit("failed", "ingestion interrupted by failure", progress_repository)
        raise
    return IngestionResult(len(snapshot.repositories), source_fact_count, writes)
