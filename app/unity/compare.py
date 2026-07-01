from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import platform
import subprocess
from typing import Any

from app.unity.report import write_html_report


class UnityCompareError(Exception):
    pass


@dataclass(frozen=True)
class CompareArtifacts:
    report: dict[str, Any]
    json_path: Path
    html_path: Path


SDK_PATTERNS: dict[str, list[str]] = {
    "Unity": ["UnityEngine", "Unity."],
    "Firebase": ["Firebase", "Google.Firebase"],
    "Facebook": ["Facebook", "FB."],
    "AdMob": ["GoogleMobileAds", "AdMob"],
    "AppsFlyer": ["AppsFlyer"],
    "Adjust": ["com.adjust", "Adjust"],
    "IronSource": ["IronSource"],
    "Bugly": ["Bugly", "com.tencent.bugly"],
    "TalkingData": ["TalkingData"],
    "UMeng": ["Umeng", "com.umeng"],
}

CORE_GAME_DLLS = {"Assembly-CSharp.dll", "Assembly-CSharp-firstpass.dll"}


def compare_dummy_dirs(
    old_dir: Path,
    new_dir: Path,
    output_dir: Path,
    *,
    metadata: Mapping[str, Any] | None = None,
    dll_analyzer_path: Path | None = None,
    timeout_seconds: float = 300.0,
) -> CompareArtifacts:
    analyzer = find_dll_analyzer(dll_analyzer_path)
    if not old_dir.is_dir():
        raise UnityCompareError(f"旧版本 DummyDll 目录不存在: {old_dir}")
    if not new_dir.is_dir():
        raise UnityCompareError(f"新版本 DummyDll 目录不存在: {new_dir}")

    output_dir.mkdir(parents=True, exist_ok=True)
    comparison_results = compare_all_dlls(old_dir, new_dir, analyzer, timeout_seconds)
    meta = dict(metadata or {})
    report = {
        "timestamp": datetime.now().isoformat(),
        "old_directory": str(old_dir),
        "new_directory": str(new_dir),
        "app_name": meta.get("app_name") or meta.get("package_name"),
        "old_version_name": meta.get("old_version_name"),
        "new_version_name": meta.get("new_version_name"),
        "overall_statistics": comparison_results["overall_statistics"],
        "summary": comparison_results["summary"],
        "dll_comparisons": comparison_results["dll_comparisons"],
        "detailed_game_logic_changes": comparison_results["detailed_game_logic_changes"],
    }

    json_path = output_dir / "report.json"
    html_path = output_dir / "report.html"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    write_html_report(report, html_path)
    return CompareArtifacts(report=report, json_path=json_path, html_path=html_path)


def find_dll_analyzer(custom_path: Path | None = None) -> Path:
    if custom_path:
        if custom_path.is_file():
            return custom_path
        raise UnityCompareError(f"指定的 DllAnalyzer 不存在: {custom_path}")
    repo_root = Path(__file__).resolve().parents[2]
    folder = "osx" if platform.system() == "Darwin" else "linux"
    candidate = repo_root / "lib" / "product" / "DllAnalyzer" / folder / "DllAnalyzer"
    if candidate.is_file():
        return candidate
    raise UnityCompareError("找不到 DllAnalyzer，请配置 DLL_ANALYZER_PATH 或放到 lib/product/DllAnalyzer")


def compare_all_dlls(old_dir: Path, new_dir: Path, analyzer: Path, timeout_seconds: float) -> dict[str, Any]:
    old_dlls = {path.name: path for path in old_dir.glob("*.dll")}
    new_dlls = {path.name: path for path in new_dir.glob("*.dll")}
    all_dll_names = sorted(set(old_dlls) | set(new_dlls))

    results: dict[str, Any] = {
        "total_dlls": len(all_dll_names),
        "dll_comparisons": [],
        "summary": {
            "added_dlls": [],
            "removed_dlls": [],
            "changed_dlls": [],
            "unchanged_dlls": [],
            "version_only_changes": [],
            "content_changes": [],
        },
        "detailed_game_logic_changes": None,
        "overall_statistics": {},
    }

    for dll_name in all_dll_names:
        if dll_name not in old_dlls:
            results["summary"]["added_dlls"].append(dll_name)
            results["dll_comparisons"].append({"dll_name": dll_name, "status": "added", "comparison_type": "new"})
            continue
        if dll_name not in new_dlls:
            results["summary"]["removed_dlls"].append(dll_name)
            results["dll_comparisons"].append({"dll_name": dll_name, "status": "removed", "comparison_type": "deleted"})
            continue

        try:
            old_analysis = analyze_dll(old_dlls[dll_name], analyzer, timeout_seconds)
            new_analysis = analyze_dll(new_dlls[dll_name], analyzer, timeout_seconds)
        except UnityCompareError:
            continue

        if dll_name in CORE_GAME_DLLS:
            comparison = compare_dlls(old_analysis, new_analysis)
            comparison["dll_name"] = dll_name
            comparison["comparison_type"] = "detailed"
            if dll_name == "Assembly-CSharp.dll":
                results["detailed_game_logic_changes"] = comparison
            if has_significant_changes(comparison):
                results["summary"]["changed_dlls"].append(dll_name)
                results["summary"]["content_changes"].append(dll_name)
            else:
                results["summary"]["unchanged_dlls"].append(dll_name)
            results["dll_comparisons"].append(comparison)
            continue

        old_version = extract_dll_version(old_analysis)
        new_version = extract_dll_version(new_analysis)
        if old_version and new_version:
            comparison = compare_dll_with_version(old_version, new_version, dll_name)
            if comparison["has_changes"]:
                results["summary"]["changed_dlls"].append(dll_name)
                results["summary"]["version_only_changes"].append(dll_name)
            else:
                results["summary"]["unchanged_dlls"].append(dll_name)
        else:
            comparison = compare_dlls(old_analysis, new_analysis)
            comparison["dll_name"] = dll_name
            comparison["comparison_type"] = "detailed_no_version"
            if has_significant_changes(comparison):
                results["summary"]["changed_dlls"].append(dll_name)
                results["summary"]["content_changes"].append(dll_name)
            else:
                results["summary"]["unchanged_dlls"].append(dll_name)
        results["dll_comparisons"].append(comparison)

    results["overall_statistics"] = calculate_overall_statistics(results)
    return results


