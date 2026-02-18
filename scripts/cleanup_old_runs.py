#!/usr/bin/env python3
"""
Elimina tutti i workflow run completati più vecchi di 1 ora.
Richiede la variabile d'ambiente GITHUB_TOKEN con permesso actions:write.
"""
import os
import sys
from datetime import datetime, timezone, timedelta
import urllib.request
import urllib.error
import json

OWNER = "ilmarins00"
REPO = "MeteoBot"
BASE_URL = f"https://api.github.com/repos/{OWNER}/{REPO}"
CUTOFF_HOURS = 1


def github_request(method: str, path: str) -> tuple[int, dict | None]:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_PAT", "")
    if not token:
        print("ERRORE: GITHUB_TOKEN non impostato.", file=sys.stderr)
        sys.exit(1)
    url = f"{BASE_URL}{path}"
    req = urllib.request.Request(url, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    try:
        with urllib.request.urlopen(req) as resp:
            body = json.loads(resp.read()) if resp.length != 0 else None
            return resp.status, body
    except urllib.error.HTTPError as e:
        return e.code, None


def get_all_completed_runs() -> list[dict]:
    """Recupera tutti i run completati (pagina per pagina)."""
    runs = []
    page = 1
    while True:
        path = f"/actions/runs?status=completed&per_page=100&page={page}"
        status, data = github_request("GET", path)
        if status != 200 or not data:
            break
        batch = data.get("workflow_runs", [])
        if not batch:
            break
        runs.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return runs


def main():
    cutoff = datetime.now(timezone.utc) - timedelta(hours=CUTOFF_HOURS)
    print(f"Cutoff: {cutoff.isoformat()} (run completati prima di quest'ora verranno eliminati)")

    runs = get_all_completed_runs()
    print(f"Run completati trovati: {len(runs)}")

    deleted = 0
    skipped = 0
    errors = 0

    for run in runs:
        created_str = run.get("created_at", "")
        try:
            created_at = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
        except ValueError:
            skipped += 1
            continue

        if created_at >= cutoff:
            skipped += 1
            continue

        run_id = run["id"]
        workflow_name = run.get("name", "?")
        status_code, _ = github_request("DELETE", f"/actions/runs/{run_id}")
        if status_code == 204:
            print(f"  Eliminato: [{run_id}] {workflow_name} — {created_str}")
            deleted += 1
        else:
            print(f"  Errore {status_code}: [{run_id}] {workflow_name}")
            errors += 1

    print(f"\nRiepilogo: {deleted} eliminati, {skipped} ignorati (troppo recenti), {errors} errori")


if __name__ == "__main__":
    main()
