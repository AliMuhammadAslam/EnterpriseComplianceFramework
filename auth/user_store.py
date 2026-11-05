import os
import json
import secrets
from typing import Optional, Dict, Any
from werkzeug.security import generate_password_hash, check_password_hash
from utils.logger import logger_instance


class UserStore:
    """File-backed store of application user accounts with hashed passwords.

    Accounts are fixed (no public registration). The three default accounts
    map to the user_id keys the app already stores documents and reports
    under, so existing data stays accessible after login.
    """

    # Passwords are generated per install, not stored here. A password kept in
    # the source would be published with it and would be the same everywhere.
    DEFAULT_ACCOUNTS = [
        {"username": "john", "user_id": "default",
         "name": "John Smith", "role": "Default User"},
        {"username": "sarah", "user_id": "analyst",
         "name": "Sarah Johnson", "role": "Analyst"},
        {"username": "michael", "user_id": "auditor",
         "name": "Michael Chen", "role": "Auditor"},
        {"username": "emily", "user_id": "admin",
         "name": "Emily Davis", "role": "Compliance Officer"},
    ]

    def __init__(self, store_path: str = None):
        self.store_path = store_path or os.getenv("USERS_FILE", "./users.json")
        self.logger = logger_instance.get_logger("user_store")
        self.users: Dict[str, Dict[str, Any]] = {}
        self._load_or_seed()

    def _load_or_seed(self):
        """Load accounts from disk, seeding the default set on first run only.

        An unreadable file stops start-up. Reseeding it used to overwrite
        every account with a new password, so a truncated write locked all
        users out and destroyed the only copy of the hashes.
        """
        if not os.path.exists(self.store_path):
            self._seed_defaults()
            return
        try:
            with open(self.store_path, "r", encoding="utf-8") as f:
                self.users = json.load(f)
        except Exception as e:
            self.logger.error(f"Failed to load users file: {e}")
            raise RuntimeError(
                f"The user accounts file {self.store_path} could not be read ({e}). "
                "It has not been changed. Restore it from a backup, or delete it "
                "to issue a new set of passwords."
            ) from e
        self.logger.info(f"Loaded {len(self.users)} user account(s)")

    def _seed_defaults(self):
        """Create the fixed accounts with a fresh random password each.

        The passwords are shown on stdout once and never written anywhere in
        plain text, so they are not recoverable from the repository or the
        log file. Delete users.json to reseed if they are lost.
        """
        self.users = {}
        issued = []
        for acct in self.DEFAULT_ACCOUNTS:
            password = secrets.token_urlsafe(12)
            self.users[acct["username"]] = {
                "user_id": acct["user_id"],
                "name": acct["name"],
                "role": acct["role"],
                "password_hash": generate_password_hash(password),
            }
            issued.append((acct["username"], password))
        self._save()

        print("\n" + "=" * 62)
        print("First run: account passwords generated. Record them now.")
        print("They are not stored in plain text and will not be shown again.")
        print("=" * 62)
        for username, password in issued:
            print(f"  {username:10s} {password}")
        print("=" * 62 + "\n")

        # Deliberately not logged: the log file would become a credential store.
        self.logger.info(
            f"Seeded {len(self.users)} account(s) with generated passwords"
        )

    def _save(self):
        # Write to a temporary file and swap it in, so an interrupted write
        # cannot leave a truncated accounts file behind.
        tmp_path = f"{self.store_path}.tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self.users, f, indent=2)
            os.replace(tmp_path, self.store_path)
        except Exception as e:
            self.logger.error(f"Failed to save users file: {e}")

    def verify(self, username: str, password: str) -> Optional[Dict[str, Any]]:
        """Return the user's public profile if credentials are valid, else None."""
        key = (username or "").strip().lower()
        record = self.users.get(key)
        if not record:
            return None
        if not check_password_hash(record.get("password_hash", ""), password or ""):
            return None
        return {
            "username": key,
            "user_id": record["user_id"],
            "name": record["name"],
            "role": record["role"],
        }
