import argparse
import json
import subprocess
import tempfile
import uuid
from pathlib import Path


def run(args, *, cwd=None, check=True):
    """Run a command and return its result."""
    result = subprocess.run(
        args,
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )

    if check and result.returncode != 0:
        raise RuntimeError(
            f"Command failed ({result.returncode}): "
            f"{subprocess.list2cmdline(args)}\n"
            f"{result.stdout}{result.stderr}"
        )

    return result


def output(args, *, cwd=None):
    """Run a command and return stdout."""
    result = run(args, cwd=cwd)

    return result.stdout.strip()


def repo_slug(url):
    """Extract OWNER/REPO from a git remote URL."""
    slug = url.strip().rstrip("/")

    if slug.endswith(".git"):
        slug = slug[:-4]

    if slug.startswith("git@"):
        slug = slug.split(":", 1)[1]
    else:
        parts = slug.split("/")
        if len(parts) >= 2:
            slug = "/".join(parts[-2:])

    return slug.lower()


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Merge parent branches into child branches "
            "in a GitHub native stack."
        )
    )

    parser.add_argument(
        "repo",
        help="GitHub repository in OWNER/REPO format",
    )

    parser.add_argument(
        "stack_number",
        type=int,
        help="GitHub native stack number",
    )

    parser.add_argument(
        "--base",
        default="main",
        help="Base branch to merge into the bottom branch (default: main)",
    )

    args = parser.parse_args()

    repo = args.repo
    stack_number = args.stack_number
    base = args.base

    # Verify GitHub CLI authentication.
    run(["gh", "auth", "status"])

    # Find the local Git repository.
    root = Path(output(["git", "rev-parse", "--show-toplevel"]))

    # Verify that the local repository's origin matches the target repo.
    remote_url = run(
        ["git", "config", "--get", "remote.origin.url"],
        cwd=root,
        check=False,
    ).stdout.strip()

    if not remote_url:
        raise RuntimeError(
            f"No 'origin' remote found in local repository {root}."
        )

    if repo_slug(remote_url) != repo.rstrip("/").lower():
        raise RuntimeError(
            f"Local repository {root} points at '{remote_url}', "
            f"but the target repo is '{repo}'. "
            f"Run this script from a clone of {repo}."
        )

    print(f"Local repository: {root}")
    print(f"GitHub repository: {repo}")
    print(f"Stack number: {stack_number}")

    # Retrieve the native stack from GitHub.
    stack_json = output([
        "gh",
        "api",
        f"repos/{repo}/stacks/{stack_number}",
    ])

    stack = json.loads(stack_json)
    prs = stack["pull_requests"]

    if len(prs) < 2:
        raise RuntimeError(
            "Stack has fewer than two pull requests; nothing to merge."
        )

    # Verify that all PRs are open.
    closed_prs = [
        pr["number"]
        for pr in prs
        if pr["state"] != "open"
    ]

    if closed_prs:
        raise RuntimeError(
            f"Stack contains non-open PRs: {closed_prs}"
        )

    # GitHub returns the stack in bottom-to-top order.
    branches = [
        (pr["head"]["ref"], pr["number"])
        for pr in prs
    ]

    print(f"\nStack #{stack_number}")
    print(f"Base branch: {base}")
    print("\nBranches in stack order:")

    for index, (branch, pr_number) in enumerate(branches):
        print(f"  {index}: {branch} (PR #{pr_number})")

    # Merge the base branch into the bottom branch, then each parent
    # branch into its child branch.
    merges = [(base, branches[0][0])]

    for index in range(1, len(branches)):
        merges.append((branches[index - 1][0], branches[index][0]))

    print("\nPlanned merges:")

    for parent, child in merges:
        print(f"  {parent} -> {child}")

    confirmation = input(
        "\nMerge the base and each parent into its child and push? Type YES: "
    )

    if confirmation != "YES":
        print("Cancelled.")
        return

    # Update remote-tracking references.
    run(["git", "fetch", "origin"], cwd=root)

    # Merge base and parent branches bottom-to-top.
    for parent, child in merges:

        print(f"\n{'=' * 60}")
        print(f"Merging '{parent}' into '{child}'")
        print(f"{'=' * 60}")

        # Refresh remote references before every merge.
        run(["git", "fetch", "origin"], cwd=root)

        worktree = (
            Path(tempfile.gettempdir())
            / f"stack-{stack_number}-{uuid.uuid4().hex}"
        )

        # Create an isolated worktree from the child branch.
        run([
            "git",
            "worktree",
            "add",
            "--detach",
            str(worktree),
            f"origin/{child}",
        ], cwd=root)

        # Merge the parent branch into the child.
        merge = run([
            "git",
            "merge",
            "--no-edit",
            f"origin/{parent}",
        ], cwd=worktree, check=False)

        if merge.returncode != 0:
            print("\nERROR: Merge failed.")
            print(merge.stdout)
            print(merge.stderr)
            print(f"Worktree preserved for resolution: {worktree}")
            print(
                "Resolve the conflict in that worktree, "
                "commit the merge, and push the child branch manually."
            )
            raise SystemExit(1)

        # Push the updated child branch.
        push = run([
            "git",
            "push",
            "origin",
            f"HEAD:refs/heads/{child}",
        ], cwd=worktree, check=False)

        if push.returncode != 0:
            print("\nERROR: Push failed.")
            print(push.stdout)
            print(push.stderr)
            print(f"Worktree preserved: {worktree}")
            raise SystemExit(1)

        print(f"Successfully pushed updated branch '{child}'.")

        # Remove the temporary worktree after a successful push.
        run([
            "git",
            "worktree",
            "remove",
            str(worktree),
        ], cwd=root)

    print(
        f"\nAll base and parent-to-child merges completed "
        f"for stack #{stack_number}."
    )


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, json.JSONDecodeError) as exc:
        raise SystemExit(f"ERROR: {exc}") from exc
