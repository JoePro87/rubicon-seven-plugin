"""Reconstruct the ancestry spark tables from the raw geometry dump (pass 2).

Cells are CENTERED per column (x0 varies row to row), so header x0s can't bin them.
Method per table region (anchored by each 'd20' header word):
1. Row anchors = the literal 1..20 in the d20 column.
2. Learn column centers from 'clean' single-line rows whose word count equals the
   header count - each position's x-center, averaged.
3. Assign EVERY cell word (including wrapped lines) to its nearest row anchor (by
   top) and nearest learned column center (by x-center).
4. Join words per (row, column) in reading order; de-squish CamelCase.

Output: docs/superpowers/plans/data/ancestry_sparks_tables.json for hand-verification.
"""
import json
import re
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "docs" / "superpowers" / "plans" / "data"


def decamel(s):
    s = re.sub(r"(?<=[a-z’'])(?=[A-Z])", " ", s)
    return s


def rebuild_page(words):
    d20s = sorted([w for w in words if w["text"] == "d20"], key=lambda w: w["top"])
    tables = []
    for ti, d in enumerate(d20s):
        top_lim = d["top"] - 2
        bot_lim = d20s[ti + 1]["top"] - 4 if ti + 1 < len(d20s) else 10**6
        region = [w for w in words if top_lim <= w["top"] < bot_lim]
        headers = sorted([w for w in region
                          if abs(w["top"] - d["top"]) < 3 and w["text"] != "d20"],
                         key=lambda w: w["x0"])
        ncols = len(headers)
        if not ncols:
            continue
        col_names = [h["text"] for h in headers]

        anchors = {}
        for w in region:
            if w["text"].isdigit() and 1 <= int(w["text"]) <= 20 \
               and abs(w["x0"] - d["x0"]) < 18 and w["top"] > d["top"] + 2:
                anchors[int(w["text"])] = w["top"]
        if not anchors:
            continue

        def is_anchor(w):
            return (w["text"].isdigit() and int(w["text"]) in anchors
                    and abs(anchors[int(w["text"])] - w["top"]) < 1
                    and abs(w["x0"] - d["x0"]) < 18)

        cell_words = [w for w in region
                      if w not in headers and w["text"] != "d20" and not is_anchor(w)]

        # learn column centers from clean rows (exact-count, same-line)
        center_samples = [[] for _ in range(ncols)]
        for r, atop in anchors.items():
            line = sorted([w for w in cell_words if abs(w["top"] - atop) < 4],
                          key=lambda w: w["x0"])
            if len(line) == ncols:
                for i, w in enumerate(line):
                    center_samples[i].append((w["x0"] + w["x1"]) / 2)
        if not all(center_samples):
            # fall back to header centers for any column never seen clean
            for i, h in enumerate(headers):
                if not center_samples[i]:
                    center_samples[i].append((h["x0"] + h["x1"]) / 2)
        centers = [sum(c) / len(c) for c in center_samples]

        cells = {}
        for w in cell_words:
            row = min(anchors, key=lambda r: abs(anchors[r] - w["top"]))
            if abs(anchors[row] - w["top"]) > 12:
                continue  # footer/legend noise
            wc = (w["x0"] + w["x1"]) / 2
            ci = min(range(ncols), key=lambda i: abs(centers[i] - wc))
            cells.setdefault((row, ci), []).append(w)

        rows = {}
        for (row, ci), ws in cells.items():
            ws.sort(key=lambda w: (w["top"], w["x0"]))
            rows.setdefault(row, {})[col_names[ci]] = decamel(
                " ".join(w["text"] for w in ws))
        tables.append({"columns": col_names,
                       "rows": {str(r): rows.get(r, {}) for r in range(1, 21)}})
    return tables


def main():
    raw = json.loads((DATA / "ancestry_sparks_raw.json").read_text(encoding="utf-8"))
    out = {}
    for key, page in raw["tables"].items():
        out[key] = {"page_index": page["page_index"],
                    "tables": rebuild_page(page["words"])}
        for t in out[key]["tables"]:
            missing = [r for r, cols in t["rows"].items()
                       if len(cols) != len(t["columns"])]
            print(f"{key:16} cols={t['columns']} incomplete_rows={missing or 'OK'}")
    (DATA / "ancestry_sparks_tables.json").write_text(
        json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
