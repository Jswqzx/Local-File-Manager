import sys

from collection_tool import run


if __name__ == "__main__":
    try:
        sys.exit(run())
    except Exception as exc:
        print(f"Application failed to start: {exc}", file=sys.stderr)
        raise
