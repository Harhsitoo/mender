"""Allow `python -m mender ...`."""

from mender.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
