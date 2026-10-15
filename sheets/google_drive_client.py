"""
google_drive_client.py
======================

Reusable OOP client for the Google Drive API v3 (service-account auth).

The module is self-contained: copy it into any other project and use it as

    from google_drive_client import GoogleDriveClient

    with GoogleDriveClient("service_account.json") as drive:
        files = drive.list_files()
        meta = drive.get_file_metadata("file_id_here")
        drive.create_file("report.txt", b"Hello, Drive!", "text/plain")
        drive.delete_file("file_id_here")

Only dependencies: google-api-python-client, google-auth.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

__all__ = [
    "GoogleDriveClient",
    "GoogleDriveError",
    "FileNotFound",
]

# Drive scope: full read/write access to Drive files visible to the service account.
DEFAULT_SCOPES: tuple[str, ...] = (
    "https://www.googleapis.com/auth/drive",
)

_RETRYABLE_STATUS: frozenset[int] = frozenset({429, 500, 502, 503, 504})

# Google-native files cannot be downloaded with get_media(), they must be
# exported. The first entry of each tuple is used as the default export format.
GOOGLE_EXPORT_FORMATS: dict[str, tuple[str, ...]] = {
    "application/vnd.google-apps.document": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/pdf",
        "text/plain",
    ),
    "application/vnd.google-apps.spreadsheet": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "text/csv",
    ),
    "application/vnd.google-apps.presentation": (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/pdf",
    ),
    "application/vnd.google-apps.drawing": ("image/png", "image/svg+xml"),
}


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #
class GoogleDriveError(RuntimeError):
    """Any error returned by the Drive API or raised by this client."""


class FileNotFound(GoogleDriveError):
    """File id is wrong, or the file is not shared with the service account."""


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _mime_guess(name: str) -> str:
    """Best-effort MIME type inference from file extension."""
    suffix = Path(name).suffix.lower()
    if not suffix:
        return "application/octet-stream"
    mapping: Mapping[str, str] = {
        ".txt": "text/plain",
        ".csv": "text/csv",
        ".json": "application/json",
        ".html": "text/html",
        ".htm": "text/html",
        ".xml": "application/xml",
        ".md": "text/markdown",
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".svg": "image/svg+xml",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xls": "application/vnd.ms-excel",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".doc": "application/msword",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    }
    return mapping.get(suffix, "application/octet-stream")


def _to_bytes(content: bytes | str) -> bytes:
    return content if isinstance(content, bytes) else content.encode("utf-8")


def _describe_http_error(exc: HttpError) -> str:
    """Short, human-readable message out of a raw HttpError payload."""
    reason = ""
    try:
        payload = json.loads(exc.content.decode("utf-8"))
        reason = payload.get("error", {}).get("message", "")
    except Exception:  # noqa: BLE001
        reason = str(exc)
    status = getattr(exc.resp, "status", None)
    hints: Mapping[int, str] = {
        403: (
            " Check sharing settings and that the Drive API is enabled "
            "in the Google Cloud Console."
        ),
        404: (
            " Check the file/folder id and sharing settings."
        ),
    }
    return f"Google Drive API error {status}: {reason}{hints.get(status, '')}"


# --------------------------------------------------------------------------- #
# Client
# --------------------------------------------------------------------------- #
class GoogleDriveClient:
    """CRUD facade over the Google Drive API v3.

    Args:
        credentials_path:
            Path to the service-account JSON key. Defaults to
            ``GOOGLE_APPLICATION_CREDENTIALS`` env var, then to the first
            ``*.json`` key found next to this module.
        scopes: API scopes; defaults to :data:`DEFAULT_SCOPES`.
    """

    # ---- lifecycle ------------------------------------------------------- #
    def __init__(
        self,
        credentials_path: str | os.PathLike[str] | None = None,
        *,
        scopes: Sequence[str] = DEFAULT_SCOPES,
    ) -> None:
        self._credentials_path = self._resolve_credentials_path(credentials_path)
        self._scopes = tuple(scopes)
        self._credentials: service_account.Credentials | None = None
        self._service: Any = None

    @staticmethod
    def _resolve_credentials_path(
        credentials_path: str | os.PathLike[str] | None,
    ) -> Path:
        if credentials_path:
            path = Path(credentials_path).expanduser().resolve()
        else:
            env = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
            if env:
                path = Path(env).expanduser().resolve()
            else:
                candidates = sorted(
                    p
                    for p in Path(__file__).resolve().parent.glob("*.json")
                    if "service_account" in p.read_text(encoding="utf-8", errors="ignore")
                )
                if not candidates:
                    raise GoogleDriveError(
                        "Service-account key not found: pass credentials_path "
                        "explicitly or set GOOGLE_APPLICATION_CREDENTIALS."
                    )
                path = candidates[0]
        if not path.is_file():
            raise GoogleDriveError(f"Credentials file not found: {path}")
        return path

    @property
    def credentials(self) -> service_account.Credentials:
        if self._credentials is None:
            self._credentials = service_account.Credentials.from_service_account_file(
                str(self._credentials_path), scopes=list(self._scopes)
            )
        return self._credentials

    @property
    def service(self) -> Any:
        """Lazily built google-api-python-client resource."""
        if self._service is None:
            self._service = build(
                "drive",
                "v3",
                credentials=self.credentials,
                cache_discovery=False,
            )
        return self._service

    @property
    def service_account_email(self) -> str:
        return self.credentials.service_account_email

    def __enter__(self) -> "GoogleDriveClient":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()

    def close(self) -> None:
        if self._service is not None:
            self._service.close()
            self._service = None

    # ---- internals ------------------------------------------------------- #
    def _execute(self, request: Any, *, attempts: int = 5) -> Any:
        """Execute a request with exponential backoff on transient errors."""
        delay = 1.0
        for attempt in range(1, attempts + 1):
            try:
                return request.execute()
            except HttpError as exc:
                status = getattr(exc.resp, "status", None)
                if status in _RETRYABLE_STATUS and attempt < attempts:
                    time.sleep(delay)
                    delay *= 2
                    continue
                message = _describe_http_error(exc)
                if status == 404:
                    raise FileNotFound(message) from exc
                raise GoogleDriveError(message) from exc
            except OSError as exc:
                if attempt < attempts:
                    time.sleep(delay)
                    delay *= 2
                    continue
                raise GoogleDriveError(f"Network error: {exc}") from exc
        raise GoogleDriveError("Request failed after retries")

    # ===================================================================== #
    #  CREATE
    # ===================================================================== #
    def create_file(
        self,
        name: str,
        content: bytes | str,
        mime_type: str | None = None,
        parent_folder_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a new file on Google Drive and return its metadata.

        Args:
            name: File name (e.g. ``"report.txt"``).
            content: File content as ``str`` or ``bytes``.
            mime_type: MIME type; auto-detected from ``name`` suffix if ``None``.
            parent_folder_id: Optional parent folder id.

        Returns:
            Full file metadata dict from the Drive API.
        """
        mime = mime_type or _mime_guess(name)
        data = _to_bytes(content)

        file_metadata: dict[str, Any] = {"name": name}
        if parent_folder_id:
            file_metadata["parents"] = [parent_folder_id]

        media = self._build_media_upload(data, mime)
        response = self._execute(
            self.service.files().create(
                body=file_metadata,
                media_body=media,
                fields="id,name,mimeType,webViewLink,createdTime,modifiedTime,size",
            )
        )
        return response

    def create_folder(self, name: str, parent_folder_id: str | None = None) -> dict[str, Any]:
        """Create a new folder on Google Drive and return its metadata.

        Args:
            name: Folder name.
            parent_folder_id: Optional parent folder id.

        Returns:
            Full file metadata dict from the Drive API.
        """
        file_metadata: dict[str, Any] = {
            "name": name,
            "mimeType": "application/vnd.google-apps.folder",
        }
        if parent_folder_id:
            file_metadata["parents"] = [parent_folder_id]

        response = self._execute(
            self.service.files().create(
                body=file_metadata,
                fields="id,name,mimeType,webViewLink,createdTime",
            )
        )
        return response

    def create_document(
        self,
        title: str,
        parent_folder_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a new Google Docs file on Drive and return its metadata.

        Returns:
            Dict with ``id``, ``name``, ``webViewLink``.
        """
        file_metadata: dict[str, Any] = {
            "name": title,
            "mimeType": "application/vnd.google-apps.document",
        }
        if parent_folder_id:
            file_metadata["parents"] = [parent_folder_id]

        response = self._execute(
            self.service.files().create(
                body=file_metadata,
                fields="id,name,webViewLink",
            )
        )
        return response

    def create_spreadsheet(
        self,
        title: str,
        parent_folder_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a new Google Sheets file on Drive and return its metadata.

        Returns:
            Dict with ``id``, ``name``, ``webViewLink``.
        """
        file_metadata: dict[str, Any] = {
            "name": title,
            "mimeType": "application/vnd.google-apps.spreadsheet",
        }
        if parent_folder_id:
            file_metadata["parents"] = [parent_folder_id]

        response = self._execute(
            self.service.files().create(
                body=file_metadata,
                fields="id,name,webViewLink",
            )
        )
        return response

    # ===================================================================== #
    #  READ
    # ===================================================================== #
    def list_files(
        self,
        query: str = "",
        mime_types: Iterable[str] | None = None,
        include_trashed: bool = False,
        page_size: int = 50,
        fields: str = "files(id,name,mimeType,modifiedTime,size,parents,webViewLink)",
    ) -> list[dict[str, Any]]:
        """List files visible to the service account.

        Args:
            query: Drive API query string (e.g. ``"name contains 'report'"``).
            mime_types: Optional MIME type filter (e.g. ``["text/plain"]``).
            include_trashed: Include trashed files.
            page_size: Max results per page.
            fields: Drive API ``fields`` parameter for projection.

        Returns:
            List of file metadata dicts.
        """
        conditions: list[str] = []
        if query:
            conditions.append(query)
        if mime_types:
            # Drive v3 does not support `mimeType in (...)`; build an OR-chain.
            ors = " or ".join(f"mimeType = '{mt}'" for mt in mime_types)
            conditions.append(f"({ors})")
        if not include_trashed:
            conditions.append("trashed = false")

        drive_query = " and ".join(conditions) if conditions else "trashed = false"

        files: list[dict[str, Any]] = []
        page_token: str | None = None

        while True:
            response = self._execute(
                self.service.files().list(
                    q=drive_query,
                    fields=fields,
                    pageSize=page_size,
                    pageToken=page_token,
                    orderBy="modifiedTime desc",
                )
            )
            files.extend(response.get("files", []))
            page_token = response.get("nextPageToken")
            if not page_token:
                break
        return files

    def get_file_metadata(self, file_id: str) -> dict[str, Any]:
        """Get metadata for a single file by id.

        Raises :class:`FileNotFound` if the file doesn't exist or is not accessible.
        """
        return self._execute(
            self.service.files().get(
                fileId=file_id,
                fields="id,name,mimeType,modifiedTime,size,parents,webViewLink,description",
            )
        )

    def get_file_content(self, file_id: str, mime_type: str | None = None) -> bytes:
        """Download file content as bytes.

        Binary files (txt, csv, pdf, images, ...) are downloaded as-is.
        Google-native files (Docs/Sheets/Slides) cannot be downloaded directly,
        so they are exported; ``mime_type`` picks the export format and defaults
        to the first entry of :data:`GOOGLE_EXPORT_FORMATS` for that type.

        Raises :class:`FileNotFound` if the file doesn't exist.
        """
        meta = self.get_file_metadata(file_id)
        if meta.get("mimeType", "") in GOOGLE_EXPORT_FORMATS:
            export_mime = mime_type or GOOGLE_EXPORT_FORMATS[meta["mimeType"]][0]
            return self.export_file(file_id, export_mime)
        return self._execute(self.service.files().get_media(fileId=file_id))

    def export_file(self, file_id: str, mime_type: str) -> bytes:
        """Export a Google-native file into an open format (e.g. Sheets -> xlsx)."""
        return self._execute(
            self.service.files().export_media(fileId=file_id, mimeType=mime_type)
        )

    def download_file(
        self, file_id: str, dest: str | os.PathLike[str], mime_type: str | None = None
    ) -> Path:
        """Download a file (or export a Google-native one) to the local disk."""
        data = self.get_file_content(file_id, mime_type)
        target = Path(dest).expanduser()
        if target.is_dir():
            target = target / self.get_file_metadata(file_id)["name"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return target

    def get_folder_files(
        self,
        folder_id: str,
        query: str = "",
    ) -> list[dict[str, Any]]:
        """List files inside a specific folder.

        Args:
            folder_id: Drive folder id.
            query: Additional query conditions.

        Returns:
            List of file metadata dicts.
        """
        conditions = [f"'{folder_id}' in parents"]
        if query:
            conditions.append(query)
        drive_query = " and ".join(conditions)
        return self.list_files(query=drive_query)

    def search_files(
        self,
        query: str,
        mime_types: Iterable[str] | None = None,
        fields: str = "files(id,name,mimeType,modifiedTime,size,webViewLink)",
    ) -> list[dict[str, Any]]:
        """Search files by query string.

        Example queries::

            'root' in parents                        # files in root
            name contains 'report'                   # name contains word
            mimeType = 'text/plain'                   # plain text
            modifiedTime > '2025-01-01T00:00:00Z'    # modified after date

        Returns:
            List of file metadata dicts.
        """
        conditions: list[str] = [query]
        if mime_types:
            ors = " or ".join(f"mimeType = '{mt}'" for mt in mime_types)
            conditions.append(f"({ors})")
        drive_query = " and ".join(conditions)
        return self.list_files(query=drive_query, fields=fields)

    # ===================================================================== #
    #  UPDATE
    # ===================================================================== #
    def rename_file(self, file_id: str, new_name: str) -> dict[str, Any]:
        """Rename a file on Google Drive.

        Returns updated file metadata.
        """
        return self._execute(
            self.service.files().update(
                fileId=file_id,
                body={"name": new_name},
                fields="id,name,mimeType,modifiedTime",
            )
        )

    def move_file(
        self,
        file_id: str,
        parent_folder_id: str | None = None,
        remove_parents: list[str] | None = None,
        add_parents: list[str] | None = None,
    ) -> dict[str, Any]:
        """Move a file between folders.

        Args:
            file_id: File to move.
            parent_folder_id: New parent folder id.
            remove_parents: List of parent ids to remove.
            add_parents: List of parent ids to add (overrides ``parent_folder_id``).

        Returns:
            Updated file metadata.
        """
        body: dict[str, Any] = {}
        if parent_folder_id:
            body["addParents"] = parent_folder_id
        if remove_parents:
            body["removeParents"] = ",".join(remove_parents)
        if add_parents:
            body["addParents"] = ",".join(add_parents)

        return self._execute(
            self.service.files().update(
                fileId=file_id,
                body=body,
                fields="id,name,parents,webViewLink",
            )
        )

    def update_file_content(
        self,
        file_id: str,
        content: bytes | str,
        mime_type: str | None = None,
    ) -> dict[str, Any]:
        """Update the content of an existing file.

        Args:
            file_id: Target file id.
            content: New content.
            mime_type: Optional MIME type override.

        Returns:
            Updated file metadata.
        """
        mime = mime_type or None
        data = _to_bytes(content)
        media = self._build_media_upload(data, mime)

        return self._execute(
            self.service.files().update(
                fileId=file_id,
                media_body=media,
                fields="id,name,modifiedTime,size",
            )
        )

    def set_file_description(
        self, file_id: str, description: str
    ) -> dict[str, Any]:
        """Set or update a file's description."""
        return self._execute(
            self.service.files().update(
                fileId=file_id,
                body={"description": description},
                fields="id,name,description",
            )
        )

    # ===================================================================== #
    #  DELETE
    # ===================================================================== #
    def delete_file(self, file_id: str) -> None:
        """Permanently delete a file on Google Drive.

        Raises :class:`FileNotFound` if the file doesn't exist.
        """
        self._execute(
            self.service.files().delete(
                fileId=file_id,
            )
        )

    def delete_folder(self, folder_id: str, recursive: bool = False) -> None:
        """Delete a folder.

        Args:
            folder_id: Folder id.
            recursive: If ``True``, delete all files inside first.
        """
        if recursive:
            children = self.get_folder_files(folder_id)
            for child in children:
                if child.get("mimeType") == "application/vnd.google-apps.folder":
                    self.delete_folder(child["id"], recursive=True)
                else:
                    self.delete_file(child["id"])
        self.delete_file(folder_id)

    # ===================================================================== #
    #  Discovery / metadata helpers
    # ===================================================================== #
    def list_spreadsheets(
        self,
        query: str = "",
    ) -> list[dict[str, str]]:
        """List all Google Sheets files visible to the service account.

        Returns:
            List of ``{'id': ..., 'name': ..., 'webViewLink': ...}`` dicts.
        """
        conditions = ["mimeType = 'application/vnd.google-apps.spreadsheet'"]
        if query:
            conditions.append(query)
        drive_query = " and ".join(conditions)
        files = self.list_files(
            query=drive_query,
            fields="files(id,name,webViewLink,modifiedTime)",
        )
        return [
            {"id": f["id"], "name": f.get("name", ""), "webViewLink": f.get("webViewLink", "")}
            for f in files
        ]

    def get_drive_root(self) -> list[dict[str, Any]]:
        """List files in the root folder."""
        return self.list_files(query="'root' in parents and trashed = false")

    def get_file_url(self, file_id: str) -> str:
        """Return the web view URL for a file."""
        meta = self.get_file_metadata(file_id)
        return meta.get("webViewLink", "")

    # ===================================================================== #
    #  Internal helpers
    # ===================================================================== #
    @staticmethod
    def _build_media_upload(data: bytes, mime_type: str | None) -> Any:
        """Build a MediaUpload object for Drive API."""
        from googleapiclient.http import MediaIoBaseUpload
        from io import BytesIO

        stream = BytesIO(data)
        return MediaIoBaseUpload(
            stream,
            mimetype=mime_type or "application/octet-stream",
            resumable=False,
        )


# --------------------------------------------------------------------------- #
# Entry point: list all files in the Drive
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    CREDENTIALS_PATH = Path(__file__).with_name(
        os.getenv("GOOGLE_SA_JSON", "service-account.json")
    )

    with GoogleDriveClient(CREDENTIALS_PATH) as drive:
        print(f"Service account : {drive.service_account_email}")
        print()

        # --- List all files in the Drive (visible to the service account) ---- #
        print("=" * 70)
        print("  Files in Google Drive:")
        print("=" * 70)

        files = drive.list_files(
            fields=(
                "files(id,name,mimeType,modifiedTime,size,webViewLink,parents,"
                "owners(displayName))"
            ),
            page_size=100,
        )

        if not files:
            print("\nThe Drive is empty or no files are shared with this account.\n")
        else:
            print(
                f"\n{'Name':<38} {'Type':<14} {'Modified':<20} "
                f"{'Size':<9} {'Owner':<20} {'ID'}\n"
            )
            print("-" * 155)

            for f in files:
                file_id = f.get("id", "")
                name = (f.get("name") or "").replace("\n", " ").ljust(38)[:38]
                mime = (f.get("mimeType") or "").replace(
                    "application/vnd.google-apps.", ""
                ).ljust(14)[:14]
                mod = (f.get("modifiedTime", "") or "")[:19].ljust(20)
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
                size = str(size).ljust(9)
                owners = f.get("owners") or []
                owner = (owners[0].get("displayName", "") if owners else "").ljust(20)[:20]

                print(f"{name}  {mime}  {mod}  {size}  {owner}  {file_id}")

            print("\n" + "-" * 155)
            print(f"Total files: {len(files)}\n")

            # --- Quick preview: show files in root folder ------------------- #
            print("=" * 70)
            print("  Root folder contents:")
            print("=" * 70)

            root_files = drive.get_drive_root()
            if not root_files:
                print(
                    "\nRoot folder is empty. Files owned by other users and shared\n"
                    "with the service account do not live in its own root — they are\n"
                    "still returned by list_files() above.\n"
                )
            else:
                for f in root_files:
                    name = f.get("name", "(untitled)")
                    file_id = f.get("id", "")
                    mime = f.get("mimeType", "")
                    print(f"  [{mime}] {name} -> {file_id}")
                print()

            # --- List spreadsheets specifically ----------------------------- #
            print("=" * 70)
            print("  Google Sheets files:")
            print("=" * 70)

            sheets = drive.list_spreadsheets()
            if not sheets:
                print("\nNo spreadsheets found.\n")
            else:
                for s in sheets:
                    print(f"  {s['name'] or '(untitled)'}")
                    print(f"    ID:   {s['id']}")
                    print(f"    Link: {s['webViewLink']}")
                    print()
