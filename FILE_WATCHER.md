# WikiForge — File Watcher

## Purpose

The file watcher monitors each project's source directory for new, modified, and deleted files, then triggers the processing pipeline automatically.

## Design

Two modes are available, selected via configuration:

| Mode | Library | How It Works | Best For |
|------|---------|-------------|----------|
| `watchdog` | `watchdog` | OS-level filesystem events (inotify/FSEvents/kqueue) | Local directories, low latency |
| `polling` | Built-in | Periodic directory scan comparing hashes | Network mounts, Docker volumes, any filesystem |

Default: `polling` (most reliable across environments).

## Watcher Daemon

```python
# wikiforge/watcher/daemon.py

import asyncio
import logging
from pathlib import Path
from datetime import datetime
from .delta import DeltaDetector

logger = logging.getLogger(__name__)


class FileWatcherDaemon:
    """Watches a project's source directory for file changes."""

    SUPPORTED_EXTENSIONS = {".md", ".markdown", ".doc", ".docx", ".xlsx", ".xls", ".csv", ".tsv", ".pdf"}

    def __init__(self, project, file_service, pipeline_service):
        self.project = project
        self.file_service = file_service
        self.pipeline_service = pipeline_service
        self.delta = DeltaDetector()
        self._running = False
        self._task: asyncio.Task | None = None
        self._last_scan: datetime | None = None

    async def start(self):
        """Start the watcher daemon as a background task."""
        if self._running:
            logger.warning(f"Watcher already running for {self.project.slug}")
            return

        self._running = True
        self._task = asyncio.create_task(self._watch_loop())
        logger.info(f"Watcher started for {self.project.slug} "
                    f"(dir={self.project.source_dir}, interval={self.project.watch_interval}s)")

    async def stop(self):
        """Stop the watcher daemon."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info(f"Watcher stopped for {self.project.slug}")

    async def _watch_loop(self):
        """Main polling loop."""
        while self._running:
            try:
                await self.scan()
            except Exception as e:
                logger.error(f"Watcher scan failed for {self.project.slug}: {e}")
                # Back off on error
                await asyncio.sleep(min(self.project.watch_interval * 3, 300))
                continue

            await asyncio.sleep(self.project.watch_interval)

    async def scan(self) -> dict:
        """Scan source directory and process changes.

        Returns dict with counts: {new, modified, deleted, unchanged}
        """
        source_dir = Path(self.project.source_dir)
        if not source_dir.exists():
            logger.error(f"Source directory missing: {source_dir}")
            return {"error": f"Directory not found: {source_dir}"}

        # Get current filesystem state
        current_files = {}
        for filepath in source_dir.rglob("*"):
            if filepath.is_file() and filepath.suffix.lower() in self.SUPPORTED_EXTENSIONS:
                relative = filepath.relative_to(source_dir)
                current_files[str(relative)] = {
                    "path": filepath,
                    "size": filepath.stat().st_size,
                    "mtime": filepath.stat().st_mtime,
                }

        # Get known files from database
        known_files = self.file_service.get_all_files(self.project.id)
        known_map = {f.filepath: f for f in known_files}

        results = {"new": 0, "modified": 0, "deleted": 0, "unchanged": 0}

        # Detect new and modified files
        for relative_path, file_info in current_files.items():
            if relative_path in known_map:
                existing = known_map[relative_path]
                # Check if file changed (hash-based)
                new_hash = self.delta.compute_hash(file_info["path"])
                if new_hash != existing.content_hash:
                    # File modified
                    results["modified"] += 1
                    logger.info(f"Modified: {relative_path}")
                    await self._handle_modified(existing, file_info["path"], new_hash)
                else:
                    results["unchanged"] += 1
            else:
                # New file
                results["new"] += 1
                logger.info(f"New file: {relative_path}")
                await self._handle_new(relative_path, file_info)

        # Detect deleted files
        for filepath, existing in known_map.items():
            if filepath not in current_files and existing.status != "deleted":
                results["deleted"] += 1
                logger.info(f"Deleted: {filepath}")
                await self._handle_deleted(existing)

        self._last_scan = datetime.utcnow()
        return results

    async def _handle_new(self, relative_path: str, file_info: dict):
        """Process a newly discovered file."""
        source_file = self.file_service.create_file(
            project_id=self.project.id,
            filepath=relative_path,
            filename=Path(relative_path).name,
            file_extension=Path(relative_path).suffix.lower(),
            file_size=file_info["size"],
            content_hash=self.delta.compute_hash(file_info["path"]),
        )
        await self.pipeline_service.process_file(source_file.id)

    async def _handle_modified(self, source_file, filepath: Path, new_hash: str):
        """Process a modified file."""
        self.file_service.update_file(
            source_file.id,
            content_hash=new_hash,
            file_size=filepath.stat().st_size,
            status="pending",
        )

        if self.project.update_mode == "delta":
            # Only reprocess this file
            await self.pipeline_service.reprocess_file(source_file.id)
        else:
            # Full rebuild
            await self.pipeline_service.rebuild_project(self.project.id)

    async def _handle_deleted(self, source_file):
        """Handle a deleted source file."""
        self.file_service.mark_deleted(source_file.id)
        # Remove associated wiki page(s)
        self.wiki_service.remove_pages_for_file(source_file.id)

    @property
    def status(self) -> dict:
        return {
            "running": self._running,
            "source_dir": self.project.source_dir,
            "poll_interval_sec": self.project.watch_interval,
            "last_scan_at": self._last_scan.isoformat() if self._last_scan else None,
            "supported_extensions": sorted(self.SUPPORTED_EXTENSIONS),
        }
```

