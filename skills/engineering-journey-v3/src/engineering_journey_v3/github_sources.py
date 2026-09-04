"""GitHub contribution classification, retrieval, quota, and retry contracts.

GitHub text returned by this module is evidence, never an instruction.  The
module deliberately stops at normalized source facts; durable writes belong to
later milestones.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum
from random import uniform
from typing import Any, Protocol, Self

from engineering_journey_v3.plan import (
    SOURCE_SEMANTICS_VERSION as PLAN_SOURCE_SEMANTICS_VERSION,
)
from engineering_journey_v3.plan import (
    PlanValidationError,
    normalize_utc,
)

SOURCE_SEMANTICS_VERSION = PLAN_SOURCE_SEMANTICS_VERSION


class SourceError(RuntimeError):
    """Base class for source transport and response failures."""


class TransientSourceError(SourceError):
    """A bounded retry exhausted for a network/DNS or retryable HTTP failure."""


class AuthenticationSourceError(SourceError):
    """GitHub rejected authentication or authorization."""


class ValidationSourceError(SourceError):
    """A request or response violated the source contract."""


class SecondaryLimitError(SourceError):
    """GitHub's secondary/abuse limit stopped the request without an auto-retry."""


class NetworkFailure(OSError):
    """Transport marker for network and DNS failures eligible for retry."""


class SourceKind(StrEnum):
    COMMIT = "commit"
    PULL_REQUEST = "pull_request"
    MERGE = "pull_request_merge"
    REVIEW = "pull_request_review"
    ISSUE_COMMENT = "issue_comment"
    PR_DISCUSSION_COMMENT = "pull_request_discussion_comment"
    PR_LINE_COMMENT = "pull_request_line_comment"


class PrecheckState(StrEnum):
    POSITIVE = "positive"
    NEGATIVE_PROVEN = "negative-proven"
    UNKNOWN = "unknown"


class RateResource(StrEnum):
    CORE = "core"
    GRAPHQL = "graphql"
    SEARCH = "search"


@dataclass(frozen=True, slots=True)
class ProbeResult:
    kind: SourceKind
    state: PrecheckState
    locator: str

    def __post_init__(self) -> None:
        if not self.locator:
            raise ValidationSourceError("pre-check locator is required")


def classify_precheck(probes: Sequence[ProbeResult]) -> PrecheckState:
    """Combine semantic probes without ever treating missing evidence as negative.

    Negative is proven only when every declared source kind independently has a
    negative proof.  Consequently a commits-only negative is always unknown.
    """

    states: dict[SourceKind, PrecheckState] = {}
    for probe in probes:
        previous = states.get(probe.kind)
        if previous is not None and previous != probe.state:
            raise ValidationSourceError(f"conflicting pre-check for {probe.kind.value}")
        states[probe.kind] = probe.state
    if PrecheckState.POSITIVE in states.values():
        return PrecheckState.POSITIVE
    if set(states) == set(SourceKind) and all(
        state == PrecheckState.NEGATIVE_PROVEN for state in states.values()
    ):
        return PrecheckState.NEGATIVE_PROVEN
    return PrecheckState.UNKNOWN


@dataclass(frozen=True, slots=True)
class PrecheckReport:
    state: PrecheckState
    probes: tuple[ProbeResult, ...]


class PrecheckAPI(Protocol):
    def rest(self, path: str, parameters: Mapping[str, str | int]) -> Any: ...


