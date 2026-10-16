"""Read-only K0 asset validation. This is not a runtime security boundary.

A maintainer must review any rule-baseline change independently. This tool never
refreshes hashes, rewrites a baseline, executes skills, or downloads references.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path, PurePosixPath
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError

SCHEMA_VERSION = "1.0.0"
DRAFT = "https://json-schema.org/draft/2020-12/schema"
CONTRACTS = ("task", "action", "capability", "artifact", "module", "build-profile")
CONTRACT_PATHS = {name: f"contracts/schemas/{name}.schema.json" for name in CONTRACTS}
MANIFEST_PATH = "seed/system-manifest/seed-bundle.json"
RULES_PATH = "seed/rules/baseline.json"
KNOWLEDGE_PATH = "seed/knowledge/bootstrap.json"
SKILLS_PATH = "seed/skills/catalog.json"
CASES_PATH = "tests/fixtures/contracts/cases.json"
TRUSTED_RULESET_VERSION = "1.0.0"
# Independently maintained, not read from the self-declared bundle manifest.
TRUSTED_RULESET_SHA256 = "sha256:00f2178f677ef3c2ed8b449cfe1ab20437bcecc1a000ed68f7bcd54c4c2a94aa"
SPECIFICATION_SUMMARY_VERSION = "1.0.0"
SPECIFICATION_SUMMARY = (
    "K0: six versioned contracts; separate reference knowledge, protected rules, "
    "and declared skills; status/sample metadata/artifact output only; candidate "
    "build remains planned; validation is not proof of semantic safety or OS isolation."
)
AVAILABLE_CAPABILITIES = {
    "system.status.v1", "filesystem.read_sample.v1", "artifact.write.v1"
}
PLANNED_CAPABILITY = "build.candidate.v1"
FORMAT_CHECKER = FormatChecker()


def sha256_bytes(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number: {value}")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object,
                      parse_constant=_reject_constant)


def project_path(root: Path, reference: str) -> Path:
    """Resolve a declared relative file and reject traversal, drives and escapes."""
    if not isinstance(reference, str) or not reference or "\\" in reference or ":" in reference:
        raise ValueError("reference must be a normalized relative POSIX path")
    parts = PurePosixPath(reference).parts
    if reference != PurePosixPath(reference).as_posix() or reference.startswith("/") or ".." in parts or "." in parts or "//" in reference:
        raise ValueError(f"unsafe relative reference: {reference}")
    base = root.resolve()
    candidate = (base / reference).resolve()
    if not candidate.is_relative_to(base):
        raise ValueError(f"reference escapes project root: {reference}")
    return candidate


def _external_refs(value: Any) -> bool:
    if isinstance(value, dict):
        return any(
            (key in {"$ref", "$dynamicRef"} and
             (not isinstance(item, str) or not item.startswith("#"))) or
            _external_refs(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_external_refs(item) for item in value)
    return False


def _validator(schema: Any) -> Draft202012Validator:
    if not isinstance(schema, dict) or _external_refs(schema):
        raise ValueError("schema must be an object without external references")
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FORMAT_CHECKER)


def _errors(schema: Any, payload: Any, label: str) -> list[str]:
    validator = _validator(schema)
    return [
        f"{label}/{('/'.join(map(str, error.absolute_path)) or '<root>')}: {error.message}"
        for error in sorted(validator.iter_errors(payload),
                            key=lambda error: "/".join(map(str, error.absolute_path)))
    ]


def validate_contract(name: str, payload: Any, root: Path | str | None = None) -> list[str]:
    """Return validation errors; an empty list means this contract shape passed."""
    base = Path(root) if root is not None else Path(__file__).resolve().parents[1]
    if name not in CONTRACT_PATHS:
        return [f"unknown contract: {name}"]
    try:
        schema = read_json(project_path(base, CONTRACT_PATHS[name]))
        if schema.get("$schema") != DRAFT or schema.get("additionalProperties") is not False:
            return [f"{name}: expected Draft 2020-12 with closed top-level fields"]
        return _errors(schema, payload, name)
    except (OSError, ValueError, TypeError, KeyError, SchemaError) as exc:
        return [f"{name}: {exc}"]


def _closed(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "additionalProperties": False, "properties": properties,
            "required": list(properties) if required is None else required}


TEXT = {"type": "string", "minLength": 1}
HASH = {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"}
STRINGS = {"type": "array", "items": TEXT, "uniqueItems": True}
MANIFEST_SCHEMA = _closed({
    "schema_version": {"const": SCHEMA_VERSION},
    "bundle_id": {"const": "jarvis.k0.seed"},
    "version": {"const": "1.0.0"},
    "scope": {"const": "K0"},
    "status": {"const": "k0_assets"},
    "specification_summary": _closed({
        "version": {"const": SPECIFICATION_SUMMARY_VERSION}, "text": TEXT,
        "sha256": HASH, "source_refs": STRINGS}),
    "rules_baseline": _closed({
        "path": {"const": RULES_PATH}, "version": {"const": TRUSTED_RULESET_VERSION},
        "sha256": HASH}),
    "contracts": _closed({name: {"const": path} for name, path in CONTRACT_PATHS.items()}),
    "assets": {"type": "array", "minItems": 1, "items": _closed({
        "path": TEXT, "kind": {"enum": ["schema", "knowledge", "rules", "skills", "fixture"]},
        "sha256": HASH})},
    "fixture_index": {"const": CASES_PATH},
    "limitations": {"type": "array", "minItems": 1, "items": TEXT}
})
KNOWLEDGE_SCHEMA = _closed({
    "schema_version": {"const": SCHEMA_VERSION},
    "knowledge_id": {"const": "jarvis.k0.knowledge"},
    "version": {"const": "1.0.0"},
    "authority": {"const": "reference_only"},
    "records": {"type": "array", "minItems": 1, "items": _closed({
        "record_id": TEXT,
        "kind": {"enum": ["original_evidence", "verified_fact", "owner_preference",
                          "hypothesis", "external_untrusted", "simulation", "withdrawn"]},
        "source": TEXT, "version": TEXT, "evidence_ref": TEXT,
        "validity": {"enum": ["design_baseline", "verified", "unverified", "withdrawn"]},
        "scope": TEXT, "owner": TEXT, "privacy": {"const": "local_only"}, "content": TEXT
    })}
})
SKILLS_SCHEMA = _closed({
    "schema_version": {"const": SCHEMA_VERSION},
    "catalog_id": {"const": "jarvis.k0.skills"}, "version": {"const": "1.0.0"},
    "availability_semantics": TEXT,
    "capabilities": {"type": "array", "minItems": 1, "items": {"type": "object"}},
    "skills": {"type": "array", "minItems": 1, "items": _closed({
        "skill_id": TEXT, "version": TEXT, "status": {"enum": ["available", "planned", "disabled"]},
        "capability_refs": {"type": "array", "minItems": 1, "items": TEXT, "uniqueItems": True},
        "description": TEXT
    })}
})
CASES_SCHEMA = _closed({
    "schema_version": {"const": SCHEMA_VERSION},
    "cases": {"type": "array", "minItems": 12, "items": _closed({
        "case_id": TEXT, "contract": {"enum": list(CONTRACTS)},
        "path": TEXT, "valid": {"type": "boolean"}
    })}
})


def _source_errors(root: Path, reference: str) -> list[str]:
    try:
        path_text, separator, anchor = reference.partition("#")
        if not path_text.startswith("docs/"):
            return [f"source must refer to current docs: {reference}"]
        source = project_path(root, path_text)
        if not source.is_file():
            return [f"missing source: {reference}"]
        if separator:
            pattern = r'<a\s+id=["\x27]' + re.escape(anchor) + r'["\x27]\s*></a>'
            if not anchor or re.search(pattern, source.read_text(encoding="utf-8")) is None:
                return [f"missing explicit source anchor: {reference}"]
        return []
    except (OSError, ValueError, TypeError) as exc:
        return [f"invalid source {reference!r}: {exc}"]


def _asset_kind(path: str) -> str | None:
    if path in CONTRACT_PATHS.values():
        return "schema"
    if path == KNOWLEDGE_PATH:
        return "knowledge"
    if path == RULES_PATH:
        return "rules"
    if path == SKILLS_PATH:
        return "skills"
    if path.startswith("tests/fixtures/contracts/") and path.endswith(".json"):
        return "fixture"
    return None


def check_seed(root: Path | str) -> dict[str, Any]:
    """Validate files without refreshing the manifest or executing any candidate."""
    root = Path(root).resolve()
    errors: list[str] = []
    checked_assets = 0
    fixture_cases = 0

    def result() -> dict[str, Any]:
        return {"ok": not errors, "errors": errors, "checked_assets": checked_assets,
                "fixture_cases": fixture_cases}

    try:
        manifest = read_json(project_path(root, MANIFEST_PATH))
        errors.extend(_errors(MANIFEST_SCHEMA, manifest, "manifest"))
        if errors:
            return result()
        summary = manifest["specification_summary"]
        if summary["text"] != SPECIFICATION_SUMMARY:
            errors.append("specification summary differs from independent K0 baseline")
        if summary["sha256"] != sha256_bytes(summary["text"].encode("utf-8")):
            errors.append("specification summary hash mismatch")
        for reference in summary["source_refs"]:
            errors.extend(_source_errors(root, reference))
        if manifest["rules_baseline"]["sha256"] != TRUSTED_RULESET_SHA256:
            errors.append("manifest cannot replace independent trusted rules baseline")
        assets = {}
        for asset in manifest["assets"]:
            path = asset["path"]
            if path in assets:
                errors.append(f"duplicate asset path: {path}")
                continue
            assets[path] = asset
            if _asset_kind(path) != asset["kind"]:
                errors.append(f"unrecognized asset path or kind: {path}")
                continue
            try:
                content = project_path(root, path).read_bytes()
                checked_assets += 1
                if sha256_bytes(content) != asset["sha256"]:
                    errors.append(f"asset hash mismatch: {path}")
            except (OSError, ValueError) as exc:
                errors.append(f"asset {path}: {exc}")
        expected = set(CONTRACT_PATHS.values()) | {KNOWLEDGE_PATH, RULES_PATH, SKILLS_PATH}
        fixture_dir = project_path(root, "tests/fixtures/contracts")
        expected.update(path.relative_to(root).as_posix() for path in fixture_dir.rglob("*.json"))
        for directory in ("seed/knowledge", "seed/rules", "seed/skills"):
            expected.update(path.relative_to(root).as_posix()
                            for path in project_path(root, directory).rglob("*.json"))
        if set(assets) != expected:
            errors.append(f"asset inventory mismatch: missing={sorted(expected-set(assets))}, "
                          f"unexpected={sorted(set(assets)-expected)}")

        rules_path = project_path(root, RULES_PATH)
        rules = read_json(rules_path)
        if sha256_bytes(rules_path.read_bytes()) != TRUSTED_RULESET_SHA256:
            errors.append("rules differ from independent trusted rules baseline")
        if rules.get("version") != TRUSTED_RULESET_VERSION:
            errors.append("rules version mismatch")
        for rule in rules.get("rules", []):
            errors.extend(_source_errors(root, rule["source_ref"]))

        knowledge = read_json(project_path(root, KNOWLEDGE_PATH))
        knowledge_errors = _errors(KNOWLEDGE_SCHEMA, knowledge, "knowledge")
        errors.extend(knowledge_errors)
        if not knowledge_errors:
            identifiers = [record["record_id"] for record in knowledge["records"]]
            if len(set(identifiers)) != len(identifiers):
                errors.append("duplicate knowledge record_id")
            for record in knowledge["records"]:
                errors.extend(_source_errors(root, record["source"]))
                errors.extend(_source_errors(root, record["evidence_ref"]))

        catalog = read_json(project_path(root, SKILLS_PATH))
        catalog_errors = _errors(SKILLS_SCHEMA, catalog, "skills")
        errors.extend(catalog_errors)
        if not catalog_errors:
            caps = {}
            for capability in catalog["capabilities"]:
                cap_errors = validate_contract("capability", capability, root)
                errors.extend(cap_errors)
                if cap_errors:
                    continue
                capability_id = capability["capability_id"]
                if capability_id in caps:
                    errors.append(f"duplicate capability_id: {capability_id}")
                caps[capability_id] = capability
                for key in ("input_schema", "output_schema"):
                    _validator(capability[key])
                if capability["permissions"]["network_scopes"] or capability["permissions"]["device_scopes"]:
                    errors.append(f"K0 capability exposes network/devices: {capability_id}")
            if set(caps) != AVAILABLE_CAPABILITIES | {PLANNED_CAPABILITY}:
                errors.append("K0 capability inventory differs from the declared seed scope")
            available = {key for key, cap in caps.items() if cap["status"] == "available"}
            if available != AVAILABLE_CAPABILITIES:
                errors.append("K0 available capability set changed")
            if PLANNED_CAPABILITY in caps and caps[PLANNED_CAPABILITY]["status"] != "planned":
                errors.append("candidate build must remain planned")
            skill_ids = set()
            for skill in catalog["skills"]:
                if skill["skill_id"] in skill_ids:
                    errors.append(f"duplicate skill_id: {skill['skill_id']}")
                skill_ids.add(skill["skill_id"])
                for reference in skill["capability_refs"]:
                    if reference not in caps:
                        errors.append(f"unknown skill capability: {reference}")
                    elif skill["status"] == "available" and caps[reference]["status"] != "available":
                        errors.append(f"available skill references unavailable capability: {reference}")

        for name, path in CONTRACT_PATHS.items():
            schema = read_json(project_path(root, path))
            if schema.get("$schema") != DRAFT or schema.get("additionalProperties") is not False:
                errors.append(f"{name}: expected closed Draft 2020-12 schema")
            _validator(schema)
        cases = read_json(project_path(root, CASES_PATH))
        case_errors = _errors(CASES_SCHEMA, cases, "fixtures")
        errors.extend(case_errors)
        if not case_errors:
            seen_ids = set()
            covered = set()
            for case in cases["cases"]:
                fixture_cases += 1
                if case["case_id"] in seen_ids:
                    errors.append(f"duplicate fixture case_id: {case['case_id']}")
                seen_ids.add(case["case_id"])
                if case["path"] not in assets or _asset_kind(case["path"]) != "fixture":
                    errors.append(f"fixture not registered as asset: {case['path']}")
                    continue
                payload = read_json(project_path(root, case["path"]))
                passed = not validate_contract(case["contract"], payload, root)
                if passed != case["valid"]:
                    errors.append(f"fixture expectation failed: {case['case_id']}")
                covered.add((case["contract"], case["valid"]))
            if covered != {(name, valid) for name in CONTRACTS for valid in (True, False)}:
                errors.append("every contract needs both a positive and a negative fixture")
    except (OSError, ValueError, TypeError, KeyError, SchemaError) as exc:
        errors.append(f"seed validation failed: {exc}")
    return result()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    report = check_seed(args.root)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
