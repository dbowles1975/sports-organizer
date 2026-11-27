import io
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import Mock, patch

from nfl_metadata import Plex, SeasonGameDetails, chiefs_game_details, poster_for
from organizer import Config, Organizer, nfl_preview
from test_organizer import game


class MetadataTests(unittest.TestCase):
    def test_wikipedia_details_match_date_and_ignore_scores(self):
        parser = SeasonGameDetails()
        parser.feed("""<h4>Week 10: at Atlanta Falcons</h4><table><tr><td>35–13</td></tr></table>
            <ul><li><b>Date</b>: November 15</li><li>Game time: 1:00 p.m. EST</li>
            <li>Game attendance: 72,045</li><li>Referee: Alan Eck</li>
            <li>TV announcers (CBS): Jim Nantz</li><li>Winner: Chiefs</li></ul>
            <h4>Week 11: vs. Arizona Cardinals</h4><ul><li>Date: November 22</li></ul>""")
        with patch("nfl_metadata.chiefs_season_details", return_value=parser.sections):
            self.assertEqual(chiefs_game_details(2026, "2026-11-22", "Falcons"), {})
            details = chiefs_game_details(2026, "2026-11-15", "Falcons")
        row = {"gameday": "2026-11-15", "stadium": "Mercedes-Benz Stadium", "roof": "closed"}
        summary = nfl_preview(row, "KC", "ATL", details)
        self.assertIn("Game attendance: 72,045", summary)
        self.assertIn("TV announcers (CBS): Jim Nantz", summary)
        self.assertIn("Game conditions: Roof closed", summary)
        self.assertNotIn("35–13", summary)
        self.assertNotIn("Winner", summary)

    def test_preview_uses_game_conditions_without_result_fields(self):
        row = {"gameday": "2026-11-15", "stadium": "Mercedes-Benz Stadium", "roof": "closed",
               "temp": "62", "wind": "8", "away_score": "35", "home_score": "13", "result": "22"}
        self.assertEqual(nfl_preview(row, "KC", "ATL"),
                         "Chiefs at Falcons on 2026-11-15 at Mercedes-Benz Stadium. Roof closed. Source: nflverse.")
        row.update(roof="outdoors", location="Neutral")
        self.assertEqual(nfl_preview(row, "KC", "ATL"),
                         "Chiefs vs. Falcons on 2026-11-15 at Mercedes-Benz Stadium. "
                         "Outdoor venue, 62 °F, wind 8 mph. Source: nflverse.")

    def test_artwork_rejects_nonimages_and_keeps_existing_poster(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            with patch("nfl_metadata.urllib.request.urlopen", return_value=io.BytesIO(b"<html>")):
                with self.assertRaisesRegex(ValueError, "JPEG or PNG"):
                    poster_for(folder, "http://game-thumbs", "Jets", "Chiefs")
            self.assertEqual(list(folder.iterdir()), [])
            jpeg = b"\xff\xd8\xfftest\xff\xd9"
            with patch("nfl_metadata.urllib.request.urlopen", return_value=io.BytesIO(jpeg)) as request:
                poster = poster_for(folder, "http://game-thumbs", "Jets", "Chiefs")
                self.assertEqual(request.call_args.args[0].full_url,
                                 "http://game-thumbs/nfl/Jets/Chiefs/cover?style=99")
            self.assertEqual(poster.read_bytes(), jpeg)
            with patch("nfl_metadata.urllib.request.urlopen") as request:
                self.assertEqual(poster_for(folder, "http://game-thumbs", "Jets", "Chiefs"), poster)
                request.assert_not_called()

    def test_plex_matches_exact_path_and_preserves_locked_fields(self):
        plex = Plex("http://plex:32400", "secret", "9")
        plex.request = Mock(side_effect=[
            b'<MediaContainer totalSize="2"><Video ratingKey="1"><Media><Part file="/wrong/game.mkv"/></Media></Video></MediaContainer>',
            b'<MediaContainer totalSize="2"><Video ratingKey="2"><Media><Part file="/nfl/game.mkv"/></Media></Video></MediaContainer>',
            b'<MediaContainer><Video><Field name="title" locked="1"/><Collection tag="Favorites"/></Video></MediaContainer>',
            b"",
        ])
        plex.update_game("/nfl/game.mkv", "2026 - Week 10 - Chiefs at Falcons", "2026-11-15", None,
                         summary="Game recap", collections=["Falcons", "Patrick Mahomes", "favorites"])
        args, kwargs = plex.request.call_args
        self.assertEqual(args[0], "/library/sections/9/all")
        self.assertEqual(args[1]["id"], "2")
        self.assertEqual(args[1]["titleSort.value"], "2026 - Week 10 - Chiefs at Falcons")
        self.assertEqual(args[1]["editionTitle.value"], "Week 10 - Chiefs at Falcons")
        self.assertEqual(args[1]["summary.value"], "Game recap")
        self.assertEqual([args[1][f"collection[{i}].tag.tag"] for i in range(3)],
                         ["Favorites", "Falcons", "Patrick Mahomes"])
        self.assertNotIn("collection[3].tag.tag", args[1])
        self.assertNotIn("title.value", args[1])
        self.assertEqual(kwargs["method"], "PUT")

    def test_retry_enriches_completed_video_without_moving_again(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            incoming = root / "incoming"
            output = root / "output"
            incoming.mkdir()
            output.mkdir()
            config = Config(root / "data", {"nfl": (incoming, output)}, "x" * 24,
                            dry_run=False, game_thumbs_url="http://game-thumbs")
            with closing(Organizer(config)) as service:
                service.schedule_rows = Mock(return_value=[game()])
                source = incoming / "nfl.2026.11.08.new.york.jets.vs.kansas.city.chiefs.mkv"
                source.write_bytes(b"video")
                job_id = service.enqueue("nfl", source.name)["id"]
                with patch("organizer.poster_for", side_effect=ValueError("unavailable")):
                    service.run_once()
                job = service.get_job(job_id)
                self.assertEqual(job["status"], "completed")
                self.assertEqual(job["metadata"], "pending")
                self.assertEqual(job["metadata_attempts"], 1)
                destination = Path(job["destination"])
                self.assertFalse(source.exists())
                self.assertEqual(destination.read_bytes(), b"video")
                service.update(job_id, metadata="failed")
                service.retry_metadata(job_id)
                with patch("organizer.poster_for") as poster:
                    service.run_once()
                    poster.assert_called_once_with(destination.parent, "http://game-thumbs", "Jets", "Chiefs")
                self.assertEqual(service.get_job(job_id)["metadata"], "completed")
                self.assertEqual(destination.read_bytes(), b"video")


if __name__ == "__main__":
    unittest.main()
