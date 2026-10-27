import copy
import unittest

from evidence_ledger.model import Record, SourceError
from evidence_ledger.registry import compare, normalize

NPM = {
    "name": "@scope/example",
    "version": "1.2.0",
    "dependencies": {"foo": "^1.0"},
    "peerDependencies": {"react": ">=18"},
    "optionalDependencies": {"optional": "~2"},
    "devDependencies": {"not-runtime": "1"},
    "license": "MIT",
    "repository": {"url": "git+https://github.com/foo/bar.git", "directory": "packages/core"},
}
PYPI = {
    "info": {
        "name": "Some_Package",
        "version": "2.0",
        "requires_dist": ["a>=1; extra == 'dev'", "b"],
        "license_expression": "MIT",
        "project_urls": {"Source": "https://github.com/foo/bar"},
    },
    "last_serial": 123,
    "urls": [],
}


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.rec = Record("one", "npm", "@scope/example")

    def test_npm_scope_preserves_groups(self):
        observed = normalize(copy.deepcopy(NPM), self.rec)
        self.assertEqual(observed["dependencies"], ["foo@^1.0", "react@>=18"])
        self.assertNotIn("not-runtime", str(observed))
        self.assertEqual(observed["dependency_groups"]["optional"], {"optional": "~2"})
        self.assertEqual(observed["repository_directory"], "packages/core")
        self.assertEqual(observed["repository"], "https://github.com/foo/bar")
        record = Record("one", "npm", "@scope/example", dependency_scope="runtime+peer+optional")
        self.assertIn("optional@~2", normalize(NPM, record)["dependencies"])

    def test_empty_manifest_is_not_empty_dependencies(self):
        for data in [
            {},
            {"error": "not found"},
            {"name": "@scope/example"},
            {"version": "1"},
            {"name": "other", "version": "1"},
            {"name": "@scope/example", "version": "1", "dependencies": []},
            {"name": "@scope/example", "version": "1", "dependencies": None},
        ]:
            with self.subTest(data=data), self.assertRaises(SourceError):
                normalize(data, self.rec)

    def test_missing_dependency_field_validly_means_none(self):
        result = normalize({"name": "@scope/example", "version": "1"}, self.rec)
        self.assertEqual(result["dependencies"], [])
        self.assertIsNone(result["license"])

    def test_requested_pinned_version_must_match(self):
        with self.assertRaisesRegex(SourceError, "version mismatch"):
            normalize(NPM, Record("one", "npm", "@scope/example", selector="1.1.0"))

    def test_duplicate_group_name_with_different_ranges_not_lost(self):
        data = copy.deepcopy(NPM)
        data["peerDependencies"]["foo"] = ">=1"
        self.assertEqual(
            normalize(data, self.rec)["dependencies"], ["foo@>=1", "foo@^1.0", "react@>=18"]
        )

    def test_compare_states_unknown_is_not_pass(self):
        observed = normalize(NPM, self.rec)
        self.assertEqual(compare(self.rec, observed)["state"], "observed")
        rec = Record("one", "npm", "@scope/example", expected={"version": "1.2.0"})
        self.assertEqual(compare(rec, observed)["state"], "unchanged")
        rec = Record(
            "one", "npm", "@scope/example", expected={"version": "1.1.0", "license": "Apache-2.0"}
        )
        self.assertEqual(len(compare(rec, observed)["differences"]), 2)
        partial = copy.deepcopy(observed)
        partial["license"] = None
        result = compare(rec, partial)
        self.assertEqual(result["state"], "unavailable")
        self.assertEqual(result["unknown_fields"], ["license"])
        self.assertEqual(len(result["differences"]), 1)

    def test_dependency_diff(self):
        rec = Record("one", "npm", "@scope/example", expected={"dependencies": ["foo@^0.9"]})
        result = compare(rec, normalize(NPM, rec))
        self.assertEqual(result["state"], "changed")
        self.assertEqual(result["differences"][0]["removed"], ["foo@^0.9"])
        self.assertEqual(result["differences"][0]["added"], ["foo@^1.0", "react@>=18"])

    def test_pypi_normalizes_name_preserves_markers(self):
        rec = Record("p", "pypi", "some-package", dependency_scope="requires-dist")
        result = normalize(PYPI, rec)
        self.assertEqual(result["dependencies"], ["a>=1; extra == 'dev'", "b"])
        self.assertEqual(result["last_serial"], 123)
        self.assertTrue(result["notes"])

    def test_pypi_shape_serial_and_wrong_identity(self):
        rec = Record("p", "pypi", "some-package", dependency_scope="requires-dist")
        for change in [
            {"info": {}},
            {"urls": None},
            {"last_serial": False},
            {"last_serial": 0},
            {"info": {"name": "wrong", "version": "2.0"}},
        ]:
            data = copy.deepcopy(PYPI)
            data.update(change)
            with self.subTest(change=change), self.assertRaises(SourceError):
                normalize(data, rec)

    def test_pypi_does_not_guess_homepage_is_repository(self):
        data = copy.deepcopy(PYPI)
        data["info"]["project_urls"] = {"Homepage": "https://github.com/foo/bar"}
        rec = Record("p", "pypi", "some-package", dependency_scope="requires-dist")
        self.assertIsNone(normalize(data, rec)["repository"])

    def test_long_legacy_license_remains_unknown(self):
        data = copy.deepcopy(PYPI)
        data["info"]["license_expression"] = None
        data["info"]["license"] = "Legal text\n" * 50
        self.assertIsNone(
            normalize(data, Record("p", "pypi", "some-package", dependency_scope="requires-dist"))[
                "license"
            ]
        )


if __name__ == "__main__":
    unittest.main()
