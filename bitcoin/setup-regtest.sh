#!/usr/bin/env bash
set -eu

datadir="${BITCOIN_DATADIR:-$HOME/.bitcoin}"
mkdir -p "$datadir"

if ! command -v bitcoind >/dev/null 2>&1 || ! command -v bitcoin-cli >/dev/null 2>&1; then
    printf '%s\n' "Install Bitcoin Core and ensure bitcoind and bitcoin-cli are on PATH." >&2
    exit 1
fi

rpc() {
    bitcoin-cli -regtest -datadir="$datadir" "$@"
}

if rpc getblockchaininfo >/dev/null 2>&1; then
    printf 'Bitcoin Core is already responding on regtest using %s\n' "$datadir"
else
    bitcoind -regtest -server -daemon -datadir="$datadir" -fallbackfee=0.0002
    attempt=0
    until rpc getblockchaininfo >/dev/null 2>&1; do
        attempt=$((attempt + 1))
        if [ "$attempt" -ge 30 ]; then
            printf '%s\n' "Bitcoin Core did not become RPC-ready within 30 seconds." >&2
            exit 1
        fi
        sleep 1
    done
fi

rpc getblockchaininfo