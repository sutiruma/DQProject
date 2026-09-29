#!/usr/bin/env python3
"""
Shared utilities for data contract scripts.
"""

import json
import os

try:
    import yaml
    _YAML_AVAILABLE = True
except ImportError:
    _YAML_AVAILABLE = False


def extract_custom_properties(contract_file: str) -> list:
    """Parse contract file and return its top-level customProperties list."""
    try:
        with open(contract_file, "r", encoding="utf-8") as fh:
            content = fh.read()

        ext = os.path.splitext(contract_file)[1].lower()
        if ext == ".json":
            doc = json.loads(content)
        elif ext in (".yaml", ".yml"):
            if not _YAML_AVAILABLE:
                return []
            doc = yaml.safe_load(content)
        else:
            try:
                doc = json.loads(content)
            except json.JSONDecodeError:
                if _YAML_AVAILABLE:
                    doc = yaml.safe_load(content)
                else:
                    return []

        custom_props = doc.get("customProperties") if isinstance(doc, dict) else None
        if isinstance(custom_props, list):
            return custom_props
    except Exception:
        pass
    return []


def extract_project_id(contract_file: str, fallback: str) -> str:
    """Return the projectId from a contract file's top-level customProperties.

    Looks for:
        customProperties:
          - property: projectId
            value: <uuid>

    Works for both JSON (.json) and YAML (.yaml / .yml) contract files.
    Falls back to `fallback` when:
      - the file cannot be parsed
      - customProperties is absent
      - no entry with property == "projectId" exists

    Args:
        contract_file: Path to the contract file.
        fallback: Value to return when projectId is not found in the file.

    Returns:
        The projectId string from the file, or `fallback`.
    """
    custom_props = extract_custom_properties(contract_file)
    for prop in custom_props:
        if isinstance(prop, dict) and prop.get("property") == "projectId":
            value = prop.get("value")
            if value and isinstance(value, str):
                return value.strip()
    return fallback


def _parse_bool(val) -> bool:
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.strip().lower() in ("true", "1", "yes")
    return False


def extract_target_info(contract_file: str) -> dict:
    """Return target container and DPH metadata from customProperties."""
    custom_props = extract_custom_properties(contract_file)
    props_map = {
        prop.get("property"): prop.get("value")
        for prop in custom_props
        if isinstance(prop, dict) and prop.get("property")
    }

    def _get_str(name: str, default: str = "") -> str:
        v = props_map.get(name)
        return v.strip() if isinstance(v, str) and v.strip() else default

    return {
        "is_dph": _parse_bool(props_map.get("isDPH")),
        "type": _get_str("type", "contract_template"),
        "draft_id": _get_str("draftId"),
        "project_id": _get_str("projectId"),
    }
