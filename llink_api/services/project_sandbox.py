"""Short-lived isolated E2B Linux runtimes for Llink Work project tasks."""
from __future__ import annotations

import asyncio
import logging
import re
import uuid
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Callable

logger = logging.getLogger(__name__)

MAX_PROJECT_FILES = 30
MAX_PROJECT_BYTES = 2_000_000
MAX_FILE_BYTES = 700_000
MAX_COMMAND_SECONDS = 60
MAX_COMMAND_OUTPUT_CHARS = 10_000
MAX_SYNC_FILES = 12
MAX_SYNC_BYTES = 2_000_000
PROJECT_ROOT = "/tmp/llink-workspace"


def safe_project_path(raw_path: str) -> str:
    path = str(raw_path or "").strip().replace(chr(92), "/")
    parts = path.split("/")
    if (
        not path or len(path) > 400 or path.startswith("/")
        or any(part in {"", ".", ".."} for part in parts)
        or chr(0) in path
    ):
        raise ValueError("Le chemin du projet doit être relatif et ne peut contenir . ou ..")
    return "/".join(parts)


def is_sensitive_project_path(path: str) -> bool:
    parts = [part.casefold() for part in path.replace(chr(92), "/").split("/")]
    base = parts[-1] if parts else ""
    if any(part in {".git", ".ssh", "node_modules", ".venv", "venv", "__pycache__"} for part in parts):
        return True
    if base.startswith(".env") or base in {"credentials.json", "service-account.json", "secrets.json"}:
        return True
    if base.endswith((".pem", ".key", ".p12", ".pfx", ".keystore")):
        return True
    return any(token in base for token in ("service-account", "firebase-adminsdk", "private-key", "secret"))


