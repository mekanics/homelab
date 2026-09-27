#!/usr/bin/env python3
"""Assert openclaw-data PVC labels enroll backups without 12h snapshots.

helm template of this chart must render PVC openclaw-data on
longhorn-local with Longhorn PVC-as-source labels for the existing
backup jobs and group default. Joining group default-backup would also
enable snapshot-12h; that is the failure that filled the previous
volume.

Scratch for plugin-captures is an emptyDir at OPENCLAW_STATE_DIR/tmp so
rebuildable build trees never land on the snapshotted volume. Exactly
one volumeMount uses the state directory.
"""

from __future__ import annotations

import shutil
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

STATE_MOUNT = "/home/node/.openclaw-state"
STATE_TMP_MOUNT = "/home/node/.openclaw-state/tmp"
STATE_TMP_LIMIT = "8Gi"
DATA_STORAGE_CLASS = "longhorn-local"
DATA_SIZE = "10Gi"


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
        templates = CHART_DIR / "templates"
        if templates.is_dir():
            shutil.copytree(templates, work / "templates")
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


def documents(manifest: str) -> list[str]:
    return [doc for doc in manifest.split("\n---\n") if doc.strip()]


def metadata_name(doc: str) -> str | None:
    after_kind = False
    for line in doc.splitlines():
        if line.startswith("kind:"):
            after_kind = True
            continue
        if after_kind and line.startswith("  name:"):
            return line.split(":", 1)[1].strip()
    return None


def pvc_doc(manifest: str, name: str) -> str:
    for doc in documents(manifest):
        if "kind: PersistentVolumeClaim" not in doc:
            continue
        if metadata_name(doc) == name:
            return doc
    raise SystemExit(f"rendered manifests have no PersistentVolumeClaim named {name}")


def pvc_labels(doc: str) -> dict[str, str]:
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


def pvc_spec_field(doc: str, key: str) -> str | None:
    in_spec = False
    for line in doc.splitlines():
        if line == "spec:":
            in_spec = True
            continue
        if in_spec:
            if line.startswith("  ") and not line.startswith("    "):
                field, _, value = line.strip().partition(":")
                if field == key:
                    return value.strip().strip("'\"")
            elif line and not line.startswith(" "):
                break
    return None


def pvc_names(manifest: str) -> list[str]:
    names: list[str] = []
    for doc in documents(manifest):
        if "kind: PersistentVolumeClaim" not in doc:
            continue
        name = metadata_name(doc)
        if name:
            names.append(name)
    return names


def _indented_maps(block: str, item_indent: str) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    prefix = item_indent + "- "
    child = item_indent + "  "
    for line in block.splitlines():
        if line.startswith(prefix):
            if current:
                items.append(current)
            current = {}
            rest = line[len(prefix) :]
            key, _, value = rest.partition(":")
            current[key.strip()] = value.strip()
            continue
        if current is not None and line.startswith(child):
            key, _, value = line.strip().partition(":")
            current[key] = value.strip()
    if current:
        items.append(current)
    return items


def deployment_doc(manifest: str) -> str:
    for doc in documents(manifest):
        if "kind: Deployment" in doc and metadata_name(doc) == "openclaw":
            return doc
    raise SystemExit("rendered manifests have no Deployment named openclaw")


def volume_mounts(manifest: str) -> list[dict[str, str]]:
    doc = deployment_doc(manifest)
    start = doc.find("          volumeMounts:")
    end = doc.find("      volumes:")
    if start < 0 or end < 0:
        raise SystemExit("deployment has no volumeMounts/volumes")
    return _indented_maps(doc[start:end], "            ")


def volumes(manifest: str) -> list[dict[str, str]]:
    doc = deployment_doc(manifest)
    start = doc.find("      volumes:")
    if start < 0:
        raise SystemExit("deployment has no volumes")
    return _indented_maps(doc[start:], "        ")


def main() -> int:
    manifest = render()
    data = pvc_doc(manifest, "openclaw-data")
    labels = pvc_labels(data)
    missing = [k for k, v in REQUIRED.items() if labels.get(k) != v]
    present = [k for k in FORBIDDEN if k in labels]
    if missing or present:
        print("openclaw-data labels:", labels, file=sys.stderr)
        if missing:
            print("missing or wrong:", missing, file=sys.stderr)
        if present:
            print("forbidden present:", present, file=sys.stderr)
        return 1
    if pvc_spec_field(data, "storageClassName") != DATA_STORAGE_CLASS:
        print("openclaw-data storageClassName:", pvc_spec_field(data, "storageClassName"), file=sys.stderr)
        return 1
    # size lives under spec.resources.requests.storage
    if f"storage: {DATA_SIZE}" not in data and f'storage: "{DATA_SIZE}"' not in data:
        print("openclaw-data missing size", DATA_SIZE, file=sys.stderr)
        print(data, file=sys.stderr)
        return 1
    print("openclaw-data backup labels ok")

    names = pvc_names(manifest)
    extra = [n for n in names if "state-tmp" in n]
    if extra:
        print("unexpected PVC for scratch:", extra, file=sys.stderr)
        return 1
    if "openclaw-state" not in names:
        print("keep-PVC openclaw-state missing from render", file=sys.stderr)
        return 1

    mounts = volume_mounts(manifest)
    mounts_by_name = {m.get("name"): m for m in mounts}
    state_paths = [m.get("mountPath") for m in mounts if m.get("mountPath") == STATE_MOUNT]
    if len(state_paths) != 1:
        print("volumeMounts:", mounts, file=sys.stderr)
        print(f"expected exactly one volumeMount at {STATE_MOUNT}", file=sys.stderr)
        return 1
    data_mount = mounts_by_name.get("data")
    if data_mount is None or data_mount.get("mountPath") != STATE_MOUNT:
        print("volumeMounts:", mounts, file=sys.stderr)
        print(f"missing volumeMount data at {STATE_MOUNT}", file=sys.stderr)
        return 1
    if "state" in mounts_by_name:
        print("openclaw-state must not be mounted after the local copy", file=sys.stderr)
        return 1
    scratch_mount = mounts_by_name.get("state-tmp")
    if scratch_mount is None or scratch_mount.get("mountPath") != STATE_TMP_MOUNT:
        print("volumeMounts:", mounts, file=sys.stderr)
        print(
            f"missing volumeMount state-tmp at {STATE_TMP_MOUNT}",
            file=sys.stderr,
        )
        return 1

    vols = volumes(manifest)
    vols_by_name = {v.get("name"): v for v in vols}
    scratch_vol = vols_by_name.get("state-tmp")
    if scratch_vol is None:
        print("volumes:", vols, file=sys.stderr)
        print("missing volume state-tmp", file=sys.stderr)
        return 1
    if scratch_vol.get("sizeLimit") != STATE_TMP_LIMIT:
        print("state-tmp volume:", scratch_vol, file=sys.stderr)
        print(f"state-tmp sizeLimit must be {STATE_TMP_LIMIT}", file=sys.stderr)
        return 1
    if "emptyDir" not in scratch_vol:
        print("state-tmp volume is not emptyDir:", scratch_vol, file=sys.stderr)
        return 1

    print("openclaw-state scratch emptyDir ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
