"""Source channel owned by someone else, only the owner's user ID is a member.

The scan must open it through the user account, forward every new media post
into MAIN_DATA via that account, and index it (not count it as an error).
"""
import asyncio
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import config  # noqa: E402
import indexer  # noqa: E402
import mtproto_importer  # noqa: E402
import userbot  # noqa: E402


class FakeDB:
    def __init__(self):
        self.kv = {}
        self.rows = []

    async def get_dedup_sets(self):
        return set(), set()

    async def get(self, key, default=""):
        return self.kv.get(key, default)

    async def set(self, key, value):
        self.kv[key] = value

    async def commit(self):
        pass

    async def bulk_upsert_movies(self, rows):
        self.rows.extend(rows)
        return len(rows)

    async def upsert_movie(self, msg_id, *args, **kwargs):
        self.rows.append(msg_id)
        return True


def make_msg(mid):
    doc = types.SimpleNamespace(id=1000 + mid, access_hash=7, mime_type="video/mp4", size=10 * 1048576,
                                attributes=[types.SimpleNamespace(file_name=f"Show S01E{mid:02d}.mkv", duration=60)])
    return types.SimpleNamespace(id=mid, media=object(), document=doc, message=f"Show S01E{mid:02d} 720p")


class FakeClient:
    def __init__(self, msgs, fail_first_entity=False):
        self.msgs = msgs
        self.fail_first_entity = fail_first_entity
        self.dialogs_loaded = False

    def is_connected(self):
        return True

    async def get_entity(self, peer):
        if self.fail_first_entity and not self.dialogs_loaded:
            raise ValueError("Could not find the input entity for PeerChannel")
        return types.SimpleNamespace(id=peer)

    async def get_dialogs(self, limit=None):
        self.dialogs_loaded = True
        return []

    async def iter_messages(self, entity, **kwargs):
        for m in self.msgs:
            yield m


class NotMemberBot:
    def __init__(self):
        self.copied = 0

    async def me(self):
        return types.SimpleNamespace(id=1)

    async def get_chat_member(self, chat_id, user_id):
        raise Exception("Telegram server says - Bad Request: chat not found")

    async def get_chat(self, chat_id):
        raise Exception("Telegram server says - Bad Request: chat not found")

    async def copy_message(self, *a, **k):
        self.copied += 1
        raise Exception("Bad Request: chat not found")

    async def delete_message(self, *a, **k):
        pass


class UserOnlySourceScan(unittest.TestCase):
    def setUp(self):
        self._saved = (config.TG_API_ID, config.TG_API_HASH, config.TG_SESSION)
        config.TG_API_ID, config.TG_API_HASH, config.TG_SESSION = 1, "hash", "session"
        self.db = FakeDB()
        self._orig = (indexer.db, indexer.request_snapshot, mtproto_importer._get_client, userbot._send_to_main)
        indexer.db = self.db

        async def no_snapshot(*a, **k):
            return None
        indexer.request_snapshot = no_snapshot
        self.forwarded = []

        async def send_to_main(client, message):
            self.forwarded.append(message.id)
            return types.SimpleNamespace(id=5000 + message.id)
        userbot._send_to_main = send_to_main
        mtproto_importer._dialogs_loaded.clear()

    def tearDown(self):
        config.TG_API_ID, config.TG_API_HASH, config.TG_SESSION = self._saved
        indexer.db, indexer.request_snapshot, mtproto_importer._get_client, userbot._send_to_main = self._orig

    def _run(self, client, bot):
        async def get_client():
            return client
        mtproto_importer._get_client = get_client
        return asyncio.run(indexer.scan_channel_fast(bot, -1002706080247, -1009999999999))

    def test_user_only_posts_are_forwarded_and_indexed(self):
        client = FakeClient([make_msg(i) for i in (3, 2, 1)])
        bot = NotMemberBot()
        stats = self._run(client, bot)
        self.assertEqual(stats.stop_reason, "")
        self.assertEqual(sorted(self.forwarded), [1, 2, 3])
        self.assertEqual(stats.found, 3)
        self.assertEqual(stats.errors, 0)
        self.assertEqual(bot.copied, 0)

    def test_private_channel_resolves_after_loading_dialogs(self):
        client = FakeClient([make_msg(1)], fail_first_entity=True)
        stats = self._run(client, NotMemberBot())
        self.assertTrue(client.dialogs_loaded)
        self.assertEqual(stats.found, 1)
        self.assertEqual(stats.stop_reason, "")


if __name__ == "__main__":
    unittest.main()
