"""Dump the FastAPI OpenAPI schema to stdout, for `make types`.

No server needed: this imports the app object directly.
"""

import json

from gridtwin.api.main import app


def main() -> None:
    print(json.dumps(app.openapi(), indent=2))


if __name__ == "__main__":
    main()
