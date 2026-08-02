import argparse
import asyncio
import getpass
from datetime import timedelta

from backend.database.session import AsyncSessionLocal
from backend.services.auth_service import AuthService


# Read and confirm a password without echoing it into terminal history.
def _read_password(confirm: bool = True) -> str:
    password = getpass.getpass("Password: ")
    if confirm and password != getpass.getpass("Confirm password: "):
        raise ValueError("passwords do not match")
    return password


# Apply one non-destructive invite-account administration command.
async def _run_command(args: argparse.Namespace) -> None:
    async with AsyncSessionLocal() as session:
        service = AuthService(session)
        if args.command == "create":
            await service.create_account(
                args.user,
                _read_password(),
                username=args.username,
            )
            print(
                f"Created active AniOS account: {args.username or args.user} "
                f"owns {args.user}"
            )
        elif args.command == "set-password":
            await service.set_password(args.user, _read_password())
            print(f"Updated password and revoked sessions: {args.user}")
        elif args.command == "enable":
            await service.set_active(args.user, True)
            print(f"Enabled AniOS account: {args.user}")
        elif args.command == "disable":
            await service.set_active(args.user, False)
            print(f"Disabled AniOS account and revoked sessions: {args.user}")
        elif args.command == "create-invite":
            invite = await service.create_registration_invite(
                timedelta(hours=args.ttl_hours)
            )
            print("Registration invite (shown once):")
            print(invite.token)
            print(f"Expires at: {invite.expires_at.isoformat()}")


# Parse account administration and one-time invitation commands.
def main() -> None:
    parser = argparse.ArgumentParser(description="Manage invited AniOS accounts")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("create", "set-password", "enable", "disable"):
        command_parser = subparsers.add_parser(command)
        command_parser.add_argument("--user", required=True)
        if command == "create":
            command_parser.add_argument(
                "--username",
                help="Login name; defaults to the stable owned user ID",
            )
    invite_parser = subparsers.add_parser("create-invite")
    invite_parser.add_argument(
        "--ttl-hours",
        type=int,
        default=24,
        choices=range(1, 169),
        metavar="1-168",
        help="Hours before the unused invitation expires (default: 24)",
    )
    args = parser.parse_args()
    try:
        asyncio.run(_run_command(args))
    except ValueError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
