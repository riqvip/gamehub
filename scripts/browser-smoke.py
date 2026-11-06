#!/usr/bin/env python3
"""Desktop/mobile smoke against the disposable local app; no production URL option."""

import os
from pathlib import Path

os.environ.setdefault(
    "PLAYWRIGHT_BROWSERS_PATH", str(Path(__file__).resolve().parents[1] / ".validation/browsers")
)
from playwright.sync_api import sync_playwright

repo = Path(__file__).resolve().parents[1]
password = (repo / ".dev/admin-password").read_text().strip()
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(viewport={"width": 1440, "height": 1000})
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto("http://127.0.0.1:18080", wait_until="networkidle")
    page.locator("#login-pass").fill(password)
    page.get_by_role("button", name="Sign in", exact=False).click()
    page.locator("#app").wait_for(state="visible")
    page.locator("#server-list button").first.click()
    page.locator("#server-name").wait_for(state="visible")
    page.get_by_role("button", name="Mods LIBRARY").click()
    page.locator("#tab-mods").wait_for(state="visible")
    page.get_by_role("button", name="Install a mod").click()
    page.locator("#install-dialog").wait_for(state="visible")
    page.get_by_role("button", name="Close", exact=True).last.click()
    page.screenshot(path=str(repo / ".validation/dashboard-desktop.png"), full_page=True)
    page.set_viewport_size({"width": 390, "height": 844})
    page.screenshot(path=str(repo / ".validation/dashboard-mobile.png"), full_page=True)
    if not (page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")):
        raise RuntimeError("Mobile page overflows horizontally")
    if not (not errors):
        raise RuntimeError(errors)
    print(
        "PASS: desktop/mobile login, server navigation, Mods tab, install dialog; no JavaScript errors or mobile overflow"
    )
    context.close()
    browser.close()
