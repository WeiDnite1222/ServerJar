import hashlib
import warnings
from pathlib import Path
import requests
import click
import os
from jproperties import Properties

PAPER_VERSION_API = "https://fill.papermc.io/v3/projects/paper/versions/{}"
PAPER_BUILD_API = "https://fill.papermc.io/v3/projects/paper/versions/{}/builds/{}"
MOJANG_VERSION_MANIFEST_V2 = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"


def read_server_properties(server_dir: Path) -> Properties:
    if not server_dir.exists():
        raise FileNotFoundError("Server directory does not exist")

    props = Properties()

    with open(server_dir / 'server.properties', 'rb') as config_file:
        props.load(config_file, encoding='utf-8')
        return props


def save_server_properties(properties: Properties, server_dir: Path) -> None:
    path = server_dir / 'server.properties'

    with path.open("wb") as config_file:
        properties.store(config_file, encoding='utf-8')


def activate_eula_file(server_dir: Path) -> bool:
    path = server_dir / 'eula.txt'

    if not path.exists():
        raise FileNotFoundError("EULA file does not exist. Did you run the server?")

    with open(path, 'r', encoding='utf-8') as file:
        lines = file.readlines()

    for line in lines:
        if line.strip() == "eula=true":
            print("EULA file has been activated.")
            return True

        print(f"{line}")

    print("To activate eula file please read above text. If you agree this license, enter Y [not agree enter N]")
    result = str(input("Agree? :"))

    if result.strip().lower() != "y":
        return False

    with open(path, 'w', encoding='utf-8') as file:
        for line in lines:
            if line.strip() == "eula=false":
                file.write("eula=true\n")
                continue
            file.write(line)

    return True


def jar_filename(filename: str | None, default: str) -> str:
    if filename:
        name = filename
        if not name.endswith(".jar"):
            name += ".jar"
        return name

    return default


def download_file(url: str, destination: Path, chunk_size: int = 1024 * 512, sha256=None):
    destination.parent.mkdir(parents=True, exist_ok=True)

    with requests.get(url, stream=True, timeout=30) as r:
        if r.status_code != 200:
            raise Exception(f"Download failed: {r.status_code}\nResponse: {r.text}")

        total = int(r.headers.get("content-length", 0))

        with destination.open(mode="wb", buffering=chunk_size) as f:
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

    if sha256:
        sha256_hash = hashlib.sha256()

        with destination.open(mode="rb", buffering=chunk_size) as f:
            for chunk in iter(lambda: f.read(chunk_size), b""):
                sha256_hash.update(chunk)

        hexdigest = sha256_hash.hexdigest()

        if hexdigest == sha256:
            click.echo(f"File {os.path.basename(destination)} verified.")
        else:
            raise RuntimeError(f"Download {os.path.basename(destination)} failed. Hash does not match.")

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


def get_version_manifest():
    try:
        r = requests.get(MOJANG_VERSION_MANIFEST_V2)

        if r.status_code == 200:
            return r.json()

        raise Exception("Unable to fetch version manifest.\n"
                        "Response: {}".format(r.text))
    except requests.exceptions.RequestException as e:
        raise Exception("Unable to get version manifest from server.\n"
                        "URL: {}\n"
                        "Error: {}".format(MOJANG_VERSION_MANIFEST_V2, e))


def get_minecraft_version_metadata(minecraft_version: str):
    manifest = get_version_manifest()
    version_info = next(
        (version for version in manifest.get("versions", []) if version.get("id") == minecraft_version),
        None,
    )

    if version_info is None:
        raise Exception(f"Minecraft version {minecraft_version} was not found in Mojang version manifest.")

    try:
        r = requests.get(version_info["url"])

        if r.status_code == 200:
            return r.json()

        raise Exception("Unable to fetch Minecraft version metadata for {}.\n"
                        "Response: {}".format(minecraft_version, r.text))
    except requests.exceptions.RequestException as e:
        raise Exception("Unable to get Minecraft version metadata from server.\n"
                        "URL: {}\n"
                        "Error: {}".format(version_info.get("url"), e))


def get_latest_version_minecraft(release=True):
    version_list = get_version_list(release=release)
    if not version_list:
        ver = None
    elif release:
        ver = version_list[0]
    else:
        ver = version_list[0].get("id")

    if ver is None:
        raise Exception("Unable to find latest version in version list.\n")

    return ver


def get_specific_version_minecraft_require_java_version(minecraft_version, release=True):
    version_list = get_version_list(release=release)

    if release:
        version_exists = minecraft_version in version_list
    else:
        version_exists = any(version.get("id") == minecraft_version for version in version_list)

    if not version_exists:
        raise Exception("Specified Minecraft version does not exist.")

    metadata = get_minecraft_version_metadata(minecraft_version)

    if not metadata:
        raise Exception("Unable to get Minecraft version metadata for {}.\n".format(minecraft_version))

    return metadata.get("javaVersion", {}).get("majorVersion", None)

