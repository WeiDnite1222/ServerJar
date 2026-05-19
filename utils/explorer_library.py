"""
Source are from KiteeLauncher.
"""
import os
import re
import subprocess
import tempfile


def check_java_executable_and_major_version(java_executable_path):
    # test java runtimes are executable
    try:
        subprocess.run([java_executable_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True, None
    except PermissionError:
        return False, "Could not execute the Java executable. Permission denied."
    except Exception as e:
        return False, "Unknown error occurred while executing the Java executable. {}".format(e)


def get_java_version_by_execute(java_executable_path):
    # test java runtimes are executable

    # executable it
    try:
        result = subprocess.run([java_executable_path, '-version'], stderr=subprocess.PIPE, stdout=subprocess.PIPE,
                                text=True)
    except PermissionError:
        return False, None, "Could not execute the Java executable. Permission denied."
    except Exception as e:
        return False, None, "Unknown error occurred while executing the Java executable. {}".format(e)

    # Get output
    output = result.stderr

    # Get major version (e.g., "21.0.3") and full version in the output
    match = re.search(r'java version "(\d+)(?:\.(\d+))?', output)

    # Is for installation by launcher runtimes (Because is openjdk not oracle java....)
    if not match:
        match = re.search(r'openjdk version "(\d+)(?:\.(\d+))?', output)

        if not match:
            return False, None, "Unsupported Java runtime build or current path is not a valid java executable."

    try:
        major_version = match.group(1)
        # Special case for Java 8 where we need to use the second part (8) instead of 1
        if major_version == "1" and match.group(2):
            major_version = match.group(2)
        return True, major_version, None
    except IndexError:
        return False, None, "The target Java runtime version is too old or is not supported by this method."

def convert_java_version_tuple_to_major_version(java_version_tuple):
    try:
        _, major_version, *_ = java_version_tuple.split(".")
        return True, major_version
    except ValueError:
        return False, None


def get_java_version_by_checkmyduke(java_executable_path):
    checkmyduke_jar = os.path.join("jar_files", "CheckMyDuke.jar")

    if not os.path.exists(checkmyduke_jar):
        return False, None, "CheckMyDuke.jar not found"

    # executable it
    try:
        result = subprocess.run([java_executable_path, '-jar', checkmyduke_jar], stderr=subprocess.PIPE, stdout=subprocess.PIPE,
                                text=True)
    except PermissionError:
        return False, None, "Could not execute the Java executable. Permission denied."
    except Exception as e:
        return False, None, "Unknown error occurred while executing the Java executable. {}".format(e)\


    status, major_version = convert_java_version_tuple_to_major_version(result.stdout.strip())

    if status:
        return True, major_version, None
    else:
        return False, None, "Unsupported Java runtime build or current path is not a valid java executable."

def search_available_java_runtimes_in_directory(target_directory, java_executable_name="java.exe" if os.name == "nt" else "java"):
    """
    Using this function may take ~1min to search for available Java executable files.
    """
    found_java_runtimes = []

    for root, dirs, files in os.walk(target_directory):
        for file in files:
            if file == java_executable_name:
                found_java_runtimes.append(os.path.join(root, file))


    return found_java_runtimes




