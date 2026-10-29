import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from utils import newest_first


class LatestFirstTest(unittest.TestCase):
    def test_newest_upload_on_top(self):
        rows = [{"msg_id": 1, "added_at": 100}, {"msg_id": 2, "added_at": 300}, {"msg_id": 3, "added_at": 200}]
        self.assertEqual([r["msg_id"] for r in newest_first(rows)], [2, 3, 1])


if __name__ == "__main__":
    unittest.main()
