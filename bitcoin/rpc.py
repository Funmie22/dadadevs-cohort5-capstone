"""Small Bitcoin Core JSON-RPC client using cookie authentication by default."""

from __future__ import annotations

import base64
import json
import os
from decimal import Decimal
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


class RPCError(RuntimeError):
    def __init__(self, code: int | None, message: str):
        super().__init__(f"Bitcoin Core RPC error {code}: {message}")
        self.code = code
        self.message = message


class BitcoinRPC:
    def __init__(self, wallet: str | None = None):
        self.url = os.environ.get("BITCOIN_RPC_URL", "http://127.0.0.1:18443").rstrip("/")
        self.wallet = wallet
        self.datadir = Path(os.environ.get("BITCOIN_DATADIR", "~/.bitcoin")).expanduser()
        self.request_id = 0
        self.authorization = self._authorization()

    def _authorization(self) -> str:
        username = os.environ.get("BITCOIN_RPC_USER")
        password = os.environ.get("BITCOIN_RPC_PASSWORD")
        if username is not None or password is not None:
            if username is None or password is None:
                raise RuntimeError("Set both BITCOIN_RPC_USER and BITCOIN_RPC_PASSWORD.")
            credentials = f"{username}:{password}"
        else:
            cookie_path = self.datadir / "regtest" / ".cookie"
            try:
                credentials = cookie_path.read_text(encoding="utf-8").strip()
            except OSError as error:
                raise RuntimeError(
                    f"Cannot read RPC cookie at {cookie_path}; start Bitcoin Core in regtest first."
                ) from error
        token = base64.b64encode(credentials.encode("utf-8")).decode("ascii")
        return f"Basic {token}"

    def call(self, method: str, *params):
        self.request_id += 1
        url = self.url
        if self.wallet is not None:
            url += "/wallet/" + quote(self.wallet, safe="")
        payload = json.dumps(
            {"jsonrpc": "1.0", "id": self.request_id, "method": method, "params": params}
        ).encode("utf-8")
        request = Request(
            url,
            data=payload,
            headers={"Authorization": self.authorization, "Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=30) as response:
                result = json.loads(response.read(), parse_float=Decimal)
        except HTTPError as error:
            body = error.read()
            try:
                result = json.loads(body, parse_float=Decimal)
            except json.JSONDecodeError:
                raise RPCError(error.code, body.decode("utf-8", errors="replace")) from error
        except URLError as error:
            raise RuntimeError(f"Cannot reach Bitcoin Core RPC at {url}: {error.reason}") from error
        if result.get("error") is not None:
            error = result["error"]
            raise RPCError(error.get("code"), error.get("message", "Unknown RPC error"))
        return result["result"]

    def __getattr__(self, method: str):
        return lambda *params: self.call(method, *params)


def assert_regtest(rpc: BitcoinRPC) -> dict:
    info = rpc.getblockchaininfo()
    if info.get("chain") != "regtest":
        raise RuntimeError(
            f"Refusing to continue: Bitcoin Core reports chain={info.get('chain')!r}, not 'regtest'."
        )
    return info


def ensure_wallet(name: str = "sats-in-a-bottle") -> BitcoinRPC:
    node = BitcoinRPC()
    assert_regtest(node)

    loaded = node.listwallets()

    if name not in loaded:
        existing = {item["name"] for item in node.listwalletdir()["wallets"]}

        if name in existing:
            node.loadwallet(name)
        else:
            # Core 31.1 positional args: disable_private_keys=False, descriptors=True.
            node.createwallet(name, False, False, "", False, True)

    wallet = BitcoinRPC(wallet=name)
    info = wallet.getwalletinfo()
    if not info.get("descriptors", False):
        raise RuntimeError(
            f"Wallet {name!r} is not descriptor-based; it was left unchanged."
        )
    if not info.get("private_keys_enabled", False):
        raise RuntimeError(
            f"Wallet {name!r} has private keys disabled; it was left unchanged. "
            "Create a separate descriptor wallet with private keys enabled and migrate explicitly."
        )
    return wallet