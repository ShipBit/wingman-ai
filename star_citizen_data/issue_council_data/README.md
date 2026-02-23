# Issue Council Token Helper

This helper captures the `Authorization: Bearer ...` token from a logged-in RSI Issue Council browser session and stores it in:

- `star_citizen_data/issue_council_data/.issue_council_bearer_token`

`IssueCouncilManager` reads this file automatically.
If no valid token is available, `IssueCouncilManager` now auto-starts the helper script by default. After login, you can ask cora to find existing issues.

## Run

```bash
python3 star_citizen_data/issue_council_data/scripts/capture_issue_council_token.py
```

For 2FA/reCAPTCHA flows, prefer real Chrome channel and a longer timeout:

```bash
python3 star_citizen_data/issue_council_data/scripts/capture_issue_council_token.py --browser-channel chrome --timeout-seconds 1200
```

## Requirements

```bash
python3 -m pip install playwright
python3 -m playwright install chromium
```

## Typical flow

1. Script opens Issue Council in a Playwright browser context (default channel: Chrome).
2. Log in to RSI (if needed).
3. Use/search the Issue Council so `/gql` requests are sent.
4. Script detects Bearer token and stores it.

You can reuse the browser profile between runs via:

- `star_citizen_data/issue_council_data/playwright_profile`

## Troubleshooting login window

- If the window shows CORS console warnings for CDN assets, that alone does not block token capture.
- If RSI shows `Your registration could not be processed ... (Code 4237)`, use the direct login URL first, then open Issue Council:
  - `https://robertsspaceindustries.com/en/account/login?redirect=https%3A%2F%2Fissue-council.robertsspaceindustries.com%2Fprojects%2FSTAR-CITIZEN%2Fissues`
- If RSI shows `Could not connect to reCAPTCHA service`, check ad blocker/VPN/DNS filtering and allow Google reCAPTCHA resources, then reload.
- If 2FA takes longer, increase timeout (`--timeout-seconds 1200` or higher).
- If login still loops, close all helper browser windows and remove the profile directory once:
  - `star_citizen_data/issue_council_data/playwright_profile`