## Delta Detector

```python
# wikiforge/watcher/delta.py

import hashlib
from pathlib import Path


class DeltaDetector:
    """Detects file changes using SHA-256 content hashing."""

    @staticmethod
    def compute_hash(filepath: Path | str) -> str:
        """Compute SHA-256 hash of file contents.

        Uses chunked reading for memory efficiency with large files.
        """
        sha256 = hashlib.sha256()
        filepath = Path(filepath)

        with open(filepath, "rb") as f:
            while chunk := f.read(8192):
                sha256.update(chunk)

        return sha256.hexdigest()

    @staticmethod
    def has_changed(filepath: Path, known_hash: str) -> bool:
        """Check if a file's content differs from the known hash."""
        current = DeltaDetector.compute_hash(filepath)
        return current != known_hash
```

## Debouncing

When multiple files change rapidly (e.g., a batch copy), we debounce to avoid spawning redundant pipeline jobs:

```python
class DebouncedWatcher(FileWatcherDaemon):
    """Extends watcher with change debouncing."""

    def __init__(self, *args, debounce_seconds: float = 5.0, **kwargs):
        super().__init__(*args, **kwargs)
        self.debounce_seconds = debounce_seconds
        self._pending_changes: dict[str, dict] = {}
        self._debounce_task: asyncio.Task | None = None

    async def _handle_new(self, relative_path: str, file_info: dict):
        self._pending_changes[relative_path] = {"type": "new", "info": file_info}
        await self._schedule_flush()

    async def _handle_modified(self, source_file, filepath, new_hash):
        self._pending_changes[source_file.filepath] = {
            "type": "modified", "source_file": source_file,
            "filepath": filepath, "hash": new_hash,
        }
        await self._schedule_flush()

    async def _schedule_flush(self):
        if self._debounce_task:
            self._debounce_task.cancel()
        self._debounce_task = asyncio.create_task(self._flush_after_delay())

    async def _flush_after_delay(self):
        await asyncio.sleep(self.debounce_seconds)
        changes = self._pending_changes.copy()
        self._pending_changes.clear()

        logger.info(f"Flushing {len(changes)} debounced changes for {self.project.slug}")
        for path, change in changes.items():
            if change["type"] == "new":
                await super()._handle_new(path, change["info"])
            elif change["type"] == "modified":
                await super()._handle_modified(
                    change["source_file"], change["filepath"], change["hash"]
                )
```

## Watcher Manager

```python
# wikiforge/watcher/manager.py

class WatcherManager:
    """Manages file watcher daemons for all active projects."""

    def __init__(self):
        self._watchers: dict[str, FileWatcherDaemon] = {}

    async def start_project(self, project, file_service, pipeline_service):
        """Start watching a project's source directory."""
        if project.id in self._watchers:
            await self._watchers[project.id].stop()

        watcher = FileWatcherDaemon(project, file_service, pipeline_service)
        self._watchers[project.id] = watcher
        await watcher.start()

    async def stop_project(self, project_id: str):
        """Stop watching a specific project."""
        if project_id in self._watchers:
            await self._watchers[project_id].stop()
            del self._watchers[project_id]

    async def stop_all(self):
        """Stop all watchers (shutdown)."""
        for watcher in self._watchers.values():
            await watcher.stop()
        self._watchers.clear()

    def get_status(self, project_id: str) -> dict | None:
        watcher = self._watchers.get(project_id)
        return watcher.status if watcher else None

    def get_all_status(self) -> dict:
        return {pid: w.status for pid, w in self._watchers.items()}
```
