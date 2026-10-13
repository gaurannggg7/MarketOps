"""Write the OpenAPI contract to stdout or a path: `python -m app.export_openapi out.json`."""

from __future__ import annotations

import json
import sys

from app.config import Settings
from app.main import create_app


def main() -> None:
    # Building the schema does not connect to the database or start the runtime.
    app = create_app(Settings(simulator_enabled=False), null_pool=True)
    text = json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"
    if len(sys.argv) > 1:
        with open(sys.argv[1], "w") as fh:
            fh.write(text)
    else:
        sys.stdout.write(text)


if __name__ == "__main__":
    main()
