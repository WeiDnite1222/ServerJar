"""
bk_core

Copyright (c) 2024~2025 Techarerm/TedKai
Copyright (c) 2026 Kitee Contributors. All rights reserved.
"""
import shutil
import os
import platform
import requests
from ..bk_utils.utils import download_file, extract_zip
from ..java.java_info import get_java_build_download_url_from_azul
from ..bk_utils.crypto import verify_checksum


def download_java_file(file_info, file_path, destination_folder):
    download_type = "raw"
    file_url = file_info["downloads"][download_type]["url"]
    full_file_path = os.path.join(destination_folder, file_path)
    expected_sha1 = file_info["downloads"][download_type].get("sha1")

    directory = os.path.join(destination_folder, os.path.dirname(file_path))
    os.makedirs(directory, exist_ok=True)

    if os.path.exists(full_file_path) and expected_sha1 and verify_checksum(full_file_path, expected_sha1):
        return []

    return download_file(
        file_url,
        full_file_path,
        with_verify=True,
        sha1=expected_sha1,
    )


def download_java_runtime_files(manifest, install_path):
    if not os.path.exists(install_path):
        return False, "InstallFolderAreNotExist"

    files = manifest.get("files", {})
    download_tasks = []

    for file_path, file_info in files.items():
        if file_info.get("type") == "directory":
            os.makedirs(os.path.join(install_path, file_path), exist_ok=True)
            continue

        if "downloads" in file_info:
            download_tasks.extend(download_java_file(file_info, file_path, install_path))

    return True, download_tasks


def install_azul_build_version_jvm(java_major_version, install_dir, full_architecture, platform_name):
    Status, download_url, version_type = get_java_build_download_url_from_azul(platform_name, full_architecture,
                                                                               java_major_version)

    if not Status:
        return False, "Get download url failed. Unsupported platform"

    tmp = os.path.join(os.path.dirname(install_dir), ".jvm_installer_tmp")
    os.makedirs(tmp, exist_ok=True)

    jvm_zip_file_path = os.path.join(tmp, f"jvm-azul-{java_major_version}.zip")

    if os.path.exists(jvm_zip_file_path):
        try:
            os.remove(jvm_zip_file_path)
        except Exception as e:
            return False, "Cannot delete tmp file. ERR: {}".format(e)

    jvm_unzip_dest = os.path.join(tmp, f"jvm-azul-{java_major_version}-unzipped")
    if os.path.exists(jvm_unzip_dest):
        try:
            shutil.rmtree(jvm_unzip_dest)
        except Exception as e:
            return False, "Cannot delete unzip tmp file. ERR: {}".format(e)

    if not os.path.exists(jvm_zip_file_path):
        try:
            _download_file_now(download_url, jvm_zip_file_path)
        except Exception as e:
            return False, "Download file failed. ERR: {}".format(e)

    extract_zip(jvm_zip_file_path, jvm_unzip_dest)

    if os.path.exists(install_dir):
        try:
            shutil.rmtree(install_dir)
        except Exception as e:
            return False, f"Cleaning install dir failed. ERR: {e}"

    if platform_name.lower() == "darwin":
        unzip_list = os.listdir(jvm_unzip_dest)
        jvm_app_folder_name = unzip_list[0]
        home_folder_path = os.path.join(jvm_unzip_dest, jvm_app_folder_name, f"zulu-{java_major_version}.jre",
                                        "Contents", "Home")
        if not os.path.isdir(home_folder_path):
            home_folder_path = _find_java_home(jvm_unzip_dest)
            if home_folder_path is None:
                return False, "JAVA_HOME not found in the unzip folder."

    else:
        unzip_list = os.listdir(jvm_unzip_dest)
        home_folder_name = unzip_list[0]
        home_folder_path = os.path.join(jvm_unzip_dest, home_folder_name)
        if not os.path.isdir(home_folder_path):
            home_folder_path = _find_java_home(jvm_unzip_dest)
            if home_folder_path is None:
                return False, "JAVA_HOME not found in the unzip folder."

    install_root_dir = os.path.dirname(install_dir)
    home_name = os.path.basename(home_folder_path)
    dest_path = os.path.join(install_root_dir, home_name)

    try:
        shutil.move(home_folder_path, install_root_dir)
    except Exception as e:
        return False, f"Move home folder to install dir failed. ERR: {e}"

    try:
        os.rename(dest_path, install_dir)
    except Exception as e:
        return False, "Rename dest_path to require name failed. ERR: {}".format(e)

    return True, None


def _find_java_home(root):
    for current_root, _, files in os.walk(root):
        executable_names = {"java.exe", "javaw.exe"} if os.name == "nt" else {"java"}
        if os.path.basename(current_root).lower() == "bin" and any(name in executable_names for name in files):
            return os.path.dirname(current_root)
    return None


def find_java_home_in_extracted_runtime(unzip_dir):
    candidates = []
    for java_name in ("javaw.exe", "java.exe", "java"):
        candidates.extend(unzip_dir.rglob(java_name))

    for java_path in candidates:
        parent = java_path.parent
        if parent.name.lower() == "bin":
            return parent.parent

    return None


def runtime_java_executable(install_dir):
    bin_dir = install_dir / "bin"
    if os.name == "nt":
        javaw = bin_dir / "javaw.exe"
        if javaw.exists():
            return javaw
        return bin_dir / "java.exe"
    return bin_dir / "java"


def find_java_runtime_candidates(java_manifest, manifest_platform, java_major_version):
    platform_data = java_manifest.get(manifest_platform, {})
    candidates = []
    for runtime_entries in platform_data.values():
        for runtime_entry in runtime_entries:
            version_name = str(runtime_entry.get("version", {}).get("name") or "")
            if version_name.startswith(str(java_major_version)):
                candidates.append(runtime_entry)
    return candidates


def mojang_java_platform_key():
    system = platform.system().lower()
    machine = platform.machine().lower()

    if system == "windows":
        if "arm" in machine or "aarch64" in machine:
            return "windows-arm64"
        if "64" in machine or "amd64" in machine:
            return "windows-x64"
        return "windows-x86"

    if system == "darwin":
        return "mac-os-arm64" if "arm" in machine or "aarch64" in machine else "mac-os"

    if system == "linux":
        return "linux-arm64" if "arm" in machine or "aarch64" in machine else "linux"

    return None


def _download_file_now(url, dest_path):
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    response = requests.get(url, stream=True, timeout=30)
    response.raise_for_status()
    with open(dest_path, "wb") as file:
        for chunk in response.iter_content(chunk_size=1024 * 128):
            if chunk:
                file.write(chunk)
