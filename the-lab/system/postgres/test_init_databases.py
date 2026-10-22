#!/usr/bin/env python3
"""Assert the shared Postgres chart provisions the n8n vector store.

The init Job must install pgvector only in n8n_vectors (the extension is not
trusted, so n8n's role cannot CREATE EXTENSION itself), the Cluster must own
that database's role, and the unused rag_obsidian database must be gone.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

CHART_DIR = Path(__file__).resolve().parent

VECTOR_EXTENSION = (
    'psql -h postgres-cluster-rw -U postgres -d n8n_vectors -c '
    '"CREATE EXTENSION IF NOT EXISTS vector"'
)
VECTOR_SECRET = "pg-n8n-vectors-credentials"
NO_EXTENSION_DATABASES = ("n8n", "paperless")


def render() -> str:
    templated = subprocess.run(
        ["helm", "template", "postgres", str(CHART_DIR), "--namespace", "postgres"],
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


def document(manifest: str, kind: str, name: str) -> str:
    for doc in documents(manifest):
        if kind_name(doc) == (kind, name):
            return doc
    raise SystemExit(f"rendered manifests have no {kind} named {name}")


def database_blocks(script: str) -> dict[str, str]:
    parts = re.split(r'echo "Ensuring database \'([^\']+)\'', script)
    blocks: dict[str, str] = {}
    # parts[0] is the preamble; then name, body, name, body, ...
    for index in range(1, len(parts), 2):
        blocks[parts[index]] = parts[index + 1]
    return blocks


def managed_roles(cluster: str) -> dict[str, str]:
    roles = re.findall(
        r"- name: ([a-z0-9_]+)\n(?:        .*\n)*?        passwordSecret:\n          name: (\S+)",
        cluster,
    )
    return dict(roles)


def main() -> int:
    manifest = render()
    job = document(manifest, "Job", "postgres-init-databases")
    cluster = document(manifest, "Cluster", "postgres-cluster")
    blocks = database_blocks(job)
    roles = managed_roles(cluster)
    failed = False

    vector_block = blocks.get("n8n_vectors", "")
    if VECTOR_EXTENSION not in vector_block:
        print(
            f"n8n_vectors init block missing {VECTOR_EXTENSION!r}",
            file=sys.stderr,
        )
        failed = True

    for database in NO_EXTENSION_DATABASES:
        block = blocks.get(database)
        if block is None:
            print(f"init Job does not ensure database {database!r}", file=sys.stderr)
            failed = True
            continue
        if "CREATE EXTENSION" in block:
            print(
                f"{database} init block must not install extensions",
                file=sys.stderr,
            )
            failed = True

    if roles.get("n8n_vectors") != VECTOR_SECRET:
        print(
            f"n8n_vectors role secret: {roles.get('n8n_vectors')!r} (want {VECTOR_SECRET!r})",
            file=sys.stderr,
        )
        failed = True

    if "rag_obsidian" in job or "rag_obsidian" in cluster:
        print("rag_obsidian must not be in the init Job or Cluster roles", file=sys.stderr)
        failed = True
    if "pg-rag-obsidian-credentials" in manifest:
        print("pg-rag-obsidian-credentials must not be rendered", file=sys.stderr)
        failed = True

    sealed_docs = [
        doc
        for doc in documents(manifest)
        if doc.count("apiVersion:") == 1 and kind_name(doc) == ("SealedSecret", VECTOR_SECRET)
    ]
    if len(sealed_docs) != 1:
        print(
            f"want one SealedSecret manifest named {VECTOR_SECRET}, found {len(sealed_docs)}",
            file=sys.stderr,
        )
        failed = True
    elif "reflection-auto-namespaces: n8n" not in sealed_docs[0]:
        print(f"{VECTOR_SECRET} must be reflected into the n8n namespace", file=sys.stderr)
        failed = True

    storage = re.search(
        r"storageClass: longhorn-postgres\n\s+size: (\S+)",
        cluster,
    )
    size = storage.group(1) if storage else None
    if size != "10Gi":
        print(f"cluster storage size: {size!r} (want '10Gi')", file=sys.stderr)
        failed = True

    if failed:
        return 1
    print("postgres init databases ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
