"""
bk_core

Copyright (c) 2024~2025 Techarerm/TedKai
Copyright (c) 2026 Kitee Contributors. All rights reserved.
"""
import zipfile
import requests
import os


def create_download_task(
    url,
    dest_path,
    sha1=None,
    with_verify=True,
    crypto_type="sha1",
    chunk_size=8192,
):
    return {
        "url": url,
        "dest": dest_path,
        "sha1": sha1,
        "with_verify": with_verify,
        "crypto_type": crypto_type,
        "chunk_size": chunk_size,
    }


def flatten_download_queue(nested_urls_and_paths):
    return [
        create_download_task(url, dest_path)
        for sublist in nested_urls_and_paths
        for url, dest_path in sublist
    ]


def download_file(url, dest_path, with_verify=True, sha1=None, no_output=False, custom_chunk_size=8192):
    """
    Downloads a file from a URL and saves it to dest_path.
    """
    return [
        create_download_task(
            url,
            dest_path,
            sha1=sha1,
            with_verify=with_verify,
            chunk_size=custom_chunk_size,
        )
    ]

def n_download_file(url, dest_path, enable_hash_check=False, sha1=None, no_download_output=False, chunk_size=8192):
    """
    Downloads a file from a URL and saves it to dest_path.
    """
    return [
        create_download_task(
            url,
            dest_path,
            sha1=sha1,
            with_verify=enable_hash_check,
            chunk_size=chunk_size,
        )
    ]


def extract_zip(zip_path, extract_to):
    try:
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(extract_to)
        print(f"Extracted {zip_path} to {extract_to}")
    except zipfile.BadZipFile as e:
        print(f"[ERR] Error extracting {zip_path}: {e}")


def multi_thread_download(nested_urls_and_paths, name, max_workers=5, retries=1, download_with_progress_bar=True):
    """
    Downloads multiple files using multiple threads with retry attempts.
    nested_urls_and_paths should be a nested list where each element is a list containing a tuple of (url, dest_path).
    """
    return flatten_download_queue(nested_urls_and_paths)


def multithread_download(
    download_url_list,
    file_dest_list,
    progress_name,
    max_workers=8,
    with_verify_checksum=False,
    file_hash_list=None,
    download_with_progress_bar=False,
    no_output=None,
    crypto_type="sha1",
):
    # parameters
    if file_hash_list is None:
        file_hash_list = []
    if no_output is None:
        no_output = download_with_progress_bar

    if not with_verify_checksum:
        file_hash_list = [None for _ in download_url_list]

    return [
        create_download_task(
            file_url,
            file_dest,
            sha1=file_hash,
            with_verify=with_verify_checksum,
            crypto_type=crypto_type,
        )
        for file_url, file_dest, file_hash in zip(download_url_list, file_dest_list, file_hash_list)
    ]


def find_jar_file_main_class(jar_file_path):
    manifest_path = 'META-INF/MANIFEST.MF'
    try:
        with zipfile.ZipFile(jar_file_path, 'r') as jar:
            if not manifest_path in jar.namelist():
                return None

            manifest = jar.read(manifest_path).decode('utf-8')
            for line in manifest.splitlines():
                if line.startswith('Main-Class:'):
                    # Return the class name specified in the Main-Class entry
                    return line.split(':')[1].strip()

            return None
    except Exception as e:
        return None


def check_url_status(url):
    try:
        # Send a HEAD request to save bandwidth
        response = requests.head(url, allow_redirects=True, timeout=5)
        if response.status_code == 200:
            return True
        elif response.status_code == 404:
            return False
        else:
            return False
    except Exception as e:
        return False


def pause():
    command = None
    if os.name == "posix":
        command = 'read -p "Press enter to continue..."'
    elif os.name == "nt":
        command = "pause"

    if command is not None: os.system(command)
