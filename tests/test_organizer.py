import json
import io
import errno
import os
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from organizer import Config, Organizer, handler_for, nfl_title, ufc_title, ufc_number, ufc_part, verified_copy_move, rename_no_replace


def game(day="2026-11-08", season="2026", kind="REG", week="10", away="NYJ", home="KC"):
    return dict(gameday=day, season=season, game_type=kind, week=week, away_team=away, home_team=home)


class NamingTests(unittest.TestCase):
    def test_config_uses_actual_nas_folder_names_and_allows_overrides(self):
        with patch.dict(os.environ, {}, clear=True):
            config = Config.env()
            self.assertEqual(config.routes["nfl"], (Path("/nfl/DOWNLOAD"), Path("/nfl/CHIEFS")))
            self.assertEqual(config.routes["ufc"], (Path("/ufc/DOWNLOAD"), Path("/ufc/COMPLETE")))
        with patch.dict(os.environ, {"NFL_DESTINATION_DIR": "/nfl/OTHER"}, clear=True):
            self.assertEqual(Config.env().routes["nfl"][1], Path("/nfl/OTHER"))

    def test_regular_and_release_suffix(self):
        self.assertEqual(nfl_title("nfl.2026.11.08.new.york.jets.vs.kansas.city.chiefs.1080p.mkv", [game()]),
                         "2026 - Week 10 - Jets at Chiefs")

    def test_sportarr_nfl_dates_and_metadata(self):
        for filename in [
            "NFL - S2026E175 - 2026-11-08 - Kansas City Chiefs vs New York Jets - sportarr-ev-1969822.mkv",
            "NFL - S2026E175 - Kansas City Chiefs vs New York Jets - 2026-11-08 - sportarr-ev-1969822.mkv",
            "NFL - 2026.11.08 - New York Jets at Kansas City Chiefs - 1080p.mkv",
            "NFL_S2026E175_2026_11_08_Kansas_City_Chiefs_vs_New_York_Jets_sportarr-ev-1969822.mkv",
        ]:
            with self.subTest(filename=filename):
                self.assertEqual(nfl_title(filename, [game()]), "2026 - Week 10 - Jets at Chiefs")

    def test_sportarr_home_first_and_explicit_away_at_home(self):
        for title in ["Kansas City Chiefs vs New York Jets", "New York Jets at Kansas City Chiefs"]:
            filename = f"NFL - S2026E175 - {title} -2026-11-08 - sportarr-ev-1969822.mkv"
            self.assertEqual(nfl_title(filename, [game(week="9")]), "2026 - Week 09 - Jets at Chiefs")
        with self.assertRaisesRegex(ValueError, "schedule match"):
            nfl_title("NFL - S2026E175 - New York Jets vs Kansas City Chiefs -2026-11-08.mkv", [game()])

    def test_sportarr_super_bowl_uses_schedule_designation(self):
        row = game("2023-02-12", "2022", "SB", "22", "KC", "PHI")
        self.assertEqual(nfl_title("NFL - S2022E999 - Philadelphia Eagles vs Kansas City Chiefs - 2023-02-12 - sportarr-ev-1.mkv", [row]),
                         "2022 - Super Bowl 57 - Chiefs at Eagles")

    def test_sportarr_episode_code_is_never_a_date_or_week(self):
        with self.assertRaisesRegex(ValueError, "game date"):
            nfl_title("NFL - S2026E175 - Kansas City Chiefs vs New York Jets - sportarr-ev-1969822.mkv", [game()])
        for dates in ["2026-02-30", "2026-11-08 - 2026-11-09"]:
            with self.assertRaises(ValueError):
                nfl_title(f"NFL - {dates} - New York Jets vs Kansas City Chiefs.mkv", [game()])

    def test_sportarr_ufc_title_retains_actual_event_number(self):
        rows = [dict(id=1, title="UFC 103: Franklin vs. Belfort", release_date="2009-09-19")]
        self.assertEqual(ufc_title("UFC - S2009E175 - 2009-09-19 - UFC 103 Franklin vs. Belfort - sportarr-ev-123.mkv", rows),
                         "UFC 103 Franklin vs. Belfort (2009)")
        self.assertEqual(ufc_title("UFC - S2009E175 - UFC 103 Early Prelims - sportarr-ev-123.mkv", rows),
                         "UFC 103 Franklin vs. Belfort (2009)")
        with self.assertRaises(ValueError):
            ufc_number("UFC - S2026E175 - Franklin vs. Belfort.mkv")

    def test_sportarr_part_markers(self):
        for marker, expected in [("pt1", "Early Prelims-featurette"), ("pt2", "Prelims-featurette"), ("pt3", None)]:
            for placement in [f"S2009E175{marker}", f"S2009E175 - {marker}"]:
                filename = f"UFC - {placement} - UFC 103 Franklin vs. Belfort - 2009-09-19 - sportarr-ev-123.mkv"
                self.assertEqual(ufc_part(filename), expected)
        with self.assertRaises(ValueError):
            ufc_part("UFC - S2009E175pt3 - UFC 103 Prelims.mkv")
        with self.assertRaises(ValueError):
            ufc_part("UFC - S2009E175pt4 - UFC 103.mkv")

    def test_season_year_and_super_bowl_filename_order(self):
        row = game("2023-02-12", "2022", "SB", "22", "KC", "PHI")
        self.assertEqual(nfl_title("nfl.2023.02.12.kansas.city.chiefs.vs.philadelphia.eagles.mp4", [row]),
                         "2022 - Super Bowl 57 - Chiefs at Eagles")
        self.assertEqual(nfl_title("nfl.2023.02.12.philadelphia.eagles.vs.kansas.city.chiefs.mp4", [row]),
                         "2022 - Super Bowl 57 - Eagles at Chiefs")

    def test_playoff_labels(self):
        for kind, label in [("WC", "Wildcard"), ("DIV", "Divisional"), ("CON", "Championship")]:
            self.assertEqual(nfl_title("nfl.2024.01.13.miami.dolphins.vs.kansas.city.chiefs.mkv",
                [game("2024-01-13", "2023", kind, "19", "MIA", "KC")]),
                f"2023 - AFC {label} - Dolphins at Chiefs")

    def test_no_date_guess(self):
        with self.assertRaises(ValueError):
            nfl_title("nfl.2026.11.09.new.york.jets.vs.kansas.city.chiefs.mkv", [game()])

    def test_alias_and_nfc(self):
        self.assertEqual(nfl_title("nfl.2024.01.14.los.angeles.rams.vs.detroit.lions.mkv",
            [game("2024-01-14", "2023", "WC", "19", "LA", "DET")]),
            "2023 - NFC Wildcard - Rams at Lions")

    def test_ufc_tmdb_and_prelims_filter(self):
        rows = [dict(id=1, title="UFC 103: Franklin vs. Belfort", release_date="2009-09-19"),
                dict(id=2, title="UFC 103 Prelims", release_date="2009-09-19"),
                dict(id=3, title="UFC 1030: Franklin vs. Belfort", release_date="2030-09-19")]
        self.assertEqual(ufc_title("UFC.103.Franklin.vs.Belfort.mkv", rows), "UFC 103 Franklin vs. Belfort (2009)")
        self.assertEqual(ufc_number("UFC.PPV103.Franklin.vs.Belfort.mkv"), 103)

    def test_wrong_fighters_and_ambiguity(self):
        rows = [dict(id=1, title="UFC 103: Franklin vs. Belfort", release_date="2009-09-19")]
        with self.assertRaises(ValueError):
            ufc_title("UFC.103.Jones.vs.Smith.mkv", rows)
        rows.append(dict(id=2, title="UFC 103: Franklin vs. Belfort", release_date="2009-09-19"))
        with self.assertRaises(ValueError):
            ufc_title("UFC.103.Franklin.vs.Belfort.mkv", rows)

    def test_prelim_detection_and_event_number_lookup(self):
        rows = [dict(id=1, title="UFC 103: Franklin vs. Belfort", release_date="2009-09-19")]
        for filename, expected in [
            ("UFC.103.Early.Prelims.mkv", "Early Prelims-featurette"),
            ("UFC_103_EarlyPrelims_1080p.mp4", "Early Prelims-featurette"),
            ("UFC.103.Prelims.mkv", "Prelims-featurette"),
            ("UFC.103.Preliminary.Card.mp4", "Prelims-featurette"),
        ]:
            self.assertEqual(ufc_part(filename), expected)
            self.assertEqual(ufc_title(filename, rows), "UFC 103 Franklin vs. Belfort (2009)")


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        routes = {sport: (root / sport / "downloads", root / sport / "complete") for sport in ("nfl", "ufc")}
        for pair in routes.values():
            for path in pair:
                path.mkdir(parents=True)
        self.config = Config(root / "data", routes, "x" * 32, dry_run=False)
        self.service = Organizer(self.config)
        self.service.schedule = [game()]
        self.service.schedule_loaded = time.time()
        self.filename = "nfl.2026.11.08.new.york.jets.vs.kansas.city.chiefs.mkv"
        self.source = routes["nfl"][0] / self.filename
        self.source.write_bytes(b"example-video-data")
        self.destination = routes["nfl"][1] / "2026 - Week 10 - Jets at Chiefs" / "2026 - Week 10 - Jets at Chiefs.mkv"

    def tearDown(self):
        self.service.close()
        self.tmp.cleanup()

    def test_move_and_history(self):
        job = self.service.enqueue("nfl", self.filename)
        self.service.run_once()
        self.assertFalse(self.source.exists())
        self.assertEqual(self.destination.read_bytes(), b"example-video-data")
        self.assertEqual(self.service.get_job(job["id"])["status"], "completed")

    def test_nas_copy_fallback_moves_and_journals_verified_file(self):
        job = self.service.enqueue("nfl", self.filename)
        with patch("organizer.rename_no_replace", side_effect=verified_copy_move):
            self.service.run_once()
        result = self.service.get_job(job["id"])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(self.destination.read_bytes(), b"example-video-data")
        self.assertFalse(self.source.exists())
        self.assertEqual(result["destination_fingerprint"], self.service.fingerprint(self.destination))

    def test_linux_unsupported_rename_automatically_uses_copy(self):
        self.destination.parent.mkdir()
        with patch("organizer.sys.platform", "linux"), patch("organizer.ctypes.CDLL") as library, patch("organizer.ctypes.get_errno", return_value=errno.EOPNOTSUPP):
            library.return_value.renameat2.return_value = -1
            rename_no_replace(self.source, self.destination)
        self.assertFalse(self.source.exists())
        self.assertEqual(self.destination.read_bytes(), b"example-video-data")

    def test_copy_fallback_never_overwrites_existing_file(self):
        self.destination.parent.mkdir()
        self.destination.write_bytes(b"existing-video")
        with self.assertRaises(FileExistsError):
            verified_copy_move(self.source, self.destination)
        self.assertEqual(self.destination.read_bytes(), b"existing-video")
        self.assertTrue(self.source.exists())

    def test_failed_copy_verification_retains_source(self):
        self.destination.parent.mkdir()
        with patch("organizer.hashlib.file_digest") as digest:
            digest.return_value.digest.return_value = b"incorrect hash"
            with self.assertRaisesRegex(ValueError, "verification"):
                verified_copy_move(self.source, self.destination)
        self.assertEqual(self.source.read_bytes(), b"example-video-data")
        self.assertFalse(self.destination.exists())

    def test_journal_failure_before_source_removal_retains_source(self):
        self.destination.parent.mkdir()
        def fail(path):
            raise OSError("journal unavailable")
        with self.assertRaises(OSError):
            verified_copy_move(self.source, self.destination, fail)
        self.assertTrue(self.source.exists())
        self.assertFalse(self.destination.exists())

    def test_copy_fallback_restart_recovers_after_source_removal(self):
        job = self.service.enqueue("nfl", self.filename)
        self.destination.parent.mkdir()
        self.service.update(job["id"], status="moving", destination=str(self.destination))
        verified_copy_move(self.source, self.destination,
            lambda copied: self.service.update(job["id"], destination_fingerprint=self.service.fingerprint(copied)))
        self.service.close()
        self.service = Organizer(self.config)
        self.assertEqual(self.service.get_job(job["id"])["status"], "completed")
        self.assertEqual(self.destination.read_bytes(), b"example-video-data")

    def test_user_sportarr_home_first_file_moves_as_away_at_home(self):
        filename = "NFL - S2026E175 - Kansas City Chiefs vs New York Jets -2026-11-08 - sportarr-ev-1969822.mkv"
        self.source.rename(self.source.parent / filename)
        self.service.schedule = [game(week="9")]
        job = self.service.enqueue("nfl", filename)
        self.service.run_once()
        result = self.service.get_job(job["id"])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["title"], "2026 - Week 09 - Jets at Chiefs")
        self.assertEqual(Path(result["destination"]).read_bytes(), b"example-video-data")

    def test_regular_season_week_padding_in_both_file_and_folder(self):
        for week in [1, 2, 9, 10, 18]:
            with self.subTest(week=week):
                self.service.schedule = [game(week=str(week))]
                plan = self.service.preview("nfl", self.filename)
                expected = f"2026 - Week {week:02d} - Jets at Chiefs"
                self.assertEqual(plan["title"], expected)
                self.assertEqual(Path(plan["destination"]).parent.name, expected)
                self.assertEqual(Path(plan["destination"]).name, expected + ".mkv")

    def test_dry_run_then_retry(self):
        self.config.dry_run = True
        job = self.service.enqueue("nfl", self.filename)
        self.service.run_once()
        self.assertTrue(self.source.exists())
        self.assertFalse(self.destination.exists())
        self.assertEqual(self.service.get_job(job["id"])["status"], "previewed")
        self.config.dry_run = False
        self.service.retry(job["id"])
        self.service.run_once()
        self.assertTrue(self.destination.exists())

    def test_duplicate_destination_never_overwritten(self):
        self.destination.parent.mkdir()
        self.destination.write_bytes(b"existing")
        job = self.service.enqueue("nfl", self.filename)
        self.service.run_once()
        self.assertEqual(self.destination.read_bytes(), b"existing")
        self.assertTrue(self.source.exists())
        self.assertEqual(self.service.get_job(job["id"])["status"], "review")

    def test_repeated_webhook_queue_is_idempotent(self):
        a = self.service.enqueue("nfl", self.filename)
        b = self.service.enqueue("nfl", self.filename)
        self.assertEqual(a["id"], b["id"])
        self.assertEqual(len(self.service.jobs()), 1)
        self.service.run_once()
        self.assertEqual(self.service.enqueue("nfl", self.filename)["id"], a["id"])

    def test_changed_file_not_moved(self):
        job = self.service.enqueue("nfl", self.filename)
        self.source.write_bytes(b"still transferring more bytes")
        self.service.run_once()
        self.assertTrue(self.source.exists())
        self.assertEqual(self.service.get_job(job["id"])["status"], "review")

    def test_path_validation(self):
        for filename in ["../escape.mkv", "/etc/test.mkv", "..\\escape.mkv", ".hidden.mkv", "file.part"]:
            with self.assertRaises(ValueError):
                self.service.enqueue("nfl", filename)

    def test_poll_waits_and_resets_on_growth(self):
        self.config.mode = "poll"
        self.config.stable_seconds = 10
        self.service.poll()
        self.assertEqual(self.service.jobs(), [])
        key = ("nfl", self.filename)
        fp, _ = self.service.seen[key]
        self.service.seen[key] = (fp, time.monotonic() - 20)
        self.source.write_bytes(b"new growth")
        self.service.poll()
        self.assertEqual(self.service.jobs(), [])
        fp, _ = self.service.seen[key]
        os.utime(self.source, (time.time() - 30, time.time() - 30))
        fp = self.service.fingerprint(self.source)
        self.service.seen[key] = (fp, time.monotonic() - 20)
        self.service.poll()
        self.assertEqual(len(self.service.jobs()), 1)

    def test_notification_failure_does_not_undo_move(self):
        self.config.pushover_enabled = True
        self.config.pushover_user = "user"
        self.config.pushover_token = "token"
        job = self.service.enqueue("nfl", self.filename)
        with patch("organizer.request_json", side_effect=OSError("offline")):
            self.service.run_once()
        result = self.service.get_job(job["id"])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["notification"], "pending")
        self.assertEqual(result["notify_attempts"], 1)
        self.assertTrue(self.destination.exists())

    def test_pushover_success_and_no_dry_run_notification(self):
        self.config.pushover_enabled = True
        job = self.service.enqueue("nfl", self.filename)
        with patch("organizer.request_json", return_value={"status": 1}) as call:
            self.service.run_once()
            self.assertEqual(call.call_count, 1)
            payload = urllib.parse.parse_qs(call.call_args.kwargs["data"].decode())
            self.assertEqual(payload["title"], ["Sports Organizer"])
            self.assertIn("Completed: 2026 - Week 10 - Jets at Chiefs", payload["message"][0])
        self.assertEqual(self.service.get_job(job["id"])["notification"], "sent")

    def test_file_errors_report_the_affected_path(self):
        message = self.service.error_text(FileNotFoundError(2, "No such file or directory", "/nfl/CHIEFS/missing.mkv"))
        self.assertIn("/nfl/CHIEFS/missing.mkv", message)
        self.assertIn("No such file", message)

    def test_dry_run_never_sends_completion_notification(self):
        self.config.dry_run = True
        self.config.pushover_enabled = True
        self.service.enqueue("nfl", self.filename)
        with patch("organizer.request_json") as call:
            self.service.run_once()
            call.assert_not_called()

    def test_notification_gives_up_after_five_attempts(self):
        self.config.pushover_enabled = True
        job = self.service.enqueue("nfl", self.filename)
        with patch("organizer.request_json", side_effect=OSError("offline")) as call:
            for _ in range(7):
                self.service.update(job["id"], notify_after=0)
                self.service.run_once()
            self.assertEqual(call.call_count, 5)
        result = self.service.get_job(job["id"])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["notification"], "failed")
        self.assertTrue(self.destination.exists())

    def test_ufc_search_cache_and_end_to_end_move(self):
        self.config.tmdb_token = "example-read-token"
        filename = "UFC.103.Franklin.vs.Belfort.mp4"
        source = self.config.routes["ufc"][0] / filename
        source.write_bytes(b"UFC-example")
        job = self.service.enqueue("ufc", filename)
        results = {"results": [dict(id=100, title="UFC 103: Franklin vs. Belfort", release_date="2009-09-19")], "total_pages": 1}
        with patch("organizer.request_json", return_value=results) as call:
            self.service.preview("ufc", filename)
            self.service.run_once()
            self.assertEqual(call.call_count, 1)
        destination = self.config.routes["ufc"][1] / "UFC 103 Franklin vs. Belfort (2009)" / "UFC 103 Franklin vs. Belfort (2009).mp4"
        self.assertEqual(destination.read_bytes(), b"UFC-example")
        self.assertFalse(source.exists())
        self.assertEqual(self.service.get_job(job["id"])["status"], "completed")

    def test_nfl_schedule_fetch_and_offline_cache(self):
        data = "gameday,season,game_type,week,away_team,home_team\n2026-11-08,2026,REG,10,NYJ,KC\n"
        self.service.schedule = None
        with patch("organizer.urllib.request.urlopen", return_value=io.BytesIO(data.encode())):
            self.assertEqual(self.service.schedule_rows()[0]["week"], "10")
        cache = self.config.data / "nfl-schedule.csv"
        os.utime(cache, (time.time() - 90000, time.time() - 90000))
        self.service.schedule = None
        with patch("organizer.urllib.request.urlopen", side_effect=OSError("offline")):
            self.assertEqual(self.service.schedule_rows()[0]["week"], "10")

    def test_restart_recovers_move_before_commit(self):
        job = self.service.enqueue("nfl", self.filename)
        self.service.update(job["id"], status="moving", title="2026 - Week 10 - Jets at Chiefs", destination=str(self.destination))
        self.destination.parent.mkdir()
        self.source.rename(self.destination)
        self.service.close()
        self.service = Organizer(self.config)
        self.assertEqual(self.service.get_job(job["id"])["status"], "completed")

    def test_restart_recovers_before_rename(self):
        job = self.service.enqueue("nfl", self.filename)
        self.service.update(job["id"], status="moving", destination=str(self.destination))
        self.destination.parent.mkdir()
        self.service.close()
        self.service = Organizer(self.config)
        self.assertEqual(self.service.get_job(job["id"])["status"], "queued")
        self.assertTrue(self.source.exists())
        self.assertFalse(self.destination.parent.exists())

    def test_rename_failure_retains_source(self):
        job = self.service.enqueue("nfl", self.filename)
        with patch("organizer.rename_no_replace", side_effect=OSError("NAS unavailable")):
            self.service.run_once()
        self.assertTrue(self.source.exists())
        self.assertFalse(self.destination.exists())
        self.assertEqual(self.service.get_job(job["id"])["status"], "review")

    def seed_ufc(self):
        self.config.tmdb_token = "test-token"
        (self.config.data / "tmdb-103.json").write_text(json.dumps([
            dict(id=1, title="UFC 103: Franklin vs. Belfort", release_date="2009-09-19")]))

    def stage_ufc(self, filename, content=b"prelims-video"):
        path = self.config.routes["ufc"][0] / filename
        path.write_bytes(content)
        return self.service.enqueue("ufc", filename)

    def test_ufc_all_cards_share_folder_in_any_arrival_order(self):
        self.seed_ufc()
        files = ["UFC.103.Early.Prelims.mp4", "UFC.103.Prelims.mkv", "UFC.103.Franklin.vs.Belfort.mkv"]
        folder = self.config.routes["ufc"][1] / "UFC 103 Franklin vs. Belfort (2009)"
        for filename in files:
            job = self.stage_ufc(filename)
            self.service.run_once()
            self.assertEqual(self.service.get_job(job["id"])["status"], "completed")
        self.assertEqual(sorted(p.name for p in folder.iterdir()), [
            "Early Prelims-featurette.mp4", "Prelims-featurette.mkv", "UFC 103 Franklin vs. Belfort (2009).mkv"])

    def test_sportarr_standard_parts_share_one_event_folder(self):
        self.seed_ufc()
        for part in [3, 1, 2]:
            filename = f"UFC - S2009E175pt{part} - UFC 103 Franklin vs. Belfort - 2009-09-19 - sportarr-ev-123.mkv"
            job = self.stage_ufc(filename)
            self.service.run_once()
            self.assertEqual(self.service.get_job(job["id"])["status"], "completed")
        folder = self.config.routes["ufc"][1] / "UFC 103 Franklin vs. Belfort (2009)"
        self.assertEqual({p.name for p in folder.iterdir()}, {
            "Early Prelims-featurette.mkv", "Prelims-featurette.mkv", "UFC 103 Franklin vs. Belfort (2009).mkv"})

    def test_main_card_first_then_prelims_and_duplicate_extension(self):
        self.seed_ufc()
        first = self.stage_ufc("UFC.103.Franklin.vs.Belfort.mkv")
        self.service.run_once()
        second = self.stage_ufc("UFC.103.Prelims.mkv", b"original-prelims")
        self.service.run_once()
        duplicate = self.stage_ufc("UFC.103.Prelims.mp4", b"duplicate-prelims")
        self.service.run_once()
        self.assertEqual(self.service.get_job(first["id"])["status"], "completed")
        self.assertEqual(self.service.get_job(second["id"])["status"], "completed")
        self.assertEqual(self.service.get_job(duplicate["id"])["status"], "review")
        folder = self.config.routes["ufc"][1] / "UFC 103 Franklin vs. Belfort (2009)"
        self.assertEqual((folder / "Prelims-featurette.mkv").read_bytes(), b"original-prelims")
        self.assertFalse((folder / "Prelims-featurette.mp4").exists())

    def test_prelim_failed_move_preserves_main_card_and_recovery(self):
        self.seed_ufc()
        main = self.stage_ufc("UFC.103.Franklin.vs.Belfort.mkv", b"main-video")
        self.service.run_once()
        prelim = self.stage_ufc("UFC.103.Prelims.mkv")
        with patch("organizer.rename_no_replace", side_effect=OSError("NAS unavailable")):
            self.service.run_once()
        main_path = Path(self.service.get_job(main["id"])["destination"])
        self.assertEqual(main_path.read_bytes(), b"main-video")
        failed = self.service.get_job(prelim["id"])
        self.assertEqual(failed["status"], "review")
        self.service.update(prelim["id"], status="moving")
        self.service.close()
        self.service = Organizer(self.config)
        self.assertEqual(self.service.get_job(prelim["id"])["status"], "queued")
        self.service.run_once()
        self.assertEqual(self.service.get_job(prelim["id"])["status"], "completed")
        self.assertEqual(main_path.read_bytes(), b"main-video")

    def test_sportarr_native_payload_uses_staging_copy_only(self):
        self.service.sportarr("nfl", {"eventType": "Test"})
        self.service.sportarr("nfl", {"eventType": "Grab"})
        self.assertEqual(self.service.jobs(), [])
        job = self.service.sportarr("nfl", {"eventType": "Download", "episodeFile": {
            "path": "/managed/library/" + self.filename, "relativePath": self.filename}})
        self.service.run_once()
        self.assertEqual(self.service.get_job(job["id"])["status"], "completed")
        self.assertTrue(self.destination.exists())

    def test_sportarr_missing_staging_copy_rejected(self):
        with self.assertRaises(ValueError):
            self.service.sportarr("nfl", {"eventType": "Download", "episodeFile": {
                "path": "/managed/library/not-a-staged-copy.mkv"}})
        self.assertTrue(self.source.exists())

    def test_api_auth_and_webhook_completion_flag(self):
        # Exercise the real HTTP request parser and handler without requiring
        # network access in restricted development environments.
        class Connection:
            def __init__(self, raw):
                self.reader = io.BytesIO(raw)
                self.response = io.BytesIO()

            def settimeout(self, value):
                pass

            def makefile(self, mode, *args):
                return self.reader

            def sendall(self, data):
                self.response.write(data)

        def request(path, body=None, auth=True):
            data = json.dumps(body).encode() if body is not None else b""
            method = "POST" if body is not None else "GET"
            headers = f"{method} {path} HTTP/1.1\r\nHost: localhost\r\nContent-Length: {len(data)}\r\n"
            if auth:
                headers += "Authorization: Bearer " + self.config.token + "\r\n"
            connection = Connection((headers + "Connection: close\r\n\r\n").encode() + data)
            handler_for(self.service)(connection, ("127.0.0.1", 0), None)
            head, body = connection.response.getvalue().split(b"\r\n\r\n", 1)
            return int(head.split()[1]), json.loads(body)
        self.assertEqual(request("/jobs", auth=False)[0], 401)
        self.assertEqual(request("/webhooks/complete", {"sport": "nfl", "filename": self.filename})[0], 400)
        status, body = request("/webhooks/complete", {"sport": "nfl", "filename": self.filename, "transfer_complete": True})
        self.assertEqual(status, 202)
        self.assertEqual(body["status"], "queued")
        self.assertEqual(request("/preview", {"sport": "nfl", "filename": self.filename})[1]["title"],
                         "2026 - Week 10 - Jets at Chiefs")
        self.assertEqual(request("/webhooks/complete", [1, 2])[0], 400)
        self.assertEqual(request("/unknown")[0], 404)


if __name__ == "__main__":
    unittest.main()
