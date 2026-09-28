#!/usr/bin/env python3
"""Assert the n8n chart renders the 2.x env contract.

helm template of this wrapper must emit N8N_WEBHOOK_URL (not WEBHOOK_URL),
omit the leftover N8N_RUNNERS_ENABLED flag, and pin the extraEnv keys that
stop future default flips from changing behaviour.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

CHART_DIR = Path(__file__).resolve().parent
WEBHOOK_URL = "https://workflow.mekanics.ch"
PINNED_ENV = {
    "N8N_UNVERIFIED_PACKAGES_ENABLED": "true",
    "N8N_RUNNERS_TASK_TIMEOUT": "300",
    "N8N_MIGRATE_FS_STORAGE_PATH": "true",
}


def render() -> str:
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        shutil.copy2(CHART_DIR / "Chart.yaml", work / "Chart.yaml")
        shutil.copy2(CHART_DIR / "values.yaml", work / "values.yaml")
        templates = CHART_DIR / "templates"
        if templates.is_dir():
            shutil.copytree(templates, work / "templates")
        built = subprocess.run(
            ["helm", "dependency", "build", str(work)],
            capture_output=True,
            text=True,
        )
        if built.returncode != 0:
            sys.stderr.write(built.stderr or built.stdout)
            raise SystemExit("helm dependency build failed")
        templated = subprocess.run(
            [
                "helm",
                "template",
                "n8n",
                str(work),
                "--namespace",
                "n8n",
            ],
            capture_output=True,
            text=True,
        )
        if templated.returncode != 0:
            sys.stderr.write(templated.stderr or templated.stdout)
            raise SystemExit("helm template failed")
        return templated.stdout


def documents(manifest: str) -> list[str]:
    return [doc for doc in manifest.split("\n---\n") if doc.strip()]


def kind_name(doc: str) -> tuple[str | None, str | None]:
    kind = None
    name = None
    in_metadata = False
    for line in doc.splitlines():
        if line.startswith("kind:"):
            kind = line.split(":", 1)[1].strip()
        if line == "metadata:":
            in_metadata = True
            continue
        if in_metadata:
            if line.startswith("  name:"):
                name = line.split(":", 1)[1].strip().strip("'\"")
                in_metadata = False
            elif line and not line.startswith(" "):
                in_metadata = False
    return kind, name


def unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def configmap_data(manifest: str) -> dict[str, str]:
    for doc in documents(manifest):
        kind, _name = kind_name(doc)
        if kind != "ConfigMap":
            continue
        if "N8N_EDITOR_BASE_URL:" not in doc and "WEBHOOK_URL:" not in doc and "N8N_WEBHOOK_URL:" not in doc:
            continue
        data: dict[str, str] = {}
        in_data = False
        for line in doc.splitlines():
            if line == "data:":
                in_data = True
                continue
            if in_data:
                if line.startswith("  ") and ":" in line:
                    key, _, value = line.strip().partition(":")
                    data[key] = unquote(value)
                    continue
                if line and not line.startswith(" "):
                    break
        return data
    raise SystemExit("rendered manifests have no n8n app ConfigMap")


def main_container_env(manifest: str) -> dict[str, str]:
    for doc in documents(manifest):
        kind, name = kind_name(doc)
        if kind != "Deployment" or name != "n8n":
            continue
        env: dict[str, str] = {}
        current: str | None = None
        in_env = False
        for line in doc.splitlines():
            stripped = line.rstrip()
            if stripped.endswith(" env:") or stripped == "env:":
                in_env = True
                current = None
                continue
            if not in_env:
                continue
            item = stripped.strip()
            if item.startswith("- name:"):
                current = unquote(item.split(":", 1)[1])
                continue
            if current and item.startswith("value:"):
                env[current] = unquote(item.split(":", 1)[1])
                current = None
                continue
            if item in {"volumeMounts:", "resources:", "livenessProbe:", "readinessProbe:", "startupProbe:", "ports:"}:
                break
        return env
    raise SystemExit("rendered manifests have no Deployment named n8n")


def main() -> int:
    manifest = render()
    data = configmap_data(manifest)
    env = main_container_env(manifest)
    failed = False

    webhook = data.get("N8N_WEBHOOK_URL")
    if webhook != WEBHOOK_URL:
        print(f"N8N_WEBHOOK_URL: {webhook!r} (want {WEBHOOK_URL!r})", file=sys.stderr)
        failed = True
    if "WEBHOOK_URL" in data:
        print("WEBHOOK_URL must not be in the ConfigMap", file=sys.stderr)
        failed = True
    if "N8N_RUNNERS_ENABLED" in data:
        print("N8N_RUNNERS_ENABLED must not be in the ConfigMap", file=sys.stderr)
        failed = True

    for key, want in PINNED_ENV.items():
        got = env.get(key)
        if got != want:
            print(f"{key}: {got!r} (want {want!r})", file=sys.stderr)
            failed = True

    if failed:
        return 1
    print("n8n env contract ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
