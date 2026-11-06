"""Renders the JobPilot logo to assets/jobpilot.ico (PNG-in-ICO). Run once by install-app.ps1."""
import struct
import sys
from pathlib import Path

SVG = ("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32' width='256' height='256'>"
       "<rect width='32' height='32' rx='7' fill='#4f46e5'/>"
       "<path d='M9 17l5 5 9-12' stroke='white' stroke-width='3.5' fill='none' stroke-linecap='round' stroke-linejoin='round'/></svg>")


def main(out: Path) -> None:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 256, "height": 256})
        pg.set_content(f"<body style='margin:0;background:transparent'>{SVG}</body>")
        png = pg.screenshot(omit_background=True, clip={"x": 0, "y": 0, "width": 256, "height": 256})
        b.close()
    out.parent.mkdir(parents=True, exist_ok=True)
    header = struct.pack("<HHH", 0, 1, 1)
    entry = struct.pack("<BBBBHHII", 0, 0, 0, 0, 1, 32, len(png), 22)  # 0 = 256px
    out.write_bytes(header + entry + png)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
