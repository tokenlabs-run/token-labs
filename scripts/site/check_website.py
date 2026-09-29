"""Browser smoke checks with mocked API responses; never sends real inference requests.

Serve docs with `python -m http.server 8765 --directory docs`, then run this
script in an environment with Playwright and Chromium installed. Use --browser
for an existing Chromium executable, or `playwright install chromium` first.
"""
import argparse
import json
from pathlib import Path
from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:8765')
    parser.add_argument('--browser')
    args = parser.parse_args()
    docs = Path(__file__).resolve().parents[2] / 'docs'
    with sync_playwright() as p:
        browser = p.chromium.launch(**({'executable_path': args.browser} if args.browser else {}))
        page = browser.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        models = [{'id': 'test-model'}]
        requests = []
        mode = 'success'

        def api(route):
            if route.request.url.endswith('/v1/models'):
                route.fulfill(json={'data': models})
                return
            requests.append(route.request.post_data_json)
            if mode == 'unauthorized':
                route.fulfill(status=401, json={'error': 'unauthorized'})
            elif mode == 'interrupted':
                route.fulfill(content_type='text/event-stream', body='data: {"choices":[]}\n\n')
            else:
                delta = {'choices': [{'delta': {'content': '<script>unsafe()</script> Hello'},
                                      'finish_reason': 'length' if mode == 'limited' else 'stop'}]}
                route.fulfill(content_type='text/event-stream', body='data: '+json.dumps(delta)+'\r\n\r\ndata: [DONE]\r\n\r\n')

        page.route('https://api.tokenlabs.run/**', api)
        for name in ['index', 'playground', 'dashboards']:
            page.goto(f'{args.base_url}/{name}.html')
            assert page.locator('h1').count() == 1
            assert not page.locator('.explore').evaluate('(el) => el.open')
            page.locator('.explore summary').click()
            assert page.get_by_role('link', name='Experiment notebook').is_visible()
            for link in page.locator('a').all():
                href = link.get_attribute('href') or ''
                if href and not href.startswith(('https:', 'mailto:', '#')):
                    assert (docs / href.split('#')[0]).is_file(), href
            for width in [360, 390, 768, 1440]:
                page.set_viewport_size({'width': width, 'height': 900})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (name, width)
        page.goto(f'{args.base_url}/playground.html')
        page.wait_for_function('document.querySelector("#model").value === "test-model"')
        page.locator('#api-key').fill('test-key-not-a-secret')
        page.locator('[data-prompt]').first.click()
        page.locator('#send').click()
        page.wait_for_function('document.querySelector("#status").textContent === "Response complete."')
        assert page.locator('.message.assistant p').inner_text() == '<script>unsafe()</script> Hello'
        assert page.locator('.message script').count() == 0
        page.locator('#prompt').fill('A follow-up')
        page.locator('#prompt').press('Enter')
        page.wait_for_function('document.querySelector("#status").textContent === "Response complete."')
        assert len(requests[-1]['messages']) == 3
        assert requests[-1]['chat_template_kwargs'] == {'enable_thinking': False}
        page.locator('#clear').click()
        assert page.locator('.message').count() == 0
        assert page.evaluate('localStorage.length === 0 && sessionStorage.length === 0')
        mode = 'limited'
        page.locator('#prompt').fill('Test output limit')
        page.locator('#send').click()
        page.wait_for_function('document.querySelector("#status").textContent.includes("Output limit reached")')
        mode = 'unauthorized'
        page.locator('#prompt').fill('Test errors')
        page.locator('#send').click()
        page.wait_for_function('document.querySelector("#status").textContent.includes("not accepted")')
        assert page.locator('#prompt').input_value() == 'Test errors'
        mode = 'interrupted'
        page.locator('#send').click()
        page.wait_for_function('document.querySelector("#status").textContent.includes("before the response finished")')
        models.clear()
        page.locator('#refresh').click()
        page.wait_for_function('document.querySelector("#status").textContent.includes("No models are available")')
        assert page.locator('#send').is_disabled()
        assert not errors, errors
        browser.close()
    print('PASS: responsive pages, links, disclosure, model discovery, streaming, history, safe text rendering, error handling, empty state.')


if __name__ == '__main__':
    main()
