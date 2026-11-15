#!/usr/bin/env python3
"""Call after a separate staging copy finishes; Python 3, no dependencies."""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request


def main():
    parser = argparse.ArgumentParser(description="Report a fully transferred video to Sports Organizer")
    parser.add_argument("sport", choices=["nfl", "ufc"])
    parser.add_argument("file", help="Staged filename or full path; only the basename is sent")
    args = parser.parse_args()
    token = os.environ.get("API_TOKEN", "")
    if not token:
        parser.error("Set API_TOKEN in this script's environment")
    url = os.environ.get("ORGANIZER_URL", "http://127.0.0.1:8080").rstrip("/")
    data = json.dumps({"sport": args.sport, "filename": args.file.replace("\\", "/").rsplit("/", 1)[-1],
                       "transfer_complete": True}).encode()
    request = urllib.request.Request(url + "/webhooks/complete", data=data,
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            print(response.read().decode())
    except urllib.error.HTTPError as exc:
        print(f"Organizer returned HTTP {exc.code}: {exc.read().decode()}", file=sys.stderr)
        return 1
    except OSError:
        print("Cannot reach Sports Organizer; check the URL and connection", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
