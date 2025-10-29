#!/bin/bash
set -e

# Determine primary and backup based on ACTIVE_POOL
if [ "$ACTIVE_POOL" = "green" ]; then
  PRIMARY="app_green:8082"
  BACKUP="app_blue:8081"
else
  PRIMARY="app_blue:8081"
  BACKUP="app_green:8082"
fi

# Export variables for envsubst
export PRIMARY BACKUP

# Render template
envsubst '\$PRIMARY \$BACKUP' < /etc/nginx/templates/nginx.conf.template > /etc/nginx/nginx.conf

# Start nginx
nginx -g 'daemon off;'
