"""Administración desde el servidor, para lo que la API no permite a ningún usuario.

    docker compose exec api python -m norte_legal.cli add-member \\
        --organization default --email ana@example.com --role owner

Sirve para dar dueño a las organizaciones que vienen de antes de las cuentas (`default`, `eval-*`,
creadas por la migración 0004). El usuario tiene que haberse registrado antes.
"""

import argparse
import sys

from norte_legal.db.accounts import AccountRepository
from norte_legal.db.models import Organization
from norte_legal.db.session import new_session


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="norte_legal.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    add = commands.add_parser("add-member", help="añade un usuario registrado a una organización")
    add.add_argument("--organization", required=True, help="id de la organización (su tenant)")
    add.add_argument("--email", required=True)
    add.add_argument("--role", choices=["owner", "member"], default="member")
    args = parser.parse_args(argv)

    with new_session() as session, session.begin():
        accounts = AccountRepository(session)
        if session.get(Organization, args.organization) is None:
            print(f"organization not found: {args.organization}", file=sys.stderr)
            return 1
        user = accounts.active_user_by_email(args.email.strip().lower())
        if user is None:
            print(f"user not found: {args.email}", file=sys.stderr)
            return 1
        if not accounts.add_membership(user.id, args.organization, args.role):
            print("already a member", file=sys.stderr)
            return 1
    print(f"added {args.email} to {args.organization} as {args.role}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
