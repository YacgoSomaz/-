# Commercial Licensing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a deployable card-key licensing service and connect the desktop client to online activation, refresh, device binding, and revocation.

**Architecture:** The separate FastAPI licensing service owns card keys, device activations, audit rows, and the Ed25519 private key through environment variables. The desktop application sends only a salted device hash; it receives a signed license package that its existing `pipeline.license_manager` verifies locally before feature-gated routes can run.

**Tech Stack:** Python 3.11+, FastAPI, SQLite, cryptography Ed25519, requests, pytest.

## Global Constraints

- Never hardcode a signing private key, administrator token, card key, or database path in a distributable artifact.
- The installer contains only `LIVEWATCH_LICENSE_PUBLIC_KEY`; the private key remains server-side.
- All card keys and refresh tokens are stored as keyed SHA-256 hashes, never plaintext.
- Activation, refresh, and administrator APIs validate field length and syntax before database access.
- Production activation must use HTTPS and a domain-backed certificate.
- Existing developer mode stays unlocked until the release launcher enables `LIVEWATCH_LICENSE_ENFORCE=1`.

---

### Task 1: Licensing service core

**Files:**
- Create: `licensing_server/service.py`
- Create: `licensing_server/app.py`
- Create: `licensing_server/requirements.txt`
- Create: `licensing_server/.env.example`
- Test: `licensing_server/tests/test_service.py`

**Interfaces:**
- Produces `LicenseService.create_card_key`, `activate`, `refresh`, `freeze_activation`, and `unbind_activation`.
- Produces signed license documents compatible with `pipeline.license_manager.verify_license`.

- [ ] Write failing tests for activation, refresh, device-limit rejection, frozen-device rejection, and generated-license signature verification.
- [ ] Run `python -m pytest licensing_server/tests/test_service.py -q` and confirm it fails because the service does not exist.
- [ ] Implement the SQLite schema, hashed card keys/tokens, Ed25519 signing, and service methods.
- [ ] Re-run the focused service tests until they pass.

### Task 2: HTTP API and admin control

**Files:**
- Modify: `licensing_server/app.py`
- Test: `licensing_server/tests/test_api.py`

**Interfaces:**
- `POST /v1/activate` accepts `card_key`, `device_hash`, and `app_version`.
- `POST /v1/refresh` accepts `activation_id`, `refresh_token`, and `device_hash`.
- Admin endpoints require `Authorization: Bearer <LICENSE_ADMIN_TOKEN>`.

- [ ] Write failing API tests proving valid activation succeeds, missing admin authorization is rejected, and freeze causes refresh to fail.
- [ ] Run focused API tests and confirm the endpoints are missing.
- [ ] Implement request validation, generic public errors, audit logging, and protected card/activation operations.
- [ ] Re-run the focused API tests until they pass.

### Task 3: Desktop activation and feature enforcement

**Files:**
- Create: `_experiments/douyin_worker_route/pipeline/license_client.py`
- Modify: `_experiments/douyin_worker_route/pipeline/config.py`
- Modify: `_experiments/douyin_worker_route/pipeline/license_manager.py`
- Modify: `_experiments/douyin_worker_route/pipeline/webui.py`
- Test: `_experiments/douyin_worker_route/tests/test_license_client.py`
- Test: `_experiments/douyin_worker_route/tests/test_license_gates.py`

**Interfaces:**
- `license_client.activate_card_key(card_key)` obtains and persists a signed package.
- `license_client.refresh_license()` refreshes only with the local activation token.
- `license_manager.require_feature(feature)` returns a user-safe denial for inactive commercial features.

- [ ] Write failing tests for server-document persistence, invalid card key handling, and a blocked feature when enforcement is active.
- [ ] Run focused desktop tests and confirm expected failures.
- [ ] Implement remote activation/refresh with timeout and safe error messages, then add route guards for export, live monitoring, AI replay, short-video AI, and lead radar.
- [ ] Re-run focused desktop tests and the existing license suite until they pass.

### Task 4: Release hardening and operations documentation

**Files:**
- Modify: `packaging/build/livewatch_launcher.py`
- Modify: `packaging/build/build_release.ps1`
- Modify: `packaging/build/check_release.ps1`
- Modify: `packaging/build/check_release.py`
- Create: `licensing_server/README.md`
- Create: `docs/security/license-server-deployment.md`
- Test: `_experiments/douyin_worker_route/tests/test_release_scan.py`

**Interfaces:**
- Commercial builds inject `LIVEWATCH_LICENSE_ENFORCE=1`, an explicit server URL, and an Ed25519 public key.
- The release scanner rejects private signing material, runtime authorization files, source maps, tests, caches, and credential-like data.

- [ ] Write a failing scanner test containing a private-key marker and ensure the scanner does not currently accept it.
- [ ] Implement commercial launcher environment defaults and make the release build run both security scanners.
- [ ] Document local development, production environment variables, HTTPS reverse proxy deployment, database backup, card issuance, and revocation workflow.
- [ ] Run the full licensing test suite, scanner smoke tests, and a local activate → refresh → freeze → denied refresh integration flow.
