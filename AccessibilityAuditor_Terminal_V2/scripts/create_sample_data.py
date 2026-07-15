"""Create small synthetic PDFs and matching failure reports for local testing."""

from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[1]
INPUT_DIR = ROOT / "input"


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + kind
        + data
        + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    )


def create_demo_png(path: Path, width: int = 240, height: int = 120) -> None:
    rows = []
    for y in range(height):
        row = bytearray([0])
        for x in range(width):
            if 20 < x < 220 and 20 < y < 100:
                red, green, blue = (65, 120, 180)
            else:
                red, green, blue = (240, 240, 240)
            if 70 < x < 95 and 45 < y < 95:
                red, green, blue = (230, 150, 60)
            if 120 < x < 145 and 35 < y < 95:
                red, green, blue = (100, 170, 100)
            if 170 < x < 195 and 60 < y < 95:
                red, green, blue = (180, 90, 110)
            row.extend((red, green, blue))
        rows.append(bytes(row))

    raw = b"".join(rows)
    png = b"\x89PNG\r\n\x1a\n"
    png += _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    png += _png_chunk(b"IDAT", zlib.compress(raw, 9))
    png += _png_chunk(b"IEND", b"")
    path.write_bytes(png)


def create_alt_text_pdf(image_path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 72), "Quarterly Activity Overview", fontsize=22)
    page.insert_text(
        (72, 105),
        "The chart below is synthetic sample content created only for local testing.",
        fontsize=11,
    )
    page.insert_image(fitz.Rect(72, 140, 432, 320), filename=str(image_path))
    doc.save(INPUT_DIR / "sample_alt_text.pdf")
    doc.close()
    (INPUT_DIR / "sample_alt_text_Failure_Report.txt").write_text(
        "A meaningful figure is missing alternative text.",
        encoding="utf-8",
    )


def create_table_pdf() -> None:
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 72), "Sample Project Status", fontsize=22)

    left, top = 72, 130
    widths = [160, 110, 110]
    row_height = 34
    rows = [
        ["Workstream", "Owner", "Status"],
        ["Design", "Team A", "Complete"],
        ["Testing", "Team B", "In progress"],
        ["Documentation", "Team C", "Planned"],
    ]

    x_positions = [left]
    for width in widths:
        x_positions.append(x_positions[-1] + width)
    y_positions = [top + index * row_height for index in range(len(rows) + 1)]

    for x in x_positions:
        page.draw_line((x, y_positions[0]), (x, y_positions[-1]), width=1)
    for y in y_positions:
        page.draw_line((x_positions[0], y), (x_positions[-1], y), width=1)

    for row_index, row in enumerate(rows):
        for column_index, value in enumerate(row):
            page.insert_text(
                (x_positions[column_index] + 6, y_positions[row_index] + 22),
                value,
                fontsize=10,
            )

    doc.save(INPUT_DIR / "sample_table.pdf")
    doc.close()
    (INPUT_DIR / "sample_table_Failure_Report.txt").write_text(
        "The data table needs clearer headers and a concise table summary.",
        encoding="utf-8",
    )


def create_heading_pdf() -> None:
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 72), "Sample Accessibility Review", fontsize=24)
    page.insert_text((72, 120), "Purpose", fontsize=17)
    page.insert_text(
        (72, 145),
        "This synthetic document demonstrates heading candidate detection.",
        fontsize=11,
    )
    page.insert_text((72, 195), "Review Steps", fontsize=17)
    page.insert_text((88, 225), "1. Inspect the document", fontsize=13)
    page.insert_text((88, 250), "2. Review suggested changes", fontsize=13)
    doc.save(INPUT_DIR / "sample_headings.pdf")
    doc.close()
    (INPUT_DIR / "sample_headings_Failure_Report.txt").write_text(
        "The document heading hierarchy and heading sequence need review.",
        encoding="utf-8",
    )


def main() -> int:
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    image_path = INPUT_DIR / "sample_chart.png"
    create_demo_png(image_path)
    create_alt_text_pdf(image_path)
    create_table_pdf()
    create_heading_pdf()
    image_path.unlink(missing_ok=True)
    print(f"Created synthetic test files in {INPUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
