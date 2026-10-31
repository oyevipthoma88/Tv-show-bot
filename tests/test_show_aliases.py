"""One serial = one show: shortcuts (TMKOC), spelling variants, latest on top."""
import datetime
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import db as db_module
from db import DB
from episode import show_key
from spelling import alias_fix, correct_spelling, suggest_corrections
import utils
from utils import newest_first, parse_caption, search_movies

TMKOC = "taarak mehta ka ooltah chashmah"


class ShowKeyTests(unittest.TestCase):
    def test_tmkoc_caption_variants_are_one_show(self):
        for cap in ("Taarak Mehta 4570 28.10.2026", "Taarak Mehta Ka Ooltah Chashmah Episode 4571 720p",
                    "TMKOC 29 Oct 2026", "Tarak Mehta Ka Oolta Chasma 4572"):
            self.assertEqual(show_key(cap), TMKOC, cap)

    def test_bigg_boss_variants_are_one_show(self):
        for cap in ("Bigg Boss 19 Grand Finale", "Big Boss 19 | Episode 62 | 29-10-2026", "Bigg Boss 18 Day 5"):
            self.assertEqual(show_key(cap), "bigg boss", cap)

    def test_repeated_name_and_junk_removed(self):
        self.assertEqual(show_key("Anupama Anupama'S Unexpected Shock Hs Dl Aac2 0 H 264 Tvshowhub Mp4"), "anupamaa")

    def test_unknown_show_untouched(self):
        self.assertEqual(show_key("Mirzapur Season 1 Episode 1"), "mirzapur")


class ShortcutSpellingTests(unittest.TestCase):
    def test_shortcuts(self):
        self.assertEqual(alias_fix("tmkoc"), TMKOC)
        self.assertEqual(alias_fix("TMKOC"), TMKOC)
        self.assertEqual(alias_fix("big boss"), "bigg boss")
        self.assertEqual(alias_fix("yrkkh"), "yeh rishta kya kehlata hai")

    def test_misspelt_long_name(self):
        self.assertEqual(alias_fix("tarak mehta ka oolta chsma"), TMKOC)
        self.assertEqual(alias_fix("taarak mehta ka ulta chasma"), TMKOC)

    def test_catalog_spelling_still_works(self):
        self.assertEqual(correct_spelling("kundaly bhagya", ["Kundali Bhagya Episode 2001"]), "kundali bhagya")

    def test_not_found_suggests_related(self):
        titles = ["Bhagya Lakshmi Episode 900", "Kumkum Bhagya 30th October 2026", "Mirzapur S03E05"]
        self.assertTrue(suggest_corrections("bhagya kuch bhi", titles))


class LatestOnTopTests(unittest.TestCase):
    def test_newer_air_date_beats_later_reupload(self):
        now = int(time.time())
        today = datetime.date.today()
        old_ep = {"msg_id": 1, "added_at": now, "air_date": (today - datetime.timedelta(days=3)).isoformat(), "episode": 10}
        new_ep = {"msg_id": 2, "added_at": now - 3600, "air_date": today.isoformat(), "episode": 11}
        self.assertEqual([r["msg_id"] for r in newest_first([old_ep, new_ep])], [2, 1])


class AliasSearchTests(unittest.IsolatedAsyncioTestCase):
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

    async def _add(self, msg_id, caption, added_at):
        meta = parse_caption(caption)
        await self.db.upsert_movie(msg_id, meta["title"], meta["year"], meta["quality"], meta["language"],
                                   "300MB", caption, f"file{msg_id}", "video", "series",
                                   storage_msg_id=msg_id, added_at=added_at)

    async def test_tmkoc_finds_every_variant_newest_first(self):
        base = int(time.time()) - 10 * 86400
        await self._add(1, "Taarak Mehta 4570", base)
        await self._add(2, "Taarak Mehta Ka Ooltah Chashmah Episode 4571 720p", base + 86400)
        await self._add(3, "TMKOC Episode 4572", base + 2 * 86400)
        for q in ("tmkoc", "tarak mehta", "taarak mehta ka oolta chsma"):
            rows = await search_movies(q) or await search_movies(alias_fix(q))
            self.assertEqual([r["msg_id"] for r in rows], [3, 2, 1], q)

    async def test_old_keys_and_follows_merge(self):
        await self._add(1, "Taarak Mehta Episode 1", 100)
        await self.db.conn.execute("UPDATE movies SET show_key='taarak mehta' WHERE msg_id=1")
        await self.db.add_user(7, "u", "U")
        await self.db.follow(7, "taarak mehta", "Taarak Mehta")
        await self.db.follow(7, "tmkoc", "TMKOC")
        await self.db.recanonicalize_show_keys()
        self.assertEqual((await self.db.movie(1))["show_key"], TMKOC)
        self.assertEqual(await self.db.followers(TMKOC), [7])
        self.assertEqual(len(await self.db.follows(7)), 1)


if __name__ == "__main__":
    unittest.main()
