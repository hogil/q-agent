"""K(확대율) 후보를 돌려 페이지별 채움률·넘침을 실측한다. 넘치지 않는 최대 K 를 고르기 위한 것."""
import subprocess, sys, pathlib, asyncio
from playwright.async_api import async_playwright

HERE = pathlib.Path(__file__).parent
CANDS = [float(x) for x in sys.argv[1:]] or [1.00, 1.10, 1.20, 1.25, 1.30, 1.33]


async def probe(pw, k: float):
    subprocess.run([sys.executable, str(HERE / "build_html.py"), str(k)],
                   check=True, capture_output=True)
    b = await pw.chromium.launch()
    pg = await b.new_page(viewport={"width": 900, "height": 1200})
    await pg.goto((HERE / "AX_Award_지원서.html").as_uri())
    await pg.wait_for_timeout(400)
    # 마지막 표를 바닥까지 늘리는 규칙을 잠시 끈다 — 안 끄면 '채움'이 늘 100% 로 나온다.
    await pg.add_style_tag(content=
        "section.page > .fit > table:last-of-type{flex:0 0 auto !important}")
    await pg.wait_for_timeout(200)
    # 주의: .fit 이 transform:scale 이라 자식의 getBoundingClientRect 는 '확대된' 좌표를
    # 준다. clientHeight 는 확대 전 좌표다 — 섞으면 안 되므로 k 로 되돌린다.
    rows = await pg.evaluate("""(k) => [...document.querySelectorAll('section.page > .fit')].map(f => {
        let bottom = 0;
        const base = f.getBoundingClientRect().top;
        for (const el of f.querySelectorAll('*')) {
          if (el.style && el.style.position === 'absolute') continue;
          const r = el.getBoundingClientRect();
          if (r.height && r.bottom - base > bottom) bottom = r.bottom - base;
        }
        return { used: Math.round(bottom / k), box: Math.round(f.clientHeight),
                 scrollH: Math.round(f.scrollHeight) };
      })""", k)
    await b.close()
    return rows

async def main():
    async with async_playwright() as pw:
        for k in CANDS:
            rows = await probe(pw, k)
            fills, overs = [], []
            for r in rows:
                usable = r["box"] - 52          # 하단 padding
                fills.append(r["used"] / usable * 100)
                overs.append(r["scrollH"] - r["box"])
            print(f"K={k:<5}  채움 " + " ".join(f"{f:5.1f}%" for f in fills)
                  + "   넘침 " + " ".join(f"{o:>4}" for o in overs)
                  + ("   <-- 넘침" if max(overs) > 0 else ""))

asyncio.run(main())
