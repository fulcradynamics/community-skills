"""Complete candidate-repository discovery and immutable snapshot construction."""

from __future__ import annotations

import hashlib
import json
import subprocess
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, cast

from engineering_journey_v3.plan import Plan, PlanValidationError, normalize_utc

SNAPSHOT_SCHEMA_VERSION = "engineering-journey-v3-repository-snapshot/v1"
DISCOVERY_POLICY_VERSION = "github-repository-union/v1"
_SOURCE_ORDER = {
    "direct-access": 0,
    "contributed": 1,
    "range-commit": 2,
    "range-authored": 3,
    "required-comment-only": 4,
}
_BOUNDED_SEARCH_QUALIFIER = {
    "range-commit": "author-date",
    "range-authored": "created",
}


def _search_date_range(start_utc: str, end_utc: str) -> str:
    """Return GitHub Search's inclusive calendar dates for a half-open UTC window."""
    start = datetime.fromisoformat(start_utc.replace("Z", "+00:00"))
    end = datetime.fromisoformat(end_utc.replace("Z", "+00:00"))
    last_included = end - timedelta(microseconds=1)
    return f"{start.date().isoformat()}..{last_included.date().isoformat()}"


_CONTRIBUTIONS_QUERY = """
query($login:String!,$after:String) {
  user(login:$login) {
    repositoriesContributedTo(
      first:100, after:$after, includeUserRepositories:true,
      contributionTypes:[COMMIT,ISSUE,PULL_REQUEST,PULL_REQUEST_REVIEW,REPOSITORY]
    ) {
      nodes { databaseId id nameWithOwner isPrivate isArchived url }
      pageInfo { hasNextPage endCursor }
    }
  }
}
"""


class DiscoveryError(RuntimeError):
    """Raised when discovery cannot prove that its candidate union is complete."""


def require_v2_isolation(snapshot: RepositorySnapshot) -> None:
    """Fail before ingestion when the frozen scope contains the legacy v2 runtime."""
    for repository in snapshot.repositories:
        repository_name = repository.name_with_owner.rsplit("/", maxsplit=1)[-1]
        normalized = repository_name.casefold().replace("_", "-")
        if normalized == "engineering-journey-v2":
            raise DiscoveryError(
                "frozen repository snapshot includes Engineering Journey v2 runtime; "
                "a newly approved isolated snapshot is required"
            )


class GitHubAPI(Protocol):
    """Small injectable boundary for GitHub REST and GraphQL reads."""

    def rest(self, path: str, parameters: Mapping[str, str | int]) -> Any:
        """Return decoded JSON for one explicitly numbered REST page."""
        ...

    def graphql(self, query: str, variables: Mapping[str, str | int | None]) -> Any:
        """Return decoded JSON for one GraphQL cursor page."""
        ...


