from pathlib import Path
from zipfile import ZipFile, is_zipfile


def looks_like_unity_package(package_path: Path) -> bool:
    if not is_zipfile(package_path):
        return False
    with ZipFile(package_path) as archive:
        names = archive.namelist()
    return any(name.endswith("global-metadata.dat") for name in names) or any(name.endswith("libil2cpp.so") for name in names)
