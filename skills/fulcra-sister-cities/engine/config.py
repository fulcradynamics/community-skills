"""config.json access.

The spec's Generation Rules say every configurable parameter lives in a single
``config.json`` and that "roles read it; nothing re-derives config values
independently". This module is how the engine obeys that, in two ways:

1. There is only ``require()``. No ``get(key, default)``. If a key is absent the
   engine raises :class:`MissingConfigKey` instead of quietly using a literal,
   so a parameter can never drift out of config.json without breaking loudly.
2. Every read is recorded in :attr:`Config.reads`. A test can therefore assert
   *that the engine actually consulted config* for a given parameter, which is
   the half of "no role hardcodes a config value" that behavioural tests alone
   cannot show.
"""

import json
import os

from .errors import ConfigError, ConfigTypeError, MissingConfigKey

_UNSET = object()

DEFAULT_CONFIG_FILENAME = "config.json"


def repo_root():
    """The deliverable repo root (this file lives in ``<root>/engine/``)."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Config:
    """Read-only view over config.json with read-tracking."""

    def __init__(self, data, source="<memory>"):
        if not isinstance(data, dict):
            raise ConfigError("config root must be a JSON object, got %r" % type(data))
        self._data = data
        self.source = source
        self.reads = []

    # -- construction -----------------------------------------------------

    @classmethod
    def load(cls, path=None):
        if path is None:
            path = os.path.join(repo_root(), DEFAULT_CONFIG_FILENAME)
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except FileNotFoundError:
            raise ConfigError("config.json not found at %s" % path)
        except ValueError as exc:
            raise ConfigError("config.json at %s is not valid JSON: %s" % (path, exc))
        return cls(data, source=path)

    def overridden(self, **dotted_values):
        """A copy of this config with some keys replaced.

        Used by tests to prove the engine's behaviour *follows* config.json
        rather than merely reading it once and ignoring the value.
        """
        data = json.loads(json.dumps(self._data))
        for dotted, value in dotted_values.items():
            path = dotted.replace("__", ".").split(".")
            node = data
            for part in path[:-1]:
                node = node.setdefault(part, {})
            node[path[-1]] = value
        return Config(data, source="%s (overridden: %s)" % (self.source, ", ".join(sorted(dotted_values))))

    # -- access -----------------------------------------------------------

    def _lookup(self, dotted):
        node = self._data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return _UNSET
            node = node[part]
        return node

    def has(self, dotted):
        return self._lookup(dotted) is not _UNSET

    def require(self, dotted):
        value = self._lookup(dotted)
        if value is _UNSET:
            raise MissingConfigKey(dotted, self.source)
        self.reads.append(dotted)
        return value

    def require_bool(self, dotted):
        value = self.require(dotted)
        if not isinstance(value, bool):
            raise ConfigTypeError("config %s must be a boolean, got %r" % (dotted, value))
        return value

    def require_int(self, dotted):
        value = self.require(dotted)
        if isinstance(value, bool) or not isinstance(value, int):
            raise ConfigTypeError("config %s must be an integer, got %r" % (dotted, value))
        return value

    def require_number(self, dotted):
        value = self.require(dotted)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ConfigTypeError("config %s must be a number, got %r" % (dotted, value))
        return value

    def require_str(self, dotted):
        value = self.require(dotted)
        if not isinstance(value, str):
            raise ConfigTypeError("config %s must be a string, got %r" % (dotted, value))
        return value

    def require_nullable_int(self, dotted):
        value = self.require(dotted)
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int):
            raise ConfigTypeError("config %s must be an integer or null, got %r" % (dotted, value))
        return value

    def keys_read(self):
        """Distinct dotted paths read so far, in first-read order."""
        seen = []
        for key in self.reads:
            if key not in seen:
                seen.append(key)
        return seen
