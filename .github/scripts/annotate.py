"""Turn test/build failures into GitHub annotations (visible in the Checks UI and API).

usage: python annotate.py junit <file.xml>   |   python annotate.py log <build.log>
"""
import re
import sys
import xml.etree.ElementTree as ET


def esc(s: str) -> str:
    return s.replace("%", "%25").replace("\r", "").replace("\n", "%0A")[:3500]


mode, path = sys.argv[1], sys.argv[2]
n = 0
if mode == "junit":
    for case in ET.parse(path).iter("testcase"):
        for bad in list(case.findall("failure")) + list(case.findall("error")):
            n += 1
            text = (bad.get("message") or "") + "\n" + (bad.text or "")[-2500:]
            print(f"::error title={case.get('classname')}.{case.get('name')}::{esc(text)}")
else:
    pat = re.compile(r"^(e: .*|.*error:.*|.*FAILED.*|.*What went wrong.*|.*Exception.*)$")
    lines = open(path, encoding="utf-8", errors="replace").read().splitlines()
    for i, line in enumerate(lines):
        if pat.match(line.strip()) and n < 40:
            n += 1
            print(f"::error title=build::{esc(chr(10).join(lines[i:i + 4]))}")
print(f"{n} problem(s) annotated")
