from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any

import pytest

from engineering_journey_v3.github_sources import (
    AuthenticationSourceError,
    ContributionPrechecker,
    ContributionRetriever,
    FactAccumulator,
    GitHubAPIBackend,
    GitHubClient,
    HTTPResponse,
    NetworkFailure,
    PrecheckState,
    ProbeResult,
    RateResource,
    SecondaryLimitError,
    SourceFact,
    SourceKind,
    SourceSighting,
    TransientSourceError,
    ValidationSourceError,
    classify_precheck,
)

START = "2025-01-01T00:00:00Z"
EVENT = "2025-06-01T12:00:00Z"
END = "2026-01-01T00:00:00Z"
LOGIN = "synthetic-user"
REPOSITORY = "example/public-fixture"


class QueueBackend:
    def __init__(self, responses: list[HTTPResponse | BaseException]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, str, Mapping[str, str | int] | None]] = []

    def request(
        self,
        method: str,
        path: str,
        *,
        parameters: Mapping[str, str | int] | None = None,
        document: Mapping[str, Any] | None = None,
    ) -> HTTPResponse:
        del document
        self.calls.append((method, path, parameters))
        result = self.responses.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


class TruthSetBackend:
    """Scrubbed bounded truth set containing every declared source subtype."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    @staticmethod
    def item(
        kind: str,
        number: int,
        *,
        timestamp_field: str = "created_at",
        login: str = LOGIN,
    ) -> dict[str, Any]:
        return {
            "id": number,
            "node_id": f"{kind}-{number}",
            timestamp_field: EVENT,
            "user": {"login": login},
            "html_url": f"https://github.com/{REPOSITORY}/{kind}/{number}",
            "title": f"Synthetic {kind}",
            "body": f"Synthetic {kind} evidence",
        }

    def request(
        self,
        method: str,
        path: str,
        *,
        parameters: Mapping[str, str | int] | None = None,
        document: Mapping[str, Any] | None = None,
    ) -> HTTPResponse:
        del method, document
        page = int((parameters or {}).get("page", 1))
        self.calls.append((path, page))
        if path.endswith("/pulls"):
            pull = self.item("pull", 1)
            pull.update(
                {
                    "number": 1,
                    "merged_at": EVENT,
                    "merged_by": {"login": "synthetic-maintainer"},
                    "merge_commit_sha": "abc123",
                }
            )
            return HTTPResponse(200, [pull])
        if path.endswith("/issues"):
            issue = {"number": 2}
            discussion = {"number": 1, "pull_request": {"url": "synthetic"}}
            return HTTPResponse(200, [issue, discussion])
        if path.endswith("/commits"):
            commit = self.item("commit", 3)
            commit.update(
                {
                    "sha": "deadbeef",
                    "author": {"login": LOGIN},
                    "commit": {"author": {"date": EVENT}, "message": "Synthetic commit"},
                }
            )
            return HTTPResponse(200, [commit])
        if path.endswith("/pulls/1/reviews"):
            return HTTPResponse(200, [self.item("review", 4, timestamp_field="submitted_at")])
        if path.endswith("/issues/2/comments"):
            return HTTPResponse(200, [self.item("issue-comment", 5)])
        if path.endswith("/issues/1/comments"):
            return HTTPResponse(200, [self.item("discussion-comment", 6)])
        if path.endswith("/pulls/comments"):
            comment = self.item("line-comment", 7)
            comment.update({"path": "src/example.py", "line": 3})
            return HTTPResponse(200, [comment])
        raise AssertionError(f"unexpected path {path}")


def negative_probes() -> list[ProbeResult]:
    return [
        ProbeResult(kind, PrecheckState.NEGATIVE_PROVEN, f"probe:{kind.value}")
        for kind in SourceKind
    ]


def test_three_state_precheck_rejects_commit_only_negative_and_conflicts() -> None:
    commit_only = [ProbeResult(SourceKind.COMMIT, PrecheckState.NEGATIVE_PROVEN, "commits-count")]
    assert classify_precheck(commit_only) == PrecheckState.UNKNOWN
    assert classify_precheck(negative_probes()) == PrecheckState.NEGATIVE_PROVEN
    assert (
        classify_precheck(
            commit_only + [ProbeResult(SourceKind.REVIEW, PrecheckState.POSITIVE, "review-count")]
        )
        == PrecheckState.POSITIVE
    )
    with pytest.raises(ValidationSourceError, match="conflicting"):
        classify_precheck(
            commit_only + [ProbeResult(SourceKind.COMMIT, PrecheckState.POSITIVE, "other-probe")]
        )


def test_search_precheck_is_positive_on_a_sighting_and_unknown_on_absence() -> None:
    class SearchAPI:
        def __init__(self, positive: bool) -> None:
            self.positive = positive
            self.calls: list[str] = []

        def rest(self, path: str, parameters: Mapping[str, str | int]) -> Any:
            del parameters
            self.calls.append(path)
            found = self.positive and len(self.calls) == 2
            return {"total_count": int(found), "incomplete_results": False, "items": []}

    positive_api = SearchAPI(True)
    positive = ContributionPrechecker(positive_api).check(
        repository=REPOSITORY, identity=LOGIN, start_utc=START, end_utc=END
    )
    assert positive.state == PrecheckState.POSITIVE
    assert len(positive.probes) == len(SourceKind)
    assert positive_api.calls.count("search/commits") == 1
    assert positive_api.calls.count("search/issues") == 5

    absent = ContributionPrechecker(SearchAPI(False)).check(
        repository=REPOSITORY, identity=LOGIN, start_utc=START, end_utc=END
    )
    assert absent.state == PrecheckState.UNKNOWN
    assert absent.probes[-1] == ProbeResult(
        SourceKind.PR_LINE_COMMENT,
        PrecheckState.UNKNOWN,
        "no-complete-search-surface:pull-request-line-comments",
    )


def test_bounded_truth_set_has_zero_silent_false_negatives_and_actual_timestamps() -> None:
    backend = TruthSetBackend()
    retriever = ContributionRetriever(GitHubClient(backend))
    facts = retriever.retrieve(
        repository=REPOSITORY,
        identity=LOGIN,
        start_utc=START,
        end_utc=END,
        # The incomplete commits-only negative is unknown and must invoke fallback.
        probes=[ProbeResult(SourceKind.COMMIT, PrecheckState.NEGATIVE_PROVEN, "commit-probe")],
    )

    assert {fact.subtype for fact in facts} == set(SourceKind)
    assert len(facts) == 7
    assert {fact.recorded_at for fact in facts} == {EVENT}
    assert all(fact.identity == LOGIN and fact.repository == REPOSITORY for fact in facts)
    assert all(fact.url and fact.url.startswith("https://github.com/") for fact in facts)
    merge = next(fact for fact in facts if fact.subtype == SourceKind.MERGE)
    assert merge.attribution == {
        "pull_author_login": LOGIN,
        "merged_by_login": "synthetic-maintainer",
        "matched_identity": LOGIN,
    }


def test_complete_negative_skips_every_fetch_but_unknown_does_not() -> None:
    backend = TruthSetBackend()
    retriever = ContributionRetriever(GitHubClient(backend))
    assert (
        retriever.retrieve(
            repository=REPOSITORY,
            identity=LOGIN,
            start_utc=START,
            end_utc=END,
            probes=negative_probes(),
        )
        == ()
    )
    assert backend.calls == []


def test_rest_graphql_duplicate_sightings_and_attribution_merge_consistently() -> None:
    rest = SourceFact(
        source_identity="github:commit:C_node",
        subtype=SourceKind.COMMIT,
        identity=LOGIN,
        repository=REPOSITORY,
        recorded_at=EVENT,
        url=f"https://github.com/{REPOSITORY}/commit/deadbeef",
        evidence={"message": "Synthetic"},
        attribution={"author_login": LOGIN},
        sightings=(SourceSighting("rest", "GET /commits"),),
    )
    graphql = replace(
        rest,
        evidence={"sha": "deadbeef"},
        attribution={"matched_identity": LOGIN},
        sightings=(SourceSighting("graphql", "repository.object"),),
    )
    accumulator = FactAccumulator()
    accumulator.add(graphql)
    accumulator.add(rest)
    merged = accumulator.facts()[0]
    assert merged.source_identity == rest.source_identity
    assert [sighting.api for sighting in merged.sightings] == ["graphql", "rest"]
    assert merged.attribution == {"matched_identity": LOGIN, "author_login": LOGIN}
    assert merged.evidence == {"sha": "deadbeef", "message": "Synthetic"}

    with pytest.raises(ValidationSourceError, match="disagree"):
        accumulator.add(replace(rest, recorded_at="2025-07-01T00:00:00Z"))


def test_paginator_requests_second_page_after_exactly_one_hundred_items() -> None:
    first_page = [TruthSetBackend.item("unused", number) for number in range(100)]
    backend = QueueBackend([HTTPResponse(200, first_page), HTTPResponse(200, [])])
    retriever = ContributionRetriever(GitHubClient(backend))
    assert len(retriever._all_pages("repos/example/repo/unused", {})) == 100
    assert [call[2]["page"] for call in backend.calls if call[2] is not None] == [1, 2]


def test_paginated_adapter_rejects_a_malformed_page() -> None:
    backend = QueueBackend([HTTPResponse(200, {"items": []})])
    retriever = ContributionRetriever(GitHubClient(backend))
    with pytest.raises(ValidationSourceError, match="not an array"):
        retriever._all_pages("repos/example/repo/commits", {})


def test_core_graphql_search_and_secondary_limits_are_independent() -> None:
    backend = QueueBackend(
        [
            HTTPResponse(200, [], {"X-RateLimit-Limit": "5000", "X-RateLimit-Remaining": "4999"}),
            HTTPResponse(200, {}, {"X-RateLimit-Limit": "5000", "X-RateLimit-Remaining": "4000"}),
            HTTPResponse(200, {}, {"X-RateLimit-Limit": "30", "X-RateLimit-Remaining": "29"}),
            HTTPResponse(403, {}, {"Retry-After": "60", "X-GitHub-Error": "secondary rate limit"}),
        ]
    )
    client = GitHubClient(backend, max_retries=0)
    client.rest("user/repos", {})
    client.graphql("query { viewer { login } }", {})
    client.rest("search/issues", {"q": "synthetic"})
    with pytest.raises(SecondaryLimitError):
        client.rest("user/repos", {})

    assert client.quotas.quota_for(RateResource.CORE).remaining == 4999
    assert client.quotas.quota_for(RateResource.GRAPHQL).remaining == 4000
    assert client.quotas.quota_for(RateResource.SEARCH).remaining == 29
    assert client.quotas.secondary.active
    assert client.quotas.secondary.retry_after_seconds == 60
    assert client.quotas.secondary.occurrences == 1


def test_real_api_bridge_uses_rest_and_graphql_transport_methods() -> None:
    class API:
        def __init__(self) -> None:
            self.calls: list[tuple[str, Any, Any]] = []

        def rest(self, path: str, parameters: Mapping[str, str | int]) -> Any:
            self.calls.append(("rest", path, parameters))
            return [{"transport": "rest"}]

        def graphql(self, query: str, variables: Mapping[str, Any]) -> Any:
            self.calls.append(("graphql", query, variables))
            return {"transport": "graphql"}

    api = API()
    client = GitHubClient.from_github_api(api)
    assert client.rest("user/repos", {"page": 1}) == [{"transport": "rest"}]
    assert client.graphql("query($login:String!){user(login:$login){id}}", {"login": LOGIN}) == {
        "transport": "graphql"
    }
    assert api.calls == [
        ("rest", "user/repos", {"page": 1}),
        ("graphql", "query($login:String!){user(login:$login){id}}", {"login": LOGIN}),
    ]

    with pytest.raises(ValidationSourceError, match="unsupported"):
        GitHubAPIBackend(api).request("DELETE", "user/repos")


def test_real_api_bridge_preserves_cli_secondary_limit_signal() -> None:
    class LimitedAPI:
        def rest(self, path: str, parameters: Mapping[str, str | int]) -> Any:
            del path, parameters
            raise RuntimeError("exceeded a secondary rate limit (HTTP 429)")

        def graphql(self, query: str, variables: Mapping[str, Any]) -> Any:
            raise AssertionError((query, variables))

    client = GitHubClient.from_github_api(LimitedAPI())
    with pytest.raises(SecondaryLimitError):
        client.rest("user/repos", {})
    assert client.quotas.secondary.active
    assert client.quotas.secondary.occurrences == 1


def test_429_secondary_limit_message_is_not_generic_transient_state() -> None:
    message = "You have exceeded a secondary rate limit. Please wait a few minutes."
    backend = QueueBackend([HTTPResponse(429, {"message": message}, {"Retry-After": "17"})])
    client = GitHubClient(backend, max_retries=3)
    with pytest.raises(SecondaryLimitError):
        client.rest("user/repos", {})
    assert len(backend.calls) == 1
    assert client.retry_count == 0
    assert client.quotas.secondary == client.quotas.secondary.__class__(True, 17, 1)


def test_ordinary_429_with_retry_after_but_no_secondary_message_retries() -> None:
    backend = QueueBackend(
        [
            HTTPResponse(429, {"message": "rate limited"}, {"Retry-After": "1"}),
            HTTPResponse(200, {"ok": True}),
        ]
    )
    client = GitHubClient(backend, max_retries=1, base_delay=0, sleep=lambda delay: None)
    assert client.rest("user/repos", {}) == {"ok": True}
    assert client.retry_count == 1
    assert not client.quotas.secondary.active


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_only_declared_transient_http_classes_retry(status: int) -> None:
    delays: list[float] = []
    backend = QueueBackend([HTTPResponse(status, {}), HTTPResponse(200, {"ok": True})])
    client = GitHubClient(
        backend, max_retries=1, base_delay=0.5, jitter=lambda attempt: 0.125, sleep=delays.append
    )
    assert client.rest("user/repos", {}) == {"ok": True}
    assert delays == [0.625]
    assert client.retry_count == 1


def test_network_retries_are_bounded_and_auth_validation_fail_directly() -> None:
    backend = QueueBackend([NetworkFailure("dns"), NetworkFailure("dns")])
    client = GitHubClient(backend, max_retries=1, base_delay=0, sleep=lambda delay: None)
    with pytest.raises(TransientSourceError, match="exhausted"):
        client.rest("user/repos", {})
    assert len(backend.calls) == 2

    for status, error in [
        (401, AuthenticationSourceError),
        (403, AuthenticationSourceError),
        (422, ValidationSourceError),
    ]:
        direct = QueueBackend([HTTPResponse(status, {})])
        with pytest.raises(error):
            GitHubClient(direct, max_retries=3).rest("user/repos", {})
        assert len(direct.calls) == 1
