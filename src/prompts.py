"""MCP prompt templates for Bitbucket workflows.

Prompts are parameterised text templates that a compatible client (Claude Code,
Cursor, ...) surfaces as slash commands. Each builder here is a pure function that
returns the prompt body as a string; ``src/server.py`` wraps them with
``@conditional_prompt()`` so FastMCP exposes them via ``prompts/list``.

Keeping the builders in a dedicated module makes them trivially unit-testable
without going through the FastMCP decorator.
"""


def build_review_pull_request_prompt(repo_slug: str, pull_request_id: str) -> str:
    """Template guiding a complete AI review of a pull request."""
    return f"""Perform a thorough code review of pull request #{pull_request_id} in repository "{repo_slug}".

Gather context using these tools, in order:
1. get_pull_request(repo_slug="{repo_slug}", pull_request_id="{pull_request_id}") — metadata, description, author, reviewers
2. get_pull_request_diffstat(repo_slug="{repo_slug}", pull_request_id="{pull_request_id}") — changed files overview
3. get_pull_request_diff(repo_slug="{repo_slug}", pull_request_id="{pull_request_id}") — the full diff
4. get_pull_request_comments(repo_slug="{repo_slug}", pull_request_id="{pull_request_id}") — existing discussion
5. get_pull_request_tasks(repo_slug="{repo_slug}", pull_request_id="{pull_request_id}") — open tasks

Then produce a structured review:
- **Summary** — what the PR does, in 2-3 sentences
- **Risk assessment** — scope, blast radius, migration/breaking concerns
- **Code quality** — design, readability, tests, edge cases
- **Security** — input validation, secrets, auth, injection
- **Recommendation** — approve or request changes, with the must-fix items listed"""


def build_debug_pipeline_failure_prompt(repo_slug: str, pipeline_uuid: str) -> str:
    """Template guiding the diagnosis of a failed pipeline run."""
    return f"""Diagnose the failure of pipeline {pipeline_uuid} in repository "{repo_slug}".

Investigate using these tools, in order:
1. get_pipeline_run(repo_slug="{repo_slug}", pipeline_uuid="{pipeline_uuid}") — status and trigger info
2. get_pipeline_steps(repo_slug="{repo_slug}", pipeline_uuid="{pipeline_uuid}") — identify the failed step(s)
3. get_pipeline_step_logs(repo_slug="{repo_slug}", pipeline_uuid="{pipeline_uuid}", step_uuid="<failed step uuid>") — read the `content` of each failed step's log (only the tail is returned by default; if `truncated` is true and the root cause is not in it, widen the window with start/end)

Then produce a structured diagnosis:
- **Root cause** — the underlying reason for the failure
- **Failed step** — which step failed and at what point
- **Error message** — the key error line(s) from the logs
- **Fix suggestion** — a concrete next action to resolve it"""


def build_summarize_repository_prompt(repo_slug: str) -> str:
    """Template guiding a high-level summary of a repository."""
    return f"""Summarize the repository "{repo_slug}" for someone new to it.

Gather context using these tools:
1. get_repository(repo_slug="{repo_slug}") — basic info, language, description
2. list_commits(repo_slug="{repo_slug}", page_size=10) — recent activity
3. get_pull_requests(repo_slug="{repo_slug}", state="OPEN", page_size=5) — open pull requests
4. list_pipeline_runs(repo_slug="{repo_slug}", page_size=5) — recent CI status
5. list_issues(repo_slug="{repo_slug}", state="open", page_size=5) — open issues

Then produce a structured summary:
- **Purpose** — what the repository is for
- **Recent activity** — what has been changing lately
- **Health** — CI status, open PRs/issues, maintenance signals
- **Key contributors** — who is most active"""


def build_onboard_reviewer_prompt(repo_slug: str, pull_request_id: str) -> str:
    """Template helping a new reviewer get up to speed on a pull request."""
    return f"""Help a reviewer get up to speed on pull request #{pull_request_id} in repository "{repo_slug}".

Gather context using these tools, in order:
1. get_pull_request(repo_slug="{repo_slug}", pull_request_id="{pull_request_id}") — what the PR is about
2. get_pull_request_commits(repo_slug="{repo_slug}", pull_request_id="{pull_request_id}") — how it was built up
3. get_pull_request_diff(repo_slug="{repo_slug}", pull_request_id="{pull_request_id}") — the actual changes
4. get_pull_request_activity(repo_slug="{repo_slug}", pull_request_id="{pull_request_id}") — review history so far

Then orient the reviewer:
- **Context** — the goal and motivation of the PR
- **What changed** — the main changes, grouped logically
- **Review so far** — prior comments, approvals, requested changes
- **Where to focus** — the files or areas most worth careful review"""
