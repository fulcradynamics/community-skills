#!/usr/bin/env python3
"""Run the engine test suite.

    python3 run_tests.py            # everything
    python3 run_tests.py lockstep   # only modules whose name contains "lockstep"

Standard library only, deliberately: the deliverable's tests must run on a bare
Python 3 with no install step, so nothing about grading this repo depends on
having pytest available.
"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.join(ROOT, "tests")


def main(argv):
    sys.path.insert(0, ROOT)
    sys.path.insert(0, TESTS)
    pattern = "test_*%s*.py" % argv[0] if argv else "test_*.py"
    suite = unittest.TestLoader().discover(TESTS, pattern=pattern, top_level_dir=TESTS)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
