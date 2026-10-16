"""K0 tests: rejection paths, integrity pins and seed references, not model intelligence."""
from __future__ import annotations

import copy
import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("jarvis_seed_check", ROOT / "tools/check_seed.py")
assert SPEC is not None and SPEC.loader is not None
seed_check = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(seed_check)


class ContractTests(unittest.TestCase):
    def fixture(self, name, valid=True):
        label = "valid" if valid else "invalid"
        return seed_check.read_json(ROOT / f"tests/fixtures/contracts/{name}.{label}.json")

    def test_each_contract_has_positive_and_negative_examples(self):
        for name in seed_check.CONTRACTS:
            with self.subTest(contract=name, valid=True):
                self.assertEqual([], seed_check.validate_contract(name, self.fixture(name), ROOT))
            with self.subTest(contract=name, valid=False):
                self.assertTrue(seed_check.validate_contract(name, self.fixture(name, False), ROOT))

    def test_contracts_reject_unknown_fields_and_versions(self):
        for name in seed_check.CONTRACTS:
            for field, value in (("unexpected_authority", True), ("schema_version", "99.0.0")):
                candidate = self.fixture(name)
                candidate[field] = value
                with self.subTest(contract=name, field=field):
                    self.assertTrue(seed_check.validate_contract(name, candidate, ROOT))

    def test_action_dispatching_and_unknown_are_valid_states(self):
        for state in ("PREPARED", "DISPATCHING", "UNKNOWN", "CONFIRMED", "FAILED", "CANCELLED"):
            candidate = self.fixture("action")
            candidate["status"] = state
            with self.subTest(state=state):
                self.assertEqual([], seed_check.validate_contract("action", candidate, ROOT))

    def test_nested_unknown_field_is_rejected(self):
        candidate = self.fixture("task")
        candidate["budget"]["unlimited"] = True
        self.assertTrue(seed_check.validate_contract("task", candidate, ROOT))

    def test_artifact_paths_cannot_escape_or_be_absolute(self):
        for path in ("../escape.txt", "/root/file", "C:/file", r"..\file", "out/../file", "out//file"):
            candidate = self.fixture("artifact")
            candidate["path"] = path
            with self.subTest(path=path):
                self.assertTrue(seed_check.validate_contract("artifact", candidate, ROOT))

    def test_planned_capability_must_not_contain_executor(self):
        candidate = self.fixture("capability")
        candidate["status"] = "planned"
        self.assertTrue(seed_check.validate_contract("capability", candidate, ROOT))

    def test_inventory_argument_schema_enforces_scope_shape_and_limits(self):
        capability = self.fixture("capability")
        validator = seed_check._validator(capability["input_schema"])
        valid = {"relative_path": ".", "max_files": 1000, "max_bytes": 10485760}
        self.assertFalse(list(validator.iter_errors(valid)))
        for change in ({"relative_path": "../private"}, {"max_files": 1001},
                       {"max_bytes": 10485761}, {"execute_shell": True}):
            with self.subTest(change=change):
                self.assertTrue(list(validator.iter_errors(valid | change)))


    def test_status_embedded_contracts_match_authoritative_schemas(self):
        catalog = seed_check.read_json(ROOT / seed_check.SKILLS_PATH)
        status = next(cap for cap in catalog["capabilities"]
                      if cap["capability_id"] == "system.status.v1")
        for name in ("task", "action", "artifact"):
            expected = seed_check.read_json(ROOT / seed_check.CONTRACT_PATHS[name])
            expected.pop("$id", None)
            with self.subTest(contract=name):
                self.assertEqual(expected, status["output_schema"]["$defs"][name])

    def test_status_degraded_branches_are_closed_and_require_evidence(self):
        catalog = seed_check.read_json(ROOT / seed_check.SKILLS_PATH)
        status = next(cap for cap in catalog["capabilities"]
                      if cap["capability_id"] == "system.status.v1")
        validator = seed_check._validator(status["output_schema"])
        uninitialized = {"initialized": False, "stopped": True,
                         "reason": "not_initialized", "version": "1.0.0",
                         "limitations": ["Restricted prototype"]}
        degraded = {"initialized": True, "stopped": True, "stop_reason": "owner stop",
                    "diagnostic_error": "Invalid ledger document",
                    "reconciliation_error": "Invalid ledger document",
                    "limitations": ["Restricted prototype"]}
        for payload in (uninitialized, degraded):
            self.assertFalse(list(validator.iter_errors(payload)))
            self.assertTrue(list(validator.iter_errors(payload | {"execute_shell": True})))
        self.assertTrue(list(validator.iter_errors(degraded | {"stopped": False})))
        missing_evidence = {key: value for key, value in degraded.items()
                            if key != "diagnostic_error"}
        self.assertTrue(list(validator.iter_errors(missing_evidence)))
        self.assertTrue(list(validator.iter_errors({"status": "ok"})))

    def test_inventory_output_rejects_old_shape_and_unbounded_metadata(self):
        catalog = seed_check.read_json(ROOT / seed_check.SKILLS_PATH)
        inventory = next(cap for cap in catalog["capabilities"]
                         if cap["capability_id"] == "filesystem.read_sample.v1")
        validator = seed_check._validator(inventory["output_schema"])
        valid = {"schema_version": "1.0.0", "relative_path": ".",
                 "files": [{"path": "sample.txt", "size_bytes": 7, "type": ".txt"}],
                 "total_files": 1, "total_bytes": 7}
        self.assertFalse(list(validator.iter_errors(valid)))
        invalid = [{"entries": []}, valid | {"schema_version": "2.0.0"},
                   valid | {"total_bytes": 10485761}, valid | {"debug": "accidental"}]
        for item_change in ({"path": "../outside.txt"}, {"contents": "not metadata"}):
            candidate = copy.deepcopy(valid)
            candidate["files"][0].update(item_change)
            invalid.append(candidate)
        for payload in invalid:
            with self.subTest(payload=payload):
                self.assertTrue(list(validator.iter_errors(payload)))


class SeedIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="jarvis-k0-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for directory in ("contracts/schemas", "seed", "tests/fixtures/contracts"):
            shutil.copytree(ROOT / directory, self.root / directory)
        # Only the documents actually referenced by the seed are copied.
        for name in ("product-requirements", "core-bootstrap", "contracts", "security-sovereignty"):
            destination = self.root / "docs" / (name + ".md")
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / "docs" / (name + ".md"), destination)

    def load(self, relative):
        return seed_check.read_json(self.root / relative)

    def save(self, relative, data):
        (self.root / relative).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                                         encoding="utf-8")

    def rehash_asset_in_test_copy(self, relative):
        """Adversarial fixture preparation only; production checker has no refresh."""
        manifest = self.load(seed_check.MANIFEST_PATH)
        for asset in manifest["assets"]:
            if asset["path"] == relative:
                asset["sha256"] = seed_check.sha256_bytes((self.root / relative).read_bytes())
        self.save(seed_check.MANIFEST_PATH, manifest)

    def assert_failure_contains(self, expected):
        report = seed_check.check_seed(self.root)
        self.assertFalse(report["ok"], report)
        self.assertIn(expected, "\n".join(report["errors"]))

    def test_current_bundle_passes_and_checker_does_not_write(self):
        paths = [path for path in self.root.rglob("*") if path.is_file()]
        before = {path.relative_to(self.root): path.read_bytes() for path in paths}
        report = seed_check.check_seed(self.root)
        self.assertTrue(report["ok"], report)
        self.assertEqual(12, report["fixture_cases"])
        self.assertEqual(before, {path.relative_to(self.root): path.read_bytes() for path in paths})

    def test_rule_change_fails_even_if_manifest_hash_is_changed(self):
        rules = self.load(seed_check.RULES_PATH)
        rules["policy"]["arbitrary_shell"] = True
        self.save(seed_check.RULES_PATH, rules)
        self.rehash_asset_in_test_copy(seed_check.RULES_PATH)
        manifest = self.load(seed_check.MANIFEST_PATH)
        manifest["rules_baseline"]["sha256"] = seed_check.sha256_bytes(
            (self.root / seed_check.RULES_PATH).read_bytes())
        self.save(seed_check.MANIFEST_PATH, manifest)
        self.assert_failure_contains("independent trusted rules baseline")

    def test_plain_asset_drift_is_rejected(self):
        target = self.root / seed_check.KNOWLEDGE_PATH
        target.write_bytes(target.read_bytes() + b"\n")
        self.assert_failure_contains("asset hash mismatch")

    def test_missing_and_traversal_manifest_references_are_rejected(self):
        manifest = self.load(seed_check.MANIFEST_PATH)
        manifest["assets"][0]["path"] = "../outside.json"
        self.save(seed_check.MANIFEST_PATH, manifest)
        self.assert_failure_contains("unrecognized asset path")

    def test_unregistered_seed_asset_is_rejected(self):
        self.save("seed/knowledge/unregistered.json", {"arbitrary": "content"})
        self.assert_failure_contains("asset inventory mismatch")

    def test_planned_build_cannot_be_enabled_by_catalog_edit(self):
        catalog = self.load(seed_check.SKILLS_PATH)
        build = next(cap for cap in catalog["capabilities"]
                     if cap["capability_id"] == "build.candidate.v1")
        build.update(status="available", executor_ref="shell.anything")
        self.save(seed_check.SKILLS_PATH, catalog)
        self.rehash_asset_in_test_copy(seed_check.SKILLS_PATH)
        self.assert_failure_contains("candidate build must remain planned")

    def test_skill_must_reference_known_capability(self):
        catalog = self.load(seed_check.SKILLS_PATH)
        catalog["skills"][0]["capability_refs"] = ["shell.execute.v1"]
        self.save(seed_check.SKILLS_PATH, catalog)
        self.rehash_asset_in_test_copy(seed_check.SKILLS_PATH)
        self.assert_failure_contains("unknown skill capability")

    def test_knowledge_cannot_promote_itself_to_rules(self):
        knowledge = self.load(seed_check.KNOWLEDGE_PATH)
        knowledge["authority"] = "root_policy"
        self.save(seed_check.KNOWLEDGE_PATH, knowledge)
        self.rehash_asset_in_test_copy(seed_check.KNOWLEDGE_PATH)
        self.assert_failure_contains("reference_only")

    def test_missing_source_anchor_is_reported(self):
        knowledge = self.load(seed_check.KNOWLEDGE_PATH)
        knowledge["records"][0]["source"] = "docs/contracts.md#not-an-existing-anchor"
        self.save(seed_check.KNOWLEDGE_PATH, knowledge)
        self.rehash_asset_in_test_copy(seed_check.KNOWLEDGE_PATH)
        self.assert_failure_contains("missing explicit source anchor")

    def test_duplicate_asset_and_duplicate_json_keys_are_rejected(self):
        manifest = self.load(seed_check.MANIFEST_PATH)
        manifest["assets"].append(copy.deepcopy(manifest["assets"][0]))
        self.save(seed_check.MANIFEST_PATH, manifest)
        self.assert_failure_contains("duplicate asset path")
        (self.root / seed_check.MANIFEST_PATH).write_text(
            '{"schema_version":"1.0.0","schema_version":"1.0.0"}', encoding="utf-8")
        self.assert_failure_contains("duplicate JSON key")

    def test_external_schema_references_are_rejected_without_network(self):
        schema_path = "contracts/schemas/task.schema.json"
        schema = self.load(schema_path)
        schema["properties"]["title"] = {"$ref": "https://example.invalid/schema"}
        self.save(schema_path, schema)
        self.rehash_asset_in_test_copy(schema_path)
        self.assert_failure_contains("without external references")

    def test_fixture_expectations_cannot_silently_disagree(self):
        index = self.load(seed_check.CASES_PATH)
        index["cases"][0]["valid"] = False
        self.save(seed_check.CASES_PATH, index)
        self.rehash_asset_in_test_copy(seed_check.CASES_PATH)
        self.assert_failure_contains("fixture expectation failed")


if __name__ == "__main__":
    unittest.main()
