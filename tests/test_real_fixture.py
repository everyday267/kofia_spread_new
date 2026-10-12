"""실제 KOFIA 응답 구조(tests/fixtures)로 파서 → 이력 변환 → 대시보드 페이로드를 점검.

    python tests/test_real_fixture.py
"""
import ast, sys
from pathlib import Path
import xml.etree.ElementTree as ET

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import spread_analytics as sa, spread_dashboard as sd  # noqa: E402

# kofia_spread.py 는 import 시 바로 실행되므로 파서 함수만 떼어 실행
src = (ROOT / "kofia_spread.py").read_text(encoding="utf-8")
ns = {"pd": pd}
for node in ast.parse(src).body:
    if isinstance(node, ast.FunctionDef) and node.name in ("parse_ratings", "parse_body"):
        exec(compile(ast.Module([node], []), "kofia_spread.py", "exec"), ns)

root = ET.parse(ROOT / "tests/fixtures/kofia_tbond_sprd_3m_corp_20261012.xml").getroot()
names = ns["parse_ratings"](root)
df = ns["parse_body"](root, names)
assert names == ["AAA", "AA+", "AA", "AA-", "A+", "A", "A-", "BBB+", "BBB", "BBB-"], names
assert len(df) == 4 and df.loc[0, "기준일"] == "2026-10-12" and df.loc[0, "국고채금리"] == 3.22

long = sa.wide_to_long(df, "3")
assert set(long["date"]) == {"20261012", "20261008", "20261007", "20261006"}, "날짜 정규화 실패"
sp, gov = sa.spread_panel_bp(long, "3")
assert sp.loc["20261012", "AAA"] == 29.0 and sp.loc["20261012", "A-"] == 86.0, sp.tail(1)
assert gov.loc["20261012"] == 3.22

payload = sd.build_payload(long, "20261012")
t = payload["tenors"][0]
assert t["label"] == "3개월" and t["dates"][-1] == "20261012"
print("OK — A- 보증차익(3M, 2026-10-12):", sp.loc["20261012", "A-"] - sp.loc["20261012", "AAA"], "bp")
