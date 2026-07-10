#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tarfile
import tomllib
import zipfile
from email.parser import Parser
from pathlib import Path
from typing import Any

SEMVER_PATTERN = (
    r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)"
    r"(?:-(?:alpha|beta|rc)\.(?:0|[1-9]\d*))?"
)
SEMVER_RE = re.compile(rf"^{SEMVER_PATTERN}$")
TAG_RE = re.compile(rf"^v({SEMVER_PATTERN})$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")

POLICIES = {
    "xian-tech-py": {
        "component": "xian-contracting",
        "repository": "xian-technology/xian-contracting",
        "component_packages": {
            "xian-tech-accounts": "packages/xian-accounts/pyproject.toml",
            "xian-tech-compiler-core": "packages/xian-compiler-core/pyproject.toml",
            "xian-tech-contracting": "pyproject.toml",
            "xian-tech-runtime-types": "packages/xian-runtime-types/pyproject.toml",
        },
    },
    "xian-tech-linter": {
        "component": "xian-contracting",
        "repository": "xian-technology/xian-contracting",
        "component_packages": {
            "xian-tech-compiler-core": "packages/xian-compiler-core/pyproject.toml",
            "xian-tech-contracting": "pyproject.toml",
            "xian-tech-runtime-types": "packages/xian-runtime-types/pyproject.toml",
            "xian-tech-vm-core": "packages/xian-vm-core/pyproject.toml",
        },
    },
}


def fail(message: str) -> None:
    raise RuntimeError(message)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def read_toml(path: Path) -> dict[str, Any]:
    return tomllib.loads(path.read_text())


def exact_keys(value: Any, expected: set[str], label: str) -> None:
    if not isinstance(value, dict):
        fail(f"{label} must be an object")
    actual = set(value)
    if actual != expected:
        fail(f"{label} keys must be exactly {sorted(expected)}; got {sorted(actual)}")


def policy_for_root(root: Path) -> dict[str, Any]:
    project = read_toml(root / "pyproject.toml")["project"]
    policy = POLICIES.get(project["name"])
    if policy is None:
        fail(f"unsupported release repository: {project['name']}")
    return policy


def load_manifest(root: Path) -> dict[str, Any]:
    return read_json(root / "release-manifest.json")


