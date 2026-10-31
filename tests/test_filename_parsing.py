import sys, os, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from episode import parse_episode, show_key


class FileNameParsing(unittest.TestCase):
    def test_underscore_season_episode(self):
        n = "Indian_Game_Show_Season_2_Episode_24_The_Slippery_Water_Challenge.mp4.1080p-AapkaFreeTv"
        p = parse_episode(n)
        self.assertEqual((p["season"], p["episode"]), (2, 24))
        self.assertEqual(show_key(n), "indian game show")

    def test_underscore_sxe(self):
        n = "Udne_Ki_Aasha_S02E917_Pankhuri_Refuses_to_Leave_1080p_JH_WEB_DL.mp4"
        p = parse_episode(n)
        self.assertEqual((p["season"], p["episode"]), (2, 917))
        self.assertEqual(show_key(n), "udne ki aasha")

    def test_dotted_sxe_same_show_as_underscore(self):
        n = "Indian.Game.Show.S02E17.Neena.And.Arjun.Join.The.Fun.1080p.SLIV.WEB-DL.Hindi.AAC2.0.H.264-VRP.mp4"
        p = parse_episode(n)
        self.assertEqual((p["season"], p["episode"]), (2, 17))
        self.assertEqual(show_key(n), "indian game show")

    def test_dotted_season_word(self):
        n = "Mannat.-.Har.Khushi.Paane.Ki.Season.1.Episode.551.Dua.Is.Heartbroken.1080p.HS.Web.Dl.AV.264.AV.mp4"
        p = parse_episode(n)
        self.assertEqual((p["season"], p["episode"]), (1, 551))
        self.assertEqual(show_key(n), "mannat har khushi paane ki")

    def test_dotted_date_still_parsed(self):
        p = parse_episode("Taarak Mehta 4570 28.10.2026")
        self.assertEqual((p["episode"], p["air_date"]), (4570, "2026-10-28"))


if __name__ == "__main__":
    unittest.main()
