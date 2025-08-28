#!/usr/bin/env python3
import csv
import os
import sys
import json
import argparse
import getpass
import time
from urllib.parse import urljoin
import requests

# Default timeouts / retries
REQUEST_TIMEOUT = 30

# Map a few common aliases to the API path "format"
FORMAT_ALIASES = {
    "maven2": "maven",
    "maven": "maven",
    "npm": "npm",
    "pypi": "pypi",
    "python": "pypi",
    "nuget": "nuget",
    "docker": "docker",
    "raw": "raw",
    "rubygems": "rubygems",
    "gem": "rubygems",
    "yum": "yum",
    "rpm": "yum",
    "helm": "helm",
    "go": "go",
    "golang": "go",
    "cargo": "cargo",
    "rust": "cargo",
}

def normalize_format(fmt: str) -> str:
    key = (fmt or "").strip().lower()
    if key not in FORMAT_ALIASES:
        raise ValueError(f"Unsupported repo_format '{fmt}'. Supported: {', '.join(sorted(set(FORMAT_ALIASES.keys())))}")
    return FORMAT_ALIASES[key]

def build_proxy_payload(name: str, blob_store: str, remote_url: str, fmt: str) -> dict:
    """
    Minimal, API-valid proxy payload for most formats.
    You can extend format-specific sections if needed.
    """
    payload = {
        "name": name,
        "online": True,
        "storage": {
            "blobStoreName": blob_store,
            "strictContentTypeValidation": True
        },
        "proxy": {
            "remoteUrl": remote_url,
            # Reasonable cache defaults (seconds)
            "contentMaxAge": 14400,     # 4h
            "metadataMaxAge": 14400
        },
        "negativeCache": {
            "enabled": True,
            "timeToLive": 1440  # minutes
        },
        "httpClient": {
            "blocked": False,
            "autoBlock": True
        },
        # "routingRuleName": None,  # add if you use routing rules
        # "cleanup": {"policyNames": ["your-policy"]},
    }

    # Add empty per-format sections only when commonly expected by Swagger.
    # These no-op sections are harmless and keep the payload future-friendly.
    fmt = fmt.lower()
    if fmt == "maven":
        # *** FIX STARTS HERE ***
        # Maven proxies require versionPolicy and layoutPolicy
        payload["maven"] = {
            "versionPolicy": "RELEASE", # Or "SNAPSHOT", or "MIXED"
            "layoutPolicy": "STRICT"    # Or "PERMISSIVE"
        }
        # *** FIX ENDS HERE ***
    elif fmt == "npm":
        payload["npm"] = {}
    elif fmt == "pypi":
        payload["pypi"] = {}
    elif fmt == "nuget":
        payload["nugetProxy"] = {"queryCacheItemMaxAge": 3600}  # common optional
    elif fmt == "docker":
        payload["docker"] = {}  # proxy doesn't need ports (hosted does)
    elif fmt == "rubygems":
        payload["rubygems"] = {}
    elif fmt == "yum":
        payload["yum"] = {}
    elif fmt == "helm":
        payload["helm"] = {}
    elif fmt == "go":
        payload["go"] = {}
    elif fmt == "cargo":
        payload["cargo"] = {}

    return payload

def repository_exists(base_url: str, auth, name: str, verify_ssl: bool):
    # GET /service/rest/v1/repositories/{name}
    url = urljoin(base_url, f"/service/rest/v1/repositories/{name}")
    r = requests.get(url, auth=auth, timeout=REQUEST_TIMEOUT, verify=verify_ssl)
    if r.status_code == 200:
        return True
    if r.status_code == 404:
        return False
    r.raise_for_status()

def create_proxy_repo(base_url: str, auth, repo_format: str, payload: dict, verify_ssl: bool):
    # POST /service/rest/v1/repositories/{format}/proxy
    path_fmt = normalize_format(repo_format)
    url = urljoin(base_url, f"/service/rest/v1/repositories/{path_fmt}/proxy")
    r = requests.post(url, json=payload, auth=auth, timeout=REQUEST_TIMEOUT, verify=verify_ssl)
    return r

