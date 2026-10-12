#!/bin/sh
# Read-only checks of a running document worker: hardened, CPU only, telemetry off, authenticated, bound to one private address.
# Usage: ./verify-worker.sh [container]   (default: reachy-document-worker-document-worker-1). Reads the token from .env.
set -u
here=$(cd "$(dirname "$0")" && pwd)
c=${1:-reachy-document-worker-document-worker-1}
fail=0
check() { if eval "$2"; then echo "ok   $1"; else echo "FAIL $1"; fail=1; fi; }
insp() { docker inspect "$c" --format "$1"; }
check "container is running and healthy" '[ "$(insp "{{.State.Health.Status}}")" = healthy ]'
check "root filesystem read-only" '[ "$(insp "{{.HostConfig.ReadonlyRootfs}}")" = true ]'
check "all capabilities dropped" '[ "$(insp "{{.HostConfig.CapDrop}}")" = "[ALL]" ]'
check "no-new-privileges" 'insp "{{.HostConfig.SecurityOpt}}" | grep -q no-new-privileges'
check "runs as a non-root user" '[ "$(docker exec "$c" id -u)" != 0 ]'
check "no GPU request and no device mapped" '[ "$(insp "{{.HostConfig.DeviceRequests}}")" = "[]" ] && [ "$(insp "{{.HostConfig.Devices}}")" = "[]" ]'
check "no GPU visible inside (no /dev/nvidia*, no /dev/dri)" '! docker exec "$c" sh -c "ls /dev/nvidia* /dev/dri 2>/dev/null | grep -q ."'
check "memory and CPU limits set" '[ "$(insp "{{.HostConfig.Memory}}")" != 0 ] && [ "$(insp "{{.HostConfig.NanoCpus}}")" != 0 ]'
check "models mounted read-only" 'insp "{{range .Mounts}}{{.Destination}}={{.RW}} {{end}}" | grep -q "/models=false"'
check "published on one specific address (not 0.0.0.0 or ::)" 'insp "{{json .NetworkSettings.Ports}}" | grep -q HostIp && ! insp "{{json .NetworkSettings.Ports}}" | grep -Eq "\"HostIp\":\"(0\.0\.0\.0|::)?\""'
health=$(docker exec "$c" python -c "import urllib.request;print(urllib.request.urlopen(\"http://localhost:8000/health\").read().decode())" 2>/dev/null)
check "health ok with telemetry disabled" 'echo "$health" | grep -q "\"ok\":true" && echo "$health" | grep -q "\"telemetry_disabled\":true"'
check "unauthenticated request is refused" '[ "$(docker exec "$c" python -c "import urllib.request,urllib.error
try: urllib.request.urlopen(\"http://localhost:8000/documents/x/status\"); print(200)
except urllib.error.HTTPError as e: print(e.code)")" = 401 ]'
check "wrong token is refused" '[ "$(docker exec "$c" python -c "import urllib.request,urllib.error
r=urllib.request.Request(\"http://localhost:8000/documents/x/status\",headers={\"Authorization\":\"Bearer wrong\"})
try: urllib.request.urlopen(r); print(200)
except urllib.error.HTTPError as e: print(e.code)")" = 401 ]'
exit $fail