def analyze_dll(dll_path: Path, analyzer: Path, timeout_seconds: float) -> dict[str, Any]:
    output_path = dll_path.with_suffix(dll_path.suffix + ".analysis.json")
    try:
        result = subprocess.run(
            [str(analyzer), str(dll_path), str(output_path)],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise UnityCompareError(f"分析 DLL 超时: {dll_path.name}") from exc
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "").strip()
        raise UnityCompareError(f"分析 DLL 失败: {dll_path.name} {message}".strip())
    try:
        return json.loads(output_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise UnityCompareError(f"读取 DLL 分析结果失败: {dll_path.name}") from exc
    finally:
        output_path.unlink(missing_ok=True)


def extract_dll_version(analysis: Mapping[str, Any]) -> str | None:
    version = analysis.get("Version")
    if version:
        return str(version)
    sdk_versions = analysis.get("SdkVersions") or {}
    if sdk_versions:
        return str(next(iter(sdk_versions.values())))
    return None


def compare_dll_with_version(old_version: str, new_version: str, dll_name: str) -> dict[str, Any]:
    return {
        "dll_name": dll_name,
        "comparison_type": "version",
        "has_changes": old_version != new_version,
        "old_version": old_version,
        "new_version": new_version,
        "change_summary": f"Version: {old_version} → {new_version}" if old_version != new_version else "No version change",
    }


def compare_dlls(old_analysis: Mapping[str, Any], new_analysis: Mapping[str, Any]) -> dict[str, Any]:
    old_classes = {cls["FullName"]: cls for cls in old_analysis.get("Classes", []) if cls.get("FullName")}
    new_classes = {cls["FullName"]: cls for cls in new_analysis.get("Classes", []) if cls.get("FullName")}
    changes: dict[str, Any] = {
        "added_classes": [],
        "removed_classes": [],
        "modified_classes": [],
        "sdk_version_changes": {},
        "statistics": {},
        "changes_summary": {
            "added_classes": 0,
            "removed_classes": 0,
            "modified_classes": 0,
            "sdk_version_changes": 0,
        },
    }

    for class_name in sorted(set(new_classes) - set(old_classes)):
        category = categorize_class(class_name)
        changes["added_classes"].append({"name": class_name, "category": category, "details": new_classes[class_name]})
        bump_stat(changes["statistics"], category, "added")

    for class_name in sorted(set(old_classes) - set(new_classes)):
        category = categorize_class(class_name)
        changes["removed_classes"].append({"name": class_name, "category": category, "details": old_classes[class_name]})
        bump_stat(changes["statistics"], category, "removed")

    for class_name in sorted(set(old_classes) & set(new_classes)):
        old_cls = old_classes[class_name]
        new_cls = new_classes[class_name]
        if is_class_modified(old_cls, new_cls):
            category = categorize_class(class_name)
            changes["modified_classes"].append({"name": class_name, "category": category, "changes": get_class_changes(old_cls, new_cls)})
            bump_stat(changes["statistics"], category, "modified")

    old_sdk_versions = old_analysis.get("SdkVersions") or {}
    new_sdk_versions = new_analysis.get("SdkVersions") or {}
    for key in sorted(set(old_sdk_versions) | set(new_sdk_versions)):
        old_ver = old_sdk_versions.get(key, "Not found")
        new_ver = new_sdk_versions.get(key, "Not found")
        if old_ver != new_ver:
            changes["sdk_version_changes"][key] = {"old": old_ver, "new": new_ver}

    changes["changes_summary"]["added_classes"] = len(changes["added_classes"])
    changes["changes_summary"]["removed_classes"] = len(changes["removed_classes"])
    changes["changes_summary"]["modified_classes"] = len(changes["modified_classes"])
    changes["changes_summary"]["sdk_version_changes"] = len(changes["sdk_version_changes"])
    return changes


def bump_stat(stats: dict[str, dict[str, int]], category: str, key: str) -> None:
    stats.setdefault(category, {"added": 0, "removed": 0, "modified": 0})
    stats[category][key] += 1


def is_class_modified(old_cls: Mapping[str, Any], new_cls: Mapping[str, Any]) -> bool:
    return (
        set(old_cls.get("Methods", [])) != set(new_cls.get("Methods", []))
        or set(old_cls.get("Fields", [])) != set(new_cls.get("Fields", []))
        or set(old_cls.get("Properties", [])) != set(new_cls.get("Properties", []))
    )


def get_class_changes(old_cls: Mapping[str, Any], new_cls: Mapping[str, Any]) -> dict[str, Any]:
    changes: dict[str, Any] = {}
    for source_key, output_key in (("Methods", "methods"), ("Fields", "fields"), ("Properties", "properties")):
        old_values = set(old_cls.get(source_key, []))
        new_values = set(new_cls.get(source_key, []))
        if old_values != new_values:
            changes[output_key] = {"added": sorted(new_values - old_values), "removed": sorted(old_values - new_values)}
    return changes


def has_significant_changes(comparison: Mapping[str, Any]) -> bool:
    if "has_changes" in comparison:
        return bool(comparison["has_changes"])
    return bool(
        comparison.get("added_classes")
        or comparison.get("removed_classes")
        or comparison.get("modified_classes")
        or comparison.get("sdk_version_changes")
    )


def calculate_overall_statistics(results: Mapping[str, Any]) -> dict[str, Any]:
    summary = results["summary"]
    total_dlls = results["total_dlls"]
    changed_count = len(summary["changed_dlls"])
    stats = {
        "total_dlls": total_dlls,
        "changed_dll_count": changed_count,
        "unchanged_dll_count": len(summary["unchanged_dlls"]),
        "added_dll_count": len(summary["added_dlls"]),
        "removed_dll_count": len(summary["removed_dlls"]),
        "total_affected_dlls": len(summary["added_dlls"]) + len(summary["removed_dlls"]) + changed_count,
        "affected_percentage": 0,
        "content_change_count": len(summary["content_changes"]),
        "version_only_change_count": len(summary["version_only_changes"]),
        "game_logic_change_ratio": 0,
        "sdk_change_ratio": 0,
    }
    if total_dlls > 0:
        stats["affected_percentage"] = round(stats["total_affected_dlls"] / total_dlls * 100, 2)
    detailed = results.get("detailed_game_logic_changes")
    if detailed:
        update_info = calculate_update_type(detailed)
        stats["game_logic_change_ratio"] = update_info["game_logic_ratio"]
        stats["sdk_change_ratio"] = update_info["sdk_ratio"]
    return stats


def calculate_update_type(changes: Mapping[str, Any]) -> dict[str, Any]:
    category_totals: dict[str, int] = {}
    total_changes = 0
    for category, counts in changes.get("statistics", {}).items():
        category_total = counts.get("added", 0) + counts.get("removed", 0) + counts.get("modified", 0)
        category_totals[category] = category_total
        total_changes += category_total
    if total_changes == 0:
        return {"type": "no_change", "game_logic_ratio": 0, "sdk_ratio": 0, "total_changes": 0, "category_breakdown": category_totals}
    game_logic_changes = category_totals.get("game_logic", 0)
    sdk_changes = sum(value for key, value in category_totals.items() if key.startswith("sdk_"))
    game_logic_ratio = round(game_logic_changes / total_changes * 100, 2)
    sdk_ratio = round(sdk_changes / total_changes * 100, 2)
    if sdk_ratio > 70:
        update_type = "sdk_update"
    elif game_logic_ratio > 70:
        update_type = "game_logic_update"
    else:
        update_type = "mixed_update"
    return {
        "type": update_type,
        "game_logic_ratio": game_logic_ratio,
        "sdk_ratio": sdk_ratio,
        "total_changes": total_changes,
        "category_breakdown": category_totals,
        "sdk_version_updates": len(changes.get("sdk_version_changes", {})),
    }


def categorize_class(class_name: str) -> str:
    for sdk_name, patterns in SDK_PATTERNS.items():
        if any(pattern in class_name for pattern in patterns):
            return f"sdk_{sdk_name}"
    if class_name.startswith("UnityEngine") or class_name.startswith("Unity."):
        return "unity_engine"
    if class_name.startswith("System."):
        return "system"
    return "game_logic"
