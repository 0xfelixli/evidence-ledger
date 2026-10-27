import csv
import io
import unittest

from evidence_ledger.model import (
    InputError,
    canonical_name,
    normalize_repository,
    parse_csv,
    validate_selector,
)


def make_csv(**overrides):
    row = {"record_id": "one", "ecosystem": "npm", "package": "react"}
    row.update(overrides)
    target = io.StringIO(newline="")
    writer = csv.DictWriter(target, fieldnames=list(row))
    writer.writeheader()
    writer.writerow(row)
    return target.getvalue().encode()


class InputTests(unittest.TestCase):
    def test_defaults_and_scoped_package(self):
        rec = parse_csv(make_csv(package="@scope/name"))[0]
        self.assertEqual(rec.package, "@scope/name")
        self.assertEqual(rec.selector, "latest")
        self.assertEqual(rec.dependency_scope, "runtime+peer")
        self.assertEqual(rec.expected, {})

    def test_name_normalization(self):
        self.assertEqual(canonical_name("pypi", "Foo_Bar.BAZ"), "foo-bar-baz")
        for value in [
            "a/b",
            "../react",
            "@a/b/c",
            "react\n",
            "react?x=y",
            "react#x",
            "A",
            "https://evil.test",
            "@/x",
        ]:
            with self.subTest(value=value), self.assertRaises(InputError):
                canonical_name("npm", value)

    def test_py_names_cannot_be_paths(self):
        for value in ["../x", "x/y", "x?", "x\n", "-abc", "abc_"]:
            with self.subTest(value=value), self.assertRaises(InputError):
                canonical_name("pypi", value)

    def test_selectors_reject_tags_ranges_and_paths(self):
        for value in ["../latest", "^1.0.0", "a/b", "1.0\n", "", "http://x"]:
            with self.subTest(value=value), self.assertRaises(InputError):
                validate_selector(value)
        self.assertEqual(validate_selector("1!2.0+local.1"), "1!2.0+local.1")

    def test_json_deps_empty_is_assertion(self):
        self.assertEqual(
            parse_csv(make_csv(expected_dependencies="[]"))[0].expected, {"dependencies": []}
        )
        self.assertEqual(parse_csv(make_csv(expected_dependencies=""))[0].expected, {})
        for value in ["{}", "null", "[1]", '[""]', '["a","a"]', "not-json"]:
            with self.subTest(value=value), self.assertRaises(InputError):
                parse_csv(make_csv(expected_dependencies=value))

    def test_duplicate_id_rejected(self):
        raw = make_csv().decode().splitlines()
        with self.assertRaisesRegex(InputError, "duplicate record_id"):
            parse_csv(("\n".join(raw + raw[1:]) + "\n").encode())

    def test_malformed_header_is_an_input_error(self):
        for raw in [b'"unterminated', b"x" * 200000 + b"\n"]:
            with self.subTest(size=len(raw)), self.assertRaisesRegex(InputError, "CSV header"):
                parse_csv(raw)

    def test_deep_dependency_json_is_an_input_error(self):
        raw = make_csv(expected_dependencies="[" * 2000 + '"x"' + "]" * 2000)
        with self.assertRaisesRegex(InputError, "JSON string array"):
            parse_csv(raw)

    def test_wrong_shape_and_headers(self):
        for raw in [
            b"",
            b"record_id,package\na,react\n",
            b"record_id,ecosystem,package,package\na,npm,react,react\n",
            b"record_id,ecosystem,package\na,npm\n",
            b"record_id,ecosystem,package\na,npm,react,extra\n",
            b"record_id,ecosystem,package,typo\na,npm,react,1\n",
            b"record_id,ecosystem,package\n",
        ]:
            with self.subTest(raw=raw), self.assertRaises(InputError):
                parse_csv(raw)

    def test_no_silent_trim(self):
        with self.assertRaises(InputError):
            parse_csv(make_csv(package="react "))
        with self.assertRaises(InputError):
            parse_csv(make_csv(package="react\x00"))

    def test_bom_and_repository_transport(self):
        self.assertEqual(parse_csv(b"\xef\xbb\xbf" + make_csv())[0].package, "react")
        self.assertEqual(
            normalize_repository("git+https://github.com/foo/bar.git"), "https://github.com/foo/bar"
        )
        self.assertEqual(
            normalize_repository("git@github.com:foo/bar.git"), "https://github.com/foo/bar"
        )
        self.assertNotEqual(
            normalize_repository("https://github.com/foo/bar#one"),
            normalize_repository("https://github.com/foo/bar#two"),
        )

    def test_scope_matters(self):
        rec = parse_csv(make_csv(ecosystem="pypi", package="requests"))[0]
        self.assertEqual(rec.dependency_scope, "requires-dist")
        with self.assertRaises(InputError):
            parse_csv(make_csv(ecosystem="pypi", package="requests", dependency_scope="runtime"))


if __name__ == "__main__":
    unittest.main()
