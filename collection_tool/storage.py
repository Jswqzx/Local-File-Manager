import json
from pathlib import Path


CONFIG_FILE = Path(__file__).resolve().parent.parent / "file_update_config.json"


def load_file_update_rows() -> list[dict[str, str]]:
    if not CONFIG_FILE.exists():
        return []

    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    if not isinstance(data, list):
        return []

    rows: list[dict[str, str]] = []
    for row in data:
        if not isinstance(row, dict):
            continue
        rows.append(
            {
                "url": str(row.get("url", "")).strip(),
                "params": str(row.get("params", "")).strip(),
            }
        )
    return rows


def save_file_update_rows(rows: list[dict[str, str]]) -> None:
    normalized_rows = [
        {
            "url": str(row.get("url", "")).strip(),
            "params": str(row.get("params", "")).strip(),
        }
        for row in rows
        if str(row.get("url", "")).strip()
    ]
    CONFIG_FILE.write_text(
        json.dumps(normalized_rows, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
