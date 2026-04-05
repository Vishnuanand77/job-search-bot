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

Either pass URLs directly on the command line:

```bash
uv run python scripts/probe_sites.py https://stripe.com/jobs/search https://example.com/careers
```

Or add them to `config/targets.yaml` and run without arguments — the probe
reads all entries automatically.

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
────────────────────────────────────────────────────────────
  Stripe
  https://stripe.com/jobs/search
────────────────────────────────────────────────────────────
  [HTTP] ✓ 200 (1.2s)
  [Playwright] ✓ content received (4.3s)

  → Recommended scrape_tier: http
    - name: Stripe
      url: https://stripe.com/jobs/search
      scrape_tier: http
```

Copy the YAML block directly into `config/targets.yaml`.

If both tiers fail, the site may use bot detection, require login, or
the URL may be wrong. Verify in your browser before including it.

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
