"""Custom SQLAlchemy column types.

``EncryptedText`` transparently seals a text column at the persistence boundary:
values are encrypted on the way to the database and opened on the way back, so
no repository or ``to_dict`` code changes. When encryption is disabled the type
is an ordinary ``Text`` column - the cipher passes values through untouched.

Apply it only to free-text content retrieved by primary key or vector search.
Never apply it to a column used in a ``WHERE`` equality, a unique constraint, or
deduplication: each value is sealed with a fresh nonce, so equal plaintext does
not produce equal ciphertext.
"""

from typing import Any

from sqlalchemy import Text
from sqlalchemy.engine.interfaces import Dialect
from sqlalchemy.types import TypeDecorator

from backend.core.crypto import get_field_cipher


class EncryptedText(TypeDecorator[str]):
    impl = Text
    # The sealed representation depends only on the value, not on any bind
    # parameter, so SQLAlchemy may cache the compiled statement.
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect: Dialect) -> str | None:
        if value is None:
            return None
        return get_field_cipher().encrypt(value)

    def process_result_value(self, value: Any, dialect: Dialect) -> str | None:
        if value is None:
            return None
        return get_field_cipher().decrypt(str(value))
