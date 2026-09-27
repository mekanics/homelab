#!/usr/bin/env python3
"""Assert openclaw-state PVC labels enroll backups without 12h snapshots.

helm template of this chart must render PVC openclaw-state with Longhorn
PVC-as-source labels for the existing backup jobs and group default.
Joining group default-backup would also enable snapshot-12h; that is the
failure that filled this volume last night.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

CHART_DIR = Path(__file__).resolve().parent
LOCAL_DEP = Path("/Users/ajoly/Development/private/charts/charts/openclaw")

REQUIRED = {
    "recurring-job.longhorn.io/source": "enabled",
    "recurring-job-group.longhorn.io/default": "enabled",
    "recurring-job.longhorn.io/backup-every-8h": "enabled",
    "recurring-job.longhorn.io/backup-weekly": "enabled",
    "recurring-job.longhorn.io/backup-monthly": "enabled",
}
FORBIDDEN = (
    "recurring-job.longhorn.io/snapshot-12h",
    "recurring-job-group.longhorn.io/default-backup",
)


def render() -> str:
    if not LOCAL_DEP.is_dir():
        raise SystemExit(f"openclaw chart not found at {LOCAL_DEP}")
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        (work / "Chart.yaml").write_text(
            "\n".join(
                [
                    "apiVersion: v2",
                    "name: openclaw-wrapper",
                    "version: 0.0.0",
                    "dependencies:",
                    "  - name: openclaw",
                    "    version: 0.5.2",
                    f"    repository: file://{LOCAL_DEP}",
                ]
            )
            + "\n"
        )
        (work / "values.yaml").write_bytes((CHART_DIR / "values.yaml").read_bytes())
        subprocess.run(
            ["helm", "dependency", "build", str(work)],
            check=True,
            capture_output=True,
            text=True,
        )
        built = subprocess.run(
            [
                "helm",
                "template",
                "openclaw",
                str(work),
                "--namespace",
                "openclaw",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return built.stdout


def pvc_openclaw_state_labels(manifest: str) -> dict[str, str]:
    for doc in manifest.split("\n---\n"):
        if "kind: PersistentVolumeClaim" not in doc:
            continue
        if "\n  name: openclaw-state\n" not in doc and not doc.lstrip().startswith(
            "name: openclaw-state\n"
        ):
            continue
        labels: dict[str, str] = {}
        in_labels = False
        for line in doc.splitlines():
            if line == "  labels:" or line == "    labels:":
                in_labels = True
                continue
            if in_labels:
                if line.startswith("    ") or line.startswith("      "):
                    key, _, value = line.strip().partition(":")
                    labels[key] = value.strip()
                    continue
                break
        return labels
    raise SystemExit("rendered manifests have no PersistentVolumeClaim named openclaw-state")


def main() -> int:
    labels = pvc_openclaw_state_labels(render())
    missing = [k for k, v in REQUIRED.items() if labels.get(k) != v]
    present = [k for k in FORBIDDEN if k in labels]
    if missing or present:
        print("openclaw-state labels:", labels, file=sys.stderr)
        if missing:
            print("missing or wrong:", missing, file=sys.stderr)
        if present:
            print("forbidden present:", present, file=sys.stderr)
        return 1
    print("openclaw-state backup labels ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
