"""Rules from the Oct-2026 fix round: no link delivery, compressed Mongo, scan cursor, dedup."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
SRC = os.path.join(os.path.dirname(__file__), "..", "src")


class Fixes(unittest.TestCase):
    def test_users_never_get_a_channel_link(self):
        text = open(os.path.join(SRC, "user_handlers.py"), encoding="utf-8").read()
        self.assertNotIn("movie_link_kb(", text)
        self.assertNotIn("link-fallback", text)

    def test_scan_never_passes_none_max_id(self):
        text = open(os.path.join(SRC, "indexer.py"), encoding="utf-8").read()
        self.assertNotIn("max_id=cursor_max or None", text)

    def test_mongo_chunks_are_compressed_and_roundtrip(self):
        import mongo_store
        rows = [{"msg_id": i, "caption": "Anupamaa episode " * 20} for i in range(500)]
        packed = mongo_store._pack_rows(rows)
        self.assertLess(len(packed), len(str(rows)) // 5)
        self.assertEqual(mongo_store._unpack_chunk({"z": packed}), rows)
        self.assertEqual(mongo_store._unpack_chunk({"rows": rows[:2]}), rows[:2])

    def test_quota_error_detected(self):
        import mongo_store
        self.assertTrue(mongo_store._is_quota_error(Exception("you are over your space quota, using 512 MB")))
        self.assertFalse(mongo_store._is_quota_error(Exception("timeout")))

    def test_same_post_from_two_accounts_processed_once(self):
        import userbot
        self.assertTrue(userbot._seen_once("-1001:55"))
        self.assertFalse(userbot._seen_once("-1001:55"))


if __name__ == "__main__":
    unittest.main()
