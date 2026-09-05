"""Tests for the facilitator-private durable engine snapshot."""

import os
import multiprocessing
import tempfile
import unittest

from engine.persistence import SnapshotError, SnapshotStore
from facilitator import Facilitator
from harness import new_game


def _unlocked_save_worker(path, result):
    """Attempt a save from a separate facilitator without its own lock."""
    try:
        SnapshotStore(path).save(new_game())
    except SnapshotError:
        result.put("rejected")
    else:
        result.put("saved")


def _locked_save_worker(path, acquired):
    """Save only after obtaining this worker's own exclusive lock."""
    store = SnapshotStore(path)
    with store.locked():
        acquired.set()
        store.save(new_game())


class PersistenceTests(unittest.TestCase):
    def test_round_trip_preserves_private_engine_and_public_checkin(self):
        game = new_game()
        game.submit_export("p2", "a wind-powered canning line")
        expected = game.checkin("p1")
        with tempfile.TemporaryDirectory() as directory:
            store = SnapshotStore(os.path.join(directory, "game.snapshot"))
            with store.locked():
                store.save(game)
            with store.locked():
                restored = store.load()
        self.assertEqual(restored.current_round, game.current_round)
        self.assertEqual(restored.checkin("p1"), expected)
        # The ledger is deliberately private but must survive a facilitator
        # restart so cap enforcement/blind voting cannot be bypassed.
        self.assertEqual(restored.ledger.all_submission_ids(), game.ledger.all_submission_ids())

    def test_save_and_load_require_a_single_writer_lock(self):
        game = new_game()
        with tempfile.TemporaryDirectory() as directory:
            store = SnapshotStore(os.path.join(directory, "game.snapshot"))
            with self.assertRaises(SnapshotError):
                store.save(game)
            with self.assertRaises(SnapshotError):
                store.load()

    def test_loaded_snapshot_does_not_retain_a_prior_session_facilitator_hook(self):
        """Each owning process attaches one fresh publication transaction."""
        game = new_game()
        with tempfile.TemporaryDirectory() as directory:
            Facilitator.attach(game, root=directory, publish=False)
            self.assertEqual(len(game._round_completed_hooks), 1)
            store = SnapshotStore(os.path.join(directory, "game.snapshot"))
            with store.locked():
                store.save(game)
            with store.locked():
                restored = store.load()
        self.assertEqual(restored._round_completed_hooks, [])

    def test_old_snapshot_without_checkin_asks_remains_usable(self):
        """Pre-check-in-ask snapshots resume with an empty per-round cache."""
        game = new_game()
        old_state = game.__getstate__()
        old_state.pop("_checkin_asks")
        restored = game.__class__.__new__(game.__class__)
        restored.__setstate__(old_state)

        self.assertEqual(restored._checkin_asks, {})
        self.assertEqual(restored.checkin("p1"), game.checkin("p1"))

    def test_second_process_must_own_lock_and_locked_writer_waits(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "game.snapshot")
            store = SnapshotStore(path)
            # Spawn avoids inheriting the holder's lock file descriptor, making
            # these genuinely independent facilitator processes.
            context = multiprocessing.get_context("spawn")
            result = context.Queue()
            acquired = context.Event()
            with store.locked():
                unlocked = context.Process(
                    target=_unlocked_save_worker, args=(path, result)
                )
                unlocked.start()
                unlocked.join(5)
                self.assertFalse(unlocked.is_alive())
                self.assertEqual(unlocked.exitcode, 0)
                self.assertEqual(result.get(timeout=1), "rejected")

                locked = context.Process(
                    target=_locked_save_worker, args=(path, acquired)
                )
                locked.start()
                self.assertFalse(acquired.wait(0.2))
            self.assertTrue(acquired.wait(5))
            locked.join(5)
            self.assertFalse(locked.is_alive())
            self.assertEqual(locked.exitcode, 0)


if __name__ == "__main__":
    unittest.main()
