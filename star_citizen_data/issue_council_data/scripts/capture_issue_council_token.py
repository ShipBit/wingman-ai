#!/usr/bin/env python3
"""
Capture and persist an RSI Issue Council Bearer token via Playwright.

Workflow:
1) Launches a persistent Chromium profile (keeps login session).
2) Opens Issue Council page.
3) Waits until a GraphQL request with Authorization: Bearer ... is observed.
4) Stores token to file for IssueCouncilManager.
"""

import argparse
import sys
import time
from pathlib import Path
from urllib.parse import quote, urlparse


DEFAULT_ISSUE_URL = "https://issue-council.robertsspaceindustries.com/projects/STAR-CITIZEN/issues"
DEFAULT_API_URL_PREFIX = "https://api-issue-council.robertsspaceindustries.com/gql"
DEFAULT_LOGIN_URL_BASE = "https://robertsspaceindustries.com/en/account/login?redirect="


def _normalize_bearer_value(raw_value):
    if not raw_value:
        return None
    token = str(raw_value).strip()
    if not token:
        return None
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    return token or None


def parse_args():
    parser = argparse.ArgumentParser(
        description="Capture RSI Issue Council Bearer token from browser network traffic."
    )
    parser.add_argument(
        "--issue-url",
        default=DEFAULT_ISSUE_URL,
        help="Issue Council page to open.",
    )
    parser.add_argument(
        "--api-url-prefix",
        default=DEFAULT_API_URL_PREFIX,
        help="GraphQL endpoint prefix to watch.",
    )
    parser.add_argument(
        "--login-url",
        default="",
        help="Optional RSI login URL. If empty, it is derived from --issue-url.",
    )
    parser.add_argument(
        "--token-file",
        default="star_citizen_data/issue_council_data/.issue_council_bearer_token",
        help="Target file to store captured bearer token.",
    )
    parser.add_argument(
        "--profile-dir",
        default="star_citizen_data/issue_council_data/playwright_profile",
        help="Persistent Chromium profile directory.",
    )
    parser.add_argument(
        "--browser-channel",
        default="chrome",
        choices=["chrome", "msedge", "chromium"],
        help=(
            "Browser channel for Playwright persistent context. "
            "Use chrome/msedge to reduce CAPTCHA/login issues."
        ),
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=900,
        help="Max wait time until token capture.",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run browser headless (not recommended for login flows).",
    )
    parser.add_argument(
        "--keep-open",
        action="store_true",
        help="Keep browser open after successful capture until Ctrl+C.",
    )
    return parser.parse_args()


def _build_login_url(issue_url: str):
    return f"{DEFAULT_LOGIN_URL_BASE}{quote(issue_url, safe='')}"


def _is_issue_council_url(url: str):
    if not url:
        return False
    parsed = urlparse(url)
    return parsed.netloc.lower() == "issue-council.robertsspaceindustries.com"


def _has_recaptcha_connectivity_error(page):
    try:
        body_text = page.inner_text("body")
    except Exception:
        return False
    if not body_text:
        return False
    lowered = body_text.lower()
    return (
        "recaptcha" in lowered
        and (
            "keine verbindung" in lowered
            or "could not connect" in lowered
            or "verify your internet connection" in lowered
        )
    )


def main():
    args = parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        print(
            "Playwright is not installed.\n"
            "Install with:\n"
            "  python3 -m pip install playwright\n"
            "  python3 -m playwright install chromium",
            file=sys.stderr,
        )
        return 2

    token_file = Path(args.token_file).resolve()
    profile_dir = Path(args.profile_dir).resolve()
    token_file.parent.mkdir(parents=True, exist_ok=True)
    profile_dir.mkdir(parents=True, exist_ok=True)

    captured = {"token": None, "from_url": None}

    def on_request(request):
        if not request.url.startswith(args.api_url_prefix):
            return
        header_value = request.headers.get("authorization")
        token = _normalize_bearer_value(header_value)
        if not token:
            return
        captured["token"] = token
        captured["from_url"] = request.url

    with sync_playwright() as playwright:
        launch_kwargs = {
            "user_data_dir": str(profile_dir),
            "headless": args.headless,
        }
        if args.browser_channel in {"chrome", "msedge"}:
            launch_kwargs["channel"] = args.browser_channel

        try:
            context = playwright.chromium.launch_persistent_context(
                **launch_kwargs,
            )
        except Exception as error:
            if args.browser_channel != "chromium":
                print(
                    f"Could not start browser channel '{args.browser_channel}' ({error}). "
                    "Falling back to bundled Chromium...",
                    file=sys.stderr,
                )
                context = playwright.chromium.launch_persistent_context(
                    user_data_dir=str(profile_dir),
                    headless=args.headless,
                )
            else:
                raise
        page = context.pages[0] if context.pages else context.new_page()
        context.on("request", on_request)

        issue_url = args.issue_url.strip() or DEFAULT_ISSUE_URL
        login_url = (args.login_url or "").strip() or _build_login_url(issue_url)

        print("Opening Issue Council...")
        page.goto(issue_url, wait_until="domcontentloaded")
        if not _is_issue_council_url(page.url):
            print("Detected redirect outside Issue Council. Opening direct RSI login page...")
            page.goto(login_url, wait_until="domcontentloaded")
            print("If RSI does not redirect automatically after login, open this URL manually:")
            print(issue_url)

        print("")
        print("Please log in (if needed) and navigate Issue Council.")
        print("If you see RSI error code 4237, retry with the direct login page and then open Issue Council.")
        print(f"Browser channel: {args.browser_channel}")
        print(f"Direct login URL: {login_url}")
        print("Waiting for GraphQL request with Authorization Bearer token...")
        print(f"Timeout: {args.timeout_seconds}s")
        print("")

        start = time.time()
        recaptcha_hint_printed = False
        last_recaptcha_check = 0.0
        while (time.time() - start) < args.timeout_seconds and not captured["token"]:
            now = time.time()
            if (now - last_recaptcha_check) >= 2.0:
                last_recaptcha_check = now
                if _has_recaptcha_connectivity_error(page) and not recaptcha_hint_printed:
                    recaptcha_hint_printed = True
                    print("Detected reCAPTCHA connectivity error in page text.")
                    print("Check ad blocker/VPN/DNS filters and allow reCAPTCHA domains, then reload login page.")
                    print("If needed, rerun with --browser-channel chrome and complete 2FA there.")
            time.sleep(0.2)

        if not captured["token"]:
            print(
                "No bearer token captured before timeout.\n"
                "Hint: Open DevTools Network and trigger Issue Council actions so /gql requests are made.",
                file=sys.stderr,
            )
            context.close()
            return 1

        token_file.write_text(captured["token"], encoding="utf-8")
        print(f"Captured token from: {captured['from_url']}")
        print(f"Saved token to: {token_file}")
        print("")
        print("IssueCouncilManager can now use this token file directly.")

        if args.keep_open:
            print("Browser remains open. Press Ctrl+C to exit.")
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                pass

        context.close()
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
