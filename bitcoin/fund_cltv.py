#!/usr/bin/env python3
"""Create, fund, and confirm a P2WSH Miniscript CLTV output on regtest."""

import argparse
import json
from decimal import Decimal
from pathlib import Path

from bitcoin.cltv import (
    build_cltv_miniscript_descriptor,
    build_cltv_miniscript_descriptor_for_key,
    build_cltv_witness_script,
    p2wsh_script_pubkey,
)
from bitcoin.rpc import BitcoinRPC, assert_regtest, ensure_wallet

DEFAULT_STATE = Path("~/.sats-in-a-bottle/cltv-state.json").expanduser()


def private_key_expression(wallet, node, address: str) -> tuple[str, int]:
    key_info = wallet.getaddressinfo(address)
    path_parts = key_info.get("hdkeypath", "").split("/")
    if len(path_parts) < 3 or path_parts[0] != "m":
        raise RuntimeError("Bitcoin Core did not return a derivation path for the CLTV key.")
    try:
        branch = int(path_parts[-2].rstrip("h'"))
        index = int(path_parts[-1].rstrip("h'"))
    except ValueError as error:
        raise RuntimeError("Bitcoin Core returned an unsupported CLTV key derivation path.") from error

    for item in wallet.listdescriptors(True)["descriptors"]:
        private_descriptor = item["desc"].split("#", 1)[0]
        if not private_descriptor.startswith("pkh(") or not private_descriptor.endswith(")"):
            continue
        key_expression = private_descriptor[4:-1]
        if not key_expression.endswith(f"/{branch}/*"):
            continue
        derived = node.deriveaddresses(item["desc"], [index, index])[0]
        if derived == address:
            return key_expression, index

    raise RuntimeError("Could not match the CLTV key to a private wallet descriptor.")


def mine_funds_if_needed(wallet, amount: Decimal) -> str:
    address = wallet.getnewaddress("regtest-mining", "legacy")
    trusted = wallet.getbalances()["mine"]["trusted"]
    if trusted < amount + Decimal("0.0001"):
        wallet.generatetoaddress(101, address)
    return address


def fund_output(lock_height: int | None, amount: Decimal, state_file: Path) -> dict:
    node = BitcoinRPC()
    info = assert_regtest(node)
    wallet = ensure_wallet()
    mining_address = mine_funds_if_needed(wallet, amount)
    current_height = wallet.getblockcount()
    if lock_height is None:
        lock_height = current_height + 6
    if lock_height <= current_height + 1:
        raise ValueError(
            f"Lock height {lock_height} must be at least two blocks above current height {current_height}."
        )

    key_address = wallet.getnewaddress("cltv-key", "legacy")
    public_key = wallet.getaddressinfo(key_address)["pubkey"]
    key_expression, key_index = private_key_expression(wallet, node, key_address)
    private_descriptor = build_cltv_miniscript_descriptor_for_key(
        lock_height, key_expression
    )
    private_descriptor_info = node.getdescriptorinfo(private_descriptor)
    if not private_descriptor_info["issolvable"] or not private_descriptor_info["hasprivatekeys"]:
        raise RuntimeError("Bitcoin Core did not recognize a private, solvable CLTV descriptor.")

    public_descriptor_info = node.getdescriptorinfo(
        build_cltv_miniscript_descriptor(lock_height, public_key)
    )
    if not public_descriptor_info["issolvable"]:
        raise RuntimeError("Bitcoin Core did not recognize the CLTV descriptor as solvable.")
    descriptor = public_descriptor_info["descriptor"]
    import_descriptor = f"{private_descriptor}#{private_descriptor_info['checksum']}"
    witness_script = build_cltv_witness_script(lock_height, public_key)
    script_pubkey = p2wsh_script_pubkey(witness_script).hex()

    imported = wallet.importdescriptors(
        [
            {
                "desc": import_descriptor,
                "timestamp": "now",
                "range": [key_index, key_index],
            }
        ]
    )[0]
    if not imported["success"]:
        error = imported.get("error", {})
        raise RuntimeError("Bitcoin Core could not import the private CLTV descriptor: " + error.get("message", "unknown error"))
    address = node.deriveaddresses(descriptor)[0]
    private_address = node.deriveaddresses(import_descriptor, [key_index, key_index])[0]
    if private_address != address:
        raise RuntimeError("Private and public CLTV descriptors derive different addresses.")
    address_info = wallet.getaddressinfo(address)
    if address_info["scriptPubKey"] != script_pubkey:
        raise RuntimeError("Descriptor address does not match the generated P2WSH witness script.")

    raw = wallet.createrawtransaction([], {address: float(amount)})
    funded = wallet.fundrawtransaction(raw, {"fee_rate": 2})
    signed = wallet.signrawtransactionwithwallet(funded["hex"])
    if not signed["complete"]:
        raise RuntimeError("Bitcoin Core could not completely sign the funding transaction.")
    decoded_tx = wallet.decoderawtransaction(signed["hex"])
    txid = wallet.sendrawtransaction(signed["hex"])
    if txid != decoded_tx["txid"]:
        raise RuntimeError("Bitcoin Core returned a funding txid that differs from the signed transaction.")
    wallet.generatetoaddress(1, mining_address)
    matching_outputs = [
        item for item in decoded_tx["vout"] if item["scriptPubKey"]["hex"] == script_pubkey
    ]
    if len(matching_outputs) != 1:
        raise RuntimeError("Could not uniquely identify the funded CLTV output.")

    state = {
        "network": info["chain"],
        "output_type": "p2wsh-miniscript",
        "lock_height": lock_height,
        "funding_txid": txid,
        "vout": matching_outputs[0]["n"],
        "amount_btc": str(matching_outputs[0]["value"]),
        "address": address,
        "descriptor": descriptor,
        "witness_script": witness_script.hex(),
        "script_pubkey": script_pubkey,
        "public_key": public_key,
    }
    state_file = state_file.expanduser().resolve()
    state_file.parent.mkdir(parents=True, exist_ok=True)
    temporary = state_file.with_suffix(state_file.suffix + ".tmp")
    temporary.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    temporary.replace(state_file)
    return state


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--height", type=int, help="Lock height; defaults to current height + 6")
    parser.add_argument("--amount", type=Decimal, default=Decimal("0.001"), help="BTC to lock")
    parser.add_argument("--state-file", type=Path, default=DEFAULT_STATE)
    args = parser.parse_args()
    if args.amount <= 0:
        parser.error("--amount must be greater than zero")
    state = fund_output(args.height, args.amount, args.state_file)
    state["state_file"] = str(args.state_file.expanduser().resolve())
    print(json.dumps(state, indent=2))


if __name__ == "__main__":
    main()