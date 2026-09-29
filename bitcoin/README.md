# Sats in a Bottle: Bitcoin CLTV Prototype

This small proof of concept locks test coins to a future **block height** on
Bitcoin Core regtest. It uses Core 31.1's descriptor-supported P2WSH Miniscript
wallet flow and Python's standard library; it does not use mainnet, real BTC,
Lightning, or an external Bitcoin package.

## CLTV in this prototype

`OP_CHECKLOCKTIMEVERIFY` (CLTV) checks a spending transaction's `nLockTime`
against a required value in the witness script. The Miniscript policy is:

```text
wsh(and_v(v:after(<required block height>),pk(<public key>)))
```

Core compiles the witness script as
`<height> OP_CHECKLOCKTIMEVERIFY OP_VERIFY <public key> OP_CHECKSIG`. CLTV
leaves the positive height on the stack, and `OP_VERIFY` consumes it. This is
semantically equivalent to the previous `OP_DROP` for valid positive block
heights. The descriptor lets Core's wallet understand and sign the policy
while preserving its height-and-signature spending conditions. Sats in a
Bottle can use this to keep Bitcoin associated with a bottle unspendable until
its chosen block height. This prototype demonstrates only a height-based
condition, not message encryption or application behavior.

The spend transaction must have a height-based `nLockTime` at least as large
as the script's height, and the spending input's sequence must not be final
(`0xffffffff`). The chain must also have advanced far enough for that
transaction locktime to be final. These are related but distinct checks.
Before the unlock height, the test sets `nLockTime` to the script's required
height so the CLTV script can be signed and validated. Bitcoin Core's mempool
then rejects the transaction as non-final until the chain reaches that height.
At the required height, the test uses the same `nLockTime`, submits the spend,
mines a confirmation, and checks the confirmed transaction output.

## Requirements

- Bitcoin Core **31.1**, with `bitcoind` and `bitcoin-cli` on PATH.
- Python 3.10 or newer.
- A Linux shell, including Ubuntu on WSL. No Python packages are required.

The prototype creates or loads the descriptor wallet named
`sats-in-a-bottle` with private keys enabled. Funding builds a private form of
the checksummed `wsh(and_v(v:after(...),pk(...)))` descriptor from that
wallet's existing ranged key descriptor and imports only the matching key
index. This lets Core recognize and sign the policy. The private descriptor is
kept in memory for the RPC call; only the public descriptor is written to the
state file. The spend script refuses older P2SH state files, leaving the
existing P2SH output untouched.

## Start regtest

Install Bitcoin Core from the official Bitcoin Core distribution for your
platform, then make `bitcoind` and `bitcoin-cli` available in the Linux/WSL
shell. From the repository root, run:

```sh
bash bitcoin/setup-regtest.sh
```

The script starts a daemon with `-regtest`, `-server`, and a fallback fee, or
reuses a responding regtest node. It does not delete or reset the data
directory. By default, Bitcoin Core data stays in `~/.bitcoin`; override it
with `BITCOIN_DATADIR=/path/to/data`. RPC uses Bitcoin Core's generated cookie
file. Do not put credentials or keys in this repository.

To check the node manually:

```sh
bitcoin-cli -regtest getblockchaininfo
bitcoin-cli -regtest getblockchaininfo   # chain should be "regtest"
```

The Python scripts use the same default datadir and RPC port. Set
`BITCOIN_DATADIR` if the node uses a different data directory. For a custom
RPC endpoint, set `BITCOIN_RPC_URL` (default `http://127.0.0.1:18443`). Cookie
authentication is preferred; alternatively set both `BITCOIN_RPC_USER` and
`BITCOIN_RPC_PASSWORD` to match a local Core configuration.

## Run the flow

Run commands from the repository root, with the regtest daemon running:

```sh
python3 bitcoin/fund_cltv.py
```

This creates/uses the descriptor wallet, mines 101 blocks if it needs mature
coinbase funds, creates a CLTV P2WSH output for `0.001` BTC, broadcasts and
confirms its funding transaction, and writes non-secret transaction metadata
to `~/.sats-in-a-bottle/cltv-state.json`. The lock height defaults to six
blocks beyond the chain tip before funding confirmation. To select a height
explicitly or choose another small amount:

```sh
python3 bitcoin/fund_cltv.py --height 120 --amount 0.001
```

The explicit height must be at least two blocks above the current tip before
funding. The saved state contains the txid, output index, checksummed
descriptor, witness script, scriptPubKey, and address, but no private key.

Test the early spend. This builds and signs a transaction but uses
`testmempoolaccept`; it does not broadcast the invalid spend:

```sh
python3 bitcoin/spend_cltv.py --before-unlock
```

Expected result includes `expected rejection` and a non-final reject reason.
The signed transaction uses the required `nLockTime` and a non-final sequence;
the mempool rejects it until the chain reaches that height. Then spend after
the height:

```sh
python3 bitcoin/spend_cltv.py
```

This mines to the required height if needed, builds a spend with matching
`nLockTime` and a non-final sequence, verifies mempool acceptance, broadcasts
it, mines a confirmation, and displays the confirmed transaction and outputs.

To construct/display a locking script independently, supply a wallet public
key and future height:

```sh
python3 bitcoin/create_cltv.py --height 120 --pubkey <hex-public-key>
```

## Automated tests

Run the full suite, including the end-to-end regtest flow:

```sh
python3 -m unittest bitcoin.test_cltv -v
```

The integration test confirms the node reports `regtest`, prepares mature
funds, funds a fresh CLTV output, checks the expected pre-unlock rejection,
advances to the required height, spends, and verifies a confirmed output. Each
run uses a fresh key/output and a temporary state file; it does not reset the
regtest chain or spend a prior run's output. The two script
construction tests can run without Bitcoin Core:

```sh
python3 -m unittest bitcoin.test_cltv.TestCLTVScript -v
```

## Assumptions and limitations

- **Regtest only:** every RPC workflow checks the node's reported chain before
  doing wallet or transaction work. Never point these scripts at mainnet or
  testnet.
- **Local wallet:** a locally running, unlocked descriptor wallet owns the key
  and funds the output. The scripts do not export or print private keys.
- **Height semantics:** heights below `500000000` use block-height locktimes;
  values at or above that threshold are timestamps and are rejected by the
  script builder.
- **Version behavior:** the flow uses descriptor, Miniscript, and wallet RPCs
  supported by Bitcoin Core 31.1, including `importdescriptors`,
  `signrawtransactionwithwallet`, and `testmempoolaccept`.
- **No application integration:** this is a synchronous local demo, not a
  backend API, production custody design, fee strategy, encrypted-message
  implementation, or Lightning implementation.
- **Repeatability:** repeated tests add blocks and create new wallet keys and
  outputs in the existing regtest data directory. No chain reset is performed.