def validate_manifest(manifest: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    exact_keys(manifest, {"schema_version", "components"}, "release manifest")
    if manifest["schema_version"] != 1:
        fail("release manifest schema_version must be 1")

    component_name = policy["component"]
    exact_keys(manifest["components"], {component_name}, "release manifest components")
    component = manifest["components"][component_name]
    exact_keys(component, {"repository", "ref", "packages"}, component_name)
    if component["repository"] != policy["repository"]:
        fail(
            f"{component_name} repository must be {policy['repository']}; "
            f"got {component['repository']}"
        )
    if not SHA_RE.fullmatch(component["ref"]):
        fail(f"{component_name} ref must be a lowercase 40-character commit SHA")

    expected_packages = policy["component_packages"]
    exact_keys(component["packages"], set(expected_packages), f"{component_name} packages")
    for name, expected_path in expected_packages.items():
        package = component["packages"][name]
        exact_keys(package, {"path", "version"}, f"{component_name} package {name}")
        if package["path"] != expected_path:
            fail(f"{name} path must be {expected_path}; got {package['path']}")
        if not SEMVER_RE.fullmatch(package["version"]):
            fail(f"{name} version is not an accepted release version: {package['version']}")
    return component


def release_version_from_tag(tag: str) -> str:
    match = TAG_RE.fullmatch(tag)
    if match is None:
        fail(f"release tag must match vX.Y.Z or vX.Y.Z-(alpha|beta|rc).N; got {tag}")
    return match.group(1)


def python_dist_version(version: str) -> str:
    match = re.fullmatch(r"(\d+\.\d+\.\d+)-(alpha|beta|rc)\.(\d+)", version)
    if match is None:
        return version
    marker = {"alpha": "a", "beta": "b", "rc": "rc"}[match.group(2)]
    return f"{match.group(1)}{marker}{match.group(3)}"


def lock_packages(root: Path) -> dict[str, dict[str, Any]]:
    packages = read_toml(root / "uv.lock")["package"]
    result: dict[str, dict[str, Any]] = {}
    for package in packages:
        name = package["name"]
        if name in result:
            fail(f"uv.lock contains duplicate package entries for {name}")
        result[name] = package
    return result


def component_source_path(component_name: str, package_path: str) -> str:
    package_root = Path(package_path).parent
    return (Path("..") / component_name / package_root).as_posix().removesuffix("/.")


def verify_component_lock(root: Path, policy: dict[str, Any], component: dict[str, Any]) -> None:
    locked_packages = lock_packages(root)
    for name, package in component["packages"].items():
        locked = locked_packages.get(name)
        if locked is None:
            fail(f"uv.lock is missing component package {name}")
        expected_version = python_dist_version(package["version"])
        if locked["version"] != expected_version:
            fail(f"uv.lock has {name} {locked['version']}; expected {expected_version}")
        source = locked.get("source", {})
        actual_source = source.get("editable") or source.get("directory")
        expected_source = component_source_path(policy["component"], package["path"])
        if actual_source != expected_source:
            fail(f"uv.lock source for {name} is {actual_source}; expected {expected_source}")


def verify_self_versions(root: Path, version: str) -> None:
    project = read_toml(root / "pyproject.toml")["project"]
    if project["version"] != version:
        fail(f"pyproject.toml has version {project['version']}; expected {version}")
    locked = lock_packages(root).get(project["name"])
    if locked is None:
        fail(f"uv.lock is missing self package {project['name']}")
    expected_version = python_dist_version(version)
    if locked["version"] != expected_version or locked.get("source", {}).get("editable") != ".":
        fail(
            f"uv.lock self package is {locked['version']} from {locked.get('source')}; "
            f"expected {expected_version} from the project root"
        )


def run(command: list[str], cwd: Path) -> str:
    return subprocess.run(
        command,
        cwd=cwd,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout.strip()


def git(cwd: Path, *args: str) -> str:
    return run(["git", *args], cwd)


def assert_clean_checkout(checkout: Path, label: str) -> None:
    status = git(checkout, "status", "--porcelain", "--untracked-files=all")
    if status:
        fail(f"{label} checkout is not clean:\n{status}")


def resolve_release_context(
    root: Path,
    *,
    tag: str,
    trigger_sha: str,
    ref_type: str,
) -> dict[str, Any]:
    if ref_type != "tag":
        fail(f"release workflow must be triggered by a tag; got ref type {ref_type}")
    policy = policy_for_root(root)
    component = validate_manifest(load_manifest(root), policy)
    version = release_version_from_tag(tag)
    verify_self_versions(root, version)
    verify_component_lock(root, policy, component)

    head = git(root, "rev-parse", "HEAD")
    tag_commit = git(root, "rev-parse", f"refs/tags/{tag}^{{commit}}")
    trigger_commit = git(root, "rev-parse", f"{trigger_sha}^{{commit}}")
    if head != tag_commit or head != trigger_commit:
        fail(f"release source mismatch: HEAD={head}, tag={tag_commit}, trigger={trigger_commit}")
    assert_clean_checkout(root, "release source")
    return {"component": component, "policy": policy, "source_sha": head, "version": version}


def verify_pinned_checkout(
    root: Path,
    component_checkout: Path,
    *,
    expected_source_sha: str,
    tag: str,
) -> None:
    policy = policy_for_root(root)
    component = validate_manifest(load_manifest(root), policy)
    version = release_version_from_tag(tag)
    source_head = git(root, "rev-parse", "HEAD")
    if source_head != expected_source_sha or not SHA_RE.fullmatch(expected_source_sha):
        fail(f"release source HEAD is {source_head}; expected {expected_source_sha}")
    assert_clean_checkout(root, "release source")
    verify_self_versions(root, version)
    verify_component_lock(root, policy, component)

    component_head = git(component_checkout, "rev-parse", "HEAD")
    if component_head != component["ref"]:
        fail(f"{policy['component']} HEAD is {component_head}; expected {component['ref']}")
    assert_clean_checkout(component_checkout, policy["component"])
    for name, package in component["packages"].items():
        project = read_toml(component_checkout / package["path"])["project"]
        if project["name"] != name or project["version"] != package["version"]:
            fail(
                f"{policy['component']}/{package['path']} is "
                f"{project['name']}@{project['version']}; expected {name}@{package['version']}"
            )


def distribution_metadata(artifact: Path) -> dict[str, str]:
    if artifact.suffix == ".whl":
        with zipfile.ZipFile(artifact) as archive:
            metadata_files = [
                name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
            ]
            if len(metadata_files) != 1:
                fail(f"{artifact.name} must contain exactly one METADATA file")
            content = archive.read(metadata_files[0]).decode()
    elif artifact.name.endswith(".tar.gz"):
        with tarfile.open(artifact, "r:gz") as archive:
            metadata_files = [
                member
                for member in archive.getmembers()
                if member.name.endswith("/PKG-INFO") and member.name.count("/") == 1
            ]
            if len(metadata_files) != 1:
                fail(f"{artifact.name} must contain exactly one PKG-INFO file")
            extracted = archive.extractfile(metadata_files[0])
            if extracted is None:
                fail(f"could not read metadata from {artifact.name}")
            content = extracted.read().decode()
    else:
        fail(f"unexpected release artifact: {artifact.name}")
    parsed = Parser().parsestr(content)
    return {"name": parsed["Name"], "version": parsed["Version"]}


def verify_artifacts(root: Path, artifact_directory: Path, tag: str) -> None:
    project = read_toml(root / "pyproject.toml")["project"]
    expected_version = python_dist_version(release_version_from_tag(tag))
    artifacts = sorted(
        path
        for path in artifact_directory.iterdir()
        if path.is_file() and not path.name.startswith(".")
    )
    wheels = [path for path in artifacts if path.suffix == ".whl"]
    sdists = [path for path in artifacts if path.name.endswith(".tar.gz")]
    if len(artifacts) != 2 or len(wheels) != 1 or len(sdists) != 1:
        fail(f"expected one wheel and one sdist; found {[path.name for path in artifacts]}")
    for artifact in artifacts:
        metadata = distribution_metadata(artifact)
        if metadata != {"name": project["name"], "version": expected_version}:
            fail(
                f"{artifact.name} has metadata {metadata}; expected {project['name']} {expected_version}"
            )
    import_package = {"xian-tech-py": "xian_py", "xian-tech-linter": "xian_linter"}[project["name"]]
    with zipfile.ZipFile(wheels[0]) as archive:
        top_levels = {
            name.split("/", 1)[0]
            for name in archive.namelist()
            if "/" in name and not name.startswith(".")
        }
    unexpected = {
        name for name in top_levels if name != import_package and not name.endswith(".dist-info")
    }
    if unexpected:
        fail(f"{wheels[0].name} contains unexpected top-level packages: {sorted(unexpected)}")


def required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        fail(f"missing required environment variable: {name}")
    return value


def write_github_outputs(path: Path, context: dict[str, Any]) -> None:
    prefix = context["policy"]["component"].replace("-", "_")
    component = context["component"]
    with path.open("a") as output:
        output.write(f"source_sha={context['source_sha']}\n")
        output.write(f"version={context['version']}\n")
        output.write(f"{prefix}_repository={component['repository']}\n")
        output.write(f"{prefix}_ref={component['ref']}\n")


def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    root = Path.cwd()
    if command == "validate-manifest":
        policy = policy_for_root(root)
        component = validate_manifest(load_manifest(root), policy)
        verify_component_lock(root, policy, component)
    elif command == "resolve":
        context = resolve_release_context(
            root,
            tag=required_env("RELEASE_TAG"),
            trigger_sha=required_env("TRIGGER_SHA"),
            ref_type=required_env("GITHUB_REF_TYPE"),
        )
        write_github_outputs(Path(required_env("GITHUB_OUTPUT")), context)
    elif command == "verify-component":
        verify_pinned_checkout(
            root,
            Path(required_env("COMPONENT_CHECKOUT")),
            expected_source_sha=required_env("EXPECTED_SOURCE_SHA"),
            tag=required_env("RELEASE_TAG"),
        )
    elif command == "verify-artifacts":
        verify_artifacts(
            root,
            Path(required_env("ARTIFACT_DIRECTORY")),
            required_env("RELEASE_TAG"),
        )
    else:
        fail(f"unknown command: {command or '(missing)'}")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, KeyError, OSError, subprocess.CalledProcessError) as error:
        print(error, file=sys.stderr)
        raise SystemExit(1) from error
