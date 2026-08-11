"""AX_Award_지원서.html -> A4 PDF + 페이지별 PNG. 인쇄 경로(@page)로 실제 출력물을 확인한다."""
import pathlib, asyncio
from playwright.async_api import async_playwright

HERE = pathlib.Path(__file__).parent
SRC = HERE / "AX_Award_지원서.html"
PNG = HERE / "preview"
PNG.mkdir(exist_ok=True)


async def main():
    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        pg = await b.new_page(viewport={"width": 900, "height": 1200}, device_scale_factor=2)
        await pg.goto(SRC.as_uri())
        await pg.wait_for_timeout(600)

        await pg.pdf(path=str(HERE / "AX_Award_지원서.pdf"),
                     format="A4", print_background=True,
                     margin={"top": "0", "bottom": "0", "left": "0", "right": "0"})

        for i, el in enumerate(await pg.query_selector_all("section.page"), 1):
            await el.screenshot(path=str(PNG / f"page{i}.png"))
        print("PDF + PNG 5장 완료 ->", HERE)
        await b.close()

asyncio.run(main())
