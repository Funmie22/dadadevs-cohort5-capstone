#!/usr/bin/env python3
"""Construct and display the Core-solvable P2WSH CLTV Miniscript descriptor."""

import argparse
import json

from bitcoin.cltv import build_cltv_miniscript_descriptor, build_cltv_witness_script
from bitcoin.rpc import BitcoinRPC, assert_regtest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--height", type=int, required=True, help="Required future block height")
    parser.add_argument("--pubkey", required=True, help="Wallet public key in hexadecimal")
    args = parser.parse_args()

    rpc = BitcoinRPC()
    assert_regtest(rpc)
    descriptor = rpc.getdescriptorinfo(
        build_cltv_miniscript_descriptor(args.height, args.pubkey)
    )
    address = rpc.deriveaddresses(descriptor["descriptor"])[0]
    print(
        json.dumps(
            {
                "lock_height": args.height,
                "descriptor": descriptor["descriptor"],
                "address": address,
                "witness_script": build_cltv_witness_script(args.height, args.pubkey).hex(),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()