#!/usr/bin/env python3
"""
Generates a neofetch-style GitHub profile SVG (light_mode.svg / dark_mode.svg)
by pulling live stats from the GitHub API:
  - repo count / stars / followers
  - total commit contributions (all-time, across all years)
  - total lines of code added/deleted across your own repos

Run locally:
    GITHUB_TOKEN=ghp_xxx GITHUB_USER=ebrahim-rabie python generate_svg.py

In CI, GITHUB_TOKEN and GITHUB_USER come from repo secrets / the workflow env.

A local cache (loc_cache.json) stores the last-processed commit SHA per repo
so re-runs only walk *new* commits instead of re-cloning history every time.
"""

import os
import json
import subprocess
import shutil
import tempfile
from datetime import datetime, timezone

import requests

GITHUB_USER = os.environ.get("GITHUB_USER", "ebrahim-rabie")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")

if not GITHUB_TOKEN:
    raise SystemExit("GITHUB_TOKEN environment variable is required")

API_URL = "https://api.github.com/graphql"
HEADERS = {"Authorization": f"bearer {GITHUB_TOKEN}"}
CACHE_FILE = "loc_cache.json"


# --------------------------------------------------------------------------
# GraphQL helpers
# --------------------------------------------------------------------------

def graphql(query: str, variables: dict | None = None) -> dict:
    resp = requests.post(
        API_URL,
        headers=HEADERS,
        json={"query": query, "variables": variables or {}},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if "errors" in data:
        raise RuntimeError(data["errors"])
    return data["data"]


def get_account_created_year() -> int:
    query = """
    query($login: String!) {
      user(login: $login) { createdAt }
    }
    """
    data = graphql(query, {"login": GITHUB_USER})
    created = data["user"]["createdAt"]
    return int(created[:4])


def get_total_commits() -> int:
    """Sum commit contributions across every year since account creation."""
    start_year = get_account_created_year()
    current_year = datetime.now(timezone.utc).year
    total = 0
    query = """
    query($login: String!, $from: DateTime!, $to: DateTime!) {
      user(login: $login) {
        contributionsCollection(from: $from, to: $to) {
          totalCommitContributions
          restrictedContributionsCount
        }
      }
    }
    """
    for year in range(start_year, current_year + 1):
        from_dt = f"{year}-01-01T00:00:00Z"
        to_dt = f"{year}-12-31T23:59:59Z"
        data = graphql(query, {"login": GITHUB_USER, "from": from_dt, "to": to_dt})
        cc = data["user"]["contributionsCollection"]
        total += cc["totalCommitContributions"] + cc["restrictedContributionsCount"]
    return total


def get_profile_stats() -> dict:
    """Repo count, stars, followers, following, contributed-to repo count."""
    query = """
    query($login: String!, $after: String) {
      user(login: $login) {
        followers { totalCount }
        following { totalCount }
        repositoriesContributedTo(first: 1) { totalCount }
        repositories(first: 100, after: $after, ownerAffiliations: OWNER, isFork: false) {
          totalCount
          pageInfo { hasNextPage endCursor }
          nodes {
            name
            stargazerCount
            defaultBranchRef { name }
          }
        }
      }
    }
    """
    repos = []
    after = None
    followers = following = contributed = repo_total = 0
    while True:
        data = graphql(query, {"login": GITHUB_USER, "after": after})
        u = data["user"]
        followers = u["followers"]["totalCount"]
        following = u["following"]["totalCount"]
        contributed = u["repositoriesContributedTo"]["totalCount"]
        repo_total = u["repositories"]["totalCount"]
        repos.extend(u["repositories"]["nodes"])
        page = u["repositories"]["pageInfo"]
        if page["hasNextPage"]:
            after = page["endCursor"]
        else:
            break

    stars = sum(r["stargazerCount"] for r in repos)
    return {
        "followers": followers,
        "following": following,
        "contributed_to": contributed,
        "repo_count": repo_total,
        "stars": stars,
        "repos": repos,
    }


# --------------------------------------------------------------------------
# Lines of code (clone each owned repo, tally git log --numstat by author)
# --------------------------------------------------------------------------

def load_cache() -> dict:
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE) as f:
            return json.load(f)
    return {}


def save_cache(cache: dict) -> None:
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f, indent=2)


def compute_loc(repos: list[dict]) -> dict:
    cache = load_cache()
    total_add, total_del = 0, 0

    for repo in repos:
        name = repo["name"]
        branch = (repo.get("defaultBranchRef") or {}).get("name") or "main"
        repo_cache = cache.get(name, {"last_sha": None, "add": 0, "delete": 0})

        with tempfile.TemporaryDirectory() as tmp:
            url = f"https://x-access-token:{GITHUB_TOKEN}@github.com/{GITHUB_USER}/{name}.git"
            clone = subprocess.run(
                ["git", "clone", "--quiet", "--single-branch", "--branch", branch, url, tmp],
                capture_output=True, text=True,
            )
            if clone.returncode != 0:
                # empty repo, deleted branch, etc. — skip gracefully
                continue

            log_range = f"{repo_cache['last_sha']}..HEAD" if repo_cache["last_sha"] else "HEAD"
            log = subprocess.run(
                ["git", "-C", tmp, "log", log_range, f"--author={GITHUB_USER}",
                 "--pretty=tformat:", "--numstat"],
                capture_output=True, text=True,
            )
            add, delete = 0, 0
            for line in log.stdout.splitlines():
                parts = line.split("\t")
                if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
                    add += int(parts[0])
                    delete += int(parts[1])

            head = subprocess.run(
                ["git", "-C", tmp, "rev-parse", "HEAD"], capture_output=True, text=True
            ).stdout.strip()

            repo_cache["add"] += add
            repo_cache["delete"] += delete
            repo_cache["last_sha"] = head or repo_cache["last_sha"]
            cache[name] = repo_cache

        total_add += repo_cache["add"]
        total_del += repo_cache["delete"]

    save_cache(cache)
    return {"add": total_add, "delete": total_del, "net": total_add - total_del}


# --------------------------------------------------------------------------
# SVG rendering
# --------------------------------------------------------------------------

def render(template_path: str, output_path: str, values: dict) -> None:
    with open(template_path, encoding="utf-8") as f:
        svg = f.read()
    for key, val in values.items():
        svg = svg.replace(f"{{{{{key}}}}}", str(val))
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(svg)


def main() -> None:
    print(f"Fetching stats for {GITHUB_USER}...")
    profile = get_profile_stats()
    commits = get_total_commits()
    loc = compute_loc(profile["repos"])

    values = {
        "repo_count": f"{profile['repo_count']:,}",
        "contributed_to": profile["contributed_to"],
        "stars": f"{profile['stars']:,}",
        "commits": f"{commits:,}",
        "followers": f"{profile['followers']:,}",
        "loc_add": f"{loc['add']:,}",
        "loc_delete": f"{loc['delete']:,}",
        "loc_total": f"{loc['net']:,}",
    }

    print(json.dumps(values, indent=2))

    render("templates/light_mode.svg", "light_mode.svg", values)
    render("templates/dark_mode.svg", "dark_mode.svg", values)
    print("Wrote light_mode.svg and dark_mode.svg")


if __name__ == "__main__":
    main()