@dataclass
class ProjectSandboxSession:
    session_id: str
    sandbox: Any
    project_id: str
    original_files: dict[str, dict[str, Any]]
    allow_internet_access: bool
    root: str = PROJECT_ROOT
    closed: bool = False

    @classmethod
    async def open(
        cls,
        *,
        project_id: str,
        paths: list[str] | None,
        allow_internet_access: bool,
        request: Any,
        user: dict[str, Any],
        db: Any,
    ) -> tuple["ProjectSandboxSession", dict[str, Any]]:
        from llink_api.api.routes import work as work_routes

        project_id = str(project_id or "").strip()
        listing = await work_routes.list_files(
            request=request, project_id=project_id, user=user, db=db
        )
        items = listing.get("files", [])
        skipped_sensitive: list[str] = []
        if paths is not None:
            if not isinstance(paths, list) or len(paths) > MAX_PROJECT_FILES:
                raise ValueError(f"La sélection doit contenir au maximum {MAX_PROJECT_FILES} chemins.")
            wanted = {safe_project_path(path).casefold() for path in paths}
            items = [
                item for item in items
                if str(item.get("path") or "").casefold() in wanted
            ]
            missing = wanted - {str(item.get("path") or "").casefold() for item in items}
            if missing:
                raise ValueError("Fichiers introuvables dans le projet : " + ", ".join(sorted(missing)[:5]))
        if len(items) > MAX_PROJECT_FILES:
            raise ValueError(f"Sélectionne au maximum {MAX_PROJECT_FILES} fichiers avec workspace_list_files.")

        originals: dict[str, dict[str, Any]] = {}
        prepared: list[tuple[str, str]] = []
        total_bytes = 0
        for item in items:
            path = safe_project_path(str(item.get("path") or item.get("name") or ""))
            if is_sensitive_project_path(path):
                skipped_sensitive.append(path)
                continue
            data = await work_routes.get_file(
                file_id=str(item["id"]), request=request, user=user, db=db
            )
            file_content = data.get("content")
            if not isinstance(file_content, str):
                continue
            size_bytes = len(file_content.encode("utf-8"))
            if size_bytes > MAX_FILE_BYTES:
                raise ValueError(f"Le fichier {path} dépasse 700 Ko.")
            total_bytes += size_bytes
            if total_bytes > MAX_PROJECT_BYTES:
                raise ValueError("Le projet dépasse 2 Mo de texte. Réduis la sélection.")
            prepared.append((path, file_content))
            originals[path] = {
                "id": str(data["id"]),
                "version": int(data.get("version") or 1),
                "name": str(data.get("name") or path.split("/")[-1]),
                "folder": str(data.get("folder") or "/".join(path.split("/")[:-1])),
                "language": str(data.get("language") or "plaintext"),
                "project_id": data.get("project_id") or project_id,
                "content": file_content,
            }
        if not prepared:
            raise ValueError("Aucun fichier texte exploitable n'a été trouvé dans ce projet.")

        # A new E2B Linux sandbox is created for each Work task.
        # Application keys, Firebase credentials and provider tokens are never copied.
        from e2b import Sandbox
        sandbox = await asyncio.wait_for(
            asyncio.to_thread(
                Sandbox.create,
                timeout=360,
                secure=True,
                allow_internet_access=allow_internet_access,
                metadata={"app": "llink-work", "purpose": "project-execution"},
            ),
            timeout=45,
        )
        try:
            await asyncio.to_thread(sandbox.files.make_dir, PROJECT_ROOT)
            for path, file_content in prepared:
                parent = str(PurePosixPath(path).parent)
                if parent not in {"", "."}:
                    await asyncio.to_thread(sandbox.files.make_dir, PROJECT_ROOT + "/" + parent)
                await asyncio.to_thread(sandbox.files.write, PROJECT_ROOT + "/" + path, file_content)
        except Exception:
            try:
                await asyncio.to_thread(sandbox.kill)
            except Exception:
                logger.exception("Échec du nettoyage d'un sandbox E2B partiellement initialisé.")
            raise

        session = cls(
            session_id=uuid.uuid4().hex[:20],
            sandbox=sandbox,
            project_id=project_id,
            original_files=originals,
            allow_internet_access=allow_internet_access,
        )
        return session, {
            "opened": True,
            "session_id": session.session_id,
            "project_id": project_id,
            "files_loaded": len(prepared),
            "bytes_loaded": total_bytes,
            "paths": [path for path, _ in prepared],
            "sensitive_files_skipped": skipped_sensitive,
            "working_directory": PROJECT_ROOT,
            "network_access": "enabled" if allow_internet_access else "disabled",
            "next": "Inspecte les fichiers, exécute les tests/build, corrige les erreurs, puis synchronise uniquement les fichiers validés.",
        }

    async def run_command(self, command: str, timeout_seconds: int = 45) -> dict[str, Any]:
        if self.closed:
            raise ValueError("Le sandbox a déjà été fermé.")
        command = str(command or "").strip()
        if not command or len(command) > 1800 or chr(0) in command:
            raise ValueError("Commande vide ou trop longue.")
        if re.search(
            r"\b(?:sudo|shutdown|reboot|mkfs|mount|umount|iptables|passwd|useradd)\b",
            command,
            flags=re.IGNORECASE,
        ):
            raise ValueError("Cette commande système est bloquée dans le sandbox Work.")
        timeout = max(1, min(int(timeout_seconds or 45), MAX_COMMAND_SECONDS))
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(
                    self.sandbox.commands.run,
                    command,
                    cwd=self.root,
                    timeout=timeout,
                    request_timeout=timeout + 12,
                ),
                timeout=timeout + 15,
            )
            exit_code = int(getattr(result, "exit_code", 0))
            stdout = str(getattr(result, "stdout", "") or "")
            stderr = str(getattr(result, "stderr", "") or "")
        except Exception as exc:
            result = getattr(exc, "result", None)
            exit_code = int(getattr(result, "exit_code", getattr(exc, "exit_code", 1)) or 1)
            stdout = str(getattr(result, "stdout", getattr(exc, "stdout", "")) or "")
            stderr = str(getattr(result, "stderr", getattr(exc, "stderr", str(exc))) or "")
        return {
            "executed": True,
            "exit_code": exit_code,
            "passed": exit_code == 0,
            "stdout": stdout[:MAX_COMMAND_OUTPUT_CHARS],
            "stderr": stderr[:MAX_COMMAND_OUTPUT_CHARS],
            "output_truncated": len(stdout) > MAX_COMMAND_OUTPUT_CHARS or len(stderr) > MAX_COMMAND_OUTPUT_CHARS,
            "command": command,
            "timeout_seconds": timeout,
            "network_access": "enabled" if self.allow_internet_access else "disabled",
        }

    async def list_files(self) -> dict[str, Any]:
        if self.closed:
            raise ValueError("Le sandbox a déjà été fermé.")
        result = await asyncio.to_thread(
            self.sandbox.commands.run,
            "find . -maxdepth 5 -type f -not -path './.git/*' -not -path './node_modules/*' -print | sort",
            cwd=self.root,
            timeout=15,
            request_timeout=20,
        )
        files = [
            line.strip().removeprefix("./")
            for line in str(getattr(result, "stdout", "") or "").splitlines()
            if line.strip()
        ]
        return {"files": files[:200], "total": len(files), "truncated": len(files) > 200}

    async def read_file(self, raw_path: str) -> dict[str, Any]:
        if self.closed:
            raise ValueError("Le sandbox a déjà été fermé.")
        path = safe_project_path(raw_path)
        if is_sensitive_project_path(path):
            raise PermissionError("La lecture des fichiers sensibles est bloquée.")
        raw = await asyncio.to_thread(self.sandbox.files.read, self.root + "/" + path)
        content = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else str(raw)
        if len(content.encode("utf-8")) > MAX_FILE_BYTES:
            raise ValueError("Le fichier dépasse la limite de lecture de 700 Ko.")
        return {"path": path, "content": content[:28_000], "truncated": len(content) > 28_000}

    async def sync_files(
        self,
        *,
        paths: list[str],
        request: Any,
        user: dict[str, Any],
        db: Any,
        record_change: Callable[[dict[str, Any]], None],
    ) -> dict[str, Any]:
        from llink_api.api.routes import work as work_routes

        if self.closed:
            raise ValueError("Le sandbox a déjà été fermé.")
        if not isinstance(paths, list) or not 1 <= len(paths) <= MAX_SYNC_FILES:
            raise ValueError(f"Sélectionne de 1 à {MAX_SYNC_FILES} fichiers à enregistrer.")
        results: list[dict[str, Any]] = []
        sync_bytes = 0
        for raw_path in paths:
            path = safe_project_path(str(raw_path))
            if is_sensitive_project_path(path):
                results.append({"path": path, "saved": False, "error": "Fichier sensible exclu."})
                continue
            try:
                raw = await asyncio.to_thread(self.sandbox.files.read, self.root + "/" + path)
                content = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else str(raw)
                size = len(content.encode("utf-8"))
                if size > MAX_FILE_BYTES:
                    results.append({"path": path, "saved": False, "error": "Fichier supérieur à 700 Ko."})
                    continue
                sync_bytes += size
                if sync_bytes > MAX_SYNC_BYTES:
                    results.append({"path": path, "saved": False, "error": "Limite de 2 Mo de synchronisation atteinte."})
                    continue
                previous = self.original_files.get(path)
                if previous and content == previous["content"]:
                    results.append({"path": path, "saved": False, "unchanged": True, "error": "Fichier inchangé."})
                    continue
                if not previous and len(self.original_files) >= MAX_PROJECT_FILES:
                    results.append({"path": path, "saved": False, "error": "Limite de 30 fichiers synchronisables atteinte."})
                    continue
                if previous:
                    updated = await work_routes.update_file(
                        file_id=previous["id"],
                        payload=work_routes.WorkFileUpdate(
                            content=content,
                            expected_version=previous["version"],
                            name=previous["name"],
                            folder=previous["folder"],
                            language=previous["language"],
                        ),
                        request=request,
                        user=user,
                        db=db,
                    )
                else:
                    parts = path.split("/")
                    updated = await work_routes.create_file(
                        payload=work_routes.WorkFileCreate(
                            name=parts[-1],
                            folder="/".join(parts[:-1]),
                            content=content,
                            language="plaintext",
                            project_id=self.project_id,
                        ),
                        request=request,
                        user=user,
                        db=db,
                    )
                record_change(updated)
                self.original_files[path] = {
                    "id": str(updated["id"]),
                    "version": int(updated.get("version") or 1),
                    "name": str(updated.get("name") or path.split("/")[-1]),
                    "folder": str(updated.get("folder") or "/".join(path.split("/")[:-1])),
                    "language": str(updated.get("language") or "plaintext"),
                    "project_id": updated.get("project_id") or self.project_id,
                    "content": content,
                }
                results.append({"path": path, "saved": True, "file_id": updated["id"], "version": updated["version"]})
            except Exception as exc:
                results.append({
                    "path": path,
                    "saved": False,
                    "conflict": getattr(exc, "status_code", None) == 409,
                    "error": str(getattr(exc, "detail", exc))[:300],
                })
        return {
            "results": results,
            "saved_count": sum(bool(item.get("saved")) for item in results),
            "failed_count": sum(not item.get("saved") for item in results),
            "next": "Relis les fichiers synchronisés dans Work. Les fichiers non sélectionnés n'ont pas été modifiés.",
        }

    async def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        try:
            await asyncio.to_thread(self.sandbox.kill)
        except Exception:
            logger.exception("Impossible de fermer le sandbox E2B de Work.")
