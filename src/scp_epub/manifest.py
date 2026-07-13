from __future__ import annotations

import json
from pathlib import Path
import re

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
SCP_SLUG_RE = re.compile(r"^scp-(?P<number>\d{3,4})$", re.IGNORECASE)


def supplement_missing_scp_entries(
    index_entries: list[PageRef],
    series_entries: list[PageRef],
) -> list[PageRef]:
    existing_slugs = {entry.slug for entry in index_entries}
    missing = [
        entry
        for entry in series_entries
        if entry.slug not in existing_slugs and _scp_number(entry.slug) is not None
    ]
    missing.sort(key=lambda entry: _scp_number(entry.slug) or 0)
    if not missing:
        return _dedupe_and_renumber(index_entries)

    grouped_entries = _top_level_groups(index_entries)
    output: list[PageRef] = []
    missing_index = 0

    for group in grouped_entries:
        root_number = _scp_number(group[0].slug)
        if root_number is not None:
            while missing_index < len(missing) and (_scp_number(missing[missing_index].slug) or 0) < root_number:
                output.append(missing[missing_index])
                missing_index += 1
        output.extend(group)

    output.extend(missing[missing_index:])
    return _dedupe_and_renumber(output)


def merge_manifest(
    index_entries: list[PageRef],
    scp001_proposals: list[PageRef],
) -> list[PageRef]:
    """Merge index pages and SCP-001 proposals into spine order.

    If the SCP-001 hub is absent from the index sample, proposal pages are
    prepended so they remain discoverable at the beginning of the volume.
    SCP-001 proposal order follows the SCP-001 hub list. Proposal slugs already
    present in the index keep their index metadata and child groups but move
    into hub order.
    """
    if not scp001_proposals:
        return _dedupe_and_renumber(index_entries)

    grouped_entries = _top_level_groups(index_entries)
    indexed_groups_by_slug: dict[str, list[PageRef]] = {}
    proposal_block: list[PageRef] = []
    proposal_slugs: set[str] = set()

    for proposal in scp001_proposals:
        proposal_slugs.add(proposal.slug)

    for group in grouped_entries:
        root = group[0]
        if root.slug in proposal_slugs:
            indexed_groups_by_slug.setdefault(root.slug, group)

    emitted_proposals: set[str] = set()
    for proposal in scp001_proposals:
        if proposal.slug in emitted_proposals:
            continue
        emitted_proposals.add(proposal.slug)
        if proposal_group := indexed_groups_by_slug.get(proposal.slug):
            proposal_block.append(_as_top_level_scp001_proposal(proposal_group[0]))
            proposal_block.extend(proposal_group[1:])
            continue
        proposal_block.append(_as_top_level_scp001_proposal(proposal))

    merged: list[PageRef] = []
    inserted_proposals = False

    for group in grouped_entries:
        root = group[0]
        if root.slug in proposal_slugs:
            continue

        merged.extend(group)
        if root.slug == "scp-001":
            merged.extend(proposal_block)
            inserted_proposals = True

    if proposal_block and not inserted_proposals:
        merged = [*proposal_block, *merged]

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


def _top_level_groups(entries: list[PageRef]) -> list[list[PageRef]]:
    groups: list[list[PageRef]] = []
    current_group: list[PageRef] = []

    for entry in entries:
        if entry.level == 1 and entry.parent_slug is None:
            if current_group:
                groups.append(current_group)
            current_group = [entry]
            continue

        if not current_group:
            current_group = [entry]
            continue

        current_group.append(entry)

    if current_group:
        groups.append(current_group)
    return groups


def _scp_number(slug: str) -> int | None:
    match = SCP_SLUG_RE.match(slug)
    if not match:
        return None
    return int(match.group("number"))


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


def _as_top_level_scp001_proposal(entry: PageRef) -> PageRef:
    return PageRef(
        title=entry.title,
        url=entry.url,
        slug=entry.slug,
        level=1,
        role=entry.role,
        parent_slug=None,
        source=entry.source,
        order=entry.order,
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
    if entry.get("children"):
        raise ValueError(
            f"manifest entries must be flat: {entry.get('slug', '<unknown>')} has children"
        )

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
