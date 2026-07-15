from .text_features import clean_heading_label


def normalize_tag(tag):
    tag = str(tag or "").lower().strip()
    return tag if tag in {"h1", "h2", "h3"} else None


def tag_level(tag):
    return int(tag[1])


def repair_heading_sequence(script):
    repaired = []

    for item in script:
        tag = normalize_tag(item.get("tag")) or "h2"
        level = tag_level(tag)

        if not repaired:
            # PAC/UA rule: if headings are used, first heading must be H1.
            level = 1
        else:
            previous_level = tag_level(repaired[-1]["tag"])
            if level > previous_level + 1:
                level = previous_level + 1

        fixed = dict(item)
        fixed["tag"] = f"h{level}"
        repaired.append(fixed)

    return repaired


def make_fallback_remediation_script(heading_candidates):
    script = []

    for entry in heading_candidates:
        text = clean_heading_label(entry["value"])
        tag = normalize_tag(entry.get("fallback_tag")) or "h2"

        if not text:
            continue

        item = {
            "page_number": entry["page_number"],
            "source_entry_id": entry["id"],
            "tag": tag,
            "text": text,
            "coordinates": entry["coordinates"]
        }

        if entry.get("merged_entry_ids"):
            item["source_entry_ids"] = entry["merged_entry_ids"]

        script.append(item)

    return repair_heading_sequence(script)


def validate_llm_remediation_script(ai, heading_candidates):
    candidates_by_id = {c["id"]: c for c in heading_candidates}
    output = []
    seen_ids = set()

    raw_script = ai.get("remediation_script", [])
    if not isinstance(raw_script, list):
        return []

    for item in raw_script:
        if not isinstance(item, dict):
            continue

        source_id = item.get("source_entry_id")
        if source_id in seen_ids:
            continue

        candidate = candidates_by_id.get(source_id)
        if candidate is None:
            continue

        text = clean_heading_label(candidate["value"])
        if not text:
            continue

        tag = normalize_tag(item.get("tag")) or normalize_tag(candidate.get("fallback_tag")) or "h2"

        out_item = {
            "page_number": candidate["page_number"],
            "source_entry_id": candidate["id"],
            "tag": tag,
            "text": text,
            "coordinates": candidate["coordinates"]
        }
        if candidate.get("merged_entry_ids"):
            out_item["source_entry_ids"] = candidate["merged_entry_ids"]
        output.append(out_item)
        seen_ids.add(source_id)

    output.sort(key=lambda e: (e["page_number"], e["coordinates"]["y"], e["coordinates"]["x"]))
    return repair_heading_sequence(output)
