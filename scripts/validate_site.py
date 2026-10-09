"""Check the local project page in Chrome without deploying it.

Playwright is a separate test dependency, never an application dependency.
Each run starts a temporary localhost server and retains browser evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import threading
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RELEASE_API = "https://api.github.com/repos/Koril33/bilix/releases/latest"
RELEASE_PAGE = "https://github.com/Koril33/bilix/releases/latest"
FALLBACK = "各平台下载与校验文件见发行页"
WIDTHS = (1440, 390, 320)
MODES = (
    "success",
    "failure",
    "no-js",
    "prerelease",
    "draft",
    "malformed",
    "invalid-json",
    "timeout",
)


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, _format, *_args):
        pass


@contextmanager
def local_page():
    handler = partial(QuietHandler, directory=str(ROOT / "site"))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/bilix.html"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def check_case(browser, url: str, output: Path, mode: str, width: int) -> dict:
    from playwright.sync_api import Error

    context = browser.new_context(
        viewport={"width": width, "height": 900}, java_script_enabled=mode != "no-js"
    )
    pending_routes = []
    try:
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        if mode == "success":
            payload = {"tag_name": "v1.7.1", "draft": False, "prerelease": False}
        elif mode == "prerelease":
            payload = {"tag_name": "v1.7.2.dev1", "prerelease": True}
        elif mode == "draft":
            payload = {"tag_name": "v1.7.2", "draft": True}
        elif mode == "malformed":
            payload = {"tag_name": 123}
        else:
            payload = None
        if payload is not None:
            page.route(RELEASE_API, lambda route: route.fulfill(json=payload))
        elif mode == "failure":
            page.route(RELEASE_API, lambda route: route.fulfill(status=503, body="unavailable"))
        elif mode == "invalid-json":
            page.route(RELEASE_API, lambda route: route.fulfill(body="{invalid json"))
        elif mode == "timeout":
            page.route(RELEASE_API, lambda route: pending_routes.append(route))

        page.goto(url, wait_until="domcontentloaded")
        if mode == "success":
            page.locator(".version-info").filter(has_text="v1.7.1").wait_for()
        elif mode == "timeout":
            # The page's six-second AbortController must preserve the fallback.
            page.wait_for_timeout(6500)
        else:
            page.wait_for_timeout(300)
        version = page.locator(".version-info").inner_text()
        expected = "版本 v1.7.1 | 各平台文件与 SHA256 校验见发行页"
        assert version == (expected if mode == "success" else FALLBACK), (mode, version)
        assert page.locator(".download-button").get_attribute("href") == RELEASE_PAGE
        assert not errors, errors

        # Browser evaluation remains available with page scripts disabled.
        layout = page.evaluate("({width:innerWidth,scroll:document.documentElement.scrollWidth})")
        assert layout["scroll"] <= layout["width"], (mode, width, layout)
        links = page.locator("a[href]").evaluate_all(
            "links => links.map(link => link.getAttribute('href'))"
        )
        assert links[0] == RELEASE_PAGE
        assert links[1:3] == [
            "https://github.com/Koril33/bilix",
            "https://git.djhx.site/koril/djhx-bilix",
        ]
        assert all(link.startswith("https://") for link in links), links
        assert not any("gitee" in link.lower() for link in links), links
        seen_links = []
        scrollable_blocks = 0
        for _ in range(len(links) + page.locator("pre").count() + 2):
            page.keyboard.press("Tab")
            focus = page.evaluate(
                "(() => { const node = document.activeElement; return {tag:node.tagName,"
                "href:node.getAttribute('href'),width:node.clientWidth,"
                "scroll:node.scrollWidth}; })()"
            )
            if focus["href"] is not None:
                expected_link = links[len(seen_links)]
                assert focus["href"] == expected_link, (mode, expected_link, focus)
                seen_links.append(focus["href"])
                if len(seen_links) == len(links):
                    break
            else:
                # Chrome makes overflowing code blocks keyboard focusable.
                assert focus["tag"] == "PRE" and focus["scroll"] > focus["width"], focus
                scrollable_blocks += 1
                if scrollable_blocks == 1:
                    for _ in range(8):
                        page.keyboard.press("ArrowRight")
                    page.wait_for_timeout(200)
                    assert page.locator(":focus").evaluate("node => node.scrollLeft") > 0
        assert seen_links == links, (mode, seen_links, links)
        page.keyboard.press("Shift+Tab")
        assert page.locator(":focus").get_attribute("href") == links[-2]

        page.evaluate("scrollTo(0,0)")
        page.screenshot(path=str(output / f"{mode}-{width}-viewport.png"))
        page.screenshot(path=str(output / f"{mode}-{width}-full.png"), full_page=True)
        return {
            "mode": mode,
            "width": width,
            "status": "passed",
            "version_text": version,
            "layout": layout,
            "keyboard_links": len(links),
            "keyboard_scrollable_blocks": scrollable_blocks,
            "reverse_keyboard": True,
        }
    finally:
        # Finish intercepted requests before closing the context; otherwise
        # Playwright can report a cancelled routing coroutine after valid checks.
        for route in pending_routes:
            try:
                route.abort()
            except Error:
                pass  # The page's AbortController may already have cancelled it.
        context.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser-executable", type=Path, help="Existing Chrome/Chromium binary")
    parser.add_argument("--output", type=Path, help="New evidence directory")
    parser.add_argument(
        "--live-api", action="store_true", help="Also observe the actual GitHub API"
    )
    args = parser.parse_args()
    run = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    output = args.output or ROOT / "build" / "validation" / "site" / run
    output.mkdir(parents=True, exist_ok=False)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        parser.error(f"Install Playwright in an isolated test environment: {exc.name}")

    record = {
        "schema_version": 1,
        "started_at": datetime.now(UTC).isoformat(),
        "source_sha256": hashlib.sha256((ROOT / "site/bilix.html").read_bytes()).hexdigest(),
        "status": "running",
        "asserted_cases": [],
        "live_observation": None,
    }
    try:
        with local_page() as url, sync_playwright() as playwright:
            options = {"headless": True}
            if args.browser_executable:
                options["executable_path"] = str(args.browser_executable.resolve())
            else:
                options["channel"] = "chrome"
            browser = playwright.chromium.launch(**options)
            try:
                record["browser_version"] = browser.version
                for mode in MODES:
                    for width in WIDTHS:
                        record["asserted_cases"].append(
                            check_case(browser, url, output, mode, width)
                        )
                context = browser.new_context(reduced_motion="reduce")
                try:
                    page = context.new_page()
                    page.route(
                        RELEASE_API, lambda route: route.fulfill(status=503, body="unavailable")
                    )
                    page.goto(url, wait_until="domcontentloaded")
                    transition = page.locator(".download-button").evaluate(
                        "node => getComputedStyle(node).transitionDuration"
                    )
                    assert all(
                        float(part.strip().removesuffix("s")) == 0 for part in transition.split(",")
                    )
                    record["asserted_cases"].append({"mode": "reduced-motion", "status": "passed"})
                finally:
                    context.close()
                if args.live_api:
                    context = browser.new_context()
                    try:
                        page = context.new_page()
                        responses = []
                        page.on(
                            "response",
                            lambda response: (
                                responses.append(response.status)
                                if response.url == RELEASE_API
                                else None
                            ),
                        )
                        page.goto(url, wait_until="domcontentloaded")
                        page.wait_for_timeout(6500)
                        record["live_observation"] = {
                            "version_text": page.locator(".version-info").inner_text(),
                            "http_statuses": responses,
                            "download_href": page.locator(".download-button").get_attribute("href"),
                        }
                    finally:
                        context.close()
            finally:
                browser.close()
        record["status"] = "passed"
    except Exception as exc:
        record["status"] = "failed"
        record["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        record["finished_at"] = datetime.now(UTC).isoformat()
        (output / "result.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    print(f"{len(record['asserted_cases'])} asserted website cases passed; evidence: {output}")
    if args.live_api:
        print("The live API result is an observation, not an asserted success case.")


if __name__ == "__main__":
    main()
