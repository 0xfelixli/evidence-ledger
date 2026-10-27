#!/bin/sh
LEDGER_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec python3 "$LEDGER_ROOT/run.py" serve --out "$LEDGER_ROOT/runs/workbench" --example "$LEDGER_ROOT/examples/chain-love-npm.csv" --open
