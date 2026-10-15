"""
google_drive_user_client.py
===========================

OAuth2 client for the Google Drive API v3 (user-account auth).

Files created through this client belong to the authenticated user, not the
service account.  The first run triggers a browser-based consent flow; the
resulting token is cached in ``token.json`` and reused on subsequent runs.

    from google_drive_user_client import GoogleDriveUserClient

    with GoogleDriveUserClient() as user:
        print(f"Logged in as {user.user_email}")
        doc = user.create_document("My Report", parent_folder_id="...")
        sheet = user.create_spreadsheet("Data", parent_folder_id="...")
        files = user.list_files(query="'<folder_id>' in parents")
        user.delete_file(doc["id"])

Dependencies (besides the ones from google_drive_client.py):
    google-auth-oauthlib
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Sequence

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

# Reuse all CRUD methods from the base Drive client.
from google_drive_client import (
    GoogleDriveClient,
    GoogleDriveError,
)
from googleapiclient.discovery import build

__all__ = [
    "GoogleDriveUserClient",
    "AuthError",
]

# Drive scope covers everything: files, Docs, Sheets, folders.
DEFAULT_SCOPES: tuple[str, ...] = (
    "https://www.googleapis.com/auth/drive",
)


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #
class AuthError(GoogleDriveError):
    """Authentication / token-related error."""


_ACCESS_DENIED_HINT = (
    "Google returned 'access_denied'. The OAuth app is still in Testing mode, "
    "so only users listed as Test users may authorize it.\n"
    "\n"
    "Fix (takes 1 minute):\n"
    "  1) Open https://console.cloud.google.com/apis/credentials/consent\n"
    "  2) If 'Audience' says 'Internal' → change to 'External', then Save\n"
    "  3) Scroll to 'Test users' → Add users → add the Google account you sign in with\n"
    "     (e.g. your@gmail.com)\n"
    "  4) Save, then retry the command.\n"
    "\n"
    "Note: the scope 'drive' is restricted. A published app requires verification "
    "(privacy policy, domain ownership), but in Testing mode it works for Test users.\n"
)


# --------------------------------------------------------------------------- #
# Client
# --------------------------------------------------------------------------- #
class GoogleDriveUserClient(GoogleDriveClient):
    """Drive API client authenticated as a human user via OAuth2.

    Args:
        client_secret_path:
            Path to the OAuth2 ``client_secret_*.json`` file.
            Defaults to ``GOOGLE_OAUTH_CLIENT_SECRET`` env var, then to the
            first ``client_secret_*.json`` file found next to this module.
        token_path:
            Path where the cached access token is stored.
            Defaults to ``token.json`` next to this module.
        scopes: API scopes; defaults to :data:`DEFAULT_SCOPES`.
    """

    # ---- lifecycle ------------------------------------------------------- #
    def __init__(
        self,
        client_secret_path: str | os.PathLike[str] | None = None,
        token_path: str | os.PathLike[str] | None = None,
        *,
        scopes: Sequence[str] = DEFAULT_SCOPES,
    ) -> None:
        # НЕ вызываем super().__init__(): базовый GoogleDriveClient при
        # инициализации ищет service-account JSON, который OAuth2-клиенту
        # не нужен. Инициализируем нужные атрибуты напрямую.
        self._credentials: Credentials | None = None
        self._service: Any = None

        self._client_secret_path = self._resolve_client_secret_path(client_secret_path)
        self._token_path = (
            Path(token_path).expanduser().resolve()
            if token_path
            else Path(__file__).resolve().parent / "token.json"
        )
        self._scopes = tuple(scopes)
        self._credentials: Credentials | None = None
        self._service: Any = None

    @staticmethod
    def _resolve_client_secret_path(
        client_secret_path: str | os.PathLike[str] | None,
    ) -> Path:
        if client_secret_path:
            path = Path(client_secret_path).expanduser().resolve()
        else:
            env = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET")
            if env:
                path = Path(env).expanduser().resolve()
            else:
                candidates = sorted(
                    p
                    for p in Path(__file__).resolve().parent.glob("client_secret_*.json")
                )
                if not candidates:
                    raise AuthError(
                        "OAuth2 client_secret not found: pass client_secret_path "
                        "explicitly, set GOOGLE_OAUTH_CLIENT_SECRET, or place a "
                        "client_secret_*.json file next to this module."
                    )
                path = candidates[0]
        if not path.is_file():
            raise AuthError(f"Client secret file not found: {path}")
        return path

    # ---- credentials / token management ---------------------------------- #
    @property
    def credentials(self) -> Credentials:
        if self._credentials is None or not self._credentials.valid:
            self._credentials = self._refresh_or_run_flow()
        return self._credentials

    def _refresh_or_run_flow(self) -> Credentials:
        """Load cached token, refresh if expired, or run the OAuth consent flow."""
        # 1) Try loading a cached token.
        if self._token_path.is_file():
            try:
                creds = Credentials.from_authorized_user_file(
                    str(self._token_path), scopes=list(self._scopes)
                )
                if creds.valid:
                    return creds
                if creds.expired and creds.refresh_token:
                    # Try to refresh (requires google.auth.transport.requests).
                    try:
                        from google.auth.transport.requests import Request

                        creds.refresh(Request())
                        self._save_token(creds)
                        return creds
                    except Exception:  # noqa: BLE001
                        pass  # Token refresh failed — fall through to flow.
            except Exception:  # noqa: BLE001
                pass  # Corrupted token — fall through to flow.

        # 2) Run the installed-app flow (browser consent).
        return self._run_flow()

    def _run_flow(self, *, open_browser: bool = True) -> Credentials:
        """Launch the OAuth2 consent flow via a temporary local web server.

        ``run_local_server`` spins up a listener on a free localhost port and
        waits for Google to redirect the consent result back to it. Any port of
        ``http://localhost`` is accepted by Google for installed-app clients, so
        the registered ``http://localhost`` redirect URI does not have to match.
        """
        flow = InstalledAppFlow.from_client_secrets_file(
            str(self._client_secret_path),
            scopes=list(self._scopes),
        )
        try:
            creds = flow.run_local_server(
                host="localhost",
                port=0,  # let the OS pick a free port
                open_browser=open_browser,
            )
        except Exception as exc:  # noqa: BLE001 - browser/OS integration failure
            text = str(exc).lower()
            if "access_denied" in text or "access denied" in text:
                raise AuthError(_ACCESS_DENIED_HINT) from exc
            if open_browser:
                # Browser failed to launch - retry without it and show the URL.
                print(f"! Could not open the browser automatically ({exc}).")
                return self._run_flow(open_browser=False)
            raise AuthError(f"OAuth2 flow failed: {exc}") from exc

        self._save_token(creds)
        return creds

    def reauth(self) -> Credentials:
        """Force a fresh OAuth2 consent, discarding the cached token."""
        self._token_path.unlink(missing_ok=True)
        self._credentials = None
        self._service = None
        return self.credentials

    def _save_token(self, creds: Credentials) -> None:
        # creds.to_json() already returns a JSON string — write it as-is,
        # do NOT re-serialize it with json.dump (that would double-encode).
        self._token_path.parent.mkdir(parents=True, exist_ok=True)
        self._token_path.write_text(creds.to_json(), encoding="utf-8")

    @property
    def user_email(self) -> str:
        """Email address of the authenticated user."""
        return self._fetch_user_email()

    def _fetch_user_email(self) -> str:
        """Fetch the authenticated user's email from Drive 'about' endpoint.

        Note: the ``about`` resource does not accept dot-nested field
        selection (``user.emailAddress`` -> HTTP 400), so request ``user``.
        """
        try:
            response = self._execute(
                self.service.about().get(fields="user")
            )
            return response.get("user", {}).get("emailAddress", "unknown")
        except Exception:  # noqa: BLE001
            return "unknown"

    def get_user(self) -> dict[str, Any]:
        """Get Drive ``about`` info for the authenticated user."""
        return self._execute(
            self.service.about().get(
                fields="user,storageQuota,maxUploadSize",
            )
        )

    # ---- service --------------------------------------------------------- #
    @property
    def service(self) -> Any:
        """Lazily built google-api-python-client resource (user credentials)."""
        if self._service is None:
            self._service = build(  # noqa: F821
                "drive",
                "v3",
                credentials=self.credentials,
                cache_discovery=False,
            )
        return self._service

    # ---- convenience methods --------------------------------------------- #
    def create_document(
        self, title: str, parent_folder_id: str | None = None
    ) -> dict[str, Any]:
        """Create a new Google Docs file owned by the user.

        Args:
            title: Document name.
            parent_folder_id: Optional folder id.

        Returns:
            Dict with ``id``, ``name``, ``webViewLink``.
        """
        return super().create_document(title, parent_folder_id)

    def create_spreadsheet(
        self, title: str, parent_folder_id: str | None = None
    ) -> dict[str, Any]:
        """Create a new Google Sheets file owned by the user.

        Args:
            title: Spreadsheet name.
            parent_folder_id: Optional folder id.

        Returns:
            Dict with ``id``, ``name``, ``webViewLink``.
        """
        return super().create_spreadsheet(title, parent_folder_id)

    def create_folder(self, name: str, parent_folder_id: str | None = None) -> dict[str, Any]:
        """Create a new folder owned by the user.

        Args:
            name: Folder name.
            parent_folder_id: Optional parent folder id.

        Returns:
            Dict with ``id``, ``name``, ``webViewLink``.
        """
        return super().create_folder(name, parent_folder_id)

    def find_folder_id(self, name: str) -> str | None:
        """Resolve a folder id by its exact name.

        Returns ``None`` if no folder with that name is accessible.
        To address a folder by name instead of id, use this once and cache
        the result — ids never change, names do.
        """
        folders = self.list_files(
            query=f"name = '{name}'",
            mime_types=["application/vnd.google-apps.folder"],
        )
        return folders[0]["id"] if folders else None

    def list_folder_files(self, folder_id: str) -> list[dict[str, Any]]:
        """List all files inside a folder.

        Args:
            folder_id: Drive folder id.

        Returns:
            List of file metadata dicts.
        """
        return self.get_folder_files(folder_id)

    def clear_folder(self, folder_id: str, recursive: bool = True) -> int:
        """Delete all files inside a folder (optionally subfolders too).

        Args:
            folder_id: Folder id.
            recursive: If ``True``, also delete files in subfolders.

        Returns:
            Number of deleted files.
        """
        count = 0
        for child in self.get_folder_files(folder_id):
            child_id = child["id"]
            if child.get("mimeType") == "application/vnd.google-apps.folder":
                if recursive:
                    count += self.clear_folder(child_id, recursive=True)
                # Non-recursive: leave subfolders alone
            else:
                try:
                    self.delete_file(child_id)
                    count += 1
                except GoogleDriveError:
                    pass
        return count

    def move_to_folder(
        self, file_id: str, target_folder_id: str, remove_from_parent: str | None = None
    ) -> dict[str, Any]:
        """Move a file into a folder.

        Args:
            file_id: File to move.
            target_folder_id: Destination folder.
            remove_from_parent: If given, remove the specified parent folder first.

        Returns:
            Updated file metadata.
        """
        return self.move_file(
            file_id,
            parent_folder_id=target_folder_id,
            remove_parents=[remove_from_parent] if remove_from_parent else None,
        )

    def get_drive_root(self) -> list[dict[str, Any]]:
        """List files in the root folder."""
        return self.list_files(query="'root' in parents and trashed = false")


# --------------------------------------------------------------------------- #
# Entry point: interactive demo
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    CREDENTIALS_PATH = Path(__file__).with_name(
        os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "client_secret_desktop.json")
    )
    TOKEN_PATH = Path(__file__).with_name("token.json")

    # ---- FOLDER ID ----------------------------------------------------- #
    # Put the target folder id here. It is the long string after /folders/
    # in the folder URL:  https://drive.google.com/drive/folders/<THIS_PART>
    # Leave empty to create files in Drive root, or set FOLDER_NAME instead.
    FOLDER_ID = os.getenv("GOOGLE_FOLDER_ID", "")  # set your folder ID here
    FOLDER_NAME = os.getenv("GOOGLE_FOLDER_NAME", "")  # used only if FOLDER_ID is empty

    print("Google Drive User Client")
    print("=" * 50)
    print()
    print("OAuth2 credentials file:", CREDENTIALS_PATH)
    print("Token cache:", TOKEN_PATH)
    print()

    try:
        user = GoogleDriveUserClient(CREDENTIALS_PATH, TOKEN_PATH)
        email = user.user_email
        print(f"Authenticated as: {email}")
        print()
    except AuthError as error:
        raise SystemExit(f"\n! {error}")

    with user:
        # Resolve the folder id (by id, by name, or fall back to root).
        folder_id = FOLDER_ID or (user.find_folder_id(FOLDER_NAME) if FOLDER_NAME else None)
        if folder_id:
            print(f"Target folder id: {folder_id}")
            print(f"Folder contents : {len(user.list_folder_files(folder_id))} item(s)")
        else:
            print("Target folder   : Drive root (FOLDER_ID is empty)")
        print()

        # --- Show all files visible to user ---------------------------- #
        print("=" * 60)
        print("  Files in your Drive (last modified):")
        print("=" * 60)

        files = user.list_files(page_size=30)

        if not files:
            print("\nNo files found.\n")
        else:
            print(f"\n{'Name':<40} {'Type':<22} {'Modified':<20} {'Size':<10}\n")
            print("-" * 115)

            for f in files:
                name = (f.get("name") or "").ljust(40)[:40]
                mime = (f.get("mimeType") or "").replace(
                    "application/vnd.google-apps.", ""
                ).ljust(22)[:22]
                mod = str(f.get("modifiedTime", "") or "")[:19].ljust(20)
                size = f.get("size")
                if size is not None:
                    size = int(size)
                    if size < 1024:
                        size = f"{size} B"
                    elif size < 1024 * 1024:
                        size = f"{size / 1024:.1f} KB"
                    else:
                        size = f"{size / (1024 * 1024):.1f} MB"
                else:
                    size = "-"
                size = str(size).ljust(10)

                print(f"{name}  {mime}  {mod}  {size}")

            print("\n" + "-" * 115)
            print(f"Total files: {len(files)}\n")

        # --- Show root folder ------------------------------------------ #
        print("=" * 60)
        print("  Root folder:")
        print("=" * 60)

        root = user.get_drive_root()
        if not root:
            print("\nRoot folder is empty.\n")
        else:
            for f in root:
                name = f.get("name", "")
                mime = f.get("mimeType", "")
                fid = f.get("id", "")
                print(f"  [{mime}] {name}  →  {fid}")
            print()

        # --- Show user info -------------------------------------------- #
        print("=" * 60)
        print("  User info:")
        print("=" * 60)

        info = user.get_user()
        user_info = info.get("user", {})
        print(f"  Email  : {user_info.get('emailAddress', '?')}")
        print(f"  Display: {user_info.get('displayName', '?')}")
        quota = info.get("storageQuota", {})
        used = quota.get("usage", 0)
        if isinstance(used, (int, float)):
            if used < 1024 * 1024:
                used = f"{used / 1024:.0f} KB"
            elif used < 1024**3:
                used = f"{used / 1024**2:.0f} MB"
            else:
                used = f"{used / 1024**3:.1f} GB"
        print(f"  Storage: {used} / {quota.get('limit', '?')}")
        print()
