"""Print a fresh AES-256 key for ENCRYPTION_KEY.

    python -m backend.cli.generate_encryption_key

Store the output in `.env` as ENCRYPTION_KEY, keep it off the same volume as the
database backups it protects, and never lose it: once content is sealed, the key
is the only way to read it back.
"""

from backend.core.crypto import generate_key


def main() -> None:
    print(generate_key())


if __name__ == "__main__":
    main()