class ContributionPrechecker:
    """Conservative GitHub Search pre-check which never overstates a negative.

    Search can cheaply prove several positive sightings.  It cannot prove absence of
    all review and comment surfaces, so unsupported or incomplete semantics remain
    unknown and force the complete fallback.
    """

    def __init__(self, api: PrecheckAPI) -> None:
        self._api = api

    def check(
        self, *, repository: str, identity: str, start_utc: str, end_utc: str
    ) -> PrecheckReport:
        queries = (
            (
                SourceKind.COMMIT,
                "search/commits",
                f"repo:{repository} author:{identity} author-date:{start_utc}..{end_utc}",
            ),
            (
                SourceKind.PULL_REQUEST,
                "search/issues",
                f"repo:{repository} is:pr author:{identity} created:{start_utc}..{end_utc}",
            ),
            (
                SourceKind.MERGE,
                "search/issues",
                f"repo:{repository} is:pr author:{identity} merged:{start_utc}..{end_utc}",
            ),
            (
                SourceKind.REVIEW,
                "search/issues",
                f"repo:{repository} is:pr reviewed-by:{identity} updated:>={start_utc}",
            ),
            (
                SourceKind.ISSUE_COMMENT,
                "search/issues",
                f"repo:{repository} commenter:{identity} updated:>={start_utc}",
            ),
            (
                SourceKind.PR_DISCUSSION_COMMENT,
                "search/issues",
                f"repo:{repository} is:pr commenter:{identity} updated:>={start_utc}",
            ),
        )
        probes: list[ProbeResult] = []
        for kind, endpoint, query in queries:
            payload = self._api.rest(endpoint, {"q": query, "per_page": 1, "page": 1})
            locator = f"GET /{endpoint}?q={query}"
            if not isinstance(payload, dict):
                raise ValidationSourceError("pre-check search response is not an object")
            total = payload.get("total_count")
            incomplete = payload.get("incomplete_results")
            if isinstance(total, bool) or not isinstance(total, int) or total < 0:
                raise ValidationSourceError("pre-check search count is invalid")
            # An incomplete search can establish a positive from returned count, but
            # never a negative. A complete zero proves only this one semantic.
            if total > 0:
                state = PrecheckState.POSITIVE
            elif incomplete is False:
                state = PrecheckState.NEGATIVE_PROVEN
            else:
                state = PrecheckState.UNKNOWN
            probes.append(ProbeResult(kind, state, locator))
        probes.append(
            ProbeResult(
                SourceKind.PR_LINE_COMMENT,
                PrecheckState.UNKNOWN,
                "no-complete-search-surface:pull-request-line-comments",
            )
        )
        frozen = tuple(probes)
        return PrecheckReport(classify_precheck(frozen), frozen)


@dataclass(frozen=True, slots=True)
class HTTPResponse:
    status: int
    data: Any
    headers: Mapping[str, str] = field(default_factory=dict)


class HTTPBackend(Protocol):
    def request(
        self,
        method: str,
        path: str,
        *,
        parameters: Mapping[str, str | int] | None = None,
        document: Mapping[str, Any] | None = None,
    ) -> HTTPResponse: ...


class GitHubAPITransport(Protocol):
    """The decoded REST/GraphQL boundary implemented by discovery.GitHubCLIAPI."""

    def rest(self, path: str, parameters: Mapping[str, str | int]) -> Any: ...

    def graphql(self, query: str, variables: Mapping[str, Any]) -> Any: ...


