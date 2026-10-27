"""Validate source identity and normalize metadata without executing package code."""

from typing import Any, Dict, List

from .model import InputError, Record, SourceError, canonical_name, normalize_repository


def required_text(obj: Dict[str, Any], key: str) -> str:
    value = obj.get(key)
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 1000
        or any(ord(c) < 32 for c in value)
    ):
        raise SourceError("missing or invalid source field: " + key)
    return value


def optional_text(obj: Dict[str, Any], key: str):
    value = obj.get(key)
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise SourceError("invalid source field: " + key)
    return value


def identity(data: Dict[str, Any], record: Record):
    name = required_text(data, "name")
    try:
        actual = canonical_name(record.ecosystem, name)
    except InputError as exc:
        raise SourceError("invalid registry package identity") from exc
    if actual != record.package:
        raise SourceError(
            "registry identity mismatch: expected %s, got %s" % (record.package, name)
        )
    version = required_text(data, "version")
    if record.selector != "latest" and version != record.selector:
        raise SourceError(
            "registry version mismatch: requested %s, got %s" % (record.selector, version)
        )
    return version


def npm_map(data: Dict[str, Any], key: str) -> Dict[str, str]:
    obj = data.get(key, {})
    if not isinstance(obj, dict):
        raise SourceError("invalid npm " + key + ": expected an object")
    for name, value in obj.items():
        try:
            canonical_name("npm", name)
        except InputError as exc:
            raise SourceError("invalid dependency name in " + key) from exc
        if not isinstance(value, str) or not value:
            raise SourceError("invalid npm requirement in " + key)
    return obj


def normalize_npm(data: Dict[str, Any], record: Record) -> Dict[str, Any]:
    version = identity(data, record)
    dependency_groups = {
        "runtime": npm_map(data, "dependencies"),
        "peer": npm_map(data, "peerDependencies"),
        "optional": npm_map(data, "optionalDependencies"),
    }
    names = record.dependency_scope.split("+")
    dependencies = sorted(
        {name + "@" + spec for group in names for name, spec in dependency_groups[group].items()}
    )
    license_value = data.get("license")
    notes = []
    if isinstance(license_value, dict):
        license_value = license_value.get("type")
        notes.append(
            "Legacy license object: using its declared type, not inspecting license files."
        )
    if license_value is not None and not isinstance(license_value, str):
        raise SourceError("invalid npm license field")
    repository = data.get("repository")
    directory = None
    if isinstance(repository, dict):
        directory = repository.get("directory")
        if directory is not None and not isinstance(directory, str):
            raise SourceError("invalid npm repository directory")
        repository = repository.get("url")
    if repository is not None and not isinstance(repository, str):
        raise SourceError("invalid npm repository field")
    deprecated = data.get("deprecated")
    if deprecated is not None and not isinstance(deprecated, str):
        raise SourceError("invalid npm deprecated field")
    if deprecated:
        notes.append("Publisher marks this version deprecated: " + deprecated)
    try:
        repository_value = normalize_repository(repository) if repository else None
    except ValueError as exc:
        raise SourceError("invalid npm repository URL") from exc
    return {
        "version": version,
        "license": license_value or None,
        "repository": repository_value,
        "repository_directory": directory,
        "dependencies": dependencies,
        "dependency_groups": dependency_groups,
        "deprecated": deprecated or None,
        "notes": notes,
    }


def normalize_pypi(data: Dict[str, Any], record: Record) -> Dict[str, Any]:
    info = data.get("info")
    if not isinstance(info, dict):
        raise SourceError("PyPI info must be an object")
    version = identity(info, record)
    # A well-formed empty info object or stale error envelope is not a success.
    if not isinstance(data.get("urls"), list):
        raise SourceError("PyPI urls must be an array")
    if (
        not isinstance(data.get("last_serial"), int)
        or isinstance(data.get("last_serial"), bool)
        or data["last_serial"] < 1
    ):
        raise SourceError("PyPI last_serial must be a positive integer")
    requires = info.get("requires_dist")
    if requires is None:
        requires = []
    if not isinstance(requires, list) or any(not isinstance(x, str) or not x for x in requires):
        raise SourceError("PyPI requires_dist must be a string array or null")
    urls = info.get("project_urls")
    if urls is None:
        urls = {}
    if not isinstance(urls, dict) or any(
        not isinstance(k, str) or not isinstance(v, str) for k, v in urls.items()
    ):
        raise SourceError("PyPI project_urls must be a string mapping")
    repository = None
    # Deliberately do not guess from Home Page; it may be documentation or a different project.
    for wanted in ("source", "source code", "repository", "code"):
        matches = [v for k, v in urls.items() if k.casefold() == wanted]
        if matches:
            repository = matches[0]
            break
    license_value = optional_text(info, "license_expression")
    notes = [
        "PyPI requirements include markers/extras verbatim; this is metadata comparison, not dependency resolution."
    ]
    if not license_value:
        # Legacy license can contain an entire legal text; do not mistake it for SPDX.
        legacy = optional_text(info, "license")
        if legacy and len(legacy) <= 120 and "\n" not in legacy:
            license_value = legacy
            notes.append(
                "License is a legacy publisher-supplied string, not a validated SPDX expression."
            )
        else:
            notes.append(
                "No concise declared license expression available; missing license is unknown, not unlicensed."
            )
    if not data["urls"]:
        notes.append(
            "No files listed for this release; metadata exists but installability is not established."
        )
    if info.get("yanked") is True:
        notes.append(
            "PyPI marks this release yanked: "
            + str(info.get("yanked_reason") or "no reason supplied")
        )
    if info.get("dynamic"):
        notes.append("Publisher declares dynamic metadata: " + str(info["dynamic"]))
    try:
        repository_value = normalize_repository(repository) if repository else None
    except ValueError as exc:
        raise SourceError("invalid PyPI repository URL") from exc
    return {
        "version": version,
        "license": license_value,
        "repository": repository_value,
        "dependencies": sorted(set(requires)),
        "last_serial": data["last_serial"],
        "notes": notes,
    }


def normalize(data: Dict[str, Any], record: Record) -> Dict[str, Any]:
    if record.ecosystem == "npm":
        return normalize_npm(data, record)
    if record.ecosystem == "pypi":
        return normalize_pypi(data, record)
    raise SourceError("unsupported ecosystem")


def compare(record: Record, observed: Dict[str, Any]) -> Dict[str, Any]:
    diffs: List[Dict[str, Any]] = []
    unknowns = []
    expected = record.expected or {}
    for field, before in expected.items():
        after = observed.get(field)
        if after is None:
            unknowns.append(field)
        elif before != after:
            difference = {"field": field, "expected": before, "observed": after}
            if field == "dependencies":
                difference["added"] = sorted(set(after) - set(before))
                difference["removed"] = sorted(set(before) - set(after))
            diffs.append(difference)
    # A partial observation never earns an all-clear even when other fields match.
    if unknowns:
        state = "unavailable"
    elif diffs:
        state = "changed"
    elif expected:
        state = "unchanged"
    else:
        state = "observed"
    return {
        "state": state,
        "differences": diffs,
        "unknown_fields": unknowns,
        "error": "Expected fields absent from source: " + ", ".join(unknowns) if unknowns else None,
    }
