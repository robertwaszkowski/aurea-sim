#!/usr/bin/env python3
import os
import shutil
import re

# The script lives in software/tools/maintenance/.  A release archive must be
# assembled from the software root, not from the intermediate tools directory.
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def get_version():
    pyproject_path = os.path.join(ROOT_DIR, "pyproject.toml")
    if os.path.exists(pyproject_path):
        with open(pyproject_path, "r", encoding="utf-8") as f:
            content = f.read()
            match = re.search(r'version\s*=\s*"([^"]+)"', content)
            if match:
                return match.group(1)
    return "1.1.2"

def ignore_patterns(path, names):
    ignored = []
    for name in names:
        if name in (
            "__pycache__", "node_modules", "dist", ".nuxt", ".vscode",
            ".DS_Store", ".git", ".gitignore", ".venv", ".pytest_cache",
            "aureasim.egg-info",
        ) or name.startswith(".pytest"):
            ignored.append(name)
        elif name.endswith((".pyc", ".pyo", ".log", ".pdf", ".docx", ".xlsx", ".csv")):
            ignored.append(name)
    return ignored

def main():
    version = get_version()
    release_name = f"aurea-sim-{version}"
    temp_release_dir = os.path.join(ROOT_DIR, release_name)
    zip_path = os.path.join(ROOT_DIR, f"{release_name}.zip")

    print("==================================================")
    print(f"Preparing Clean GitHub Release Archive: {release_name}")
    print("==================================================")

    # 1. Clean temp directory and zip if exist
    if os.path.exists(temp_release_dir):
        print(f"Cleaning temporary folder: {temp_release_dir}")
        shutil.rmtree(temp_release_dir)
    if os.path.exists(zip_path):
        print(f"Removing old zip: {zip_path}")
        os.remove(zip_path)

    os.makedirs(temp_release_dir)

    # 2. Files to copy directly to root of release
    core_files = [
        "server.py",
        "wizard.py",
        "run_experiment.py",
        "aureasim.sh",
        "aureasim.bat",
        "requirements.txt",
        "environment.yml",
        "pyproject.toml",
        "LICENSE",
        "README.md",
        "CITATION.cff",
        "CHANGELOG.md",
    ]

    for f in core_files:
        src = os.path.join(ROOT_DIR, f)
        if os.path.exists(src):
            print(f"Copying file: {f}")
            shutil.copy2(src, os.path.join(temp_release_dir, f))
        else:
            print(f"[WARNING] File not found: {f}")

    # 3. Directories to copy
    core_dirs = [
        "aureasim",
        "docs",
        "examples",
        "frontend",
        "projects",
        "tests"
    ]

    for d in core_dirs:
        src = os.path.join(ROOT_DIR, d)
        if os.path.exists(src):
            print(f"Copying directory: {d}/")
            shutil.copytree(src, os.path.join(temp_release_dir, d), ignore=ignore_patterns)
        else:
            print(f"[WARNING] Directory not found: {d}")

    # 4. Create ZIP archive
    print(f"\nCreating ZIP archive: {zip_path}...")
    shutil.make_archive(temp_release_dir, 'zip', ROOT_DIR, release_name)

    # 5. Clean up temporary directory
    print("Cleaning up temporary build folder...")
    shutil.rmtree(temp_release_dir)

    print("\n[SUCCESS] Clean GitHub Release Archive created successfully!")
    print(f"Archive file: {zip_path}")
    print(f"Size: {os.path.getsize(zip_path) / (1024*1024):.2f} MB\n")

if __name__ == "__main__":
    main()
