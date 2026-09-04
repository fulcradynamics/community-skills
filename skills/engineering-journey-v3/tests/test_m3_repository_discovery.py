from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import replace
from typing import Any

import pytest

from engineering_journey_v3.discovery import (
    DiscoveryError,
    GitHubCLIAPI,
    RepositoryDiscoverer,
    RepositorySnapshot,
    bind_snapshot,
    require_v2_isolation,
)
from engineering_journey_v3.plan import approval_matches, build_plan

START = "2025-01-02T03:04:05Z"
END = "2026-01-02T03:04:05Z"


def rest_repository(
    database_id: int,
    name: str,
    *,
    private: bool = False,
    archived: bool = False,
) -> dict[str, Any]:
    return {
        "id": database_id,
        "node_id": f"R_{database_id}",
        "full_name": name,
        "private": private,
        "archived": archived,
        "html_url": f"https://github.com/{name}",
    }


def graphql_repository(
    database_id: int,
    name: str,
    *,
    private: bool = False,
    archived: bool = False,
) -> dict[str, Any]:
    return {
        "databaseId": database_id,
        "id": f"R_{database_id}",
        "nameWithOwner": name,
        "isPrivate": private,
        "isArchived": archived,
        "url": f"https://github.com/{name}",
    }


class FakeAPI:
    def __init__(self) -> None:
        self.rest_calls: list[tuple[str, dict[str, str | int]]] = []
        self.graphql_calls: list[dict[str, str | int | None]] = []

    def rest(self, path: str, parameters: Mapping[str, str | int]) -> Any:
        values = dict(parameters)
        self.rest_calls.append((path, values))
        page = values["page"]
        if path == "user/repos":
            if page == 1:
                # Exactly 100 forces a second page. Repository 1 has no activity and
                # proves directly accessible zero-activity candidates stay frozen.
                return [
                    rest_repository(
                        database_id,
                        f"direct/repository-{database_id}",
                        private=database_id == 2,
                        archived=database_id == 3,
                    )
                    for database_id in range(1, 101)
                ]
            return [rest_repository(101, "direct/repository-101")]
        query = str(values["q"])
        if path == "search/commits":
            items = [{"repository": rest_repository(201, "external/commit-work")}]
        elif query.startswith("author:"):
            items = [{"repository": rest_repository(202, "external/opened-work")}]
        else:
            items = [
                {"repository": rest_repository(203, "external/comment-only")},
                # A stale search name for a repository also directly accessible.
                {"repository": rest_repository(2, "old-owner/old-name", private=True)},
            ]
        return {"total_count": len(items), "incomplete_results": False, "items": items}

    def graphql(self, query: str, variables: Mapping[str, str | int | None]) -> Any:
        del query
        values = dict(variables)
        self.graphql_calls.append(values)
        if values["after"] is None:
            nodes = [graphql_repository(200, "external/contributed")]
            page_info = {"hasNextPage": True, "endCursor": "next-page"}
        else:
            # Same stable ID, stale transfer name: direct-access metadata must win.
            nodes = [graphql_repository(2, "former-owner/private-repository", private=True)]
            page_info = {"hasNextPage": False, "endCursor": None}
        return {
            "data": {
                "user": {
                    "contributionsCollection": {"unused": True},
                    "repositoriesContributedTo": {"nodes": nodes, "pageInfo": page_info},
                }
            }
        }


def test_paginated_union_retains_private_archived_external_and_zero_activity() -> None:
    api = FakeAPI()
    snapshot = RepositoryDiscoverer(api).discover(
        identity="synthetic-user", start_utc=START, end_utc=END
    )

    by_id = {repository.database_id: repository for repository in snapshot.repositories}
    assert len(snapshot.repositories) == 105
    assert by_id[1].name_with_owner == "direct/repository-1"  # zero-activity direct candidate
    assert by_id[2].private is True
    assert by_id[3].archived is True
    assert by_id[200].name_with_owner == "external/contributed"
    assert by_id[203].name_with_owner == "external/comment-only"
    assert [call[1]["page"] for call in api.rest_calls if call[0] == "user/repos"] == [1, 2]
    assert [call["after"] for call in api.graphql_calls] == [None, "next-page"]

    provenance = {item.source for item in by_id[2].provenance}
    assert provenance == {"direct-access", "contributed", "required-comment-only"}
    assert "private/repository" not in json.dumps(snapshot.as_dict())


