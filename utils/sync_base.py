#!/usr/bin/env python3
"""
Synchronize the main branch with LLVM commits, with optional step control.

This script manages the fork point between the local main branch and llvm-main,
allowing you to:
- Sync to the LLVM commit that CIRCT is currently tracking (default)
- Move the fork point forward or backward by a specified number of commits
- Update to the latest llvm-main commit
All while preserving local modifications on top of the chosen base commit.
"""

import os
import sys
import json
import subprocess
import urllib.request
import tempfile
import shutil
import argparse
from pathlib import Path


def run_command(cmd, check=True, capture_output=True):
    """Run a shell command and return the result."""
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=capture_output, text=True, check=check)
    if capture_output:
        return result.stdout.strip()
    return None


def get_current_branch():
    """Get the name of the current Git branch."""
    return run_command(["git", "rev-parse", "--abbrev-ref", "HEAD"])


def get_tracking_branch():
    """Get the tracking branch for the current branch."""
    try:
        return run_command(["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"])
    except subprocess.CalledProcessError:
        return None


def get_remote_url(remote_name):
    """Get the URL for a Git remote."""
    try:
        return run_command(["git", "config", f"remote.{remote_name}.url"])
    except subprocess.CalledProcessError:
        return None


def is_working_directory_dirty():
    """Check if the working directory has uncommitted changes."""
    try:
        # Check for staged changes (returns 0 if no changes)
        run_command(["git", "diff", "--cached", "--quiet"])
    except subprocess.CalledProcessError:
        return True  # Has staged changes

    try:
        # Check for unstaged changes (returns 0 if no changes)
        run_command(["git", "diff", "--quiet"])
    except subprocess.CalledProcessError:
        return True  # Has unstaged changes

    # Check for untracked files
    untracked = run_command(["git", "ls-files", "--others", "--exclude-standard"])
    if untracked:
        return True  # Has untracked files

    return False


def check_main_branch():
    """Ensure we're on the main branch tracking origin/main with SihaoLiu in URL."""
    current_branch = get_current_branch()

    if current_branch != "main":
        print(f"Current branch is '{current_branch}', switching to 'main'...")
        run_command(["git", "checkout", "main"])

    tracking_branch = get_tracking_branch()
    if tracking_branch != "origin/main":
        print(f"ERROR: main branch is not tracking origin/main (currently: {tracking_branch})")
        sys.exit(1)

    origin_url = get_remote_url("origin")
    if not origin_url or "SihaoLiu" not in origin_url:
        print(f"ERROR: origin URL does not contain 'SihaoLiu': {origin_url}")
        sys.exit(1)

    print("✓ On main branch tracking origin/main with correct origin URL")


def get_circt_llvm_commit():
    """Fetch the LLVM commit hash that CIRCT is currently tracking."""
    url = "https://api.github.com/repos/llvm/circt/contents/"

    try:
        with urllib.request.urlopen(url) as response:
            data = json.loads(response.read().decode())

        for item in data:
            if item["name"] == "llvm":
                commit_sha = item["sha"]
                print(f"✓ CIRCT is tracking LLVM commit: {commit_sha}")
                return commit_sha

        print("ERROR: Could not find LLVM submodule in CIRCT repository")
        sys.exit(1)

    except Exception as e:
        print(f"ERROR: Failed to fetch CIRCT repository info: {e}")
        sys.exit(1)


def find_fork_point():
    """Find the merge base between main and llvm-main branches."""
    # Find the common ancestor (fork point) between main and llvm-main
    fork_point = run_command([
        "git", "merge-base", "main", "llvm-main"
    ])

    if not fork_point:
        print("ERROR: Could not find merge base between main and llvm-main")
        sys.exit(1)

    # Get all commits on main that are not on llvm-main (local commits)
    local_commits_output = run_command([
        "git", "rev-list", "--reverse", f"{fork_point}..main"
    ])

    local_commits = []
    if local_commits_output:
        local_commits = local_commits_output.split('\n')

    print(f"✓ Found fork point: {fork_point}")
    print(f"✓ Found {len(local_commits)} local commits on main branch")

    return fork_point, local_commits


def check_if_already_based_on(new_base_commit):
    """Check if main is already based on new_base_commit."""
    try:
        # Check if new_base_commit is an ancestor of main
        run_command(["git", "merge-base", "--is-ancestor", new_base_commit, "main"])
        return True
    except subprocess.CalledProcessError:
        return False


def save_patches(commits, temp_dir):
    """Save commits as patch files."""
    patch_files = []
    for i, commit in enumerate(commits):
        patch_file = os.path.join(temp_dir, f"{i:04d}-{commit[:8]}.patch")
        patch_content = run_command(["git", "format-patch", "-1", "--stdout", commit])
        with open(patch_file, 'w') as f:
            f.write(patch_content)
        patch_files.append(patch_file)
    return patch_files