def parse_args():
    p = argparse.ArgumentParser(description="Bulk-create proxy repositories in Sonatype Nexus Repository from CSV")
    p.add_argument("csv_path", help="Path to CSV with columns: name,repo_type,repo_format,proxy_url,blob_store")
    p.add_argument("--base-url", default=os.environ.get("NEXUS_BASE_URL", "http://localhost:8081"),
                   help="Base URL to Nexus (default: %(default)s or $NEXUS_BASE_URL)")
    p.add_argument("--user", default=os.environ.get("NEXUS_USER", "admin"),
                   help="Username (default: %(default)s or $NEXUS_USER)")
    p.add_argument("--password", default=os.environ.get("NEXUS_PASSWORD"),
                   help="Password or token (use env $NEXUS_PASSWORD to avoid prompts)")
    p.add_argument("--insecure", action="store_true",
                   help="Disable TLS verification (useful for self-signed)")
    p.add_argument("--dry-run", action="store_true",
                   help="Print requests without creating anything")
    return p.parse_args()

def main():
    args = parse_args()
    verify_ssl = not args.insecure

    password = args.password or getpass.getpass("Nexus password/token: ")
    auth = (args.user, password)

    successes, skips, failures = 0, 0, 0

    with open(args.csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        required = {"name", "repo_type", "repo_format", "proxy_url", "blob_store"}
        missing = required - set(h.strip() for h in reader.fieldnames or [])
        if missing:
            sys.exit(f"CSV is missing required columns: {', '.join(sorted(missing))}")

        for i, row in enumerate(reader, start=1):
            name = (row.get("name") or "").strip()
            repo_type = (row.get("repo_type") or "").strip().lower()
            repo_format = (row.get("repo_format") or "").strip()
            proxy_url = (row.get("proxy_url") or "").strip()
            blob_store = (row.get("blob_store") or "").strip()

            if not all([name, repo_type, repo_format, proxy_url, blob_store]):
                print(f"[row {i}] Skipping: incomplete data -> {row}")
                skips += 1
                continue

            if repo_type != "proxy":
                print(f"[row {i}] Skipping '{name}': repo_type is '{repo_type}', only 'proxy' is handled.")
                skips += 1
                continue

            try:
                fmt_for_path = normalize_format(repo_format)
            except Exception as e:
                print(f"[row {i}] Skipping '{name}': {e}")
                skips += 1
                continue

            # Skip if it already exists
            try:
                if repository_exists(args.base_url, auth, name, verify_ssl):
                    print(f"[row {i}] Exists -> {name} (skipping)")
                    skips += 1
                    continue
            except requests.HTTPError as e:
                print(f"[row {i}] Warning: existence check failed for '{name}': {e}, continuing to create...")

            payload = build_proxy_payload(name, blob_store, proxy_url, fmt_for_path)

            if args.dry_run:
                print(f"[row {i}] DRY-RUN would POST /repositories/{fmt_for_path}/proxy with payload:\n{json.dumps(payload, indent=2)}")
                successes += 1
                continue

            try:
                resp = create_proxy_repo(args.base_url, auth, fmt_for_path, payload, verify_ssl)
                if resp.status_code in (200, 201):
                    print(f"[row {i}] Created -> {name}")
                    successes += 1
                elif resp.status_code == 400:
                    print(f"[row {i}] Failed (400) -> {name}: {resp.text}")
                    failures += 1
                elif resp.status_code == 401:
                    print(f"[row {i}] Failed (401 Unauthorized) -> check credentials")
                    failures += 1
                elif resp.status_code == 409:
                    print(f"[row {i}] Conflict (already exists?) -> {name}")
                    skips += 1
                else:
                    print(f"[row {i}] Failed ({resp.status_code}) -> {name}: {resp.text}")
                    failures += 1
            except requests.RequestException as e:
                print(f"[row {i}] Error -> {name}: {e}")
                failures += 1

            # Small delay to be gentle on the server (optional)
            time.sleep(0.1)

    print(f"\nDone. created={successes} skipped={skips} failed={failures}")

if __name__ == "__main__":
    main()
