#!/usr/bin/env python3
"""Test an early CLTV spend or spend a funded output after its lock height."""

import argparse
import json
from decimal import Decimal
from pathlib import Path

from bitcoin.rpc import assert_regtest, ensure_wallet


DEFAULT_STATE = Path("~/.sats-in-a-bottle/cltv-state.json").expanduser()
FEE_BTC = Decimal("0.00001")


def json_default(value):
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def load_state(state_file: Path) -> dict:
    state = json.loads(state_file.expanduser().read_text(encoding="utf-8"))
    if state.get("network") != "regtest":
        raise RuntimeError("Refusing to spend state that was not created on regtest.")
    if state.get("output_type") != "p2wsh-miniscript":
        raise RuntimeError("State is not a P2WSH Miniscript output; refusing to spend it.")
    return state


def create_signed_spend(wallet, state: dict, locktime: int) -> str:
    unspent = wallet.gettxout(state["funding_txid"], state["vout"], True)
    if unspent is None:
        raise RuntimeError("The recorded CLTV funding output is missing or already spent.")
    value = unspent["value"]
    if value <= FEE_BTC:
        raise RuntimeError("CLTV output is too small to pay the configured transaction fee.")
    destination = wallet.getnewaddress("cltv-spend", "legacy")
    raw = wallet.createrawtransaction(
        [
            {
                "txid": state["funding_txid"],
                "vout": state["vout"],
                "sequence": 0xFFFFFFFE,
            }
        ],
        {destination: float(value - FEE_BTC)},
        locktime,
        False,
    )
    previous_output = {
        "txid": state["funding_txid"],
        "vout": state["vout"],
        "scriptPubKey": state["script_pubkey"],
        "witnessScript": state["witness_script"],
        "amount": float(value),
    }
    signed = wallet.signrawtransactionwithwallet(raw, [previous_output])
    if not signed["complete"]:
        errors = json.dumps(signed.get("errors", []), sort_keys=True)
        raise RuntimeError(f"Bitcoin Core could not completely sign the CLTV spend: {errors}")
    return signed["hex"]


def assert_expected_timelock_rejection(wallet, state: dict) -> str:
    height = wallet.getblockcount()
    if height >= state["lock_height"]:
        raise RuntimeError("The chain is already at the CLTV height; cannot test an early spend.")
    # CLTV must pass during signing; mempool finality still rejects this before its height.
    signed_hex = create_signed_spend(wallet, state, state["lock_height"])
    result = wallet.testmempoolaccept([signed_hex])[0]
    reason = result.get("reject-reason", "")
    if result.get("allowed") or "non-final" not in reason.lower():
        raise AssertionError(
            "Early spend did not fail for the expected non-final locktime reason; "
            f"allowed={result.get('allowed')}, reject-reason={reason!r}"
        )
    return reason


def spend_after_unlock(wallet, state: dict) -> dict:
    height = wallet.getblockcount()
    if height < state["lock_height"]:
        wallet.generatetoaddress(state["lock_height"] - height, wallet.getnewaddress("cltv-mining", "legacy"))
    signed_hex = create_signed_spend(wallet, state, state["lock_height"])
    acceptance = wallet.testmempoolaccept([signed_hex])[0]
    if not acceptance.get("allowed"):
        raise RuntimeError(
            "Post-unlock spend was rejected: " + acceptance.get("reject-reason", "unknown reason")
        )
    txid = wallet.sendrawtransaction(signed_hex)
    wallet.generatetoaddress(1, wallet.getnewaddress("cltv-confirm", "legacy"))
    transaction = wallet.gettransaction(txid, True)
    if transaction["confirmations"] < 1 or not transaction.get("blockhash"):
        raise RuntimeError("Spend transaction was broadcast but not confirmed.")
    block_height = wallet.getblockheader(transaction["blockhash"])["height"]
    decoded = wallet.getrawtransaction(txid, True, transaction["blockhash"])
    if not decoded["vout"]:
        raise RuntimeError("Confirmed spend transaction has no outputs.")
    return {
        "txid": txid,
        "confirmations": transaction["confirmations"],
        "block_height": block_height,
        "outputs": decoded["vout"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-file", type=Path, default=DEFAULT_STATE)
    parser.add_argument(
        "--before-unlock",
        action="store_true",
        help="Verify an early spend is rejected specifically by CLTV; do not broadcast it",
    )
    args = parser.parse_args()
    wallet = ensure_wallet()
    assert_regtest(wallet)
    state = load_state(args.state_file)
    if args.before_unlock:
        reason = assert_expected_timelock_rejection(wallet, state)
        print(json.dumps({"result": "expected rejection", "reject_reason": reason}, indent=2))
    else:
        print(json.dumps(spend_after_unlock(wallet, state), indent=2, default=json_default))


if __name__ == "__main__":
    main()