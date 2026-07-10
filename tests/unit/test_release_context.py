from __future__ import annotations

import sys
import tomllib
from copy import deepcopy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.release_context import (  # noqa: E402
    load_manifest,
    policy_for_root,
    python_dist_version,
    release_version_from_tag,
    validate_manifest,
    verify_component_lock,
    verify_self_versions,
)


def test_checked_in_release_manifest_and_lock_versions_agree() -> None:
    policy = policy_for_root(ROOT)
    component = validate_manifest(load_manifest(ROOT), policy)
    verify_component_lock(ROOT, policy, component)


def test_manifest_rejects_floating_component_ref() -> None:
    policy = policy_for_root(ROOT)
    manifest = deepcopy(load_manifest(ROOT))
    manifest["components"][policy["component"]]["ref"] = "main"
    with pytest.raises(RuntimeError, match="40-character commit SHA"):
        validate_manifest(manifest, policy)


def test_manifest_rejects_missing_component_package_authority() -> None:
    policy = policy_for_root(ROOT)
    manifest = deepcopy(load_manifest(ROOT))
    packages = manifest["components"][policy["component"]]["packages"]
    packages.pop(next(iter(packages)))
    with pytest.raises(RuntimeError, match="keys must be exactly"):
        validate_manifest(manifest, policy)


def test_release_tag_and_python_version_normalization_are_strict() -> None:
    assert release_version_from_tag("v1.2.3") == "1.2.3"
    assert release_version_from_tag("v1.2.3-beta.4") == "1.2.3-beta.4"
    assert python_dist_version("1.2.3-beta.4") == "1.2.3b4"
    with pytest.raises(RuntimeError, match="release tag must match"):
        release_version_from_tag("v1.2.3-preview.1")


def test_self_project_and_lock_versions_agree() -> None:
    version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    verify_self_versions(ROOT, version)
