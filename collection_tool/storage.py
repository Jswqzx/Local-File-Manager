import json
from pathlib import Path


CONFIG_FILE = Path(__file__).resolve().parent.parent / "file_update_config.json"
RULES_FILE = Path(__file__).resolve().parent.parent / "site_rules_config.json"


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


def load_site_rules() -> dict[str, list[dict[str, str]]]:
    if not RULES_FILE.exists():
        return {}

    try:
        data = json.loads(RULES_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

    if not isinstance(data, dict):
        return {}

    rules: dict[str, list[dict[str, str]]] = {}
    for site_url, items in data.items():
        if not isinstance(site_url, str) or not isinstance(items, list):
            continue
        normalized_items: list[dict[str, str]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            normalized_items.append(
                {
                    "site_name": str(item.get("site_name", "")).strip(),
                    "match_url": str(item.get("match_url", "")).strip(),
                    "rule_json": str(item.get("rule_json", "")).strip(),
                }
            )
        rules[site_url.strip()] = normalized_items
    return rules


def save_site_rules(rules: dict[str, list[dict[str, str]]]) -> None:
    normalized_rules: dict[str, list[dict[str, str]]] = {}
    for site_url, items in rules.items():
        cleaned_url = str(site_url).strip()
        if not cleaned_url:
            continue
        normalized_items: list[dict[str, str]] = []
        for item in items:
            normalized_items.append(
                {
                    "site_name": str(item.get("site_name", "")).strip(),
                    "match_url": str(item.get("match_url", "")).strip(),
                    "rule_json": str(item.get("rule_json", "")).strip(),
                }
            )
        normalized_rules[cleaned_url] = normalized_items

    RULES_FILE.write_text(
        json.dumps(normalized_rules, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
