"""Build the P2WSH Miniscript policy and witness script for the CLTV demo."""

import hashlib


OP_CHECKLOCKTIMEVERIFY = 0xB1
OP_VERIFY = 0x69
OP_CHECKSIG = 0xAC


def _push_data(data: bytes) -> bytes:
    if len(data) <= 75:
        return bytes([len(data)]) + data
    if len(data) <= 255:
        return bytes([0x4C, len(data)]) + data
    raise ValueError("Script data push is too large.")


def _push_script_number(number: int) -> bytes:
    if number < 0:
        raise ValueError("CLTV block height must be non-negative.")
    if number == 0:
        return b"\x00"
    if number <= 16:
        return bytes([0x50 + number])
    encoded = bytearray()
    while number:
        encoded.append(number & 0xFF)
        number >>= 8
    if encoded[-1] & 0x80:
        encoded.append(0)
    return _push_data(bytes(encoded))


def _validate_lock_height(lock_height: int) -> None:
    if not 1 <= lock_height < 500_000_000:
        raise ValueError("Use a future block height from 1 to 499,999,999 (not a timestamp).")


def _public_key_bytes(public_key_hex: str) -> bytes:
    try:
        public_key = bytes.fromhex(public_key_hex)
    except ValueError as error:
        raise ValueError("Public key must be hexadecimal.") from error
    if len(public_key) != 33 or public_key[0] not in (2, 3):
        raise ValueError("P2WSH requires a 33-byte compressed secp256k1 public key.")
    return public_key


def build_cltv_miniscript_descriptor(lock_height: int, public_key_hex: str) -> str:
    _validate_lock_height(lock_height)
    public_key = _public_key_bytes(public_key_hex)
    return build_cltv_miniscript_descriptor_for_key(lock_height, public_key.hex())


def build_cltv_miniscript_descriptor_for_key(lock_height: int, key_expression: str) -> str:
    _validate_lock_height(lock_height)
    if not key_expression or any(character.isspace() for character in key_expression):
        raise ValueError("Miniscript key expression must be non-empty and contain no whitespace.")
    return f"wsh(and_v(v:after({lock_height}),pk({key_expression})))"


def build_cltv_witness_script(lock_height: int, public_key_hex: str) -> bytes:
    _validate_lock_height(lock_height)
    public_key = _public_key_bytes(public_key_hex)
    return (
        _push_script_number(lock_height)
        + bytes([OP_CHECKLOCKTIMEVERIFY, OP_VERIFY])
        + _push_data(public_key)
        + bytes([OP_CHECKSIG])
    )


def p2wsh_script_pubkey(witness_script: bytes) -> bytes:
    return b"\x00\x20" + hashlib.sha256(witness_script).digest()