def get_paper_server_jar_info(minecraft_version: str, build_version: str):
    url = PAPER_BUILD_API.format(minecraft_version, build_version)

    try:
        r = requests.get(url)
        if r.status_code == 200:
            return r.json().get("downloads", {}).get("server:default", None)
        else:
            raise Exception(f"Unable to fetch paper server jar information. (VER:{minecraft_version},BUILD:{build_version})\n")
    except requests.exceptions.RequestException as e:
        raise Exception(f"Unable to get paper version information. Exec: {e}\n")

def download_server_jar(minecraft_version: str, build_version: str, destination: Path, filename: str | None = None):
    """
    Download server jar (paper server only)
    """
    data = get_paper_server_jar_info(minecraft_version, build_version)

    download_url = data.get("url", None)
    sha256 = data.get("checksums", {}).get("sha256", None)

    jar_name = jar_filename(filename, os.path.basename(download_url))

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination = Path(destination, jar_name)

    if not sha256:
        warnings.warn("Unable to verify server jar due to hash from server is invalid.", UserWarning)

    try:
        download_file(download_url, destination, sha256=sha256)
        return destination
    except Exception as e:
        raise Exception(
            "Unable to download server jar for version {}\nURL: {}\nError: {}".format(minecraft_version, download_url, e))


def get_latest_build_of_version(minecraft_version: str) -> str:
    builds = get_specific_version_paper_builds(minecraft_version)
    if not builds:
        raise Exception(f"No builds found for Paper {minecraft_version}")
    # Paper API usually lists builds ascending; latest is the last one
    return str(builds[-1])


def download_latest_build_paper_jar(minecraft_version: str, destination_dir: Path, filename: str | None = None):
    build = get_latest_build_of_version(minecraft_version)
    return download_server_jar(minecraft_version, build, destination_dir, filename=filename)


def version_exist_from_paper(minecraft_version: str) -> bool:
    try:
        get_specific_version_paper_builds(minecraft_version)
        return True
    except Exception:
        return False


def get_latest_paper_version(release) -> str:
    vers = get_version_list(release=release)
    index = 0
    latest_paper_support_ver = None

    while latest_paper_support_ver is None:
        if len(vers) < index + 1:
            raise Exception("No supported Minecraft version available for Paper support.")

        if version_exist_from_paper(minecraft_version=vers[index]):
            latest_paper_support_ver = vers[index]
            break

        index += 1

    return latest_paper_support_ver


def download_latest_paper_jar(destination_dir: Path, filename: str | None = None, release: bool = True):
    """
    Download latest Minecraft version (release) paper jar
    """
    vers = get_version_list(release=release)

    if len(vers) == 0:
        raise Exception("No versions available for Minecraft (Did the server return wrong response ?)")

    latest_mc = vers[0]

    return download_latest_build_paper_jar(latest_mc, destination_dir, filename=filename)


def download_vanilla_server_jar(minecraft_version: str, destination: Path, filename: str | None = None):
    """
    Download a vanilla Minecraft server jar from Mojang's version manifest.
    """
    metadata = get_minecraft_version_metadata(minecraft_version)
    server_download = metadata.get("downloads", {}).get("server")

    if not server_download or not server_download.get("url"):
        raise Exception(f"Minecraft version {minecraft_version} does not provide a vanilla server jar.")

    url = server_download["url"]
    jar_name = jar_filename(filename, f"minecraft_server.{minecraft_version}.jar")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination = Path(destination, jar_name)

    try:
        download_file(url, destination)
        return destination
    except Exception as e:
        raise Exception("Unable to download vanilla server jar for version {}\nURL: {}\nError: {}".format(
            minecraft_version,
            url,
            e,
        ))

def find_system_java_executables(java_names):
    """
    Find system Java executables
    :param java_names:
    :return:
    """
    roots = []
    if os.name == "nt":
        for env_name in ("ProgramFiles", "ProgramFiles(x86)"):
            root = os.environ.get(env_name)
            if root:
                roots.append(os.path.join(root, "Java"))
    elif os.name == "posix":
        roots.extend(("/Library/Java/JavaVirtualMachines", "/opt/java", "/usr/lib/jvm", "/usr/local/java"))

    found = []
    for root in roots:
        if not os.path.isdir(root):
            continue

        for current_root, _, files in os.walk(root):
            for java_name in java_names:
                if java_name in files and os.path.basename(current_root).lower() == "bin":
                    found.append(os.path.join(current_root, java_name))
                    break

    return found

def major_version_from_runtime_dir(runtime_dir):
    """
    Get major version from target runtime directory
    (Only works if this runtime is created by launcher)
    :param runtime_dir:
    :return:
    """
    name = runtime_dir.name
    if name.lower().startswith("java_"):
        return name.split("_", 1)[1]

    info_path = runtime_dir / "java.version.info"
    if info_path.exists():
        try:
            for line in info_path.read_text(encoding="utf-8").splitlines():
                if line.strip().startswith("JavaMajorVersion") and "=" in line:
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
        except Exception:
            return ""

    return ""
