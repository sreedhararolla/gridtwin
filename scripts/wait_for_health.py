"""`make demo` helper: poll the API health endpoint until every dependency is up."""

import json
import sys
import time
import urllib.request

URL = "http://localhost:8000/health"
TIMEOUT_SECONDS = 90
POLL_SECONDS = 2


def main() -> int:
    deadline = time.monotonic() + TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(URL, timeout=3) as resp:  # noqa: S310 - fixed localhost URL
                body = json.loads(resp.read())
                if body.get("ok"):
                    print("all dependencies healthy")
                    return 0
                print(f"waiting for dependencies: {body}")
        except Exception as exc:  # noqa: BLE001 - keep polling through any transient error
            print(f"waiting for API: {exc}")
        time.sleep(POLL_SECONDS)
    print("timed out waiting for dependencies", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
