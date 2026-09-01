#!/usr/bin/env python3
import os
import shutil
import subprocess
import sys

# Define root path
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The 10 core projects to keep tracked
CORE_PROJECTS = {
    "Contract Conclusion Process",
    "Incident Management",
    "Leave Request",
    "RES_Sales_Process",
    "RES_Installation_Process",
    "DPE_1-2_Employment_of_academic_teacher",
    "DPE_1-3_Ongoing_HR_services",
    "DPE_1-5_Dismissal_of_academic_teacher"
}

def run_git(args):
    try:
        result = subprocess.run(["git"] + args, cwd=ROOT_DIR, capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] git {' '.join(args)} failed:")
        print(e.stderr)
        return None

def update_gitignore():
    gitignore_path = os.path.join(ROOT_DIR, ".gitignore")
    if not os.path.exists(gitignore_path):
        print("[WARNING] .gitignore not found. Creating a new one...")
        with open(gitignore_path, "w", encoding="utf-8") as f:
            f.write("# AureaSim .gitignore\n")

    with open(gitignore_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    # Define new ignore patterns to ensure are in .gitignore
    patterns_to_add = [
        "\n# Code Ocean capsules and sync tools\n",
        "code_ocean_jii_capsule/\n",
        "code_ocean_software_capsule/\n",
        "sync_to_codeocean.sh\n",
        "run_capsule.sh\n",
        "\n# Local screenshot/movie tooling dependencies\n",
        "diagrams/\n",
        "\n# Local simulation project runs\n",
        "projects/*\n",
        "!projects/README.md\n",
        "!projects/folder_structure.txt\n"
    ]
    for project in sorted(CORE_PROJECTS):
        patterns_to_add.append(f"!projects/{project}/\n")

    # Filter out the old projects ignore rules
    new_lines = []
    skip_mode = False
    for line in lines:
        if line.strip() == "# Local simulation project runs" or line.strip() == "/projects/":
            continue
        if line.strip() == "projects/*" or line.strip().startswith("!projects/"):
            continue
        new_lines.append(line)

    # Append the clean patterns
    new_lines.extend(patterns_to_add)

    # Ensure other directories are covered
    other_ignores = [
        "/results/\n",
        "experiments/\n",
        ".vscode/\n",
        "_dev/\n",
        "_paper/\n",
        "archived_evaluation/\n",
        "research_evaluation/\n",
        "tools/\n"
    ]
    for ignore in other_ignores:
        if ignore not in new_lines:
            new_lines.append(ignore)

    with open(gitignore_path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)
    print("Updated .gitignore with precise project-level ignore rules.")

def main():
    print("==================================================")
    print(" AureaSim Repository Clean-up Script              ")
    print("==================================================")

    # Verify we are in a git repo
    git_dir = os.path.join(ROOT_DIR, ".git")
    if not os.path.exists(git_dir):
        print("[ERROR] This script must be run inside a Git repository.")
        sys.exit(1)

    # 1. Update .gitignore
    update_gitignore()

    # 2. Identify folders/files to untrack (git rm --cached)
    paths_to_untrack = [
        "code_ocean_jii_capsule",
        "code_ocean_software_capsule",
        "sync_to_codeocean.sh",
        "run_capsule.sh",
        "results",
        "experiments",
        ".vscode",
        "_dev",
        "diagrams",
        "_paper",
        "archived_evaluation",
        "research_evaluation",
        "tools"
    ]

    # Find generated projects to untrack
    projects_dir = os.path.join(ROOT_DIR, "projects")
    if os.path.exists(projects_dir):
        for item in os.listdir(projects_dir):
            item_path = os.path.join(projects_dir, item)
            if os.path.isdir(item_path) and item not in CORE_PROJECTS:
                paths_to_untrack.append(f"projects/{item}")

    print(f"Found {len(paths_to_untrack)} paths to untrack from Git.")

    # 3. Perform git rm --cached
    success_count = 0
    for path in paths_to_untrack:
        # Check if tracked in git first
        is_tracked = run_git(["ls-files", path])
        if is_tracked:
            print(f" - Untracking: {path}")
            result = run_git(["rm", "-r", "--cached", "--ignore-unmatch", path])
            if result is not None:
                success_count += 1

    # 4. Commit changes
    if success_count > 0:
        print(f"\nSuccessfully untracked {success_count} folders/files from Git.")
        print("Committing the cleanup...")
        run_git(["add", ".gitignore"])
        commit_msg = "Cleanup: Untrack obsolete capsules, local runs, results, and generated projects"
        commit_result = run_git(["commit", "-m", commit_msg])
        if commit_result:
            print("Cleanup commit created successfully.")

            # Print instructions to update release tag
            print("\n==================================================")
            print(" NEXT STEPS TO UPDATE THE GITHUB RELEASE:         ")
            print("==================================================")
            print("To update the v1.1.2 release on GitHub with this clean state,")
            print("Run these commands manually if needed:")
            print("  git tag -d v1.1.2")
            print("  git push --delete origin v1.1.2")
            print("  git commit --allow-empty -m 'Trigger release'")
            print("  git tag v1.1.2")
            print("  git push origin v1.1.2")
            print("\nThis will automatically update the ZIP file download on GitHub!")
        else:
            print("[WARNING] Failed to commit changes. Please commit manually.")
    else:
        print("\nNo tracked files needed to be untracked.")

if __name__ == "__main__":
    main()
