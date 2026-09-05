"""Private, atomic persistence for a facilitator-owned Sister Cities engine.

The engine is intentionally transport-neutral.  This adapter makes its durable
boundary explicit: exactly one facilitator process owns a local snapshot and
serializes every mutation under an advisory lock.  Workspace records are views,
not a replacement for this private snapshot (which contains identity routing and
the exporter ledger).
"""

import fcntl
import os
import pickle
import tempfile
from contextlib import contextmanager


class SnapshotError(RuntimeError):
    """A snapshot is missing, corrupt, or belongs to a different engine type."""


class SnapshotStore:
    """Atomically save/load one private game snapshot with a single-writer lock.

    Callers must use :meth:`locked` around a read/mutate/save transaction.  The
    lock is intentionally separate from the snapshot file so ``os.replace``
    cannot invalidate it for a second facilitator process.
    """

    def __init__(self, path):
        self.path = os.path.abspath(path)
        self.lock_path = self.path + ".lock"
        self._lock_file = None

    @contextmanager
    def locked(self):
        if self._lock_file is not None:
            raise SnapshotError("SnapshotStore lock is not reentrant")
        directory = os.path.dirname(self.path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(self.lock_path, "a+b") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            self._lock_file = lock_file
            try:
                yield self
            finally:
                self._lock_file = None
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def save(self, game):
        """Write ``game`` atomically; caller must hold :meth:`locked`."""
        self._require_lock()
        directory = os.path.dirname(self.path) or "."
        fd, temporary = tempfile.mkstemp(prefix=".sister-cities-", dir=directory)
        try:
            with os.fdopen(fd, "wb") as stream:
                pickle.dump(game, stream, protocol=pickle.HIGHEST_PROTOCOL)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            self._fsync_directory(directory)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def load(self):
        """Load a snapshot; caller must hold :meth:`locked`."""
        self._require_lock()
        try:
            with open(self.path, "rb") as stream:
                game = pickle.load(stream)
        except FileNotFoundError:
            raise SnapshotError("no game snapshot at %s" % self.path)
        except (EOFError, OSError, pickle.UnpicklingError) as exc:
            raise SnapshotError("cannot read game snapshot at %s: %s" % (self.path, exc))
        # Avoid importing GameEngine at module load time (engine imports remain
        # usable both as a package and through the bare test runner path).
        if game.__class__.__name__ != "GameEngine":
            raise SnapshotError("snapshot does not contain a GameEngine")
        return game

    def _require_lock(self):
        # The lock must belong to this store instance.  Merely observing that
        # another process holds the advisory lock does not make an unlocked
        # caller safe to read or replace the snapshot.
        if self._lock_file is None:
            raise SnapshotError("save/load requires 'with store.locked()'")

    @staticmethod
    def _fsync_directory(directory):
        descriptor = os.open(directory, os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
