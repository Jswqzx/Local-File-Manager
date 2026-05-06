import sys

from collection_tool import run
#https://misskon.com/page/1/?s=%E8%A0%A2%E6%B2%AB%E6%B2%AB

if __name__ == "__main__":
    try:
        sys.exit(run())
    except Exception as exc:
        print(f"Application failed to start: {exc}", file=sys.stderr)
        raise