def ensure_llvm_upstream():
    """Ensure llvm-upstream remote exists and fetch it."""
    remotes = run_command(["git", "remote"]).split('\n')

    if "llvm-upstream" not in remotes:
        print("Adding llvm-upstream remote...")
        run_command(["git", "remote", "add", "llvm-upstream", "git@github.com:llvm/llvm-project.git"])

    # Get the current llvm-main commit before update
    old_llvm_main = None
    try:
        old_llvm_main = run_command(["git", "rev-parse", "llvm-main"])
    except subprocess.CalledProcessError:
        # llvm-main doesn't exist yet
        pass

    print("Fetching llvm-upstream/main...")
    run_command(["git", "fetch", "llvm-upstream", "main:llvm-main"], capture_output=False)

    # Get the new llvm-main commit after update
    new_llvm_main = run_command(["git", "rev-parse", "llvm-main"])

    # Push to origin if llvm-main was updated
    if old_llvm_main != new_llvm_main:
        print("Pushing updated llvm-main to origin...")
        try:
            run_command(["git", "push", "origin", "llvm-main:llvm-main"], capture_output=False)
            print("✓ Pushed llvm-main to origin/llvm-main")
        except subprocess.CalledProcessError:
            print("WARNING: Failed to push llvm-main to origin")
            print("You may need to manually run: git push origin llvm-main:llvm-main")
    else:
        print("✓ llvm-main is already up to date")


def update_llvm_main():
    """Update llvm-main branch is already done in ensure_llvm_upstream."""
    # The llvm-main branch is already updated via the fetch command
    print("✓ llvm-main is synchronized with llvm-upstream/main")


def verify_commits_in_upstream(old_base, new_base):
    """Verify that both old and new base commits exist in llvm-upstream/main."""
    print(f"Verifying commits exist in llvm-upstream/main...")

    try:
        # Check if old_base is ancestor of llvm-upstream/main
        run_command(["git", "merge-base", "--is-ancestor", old_base, "llvm-upstream/main"])
        print(f"✓ Old base {old_base[:8]} found in llvm-upstream/main")
    except subprocess.CalledProcessError:
        print(f"ERROR: Old base commit {old_base} not found in llvm-upstream/main")
        sys.exit(1)

    try:
        # Check if new_base is ancestor of llvm-upstream/main
        run_command(["git", "merge-base", "--is-ancestor", new_base, "llvm-upstream/main"])
        print(f"✓ New base {new_base[:8]} found in llvm-upstream/main")
    except subprocess.CalledProcessError:
        print(f"ERROR: New base commit {new_base} not found in llvm-upstream/main")
        sys.exit(1)


def get_commits_between(from_commit, to_commit, branch="llvm-main"):
    """Get list of commits between two commits on a branch."""
    # Get commits from from_commit (exclusive) to to_commit (inclusive)
    commits = run_command([
        "git", "rev-list", "--reverse", f"{from_commit}..{to_commit}", branch
    ])

    if commits:
        return commits.split('\n')
    return []


def calculate_target_commit(old_base, circt_commit, step):
    """Calculate the target commit based on step value."""
    if step == "MAX":
        # Return latest llvm-main commit
        return run_command(["git", "rev-parse", "llvm-main"])

    step_num = int(step)

    if step_num == 0:
        # Keep current fork point
        return old_base

    # Get all commits on llvm-main
    all_commits = run_command([
        "git", "rev-list", "--reverse", "llvm-main"
    ]).split('\n')

    # Find current position
    try:
        current_idx = all_commits.index(old_base)
    except ValueError:
        print(f"ERROR: Current base {old_base} not found in llvm-main")
        sys.exit(1)

    if step_num > 0:
        # Move forward by step_num commits
        target_idx = current_idx + step_num

        if target_idx < len(all_commits):
            return all_commits[target_idx]
        else:
            print(f"Warning: Requested step {step_num} exceeds available commits. Using latest.")
            return all_commits[-1]
    else:
        # Move backward by abs(step_num) commits
        target_idx = current_idx + step_num  # step_num is negative

        if target_idx >= 0:
            return all_commits[target_idx]
        else:
            print(f"Warning: Cannot go back {abs(step_num)} commits. Using oldest available.")
            return all_commits[0]


def report_fork_position(fork_commit, circt_commit, local_commits_count):
    """Report the position of the fork point relative to CIRCT and llvm-main."""
    print("\n=== Fork Point Position Report ===")

    # Get latest llvm-main
    latest_llvm = run_command(["git", "rev-parse", "llvm-main"])

    # Calculate relative positions
    circt_position = ""
    if fork_commit == circt_commit:
        circt_position = "(same as current fork point)"
    else:
        try:
            # Check if fork is before CIRCT
            run_command(["git", "merge-base", "--is-ancestor", fork_commit, circt_commit])
            # Fork is before CIRCT, count commits between
            commits_to_circt = get_commits_between(fork_commit, circt_commit, "llvm-main")
            circt_position = f"(+{len(commits_to_circt)} commits to current)"
        except subprocess.CalledProcessError:
            try:
                # Check if CIRCT is before fork
                run_command(["git", "merge-base", "--is-ancestor", circt_commit, fork_commit])
                commits_from_circt = get_commits_between(circt_commit, fork_commit, "llvm-main")
                circt_position = f"(-{len(commits_from_circt)} commits to current)"
            except subprocess.CalledProcessError:
                circt_position = "(on different branch)"

    # Calculate position relative to latest llvm-main
    latest_position = ""
    if fork_commit == latest_llvm:
        latest_position = "(at latest)"
    else:
        commits_to_latest = get_commits_between(fork_commit, latest_llvm, "llvm-main")
        latest_position = f"(+{len(commits_to_latest)} commits to current)"

    # Print report
    print(f"Current fork point:  {fork_commit[:8]} (with {local_commits_count} local commits)")
    print(f"CIRCT's LLVM commit: {circt_commit[:8]} {circt_position}")
    print(f"Latest llvm-main:    {latest_llvm[:8]} {latest_position}")


