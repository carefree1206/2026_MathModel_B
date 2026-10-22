"""只读原始 DOCX，保留全部原生公式及分式、根号、上下标结构。"""
from pathlib import Path
import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "我的论文.docx"
OUT = Path(__file__).resolve().parent
NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "m": "http://schemas.openxmlformats.org/officeDocument/2006/math",
}


def structural(e):
    if e is None:
        return ""
    tag = e.tag.rsplit("}", 1)[-1]
    if tag.endswith("Pr") or tag in {"ctrlPr", "degHide", "sty", "rFonts"}:
        return ""
    if tag == "t":
        return e.text or ""
    child = lambda name: structural(e.find("m:" + name, NS))
    if tag == "f":
        return "(" + child("num") + ")/(" + child("den") + ")"
    if tag == "rad":
        degree = child("deg")
        return ("sqrt" if not degree else "root[" + degree + "]") + "(" + child("e") + ")"
    if tag in {"sSub", "sSup", "sSubSup"}:
        out = child("e")
        if tag in {"sSub", "sSubSup"}:
            out += "_{" + child("sub") + "}"
        if tag in {"sSup", "sSubSup"}:
            out += "^{" + child("sup") + "}"
        return out
    return "".join(structural(c) for c in e)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    raw = SOURCE.read_bytes()
    with zipfile.ZipFile(SOURCE) as z:
        tree = ET.fromstring(z.read("word/document.xml"))
    records = []
    numbered = []
    for pi, p in enumerate(tree.findall(".//w:p", NS), 1):
        context = "".join(e.text or "" for e in p.iter() if e.tag.rsplit("}", 1)[-1] == "t")
        maths = p.findall(".//m:oMath", NS)
        if not maths:
            continue
        match = re.search(r"\((\d{1,2})\)\s*$", context)
        number = int(match.group(1)) if match else None
        if number is not None:
            numbered.append(number)
        converted = []
        for e in maths:
            record = {
                "id": len(records) + 1,
                "paragraph_index": pi,
                "equation_number": number,
                "context": context,
                "structural_text": structural(e),
                "omml_xml": ET.tostring(e, encoding="unicode"),
            }
            records.append(record)
            converted.append(record["structural_text"])
        print(f"p{pi} / eq{number if number is not None else '-'}: " + " | ".join(converted))
    assert numbered == list(range(1, 39)), numbered
    assert len(records) == len(tree.findall(".//m:oMath", NS)) == 170
    data = {
        "source": str(SOURCE),
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "numbered_equation_count": len(numbered),
        "native_math_occurrence_count": len(records),
        "note": "170 是原生公式出现次数，包含符号、重复引用和表格公式；不是170条独立推导。结构文本是核对索引，原始OMML为排版结构依据。",
        "records": records,
    }
    (OUT / "论文公式原文清单.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nVERIFIED: 38 numbered equations; 170 native math occurrences; source left unchanged.")


if __name__ == "__main__":
    main()
