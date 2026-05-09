"""
Record tutorial screen captures using Playwright.
v3: Accurate workflow demos per user feedback.

Requires WebUI running: python GUI/launcher.py
Usage: .venv/Scripts/python record_tutorial.py
"""
import asyncio, json, os
from playwright.async_api import async_playwright

ROOT = os.path.dirname(os.path.abspath(__file__))
TIMING_PATH = os.path.join(ROOT, "narration", "timing.json")
VIDEO_DIR = os.path.join(ROOT)
BASE_URL = "http://localhost:5173"
W, H = 1920, 1080

def _clean_recordings():
    for f in os.listdir(VIDEO_DIR):
        if f.endswith(".webm") and not f.startswith("_"):
            os.remove(os.path.join(VIDEO_DIR, f))

CURSOR_CSS = """
(() => {
  const s = document.createElement('style');
  s.textContent = '* { cursor: none !important; }';
  document.documentElement.appendChild(s);
  const d = document.createElement('div');
  d.id = 'fc';
  d.innerHTML = '<svg width="32" height="32" viewBox="0 0 24 24"><defs><filter id="sh"><feDropShadow dx="1.5" dy="1.5" stdDeviation="1" flood-opacity="0.5"/></filter></defs><path d="M3 3l6 18 2-6 6-2z" fill="#fff" stroke="#333" stroke-width="1.8" filter="url(#sh)"/></svg>';
  d.style.cssText = 'position:fixed;z-index:99999;pointer-events:none;left:0;top:0;width:32px;height:32px;transform:translate(-6px,-6px)';
  document.body.appendChild(d);
})()
"""

async def wait(ms: float):
    await asyncio.sleep(ms / 1000)

async def move_to(page, x: float, y: float):
    await page.mouse.move(x, y)
    try: await page.evaluate(f"fc.style.left='{x}px';fc.style.top='{y}px'")
    except: pass

async def smooth_move(page, x1, y1, x2, y2, steps=15):
    for i in range(steps + 1):
        t = i / steps; et = 1 - (1 - t) ** 3
        await move_to(page, x1 + (x2 - x1) * et, y1 + (y2 - y1) * et)
        await asyncio.sleep(0.012)

