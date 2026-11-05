#!/bin/sh
# Install Claude Pets: hooks, skills, launcher — and bring the pets out.
set -e
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec /usr/bin/env python3 -I "$here/bin/claude-pets" install "$@"
