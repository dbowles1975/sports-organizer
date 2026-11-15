"""CI-only live HTTP check against the built Linux Docker image."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

import organizer


def main():
    token = "smoke-test-token-not-a-real-secret-123456"
    name = "sports-organizer-smoke"
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        os.chmod(root, 0o755)
        for relative in ["nfl", "nfl/DOWNLOAD", "nfl/CHIEFS", "ufc", "ufc/DOWNLOAD", "ufc/COMPLETE", "data"]:
            path = root / relative
            path.mkdir(exist_ok=True)
            os.chmod(path, 0o777)
        command = ["docker", "run", "-d", "--name", name,
                   "-e", "API_TOKEN=" + token, "-e", "DRY_RUN=true",
                   "-p", "127.0.0.1::8080"]
        for folder in ["nfl", "ufc", "data"]:
            command.extend(["-v", f"{root / folder}:/{folder}"])
        subprocess.run(command + ["sports-organizer:smoke"], check=True, capture_output=True)
        try:
            published = subprocess.check_output(["docker", "port", name, "8080/tcp"], text=True).strip()
            base = "http://" + published
            for attempt in range(30):
                try:
                    request = urllib.request.Request(base + "/health", headers={"Authorization": "Bearer " + token})
                    with urllib.request.urlopen(request, timeout=3) as response:
                        health = json.load(response)
                    break
                except (OSError, ValueError):
                    time.sleep(1)
            else:
                raise RuntimeError("Container health endpoint did not become ready")
            assert health["version"] == organizer.VERSION, health
            assert health["healthy"] and health["dry_run"], health
            try:
                urllib.request.urlopen(base + "/jobs", timeout=3)
            except urllib.error.HTTPError as exc:
                assert exc.code == 401
            else:
                raise AssertionError("Unauthenticated job request was accepted")
            request = urllib.request.Request(base + "/jobs", headers={"Authorization": "Bearer " + token})
            with urllib.request.urlopen(request, timeout=3) as response:
                assert json.load(response) == {"jobs": []}
            print("Live container health, version, routes, authentication, and jobs checks passed")
        except Exception:
            subprocess.run(["docker", "logs", name], check=False)
            raise
        finally:
            subprocess.run(["docker", "rm", "-f", name], check=False, capture_output=True)


if __name__ == "__main__":
    main()