@dataclass(slots=True)
class GitHubCLIAPI:
    """Read-only GitHub API transport using the authenticated GitHub CLI session."""

    executable: str = "gh"
    search_interval_seconds: float = 6.1
    secondary_limit_attempts: int = 3
    secondary_limit_backoff_seconds: float = 60.0
    _clock: Callable[[], float] = field(default=time.monotonic, repr=False)
    _sleep: Callable[[float], None] = field(default=time.sleep, repr=False)
    _last_search_at: float | None = field(default=None, init=False, repr=False)

    def _run(self, arguments: list[str]) -> Any:
        try:
            result = subprocess.run(
                [self.executable, "api", *arguments],
                check=False,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError as error:
            raise DiscoveryError("GitHub CLI (gh) is required for repository discovery") from error
        if result.returncode != 0:
            message = result.stderr.strip() or "GitHub API request failed"
            raise DiscoveryError(message)
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise DiscoveryError("GitHub CLI returned malformed JSON") from error

    def rest(self, path: str, parameters: Mapping[str, str | int]) -> Any:
        if path.startswith("search/"):
            now = self._clock()
            if self._last_search_at is not None:
                self._sleep(max(0.0, self.search_interval_seconds - (now - self._last_search_at)))
            self._last_search_at = self._clock()
        arguments = [path, "-X", "GET"]
        for key, value in sorted(parameters.items()):
            arguments.extend(("-f", f"{key}={value}"))
        for attempt in range(self.secondary_limit_attempts):
            try:
                return self._run(arguments)
            except DiscoveryError as error:
                message = str(error)
                if (
                    path.startswith("repos/")
                    and path.endswith("/commits")
                    and "Git Repository is empty." in message
                    and "HTTP 409" in message
                ):
                    return []
                is_secondary = "secondary rate limit" in message.casefold()
                if (
                    not path.startswith("search/")
                    or not is_secondary
                    or attempt + 1 == self.secondary_limit_attempts
                ):
                    raise
                self._sleep(self.secondary_limit_backoff_seconds * (attempt + 1))
                self._last_search_at = self._clock()
        raise AssertionError("secondary-limit retry loop exhausted")

    def graphql(self, query: str, variables: Mapping[str, str | int | None]) -> Any:
        arguments = ["graphql", "-f", f"query={query}"]
        for key, value in sorted(variables.items()):
            if value is not None:
                arguments.extend(("-F", f"{key}={value}"))
        return self._run(arguments)


@dataclass(frozen=True, slots=True)
class Provenance:
    """One API page that established repository candidacy."""

    source: str
    page: int
    locator: str

    def __post_init__(self) -> None:
        if self.source not in _SOURCE_ORDER or self.page < 1 or not self.locator:
            raise DiscoveryError("invalid repository discovery provenance")

    def as_dict(self) -> dict[str, str | int]:
        return {"source": self.source, "page": self.page, "locator": self.locator}

    @classmethod
    def from_dict(cls, value: Any) -> Provenance:
        if not isinstance(value, dict) or set(value) != {"source", "page", "locator"}:
            raise DiscoveryError("snapshot provenance fields are invalid")
        if (
            not isinstance(value["source"], str)
            or isinstance(value["page"], bool)
            or not isinstance(value["page"], int)
            or not isinstance(value["locator"], str)
        ):
            raise DiscoveryError("snapshot provenance types are invalid")
        return cls(value["source"], value["page"], value["locator"])


@dataclass(frozen=True, slots=True)
class Repository:
    """Current repository metadata keyed by GitHub's rename/transfer-stable database ID."""

    database_id: int
    node_id: str
    name_with_owner: str
    private: bool
    archived: bool
    url: str
    provenance: tuple[Provenance, ...]

    def __post_init__(self) -> None:
        if (
            isinstance(self.database_id, bool)
            or self.database_id < 1
            or not self.node_id
            or self.name_with_owner.count("/") != 1
            or not self.url.startswith("https://github.com/")
            or not self.provenance
        ):
            raise DiscoveryError("invalid repository snapshot entry")

    def as_dict(self) -> dict[str, Any]:
        return {
            "database_id": self.database_id,
            "node_id": self.node_id,
            "name_with_owner": self.name_with_owner,
            "private": self.private,
            "archived": self.archived,
            "url": self.url,
            "provenance": [item.as_dict() for item in self.provenance],
        }

    @classmethod
    def from_dict(cls, value: Any) -> Repository:
        expected = {
            "database_id",
            "node_id",
            "name_with_owner",
            "private",
            "archived",
            "url",
            "provenance",
        }
        if not isinstance(value, dict) or set(value) != expected:
            raise DiscoveryError("snapshot repository fields are invalid")
        if (
            isinstance(value["database_id"], bool)
            or not isinstance(value["database_id"], int)
            or not all(
                isinstance(value[field], str) for field in ("node_id", "name_with_owner", "url")
            )
            or not isinstance(value["private"], bool)
            or not isinstance(value["archived"], bool)
            or not isinstance(value["provenance"], list)
        ):
            raise DiscoveryError("snapshot repository types are invalid")
        return cls(
            database_id=value["database_id"],
            node_id=value["node_id"],
            name_with_owner=value["name_with_owner"],
            private=value["private"],
            archived=value["archived"],
            url=value["url"],
            provenance=tuple(Provenance.from_dict(item) for item in value["provenance"]),
        )


@dataclass(frozen=True, slots=True)
class RepositorySnapshot:
    """Byte-stable frozen union, including candidates with no in-range activity."""

    identity: str
    start_utc: str
    end_utc: str
    repositories: tuple[Repository, ...]
    policy_version: str = DISCOVERY_POLICY_VERSION
    schema_version: str = SNAPSHOT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.identity or self.identity != self.identity.strip():
            raise DiscoveryError("snapshot identity is invalid")
        if self.policy_version != DISCOVERY_POLICY_VERSION:
            raise DiscoveryError("unsupported discovery policy version")
        if self.schema_version != SNAPSHOT_SCHEMA_VERSION:
            raise DiscoveryError("unsupported repository snapshot schema")
        try:
            if (
                normalize_utc(self.start_utc) != self.start_utc
                or normalize_utc(self.end_utc) != self.end_utc
            ):
                raise DiscoveryError("snapshot UTC bounds are not canonical")
        except PlanValidationError as error:
            raise DiscoveryError("snapshot UTC bounds are invalid") from error
        if datetime.fromisoformat(self.start_utc.replace("Z", "+00:00")) >= datetime.fromisoformat(
            self.end_utc.replace("Z", "+00:00")
        ):
            raise DiscoveryError("snapshot start must be earlier than its end")
        ids = [repository.database_id for repository in self.repositories]
        if ids != sorted(ids) or len(ids) != len(set(ids)):
            raise DiscoveryError("snapshot repositories must be unique and database-ID sorted")

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "policy_version": self.policy_version,
            "identity": self.identity,
            "start_utc": self.start_utc,
            "end_utc": self.end_utc,
            "repositories": [repository.as_dict() for repository in self.repositories],
        }

    @property
    def canonical_json(self) -> str:
        return json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True)

    @property
    def digest(self) -> str:
        return "sha256:" + hashlib.sha256(self.canonical_json.encode()).hexdigest()

    def to_json(self) -> str:
        return (
            json.dumps({**self.as_dict(), "digest": self.digest}, indent=2, sort_keys=True) + "\n"
        )

    @classmethod
    def from_json(cls, document: str) -> RepositorySnapshot:
        try:
            value = json.loads(document)
        except json.JSONDecodeError as error:
            raise DiscoveryError("repository snapshot is not valid JSON") from error
        expected = {
            "schema_version",
            "policy_version",
            "identity",
            "start_utc",
            "end_utc",
            "repositories",
            "digest",
        }
        if not isinstance(value, dict) or set(value) != expected:
            raise DiscoveryError("repository snapshot fields are invalid")
        if not all(
            isinstance(value[field], str) for field in expected - {"repositories"}
        ) or not isinstance(value["repositories"], list):
            raise DiscoveryError("repository snapshot field types are invalid")
        snapshot = cls(
            schema_version=value["schema_version"],
            policy_version=value["policy_version"],
            identity=value["identity"],
            start_utc=value["start_utc"],
            end_utc=value["end_utc"],
            repositories=tuple(Repository.from_dict(item) for item in value["repositories"]),
        )
        if value["digest"] != snapshot.digest:
            raise DiscoveryError("repository snapshot digest does not match its contents")
        return snapshot


