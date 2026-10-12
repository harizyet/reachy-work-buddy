# Document worker host (Phase 50 integrated deployment gate)

The worker runs on its own host (the Proxmox box): MinerU, CPU only, derived and rebuildable state only. companion-core, PostgreSQL and the authoritative `document-source` volume stay on the MS-01.
Losing this host makes document processing unavailable; it never loses a document, because the sync loop gives the retained originals back to a fresh worker.

## Layout

| Where | What | Backed up |
|---|---|---|
| MS-01 | PostgreSQL (document records), volume `document-source` (originals, content-addressed) | **yes, mandatory, together** |
| Worker host, volume `reachy-mineru` (`DOCUMENT_WORKER_VOLUME`) | MinerU library, parse cache, working copies | no (rebuildable); optional for faster recovery |
| Worker host, `DOCUMENT_WORKER_MODELS_DIR` | the two model bundles, read-only | no; `models.sha256` pins them, sources and revisions are in the [50A record](../../docs/verification/phase-50a-mineru-spike-2026-10-11.md) |

On ZFS, make `reachy-mineru` and the models directory separate datasets; to put the volume on a dataset, create it with `docker volume create --driver local -o type=none -o o=bind -o device=/path/to/dataset <name>` and set `DOCUMENT_WORKER_VOLUME=<name>`.

## Bring-up (on the worker host, from a checkout of this repository)

1. `cp .env.example .env` and set `DOCUMENT_WORKER_TOKEN` (`openssl rand -hex 32`; the same value goes into companion-core's `.env` as `DOCUMENT_WORKER_TOKEN`), `DOCUMENT_WORKER_BIND` (this host's private LAN or tailnet address) and `DOCUMENT_WORKER_MODELS_DIR`. `.env` is gitignored; keep it mode 600 and never paste the token into chat or logs.
2. Copy the model directory from the MS-01 (`~/.local/share/reachy-phase50a/models`) to `DOCUMENT_WORKER_MODELS_DIR` and run `./verify-models.sh`: all 17 files must match.
3. Firewall first, then start. Allow only the MS-01 to the worker port and drop everything else, for example with nftables on the worker host (replace the addresses; `18700` is `DOCUMENT_WORKER_PORT`):

   ```
   nft add rule inet filter input ip saddr <MS-01 address> tcp dport 18700 accept
   nft add rule inet filter input tcp dport 18700 drop
   ```

   Docker publishes ports ahead of the host's `INPUT` chain, so on a Docker host put the restriction in the `DOCKER-USER` chain (`iptables -I DOCKER-USER -p tcp --dport 18700 ! -s <MS-01 address> -j DROP`) and keep the container bound to the private address (`DOCUMENT_WORKER_BIND`), never `0.0.0.0`. The token is a second, independent control.
4. `docker compose up -d --build`, then `./verify-worker.sh`: every line must say `ok` (hardened container, no GPU, telemetry disabled, unauthenticated and wrong-token requests refused, bound to one address).
5. From the MS-01 check reachability and refusal: `curl http://<worker>:18700/health` answers; from any other host it must not connect.

## Connecting companion-core (MS-01, only after the worker verifies)

In `deploy/homelab/.env`: `DOCUMENT_WORKER_URL=http://<worker private address>:18700` and the same `DOCUMENT_WORKER_TOKEN`. Keep `DOCUMENT_LIBRARY_ENABLED=false` through the schema upgrade and the check of existing behaviour; enable it only as the last step (see the [50C record](../../docs/verification/phase-50c-integration-2026-10-12.md#integrated-deployment-gate)).

## Drill

`tools/document_gate_drill.py` runs the two scenarios worth running against a real worker with a throwaway PostgreSQL and source store (never production data): identical bytes under two policies (reprocess and delete one, the other stays valid), and a restore (database and source store restored, worker state destroyed, fresh worker, documents rebuilt by the sync loop). Pass `--reset-worker-cmd` for a worker on this machine, or omit it and wipe and restart the remote worker by hand when prompted.

## Upgrade and rollback

Rebuild and recreate with `docker compose up -d --build`; the pinned lock (`deploy/homelab/document-worker/requirements-mineru.txt`) is the version record. Rolling back is `docker compose down` and starting the previous image: nothing authoritative lives here.
