#!/bin/sh
set -e
envsubst '$PORT' < /etc/nginx/nginx.conf.template > /etc/nginx/nginx.conf
exec nginx -g 'daemon off;'
