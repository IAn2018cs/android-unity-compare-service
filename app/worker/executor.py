import asyncio
from pathlib import Path
import shutil

from app.aps.client import ApsClient
from app.config import Settings
from app.db import TaskStore
from app.models import PairStatus, TaskStatus, VersionRef, VersionStatus
from app.unity.compare import compare_dummy_dirs
from app.unity.dumper import DumperNotConfigured, dump_package, looks_like_unity_package


class TaskExecutor:
    def __init__(self, settings: Settings, store: TaskStore, aps_client: ApsClient | None = None):
        self.settings = settings
        self.store = store
        self.aps_client = aps_client or ApsClient(settings)

    def run(self, task_id: str) -> None:
        asyncio.run(self._run(task_id))

    async def _run(self, task_id: str) -> None:
        task = self.store.get_task(task_id)
        if task is None:
            return

        try:
            for version in task["versions"]:
                await self._download_and_check(task, version)

            task = self.store.get_task(task_id)
            versions = {version["id"]: version for version in task["versions"]}
            if not task["comparisons"]:
                self._finish_unity_check(task_id, task["versions"])
            for pair in task["comparisons"]:
                self._finish_pair(task_id, pair, versions)

            status = self._task_status(self.store.get_task(task_id))
            self.store.mark_task(task_id, status)
            self._cleanup(task_id, failed=status != TaskStatus.SUCCEEDED)
        except Exception as exc:
            self.store.mark_task(task_id, TaskStatus.FAILED, str(exc))
            self._cleanup(task_id, failed=True)
            raise

    async def _download_and_check(self, task: dict, version: dict) -> None:
        target = Path(self.settings.work_dir) / task["taskId"] / "packages" / f"{version['id']}.apk"
        self.store.mark_version(version["id"], VersionStatus.DOWNLOAD_RUNNING)
        try:
            await self.aps_client.download(
                task["packageName"],
                VersionRef(versionCode=version["versionCode"], versionName=version["versionName"]),
                target,
            )
            self.store.set_version_paths(version["id"], package_path=target)
            self.store.mark_version(version["id"], VersionStatus.DOWNLOAD_SUCCEEDED)
            self.store.mark_version(version["id"], VersionStatus.DUMP_RUNNING)
            if not looks_like_unity_package(target):
                self.store.mark_version(version["id"], VersionStatus.UNITY_UNSUPPORTED, "包缺少 libil2cpp.so 或 global-metadata.dat")
                return
            dump_path = Path(self.settings.work_dir) / task["taskId"] / "dumps" / version["id"]
            try:
                dummy_dll = dump_package(
                    target,
                    dump_path,
                    il2cpp_dumper_path=self.settings.il2cpp_dumper_path,
                    timeout_seconds=self.settings.il2cpp_dumper_timeout_seconds,
                )
                self.store.set_version_paths(version["id"], dump_path=dummy_dll)
            except DumperNotConfigured:
                # ponytail: no bundled dumper yet; keep phase-1 worker useful until lib/product is added.
                self.store.set_version_paths(version["id"], dump_path=dump_path)
            self.store.mark_version(version["id"], VersionStatus.UNITY_DUMPABLE)
        except Exception as exc:
            self.store.mark_version(version["id"], VersionStatus.FAILED, str(exc))

    def _finish_unity_check(self, task_id: str, versions: list[dict]) -> None:
        version = versions[0]
        if version["status"] == VersionStatus.UNITY_DUMPABLE:
            self.store.add_artifact(task_id, None, "unity-check.json", f"{task_id}/unity-check.json", "application/json")

    def _finish_pair(self, task_id: str, pair: dict, versions: dict[str, dict]) -> None:
        old = versions[pair["oldVersionId"]]
        new = versions[pair["newVersionId"]]
        if old["status"] != VersionStatus.UNITY_DUMPABLE or new["status"] != VersionStatus.UNITY_DUMPABLE:
            self.store.mark_pair(pair["pairId"], PairStatus.FAILED, "pair 两端必须都是可 dump Unity 包")
            return
        self.store.mark_pair(pair["pairId"], PairStatus.COMPARING)
        try:
            package_name = self.store.get_task(task_id)["packageName"]
            report_dir = Path(self.settings.work_dir) / task_id / "reports" / pair["pairId"]
            artifacts = compare_dummy_dirs(
                Path(old["dumpPath"]),
                Path(new["dumpPath"]),
                report_dir,
                metadata={
                    "package_name": package_name,
                    "old_version_name": old["versionName"] or old["versionCode"],
                    "new_version_name": new["versionName"] or new["versionCode"],
                },
                dll_analyzer_path=self.settings.dll_analyzer_path,
                timeout_seconds=self.settings.dll_analyzer_timeout_seconds,
            )
            self.store.mark_pair(pair["pairId"], PairStatus.UPLOADING)
            for source, content_type in ((artifacts.json_path, "application/json"), (artifacts.html_path, "text/html")):
                object_key = self._persist_artifact(package_name, task_id, pair["pairId"], source)
                self.store.add_artifact(task_id, pair["pairId"], source.name, object_key, content_type)
            self.store.mark_pair(pair["pairId"], PairStatus.SUCCEEDED)
        except Exception as exc:
            self.store.mark_pair(pair["pairId"], PairStatus.FAILED, str(exc))

    def _persist_artifact(self, package_name: str, task_id: str, pair_id: str, source: Path) -> str:
        object_key = f"{self.settings.report_storage_prefix}/{package_name}/{task_id}/{pair_id}/{source.name}"
        target = Path(self.settings.data_dir) / "reports" / object_key
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        return object_key

    @staticmethod
    def _task_status(task: dict) -> TaskStatus:
        pairs = task["comparisons"]
        if not pairs:
            return TaskStatus.SUCCEEDED if task["versions"][0]["status"] == VersionStatus.UNITY_DUMPABLE else TaskStatus.FAILED
        failed = sum(1 for pair in pairs if pair["status"] == PairStatus.FAILED)
        if failed == 0:
            return TaskStatus.SUCCEEDED
        if failed == len(pairs):
            return TaskStatus.FAILED
        return TaskStatus.PARTIAL_FAILED

    def _cleanup(self, task_id: str, failed: bool) -> None:
        if failed and self.settings.keep_failed_work_dir:
            return
        # ponytail: executor is a placeholder; real dump/report cleanup will delete this populated task dir later.
        task_dir = Path(self.settings.work_dir) / task_id
        if task_dir.exists():
            import shutil

            shutil.rmtree(task_dir, ignore_errors=True)
