# Github Branch Stacker

Merge parent branches into child branches in a GitHub native stack.

## Requirements

- Python 3.7+
- [GitHub CLI](https://cli.github.com/) authenticated (`gh auth status` must succeed)
- A local clone of the repository, run from inside it
- Git access to the GitHub remote named `origin`

## Usage

```
python merge_stack.py OWNER/REPO STACK_NUMBER
```

Example:

```
python merge_stack.py TeamUberStrike/uber-client-4-3-8 96
```

### Finding the stack number

List all native stacks in a repository:

```
gh api repos/OWNER/REPO/stacks --jq '.[] | .number'
```

Or open a PR in the stack on GitHub - the stack number is shown on the PR page.

## What it does

1. Fetches the native stack via the GitHub API (`repos/OWNER/REPO/stacks/NUMBER`).
2. Verifies all PRs in the stack are open.
3. Prints the stack order (bottom-to-top) and the planned parent-to-child merges.
4. Asks for confirmation (type `YES`).
5. For each child branch, in a fresh temporary worktree (created in the system
   temp directory, e.g. `%TEMP%\stack-96-<random>`):
   - merges the parent branch into the child with `git merge --no-edit`,
   - pushes the result to the child branch on `origin`,
   - removes the worktree on success.

On a failed merge (conflict) or failed push, the script stops and leaves the
worktree in place so it can be resolved manually.

## Notes

- If a parent branch is already an ancestor of its child, `git merge` reports
  "Already up to date", no merge commit is created, and the push changes
  nothing. The script still reports success - verify on GitHub if you expected
  new merge commits.
- Only open PRs are processed; the script errors if the stack contains closed
  or merged PRs.
- Branches are pushed with `HEAD:refs/heads/<child>`, so branch protection
  rules that reject direct pushes will cause a failure.
