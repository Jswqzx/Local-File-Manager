import re
from fnmatch import translate
from pathlib import Path

from .models import EntryRecord


GroupKey = tuple[str, str]


def build_filter_pattern(filter_text: str) -> re.Pattern[str]:
    if filter_text.startswith("regex:"):
        return re.compile(filter_text[6:])

    if any(char in filter_text for char in "*?[]"):
        return re.compile(translate(filter_text))

    return re.compile(filter_text)


def calculate_size(path: Path, is_dir: bool) -> int:
    if not is_dir:
        try:
            return path.stat().st_size
        except OSError:
            return 0

    total_size = 0
    try:
        for child in path.rglob("*"):
            try:
                if child.is_file():
                    total_size += child.stat().st_size
            except OSError:
                continue
    except OSError:
        return 0
    return total_size


def collect_entries(
    root: Path,
    pattern: re.Pattern[str] | None,
    recursive: bool,
) -> list[EntryRecord]:
    iterator = root.rglob("*") if recursive else root.iterdir()
    entries: list[EntryRecord] = []

    for item in iterator:
        try:
            is_dir = item.is_dir()
        except OSError:
            continue

        relative_path = item.relative_to(root).as_posix()
        type_label = "Folder" if is_dir else (item.suffix.lower() or "[no extension]")
        search_text = f"{item.name} {relative_path} {type_label}"
        if pattern and not pattern.search(search_text):
            continue

        entries.append(
            EntryRecord(
                path=item,
                kind="Folder" if is_dir else "File",
                type_label=type_label,
                relative_path=relative_path,
                size_bytes=calculate_size(item, is_dir),
            )
        )

    entries.sort(key=lambda entry: (entry.kind != "Folder", entry.type_label, entry.relative_path))
    return entries


def build_groups(entries: list[EntryRecord]) -> dict[GroupKey, list[EntryRecord]]:
    groups: dict[GroupKey, list[EntryRecord]] = {
        ("All", "All"): list(entries),
        ("Folder", "All"): [],
        ("File", "All"): [],
    }

    for entry in entries:
        groups.setdefault((entry.kind, entry.type_label), []).append(entry)
        groups[(entry.kind, "All")].append(entry)

    return groups


def format_size(size_bytes: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(size_bytes)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} TB"


def build_rename_plan(
    selected_paths: list[Path],
    source_text: str,
    target_text: str,
) -> tuple[list[tuple[Path, Path]], list[str]]:
    rename_pairs: list[tuple[Path, Path]] = []
    skipped_paths: list[str] = []
    seen_targets: set[Path] = set()

    for path in selected_paths:
        new_name = path.name.replace(source_text, target_text)
        if new_name == path.name:
            skipped_paths.append(str(path))
            continue

        target_path = path.with_name(new_name)
        if target_path.exists() and target_path != path:
            skipped_paths.append(f"{path} -> {target_path} 已存在")
            continue
        if target_path in seen_targets:
            skipped_paths.append(f"{path} -> {target_path} 目标重复")
            continue

        seen_targets.add(target_path)
        rename_pairs.append((path, target_path))

    return rename_pairs, skipped_paths


def is_path_within(candidate: Path, parent: Path) -> bool:
    try:
        candidate.relative_to(parent)
        return True
    except ValueError:
        return False
