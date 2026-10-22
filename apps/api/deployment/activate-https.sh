#!/bin/bash
# Requires a previously registered Certbot account and reviewed operator consent.
# Usage: activate-https.sh DOMAIN COMPOSE_DIRECTORY [PROXY_CONFIG_DIRECTORY]
set -euo pipefail
umask 077
domain=${1:?Specify the reviewed domain}
deployment=$(realpath "${2:?Specify the Compose directory}")
configuration=${3:-/etc/we2day-proxy}
[[ $domain =~ ^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$ && $domain == *.* ]]
[[ -d $configuration && ! -L $configuration ]]
[[ -f $deployment/.env && ! -L $deployment/.env ]]
[[ -f $deployment/compose.yaml && ! -L $deployment/compose.yaml ]]
[[ $(grep -c '^WE2DAY_SITE_ORIGIN=' "$deployment/.env") == 1 ]]
[[ $(grep -c '^WE2DAY_ALLOWED_ORIGINS=' "$deployment/.env") == 1 ]]

# A rate-limit or validation failure exits before any running app/config changes.
certbot certonly --non-interactive --webroot --webroot-path /var/lib/we2day-acme \
    --domain "$domain" --cert-name "$domain" --key-type ecdsa --keep-until-expiring
lineage=/etc/letsencrypt/live/$domain
openssl x509 -in "$lineage/cert.pem" -noout -checkend 86400
openssl x509 -in "$lineage/cert.pem" -noout -checkhost "$domain"
openssl verify -CApath /etc/ssl/certs -untrusted "$lineage/chain.pem" "$lineage/cert.pem"
nginx -t -c "$configuration/nginx.https.pending.conf"

# Exclusive snapshot: never overwrite earlier rollback evidence on a second run.
snapshot=$configuration/pre-https
mkdir "$snapshot"
cp -p "$deployment/.env" "$snapshot/compose.env"
cp -p "$configuration/nginx.conf" "$snapshot/nginx.conf"
envtmp=
rollback() {
    local failure=$?
    trap - EXIT
    set +e
    local restored=1
    cp -p "$snapshot/compose.env" "$deployment/.env" || restored=0
    cp -p "$snapshot/nginx.conf" "$configuration/nginx.conf" || restored=0
    if [[ -n $envtmp && -f $envtmp ]]; then rm -- "$envtmp"; fi
    nginx -t -c "$configuration/nginx.conf" && systemctl reload we2day-proxy.service || restored=0
    docker compose --project-directory "$deployment" up --detach --no-build --pull never \
        --wait --wait-timeout 120 || restored=0
    if [[ $restored == 1 ]]; then
        echo 'HTTPS activation failed; previous app and proxy configuration restored' >&2
    else
        echo 'HTTPS activation failed; operator recovery required from private pre-https snapshot' >&2
    fi
    exit "$failure"
}
trap rollback EXIT
envtmp=$(mktemp "$deployment/.env.https.XXXXXX")
sed -e "s|^WE2DAY_SITE_ORIGIN=.*|WE2DAY_SITE_ORIGIN=https://$domain|" \
    -e "s|^WE2DAY_ALLOWED_ORIGINS=.*|WE2DAY_ALLOWED_ORIGINS=[\"https://$domain\"]|" \
    "$deployment/.env" > "$envtmp"
chmod 600 "$envtmp"
chown --reference="$deployment/.env" "$envtmp"
mv -- "$envtmp" "$deployment/.env"
envtmp=
docker compose --project-directory "$deployment" config --quiet
docker compose --project-directory "$deployment" up --detach --no-build --pull never \
    --wait --wait-timeout 120
cp -p "$configuration/nginx.https.pending.conf" "$configuration/nginx.conf"
systemctl reload we2day-proxy.service
# Explicit CA validation: no --insecure and no browser warning bypass.
# nginx reload returns after signalling; allow the new TLS listener to become ready.
curl --fail --silent --show-error --connect-timeout 5 --max-time 15 \
    --retry 5 --retry-connrefused --retry-delay 1 --retry-max-time 20 \
    --resolve "$domain:443:127.0.0.1" "https://$domain/login" --output /dev/null
status=$(curl --silent --show-error --connect-timeout 5 --max-time 15 \
    --resolve "$domain:443:127.0.0.1" "https://$domain/api/plans" \
    --output /dev/null --write-out '%{http_code}')
[[ $status == 401 ]]
systemctl enable we2day-proxy.service
systemctl enable --now certbot.timer
trap - EXIT
echo 'HTTPS activation succeeded; external browser and device acceptance still required'
