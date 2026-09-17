"""VaultService: file-first markdown vault on disk, Obsidian-compatible.

The vault root (``data/vault`` by default) can be opened as a folder vault in
Obsidian. The service owns every absolute path: external callers store and
receive vault-relative POSIX paths (so database rows stay portable), while
absolute paths are derived inside the service. Files are the source of truth
for knowledge (spec §14/§17); the database keeps metadata and the vector
store keeps embeddings.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True)
class VaultFile:
    """One file discovered by :meth:`VaultService.scan`."""

    rel_path: str  # POSIX-style path relative to the vault root (portable)
    abs_path: Path  # absolute path on disk (service-internal only)
    mtime: datetime  # UTC modification time


class VaultService:
    """Path mapping, safe slugs, and file primitives over one vault root."""

    def __init__(self, root: Path) -> None:
        self._root = Path(root).resolve()

    # -- Path mapping ---------------------------------------------------

    @staticmethod
    def slugify(text: str) -> str:
        """Return a safe kebab-case slug for folders/filenames.

        Unicode is normalized to NFKD and stripped of non-ASCII accents,
        lowercased, with every run of non-alphanumeric characters collapsed
        into a single dash; leading/trailing dashes are removed. An empty
        result falls back to ``nota`` so folders and files always exist.
        """
        ascii_text = (
            unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
        )
        slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
        return slug or "nota"

    def project_folder(self, project_name: str) -> Path:
        """Return the absolute vault folder for a project."""
        return self._root / self.slugify(project_name)

    def markdown_path(self, project_name: str, title: str) -> Path:
        """Return an absolute markdown path, deduped with ``-2``, ``-3``, ….

        When a file with the slugged title already exists, an integer suffix
        is appended until an unused name is found (Obsidian-style dedupe).
        Parent folders are created at write time, not here.
        """
        folder = self.project_folder(project_name)
        base = self.slugify(title)
        candidate = folder / f"{base}.md"
        if not candidate.exists():
            return candidate
        index = 2
        while True:
            candidate = folder / f"{base}-{index}.md"
            if not candidate.exists():
                return candidate
            index += 1

    # -- File primitives -------------------------------------------------

    def _resolve(self, path: Path | str) -> Path:
        """Turn a vault-relative or absolute path into an absolute path."""
        candidate = Path(path)
        return candidate if candidate.is_absolute() else self._root / candidate

    def write_text(self, path: Path | str, content: str) -> None:
        """Write ``content`` as UTF-8, creating parent folders as needed."""
        target = self._resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def read_text(self, path: Path | str) -> str:
        """Return the UTF-8 content of a vault file."""
        return self._resolve(path).read_text(encoding="utf-8")

    def delete(self, path: Path | str) -> None:
        """Delete a vault file, ignoring a missing file."""
        try:
            self._resolve(path).unlink()
        except FileNotFoundError:
            pass

    def exists(self, path: Path | str) -> bool:
        """Return whether the vault file exists."""
        return self._resolve(path).exists()

    def mtime(self, path: Path | str) -> datetime | None:
        """Return the file's modification time as a UTC datetime, else None."""
        try:
            return datetime.fromtimestamp(self._resolve(path).stat().st_mtime, tz=UTC)
        except FileNotFoundError:
            return None

    # -- Scanning ----------------------------------------------------------

    def scan(self) -> list[VaultFile]:
        """Return every file under the root (recursive), sorted by rel_path.

        Empty when the root does not exist. Symlinks resolving outside the
        root are rejected (``Path.relative_to`` on the resolved path), so a
        scan never escapes the vault.
        """
        if not self._root.exists():
            return []
        files: list[VaultFile] = []
        for path in sorted(self._root.rglob("*")):
            if not path.is_file():
                continue
            try:
                path.resolve().relative_to(self._root)
            except ValueError:
                continue  # normalizes to a path escaping the vault root
            rel = path.relative_to(self._root)
            files.append(
                VaultFile(rel_path=rel.as_posix(), abs_path=path, mtime=self.mtime(path))
            )
        files.sort(key=lambda f: f.rel_path)
        return files