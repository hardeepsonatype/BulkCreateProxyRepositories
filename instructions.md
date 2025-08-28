Bulk Create Proxy Repositories in Sonatype Nexus Repository
===========================================================
This document provides a ready-to-run Python script that bulk-creates **proxy** repositories in
Sonatype Nexus Repository (Repo Manager) by reading rows from a CSV.
---
CSV expected columns
--------------------
name,repo_type,repo_format,proxy_url,blob_store
- **name** – the repository name to create
- **repo_type** – should be `proxy` for this use case
- **repo_format** – e.g., `maven`, `npm`, `pypi`, `nuget`, `docker`, `raw`, `rubygems`, `yum`, `helm`,
`go`, `cargo`
- **proxy_url** – remote URL to proxy
- **blob_store** – existing blob store name in your Nexus
Example row:
```
my-maven-central,proxy,maven,https://repo1.maven.org/maven2,default
```
---
Python Script (bulk_create_proxy_repos.py)
------------------------------------------
#!/usr/bin/env python3
Full script provided in the earlier answer
---
How to run
----------
```bash
# Option 1: env vars
export NEXUS_BASE_URL="http://nexus.company.local:8081"
export NEXUS_USER="admin"
export NEXUS_PASSWORD="***"
python3 bulk_create_proxy_repos.py repos.csv
# Self-signed HTTPS?
python3 bulk_create_proxy_repos.py repos.csv --insecure
# Dry-run to preview requests:
python3 bulk_create_proxy_repos.py repos.csv --dry-run
```
---
Notes & extension points
------------------------
- **Endpoint**: The script posts to `/service/rest/v1/repositories/{format}/proxy` with a minimal, valid
body including `storage`, `proxy.remoteUrl`, and sensible cache defaults—per Sonatype’s
**Repositories API**.
- **Formats**: Alias mapping lets you pass `maven` or `maven2`, `python` or `pypi`, etc.
- **Idempotency**: It checks existence via `GET /service/rest/v1/repositories/{name}` and skips if
present.
- **Policies, routing rules, auth**: Uncomment/add `cleanup.policyNames`, `routingRuleName`, or
`httpClient.authentication` if your instance requires them.
If you want, you can further customize format-specific payloads or extend for hosted/group repos.