#!/usr/bin/env bash
# Executed only after authenticated read-only VPS inventory and secret provisioning.
set -euo pipefail
base=/home/projects/call-translator-saas
service=call-translator-saas.service
include=/home/web/conf/web/ppsbot.pp.ua/nginx.ssl.conf_call-translator-saas
unit=/etc/systemd/system/$service
release=$(realpath -e -- "${1:?Absolute uploaded release directory required}")
[[ $(id -u) == 0 && "$release" == "$base/releases/"* ]] || { echo 'Invalid deployment root'; exit 1; }
[[ -f /etc/call-translator-saas.env && -x "$base/tools/uv" ]] || { echo 'Provision dedicated environment and uv first'; exit 1; }
grep -Fq '/home/web/conf/web/ppsbot.pp.ua/nginx.ssl.conf_*' /home/web/conf/web/ppsbot.pp.ua/nginx.ssl.conf || { echo 'Required Hestia custom include hook missing; generated config left untouched'; exit 1; }
for file in "$include" "$unit"; do
    if [[ -e "$file" ]] && ! head -n 1 "$file" | grep -q '^# Managed by Call Translator SaaS deployment\.$'; then
        echo 'Refusing to replace an unmanaged configuration'; exit 1
    fi
done
if [[ -e "$base/current" && ! -L "$base/current" ]]; then echo 'Current must be a managed release symlink'; exit 1; fi
previous=''
if [[ -f "$unit" && -L "$base/current" ]]; then previous=$(readlink -e "$base/current"); fi
[[ -z "$previous" || "$previous" == "$base/releases/"* ]] || { echo 'Unexpected current release'; exit 1; }
if ss -H -ltn 'sport = :5086' | grep -q .; then
    systemctl is-active --quiet "$service" || { echo 'Port 5086 is occupied by another service'; exit 1; }
    pid=$(systemctl show "$service" -p MainPID --value)
    [[ "$pid" != 0 ]] && ss -H -ltnp 'sport = :5086' | grep -Fq "pid=$pid," || { echo 'Port owner differs from the SaaS service'; exit 1; }
fi
if ! id call-translator-saas >/dev/null 2>&1; then
    useradd --system --home-dir "$base" --shell /usr/sbin/nologin call-translator-saas
fi
install -d -o call-translator-saas -g call-translator-saas -m 0700 "$base/shared"
backup="$base/backups/$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 0700 "$backup"
export UV_CACHE_DIR="$base/tools/uv-cache"
export UV_PYTHON_INSTALL_DIR="$base/tools/python"
if [[ -f "$base/shared/accounts.sqlite3" ]]; then
    "$base/tools/uv" run --no-project --python 3.11.9 python - "$base/shared/accounts.sqlite3" "$backup/accounts.sqlite3" <<'PY'
import sqlite3, sys
source = sqlite3.connect('file:'+sys.argv[1]+'?mode=ro', uri=True)
if source.execute("SELECT count(*) FROM calls WHERE state='active'").fetchone()[0]:
    raise SystemExit('Finish active SaaS calls before deployment')
target = sqlite3.connect(sys.argv[2]); source.backup(target); target.close(); source.close()
PY
fi
"$base/tools/uv" sync --project "$release" --frozen --no-default-groups --python 3.11.9
chmod -R a+rX "$release" "$base/tools/python"
for file in "$include" "$unit"; do [[ ! -f "$file" ]] || cp -p -- "$file" "$backup/$(basename "$file")"; done
changed=false
rollback() {
    [[ "$changed" == true ]] || return 0
    systemctl stop "$service" || true
    if [[ ! -f "$backup/$(basename "$unit")" ]]; then systemctl disable "$service" >/dev/null 2>&1 || true; fi
    if [[ -f "$backup/$(basename "$include")" ]]; then cp -p -- "$backup/$(basename "$include")" "$include"; else rm -f -- "$include"; fi
    if [[ -f "$backup/$(basename "$unit")" ]]; then cp -p -- "$backup/$(basename "$unit")" "$unit"; else rm -f -- "$unit"; fi
    systemctl daemon-reload
    if [[ -n "$previous" ]]; then
        ln -s -- "$previous" "$base/.current-rollback"; mv -Tf -- "$base/.current-rollback" "$base/current"
        systemctl restart "$service" || true
    else
        if [[ -L "$base/current" && "$(readlink -e "$base/current")" == "$release" ]]; then rm -- "$base/current"; fi
    fi
    nginx -t >/dev/null 2>&1 && systemctl reload nginx || true
}
trap 'rollback' ERR
changed=true
install -m 0644 "$release/deploy/call-translator-saas.service" "$unit"
install -m 0644 "$release/deploy/nginx.ssl.conf_call-translator-saas" "$include"
nginx -t
ln -s -- "$release" "$base/.current-new"
mv -Tf -- "$base/.current-new" "$base/current"
systemctl daemon-reload
systemctl enable "$service" >/dev/null
systemctl restart "$service"
ready=false
for _ in $(seq 1 30); do
    if curl --http1.1 -fsS http://127.0.0.1:5086/call-translator-saas/health >/dev/null; then ready=true; break; fi
    sleep 1
done
[[ "$ready" == true ]] || { echo 'SaaS readiness failed'; false; }
systemctl reload nginx
https_ready=false
for _ in $(seq 1 30); do
    if curl --http1.1 -fsS --max-time 5 https://ppsbot.pp.ua/call-translator-saas/health >/dev/null; then https_ready=true; break; fi
    sleep 1
done
[[ "$https_ready" == true ]] || { echo 'SaaS HTTPS readiness failed'; false; }
curl --http1.1 -fsS https://ppsbot.pp.ua/call-translator/health >/dev/null
changed=false
trap - ERR
echo 'SaaS release healthy; legacy HTTPS health preserved.'
