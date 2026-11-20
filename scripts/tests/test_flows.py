import hashlib
import os
import shutil
import tempfile
import unittest
from unittest import mock

from crush80 import flows
from crush80.mcumgr import McumgrError, Slot
from tests.test_image import make_image

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class FakeUi:
    def __init__(self, answer=True):
        self.lines, self.answer, self.asked = [], answer, 0

    def say(self, msg=""): self.lines.append(msg)
    def ask(self, prompt): self.asked += 1; return self.answer
    def pause(self, prompt): pass


class FakeBoard:
    """Stands in for the keyboard behind Mcumgr: slot lists change as the real board's would."""

    def __init__(self, old, new, boots_into):
        self.old, self.new, self.boots_into = old, new, boots_into
        self.slot0 = Slot(0, old, True, True, False)
        self.slot1 = None
        self.confirmed_calls = []
        self.uploads = 0

    def factory(self, port):
        board = self
        class M:
            def __init__(self, port): pass
            def echo(self): pass
            def image_list(self): return [board.slot0] + ([board.slot1] if board.slot1 else [])
            def upload(self, path):
                board.uploads += 1
                board.slot1 = Slot(1, board.new, False, False, False)
            def test(self, digest): board.slot1 = Slot(1, digest, False, False, True)
            def confirm(self, digest=""):
                board.confirmed_calls.append(digest)
                board.slot0 = Slot(0, board.slot0.hash, True, True, False)
        return M(port)

    def power_cycle(self):
        h = self.boots_into
        self.slot0 = Slot(0, h, h == self.old, True, False)


class UpdateFlowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.repo = os.path.join(self.tmp, "repo")
        os.makedirs(os.path.join(self.repo, "releases"))
        # a synthetic known-good image: the tests must not depend on a real release image being in the repo
        golden, golden_hash = make_image(b"golden")
        with open(os.path.join(self.repo, "releases", "Crush80-No-RGB.bin"), "wb") as f:
            f.write(golden)
        with open(os.path.join(self.repo, "releases", "MANIFEST.sha256"), "w") as f:
            f.write(hashlib.sha256(golden).hexdigest() + "  Crush80-No-RGB.bin\n")
        data, self.new_hash = make_image()
        self.image = os.path.join(self.tmp, "new.signed.bin")
        with open(self.image, "wb") as f:
            f.write(data)
        self.old_hash = "ab" * 32

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def run_update(self, board, ui, **kw):
        def wait(timeout, gone_first=False, **_):
            if gone_first:
                board.power_cycle()
            return "/dev/fake"
        with mock.patch.object(flows, "Mcumgr", board.factory), \
             mock.patch.object(flows.device, "wait_for_port", wait), \
             mock.patch.object(flows.time, "sleep", lambda s: None):
            return flows.update(ui, self.repo, self.image, port="/dev/fake", **kw)

    def test_happy_path_confirms_only_after_user_says_yes(self):
        board = FakeBoard(self.old_hash, self.new_hash, boots_into=self.new_hash)
        self.run_update(board, FakeUi(True))
        self.assertEqual(board.confirmed_calls, [self.new_hash])
        self.assertTrue(board.slot0.confirmed)

    def test_user_declines_leaves_trial_unconfirmed(self):
        board = FakeBoard(self.old_hash, self.new_hash, boots_into=self.new_hash)
        self.run_update(board, FakeUi(False))
        self.assertEqual(board.confirmed_calls, [])
        self.assertFalse(board.slot0.confirmed)

    def test_reverted_board_is_reported_and_never_confirmed(self):
        board = FakeBoard(self.old_hash, self.new_hash, boots_into=self.old_hash)
        with self.assertRaisesRegex(flows.FlowError, "OLD image"):
            self.run_update(board, FakeUi(True))
        self.assertEqual(board.confirmed_calls, [])

    def test_refuses_when_running_image_is_unconfirmed(self):
        board = FakeBoard(self.old_hash, self.new_hash, boots_into=self.new_hash)
        board.slot0 = Slot(0, self.old_hash, False, True, False)
        with self.assertRaisesRegex(flows.FlowError, "unconfirmed"):
            self.run_update(board, FakeUi())
        self.assertEqual(board.uploads, 0)

    def test_noop_when_same_image_running(self):
        board = FakeBoard(self.new_hash, self.new_hash, boots_into=self.new_hash)
        self.run_update(board, FakeUi())
        self.assertEqual(board.uploads, 0)

    def test_refuses_without_known_good_image(self):
        os.remove(os.path.join(self.repo, "releases", "MANIFEST.sha256"))
        board = FakeBoard(self.old_hash, self.new_hash, boots_into=self.new_hash)
        with self.assertRaisesRegex(flows.FlowError, "known-good"):
            self.run_update(board, FakeUi())
        self.assertEqual(board.uploads, 0)

    def test_refuses_tampered_known_good_image(self):
        with open(os.path.join(self.repo, "releases", "Crush80-No-RGB.bin"), "ab") as f:
            f.write(b"x")
        board = FakeBoard(self.old_hash, self.new_hash, boots_into=self.new_hash)
        with self.assertRaises(flows.FlowError):
            self.run_update(board, FakeUi())
        self.assertEqual(board.uploads, 0)

    def test_wrong_slot1_hash_after_upload_stops_before_marking_test(self):
        board = FakeBoard(self.old_hash, "cd" * 32, boots_into=self.new_hash)
        with self.assertRaisesRegex(flows.FlowError, "slot 1"):
            self.run_update(board, FakeUi())
        self.assertFalse(board.slot1.pending)

    def test_corrupt_image_never_reaches_the_board(self):
        with open(self.image, "wb") as f:
            f.write(make_image(corrupt=True)[0])
        board = FakeBoard(self.old_hash, self.new_hash, boots_into=self.new_hash)
        with self.assertRaises(Exception):
            self.run_update(board, FakeUi())
        self.assertEqual(board.uploads, 0)


class StockRestoreGuardTest(unittest.TestCase):
    def test_commit_requires_backup(self):
        tmp = tempfile.mkdtemp()
        try:
            with self.assertRaisesRegex(flows.FlowError, "backup"):
                flows.stock_restore(FakeUi(), tmp, "x.bin", "/dev/fake", commit=True)
        finally:
            shutil.rmtree(tmp)

    def test_rejects_non_telink_image(self):
        tmp = tempfile.mkdtemp()
        try:
            path = os.path.join(tmp, "x.bin")
            with open(path, "wb") as f:
                f.write(bytes(0x2000))
            with self.assertRaisesRegex(flows.FlowError, "KNLT"):
                flows.stock_restore(FakeUi(), tmp, path, "/dev/fake", commit=False)
        finally:
            shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main()
