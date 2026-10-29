"""Spelling, stale-post recovery, limit reminders, extra owners."""
import asyncio, os, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from spelling import correct_spelling, phonetic
import db as db_module
from db import DB

TITLES = ["Anupamaa Anupama'S Unexpected Shock Hs Dl Aac2 0", "Kundali Bhagya Episode 2001", "Bigg Boss 19 Day 40"]

class Spelling(unittest.TestCase):
    def test_anupma(self):
        self.assertEqual(correct_spelling("anupma", TITLES), "anupamaa")
    def test_phonetic_same(self):
        self.assertEqual(phonetic("Anupamaa"), phonetic("anupama"))
    def test_kundli(self):
        self.assertEqual(correct_spelling("kundli bhagy", TITLES), "kundali bhagya")
    def test_typo_first_letters(self):
        self.assertEqual(correct_spelling("kundaly bhagya", TITLES), "kundali bhagya")
    def test_correct_spelling_untouched(self):
        self.assertIsNone(correct_spelling("bigg boss", TITLES))

class DbFixes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        db_module.DB_PATH = os.path.join(self.tmp, "t.db")
        self.db = DB(); self.loop = asyncio.new_event_loop()
        self.loop.run_until_complete(self.db.init())
    def run_(self, c): return self.loop.run_until_complete(c)
    def test_reminder_due(self):
        self.run_(self.db.set_limit_reminder(5, 100))
        self.assertEqual(self.run_(self.db.due_limit_reminders(101)), [5])
        self.assertEqual(self.run_(self.db.due_limit_reminders(99)), [])
    def test_extra_owner(self):
        self.run_(self.db.add_extra_owner(42))
        self.assertIn(42, self.run_(self.db.extra_owners()))
        self.run_(self.db.remove_extra_owner(42))
        self.assertNotIn(42, self.run_(self.db.extra_owners()))

if __name__ == "__main__":
    unittest.main()
