import argparse

from backend.core.auth import issue_user_token


def main() -> None:
    parser = argparse.ArgumentParser(description="Issue a local AniOS user token")
    parser.add_argument("--user", required=True, help="User ID bound to the token")
    parser.add_argument("--ttl-seconds", type=int, default=3_600)
    args = parser.parse_args()
    if not 1 <= len(args.user) <= 50:
        parser.error("--user must contain 1 to 50 characters")
    if args.ttl_seconds <= 0:
        parser.error("--ttl-seconds must be positive")
    print(issue_user_token(args.user, args.ttl_seconds))


if __name__ == "__main__":
    main()
