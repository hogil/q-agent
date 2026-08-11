"""문서에 실제로 쓰인 글자만 남긴 Noto Sans KR 서브셋(WOFF2) 을 만든다.

사내 PC 에 Noto Sans KR 이 없으면 Malgun Gothic 으로 떨어지고, 자간이 달라져
페이지가 넘칠 수 있다. 폰트를 HTML 안에 심어 어디서 열어도 같은 결과가 나오게 한다.
가변 폰트라 wght 축을 살려두면 400/700/900 을 파일 하나로 덮는다.
"""
import re, base64, pathlib
from fontTools import subset
from fontTools.ttLib import TTFont

HERE = pathlib.Path(__file__).parent
SRC_FONT = pathlib.Path(r"C:\Windows\Fonts\NotoSansKR-VF.ttf")
OUT = HERE / "noto-subset.woff2"

html = (HERE / "ax_dc.html").read_text(encoding="utf-8")
html = re.sub(r"<sc-if\b.*?</sc-if>", "", html, flags=re.S)
text = re.sub(r"<[^>]+>", " ", html)                     # 태그 제거
text = re.sub(r"&[a-z]+;|&#\d+;", " ", text)             # 엔티티 제거
chars = set(text) | set(
    "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    " .,:;!?()[]{}<>/\\|-–—_+=*&%#@'\"·…→←↑↓⇢▶●○◆■□✓✕×Δ~"
)
chars = {c for c in chars if c.isprintable() and c != " "} | {" "}
print(f"고유 글자 {len(chars)}자")

opts = subset.Options()
opts.layout_features = ["*"]
opts.name_IDs = ["*"]
opts.notdef_outline = True
opts.recalc_bounds = True
opts.drop_tables = []                    # 가변 축(fvar/gvar/HVAR) 유지
opts.flavor = "woff2"

font = TTFont(str(SRC_FONT))
subsetter = subset.Subsetter(options=opts)
subsetter.populate(text="".join(sorted(chars)))
subsetter.subset(font)
font.flavor = "woff2"
font.save(str(OUT))

b = OUT.read_bytes()
print(f"{SRC_FONT.stat().st_size/1e6:.1f}MB -> {len(b)/1024:.0f}KB "
      f"(base64 {len(base64.b64encode(b))/1024:.0f}KB)")
(HERE / "noto-subset.b64").write_text(base64.b64encode(b).decode(), encoding="utf-8")