@dataclass(frozen=True, slots=True)
class _Sighting:
    repository: Repository
    source_rank: int


class RepositoryDiscoverer:
    """Collect every paginated source and deterministically merge by database ID."""

    def __init__(self, api: GitHubAPI) -> None:
        self._api = api
        self._repository_details: dict[int, dict[str, Any]] = {}
        self._repository_paths: dict[str, dict[str, Any]] = {}

    def discover(self, *, identity: str, start_utc: str, end_utc: str) -> RepositorySnapshot:
        self._repository_details.clear()
        self._repository_paths.clear()
        sightings: list[_Sighting] = []
        self._direct(identity, sightings)
        self._contributed(identity, sightings)
        self._search(
            source="range-commit",
            query=f"author:{identity} author-date:{_search_date_range(start_utc, end_utc)}",
            start_utc=start_utc,
            end_utc=end_utc,
            sightings=sightings,
        )
        self._search(
            source="range-authored",
            query=f"author:{identity} created:{_search_date_range(start_utc, end_utc)}",
            start_utc=start_utc,
            end_utc=end_utc,
            sightings=sightings,
        )
        # Any issue with an in-range comment has updated_at >= the interval start. No
        # upper bound is used: later issue activity must not hide an earlier comment.
        self._search(
            source="required-comment-only",
            query=f"commenter:{identity} updated:>={start_utc}",
            start_utc=start_utc,
            end_utc=end_utc,
            sightings=sightings,
        )
        return RepositorySnapshot(
            identity=identity,
            start_utc=start_utc,
            end_utc=end_utc,
            repositories=self._merge(sightings),
        )

    def _direct(self, identity: str, sightings: list[_Sighting]) -> None:
        page = 1
        while True:
            parameters: dict[str, str | int] = {
                "affiliation": "owner,collaborator,organization_member",
                "visibility": "all",
                "sort": "full_name",
                "direction": "asc",
                "per_page": 100,
                "page": page,
            }
            payload = self._api.rest("user/repos", parameters)
            if not isinstance(payload, list):
                raise DiscoveryError("direct repository page is not an array")
            locator = f"GET /user/repos?affiliation=all-direct&per_page=100&page={page}"
            for item in payload:
                sightings.append(self._rest_sighting(item, "direct-access", page, locator))
            if len(payload) < 100:
                return
            page += 1

    def _contributed(self, identity: str, sightings: list[_Sighting]) -> None:
        page = 1
        cursor: str | None = None
        while True:
            payload = self._api.graphql(
                _CONTRIBUTIONS_QUERY,
                {"login": identity, "after": cursor},
            )
            try:
                connection = payload["data"]["user"]["repositoriesContributedTo"]
                nodes = connection["nodes"]
                page_info = connection["pageInfo"]
            except (KeyError, TypeError) as error:
                raise DiscoveryError(
                    "contributed repository response has an invalid shape"
                ) from error
            if not isinstance(nodes, list) or not isinstance(page_info, dict):
                raise DiscoveryError("contributed repository page has an invalid shape")
            locator = f"GraphQL repositoriesContributedTo(first:100,page:{page})"
            for item in nodes:
                sightings.append(self._graphql_sighting(item, page, locator))
            if not page_info.get("hasNextPage"):
                return
            next_cursor = page_info.get("endCursor")
            if not isinstance(next_cursor, str) or not next_cursor or next_cursor == cursor:
                raise DiscoveryError("contributed repository pagination did not advance")
            cursor = next_cursor
            page += 1

    def _search(
        self,
        *,
        source: str,
        query: str,
        start_utc: str,
        end_utc: str,
        sightings: list[_Sighting],
    ) -> None:
        endpoint = "search/commits" if source == "range-commit" else "search/issues"
        page = 1
        while True:
            payload = self._api.rest(
                endpoint,
                {"q": query, "sort": "updated", "order": "asc", "per_page": 100, "page": page},
            )
            if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
                raise DiscoveryError(f"{source} search page has an invalid shape")
            if payload.get("incomplete_results") is not False:
                if source in _BOUNDED_SEARCH_QUALIFIER:
                    self._split_search(
                        source=source,
                        query=query,
                        start_utc=start_utc,
                        end_utc=end_utc,
                        sightings=sightings,
                        cause="incomplete results",
                    )
                    return
                raise DiscoveryError(f"{source} search did not prove complete results")
            total = payload.get("total_count")
            if isinstance(total, bool) or not isinstance(total, int):
                raise DiscoveryError(
                    f"{source} search exceeds GitHub's provable 1000-result window"
                )
            if total > 1000:
                self._split_search(
                    source=source,
                    query=query,
                    start_utc=start_utc,
                    end_utc=end_utc,
                    sightings=sightings,
                )
                return
            items = cast(list[Any], payload["items"])
            locator = (
                f"GET /{endpoint}?page={page}; bounds={start_utc}..{end_utc}; qualifier={source}"
            )
            for item in items:
                repository = self._search_repository(item)
                sightings.append(self._rest_sighting(repository, source, page, locator))
            if page * 100 >= total:
                return
            if not items:
                raise DiscoveryError(f"{source} pagination stopped before total_count")
            page += 1

    def _split_search(
        self,
        *,
        source: str,
        query: str,
        start_utc: str,
        end_utc: str,
        sightings: list[_Sighting],
        cause: str = "1000-result cap",
    ) -> None:
        """Recursively split a bounded over-cap search into adjacent ranges."""
        qualifier = _BOUNDED_SEARCH_QUALIFIER.get(source)
        if qualifier is None:
            raise DiscoveryError(f"{source} search exceeds GitHub's provable 1000-result window")
        start = datetime.fromisoformat(start_utc.replace("Z", "+00:00"))
        end = datetime.fromisoformat(end_utc.replace("Z", "+00:00"))
        first_date = start.date()
        last_date = (end - timedelta(microseconds=1)).date()
        day_count = (last_date - first_date).days + 1
        if day_count <= 1:
            raise DiscoveryError(f"{source} search {cause} in an indivisible range")
        right_date = first_date + timedelta(days=day_count // 2)
        boundary = datetime.combine(right_date, datetime.min.time(), tzinfo=UTC)
        boundary_utc = boundary.isoformat(timespec="seconds").replace("+00:00", "Z")
        current_range = f"{qualifier}:{_search_date_range(start_utc, end_utc)}"
        if current_range in query:
            base_query = query.replace(current_range, "{bounds}", 1)
        else:
            raise DiscoveryError(f"{source} search query is missing its UTC bounds")
        for sub_start, sub_end in ((start_utc, boundary_utc), (boundary_utc, end_utc)):
            bounded_query = base_query.replace(
                "{bounds}", f"{qualifier}:{_search_date_range(sub_start, sub_end)}", 1
            )
            self._search(
                source=source,
                query=bounded_query,
                start_utc=sub_start,
                end_utc=sub_end,
                sightings=sightings,
            )

    def _search_repository(self, item: Any) -> Any:
        if not isinstance(item, dict):
            return None
        repository = item.get("repository")
        if repository is not None:
            return self._complete_repository(repository)
        repository_url = item.get("repository_url")
        prefix = "https://api.github.com/repos/"
        if not isinstance(repository_url, str) or not repository_url.startswith(prefix):
            return None
        path = "repos/" + repository_url.removeprefix(prefix)
        if path not in self._repository_paths:
            payload = self._api.rest(path, {})
            if not isinstance(payload, dict):
                raise DiscoveryError("issue search repository hydration has an invalid shape")
            self._repository_paths[path] = payload
        return self._repository_paths[path]

    def _complete_repository(self, item: Any) -> Any:
        """Hydrate reduced search-result repositories without changing candidacy."""
        required = {"id", "node_id", "full_name", "private", "archived", "html_url"}
        if not isinstance(item, dict) or "id" not in item:
            return item
        if required <= set(item):
            return item
        database_id = item["id"]
        if isinstance(database_id, bool) or not isinstance(database_id, int):
            return item
        if database_id not in self._repository_details:
            payload = self._api.rest(f"repositories/{database_id}", {})
            if not isinstance(payload, dict):
                raise DiscoveryError("repository metadata hydration has an invalid shape")
            self._repository_details[database_id] = payload
        return self._repository_details[database_id]

    @staticmethod
    def _rest_sighting(item: Any, source: str, page: int, locator: str) -> _Sighting:
        if not isinstance(item, dict):
            raise DiscoveryError(f"{source} repository item is invalid")
        try:
            repository = Repository(
                database_id=item["id"],
                node_id=item["node_id"],
                name_with_owner=item["full_name"],
                private=item["private"],
                archived=item["archived"],
                url=item["html_url"],
                provenance=(Provenance(source, page, locator),),
            )
        except KeyError as error:
            raise DiscoveryError(f"{source} repository metadata is incomplete") from error
        return _Sighting(repository, _SOURCE_ORDER[source])

    @staticmethod
    def _graphql_sighting(item: Any, page: int, locator: str) -> _Sighting:
        if not isinstance(item, dict):
            raise DiscoveryError("contributed repository item is invalid")
        try:
            repository = Repository(
                database_id=item["databaseId"],
                node_id=item["id"],
                name_with_owner=item["nameWithOwner"],
                private=item["isPrivate"],
                archived=item["isArchived"],
                url=item["url"],
                provenance=(Provenance("contributed", page, locator),),
            )
        except KeyError as error:
            raise DiscoveryError("contributed repository metadata is incomplete") from error
        return _Sighting(repository, _SOURCE_ORDER["contributed"])

    @staticmethod
    def _merge(sightings: list[_Sighting]) -> tuple[Repository, ...]:
        grouped: dict[int, list[_Sighting]] = {}
        for sighting in sightings:
            grouped.setdefault(sighting.repository.database_id, []).append(sighting)
        repositories: list[Repository] = []
        for group in grouped.values():
            # A current direct-access response is authoritative for rename/transfer
            # metadata. Otherwise source precedence then lexical fields make selection
            # independent of API return order.
            selected = min(
                group,
                key=lambda item: (
                    item.source_rank,
                    item.repository.name_with_owner.casefold(),
                    item.repository.node_id,
                ),
            ).repository
            provenance = tuple(
                sorted(
                    {entry for item in group for entry in item.repository.provenance},
                    key=lambda entry: (_SOURCE_ORDER[entry.source], entry.page, entry.locator),
                )
            )
            repositories.append(replace(selected, provenance=provenance))
        return tuple(sorted(repositories, key=lambda repository: repository.database_id))


def bind_snapshot(plan: Plan, snapshot: RepositorySnapshot) -> Plan:
    """Return a new immutable plan; the prior approval can never authorize it."""
    if (plan.identity, plan.start_utc, plan.end_utc) != (
        snapshot.identity,
        snapshot.start_utc,
        snapshot.end_utc,
    ):
        raise PlanValidationError("repository snapshot does not match plan identity and UTC bounds")
    return replace(plan, repository_snapshot_digest=snapshot.digest)
