#!/usr/bin/env python3
"""Copy the Zircon audit assets into a static site and add its review entry point."""
from __future__ import annotations

import argparse
import html
import json
import re
import shutil
from pathlib import Path

ASSETS = (
    "zircon-audit.html",
    "assets/zircon-audit.css",
    "assets/zircon-name-bridge.css",
    "scripts/zircon-audit.js",
    "scripts/zircon-name-bridge.js",
    "data/zircon_name_audit.json",
    "data/zircon_name_index.json",
)
CACHE_VERSION = "3"


def _site_prefix(base: str) -> str:
    value = base.strip()
    if any(char in value for char in ("?", "#", "\\")) or "://" in value:
        raise ValueError("--base must be a site path such as '' or '/mir2ei'")
    return "/" + value.strip("/") + "/" if value.strip("/") else "/"


def _integrate_html(text: str, prefix: str, include_bridge: bool, audit_version: str) -> tuple[str, bool]:
    nav_changed = False
    nav_link = f'<a href="{html.escape(prefix + "zircon-audit.html", quote=True)}" data-zircon-audit-nav>名称审校</a>'
    nav_pattern = re.compile(r'<a\b(?=[^>]*\bdata-zircon-audit-nav\b)[^>]*>.*?</a>', re.IGNORECASE | re.DOTALL)
    existing_nav = nav_pattern.search(text)
    if existing_nav:
        updated_nav = re.sub(r'\bhref="[^"]*"', f'href="{html.escape(prefix + "zircon-audit.html", quote=True)}"',
                             existing_nav.group(0), count=1, flags=re.IGNORECASE)
        text = text[:existing_nav.start()] + updated_nav + text[existing_nav.end():]
    else:
        text, count = re.subn(r"</nav\s*>", nav_link + "</nav>", text, count=1, flags=re.IGNORECASE)
        nav_changed = count == 1

    if include_bridge:
        css = f'<link rel="stylesheet" href="{prefix}assets/zircon-name-bridge.css?v={CACHE_VERSION}" data-zircon-name-bridge-css>'
        js = (f'<script src="{prefix}scripts/zircon-name-bridge.js?v={CACHE_VERSION}&amp;build={html.escape(audit_version, quote=True)}" '
              f'data-site-base="{html.escape(prefix, quote=True)}" data-zircon-name-bridge defer></script>')
        css_pattern = re.compile(r'<link\b(?=[^>]*\bdata-zircon-name-bridge-css\b)[^>]*>', re.IGNORECASE | re.DOTALL)
        script_pattern = re.compile(r'<script\b(?=[^>]*\bdata-zircon-name-bridge\b)[^>]*>.*?</script>',
                                    re.IGNORECASE | re.DOTALL)
        if css_pattern.search(text):
            text = css_pattern.sub(css, text, count=1)
        else:
            text, _ = re.subn(r"</head\s*>", css + "</head>", text, count=1, flags=re.IGNORECASE)
        if script_pattern.search(text):
            text = script_pattern.sub(js, text, count=1)
        else:
            text, _ = re.subn(r"</body\s*>", js + "</body>", text, count=1, flags=re.IGNORECASE)
    return text, nav_changed


def integrate_site(source_root: Path | str, site_root: Path | str, base: str = "") -> dict[str, int]:
    source = Path(source_root).resolve()
    site = Path(site_root).resolve()
    prefix = _site_prefix(base)
    copied = 0
    for relative in ASSETS:
        origin = source / relative
        if not origin.is_file():
            raise FileNotFoundError(f"required Zircon audit asset is missing: {relative}")
        destination = site / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if origin.resolve() != destination.resolve():
            shutil.copy2(origin, destination)
            copied += 1
    audit = json.loads((site / "data/zircon_name_audit.json").read_text(encoding="utf-8"))
    audit_version = str(audit.get("build_fingerprint") or "")[:16]
    if not re.fullmatch(r"[0-9a-fA-F]{16}", audit_version):
        raise ValueError("audit JSON has no valid build_fingerprint")

    updated = 0
    nav_missing = 0
    scanned = 0
    audit_page = site / "zircon-audit.html"
    for page in sorted(site.rglob("*.html")):
        if any(part.startswith(".") for part in page.relative_to(site).parts):
            continue
        scanned += 1
        with page.open("r", encoding="utf-8", newline="") as source_html:
            original = source_html.read()
        include_bridge = page.resolve() != audit_page.resolve()
        integrated, nav_changed = _integrate_html(original, prefix, include_bridge, audit_version)
        if not nav_changed and "<nav" in original.lower() and "data-zircon-audit-nav" not in original:
            nav_missing += 1
        if integrated != original:
            with page.open("w", encoding="utf-8", newline="") as target_html:
                target_html.write(integrated)
            updated += 1

    return {"assets_copied": copied, "pages_scanned": scanned,
            "pages_updated": updated, "pages_without_navigation": nav_missing}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--site-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--base", default="", help="Static-site URL prefix, e.g. /mir2ei")
    args = parser.parse_args()
    result = integrate_site(args.source_root, args.site_root, args.base)
    print("Integrated Zircon name audit: " + ", ".join(f"{key}={value}" for key, value in result.items()))


if __name__ == "__main__":
    main()
