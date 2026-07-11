# Setup: auto-updating GitHub stats README

This repo generates a neofetch-style SVG card (like the one Andrew Grant uses)
with your **real, live** GitHub stats — repos, stars, commits, followers, and
total lines of code — and re-generates it automatically on a schedule.

## 1. Create the special profile repo

If you haven't already: create a new **public** repo named exactly
`ebrahim-rabie` (must match your username exactly). GitHub treats a repo
with this special name as your profile README source.

Push all the files in this folder to that repo (`generate_svg.py`,
`templates/`, `.github/workflows/main.yml`, `README.md`).

## 2. Create a Personal Access Token (PAT)

The default `GITHUB_TOKEN` that Actions provides can't read stats across
*all* your repos or your profile-level contribution history, so you need a
PAT:

1. Go to **GitHub → Settings → Developer settings → Personal access tokens
   → Fine-grained tokens** (or classic tokens).
2. Scopes needed: `repo` (read) and `read:user`.
3. Copy the token.

## 3. Add it as a repo secret

In your `ebrahim-rabie` repo: **Settings → Secrets and variables → Actions
→ New repository secret**.
- Name: `ACCESS_TOKEN`
- Value: the PAT you just copied

## 4. Run it once

The workflow (`.github/workflows/main.yml`) runs automatically:
- once a day (cron schedule, 05:00 UTC — edit the cron line to change it)
- whenever you push to `main`
- or manually, any time, from the **Actions** tab → "Update GitHub stats
  SVG" → **Run workflow**

Trigger it manually the first time so `light_mode.svg` and `dark_mode.svg`
get created and committed.

## 5. Customize the static fields

`templates/light_mode.svg` and `templates/dark_mode.svg` hold the parts
that *aren't* pulled from the API — OS, languages, contact info, the ASCII
art of you. Edit the text directly inside those SVG files (they're plain
XML/text). The `{{repo_count}}`, `{{stars}}`, `{{commits}}`,
`{{followers}}`, `{{loc_total}}` etc. placeholders get filled in by
`generate_svg.py` — leave those as-is.

## Notes on the "lines of code" number

Computing this properly means cloning every repo you own and walking its
full commit history, which is slow and API-heavy. The script caches
progress in `loc_cache.json` (committed alongside the SVGs) so each run
after the first only processes *new* commits, not the whole history again.
For accounts with a lot of repos, the very first run may take a few
minutes — that's expected.
