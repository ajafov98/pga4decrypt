##########################################################################
#
# pgAdmin 4 - PostgreSQL Tools
#
# Copyright (C) 2013 - 2026, The pgAdmin Development Team
# This software is released under the PostgreSQL Licence
#
##########################################################################

"""This File Provides Cryptography.

The on-disk format changed over pgAdmin releases:

  legacy  (<= 6.x):  base64(iv + ciphertext)
  modern  (>= 7.0):  hex(base64(iv + ciphertext))

Both are accepted here.
"""

import base64
import re

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers import Cipher
from cryptography.hazmat.primitives.ciphers.algorithms import AES

try:  # cryptography >= 43
    from cryptography.hazmat.decrepit.ciphers.modes import CFB8
except ImportError:  # pragma: no cover - older cryptography
    from cryptography.hazmat.primitives.ciphers.modes import CFB8

padding_string = b'}'
iv_size = AES.block_size // 8

MASTERPASS_CHECK_TEXT = 'ideas are bulletproof'

_BASE64_RE = re.compile(rb'^[A-Za-z0-9+/]*={0,2}$')


def encrypt(plaintext, key):
    """Encrypt plaintext with AES-CFB8 (same scheme as pgAdmin)."""
    import os

    iv = os.urandom(iv_size)
    cipher = Cipher(AES(pad(key)), CFB8(iv), default_backend())
    encryptor = cipher.encryptor()

    if isinstance(plaintext, str):
        plaintext = plaintext.encode()

    return base64.b64encode(iv + encryptor.update(plaintext) +
                            encryptor.finalize())


def _looks_like_base64(data):
    return bool(data) and len(data) % 4 == 0 and _BASE64_RE.match(data)


def decode_ciphertext(value):
    """Undo pgAdmin's storage encoding and return raw IV + ciphertext."""
    if isinstance(value, str):
        raw = value.encode('ascii')
    else:
        raw = bytes(value)

    # Modern format: hex of the base64 text.
    try:
        unhexed = bytes.fromhex(raw.decode('ascii'))
    except (ValueError, UnicodeDecodeError):
        unhexed = None

    if unhexed is not None and _looks_like_base64(unhexed):
        raw = unhexed

    return base64.b64decode(raw, validate=False)


def storage_format(value):
    """Return 'hex' or 'base64' for a value read from the config DB."""
    if isinstance(value, str):
        raw = value.encode('ascii')
    else:
        raw = bytes(value)
    try:
        unhexed = bytes.fromhex(raw.decode('ascii'))
    except (ValueError, UnicodeDecodeError):
        return 'base64'
    return 'hex' if _looks_like_base64(unhexed) else 'base64'


def decrypt(ciphertext, key):
    """Decrypt an AES encrypted string."""
    ciphertext = decode_ciphertext(ciphertext)
    iv = ciphertext[:iv_size]

    cipher = Cipher(AES(pad(key)), CFB8(iv), default_backend())
    decryptor = cipher.decryptor()
    return decryptor.update(ciphertext[iv_size:]) + decryptor.finalize()


def pad(key):
    """Add padding to the key."""

    if isinstance(key, str):
        key = key.encode()

    key = key[:32]

    if len(key) in (16, 24, 32):
        return key

    return key.ljust(32, padding_string)


def validate_key(key, masterpass_check):
    """Return True if key decrypts pgAdmin's master-password check text."""
    if key is None or masterpass_check is None:
        return False
    try:
        return decrypt(masterpass_check, key).decode('utf-8') == \
            MASTERPASS_CHECK_TEXT
    except Exception:
        return False
