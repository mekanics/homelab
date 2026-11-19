#!/usr/bin/env python3
"""Assert the OpenClaw pod sets no fsGroup.

OpenClaw refuses to start when `<stateDir>/client` or `control` is
group-accessible, and doctor will not use an update-captures root that is
group-writable. With fsGroup set, kubelet's walk widens exactly those paths
(2770 / 660) on every mount where the volume root's mode was narrowed, and
doctor narrows the root itself. So each pod restart re-broke init-doctor.
Every mounted volume is already owned by the process uid 1024 or is a
world-writable emptyDir, so the pod does not need fsGroup to write.
"""

from __future__ import annotations

import subprocess
import sys

from test_state_pvc_backup_labels import deployment_doc, render


def pod_security_context(deployment: str) -> dict[str, object]:
    out = subprocess.run(
        ["yq", "-o=json", ".spec.template.spec.securityContext"],
        input=deployment,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    import json

    return json.loads(out) or {}


def main() -> int:
    ctx = pod_security_context(deployment_doc(render()))
    leaked = {k: v for k, v in ctx.items() if k.startswith("fsGroup")}
    if leaked:
        print("pod securityContext must not set fsGroup:", leaked, file=sys.stderr)
        return 1
    print("no fsGroup in pod securityContext:", ctx)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
