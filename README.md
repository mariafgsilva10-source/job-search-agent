# Daily Job Search Agent

Runs every morning, automatically:
1. Pulls new paralegal/legal vacancies (Reading / High Wycombe / Loudwater / Maidenhead area) from **Reed** and **Adzuna**
2. Drafts a tailored cover letter + CV bullet suggestions for each new one, using Claude
3. Publishes the results to a simple dashboard website (GitHub Pages)

Why not LinkedIn/Indeed directly? Both prohibit automated scraping in their Terms of
Service, and doing so risks your account. Reed and Adzuna are official, free, ToS-compliant
APIs — Adzuna also aggregates listings that originate on Indeed and other boards, so
coverage is still broad.

## One-time setup (about 15 minutes)

### 1. Create a GitHub repository
Create a new **private** repo and push this folder's contents to it.

### 2. Get your free API keys
- **Reed**: https://www.reed.co.uk/developers — sign up, copy your API key
- **Adzuna**: https://developer.adzuna.com/ — register an app, copy App ID + App Key
- **Anthropic**: https://console.anthropic.com/ — create an API key (this is a paid API;
  drafting ~5-10 jobs/day costs a small fraction of a cent to a few cents per job)

### 3. Add them as repo secrets
In your GitHub repo: **Settings → Secrets and variables → Actions → New repository secret**
Add each of:
- `REED_API_KEY`
- `ADZUNA_APP_ID`
- `ADZUNA_APP_KEY`
- `ANTHROPIC_API_KEY`

### 4. Enable GitHub Pages
**Settings → Pages → Source: Deploy from branch → Branch: main, folder: /docs → Save**
Your dashboard will be live at `https://<your-username>.github.io/<repo-name>/`

### 5. Add your real CV
Replace the contents of `data/base_cv.md` with your full, real CV text — the more detail
you give it (specific achievements, phrasing you like, past cover letter snippets), the
better the drafts will be.

### 6. Test it manually first
Go to the **Actions** tab → "Daily Job Search" → **Run workflow** (this is the
`workflow_dispatch` trigger). Check the dashboard updates correctly before trusting the
daily schedule.

## Adjusting the search

Edit `scripts/fetch_jobs.py`:
- `SEARCH_TERMS` — job title keywords
- `LOCATIONS` — Reed locations searched
- `RESULTS_PER_SEARCH` — results per term/location combo

Edit the cron time in `.github/workflows/daily-job-search.yml` if 07:00 UK time doesn't
suit (GitHub Actions cron is in UTC, so account for BST in summer).

## Costs
- GitHub Actions: free for this usage level on a private repo (well within free minutes)
- Reed / Adzuna: free tiers, no cost
- Anthropic API: pay-as-you-go, small (a handful of jobs/day is pennies)

## Limitations to know
- Reed and Adzuna won't have 100% of what's on LinkedIn/Indeed — for roles you find there
  manually, paste the job description to Claude directly for a one-off draft
- The dashboard has no login — keep the repo/Pages site private if you don't want it public,
  or add basic auth via GitHub Pages settings / a private repo with a token-gated Pages URL
- Runs are capped at 10 new jobs drafted per day (see `MAX_NEW_JOBS_PER_RUN` in
  `scripts/fetch_jobs.py`) — if more than 10 new matches appear, the extras roll over
  and get drafted on the next run rather than being dropped
