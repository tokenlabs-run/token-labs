import glob
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    browser=p.chromium.launch(executable_path=glob.glob('/home/nvidia/.cache/ms-playwright/chromium-*/chrome-linux64/chrome')[0],headless=True)
    page=browser.new_page()
    errors=[]
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.goto('https://www.tokenlabs.run/playground.html',wait_until='networkidle')
    page.wait_for_function('document.querySelector("#model").value === "nvidia/Qwen3.6-35B-A3B-NVFP4"',timeout=30000)
    ids=page.locator('#model option').evaluate_all('(els)=>els.map(e=>e.value)')
    assert ids==['nvidia/Qwen3.6-35B-A3B-NVFP4'], ids
    assert page.locator('#status').inner_text()=='Ready when you are.'
    assert not errors, errors
    print('PASS live browser model selector and CORS: Qwen only; no JavaScript errors',flush=True)
    browser.close()
