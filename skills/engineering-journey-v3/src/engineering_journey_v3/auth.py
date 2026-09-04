"""GitHub identity detection and browser/device authentication boundary."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Protocol


class AuthenticationError(RuntimeError):
    """Raised when GitHub identity detection or switching cannot complete safely."""


@dataclass(frozen=True, slots=True)
class GitHubIdentity:
    """One runtime GitHub account, as reported by GitHub itself."""

    login: str

    def __post_init__(self) -> None:
        if (
            not self.login
            or self.login != self.login.strip()
            or any(character.isspace() for character in self.login)
        ):
            raise AuthenticationError("GitHub returned an invalid login")


class AuthBoundary(Protocol):
    """Injectable boundary used by consent workflow tests and real GitHub CLI auth."""

    def detect_identity(self) -> GitHubIdentity | None:
        """Return the active GitHub identity, if a usable session exists."""
        ...

    def authenticate_different(self) -> GitHubIdentity:
        """Run an interactive supported browser/device flow and return its identity."""
        ...


@dataclass(slots=True)
class GitHubCLIAuth:
    """Authentication through GitHub's maintained ``gh`` browser/device flow."""

    executable: str = "gh"

    def _run(self, arguments: list[str]) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                [self.executable, *arguments],
                check=False,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError as error:
            raise AuthenticationError(
                "GitHub CLI (gh) is required for identity detection and browser/device auth"
            ) from error

    def detect_identity(self) -> GitHubIdentity | None:
        result = self._run(["api", "user", "--jq", ".login"])
        if result.returncode != 0:
            return None
        login = result.stdout.strip()
        return GitHubIdentity(login) if login else None

    def authenticate_different(self) -> GitHubIdentity:
        # Inherit the terminal so the browser/device URL, one-time code, and prompts
        # remain visible and usable. Credentials are owned by gh, never this process.
        try:
            result = subprocess.run(
                [self.executable, "auth", "login", "--web", "--git-protocol", "https"],
                check=False,
            )
        except FileNotFoundError as error:
            raise AuthenticationError(
                "GitHub CLI (gh) is required for identity detection and browser/device auth"
            ) from error
        if result.returncode != 0:
            raise AuthenticationError("GitHub browser/device authentication failed")
        identity = self.detect_identity()
        if identity is None:
            raise AuthenticationError("authentication completed but no GitHub login was detected")
        return identity