def test_deduplication_and_rename_transfer_policy_are_order_independent() -> None:
    api = FakeAPI()
    first = RepositoryDiscoverer(api).discover(
        identity="synthetic-user", start_utc=START, end_utc=END
    )
    with pytest.raises(DiscoveryError, match="database-ID sorted"):
        replace(first, repositories=tuple(reversed(first.repositories)))

    replay = RepositoryDiscoverer(FakeAPI()).discover(
        identity="synthetic-user", start_utc=START, end_utc=END
    )
    assert replay.canonical_json == first.canonical_json
    assert replay.digest == first.digest
    repository = next(item for item in first.repositories if item.database_id == 2)
    assert repository.name_with_owner == "direct/repository-2"


def test_frozen_snapshot_digest_is_embedded_and_tamper_evident() -> None:
    snapshot = RepositoryDiscoverer(FakeAPI()).discover(
        identity="synthetic-user", start_utc=START, end_utc=END
    )
    document = json.loads(snapshot.to_json())
    assert document["digest"] == snapshot.digest
    assert document["repositories"][0]["provenance"] == [
        {
            "source": "direct-access",
            "page": 1,
            "locator": "GET /user/repos?affiliation=all-direct&per_page=100&page=1",
        }
    ]
    assert snapshot.digest.startswith("sha256:")
    assert RepositorySnapshot.from_json(snapshot.to_json()) == snapshot

    document["repositories"][0]["name_with_owner"] = "attacker/changed"
    with pytest.raises(DiscoveryError, match="digest does not match"):
        RepositorySnapshot.from_json(json.dumps(document))


def test_snapshot_with_legacy_v2_runtime_fails_isolation_preflight() -> None:
    snapshot = RepositoryDiscoverer(FakeAPI()).discover(
        identity="synthetic-user", start_utc=START, end_utc=END
    )
    legacy = replace(
        snapshot.repositories[0],
        name_with_owner="synthetic-owner/engineering-journey-v2",
        url="https://github.com/synthetic-owner/engineering-journey-v2",
    )
    isolated = replace(snapshot, repositories=(legacy, *snapshot.repositories[1:]))

    with pytest.raises(DiscoveryError, match="v2 runtime"):
        require_v2_isolation(isolated)


def test_snapshot_change_changes_plan_run_and_requires_new_approval() -> None:
    snapshot = RepositoryDiscoverer(FakeAPI()).discover(
        identity="synthetic-user", start_utc=START, end_utc=END
    )
    candidate = build_plan(identity="synthetic-user", start_utc=START, end_utc=END)
    frozen = bind_snapshot(candidate, snapshot)
    changed_snapshot = replace(snapshot, repositories=snapshot.repositories[:-1])
    changed = bind_snapshot(candidate, changed_snapshot)

    assert candidate.repository_snapshot_digest == "pending-discovery"
    assert frozen.repository_snapshot_digest == snapshot.digest
    assert frozen.digest != candidate.digest
    assert frozen.run_id != candidate.run_id
    assert changed.digest != frozen.digest
    assert changed.run_id != frozen.run_id
    assert approval_matches(candidate, candidate.digest)
    assert not approval_matches(frozen, candidate.digest)
    assert not approval_matches(changed, frozen.digest)


def test_search_cap_and_incomplete_results_fail_closed() -> None:
    class CappedAPI(FakeAPI):
        def rest(self, path: str, parameters: Mapping[str, str | int]) -> Any:
            if path == "search/commits":
                return {"total_count": 1001, "incomplete_results": False, "items": []}
            return super().rest(path, parameters)

    with pytest.raises(DiscoveryError, match="indivisible range"):
        RepositoryDiscoverer(CappedAPI()).discover(
            identity="synthetic-user",
            start_utc="2025-01-02T03:04:05Z",
            end_utc="2025-01-02T03:04:06Z",
        )

    class IncompleteAPI(FakeAPI):
        def rest(self, path: str, parameters: Mapping[str, str | int]) -> Any:
            if path == "search/issues" and str(parameters.get("q", "")).startswith("commenter:"):
                return {"total_count": 1, "incomplete_results": True, "items": []}
            return super().rest(path, parameters)

    with pytest.raises(DiscoveryError, match="did not prove complete"):
        RepositoryDiscoverer(IncompleteAPI()).discover(
            identity="synthetic-user", start_utc=START, end_utc=END
        )