@dataclass(slots=True)
class GitHubAPIBackend:
    """Connect the source client to the shipped, authenticated GitHub CLI transport.

    ``GitHubCLIAPI`` returns decoded successful responses and raises on unsuccessful
    commands, so this bridge produces a successful HTTP-shaped response only after the
    transport call has completed. The lower-level injectable backend remains useful for
    deterministic status/header fault tests.
    """

    api: GitHubAPITransport

    def request(
        self,
        method: str,
        path: str,
        *,
        parameters: Mapping[str, str | int] | None = None,
        document: Mapping[str, Any] | None = None,
    ) -> HTTPResponse:
        try:
            if method == "GET" and path != "graphql" and document is None:
                return HTTPResponse(200, self.api.rest(path, parameters or {}))
            if method == "POST" and path == "graphql" and parameters is None:
                if not isinstance(document, Mapping):
                    raise ValidationSourceError("GraphQL request document is missing")
                query = document.get("query")
                variables = document.get("variables")
                if not isinstance(query, str) or not isinstance(variables, Mapping):
                    raise ValidationSourceError("GraphQL request document is invalid")
                return HTTPResponse(200, self.api.graphql(query, variables))
        except OSError as error:
            raise NetworkFailure(str(error)) from error
        except SourceError:
            raise
        except RuntimeError as error:
            # GitHubCLIAPI raises DiscoveryError (a RuntimeError) for a failed command
            # and includes gh's response text. Preserve a supported secondary-limit
            # signal rather than collapsing it into generic validation state.
            message = str(error)
            if "secondary rate limit" in message.casefold():
                return HTTPResponse(
                    403,
                    {"message": message},
                    {"X-GitHub-Error": "secondary rate limit"},
                )
            # Other CLI failures do not expose structured status/headers, so retrying
            # or guessing an authentication class would violate the error contract.
            raise ValidationSourceError("GitHub CLI API request failed") from error
        raise ValidationSourceError("unsupported GitHub API transport request")


@dataclass(frozen=True, slots=True)
class Quota:
    limit: int | None = None
    remaining: int | None = None
    reset_epoch: int | None = None


@dataclass(frozen=True, slots=True)
class SecondaryLimitState:
    active: bool = False
    retry_after_seconds: int | None = None
    occurrences: int = 0


@dataclass(slots=True)
class QuotaState:
    """Independent primary resource buckets and secondary-limit state."""

    core: Quota = field(default_factory=Quota)
    graphql: Quota = field(default_factory=Quota)
    search: Quota = field(default_factory=Quota)
    secondary: SecondaryLimitState = field(default_factory=SecondaryLimitState)

    def quota_for(self, resource: RateResource) -> Quota:
        return {
            RateResource.CORE: self.core,
            RateResource.GRAPHQL: self.graphql,
            RateResource.SEARCH: self.search,
        }[resource]

    def update(self, resource: RateResource, headers: Mapping[str, str], status: int) -> None:
        lowered = {key.lower(): value for key, value in headers.items()}

        def number(name: str) -> int | None:
            value = lowered.get(name)
            try:
                return int(value) if value is not None else None
            except ValueError:
                return None

        observed = Quota(
            number("x-ratelimit-limit"),
            number("x-ratelimit-remaining"),
            number("x-ratelimit-reset"),
        )
        if observed != Quota():
            setattr(self, resource.value, observed)
        retry_after = number("retry-after")
        secondary = (status == 403 and retry_after is not None) or (
            status in {403, 429} and "secondary" in lowered.get("x-github-error", "").lower()
        )
        if secondary:
            self.secondary = SecondaryLimitState(
                active=True,
                retry_after_seconds=retry_after,
                occurrences=self.secondary.occurrences + 1,
            )
        elif status < 400:
            self.secondary = replace(self.secondary, active=False, retry_after_seconds=None)


