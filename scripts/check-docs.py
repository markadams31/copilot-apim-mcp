"""Check the Markdown docs: every relative link and heading anchor resolves, and no page repeats a heading.

    python3 scripts/check-docs.py        # exits non-zero on a broken link or a duplicate heading

Anchors follow GitHub's rules closely enough for this repository's headings.
"""

import collections
import glob
import os
import re
import sys

os.chdir(os.path.join(os.path.dirname(__file__), ".."))
files = ["README.md", "AGENTS.md", *sorted(glob.glob("docs/*.md"))]


def slug(heading: str) -> str:
    h = re.sub(r"[`*]", "", heading.strip().lower())
    return "".join(c for c in h if c.isalnum() or c in " -_").replace(" ", "-")


anchors: dict[str, set[str]] = {}
duplicates = []
for f in files:
    text = re.sub(r"```.*?```", "", open(f).read(), flags=re.S)
    slugs = [slug(m) for m in re.findall(r"^#{1,6} (.+)$", text, re.M)]
    anchors[os.path.normpath(f)] = set(slugs)
    duplicates += [(f, k) for k, v in collections.Counter(slugs).items() if v > 1]

broken = []
for f in files:
    for link in re.findall(r"\]\(([^)\s]+)\)", open(f).read()):
        if link.startswith(("http", "mailto:")):
            continue
        path, _, fragment = link.partition("#")
        target = (
            os.path.normpath(os.path.join(os.path.dirname(f), path))
            if path
            else os.path.normpath(f)
        )
        if not os.path.exists(target) or (
            fragment and target.endswith(".md") and fragment not in anchors[target]
        ):
            broken.append((f, link))

for f, link in broken:
    print(f"BROKEN     {f}: {link}")
for f, heading in duplicates:
    print(f"DUPLICATE  {f}: {heading}")
print(f"{len(broken)} broken link(s), {len(duplicates)} duplicate heading(s)")
sys.exit(1 if broken or duplicates else 0)
