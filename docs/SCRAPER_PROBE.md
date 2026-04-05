# Scraper Probe Tool

Before committing your target sites, run the probe to determine which scrape tier works for each URL and whether the site blocks automated access.

This is your pre-scraping penetration test — run it before production, not during.

---

## Run it

```bash
uv run python scripts/probe_sites.py
```

No `.env` required. Makes no AI API calls. Tests HTTP and Playwright only.

---

## Add your target URLs

Edit the `PROBE_URLS` list at the top of `scripts/probe_sites.py`:

```python
PROBE_URLS: list[tuple[str, str]] = [
    ("Stripe", "https://stripe.com/jobs/search"),
    ("American Express", "https://aexp.eightfold.ai/careers?domain=aexp.com"),
    # add all 10 targets here
]
```

---

## What it does

For each URL:
1. Attempts HTTP fetch with browser headers
2. If HTTP fails or returns < 500 meaningful chars, attempts Playwright
3. Records chars extracted per tier and recommends a `scrape_tier`
4. Flags sites returning near-zero content on both tiers

---

## Reading the output

```
sites:
  - name: Stripe
    url: https://stripe.com/jobs/search
    scrape_tier: http          # http:12400 pw:0 chars

  - name: American Express
    url: https://aexp.eightfold.ai/careers?domain=aexp.com
    scrape_tier: playwright    # http:0 pw:8200 chars

  - name: Broken Site
    url: https://example.com/jobs
    scrape_tier: playwright    # ⚠ WARNING: only 180 chars — may be blocked
```

Paste the output directly into `config/targets.yaml`.

Sites with ⚠ WARNING returned very little content. This means the site
may use bot detection, require login, or the URL is wrong. Verify the URL
shows job listings in your browser before including it.

---

## Rate limit safety

- 3-second delay between requests per domain
- Do not run more than once per day per site
- Do not run in CI — local only
- HTTP 429 responses are noted in the output and the site is flagged

---

## Sites that fail the probe

If a site returns < 500 chars on both tiers, your options are:
1. Verify the URL manually in your browser
2. Try a different URL (e.g. the search page vs the main careers page)
3. Remove it from your target list — some sites are not scrapeable
   without a managed scraping service