class GitHubClient:
    """Transport with explicit error classes, quotas, and bounded retries."""

    def __init__(
        self,
        backend: HTTPBackend,
        *,
        max_retries: int = 3,
        base_delay: float = 0.25,
        jitter: Callable[[int], float] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if max_retries < 0 or base_delay < 0:
            raise ValueError("retry settings cannot be negative")
        self._backend = backend
        self._max_retries = max_retries
        self._base_delay = base_delay
        self._jitter = jitter or (lambda attempt: uniform(0.0, base_delay * (2**attempt)))
        self._sleep = sleep
        self.quotas = QuotaState()
        self.retry_count = 0

    @classmethod
    def from_github_api(cls, api: GitHubAPITransport, **settings: Any) -> Self:
        """Build a source client on the real GitHubCLIAPI REST/GraphQL boundary."""

        return cls(GitHubAPIBackend(api), **settings)

    def rest(self, path: str, parameters: Mapping[str, str | int]) -> Any:
        resource = RateResource.SEARCH if path.startswith("search/") else RateResource.CORE
        return self._request("GET", path, resource, parameters=parameters)

    def graphql(self, query: str, variables: Mapping[str, Any]) -> Any:
        return self._request(
            "POST",
            "graphql",
            RateResource.GRAPHQL,
            document={"query": query, "variables": dict(variables)},
        )

    def _request(
        self,
        method: str,
        path: str,
        resource: RateResource,
        *,
        parameters: Mapping[str, str | int] | None = None,
        document: Mapping[str, Any] | None = None,
    ) -> Any:
        for attempt in range(self._max_retries + 1):
            try:
                response = self._backend.request(
                    method, path, parameters=parameters, document=document
                )
            except NetworkFailure as error:
                if attempt == self._max_retries:
                    raise TransientSourceError("GitHub network/DNS retries exhausted") from error
                self._backoff(attempt)
                continue
            self.quotas.update(resource, response.headers, response.status)
            if response.status < 400:
                return response.data
            if response.status in {403, 429} and self._is_secondary_limit(response):
                # Body detection matters for real GitHub 429 responses, whose
                # secondary-limit message need not be duplicated in a custom header.
                self.quotas.secondary = SecondaryLimitState(
                    active=True,
                    retry_after_seconds=self._retry_after(response.headers),
                    occurrences=self.quotas.secondary.occurrences
                    + (0 if self.quotas.secondary.active else 1),
                )
                raise SecondaryLimitError("GitHub secondary rate limit is active")
            retryable = response.status == 429 or response.status in {500, 502, 503, 504}
            if retryable:
                if attempt == self._max_retries:
                    raise TransientSourceError(
                        f"GitHub transient HTTP {response.status} retries exhausted"
                    )
                self._backoff(attempt)
                continue
            if response.status in {401, 403}:
                raise AuthenticationSourceError(f"GitHub authentication failed ({response.status})")
            raise ValidationSourceError(f"GitHub request failed ({response.status})")
        raise AssertionError("unreachable retry loop")

    @staticmethod
    def _retry_after(headers: Mapping[str, str]) -> int | None:
        value = next(
            (value for key, value in headers.items() if key.lower() == "retry-after"), None
        )
        try:
            return int(value) if value is not None else None
        except ValueError:
            return None

    @classmethod
    def _is_secondary_limit(cls, response: HTTPResponse) -> bool:
        headers = {key.lower(): value.lower() for key, value in response.headers.items()}
        message = response.data.get("message") if isinstance(response.data, dict) else None
        body_marks_secondary = isinstance(message, str) and (
            "secondary rate limit" in message.casefold() or "abuse detection" in message.casefold()
        )
        return (
            cls._retry_after(response.headers) is not None and body_marks_secondary
        ) or "secondary" in headers.get("x-github-error", "")

    def _backoff(self, attempt: int) -> None:
        self.retry_count += 1
        exponential = self._base_delay * (2**attempt)
        bounded_jitter = min(exponential, max(0.0, self._jitter(attempt)))
        self._sleep(exponential + bounded_jitter)


@dataclass(frozen=True, slots=True)
class SourceSighting:
    api: str
    locator: str


@dataclass(frozen=True, slots=True)
class SourceFact:
    """A normalized GitHub fact with stable identity and explicit attribution."""

    source_identity: str
    subtype: SourceKind
    identity: str
    repository: str
    recorded_at: str
    url: str | None
    evidence: Mapping[str, Any]
    attribution: Mapping[str, Any]
    sightings: tuple[SourceSighting, ...]
    semantics_version: str = SOURCE_SEMANTICS_VERSION

    def __post_init__(self) -> None:
        if not self.source_identity.startswith("github:") or not self.identity:
            raise ValidationSourceError("source identity and runtime identity are required")
        if self.repository.count("/") != 1 or not self.sightings:
            raise ValidationSourceError("repository and source sightings are required")
        if normalize_utc(self.recorded_at) != self.recorded_at:
            raise ValidationSourceError("source timestamp must be canonical UTC")
        if self.url is not None and not self.url.startswith("https://github.com/"):
            raise ValidationSourceError("source URL must be a GitHub URL")


class FactAccumulator:
    """Merge duplicate sightings within a repository without collapsing forks."""

    def __init__(self) -> None:
        self._facts: dict[tuple[str, str], SourceFact] = {}

    def add(self, fact: SourceFact) -> None:
        accumulator_key = (fact.repository, fact.source_identity)
        previous = self._facts.get(accumulator_key)
        if previous is None:
            self._facts[accumulator_key] = fact
            return
        comparable = ("subtype", "identity", "repository", "recorded_at")
        if any(getattr(previous, name) != getattr(fact, name) for name in comparable):
            raise ValidationSourceError("duplicate source sightings disagree")
        if previous.url is not None and fact.url is not None and previous.url != fact.url:
            raise ValidationSourceError("duplicate source URLs disagree")
        sightings = tuple(
            sorted(
                set(previous.sightings + fact.sightings), key=lambda item: (item.api, item.locator)
            )
        )
        attribution = dict(previous.attribution)
        for key, value in fact.attribution.items():
            if key in attribution and attribution[key] != value:
                raise ValidationSourceError("duplicate attribution fields disagree")
            attribution[key] = value
        evidence = dict(previous.evidence)
        for key, value in fact.evidence.items():
            if key in evidence and evidence[key] != value:
                raise ValidationSourceError("duplicate evidence fields disagree")
            evidence[key] = value
        self._facts[accumulator_key] = replace(
            previous,
            url=previous.url or fact.url,
            evidence=evidence,
            attribution=attribution,
            sightings=sightings,
        )

    def facts(self) -> tuple[SourceFact, ...]:
        return tuple(
            sorted(
                self._facts.values(),
                key=lambda fact: (fact.recorded_at, fact.repository, fact.source_identity),
            )
        )


class ContributionRetriever:
    """Complete paginated REST fallback for all initial source semantics."""

    def __init__(
        self, api: GitHubClient, page_observer: Callable[[str, int], None] | None = None
    ) -> None:
        self.api = api
        self._page_observer = page_observer

    def retrieve(
        self,
        *,
        repository: str,
        identity: str,
        start_utc: str,
        end_utc: str,
        probes: Sequence[ProbeResult] = (),
    ) -> tuple[SourceFact, ...]:
        state = classify_precheck(probes)
        if state == PrecheckState.NEGATIVE_PROVEN:
            return ()
        # Positive and unknown both run the same complete fallback.  A positive
        # probe is evidence of presence, not permission to omit other semantics.
        accumulator = FactAccumulator()
        pulls = self._all_pages(
            f"repos/{repository}/pulls", {"state": "all", "sort": "created", "direction": "asc"}
        )
        issues = self._all_pages(f"repos/{repository}/issues", {"state": "all", "since": start_utc})
        self._commits(accumulator, repository, identity, start_utc, end_utc)
        self._pulls_and_reviews(accumulator, pulls, repository, identity, start_utc, end_utc)
        self._issue_and_discussion_comments(
            accumulator, issues, repository, identity, start_utc, end_utc
        )
        self._line_comments(accumulator, repository, identity, start_utc, end_utc)
        return accumulator.facts()

    def _all_pages(self, path: str, parameters: Mapping[str, str | int]) -> list[Any]:
        page = 1
        result: list[Any] = []
        while True:
            query = {**parameters, "per_page": 100, "page": page}
            payload = self.api.rest(path, query)
            if not isinstance(payload, list):
                raise ValidationSourceError(f"paginated response for {path} is not an array")
            if self._page_observer is not None:
                self._page_observer(path, page)
            result.extend(payload)
            if len(payload) < 100:
                return result
            page += 1

    @staticmethod
    def _in_range(timestamp: str, start_utc: str, end_utc: str) -> bool:
        try:
            canonical = normalize_utc(timestamp)
        except (PlanValidationError, TypeError, ValueError) as error:
            raise ValidationSourceError("GitHub source timestamp is invalid") from error
        return canonical == timestamp and start_utc <= timestamp < end_utc

    @staticmethod
    def _login(value: Any) -> str | None:
        return (
            value.get("login")
            if isinstance(value, dict) and isinstance(value.get("login"), str)
            else None
        )

    def _fact(
        self,
        item: Any,
        *,
        kind: SourceKind,
        identity: str,
        repository: str,
        timestamp_field: str,
        locator: str,
        attribution: Mapping[str, Any],
        evidence: Mapping[str, Any],
    ) -> SourceFact:
        if not isinstance(item, dict):
            raise ValidationSourceError(f"{kind.value} item is not an object")
        stable_id = item.get("node_id") or item.get("id") or item.get("sha")
        timestamp = item.get(timestamp_field)
        if not isinstance(stable_id, str | int) or not isinstance(timestamp, str):
            raise ValidationSourceError(f"{kind.value} source identity/timestamp is missing")
        url = item.get("html_url")
        if url is not None and not isinstance(url, str):
            raise ValidationSourceError(f"{kind.value} URL is invalid")
        return SourceFact(
            source_identity=f"github:{kind.value}:{stable_id}",
            subtype=kind,
            identity=identity,
            repository=repository,
            recorded_at=timestamp,
            url=url,
            evidence=dict(evidence),
            attribution=dict(attribution),
            sightings=(SourceSighting("rest", locator),),
        )

    def _commits(
        self, out: FactAccumulator, repository: str, identity: str, start: str, end: str
    ) -> None:
        path = f"repos/{repository}/commits"
        items = self._all_pages(path, {"author": identity, "since": start, "until": end})
        for item in items:
            if not isinstance(item, dict):
                raise ValidationSourceError("commit item is not an object")
            commit = item.get("commit")
            author = commit.get("author") if isinstance(commit, dict) else None
            timestamp = author.get("date") if isinstance(author, dict) else None
            if not isinstance(timestamp, str) or not self._in_range(timestamp, start, end):
                continue
            material = dict(item)
            material["source_timestamp"] = timestamp
            out.add(
                self._fact(
                    material,
                    kind=SourceKind.COMMIT,
                    identity=identity,
                    repository=repository,
                    timestamp_field="source_timestamp",
                    locator=path,
                    attribution={
                        "author_login": self._login(item.get("author")),
                        "matched_identity": identity,
                    },
                    evidence={
                        "sha": item.get("sha"),
                        "message": commit.get("message") if isinstance(commit, dict) else None,
                    },
                )
            )

    def _pulls_and_reviews(
        self,
        out: FactAccumulator,
        pulls: list[Any],
        repository: str,
        identity: str,
        start: str,
        end: str,
    ) -> None:
        for pull in pulls:
            if not isinstance(pull, dict) or not isinstance(pull.get("number"), int):
                raise ValidationSourceError("pull request item is invalid")
            number = pull["number"]
            author_login = self._login(pull.get("user"))
            created = pull.get("created_at")
            if (
                author_login == identity
                and isinstance(created, str)
                and self._in_range(created, start, end)
            ):
                out.add(
                    self._fact(
                        pull,
                        kind=SourceKind.PULL_REQUEST,
                        identity=identity,
                        repository=repository,
                        timestamp_field="created_at",
                        locator=f"repos/{repository}/pulls",
                        attribution={"author_login": author_login, "matched_identity": identity},
                        evidence={
                            "number": number,
                            "title": pull.get("title"),
                            "body": pull.get("body"),
                        },
                    )
                )
            merged = pull.get("merged_at")
            if (
                author_login == identity
                and isinstance(merged, str)
                and self._in_range(merged, start, end)
            ):
                merge_item = {**pull, "node_id": f"{pull.get('node_id') or pull.get('id')}:merge"}
                out.add(
                    self._fact(
                        merge_item,
                        kind=SourceKind.MERGE,
                        identity=identity,
                        repository=repository,
                        timestamp_field="merged_at",
                        locator=f"repos/{repository}/pulls",
                        attribution={
                            "pull_author_login": author_login,
                            "merged_by_login": self._login(pull.get("merged_by")),
                            "matched_identity": identity,
                        },
                        evidence={
                            "number": number,
                            "merge_commit_sha": pull.get("merge_commit_sha"),
                            "title": pull.get("title"),
                        },
                    )
                )
            reviews_path = f"repos/{repository}/pulls/{number}/reviews"
            for review in self._all_pages(reviews_path, {}):
                if not isinstance(review, dict):
                    raise ValidationSourceError("review item is invalid")
                submitted = review.get("submitted_at")
                reviewer = self._login(review.get("user"))
                if (
                    reviewer == identity
                    and isinstance(submitted, str)
                    and self._in_range(submitted, start, end)
                ):
                    out.add(
                        self._fact(
                            review,
                            kind=SourceKind.REVIEW,
                            identity=identity,
                            repository=repository,
                            timestamp_field="submitted_at",
                            locator=reviews_path,
                            attribution={"reviewer_login": reviewer, "matched_identity": identity},
                            evidence={
                                "pull_number": number,
                                "state": review.get("state"),
                                "body": review.get("body"),
                            },
                        )
                    )

    def _issue_and_discussion_comments(
        self,
        out: FactAccumulator,
        issues: list[Any],
        repository: str,
        identity: str,
        start: str,
        end: str,
    ) -> None:
        for issue in issues:
            if not isinstance(issue, dict) or not isinstance(issue.get("number"), int):
                raise ValidationSourceError("issue item is invalid")
            number = issue["number"]
            kind = (
                SourceKind.PR_DISCUSSION_COMMENT
                if "pull_request" in issue
                else SourceKind.ISSUE_COMMENT
            )
            path = f"repos/{repository}/issues/{number}/comments"
            for comment in self._all_pages(path, {"since": start}):
                if not isinstance(comment, dict):
                    raise ValidationSourceError("comment item is invalid")
                created = comment.get("created_at")
                author = self._login(comment.get("user"))
                if (
                    author == identity
                    and isinstance(created, str)
                    and self._in_range(created, start, end)
                ):
                    out.add(
                        self._fact(
                            comment,
                            kind=kind,
                            identity=identity,
                            repository=repository,
                            timestamp_field="created_at",
                            locator=path,
                            attribution={"author_login": author, "matched_identity": identity},
                            evidence={"issue_or_pull_number": number, "body": comment.get("body")},
                        )
                    )

    def _line_comments(
        self, out: FactAccumulator, repository: str, identity: str, start: str, end: str
    ) -> None:
        path = f"repos/{repository}/pulls/comments"
        for comment in self._all_pages(
            path, {"since": start, "sort": "created", "direction": "asc"}
        ):
            if not isinstance(comment, dict):
                raise ValidationSourceError("line comment item is invalid")
            created = comment.get("created_at")
            author = self._login(comment.get("user"))
            if (
                author == identity
                and isinstance(created, str)
                and self._in_range(created, start, end)
            ):
                out.add(
                    self._fact(
                        comment,
                        kind=SourceKind.PR_LINE_COMMENT,
                        identity=identity,
                        repository=repository,
                        timestamp_field="created_at",
                        locator=path,
                        attribution={"author_login": author, "matched_identity": identity},
                        evidence={
                            "pull_request_url": comment.get("pull_request_url"),
                            "path": comment.get("path"),
                            "line": comment.get("line"),
                            "body": comment.get("body"),
                        },
                    )
                )