async def hover_el(page, locator, hold=0.5):
    try:
        box = await locator.bounding_box()
        if box:
            x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
            await smooth_move(page, W // 2, H // 2, x, y)
            await wait(hold * 1000)
    except: pass

async def click_el(page, locator):
    await hover_el(page, locator, 0.3)
    try: await locator.click()
    except: pass
    await wait(400)

async def setup_page(page):
    await page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
    await page.evaluate(CURSOR_CSS)
    await wait(800)

async def idle_pan(page, duration_ms):
    if duration_ms <= 0: return
    cycles = max(1, int(duration_ms / 4000))
    pc = duration_ms / cycles
    for _ in range(cycles):
        await page.evaluate("window.scrollBy(0, 20)"); await wait(pc * 0.4)
        await page.evaluate("window.scrollBy(0, -15)"); await wait(pc * 0.4)
        await page.evaluate("window.scrollBy(0, -5)"); await wait(pc * 0.2)

async def select_file(page, filename):
    btn = page.get_by_role("button", name="选择文件").first
    await click_el(page, btn)
    await wait(600)
    dlg = page.locator('[role="dialog"]')
    if await dlg.is_visible():
        fb = dlg.get_by_role("button", name=filename)
        if await fb.is_visible(): await click_el(page, fb); await wait(500)

async def click_sidebar(page, tab_name):
    """Click a sidebar navigation tab by label."""
    tab = page.get_by_role("button", name=tab_name)
    if await tab.count() > 0:
        await click_el(page, tab.first)
        await wait(500)

# ====================================================================
# Section recording functions
# ====================================================================

async def rec_intro(page, duration_s):
    """sec00: Opening intro — show main UI static with project name."""
    await setup_page(page)
    await wait(1000)
    # Gentle pan across the main UI
    await page.evaluate("window.scrollTo(0, 0)")
    await wait(2000)
    await page.evaluate("window.scrollTo(0, 100)")
    await wait(1500)
    await page.evaluate("window.scrollTo(0, 0)")
    remaining = max(0, duration_s - 6) * 1000
    await idle_pan(page, remaining)


async def rec_hook(page, duration_s):
    """sec01: Select file, click start, then tour sidebar tabs."""
    await setup_page(page)

    # Select a file to show the workflow starts here
    await select_file(page, "test.mp4")
    await wait(600)

    # Hover on start button to draw attention
    start = page.get_by_role("button", name="开始处理")
    if await start.is_visible(): await hover_el(page, start, 2.0)

    # Tour sidebar tabs: click through them
    for tab in ["步骤配置", "工具栏", "字幕校准", "主界面"]:
        await click_sidebar(page, tab)
        await wait(800)

    remaining = max(0, duration_s - 14) * 1000
    await idle_pan(page, remaining)


async def rec_api_config(page, duration_s):
    """sec02: Navigate to step config panel, open API dialog, switch providers."""
    await setup_page(page)

    # Click "步骤配置" in sidebar
    await click_sidebar(page, "步骤配置")
    await wait(800)

    # Click "配置 API" button
    api_btn = page.get_by_role("button", name="配置 API")
    if await api_btn.count() > 0:
        await click_el(page, api_btn.first)
        await wait(1000)

        dlg = page.locator('[role="dialog"]')
        if await dlg.is_visible():
            # Click provider dropdown to show options
            provider_select = dlg.locator('[role="combobox"]').first
            if await provider_select.is_visible():
                await click_el(page, provider_select)
                await wait(600)
                # Select a different provider option
                opts = dlg.locator('[role="option"]')
                cnt = await opts.count()
                if cnt > 1:
                    await click_el(page, opts.nth(1))
                    await wait(600)

            await wait(500)
        await page.keyboard.press("Escape")
        await wait(500)

    remaining = max(0, duration_s - 12) * 1000
    await idle_pan(page, remaining)


async def rec_workflow1(page, duration_s):
    """sec03: Full one-click pipeline flow, MUST click start at end."""
    await setup_page(page)

    # Navigate to toolbar, import config
    await click_sidebar(page, "工具栏")
    await wait(600)

    imp = page.get_by_role("button", name="导入配置")
    if await imp.is_visible():
        await hover_el(page, imp, 1.0)
        await wait(400)
        cfg = os.path.join(ROOT, "demo-config.json").replace("\\", "/")
        try: await page.locator('input[type="file"]').set_input_files(cfg)
        except: pass
        await wait(600)

    # Back to main
    await click_sidebar(page, "主界面")
    await wait(600)

    # Select video
    await select_file(page, "test.mp4")
    await wait(800)

    # Click start — this is the key fix
    start = page.get_by_role("button", name="开始处理")
    if await start.is_visible():
        await hover_el(page, start, 1.0)
        await wait(400)
        await click_el(page, start)
        await wait(1500)

    remaining = max(0, duration_s - 16) * 1000
    await idle_pan(page, remaining)


async def rec_workflow2(page, duration_s):
    """sec04: Select file, check review, start, wait for 开始字幕校验 button, force-click it, review, continue TTS."""
    await setup_page(page)

    # Select video
    await select_file(page, "test.mp4")
    await wait(600)

    # Check "翻译完成后先校验"
    cb = page.get_by_label("翻译完成后先校验")
    if await cb.count() > 0:
        if not await cb.first.is_checked():
            await click_el(page, cb.first)
            await wait(400)

    # Click start
    start = page.get_by_role("button", name="开始处理")
    if await start.is_visible():
        await click_el(page, start)

    # Wait for "开始字幕校验" button to become ENABLED (translation completes ~20s)
    review_btn = page.get_by_role("button", name="开始字幕校验")
    if await review_btn.count() > 0:
        # Poll until button is enabled (up to 30s)
        for attempt in range(30):
            if await review_btn.first.is_enabled():
                print(f"  [INFO] 开始字幕校验 enabled after {attempt + 1}s")
                break
            await wait(1000)
        await hover_el(page, review_btn.first, 0.5)
        await review_btn.first.click()
        await wait(2000)

    # Should now be on review tab with prefill data loaded
    await page.evaluate("window.scrollTo(0, 200)")
    await wait(800)
    await page.evaluate("window.scrollTo(0, 0)")
    await wait(800)

    # Back to main — simulate clicking "继续TTS合成"
    await click_sidebar(page, "主界面")
    await wait(1000)

    cont_btn = page.get_by_role("button", name="继续TTS合成")
    if await cont_btn.count() > 0:
        await hover_el(page, cont_btn.first, 2.0)

    remaining = max(0, duration_s - 22) * 1000
    await idle_pan(page, remaining)


async def rec_term_replace(page, duration_s):
    """sec05: Show term replacement feature in step config panel."""
    await setup_page(page)

    # Navigate to step config
    await click_sidebar(page, "步骤配置")
    await wait(800)

    # Find and hover "启用术语替换" checkbox
    term_cb = page.get_by_label("启用术语替换")
    if await term_cb.count() > 0:
        await hover_el(page, term_cb.first, 2.0)
        await wait(600)

    # Hover over the description text too
    desc = page.get_by_text("Minecraft专有名词")
    if await desc.count() > 0:
        await hover_el(page, desc.first, 1.5)

    remaining = max(0, duration_s - 10) * 1000
    await idle_pan(page, remaining)


async def rec_config(page, duration_s):
    """sec06: Toolbar config management tour."""
    await setup_page(page)

    await click_sidebar(page, "工具栏")
    await wait(600)

    for btn_name in ["快速配置", "保存配置", "导出配置", "导入配置"]:
        btn = page.get_by_role("button", name=btn_name)
        if await btn.is_visible(): await hover_el(page, btn, 0.8); await wait(600)

    remaining = max(0, duration_s - 12) * 1000
    await idle_pan(page, remaining)


async def rec_recap(page, duration_s):
    """sec07: Main interface recap."""
    await setup_page(page)
    await wait(500)
    await page.evaluate("window.scrollTo(0, 0)"); await wait(1000)
    await page.evaluate("window.scrollTo(0, 200)"); await wait(1500)
    await page.evaluate("window.scrollTo(0, 0)"); await wait(1000)
    remaining = max(0, duration_s - 5) * 1000
    await idle_pan(page, min(remaining, duration_s * 1000))


SECTION_RECORDERS = {
    "sec00": ("00_intro", rec_intro),
    "sec01": ("01_hook", rec_hook),
    "sec02": ("02_api_config", rec_api_config),
    "sec03": ("03_workflow1", rec_workflow1),
    "sec04": ("04_workflow2", rec_workflow2),
    "sec05": ("05_term_replace", rec_term_replace),
    "sec06": ("06_config", rec_config),
    "sec07": ("07_recap", rec_recap),
}


async def record_segment(name, fn, duration_s):
    out_path = os.path.join(VIDEO_DIR, f"{name}.webm")
    print(f"  Recording '{name}' (target {duration_s:.0f}s)...")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            viewport={"width": W, "height": H},
            record_video_dir=VIDEO_DIR,
            record_video_size={"width": W, "height": H},
        )
        page = await ctx.new_page()
        try:
            await fn(page, duration_s)
        finally:
            v = page.video
            vpath = str(await v.path()) if v else None
            await ctx.close()
            await browser.close()
            if vpath and os.path.exists(vpath):
                if os.path.exists(out_path): os.remove(out_path)
                os.rename(vpath, out_path)
    print(f"  [OK] {name}.webm")


async def main():
    print("=== Tutorial Recorder v3 ===\n")

    _clean_recordings()

    if os.path.exists(TIMING_PATH):
        with open(TIMING_PATH, "r", encoding="utf-8") as f:
            timing = json.load(f)
    else:
        print("[ERROR] timing.json not found. Run generate_tts.py first."); return

    total_t = sum(t["duration"] for t in timing.values())
    print(f"Narration total: {total_t:.1f}s\n")

    for sec_id, (name, fn) in SECTION_RECORDERS.items():
        if sec_id in timing:
            dur = timing[sec_id]["duration"]
            await record_segment(name, fn, dur * 1.1)
        else:
            print(f"  [SKIP] {name}: no timing data")

    print(f"\n=== Done: {len(SECTION_RECORDERS)} segments ===")
    print("Next: run composite_tutorial.py")


if __name__ == "__main__":
    asyncio.run(main())
