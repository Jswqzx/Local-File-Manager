import json
from pathlib import Path


CONFIG_FILE = Path(__file__).resolve().parent.parent / "file_update_config.json"
RULES_FILE = Path(__file__).resolve().parent.parent / "site_rules_config.json"


def load_file_update_rows() -> list[dict[str, object]]:
    if not CONFIG_FILE.exists():
        return []

    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return []

    if not isinstance(data, list):
        return []

    rows: list[dict[str, object]] = []
    for row in data:
        if not isinstance(row, dict):
            continue
        resources = row.get("resources", [])
        normalized_resources: list[dict[str, str]] = []
        if isinstance(resources, list):
            for item in resources:
                if not isinstance(item, dict):
                    continue
                normalized_resources.append(
                    {
                        "name": str(item.get("name", "")).strip(),
                        "detail_url": str(item.get("detail_url", "")).strip(),
                        "download_url": str(item.get("download_url", "")).strip(),
                    }
                )
        resources_by_param = row.get("resources_by_param", {})
        normalized_resources_by_param: dict[str, list[dict[str, str]]] = {}
        if isinstance(resources_by_param, dict):
            for params_text, items in resources_by_param.items():
                if not isinstance(params_text, str) or not isinstance(items, list):
                    continue
                normalized_items: list[dict[str, str]] = []
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    normalized_items.append(
                        {
                            "name": str(item.get("name", "")).strip(),
                            "detail_url": str(item.get("detail_url", "")).strip(),
                            "download_url": str(item.get("download_url", "")).strip(),
                        }
                    )
                normalized_resources_by_param[params_text.strip()] = normalized_items
        rows.append(
            {
                "url": str(row.get("url", "")).strip(),
                "params": str(row.get("params", "")).strip(),
                "resources": normalized_resources,
                "resources_by_param": normalized_resources_by_param,
            }
        )
    return rows


def save_file_update_rows(rows: list[dict[str, object]]) -> None:
    normalized_rows = [
        {
            "url": str(row.get("url", "")).strip(),
            "params": str(row.get("params", "")).strip(),
            "resources": [
                {
                    "name": str(item.get("name", "")).strip(),
                    "detail_url": str(item.get("detail_url", "")).strip(),
                    "download_url": str(item.get("download_url", "")).strip(),
                }
                for item in row.get("resources", [])
                if isinstance(item, dict)
                and (
                    str(item.get("name", "")).strip()
                    or str(item.get("detail_url", "")).strip()
                    or str(item.get("download_url", "")).strip()
                )
            ],
            "resources_by_param": {
                str(params_text).strip(): [
                    {
                        "name": str(item.get("name", "")).strip(),
                        "detail_url": str(item.get("detail_url", "")).strip(),
                        "download_url": str(item.get("download_url", "")).strip(),
                    }
                    for item in items
                    if isinstance(item, dict)
                    and (
                        str(item.get("name", "")).strip()
                        or str(item.get("detail_url", "")).strip()
                        or str(item.get("download_url", "")).strip()
                    )
                ]
                for params_text, items in row.get("resources_by_param", {}).items()
                if str(params_text).strip() and isinstance(items, list)
            },
        }
        for row in rows
        if str(row.get("url", "")).strip()
    ]
    CONFIG_FILE.write_text(
        json.dumps(normalized_rows, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_site_rules() -> dict[str, list[dict[str, object]]]:
    if not RULES_FILE.exists():
        return {}

    try:
        data = json.loads(RULES_FILE.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}

    if not isinstance(data, dict):
        return {}

    rules: dict[str, list[dict[str, object]]] = {}
    for site_url, items in data.items():
        if not isinstance(site_url, str) or not isinstance(items, list):
            continue
        normalized_items = _normalize_rule_items(items)
        rules[site_url.strip()] = normalized_items
    return rules


def save_site_rules(rules: dict[str, list[dict[str, object]]]) -> None:
    normalized_rules: dict[str, list[dict[str, object]]] = {}
    for site_url, items in rules.items():
        cleaned_url = str(site_url).strip()
        if not cleaned_url:
            continue
        normalized_items = _normalize_rule_items(items)
        normalized_rules[cleaned_url] = normalized_items

    RULES_FILE.write_text(
        json.dumps(normalized_rules, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _normalize_rule_items(items: list[dict[str, object]]) -> list[dict[str, object]]:
    normalized_items: list[dict[str, object]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        children = item.get("children", [])
        normalized_items.append(
            {
                "site_name": str(item.get("site_name", "")).strip(),
                "match_url": str(item.get("match_url", "")).strip(),
                "purpose": str(item.get("purpose", "")).strip(),
                "rule_json": str(item.get("rule_json", "")).strip(),
                "children": _normalize_rule_items(children) if isinstance(children, list) else [],
            }
        )
    return normalized_items
