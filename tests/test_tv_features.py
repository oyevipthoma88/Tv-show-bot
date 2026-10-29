"""TV show rules: episode detection, latest-first, follow alerts, duplicate guard."""
import datetime
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import db as db_module
from db import DB
from episode import parse_episode, show_key
import keyboards
from keyboards import browse_kb, episode_button_label, main_menu, owner_panel_kb
import utils
from utils import parse_caption, search_movies

TODAY = datetime.date(2026, 10, 29)


class EpisodeParsingTests(unittest.TestCase):
    def test_daily_soap_caption(self):
        info = parse_episode("Anupamaa 28th October 2026 Full Episode 1234 720p", TODAY)
        self.assertEqual((info["season"], info["episode"], info["air_date"]), (0, 1234, "2026-10-28"))

    def test_season_episode_caption(self):
        info = parse_episode("Mirzapur S03E05 1080p WEB-DL", TODAY)
        self.assertEqual((info["season"], info["episode"]), (3, 5))

    def test_bare_number_with_date_is_episode(self):
        info = parse_episode("Taarak Mehta 4570 28.10.2026", TODAY)
        self.assertEqual((info["episode"], info["air_date"]), (4570, "2026-10-28"))

    def test_show_name_stays_clean(self):
        meta = parse_caption("Anupamaa 28th October 2026 Full Episode 1234 720p @tvchannel")
        self.assertEqual(meta["title"], "Anupamaa")
        self.assertEqual(meta["episode"], 1234)
        self.assertEqual(show_key("Mirzapur Season 1 Episode 1"), "mirzapur")


class TvCatalogTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        db_module.DB_PATH = os.path.join(self.tempdir.name, "bot.db")
        self.db = DB()
        await self.db.init()
        self._orig = utils.db
        utils.db = self.db

    async def asyncTearDown(self):
        utils.db = self._orig
        await self.db.close()
        self.tempdir.cleanup()

    async def _add(self, msg_id, caption, added_at, size="300MB", content_type="series"):
        meta = parse_caption(caption)
        return await self.db.upsert_movie(msg_id, meta["title"], meta["year"], meta["quality"], meta["language"],
                                          size, caption, f"file{msg_id}", "video", content_type,
                                          storage_msg_id=msg_id, added_at=added_at)

    async def test_latest_episode_on_top_and_specific_episode_search(self):
        await self._add(1, "Anupamaa Episode 1232 720p", 1000)
        await self._add(2, "Anupamaa Episode 1234 720p", 3000)
        await self._add(3, "Anupamaa Episode 1233 720p", 2000)
        rows = await search_movies("anupama")
        self.assertEqual([r["msg_id"] for r in rows], [2, 3, 1])
        only = await search_movies("Anupamaa episode 1233")
        self.assertEqual([r["msg_id"] for r in only], [3])

    async def test_plain_search_finds_series_rows(self):
        # DM search uses content_type "" — TV episodes classified as series must show up.
        await self._add(5, "Mirzapur S03E05 1080p", 100, content_type="series")
        rows = await search_movies("mirzapur", content_type="")
        self.assertEqual([r["msg_id"] for r in rows], [5])

    async def test_latest_uploads_newest_first(self):
        await self._add(10, "Show A Episode 1", 100)
        await self._add(11, "Show B Episode 1", 300)
        await self._add(12, "Show C Episode 1", 200)
        self.assertEqual([r["msg_id"] for r in await self.db.latest_uploads(0, 10)], [11, 12, 10])

    async def test_follow_unfollow_and_banned_followers_skipped(self):
        await self._add(20, "Anupamaa Episode 1 720p", 100)
        key = (await self.db.movie(20))["show_key"]
        self.assertEqual(key, "anupamaa")
        await self.db.add_user(1, "a", "A")
        await self.db.add_user(2, "b", "B")
        self.assertTrue(await self.db.follow(1, key, "Anupamaa"))
        self.assertFalse(await self.db.follow(1, key, "Anupamaa"))
        await self.db.follow(2, key, "Anupamaa")
        await self.db.ban_user(2)
        self.assertEqual(await self.db.followers(key), [1])
        self.assertTrue(await self.db.unfollow(1, key))
        self.assertEqual(await self.db.followers(key), [])

    async def test_alert_claimed_only_once(self):
        self.assertTrue(await self.db.mark_alert_sent(99))
        self.assertFalse(await self.db.mark_alert_sent(99))

    async def test_generic_caption_is_not_a_duplicate(self):
        await self._add(30, "Join @tvchannel", 100, size="300MB")
        self.assertFalse(await self.db.has_duplicate_upload("new-file", "Join @tvchannel", "310MB"))
        self.assertTrue(await self.db.has_duplicate_upload("new-file", "Join  @tvchannel", "300MB"))
        self.assertTrue(await self.db.has_duplicate_upload("file30", "", ""))

    async def test_browse_keyboard_accepts_sqlite_rows(self):
        await self._add(40, "Anupamaa Episode 1234 720p", 1761700000)
        rows = await self.db.latest_uploads(0, 10)
        kb = browse_kb(rows, page=0, callback_prefix="trending")
        label = kb.inline_keyboard[0][0].text
        self.assertTrue(label.startswith("📅 "))
        self.assertIn("E1234", label)
        self.assertLessEqual(len(episode_button_label(rows[0])), 64)

    async def test_follows_are_backed_up(self):
        import mongo_store
        self.assertIn("follows", mongo_store.PERSISTED_TABLES)
        await self.db.follow(7, "anupamaa", "Anupamaa")
        state = await self.db.export_state()
        self.assertEqual(len(state["tables"]["follows"]), 1)


class MenuTests(unittest.TestCase):
    def test_user_menu_has_tv_buttons(self):
        data = [b.callback_data for row in main_menu(False).inline_keyboard for b in row]
        for needed in ("get_show", "latest:0", "myshows", "trending"):
            self.assertIn(needed, data)

    def test_owner_panel_login_on_top(self):
        first_row = [b.callback_data for b in owner_panel_kb().inline_keyboard[0]]
        self.assertEqual(first_row, ["op:login", "op:live"])


if __name__ == "__main__":
    unittest.main()
