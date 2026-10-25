#!/usr/bin/env python3
"""Check live portal discovery and selecting Qwen3.8 in a real browser."""
import argparse,glob,json,pathlib
from playwright.sync_api import sync_playwright
p=argparse.ArgumentParser();p.add_argument('--output',type=pathlib.Path,required=True);a=p.parse_args()
with sync_playwright() as p:
 browser=p.chromium.launch(executable_path=glob.glob('/home/nvidia/.cache/ms-playwright/chromium-*/chrome-linux64/chrome')[0],headless=True)
 page=browser.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
 page.goto('https://www.tokenlabs.run/playground.html',wait_until='networkidle')
 page.wait_for_function('Array.from(document.querySelectorAll("#model option")).some(e=>e.value === "nvidia/Qwen3.8-27B-NVFP4")',timeout=45000)
 ids=page.locator('#model option').evaluate_all('(els)=>els.map(e=>e.value)')
 assert set(ids)=={'nvidia/Qwen3.6-35B-A3B-NVFP4','nvidia/Qwen3.8-27B-NVFP4'},ids
 page.locator('#model').select_option('nvidia/Qwen3.8-27B-NVFP4');assert page.locator('#model').input_value()=='nvidia/Qwen3.8-27B-NVFP4'
 assert not errors,errors
 a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps({'passed':True,'url':page.url,'models':ids,'selected':page.locator('#model').input_value(),'javascript_errors':errors},indent=2)+'\n')
 print('PASS live portal discovery and Qwen3.8 selection');browser.close()
