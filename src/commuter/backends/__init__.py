from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class SessionInfo:
    session_id: str
    project_dir: str
    last_activity: datetime | None
    message_count: int
    first_prompt: str
    summary: str = ""
    jsonl_path: Path | None = field(default=None, repr=False)


class Backend(ABC):
    name: str

    @abstractmethod
    def discover(self) -> list[SessionInfo]:
        """List all sessions on the current machine."""
        ...

    @abstractmethod
    def export_session(self, session_id: str) -> dict:
        """Export a session.

        Returns a dict with keys:
          session_id, project_dir, conversation, config, backend_version
        """
        ...

    @abstractmethod
    def import_session(
        self,
        bundle: dict,
        project_dir: str,
        *,
        dry_run: bool = False,
    ) -> str:
        """Write session data from a bundle to local storage.

        Returns the session_id that was written.
        """
        ...

    @abstractmethod
    def launch(self, session_id: str, project_dir: str) -> None:
        """Launch the AI tool, resuming the given session."""
        ...
