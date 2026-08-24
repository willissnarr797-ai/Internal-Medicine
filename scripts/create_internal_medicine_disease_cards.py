#!/usr/bin/env python3
"""Create system-grouped disease card files for internal medicine.

The source of truth is ``00_全书疾病清单.json``.  The requested Obsidian
template is read and fingerprinted as the future card template, but its YAML
and body are intentionally not copied during placeholder creation.  Later
source-backed card builders may register selected non-empty cards in a manifest;
those files are then preserved and accepted by this base verifier.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path


EXPECTED_DISEASE_COUNT = 653
TARGET_DIR = "998_疾病卡片"
TEMPLATE_RELATIVE = Path("00_模板") / "疾病模板1.md"
INDEX_RELATIVE = (
    Path("999_附件文件夹")
    / "02_内科学第10版_按章节"
    / "00_全书疾病清单.json"
)
REGISTERED_CONTENT_MANIFESTS = (
    Path("scripts") / "respiratory_306_cards_manifest.json",
)

SYSTEM_DIRS = {
    2: "02_呼吸系统疾病",
    3: "03_循环系统疾病",
    4: "04_消化系统疾病",
    5: "05_泌尿系统疾病",
    6: "06_血液系统疾病",
    7: "07_内分泌和代谢性疾病",
    8: "08_风湿免疫病",
    9: "09_理化因素所致疾病",
}

# Windows forbids < > : " / \ | ? * in filenames.  These replacements retain
# the medical meaning and are stable for future reruns.
SAFE_NAME_OVERRIDES = {
    "亚急性/慢性结节病": "亚急性、慢性结节病",
    "无症状性血尿和/或蛋白尿": "无症状性血尿和（或）蛋白尿",
    r"$\alpha$ 珠蛋白生成障碍性贫血": "α珠蛋白生成障碍性贫血",
    "蕈样肉芽肿病 / 塞扎里综合征": "蕈样肉芽肿病、塞扎里综合征",
    "LH/HCG受体功能缺陷": "LH-HCG受体功能缺陷",
}

INVALID_FILENAME_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_stem(name: str) -> str:
    stem = SAFE_NAME_OVERRIDES.get(name, name).strip()
    if INVALID_FILENAME_RE.search(stem):
        raise RuntimeError(f"Disease name still contains invalid filename characters: {name}")
    if stem.endswith((" ", ".")):
        raise RuntimeError(f"Disease filename has an invalid ending: {name}")
    if stem.upper() in RESERVED_NAMES:
        raise RuntimeError(f"Disease filename is reserved on Windows: {name}")
    return stem


def load_expected(workspace: Path) -> tuple[list[dict[str, object]], Path, Path]:
    index_path = workspace / INDEX_RELATIVE
    template_path = workspace / TEMPLATE_RELATIVE
    if not index_path.is_file():
        raise RuntimeError(f"Missing disease index: {index_path}")
    if not template_path.is_file():
        raise RuntimeError(f"Missing disease template: {template_path}")
    # Read the template so the operation is explicitly bound to this template.
    # Its content is deliberately not copied into the cards in this phase.
    template_path.read_bytes()

    source = json.loads(index_path.read_text(encoding="utf-8"))
    diseases = source.get("diseases")
    if not isinstance(diseases, list) or len(diseases) != EXPECTED_DISEASE_COUNT:
        raise RuntimeError(
            f"Expected {EXPECTED_DISEASE_COUNT} diseases, found "
            f"{len(diseases) if isinstance(diseases, list) else 'invalid JSON'}"
        )
    if int(source.get("disease_count", -1)) != EXPECTED_DISEASE_COUNT:
        raise RuntimeError("Disease index count field does not match expected count")
    return diseases, index_path, template_path


def build_mapping(
    diseases: list[dict[str, object]], target: Path
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    seen_names: set[str] = set()
    seen_paths: dict[str, str] = {}
    for disease in diseases:
        name = str(disease["name"])
        part_number = int(disease["part_number"])
        if name in seen_names:
            raise RuntimeError(f"Duplicate disease name: {name}")
        seen_names.add(name)
        if part_number not in SYSTEM_DIRS:
            raise RuntimeError(f"Disease has unsupported system number {part_number}: {name}")
        filename = safe_stem(name) + ".md"
        relative = Path(SYSTEM_DIRS[part_number]) / filename
        collision_key = str(relative).casefold()
        if collision_key in seen_paths:
            raise RuntimeError(
                f"Filename collision: {seen_paths[collision_key]} and {name} -> {relative}"
            )
        seen_paths[collision_key] = name
        rows.append(
            {
                "name": name,
                "part_number": part_number,
                "system_dir": SYSTEM_DIRS[part_number],
                "filename": filename,
                "relative_path": relative,
                "path": target / relative,
            }
        )
    if len(rows) != EXPECTED_DISEASE_COUNT:
        raise RuntimeError("Disease-card mapping count mismatch")
    return rows


def load_registered_content(workspace: Path, target: Path) -> set[Path]:
    registered: set[Path] = set()
    for relative_manifest in REGISTERED_CONTENT_MANIFESTS:
        manifest_path = workspace / relative_manifest
        if not manifest_path.is_file():
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        cards = manifest.get("cards", {})
        if not isinstance(cards, dict):
            raise RuntimeError(f"Invalid registered-card manifest: {manifest_path}")
        for relative_card in cards:
            card_path = workspace / Path(str(relative_card))
            try:
                card_path.resolve().relative_to(target.resolve())
            except ValueError as exc:
                raise RuntimeError(
                    f"Registered card is outside disease-card target: {relative_card}"
                ) from exc
            registered.add(card_path)
    return registered


def audit_state(
    target: Path,
    rows: list[dict[str, object]],
    registered_content: set[Path],
) -> dict[str, object]:
    expected_paths = {Path(row["path"]) for row in rows}
    existing_files = set(target.rglob("*")) if target.is_dir() else set()
    existing_files = {path for path in existing_files if path.is_file()}
    expected_dirs = {target / name for name in SYSTEM_DIRS.values()}
    existing_dirs = set(target.iterdir()) if target.is_dir() else set()
    existing_dirs = {path for path in existing_dirs if path.is_dir()}
    nonempty = {path for path in expected_paths if path.is_file() and path.stat().st_size}
    registered_nonempty = nonempty & registered_content
    unregistered_nonempty = nonempty - registered_content
    return {
        "expected_cards": len(expected_paths),
        "expected_system_dirs": len(expected_dirs),
        "existing_expected_cards": len(expected_paths & existing_files),
        "missing_cards": len(expected_paths - existing_files),
        "unexpected_files": len(existing_files - expected_paths),
        "unexpected_dirs": len(existing_dirs - expected_dirs),
        "nonempty_expected_cards": len(nonempty),
        "registered_nonempty_cards": len(registered_nonempty),
        "unregistered_nonempty_cards": len(unregistered_nonempty),
    }


def create_cards(
    target: Path,
    rows: list[dict[str, object]],
    registered_content: set[Path],
) -> int:
    state = audit_state(target, rows, registered_content)
    if state["unexpected_files"] or state["unexpected_dirs"]:
        raise RuntimeError(
            "Target contains unexpected files or directories; refusing to mix card sets"
        )
    for row in rows:
        path = Path(row["path"])
        if path.is_file() and path.stat().st_size and path not in registered_content:
            raise RuntimeError(f"Existing disease card is not empty: {path}")
    target.mkdir(parents=True, exist_ok=True)
    for dirname in SYSTEM_DIRS.values():
        (target / dirname).mkdir(exist_ok=True)
    changed = 0
    for row in rows:
        path = Path(row["path"])
        if path.exists():
            continue
        # Exclusive creation protects against accidental overwrite.
        with path.open("xb"):
            pass
        changed += 1
    return changed


def verify(
    target: Path,
    rows: list[dict[str, object]],
    registered_content: set[Path],
) -> dict[str, object]:
    state = audit_state(target, rows, registered_content)
    failures = {
        key: state[key]
        for key in (
            "missing_cards",
            "unexpected_files",
            "unexpected_dirs",
            "unregistered_nonempty_cards",
        )
        if state[key]
    }
    missing_dirs = [
        name for name in SYSTEM_DIRS.values() if not (target / name).is_dir()
    ]
    if missing_dirs:
        failures["missing_system_dirs"] = missing_dirs
    if failures:
        raise RuntimeError(f"Disease-card verification failed: {failures}")
    return state


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--audit", action="store_true")
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--verify-only", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    workspace = Path(__file__).resolve().parent.parent
    target = workspace / TARGET_DIR
    diseases, index_path, template_path = load_expected(workspace)
    rows = build_mapping(diseases, target)
    registered_content = load_registered_content(workspace, target)
    counts = Counter(str(row["system_dir"]) for row in rows)
    report: dict[str, object] = {
        "source_disease_index": str(index_path),
        "source_disease_index_sha256": sha256_file(index_path),
        "template": str(template_path),
        "template_sha256": sha256_file(template_path),
        "template_content_copied": False,
        "cards": len(rows),
        "system_counts": dict(counts),
        "renamed_for_windows": SAFE_NAME_OVERRIDES,
    }
    if args.audit:
        report.update(audit_state(target, rows, registered_content))
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
        print("DISEASE_CARD_AUDIT_OK")
        return 0
    changed = create_cards(target, rows, registered_content) if args.write else 0
    report.update(verify(target, rows, registered_content))
    report["changed_files"] = changed
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    print("DISEASE_CARD_VERIFY_OK")
    if args.verify_only:
        print("VERIFY_ONLY_OK")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        raise SystemExit(1)
