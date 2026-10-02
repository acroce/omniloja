#!/bin/sh
# Reap orphaned collectors even when Compose invokes node directly.
if [ "$$" -eq 1 ]; then
  exec tini -- /usr/local/bin/node-real "$@"
fi
exec /usr/local/bin/node-real "$@"
