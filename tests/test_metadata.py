import io
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import Mock, patch

from nfl_metadata import Plex, poster_for
from organizer import Config, Organizer
from test_organizer import game


class MetadataTests(unittest.TestCase):
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
            b'<MediaContainer><Video><Field name="title" locked="1"/></Video></MediaContainer>',
            b"",
        ])
        plex.update_game("/nfl/game.mkv", "Chiefs Game", "2026-11-08", None)
        args, kwargs = plex.request.call_args
        self.assertEqual(args[0], "/library/sections/9/all")
        self.assertEqual(args[1]["id"], "2")
        self.assertEqual(args[1]["titleSort.value"], "Chiefs Game")
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
