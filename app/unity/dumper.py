from io import BytesIO
from pathlib import Path
import platform
import shutil
import subprocess
from zipfile import ZipFile, is_zipfile


class UnityDumpError(Exception):
    pass


class DumperNotConfigured(UnityDumpError):
    pass


def looks_like_unity_package(package_path: Path) -> bool:
    if not is_zipfile(package_path):
        return False
    found = _scan_zip(package_path)
    return found["metadata"] and found["libil2cpp"]


def _scan_zip(path_or_bytes: Path | BytesIO) -> dict[str, bool]:
    found = {"metadata": False, "libil2cpp": False}
    with ZipFile(path_or_bytes) as archive:
        for name in archive.namelist():
            if name.endswith("global-metadata.dat"):
                found["metadata"] = True
            elif name.endswith("libil2cpp.so"):
                found["libil2cpp"] = True
            elif name.endswith(".apk"):
                nested = _scan_nested_apk(archive, name)
                found["metadata"] = found["metadata"] or nested["metadata"]
                found["libil2cpp"] = found["libil2cpp"] or nested["libil2cpp"]
    return found


def _scan_nested_apk(archive: ZipFile, name: str) -> dict[str, bool]:
    try:
        return _scan_zip(BytesIO(archive.read(name)))
    except Exception:
        return {"metadata": False, "libil2cpp": False}


def dump_package(
    package_path: Path,
    output_dir: Path,
    *,
    il2cpp_dumper_path: Path | None = None,
    timeout_seconds: float = 3600.0,
) -> Path:
    dumper = find_il2cpp_dumper(il2cpp_dumper_path)
    inputs_dir = output_dir / "_inputs"
    inputs_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    libil2cpp, metadata = extract_unity_inputs(package_path, inputs_dir)
    _run_il2cpp_dumper(dumper, libil2cpp, metadata, output_dir, timeout_seconds)
    dummy_dll = output_dir / "DummyDll"
    if not dummy_dll.exists():
        raise UnityDumpError(f"Il2CppDumper 未生成 DummyDll: {dummy_dll}")
    shutil.rmtree(inputs_dir, ignore_errors=True)
    return dummy_dll


def find_il2cpp_dumper(custom_path: Path | None = None) -> Path:
    if custom_path:
        if custom_path.is_file():
            return custom_path
        raise UnityDumpError(f"指定的 Il2CppDumper 不存在: {custom_path}")
    system = platform.system()
    repo_root = Path(__file__).resolve().parents[2]
    candidate = repo_root / "lib" / "product" / "Il2CppDumper" / ("osx" if system == "Darwin" else "linux") / "Il2CppDumper"
    if candidate.is_file():
        return candidate
    raise DumperNotConfigured("找不到 Il2CppDumper，请配置 IL2CPP_DUMPER_PATH 或放到 lib/product/Il2CppDumper")


def extract_unity_inputs(package_path: Path, output_dir: Path) -> tuple[Path, Path]:
    found = _extract_from_zip(package_path, output_dir)
    if found["libil2cpp"] is None:
        raise UnityDumpError("缺少 libil2cpp.so，无法 Il2CppDump")
    if found["metadata"] is None:
        raise UnityDumpError("非 Unity 应用，找不到 global-metadata.dat")
    return found["libil2cpp"], found["metadata"]


def _extract_from_zip(path_or_bytes: Path | BytesIO, output_dir: Path) -> dict[str, Path | None]:
    found: dict[str, Path | None] = {"libil2cpp": None, "metadata": None}
    with ZipFile(path_or_bytes) as archive:
        for name in archive.namelist():
            if found["metadata"] is None and name.endswith("global-metadata.dat"):
                found["metadata"] = _write_zip_member(archive, name, output_dir / "global-metadata.dat")
            elif found["libil2cpp"] is None and name.endswith("libil2cpp.so"):
                found["libil2cpp"] = _write_zip_member(archive, name, output_dir / "libil2cpp.so")
            elif name.endswith(".apk"):
                nested = _extract_from_nested_apk(archive, name, output_dir)
                found["metadata"] = found["metadata"] or nested["metadata"]
                found["libil2cpp"] = found["libil2cpp"] or nested["libil2cpp"]
            if found["metadata"] and found["libil2cpp"]:
                break
    return found


def _extract_from_nested_apk(archive: ZipFile, name: str, output_dir: Path) -> dict[str, Path | None]:
    try:
        return _extract_from_zip(BytesIO(archive.read(name)), output_dir)
    except Exception:
        return {"metadata": None, "libil2cpp": None}


def _write_zip_member(archive: ZipFile, name: str, target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(archive.read(name))
    return target


def _run_il2cpp_dumper(
    dumper_path: Path,
    libil2cpp_path: Path,
    metadata_path: Path,
    output_dir: Path,
    timeout_seconds: float,
) -> None:
    try:
        result = subprocess.run(
            [str(dumper_path), str(libil2cpp_path), str(metadata_path), str(output_dir)],
            input="\n",
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise UnityDumpError("Il2CppDumper 执行超时") from exc
    output_lines = (result.stdout + result.stderr).splitlines()
    if not any("Generate dummy dll..." in line for line in output_lines):
        raise UnityDumpError("Il2CppDumper 未生成 DummyDll: " + "".join(output_lines[-5:]).strip())
