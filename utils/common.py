from pathlib import Path
import requests
import click
import os

PAPER_VERSION_API = "https://api.papermc.io/v2/projects/paper/versions/{}"
PAPER_SERVER_JAR_API = "https://api.papermc.io/v2/projects/paper/versions/{}/builds/{}/downloads/paper-{}-{}.jar"
MOJANG_VERSION_MANIFEST_V2 = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"


def download_file(url: str, destination: Path, chunk_size: int = 1024 * 512):
    destination.mkdir(parents=True, exist_ok=True)

    with requests.get(url, stream=True, timeout=30) as r:
        if r.status_code != 200:
            raise Exception(f"Download failed: {r.status_code}\nResponse: {r.text}")

        total = int(r.headers.get("content-length", 0))

        with destination.open(mode="wb", buffering=chunk_size).write(r.content) as f:
            if total > 0:
                with click.progressbar(length=total, label=f"Downloading {os.path.basename(destination)}") as bar:
                    for chunk in r.iter_content(chunk_size=chunk_size):
                        if chunk:
                            f.write(chunk)
                            bar.update(len(chunk))
            else:
                click.echo(f"Downloading {os.path.basename(destination)} (unknown size)")
                for chunk in r.iter_content(chunk_size=chunk_size):
                    if chunk:
                        f.write(chunk)


def get_specific_version_paper_builds(minecraft_version: str) -> list[dict[str, str]]:
    """
    Get specific version of Paper builds
    :param minecraft_version:
    :return:
    """
    url = PAPER_VERSION_API.format(minecraft_version)
    try:
        r = requests.get(url)

        if r.status_code == 200:
            return r.json().get("builds", [])
        else:
            raise Exception("Unable to fetch build version for {}\n"
                            "Response: {}".format(minecraft_version, r.text))
    except requests.exceptions.RequestException as e:
        raise Exception("Unable to get paper version from server.\n"
                        "URL: {}\n"
                        "Error: {}".format(url, e))


def get_version_list(release=True):
    try:
        r = requests.get(MOJANG_VERSION_MANIFEST_V2)

        if r.status_code == 200:
            if release:
                return [version.get('id') for version in r.json().get("versions", [])
                        if version.get("type") == "release" if version.get('id') is not None]
            return r.json()["versions"]
        else:
            raise Exception("Unable to fetch version list.\n"
                            "Response: {}".format(r.text))
    except requests.exceptions.RequestException as e:
        raise Exception("Unable to get version list from server.\n"
                        "URL: {}\n"
                        "Error: {}".format(MOJANG_VERSION_MANIFEST_V2, e))


def get_latest_version_minecraft(release=True):
    version_list = get_version_list(release=release)
    ver = version_list[0].get("id") if version_list else None

    if ver is None:
        raise Exception("Unable to find latest version in version list.\n")

    return ver


def download_server_jar(minecraft_version: str, build_version: str, destination: Path, filename: str | None = None):
    """
    Download server jar (paper server only)
    """
    url = PAPER_SERVER_JAR_API.format(minecraft_version, build_version, minecraft_version, build_version)

    if filename:
        jar_name = filename
        if not jar_name.endswith(".jar"):
            jar_name += ".jar"
    else:
        jar_name = os.path.basename(url)

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination = Path(destination, jar_name)

    try:
        download_file(url, destination)
        return destination
    except Exception as e:
        raise Exception("Unable to download server jar for version {}\nURL: {}\nError: {}".format(minecraft_version, url, e))


def get_latest_build_of_version(minecraft_version: str) -> str:
    builds = get_specific_version_paper_builds(minecraft_version)
    if not builds:
        raise Exception(f"No builds found for Paper {minecraft_version}")
    # Paper API usually lists builds ascending; latest is the last one
    return str(builds[-1])


def download_latest_build_paper_jar(minecraft_version: str, destination_dir: Path, filename: str | None = None):
    build = get_latest_build_of_version(minecraft_version)
    return download_server_jar(minecraft_version, build, destination_dir, filename=filename)


def download_latest_paper_jar(destination_dir: Path, filename: str | None = None, release: bool = True):
    """
    Download latest Minecraft version (release) paper jar
    """
    vers = get_version_list(release=release)

    if len(vers) == 0:
        raise Exception("No versions available for Minecraft (Did the server return wrong response ?)")

    latest_mc = vers[0]
    return download_latest_build_paper_jar(latest_mc, destination_dir, filename=filename)