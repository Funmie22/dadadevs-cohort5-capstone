#!/usr/bin/env python3
"""Unit checks and a full Bitcoin Core regtest CLTV proof-of-concept test."""

import json
import tempfile
import unittest
from pathlib import Path
from decimal import Decimal

from bitcoin.cltv import (
    OP_CHECKLOCKTIMEVERIFY,
    OP_VERIFY,
    build_cltv_miniscript_descriptor,
    build_cltv_witness_script,
    p2wsh_script_pubkey,
)
from bitcoin.fund_cltv import fund_output
from bitcoin.rpc import BitcoinRPC, assert_regtest, ensure_wallet
from bitcoin.spend_cltv import assert_expected_timelock_rejection, json_default, spend_after_unlock


class TestCLTVScript(unittest.TestCase):
    def test_miniscript_policy_and_witness_script_encode_height_lock_and_key(self):
        public_key = "02" + "11" * 32
        descriptor = build_cltv_miniscript_descriptor(500, public_key)
        script = build_cltv_witness_script(500, public_key)
        self.assertEqual(descriptor, f"wsh(and_v(v:after(500),pk({public_key})))")
        self.assertIn(bytes([OP_CHECKLOCKTIMEVERIFY]), script)
        self.assertIn(bytes([OP_VERIFY]), script)
        self.assertTrue(script.endswith(bytes.fromhex("ac")))
        self.assertTrue(script.startswith(bytes.fromhex("02f401b169")))
        self.assertEqual(p2wsh_script_pubkey(script)[:2], b"\x00\x20")

    def test_rejects_timestamp_range(self):
        with self.assertRaises(ValueError):
            build_cltv_miniscript_descriptor(500_000_000, "02" + "11" * 32)


class TestSpendJsonSerialization(unittest.TestCase):
    def test_decimal_btc_values_serialize_as_strings(self):
        result = json.dumps(
            {"value": Decimal("0.00099000")},
            default=json_default,
        )
        self.assertEqual(json.loads(result)["value"], "0.00099000")


class TestCLTVRegtest(unittest.TestCase):
    def test_fund_reject_then_unlock_and_spend(self):
        node = BitcoinRPC()
        info = assert_regtest(node)
        self.assertEqual(info["chain"], "regtest")
        wallet = ensure_wallet()
        if wallet.getbalances()["mine"]["trusted"] < Decimal("0.0011"):
            wallet.generatetoaddress(101, wallet.getnewaddress("regtest-mining", "legacy"))
        current_height = wallet.getblockcount()
        lock_height = current_height + 5

        with tempfile.TemporaryDirectory(prefix="sats-in-a-bottle-") as temp_dir:
            state_file = Path(temp_dir) / "cltv-state.json"
            funded = fund_output(lock_height, Decimal("0.001"), state_file)
            self.assertTrue(funded["funding_txid"])
            self.assertGreaterEqual(funded["vout"], 0)
            self.assertTrue(state_file.is_file())
            failure_reason = assert_expected_timelock_rejection(wallet, funded)
            successful_spend = spend_after_unlock(wallet, funded)
            self.assertTrue(successful_spend["txid"])
            self.assertGreaterEqual(successful_spend["confirmations"], 1)
            self.assertTrue(successful_spend["outputs"])

        print(
            json.dumps(
                {
                    "unlock_height": lock_height,
                    "funding_txid": funded["funding_txid"],
                    "pre_unlock_rejection": failure_reason,
                    "post_unlock_spend": successful_spend,
                },
                indent=2,
                default=json_default,
            )
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)