def test_over_cap_search_splits_into_adjacent_ranges_and_deduplicates() -> None:
    start = "2025-01-01T00:00:00Z"
    end = "2025-01-05T00:00:00Z"

    class PartitionAPI:
        def __init__(self, *, root_incomplete: bool = False) -> None:
            self.queries: list[str] = []
            self.root_incomplete = root_incomplete

        def rest(self, path: str, parameters: Mapping[str, str | int]) -> Any:
            assert path == "search/commits"
            query = str(parameters["q"])
            self.queries.append(query)
            if "author-date:2025-01-01..2025-01-04" in query:
                if self.root_incomplete:
                    return {"total_count": 0, "incomplete_results": True, "items": []}
                return {"total_count": 1001, "incomplete_results": False, "items": []}
            if "author-date:2025-01-01..2025-01-02" in query:
                items = [{"repository": rest_repository(1, "example/shared")}]
            elif "author-date:2025-01-03..2025-01-04" in query:
                items = [
                    {"repository": rest_repository(1, "example/shared")},
                    {"repository": rest_repository(2, "example/second")},
                ]
            else:
                raise AssertionError(f"unexpected partition query: {query}")
            return {"total_count": len(items), "incomplete_results": False, "items": items}

        def graphql(self, query: str, variables: Mapping[str, str | int | None]) -> Any:
            raise AssertionError((query, variables))

    api = PartitionAPI()
    discoverer = RepositoryDiscoverer(api)
    sightings: list[Any] = []
    discoverer._search(
        source="range-commit",
        query="author:synthetic-user author-date:2025-01-01..2025-01-04",
        start_utc=start,
        end_utc=end,
        sightings=sightings,
    )

    assert len(api.queries) == 3
    assert "author-date:2025-01-01..2025-01-02" in api.queries[1]
    assert "author-date:2025-01-03..2025-01-04" in api.queries[2]
    assert [repository.database_id for repository in discoverer._merge(sightings)] == [1, 2]

    incomplete_api = PartitionAPI(root_incomplete=True)
    incomplete_discoverer = RepositoryDiscoverer(incomplete_api)
    incomplete_sightings: list[Any] = []
    incomplete_discoverer._search(
        source="range-commit",
        query="author:synthetic-user author-date:2025-01-01..2025-01-04",
        start_utc=start,
        end_utc=end,
        sightings=incomplete_sightings,
    )
    assert len(incomplete_api.queries) == 3
    assert [
        repository.database_id for repository in incomplete_discoverer._merge(incomplete_sightings)
    ] == [1, 2]


def test_real_cli_transport_paces_search_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    times = iter((0.0, 0.0, 0.5, 0.5, 0.5))
    sleeps: list[float] = []
    monkeypatch.setattr(GitHubCLIAPI, "_run", lambda self, arguments: arguments)
    api = GitHubCLIAPI(
        search_interval_seconds=2.0,
        _clock=lambda: next(times),
        _sleep=sleeps.append,
    )

    api.rest("search/commits", {"q": "first"})
    api.rest("search/issues", {"q": "second"})
    api.rest("user/repos", {"page": 1})

    assert sleeps == [1.5]


def test_real_cli_transport_backs_off_boundedly_for_secondary_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outcomes: list[Any] = [
        DiscoveryError("secondary rate limit"),
        DiscoveryError("secondary rate limit"),
        {"ok": True},
    ]
    sleeps: list[float] = []

    def run_once(self: GitHubCLIAPI, arguments: list[str]) -> Any:
        del self, arguments
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(GitHubCLIAPI, "_run", run_once)
    api = GitHubCLIAPI(
        search_interval_seconds=0.0,
        secondary_limit_attempts=3,
        secondary_limit_backoff_seconds=10.0,
        _clock=lambda: 0.0,
        _sleep=sleeps.append,
    )

    assert api.rest("search/commits", {"q": "bounded"}) == {"ok": True}
    assert sleeps == [10.0, 20.0]


def test_real_cli_transport_treats_empty_repository_commits_as_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def empty_repository(self: GitHubCLIAPI, arguments: list[str]) -> Any:
        del self, arguments
        raise DiscoveryError("gh: Git Repository is empty. (HTTP 409)")

    monkeypatch.setattr(GitHubCLIAPI, "_run", empty_repository)
    api = GitHubCLIAPI(search_interval_seconds=0.0)

    assert api.rest("repos/example/empty/commits", {"page": 1}) == []
    with pytest.raises(DiscoveryError, match="empty"):
        api.rest("repos/example/empty/issues", {"page": 1})
