#!/usr/bin/env sh
# Container entrypoint: bootstrap data on first run, then exec the lorscan CLI.
#
# Bootstrap policy:
#   1. If LORSCAN_DATA_DIR has no DB, pull the catalog from lorcana-api.com.
#   2. If there are no embeddings, download every catalog image and build them.
#   3. Hand off to the requested subcommand (default: serve).
#
# Both steps are skipped on subsequent starts because the DB and embeddings.npz
# persist in the mounted volume. To force a re-sync (e.g. after a new Lorcana
# chapter releases), `docker exec lorscan lorscan sync-catalog` and likewise
# `index-images`.

set -e

DATA_DIR="${LORSCAN_DATA_DIR:-/data}"
DB="$DATA_DIR/lorscan.db"
EMB="$DATA_DIR/embeddings.npz"

mkdir -p "$DATA_DIR"

if [ ! -f "$DB" ]; then
    echo "[lorscan] First run: syncing catalog from lorcana-api.com..."
    lorscan sync-catalog
fi

if [ ! -f "$EMB" ]; then
    echo "[lorscan] First run: building image embeddings (this takes 20-40 min on a NAS)..."
    lorscan index-images
fi

case "$1" in
    serve)
        echo "[lorscan] Starting web UI on http://0.0.0.0:8000"
        exec lorscan serve --host 0.0.0.0 --no-reload
        ;;
    "")
        echo "[lorscan] No command given; defaulting to serve"
        exec lorscan serve --host 0.0.0.0 --no-reload
        ;;
    *)
        exec lorscan "$@"
        ;;
esac
