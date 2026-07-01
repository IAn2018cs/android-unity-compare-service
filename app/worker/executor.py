from pathlib import Path

from app.config import Settings
from app.db import TaskStore
from app.models import PairStatus, TaskStatus, VersionStatus


class TaskExecutor:
    def __init__(self, settings: Settings, store: TaskStore):
        self.settings = settings
        self.store = store

    def run(self, task_id: str) -> None:
        task = self.store.get_task(task_id)
        if task is None:
            return

        try:
            for version in task["versions"]:
                self.store.mark_version(version["id"], VersionStatus.DOWNLOAD_SUCCEEDED)
                self.store.mark_version(version["id"], VersionStatus.UNITY_DUMPABLE)

            if not task["comparisons"]:
                self.store.add_artifact(task_id, None, "unity-check.json", f"{task_id}/unity-check.json", "application/json")
            for pair in task["comparisons"]:
                self.store.mark_pair(pair["pairId"], PairStatus.COMPARING)
                self.store.mark_pair(pair["pairId"], PairStatus.SUCCEEDED)
                self.store.add_artifact(task_id, pair["pairId"], "report.json", f"{task_id}/{pair['pairId']}/report.json", "application/json")

            self.store.mark_task(task_id, TaskStatus.SUCCEEDED)
            self._cleanup(task_id, failed=False)
        except Exception as exc:
            self.store.mark_task(task_id, TaskStatus.FAILED, str(exc))
            self._cleanup(task_id, failed=True)
            raise

    def _cleanup(self, task_id: str, failed: bool) -> None:
        if failed and self.settings.keep_failed_work_dir:
            return
        # ponytail: executor is a placeholder; real dump/report cleanup will delete this populated task dir later.
        task_dir = Path(self.settings.work_dir) / task_id
        if task_dir.exists():
            import shutil

            shutil.rmtree(task_dir, ignore_errors=True)
