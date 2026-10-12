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

    args = parser.parse_args()

    repo = args.repo
    stack_number = args.stack_number

    # Verify GitHub CLI authentication.
    run(["gh", "auth", "status"])

    # Find the local Git repository.
    root = Path(output(["git", "rev-parse", "--show-toplevel"]))

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
    print(f"Base branch: {stack['base']['ref']}")
    print("\nBranches in stack order:")

    for index, (branch, pr_number) in enumerate(branches):
        print(f"  {index}: {branch} (PR #{pr_number})")

    print("\nPlanned merges:")

    for index in range(1, len(branches)):
        parent = branches[index - 1][0]
        child = branches[index][0]
        print(f"  {parent} -> {child}")

    confirmation = input(
        "\nMerge each parent into its child and push? Type YES: "
    )

    if confirmation != "YES":
        print("Cancelled.")
        return

    # Update remote-tracking references.
    run(["git", "fetch", "origin"], cwd=root)

    # Merge branches bottom-to-top.
    for index in range(1, len(branches)):
        parent = branches[index - 1][0]
        child = branches[index][0]

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

    print(f"\nAll parent-to-child merges completed for stack #{stack_number}.")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, json.JSONDecodeError) as exc:
        raise SystemExit(f"ERROR: {exc}") from exc