def rebase_to_new_base(new_base_commit, patch_files):
    """Rebase main branch to new base commit and apply patches."""
    print(f"\nRebasing main to {new_base_commit[:8]}...")

    # Create a backup branch
    backup_branch = f"main-backup-{run_command(['date', '+%Y%m%d-%H%M%S'])}"
    run_command(["git", "branch", backup_branch])
    print(f"✓ Created backup branch: {backup_branch}")

    try:
        # Reset main to new base
        run_command(["git", "reset", "--hard", new_base_commit])
        print(f"✓ Reset main to {new_base_commit[:8]}")

        # Apply patches
        print(f"\nApplying {len(patch_files)} patches...")
        for i, patch_file in enumerate(patch_files):
            print(f"Applying patch {i+1}/{len(patch_files)}: {os.path.basename(patch_file)}")
            try:
                run_command(["git", "am", patch_file], capture_output=False)
            except subprocess.CalledProcessError:
                print(f"\nERROR: Failed to apply patch {patch_file}")
                print("You can try to resolve conflicts manually.")
                print(f"To restore the original state: git checkout {backup_branch}")
                sys.exit(1)

        print(f"\n✓ Successfully rebased main to {new_base_commit[:8]}")
        print(f"✓ Applied {len(patch_files)} patches")
        print(f"\nYou can delete the backup branch with: git branch -D {backup_branch}")

    except Exception as e:
        print(f"\nERROR: Rebase failed: {e}")
        print(f"Restoring from backup branch {backup_branch}...")
        run_command(["git", "checkout", backup_branch])
        run_command(["git", "branch", "-f", "main", backup_branch])
        run_command(["git", "checkout", "main"])
        sys.exit(1)


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Synchronize the main branch with LLVM commits, with optional step control."
    )
    parser.add_argument(
        "--step",
        type=str,
        default=None,
        help="Step control for fork point update. Can be: negative int (go back), "
             "0 (keep current), positive int (go forward), or 'MAX' (latest llvm-main)"
    )
    return parser.parse_args()


def main():
    """Main function to synchronize the repository."""
    args = parse_arguments()

    print("=== LLVM-CIRCT Base Synchronization Tool ===\n")

    # Step 0: Check we're on main branch with correct tracking
    check_main_branch()

    # Step 1: Ensure llvm-upstream remote exists and update llvm-main
    ensure_llvm_upstream()
    update_llvm_main()

    # Step 2: Get the latest LLVM commit from CIRCT
    circt_commit = get_circt_llvm_commit()

    # Find fork point and get local commits
    old_base_commit, local_commits = find_fork_point()
    if not old_base_commit:
        print("ERROR: Could not find fork point")
        sys.exit(1)

    # Step 3: Determine target commit based on --step parameter
    if args.step is not None:
        new_base_commit = calculate_target_commit(old_base_commit, circt_commit, args.step)
        print(f"\n✓ Using --step {args.step}: target commit is {new_base_commit[:8]}")
    else:
        new_base_commit = circt_commit
        print(f"\n✓ Using CIRCT's LLVM commit as target: {new_base_commit[:8]}")

    # Step 4: Check if already based on target commit
    if old_base_commit == new_base_commit:
        print(f"\n✓ Main branch is already at target commit {new_base_commit[:8]}")
        report_fork_position(new_base_commit, circt_commit, len(local_commits))
        return

    # Step 5: Check for dirty working directory
    if is_working_directory_dirty():
        print("\nERROR: Working directory has uncommitted changes")
        print("Please commit or stash your changes before running this script")
        print("You can use one of the following commands:")
        print("  git commit -am 'your commit message'  # to commit all changes")
        print("  git stash                            # to temporarily save changes")
        sys.exit(1)

    # Step 6: Save patches
    temp_dir = tempfile.mkdtemp()
    try:
        print(f"\nSaving patches to {temp_dir}...")
        patch_files = save_patches(local_commits, temp_dir)
        print(f"✓ Saved {len(patch_files)} patches")

        # Step 7: Verify commits exist in upstream
        verify_commits_in_upstream(old_base_commit, new_base_commit)

        # Step 8: Rebase to new base
        rebase_to_new_base(new_base_commit, patch_files)

        # Step 9: Report fork position
        report_fork_position(new_base_commit, circt_commit, len(local_commits))

    finally:
        # Clean up temp directory
        shutil.rmtree(temp_dir)
        print(f"\n✓ Cleaned up temporary directory")


if __name__ == "__main__":
    main()
