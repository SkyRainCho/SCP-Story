from __future__ import annotations

import json
from pathlib import Path

from .models import PageRef

MANIFEST_FIELDS = (
    "title",
    "url",
    "slug",
    "level",
    "role",
    "parent_slug",
    "source",
    "order",
)


def merge_manifest(
    index_entries: list[PageRef],
    scp001_proposals: list[PageRef],
) -> list[PageRef]:
    """Merge index pages and SCP-001 proposals into spine order.

    If the SCP-001 hub is absent from the index sample, proposal pages are
    prepended so they remain discoverable at the beginning of the volume.
    Proposal slugs already present in the index are left in index position.
    """
    merged: list[PageRef] = []
    index_slugs = {entry.slug for entry in index_entries}
    proposals_to_insert = [
        proposal
        for proposal in scp001_proposals
        if proposal.slug not in index_slugs
    ]
    inserted_proposals = False

    for entry in index_entries:
        merged.append(entry)
        if entry.slug == "scp-001":
            merged.extend(proposals_to_insert)
            inserted_proposals = True

    if proposals_to_insert and not inserted_proposals:
        merged = [*proposals_to_insert, *merged]

    return _dedupe_and_renumber(merged)


def write_manifest(entries: list[PageRef], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [_to_manifest_dict(entry) for entry in entries]
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def read_manifest(path: Path) -> list[PageRef]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [_from_manifest_dict(entry) for entry in payload]


def _dedupe_and_renumber(entries: list[PageRef]) -> list[PageRef]:
    seen_slugs: set[str] = set()
    manifest: list[PageRef] = []

    for entry in entries:
        if entry.slug in seen_slugs:
            continue
        seen_slugs.add(entry.slug)
        manifest.append(_with_order(entry, len(manifest) + 1))

    return manifest


def _with_order(entry: PageRef, order: int) -> PageRef:
    return PageRef(
        title=entry.title,
        url=entry.url,
        slug=entry.slug,
        level=entry.level,
        role=entry.role,
        parent_slug=entry.parent_slug,
        source=entry.source,
        order=order,
        children=entry.children,
    )


def _to_manifest_dict(entry: PageRef) -> dict[str, object]:
    if entry.children:
        raise ValueError(
            f"manifest entries must be flat: {entry.slug} has children"
        )

    values = {
        "title": entry.title,
        "url": entry.url,
        "slug": entry.slug,
        "level": entry.level,
        "role": entry.role,
        "parent_slug": entry.parent_slug,
        "source": entry.source,
        "order": entry.order,
    }
    return {field: values[field] for field in MANIFEST_FIELDS}


def _from_manifest_dict(entry: dict[str, object]) -> PageRef:
    parent_slug = entry["parent_slug"]
    return PageRef(
        title=str(entry["title"]),
        url=str(entry["url"]),
        slug=str(entry["slug"]),
        level=int(entry["level"]),
        role=str(entry["role"]),
        parent_slug=parent_slug if parent_slug is None else str(parent_slug),
        source=str(entry["source"]),
        order=int(entry["order"]),
    )
