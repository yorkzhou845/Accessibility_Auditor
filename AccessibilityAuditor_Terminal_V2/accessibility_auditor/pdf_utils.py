from collections import Counter

import fitz

from . import config as cfg
from .text_features import clean_text


def get_page_count(doc):
    if cfg.MAX_PAGES is None:
        return len(doc)

    return min(len(doc), cfg.MAX_PAGES)


def bbox_to_pixels(bbox):
    x0, y0, x1, y1 = bbox

    return {
        "x": round(x0 * cfg.RENDER_SCALE),
        "y": round(y0 * cfg.RENDER_SCALE),
        "width": round((x1 - x0) * cfg.RENDER_SCALE),
        "height": round((y1 - y0) * cfg.RENDER_SCALE)
    }


def render_page(page, page_number, pdf_path):
    pix = page.get_pixmap(
        matrix=fitz.Matrix(cfg.RENDER_SCALE, cfg.RENDER_SCALE),
        alpha=False
    )

    image_path = cfg.RENDERED_FOLDER / f"{pdf_path.stem}_page_{page_number}.png"
    pix.save(image_path)

    return image_path, pix.width, pix.height


def rect_overlap_ratio(bbox, rects):
    line_rect = fitz.Rect(bbox)
    area = line_rect.get_area()

    if area <= 0:
        return 0.0

    best = 0.0

    for rect in rects:
        inter = line_rect & rect
        if not inter.is_empty:
            best = max(best, inter.get_area() / area)

    return best


def get_page_image_rects(page):
    rects = []

    for image_info in page.get_images(full=True):
        xref = image_info[0]
        for rect in page.get_image_rects(xref):
            if rect.get_area() > 0:
                rects.append(rect)

    return rects


def get_text_line_entries(page, page_number):
    entries = []
    text_dict = page.get_text("dict")
    page_rect = page.rect
    image_rects = get_page_image_rects(page)
    entry_num = 1

    for block in text_dict["blocks"]:
        if block["type"] != 0:
            continue

        for line in block["lines"]:
            parts = []
            font_sizes = []
            font_names = []
            font_flags = []
            colors = []

            for span in line["spans"]:
                span_text = span["text"].strip()

                if span_text:
                    parts.append(span_text)
                    font_sizes.append(span.get("size", 0))
                    font_names.append(span.get("font", ""))
                    font_flags.append(span.get("flags", 0))
                    colors.append(span.get("color"))

            value = clean_text(" ".join(parts))

            if value:
                font_size = max(font_sizes) if font_sizes else 0
                font_name_text = " ".join(font_names).lower()
                color_counts = Counter(colors)
                dominant_color = color_counts.most_common(1)[0][0] if color_counts else None

                # PyMuPDF flags are not always reliable across PDFs, so use
                # both flags and font-name text.
                is_bold = (
                    any((flag & 16) for flag in font_flags)
                    or "bold" in font_name_text
                    or "black" in font_name_text
                    or "semibold" in font_name_text
                )
                is_italic = any((flag & 2) for flag in font_flags) or "italic" in font_name_text

                entries.append({
                    "id": f"p{page_number}_entry_{entry_num:03d}",
                    "page_number": page_number,
                    "type": "text",
                    "value": value,
                    "font_size": font_size,
                    "font_names": sorted(set(font_names)),
                    "is_bold": is_bold,
                    "is_italic": is_italic,
                    "color": dominant_color,
                    "coordinates": bbox_to_pixels(line["bbox"]),
                    "pdf_bbox": tuple(line["bbox"]),
                    "page_width": page_rect.width,
                    "page_height": page_rect.height,
                    "image_overlap_ratio": rect_overlap_ratio(line["bbox"], image_rects)
                })

                entry_num += 1

    return entries


def get_image_entries(page):
    entries = []
    entry_num = 1

    for image_info in page.get_images(full=True):
        xref = image_info[0]
        rects = page.get_image_rects(xref)

        for rect in rects:
            entries.append({
                "id": f"entry_{entry_num:03d}",
                "type": "image",
                "xref": xref,
                "coordinates": bbox_to_pixels(rect),
                "pdf_rect": {
                    "x0": rect.x0,
                    "y0": rect.y0,
                    "x1": rect.x1,
                    "y1": rect.y1
                }
            })

            entry_num += 1

    return entries


def crop_image(page, image_entry, page_number, pdf_path):
    rect = fitz.Rect(
        image_entry["pdf_rect"]["x0"],
        image_entry["pdf_rect"]["y0"],
        image_entry["pdf_rect"]["x1"],
        image_entry["pdf_rect"]["y1"]
    )

    pix = page.get_pixmap(
        matrix=fitz.Matrix(cfg.RENDER_SCALE, cfg.RENDER_SCALE),
        clip=rect,
        alpha=False
    )

    crop_path = cfg.CROPPED_FOLDER / f"{pdf_path.stem}_page_{page_number}_{image_entry['id']}.png"
    pix.save(crop_path)

    return crop_path


def get_table_entries(page):
    entries = []
    entry_num = 1

    tables = page.find_tables().tables

    for table in tables:
        entries.append({
            "id": f"entry_{entry_num:03d}",
            "type": "table",
            "value": table.extract(),
            "coordinates": bbox_to_pixels(table.bbox)
        })

        entry_num += 1

    return entries
