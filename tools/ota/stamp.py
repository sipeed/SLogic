#!/usr/bin/env python3
"""Stamp asset URLs in the pages with content hashes.

Browsers cache style.css and the JS modules; after an update a page could run
new code against stale modules (or the reverse) and break. Each page carries
an import map that points every module at `src/x.js?v=<hash>` and links
`style.css?v=<hash>`, so changed files always load fresh.

    python3 stamp.py          rewrite index.html and batch.html
    python3 stamp.py --check  exit 1 if a stamp is out of date (used by the tests)
"""
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PAGES = ["index.html", "batch.html"]
BEGIN = "<!-- stamp:begin (python3 stamp.py) -->"
END = "<!-- stamp:end -->"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()[:10]


def block():
    imports = {f"./src/{p.name}": f"./src/{p.name}?v={digest(p)}"
               for p in sorted((ROOT / "src").glob("*.js"))}
    css = f"style.css?v={digest(ROOT / 'style.css')}"
    importmap = json.dumps({"imports": imports}, indent=2).replace("\n", "\n  ")
    return (f"{BEGIN}\n  <link rel=\"stylesheet\" href=\"{css}\" />\n"
            f"  <script type=\"importmap\">\n  {importmap}\n  </script>\n  {END}")


def main():
    check = "--check" in sys.argv
    stale = []
    new = block()
    for name in PAGES:
        path = ROOT / name
        text = path.read_text()
        out = re.sub(re.escape(BEGIN) + r".*?" + re.escape(END), lambda _: new, text, flags=re.S)
        if BEGIN not in text:
            sys.exit(f"{name}: stamp markers missing")
        if out != text:
            stale.append(name)
            if not check:
                path.write_text(out)
    if check and stale:
        sys.exit(f"stale asset stamps in {', '.join(stale)}: run python3 tools/ota/stamp.py")
    print("stamps up to date" if check else f"stamped {', '.join(PAGES)}")


if __name__ == "__main__":
    main()
