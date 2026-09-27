#!/usr/bin/env python3
"""Build a deterministic, evidence-preserving Zircon name crosswalk."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import subprocess
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

CATEGORIES = ("items", "monsters", "npcs", "magics", "maps")
SCHEMA_VERSION = 2
GENERATOR_VERSION = 4

SPECS = {
    "items": {
        "table": "ItemInfo", "name": "ItemName", "site_group": "items", "route": "item",
        "source_fields": ("ItemType", "RequiredClass", "RequiredGender", "Shape", "Image", "Durability", "Price", "Weight"),
        "site_fields": ("category", "type_zh", "class", "img"), "asset": "img/items",
    },
    "monsters": {
        "table": "MonsterInfo", "name": "MonsterName", "site_group": "monsters", "route": "monster",
        "source_fields": ("Image", "Level", "AI", "Experience", "Undead", "CanPush", "CanTame", "IsBoss", "Flag"),
        "site_fields": ("level", "boss", "undead", "tame", "img"), "asset": "img/monsters",
    },
    "npcs": {
        "table": "NPCInfo", "name": "NPCName", "site_group": "npcs", "route": "npc",
        "source_fields": ("Region", "Image", "FaceImage", "MapIcon", "RegionName", "EntryPage"),
        "site_fields": ("map", "icon", "face", "img", "face_img"), "asset": "img/npcs",
    },
    "magics": {
        "table": "MagicInfo", "name": "Name", "site_group": "skills", "route": "skill",
        "source_fields": ("Magic", "Class", "School", "Property", "Icon", "MinBasePower", "MaxBasePower", "Description"),
        "site_fields": ("klass", "school", "type", "icon", "img"), "asset": "img/skills",
    },
    "maps": {
        "table": "MapInfo", "name": "Description", "name_aliases": ("PlayerDescription",),
        "site_group": "maps", "route": "map",
        "source_fields": ("FileName", "PlayerDescription", "ServerDescription", "MiniMap", "Light", "Weather", "Fight", "CanHorse"),
        "site_fields": ("file", "w", "h", "env", "ver"), "asset": "thumb",
    },
}

STATUS_LABELS = {
    "conflict": "映射或身份冲突",
    "missing_translation": "缺少中文名",
    "suspected_mismatch": "百科译名存在差异·待核",
    "suspected_untranslated": "疑似未汉化",
    "translation_agreement_candidate": "与百科译名一致·待确认",
    "needs_evidence": "证据不足待核",
    "source_unlinked": "Zircon 条目未能对应百科",
    "mapping_unlinked": "汉化键未能对应当前 System.db",
    "wiki_unlinked": "百科条目未能对应当前 System.db",
}


def normalize_candidate(value: object) -> str:
    """Normalize only for candidate recall; never use this to confirm identity."""
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return "".join(ch for ch in text if not ch.isspace() and not unicodedata.category(ch).startswith("P"))


def _clean_value(value: object) -> object:
    if isinstance(value, dict):
        return {str(k): _clean_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clean_value(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _pick(record: dict, fields: tuple[str, ...]) -> dict:
    return {field: _clean_value(record[field]) for field in fields if field in record and record[field] is not None}


def _display(value: object) -> str | None:
    if value is None:
        return None
    text = html.unescape(str(value))
    return text if text.strip() else None


def _english_unchanged(key: str, zh: str) -> bool:
    if not re.search(r"[A-Za-z]", key) or re.search(r"[\u3400-\u9fff]", key):
        return False
    return html.unescape(zh) == key


def _url_for(route: str, value: object, suffix: str = ".html") -> str:
    segment = quote(str(value), safe="-_.~")
    return f"/{route}/{segment}{suffix}"


def _local_file(root: Path, url: str | None) -> Path | None:
    if not url:
        return None
    parts = urlsplit(url)
    if parts.scheme or parts.netloc:
        return None
    relative = unquote(parts.path).lstrip("/")
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        return None
    return path


def _exists(root: Path, url: str | None) -> bool:
    path = _local_file(root, url)
    return path is not None and path.is_file()


def _site_page(category: str, entry: dict, map_file: str | None = None) -> str:
    spec = SPECS[category]
    if category == "maps":
        return _url_for("map", map_file or (str(entry.get("file") or "") + ".map"))
    key = entry.get("id")
    slug = entry.get("name") if category == "monsters" else key
    return _url_for(spec["route"], slug)


def _site_image(category: str, entry: dict, root: Path, map_file: str | None = None) -> str:

    if category == "maps":
        filename = map_file or (str(entry.get("file") or "") + ".map")
        return f"/thumb/{quote(filename, safe='-_.~')}.png"
    if category == "npcs":
        entity_id = quote(str(entry.get("id", "")), safe="-_.~")
        face = f"/img/npcs_face/{entity_id}.png"
        body = f"/img/npcs/{entity_id}.png"
        return face if _exists(root, face) else body
    board = SPECS[category]["asset"]
    entity_id = quote(str(entry.get("id", "")), safe="-_.~")
    return f"/{board}/{entity_id}.png"


def _site_entry_view(category: str, entry: dict, root: Path, route_count: Counter, map_file: str | None = None) -> dict:
    page_url = _site_page(category, entry, map_file)
    image_url = _site_image(category, entry, root, map_file)
    page_exists = _exists(root, page_url)
    image_exists = _exists(root, image_url)
    ambiguous_route = route_count[page_url] > 1
    return {
        "entity_id": _clean_value(entry.get("id")),
        "name": _clean_value(entry.get("name")),
        "zh": _clean_value(entry.get("zh")),
        "translation_source": entry.get("_translation_source") or (
            "data/wiki_data_v2.json" if _display(entry.get("zh")) else None
        ),
        "attributes": _pick(entry, SPECS[category]["site_fields"]),
        "page_url": page_url if page_exists and not ambiguous_route else None,
        "page_url_candidate": page_url,
        "page_exists": page_exists,
        "page_route_ambiguous": ambiguous_route,
        "candidate_page_urls": [page_url] if page_exists and ambiguous_route else [],
        "image_url": image_url,
        "image_exists": image_exists,
        "visual_status": "image_available_not_reviewed" if image_exists else "image_unavailable",
    }


def _map_file_index(wiki_data: dict) -> dict[str, list[dict]]:
    result: dict[str, list[dict]] = defaultdict(list)
    for entry in wiki_data.get("ei_maps", []):
        name = str(entry.get("name") or "")
        stem = name[:-4] if name.casefold().endswith(".map") else name
        result[stem.casefold()].append(entry)
    return result


def _site_entries(category: str, wiki_data: dict) -> list[dict]:
    if category == "maps":
        return list(wiki_data.get("ei_maps", []))
    return list(wiki_data.get(SPECS[category]["site_group"], []))


def _sprite_comparison(category: str, source: dict, site: dict) -> tuple[bool, list[dict]]:
    comparisons: list[tuple[object, object, str]] = []
    if category == "items":
        image = (site.get("img") or {}).get("frame") if isinstance(site.get("img"), dict) else None
        comparisons.append((source.get("Image"), image, "ItemInfo.Image ↔ wiki_data_v2.img.frame"))
    elif category == "magics":
        image = site.get("icon")
        if image is None and isinstance(site.get("img"), dict):
            image = site["img"].get("frame")
        comparisons.append((source.get("Icon"), image, "MagicInfo.Icon ↔ wiki_data_v2.icon/img.frame"))
    elif category == "npcs":
        comparisons.extend((
            (source.get("Image"), site.get("icon"), "NPCInfo.Image ↔ wiki_data_v2.icon"),
            (source.get("FaceImage"), site.get("face"), "NPCInfo.FaceImage ↔ wiki_data_v2.face"),
        ))
    mismatches = []
    compared = False
    for source_value, site_value, evidence in comparisons:
        if source_value is None or site_value is None or str(source_value) == "None" or str(site_value) == "None":
            continue
        compared = True
        if str(source_value) != str(site_value):
            mismatches.append({"source": _clean_value(source_value), "site": _clean_value(site_value), "fields": evidence})
    return compared, mismatches


def _candidate_keys(key: str, translations: dict) -> list[dict]:
    normalized = normalize_candidate(key)
    if not normalized:
        return []
    candidates = []
    for candidate, value in translations.items():
        if candidate != key and normalize_candidate(candidate) == normalized:
            candidates.append({
                "english_key": candidate,
                "zh_raw": _clean_value(value.get("zh")),
                "ja_raw": _clean_value(value.get("ja")),
                "method": "normalized_candidate_recall_only",
            })
    return sorted(candidates, key=lambda candidate: candidate["english_key"])


def _site_candidate_views(category: str, entries: list[dict], root: Path, route_count: Counter,
                          map_files: dict[str, list[dict]] | None = None) -> list[dict]:
    views = []
    for entry in entries:
        map_file = None
        if category == "maps":
            value = str(entry.get("file") or entry.get("name") or "")
            stem = value[:-4] if value.casefold().endswith(".map") else value
            candidates = (map_files or {}).get(stem.casefold(), [])
            map_file = str(candidates[0].get("name")) if len(candidates) == 1 else (
                value if value.casefold().endswith(".map") else value + ".map"
            )
        views.append(_site_entry_view(category, entry, root, route_count, map_file))
    return views


def _translation_flags(mapping: dict | None, site: dict | None, key: str) -> list[str]:
    zh_value = mapping.get("zh_raw") if mapping else None
    if not _display(zh_value):
        return ["missing"]
    zh = str(zh_value)
    flags = []
    site_zh = _display(site.get("zh")) if site else None
    if site_zh:
        flags.append("agrees_with_encyclopedia" if html.unescape(zh) == site_zh else "differs_from_encyclopedia")
    else:
        flags.append("unverified")
    if _english_unchanged(key, zh):
        flags.append("suspected_untranslated")
    return flags


def _translation_assessment(mapping: dict | None, site: dict | None, key: str) -> str:
    flags = _translation_flags(mapping, site, key)
    if "differs_from_encyclopedia" in flags:
        return "suspected_mismatch"
    if "missing" in flags:
        return "missing"
    if "suspected_untranslated" in flags:
        return "suspected_untranslated"
    if "agrees_with_encyclopedia" in flags:
        return "agrees_with_encyclopedia"
    return "unverified"

def _status(identity_status: str, translation_assessment: str, issues: list[str], kind: str) -> str:
    if kind == "mapping_key":
        return "mapping_unlinked"
    if kind == "wiki_entity":
        return "wiki_unlinked"
    if identity_status == "conflict" or any(issue in issues for issue in (
        "mapping_key_fanout", "multiple_mapping_keys_for_entity", "sprite_attribute_conflict",
        "multiple_site_candidates", "multiple_map_file_candidates",
    )):
        return "conflict"
    if translation_assessment == "missing":
        return "missing_translation"
    if translation_assessment == "suspected_mismatch":
        return "suspected_mismatch"
    if translation_assessment == "suspected_untranslated":
        return "suspected_untranslated"
    if identity_status != "matched":
        return "source_unlinked" if identity_status == "unmatched" else "needs_evidence"
    if translation_assessment == "agrees_with_encyclopedia":
        return "translation_agreement_candidate"
    return "needs_evidence"


def _evidence(source: dict | None, mapping: dict | None, wiki: dict | None, identity: dict) -> list[dict]:
    evidence = []
    if source:
        evidence.append({
            "source": "data/wiki_all.json",
            "locator": f"{source['table']}[Index={source['index']}]",
            "fields": ["Index", source["name_field"]],
        })
    if mapping:
        evidence.append({
            "source": "Zircon/GodotClient/translations/db_names.json",
            "locator": mapping["english_key"],
            "fields": ["zh", "ja"],
            "status": "exact_key_found" if mapping["source_entry_present"] else "exact_key_missing",
        })
    if wiki:
        evidence.append({
            "source": wiki.get("translation_source") or (
                "published EI map file index" if identity["method"] == "case_insensitive_map_filename_and_page"
                else "data/wiki_data_v2.json"
            ),
            "locator": wiki.get("page_url") or wiki.get("page_url_candidate"),
            "method": identity["method"],
        })
        if wiki.get("image_url"):
            evidence.append({
                "source": wiki["image_url"],
                "method": "visual_hint_only_not_automatically_assessed",
            })
    return evidence


def _mapping_view(key: str, entry: dict | None, related_rows: list[dict]) -> dict:
    return {
        "english_key": key,
        "zh_raw": _clean_value(entry.get("zh")) if entry else None,
        "zh_display": _display(entry.get("zh")) if entry else None,
        "ja_raw": _clean_value(entry.get("ja")) if entry else None,
        "english_key_entity_count": len(related_rows),
        "related_indices": sorted(row.get("Index") for row in related_rows if row.get("Index") is not None),
        "source_group": None,
        "source_entry_present": entry is not None,
    }


def _record_id(category: str, kind: str, identifier: object, name: object = None) -> str:
    suffix = str(identifier)
    if name is not None:
        suffix += ":" + hashlib.sha256(str(name).encode("utf-8")).hexdigest()[:8]
    return f"{category}:{kind}:{suffix}"

def _supplemental_map_record(entry: dict, index: int, root: Path, route_count: Counter,
                            map_files: dict[str, list[dict]], translations: dict) -> dict:
    value = str(entry.get("file") or "")
    stem = value[:-4] if value.casefold().endswith(".map") else value
    file_candidates = map_files.get(stem.casefold(), [])
    map_file = str(file_candidates[0].get("name")) if len(file_candidates) == 1 else (
        value if value.casefold().endswith(".map") else value + ".map"
    )
    site_view = _site_entry_view("maps", entry, root, route_count, map_file)
    name = str(entry.get("name") or "")
    mapping = translations.get(name)
    candidates = ([{
        "english_key": name,
        "zh_raw": _clean_value(mapping.get("zh")),
        "ja_raw": _clean_value(mapping.get("ja")),
        "method": "name_only_candidate_not_identity_confirmation",
    }] if mapping else [])
    return {
        "record_id": _record_id("maps", "wiki_supplemental",
                                f"{entry.get('id', 'missing-id')}:{index}", name),
        "category": "maps", "kind": "wiki_supplemental", "status": "wiki_unlinked",
        "status_label": STATUS_LABELS["wiki_unlinked"], "source": None, "translation": None,
        "wiki": site_view, "candidate_wiki": [], "candidate_mapping_keys": candidates,
        "identity": {"status": "unmatched",
                     "method": "supplemental_map_record_not_linked_to_systemdb_row",
                     "confidence": "none"},
        "translation_assessment": "unverified",
        "issues": ["supplemental_map_record_not_linked_to_current_table"],
        "confidence": "none", "review_status": "not_reviewed",
        "visual_evidence": {"status": site_view["visual_status"],
                            "statement": "地图补充记录未建立 Zircon 行对应；缩略图仅供人工辅助。"},
        "evidence": [{"source": "data/wiki_data_v2.json",
                      "locator": f"maps[index={index},file={entry.get('file')}]",
                      "fields": ["id", "name", "zh", "file"]}],
    }


def build_audit(names: dict, wiki_all: dict, wiki_data: dict, site_root: Path | str, provenance: dict) -> dict:
    """Create a deterministic crosswalk without changing any input object or source file."""
    root = Path(site_root).resolve()
    records: list[dict] = []
    summary: dict[str, dict] = {}

    for category in CATEGORIES:
        spec = SPECS[category]
        translations = names.get(category, {})
        rows = list(wiki_all.get(spec["table"], {}).get("rows", []))
        site_entries = _site_entries(category, wiki_data)
        for row in rows:
            if row.get("Index") is None:
                raise ValueError(f"{spec['table']} row is missing stable Index")
        row_indices = [row["Index"] for row in rows]
        if len(row_indices) != len(set(row_indices)):
            raise ValueError(f"{spec['table']} contains duplicate Index values")

        site_by_id_name: dict[tuple[str, str], list[dict]] = defaultdict(list)
        site_by_name: dict[str, list[dict]] = defaultdict(list)
        for entry in site_entries:
            site_by_id_name[(str(entry.get("id")), str(entry.get("name") or ""))].append(entry)
            if isinstance(entry.get("name"), str) and entry["name"]:
                site_by_name[entry["name"]].append(entry)
        map_files = _map_file_index(wiki_data) if category == "maps" else None
        site_maps_by_file: dict[str, list[dict]] = defaultdict(list)
        for entry in wiki_data.get("maps", []):
            if entry.get("file"):
                value = str(entry["file"])
                stem = value[:-4] if value.casefold().endswith(".map") else value
                site_maps_by_file[stem.casefold()].append(entry)
        map_link_names = {
            str(key).casefold(): _clean_value(value)
            for key, value in wiki_data.get("_map_link_names", {}).items()
        }

        route_count = Counter(
            _site_page(category, entry, str(entry.get("name") or "") if category == "maps" else None)
            for entry in site_entries
        )
        matched_site_object_ids: set[int] = set()
        matched_site_detail_object_ids: set[int] = set()
        mapping_rows: dict[str, list[dict]] = defaultdict(list)
        for row in rows:
            key = row.get(spec["name"])
            if isinstance(key, str) and key in translations:
                mapping_rows[key].append(row)

        for row in sorted(rows, key=lambda item: (str(item.get("Index")), str(item.get(spec["name"]) or ""))):
            key = row.get(spec["name"])
            key_text = key if isinstance(key, str) else ""
            translation_entry = translations.get(key_text) if key_text else None
            mapping = _mapping_view(key_text, translation_entry, mapping_rows.get(key_text, []))
            mapping["source_group"] = category
            issues: list[str] = []
            identity = {"status": "unmatched", "method": "no_current_site_candidate", "confidence": "none"}
            matched_site = None
            map_file = None
            candidate_entries: list[dict] = []

            if category == "maps":
                filename = str(row.get("FileName") or "")
                file_candidates = (map_files or {}).get(filename.casefold(), [])
                map_file = str(file_candidates[0].get("name")) if len(file_candidates) == 1 else None
                if len(file_candidates) == 1:
                    map_entry = file_candidates[0]
                    data_candidates = site_maps_by_file.get(filename.casefold(), [])
                    exact_details = [entry for entry in data_candidates
                                     if str(entry.get("id")) == str(row.get("Index"))
                                     and entry.get("name") == key_text]
                    detail_candidates = exact_details if exact_details else data_candidates
                    detail = detail_candidates[0] if len(detail_candidates) == 1 else None
                    if detail:
                        matched_site_detail_object_ids.add(id(detail))
                    if len(detail_candidates) > 1:
                        candidate_entries = detail_candidates
                        issues.append("multiple_supplemental_map_records")
                    matched_site = dict(detail if detail else map_entry)
                    matched_site.update({"file": map_file, "w": map_entry.get("w"), "h": map_entry.get("h")})
                    link_zh = map_link_names.get(filename.casefold())
                    if _display(matched_site.get("zh")):
                        matched_site["_translation_source"] = "data/wiki_data_v2.json"
                    if not _display(matched_site.get("zh")) and _display(link_zh):
                        matched_site["zh"] = link_zh
                        matched_site["_translation_source"] = "data/map_links.json"
                    identity = {"status": "matched", "method": "case_insensitive_map_filename_and_page",
                                "confidence": "high", "evidence": filename}
                    matched_site_object_ids.add(id(map_entry))
                elif file_candidates:
                    issues.append("multiple_map_file_candidates")
                    candidate_entries = file_candidates
                    identity = {"status": "conflict", "method": "ambiguous_map_filename", "confidence": "low"}
                else:
                    identity = {"status": "needs_evidence", "method": "map_filename_candidate_not_found", "confidence": "low"}
            else:
                exact = site_by_id_name.get((str(row.get("Index")), key_text), [])
                if len(exact) == 1:
                    matched_site = exact[0]
                    matched_site_object_ids.add(id(matched_site))
                    identity = {"status": "matched", "method": "stable_id_and_exact_name", "confidence": "high"}
                    compared, mismatches = _sprite_comparison(category, row, matched_site)
                    if mismatches:
                        issues.append("sprite_attribute_conflict")
                        identity = {"status": "conflict", "method": "stable_id_name_but_sprite_attribute_conflict", "confidence": "conflict"}
                        identity["sprite_comparisons"] = mismatches
                    elif compared:
                        identity["sprite_attribute_check"] = "matching"
                elif len(exact) > 1:
                    candidate_entries = exact
                    identity = {"status": "conflict", "method": "multiple_site_records_for_stable_id_and_name", "confidence": "low"}
                    issues.append("multiple_site_candidates")
                else:
                    name_candidates = site_by_name.get(key_text, []) if key_text else []
                    if category == "npcs" and name_candidates:
                        icon_candidates = [entry for entry in name_candidates
                                           if row.get("Image") is not None and entry.get("icon") is not None
                                           and str(row.get("Image")) == str(entry.get("icon"))
                                           and (row.get("FaceImage") is None or entry.get("face") is None
                                                or str(row.get("FaceImage")) == str(entry.get("face")))]
                        if len(icon_candidates) == 1:
                            matched_site = icon_candidates[0]
                            matched_site_object_ids.add(id(matched_site))
                            identity = {"status": "matched", "method": "exact_name_and_icon_identity", "confidence": "medium"}
                        elif icon_candidates or len(name_candidates) > 1:
                            candidate_entries = icon_candidates or name_candidates
                            identity = {"status": "conflict", "method": "ambiguous_name_and_icon_candidates", "confidence": "low"}
                            issues.append("multiple_site_candidates")
                        else:
                            candidate_entries = name_candidates
                            identity = {"status": "needs_evidence", "method": "exact_name_without_icon_confirmation", "confidence": "low"}
                    elif name_candidates:
                        candidate_entries = name_candidates
                        identity = {"status": "needs_evidence", "method": "exact_name_without_stable_id_confirmation", "confidence": "low"}
                    else:
                        normalized = normalize_candidate(key_text)
                        candidate_entries = [entry for entry in site_entries
                                             if normalized and normalize_candidate(entry.get("name")) == normalized]
                        if candidate_entries:
                            identity = {"status": "needs_evidence", "method": "normalized_name_candidate_recall_only", "confidence": "low"}

            if mapping and mapping["english_key_entity_count"] > 1:
                issues.append("mapping_key_fanout")
            if category == "maps":
                alias_key = row.get("PlayerDescription")
                if isinstance(alias_key, str) and alias_key and alias_key != key_text and alias_key in translations:
                    issues.append("multiple_mapping_keys_for_entity")
                    mapping["alternate_mapping_keys"] = [{
                        "english_key": alias_key, "zh_raw": _clean_value(translations[alias_key].get("zh")),
                        "ja_raw": _clean_value(translations[alias_key].get("ja")),
                    }]

            site_view = _site_entry_view(category, matched_site, root, route_count, map_file) if matched_site else {
                "entity_id": None, "name": None, "zh": None, "attributes": {}, "page_url": None,
                "page_url_candidate": None, "page_exists": False, "page_route_ambiguous": False,
                "candidate_page_urls": [], "image_url": None, "image_exists": False,
                "visual_status": "not_available",
            }
            if matched_site:
                if not site_view["page_exists"]:
                    issues.append("detail_page_missing")
                if not site_view["image_exists"]:
                    issues.append("image_missing")
            if candidate_entries:
                candidate_views = _site_candidate_views(category, candidate_entries, root, route_count, map_files)
            else:
                candidate_views = []
            if identity["status"] == "conflict" and "multiple_site_candidates" not in issues:
                issues.append("identity_conflict")

            translation_flags = _translation_flags(mapping, matched_site, key_text)
            assessment = _translation_assessment(mapping, matched_site, key_text)
            if "suspected_untranslated" in translation_flags:
                issues.append("translation_equals_english_identity")
            if "differs_from_encyclopedia" in translation_flags:
                issues.append("translation_disagrees_with_encyclopedia")
            if identity["status"] == "matched" and mapping and mapping["english_key_entity_count"] > 1:
                issues.append("mapping_key_fanout")
            status = _status(identity["status"], assessment, issues, "system_entity")
            record_id = _record_id(category, "system", row.get("Index"))
            source = {
                "table": spec["table"], "index": _clean_value(row.get("Index")),
                "name_field": spec["name"], "english_key": _clean_value(key),
                "attributes": _pick(row, spec["source_fields"]),
                "source_file": "data/wiki_all.json",
            }
            candidate_keys = _candidate_keys(key_text, translations)
            record = {
                "record_id": record_id, "category": category, "kind": "system_entity",
                "status": status, "status_label": STATUS_LABELS[status],
                "source": source, "translation": mapping,
                "wiki": site_view, "candidate_wiki": candidate_views,
                "candidate_mapping_keys": candidate_keys,
                "identity": identity, "translation_assessment": assessment, "translation_flags": translation_flags,
                "issues": sorted(set(issues)), "confidence": identity["confidence"],
                "review_status": "not_reviewed",
                "visual_evidence": {
                    "status": site_view["visual_status"],
                    "statement": "百科图片仅作人工辅助线索；生成器不执行图像识别，也不据此确认身份或译名。",
                },
                "evidence": _evidence(source, mapping, site_view if matched_site else None, identity),
            }
            records.append(record)

        # Preserve dictionary keys that have no exact row in this System.db table.
        for key in sorted(translations):
            if mapping_rows.get(key):
                continue
            entry = translations[key]
            candidate_rows = []
            normalized = normalize_candidate(key)
            for row in rows:
                searchable = [row.get(spec["name"])]
                searchable.extend(row.get(alias) for alias in spec.get("name_aliases", ()))
                if any(normalized and normalize_candidate(value) == normalized for value in searchable if value is not None):
                    candidate_rows.append({"index": _clean_value(row.get("Index")), "english_key": _clean_value(row.get(spec["name"]))})
            site_candidates = [site for site in site_entries
                               if site.get("name") == key or normalize_candidate(site.get("name")) == normalized]
            views = _site_candidate_views(category, site_candidates, root, route_count, map_files)
            mapping = _mapping_view(key, entry, [])
            mapping["source_group"] = category
            records.append({
                "record_id": _record_id(category, "mapping", hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]),
                "category": category, "kind": "mapping_key", "status": "mapping_unlinked",
                "status_label": STATUS_LABELS["mapping_unlinked"], "source": None,
                "translation": mapping, "wiki": {"entity_id": None, "name": None, "zh": None,
                    "attributes": {}, "page_url": None, "page_url_candidate": None, "page_exists": False,
                    "page_route_ambiguous": False, "candidate_page_urls": sorted({view["page_url_candidate"] for view in views if view["page_url_candidate"]}),
                    "image_url": None, "image_exists": False, "visual_status": "not_available"},
                "candidate_wiki": views, "candidate_mapping_keys": [],
                "candidate_system_rows": candidate_rows,
                "identity": {"status": "unmatched", "method": "dictionary_key_not_found_in_table; normalized_candidates_are_recall_only", "confidence": "none"},
                "translation_assessment": "unverified", "issues": ["mapping_key_not_found_in_current_table"],
                "confidence": "none", "review_status": "not_reviewed",
                "visual_evidence": {"status": "not_available", "statement": "未建立实体身份对应。"},
                "evidence": [{"source": "Zircon/GodotClient/translations/db_names.json", "locator": key,
                              "fields": ["zh", "ja"]}],
            })

        # Keep every website entity not linked by a stable ID/name or map filename.
        for entry in sorted(site_entries, key=lambda item: (str(item.get("id")), str(item.get("name") or ""))):
            if id(entry) in matched_site_object_ids:
                continue
            if category == "maps":
                map_file = str(entry.get("name") or "") or None
            site_view = _site_entry_view(category, entry, root, route_count, map_file)
            name = str(entry.get("name") or "")
            mapping_candidate = translations.get(name)
            candidate_mapping = []
            if mapping_candidate:
                candidate_mapping.append({"english_key": name, "zh_raw": _clean_value(mapping_candidate.get("zh")),
                                          "ja_raw": _clean_value(mapping_candidate.get("ja")),
                                          "method": "name_only_candidate_not_identity_confirmation"})
            record_id = _record_id(category, "wiki", entry.get("id", "missing-id"), name)
            records.append({
                "record_id": record_id, "category": category, "kind": "wiki_entity", "status": "wiki_unlinked",
                "status_label": STATUS_LABELS["wiki_unlinked"], "source": None, "translation": None,
                "wiki": site_view, "candidate_wiki": [], "candidate_mapping_keys": candidate_mapping,
                "identity": {"status": "unmatched", "method": "no_current_systemdb_identity_link", "confidence": "none"},
                "translation_assessment": "unverified", "issues": ["website_entity_not_linked_to_current_table"],
                "confidence": "none", "review_status": "not_reviewed",
                "visual_evidence": {"status": site_view["visual_status"],
                    "statement": "百科图片仅作人工辅助线索；未建立 Zircon 身份对应。"},
                "evidence": [{"source": "data/wiki_data_v2.json", "locator": f"{spec['site_group']}[id={entry.get('id')}]",
                              "fields": ["id", "name", "zh"]}],
            })

        if category == "maps":
            records.extend(
                _supplemental_map_record(entry, index, root, route_count, map_files or {}, translations)
                for index, entry in enumerate(wiki_data.get("maps", []))
                if id(entry) not in matched_site_detail_object_ids
            )
        category_records = [record for record in records if record["category"] == category]
        system_records = [record for record in category_records if record["kind"] == "system_entity"]
        summary[category] = {
            "system_entities": len(rows),
            "translation_keys": len(translations),
            "website_entities": len(site_entries),
            "supplemental_website_records": len(wiki_data.get("maps", [])) if category == "maps" else 0,
            "unlinked_supplemental_website_records": sum(
                record["kind"] == "wiki_supplemental" for record in category_records
            ),
            "identity_matches": sum(record["identity"]["status"] == "matched" for record in system_records),
            "translation_agreements": sum("agrees_with_encyclopedia" in record["translation_flags"] for record in system_records),
            "suspected_mismatches": sum("differs_from_encyclopedia" in record["translation_flags"] for record in system_records),
            "suspected_untranslated": sum("suspected_untranslated" in record["translation_flags"] for record in system_records),
            "missing_zh": sum("missing" in record["translation_flags"] for record in system_records),
            "unverified_translations": sum("unverified" in record["translation_flags"] for record in system_records),
            "mapping_conflicts": sum("mapping_key_fanout" in record["issues"] or "multiple_mapping_keys_for_entity" in record["issues"]
                                      for record in system_records),
            "sprite_conflicts": sum("sprite_attribute_conflict" in record["issues"] for record in system_records),
            "source_entities_without_confirmed_site": sum(record["identity"]["status"] != "matched" for record in system_records),
            "unlinked_translation_keys": sum(record["kind"] == "mapping_key" for record in category_records),
            "unlinked_website_entities": sum(record["kind"] == "wiki_entity" for record in category_records),
            "awaiting_visual_review": sum(record["visual_evidence"]["status"] == "image_available_not_reviewed" for record in system_records),
            "awaiting_identity_evidence": sum(record["identity"]["status"] != "matched" for record in system_records),
            "confirmed_correct": 0,
        }

    records.sort(key=lambda record: (
        CATEGORIES.index(record["category"]),
        {"system_entity": 0, "mapping_key": 1, "wiki_entity": 2, "wiki_supplemental": 3}[record["kind"]],
        str((record.get("source") or {}).get("index", "")),
        str((record.get("translation") or {}).get("english_key", "")),
        record["record_id"],
    ))
    final_provenance = json.loads(json.dumps(provenance, ensure_ascii=False, sort_keys=True))
    fingerprint_input = {
        "generator_version": GENERATOR_VERSION,
        "provenance": final_provenance,
        "category_counts": {category: summary[category]["system_entities"] for category in CATEGORIES},
    }
    fingerprint = hashlib.sha256(json.dumps(fingerprint_input, ensure_ascii=False, sort_keys=True,
                                             separators=(",", ":")).encode("utf-8")).hexdigest()
    return {
        "schema_version": SCHEMA_VERSION,
        "generator_version": GENERATOR_VERSION,
        "build_fingerprint": fingerprint,
        "provenance": final_provenance,
        "review_policy": {
            "identity": "Exact IDs/table fields and independent page/image attributes establish candidates; normalized names are recall only.",
            "visual": "No automated visual recognition. Every image remains an unreviewed hint until a human checks it.",
            "unmatched": "Unlinked entries are unresolved evidence gaps, not proof that either side is exclusive or incorrect.",
        },
        "status_labels": STATUS_LABELS,
        "summary": summary,
        "records": records,
    }


def build_link_index(audit: dict) -> list[dict]:
    """Return a compact, lossless per-page index for list and detail page decoration."""
    index = []
    for record in audit["records"]:
        wiki = record["wiki"]
        paths = []
        if wiki.get("page_url"):
            relation = ("unmatched_site_record" if record["kind"] in ("wiki_entity", "wiki_supplemental") else
                        "matched" if record["identity"]["status"] == "matched" else "candidate")
            paths.append((wiki["page_url"], relation))
        for path in wiki.get("candidate_page_urls", []):
            if path:
                paths.append((path, "candidate"))
        if wiki.get("page_url_candidate") and not paths:
            paths.append((wiki["page_url_candidate"], "candidate"))
        for page_url, relation in sorted(set(paths)):
            index.append({
                "page_url": page_url,
                "page_relation": relation,
                "record_id": record["record_id"],
                "category": record["category"],
                "kind": record["kind"],
                "status": record["status"],
                "status_label": record["status_label"],
                "identity_status": record["identity"]["status"],
                "translation_assessment": record["translation_assessment"],
                "identity_method": record["identity"]["method"],
                "source_index": (record.get("source") or {}).get("index"),
                "english_key": (record.get("source") or {}).get("english_key") or (record.get("translation") or {}).get("english_key"),
                "zh_raw": (record.get("translation") or {}).get("zh_raw"),
                "translation_flags": record.get("translation_flags", []),
                "wiki_name": wiki.get("name"),
                "wiki_zh": wiki.get("zh"),
                "image_url": wiki.get("image_url"),
                "image_exists": wiki.get("image_exists", False),
                "page_exists": wiki.get("page_exists", False),
            })
    return sorted(index, key=lambda entry: (entry["page_url"], entry["category"], entry["record_id"], entry["page_relation"]))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def repository_provenance(site_root: Path, zircon_repo: Path, names_path: Path,
                          wiki_all_path: Path, wiki_data_path: Path, map_links_path: Path,
                          names: dict, wiki_data: dict) -> dict:
    names_path = names_path.resolve()
    zircon_repo = zircon_repo.resolve()
    relative_names = names_path.relative_to(zircon_repo).as_posix()
    file_commit = _git(zircon_repo, "log", "-1", "--format=%H", "--", relative_names)
    file_commit_time = _git(zircon_repo, "log", "-1", "--format=%cI", "--", relative_names)
    source_mtime = datetime.fromtimestamp(names_path.stat().st_mtime).astimezone().isoformat(timespec="microseconds")
    source_status = _git(zircon_repo, "status", "--porcelain", "--", relative_names)
    source = {
        "repository": "Zircon",
        "repository_revision": _git(zircon_repo, "rev-parse", "HEAD"),
        "source_branch": _git(zircon_repo, "branch", "--show-current"),
        "file": relative_names,
        "file_commit": file_commit,
        "file_commit_time": file_commit_time,
        "git_blob": _git(zircon_repo, "hash-object", str(names_path)),
        "sha256": _sha256(names_path),
        "working_tree_modified": bool(source_status),
        "file_mtime_observed": source_mtime,
        "timestamp_note": "db_names.json has no embedded generated_at; mtime is an observation, commit time is reproducible provenance.",
        "category_counts": {category: len(names.get(category, {})) for category in CATEGORIES},
    }
    files = {
        "wiki_all.json": wiki_all_path,
        "wiki_data_v2.json": wiki_data_path,
        "map_links.json": map_links_path,
    }
    wiki = {"source_files": {name: {"sha256": _sha256(path), "path": f"data/{name}"} for name, path in files.items()}}
    meta = wiki_data.get("_meta", {})
    if meta.get("generated_at"):
        wiki["wiki_data_generated_at"] = meta["generated_at"]
    return {"zircon": source, "wiki": wiki, "builder": {"path": "scripts/build_zircon_name_audit.py", "version": GENERATOR_VERSION}}


def _write_json(path: Path, value: object, compact: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    separators = (",", ":") if compact else None
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=None if compact else 2,
                               separators=separators) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zircon-repo", default=os.environ.get("ZIRCON_REPO"), help="Local read-only Zircon Git checkout")
    parser.add_argument("--site-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--names", type=Path, help="Defaults to GodotClient/translations/db_names.json in --zircon-repo")
    parser.add_argument("--output", type=Path, help="Defaults to data/zircon_name_audit.json under --site-root")
    args = parser.parse_args()
    if not args.zircon_repo:
        parser.error("pass --zircon-repo or set ZIRCON_REPO")
    root = args.site_root.resolve()
    zircon_repo = Path(args.zircon_repo).resolve()
    names_path = (args.names or (zircon_repo / "GodotClient/translations/db_names.json")).resolve()
    wiki_all_path = root / "data/wiki_all.json"
    wiki_data_path = root / "data/wiki_data_v2.json"
    map_links_path = root / "data/map_links.json"
    names = json.loads(names_path.read_text(encoding="utf-8"))
    wiki_all = json.loads(wiki_all_path.read_text(encoding="utf-8"))
    wiki_data = json.loads(wiki_data_path.read_text(encoding="utf-8"))
    wiki_data["_map_link_names"] = json.loads(map_links_path.read_text(encoding="utf-8")).get("names", {})
    provenance = repository_provenance(root, zircon_repo, names_path, wiki_all_path, wiki_data_path, map_links_path, names, wiki_data)
    audit = build_audit(names, wiki_all, wiki_data, root, provenance)
    output = (args.output or root / "data/zircon_name_audit.json").resolve()
    _write_json(output, audit)
    _write_json(output.with_name("zircon_name_index.json"), build_link_index(audit), compact=True)
    print(f"Audit rows: {len(audit['records'])}")
    for category in CATEGORIES:
        print(f"{category}: {json.dumps(audit['summary'][category], ensure_ascii=False, sort_keys=True)}")
    print(f"Build fingerprint: {audit['build_fingerprint']}")
    print(f"Wrote {output} and {output.with_name('zircon_name_index.json')}")


if __name__ == "__main__":
    main()
