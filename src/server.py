"""MCP Server for Bitbucket API"""

import asyncio
import functools
import os
import sys
import json
import logging
from pathlib import Path
from typing import Optional, Dict, Any
from mcp.server.fastmcp import FastMCP
from .client import BitbucketClient, IssueTrackerDisabledError, DEFAULT_MAX_FILE_BYTES
from .utils.credentials import get_credentials
from .utils.transformers import (
    slim_repository, slim_repository_list, slim_tag_list,
    slim_pull_request, slim_pull_request_list, slim_pull_request_created,
    slim_status, slim_status_list,
    slim_commit, slim_commit_list,
    slim_source_list,
    slim_diffstat_entry, slim_diffstat_list,
    slim_comment, slim_comment_list,
    slim_commit_comment, slim_commit_comment_list,
    slim_activity_list,
    slim_pipeline_run, slim_pipeline_run_list,
    slim_pipeline_step_list,
    slim_pipeline_config,
    slim_pipeline_variable, slim_pipeline_variable_list,
    slim_pipeline_schedule, slim_pipeline_schedule_list,
    slim_pipeline_schedule_execution_list,
    slim_pipeline_cache_list,
    slim_reviewer_list,
    slim_task, slim_task_list,
    slim_issue, slim_issue_list,
    slim_issue_comment, slim_issue_comment_list,
)

# Configuration logging vers stderr uniquement (container-friendly)
logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


# ========== Tool Configuration ==========

def load_tools_config(config_path: Optional[str] = None) -> Dict[str, bool]:
    """
    Load tool configuration from a JSON file.

    Fallback chain (first wins):
    1. ``config_path`` argument passed directly to this function
    2. ``BITBUCKET_TOOLS_CONFIG`` environment variable
    3. Default path: ``configs/tools.json`` relative to the project root

    When the resolved path comes from an explicit source (arg or env var) and
    the file is missing or contains invalid JSON, a hard exception is raised.
    When falling back to the default path and it is missing, all tools are
    enabled and no exception is raised (fail-open, backward-compatible).

    Args:
        config_path: Optional explicit path to a tools config JSON file.

    Returns:
        Dictionary mapping tool names to their enabled status.

    Raises:
        FileNotFoundError: If an explicit config path does not exist.
        ValueError: If an explicit config file contains invalid JSON.
    """
    project_root = Path(__file__).parent.parent
    default_path = str(project_root / "configs" / "tools.json")

    env_config = os.getenv("BITBUCKET_TOOLS_CONFIG", "").strip() or None
    resolved_path = config_path or env_config or default_path
    config_file = Path(resolved_path).resolve()
    is_explicit = bool(config_path or env_config)
    source = "config_path" if config_path else "BITBUCKET_TOOLS_CONFIG"

    logger.info(f"Tools config source: {config_file}")

    enabled_tools = {}
    try:
        if config_file.exists():
            with open(config_file, 'r') as f:
                config = json.load(f)
            for category, tools in config.get("tools", {}).items():
                for tool_name, tool_config in tools.items():
                    enabled_tools[tool_name] = tool_config.get("enabled", True)
            logger.info(f"Enabled tools: {sum(enabled_tools.values())}/{len(enabled_tools)}")
        elif is_explicit:
            raise FileNotFoundError(f"Tools config not found ({source}={resolved_path})")
        else:
            logger.warning(f"Tool configuration file not found: {config_file}")
            logger.info("All tools will be enabled by default")
    except json.JSONDecodeError as e:
        if is_explicit:
            raise ValueError(f"Invalid JSON in tools config ({source}={config_file}): {e}")
        logger.error(f"Error loading tool configuration: {e}")
        logger.info("All tools will be enabled by default")
    except (FileNotFoundError, ValueError):
        raise
    except Exception as e:
        if is_explicit:
            raise
        logger.error(f"Error loading tool configuration: {e}")
        logger.info("All tools will be enabled by default")

    return enabled_tools


# Load configuration at startup
_enabled_tools = load_tools_config()


def is_tool_enabled(tool_name: str) -> bool:
    """
    Check if a tool is enabled in configuration.

    Args:
        tool_name: Name of the tool to check

    Returns:
        True if tool is enabled, False otherwise (defaults to True if not configured)
    """
    return _enabled_tools.get(tool_name, True)


def conditional_tool(structured_output: bool = True):
    """
    Decorator that conditionally registers a tool based on configuration.

    If the tool is enabled in configs/tools.json, it will be registered as an MCP tool.
    Otherwise, the function remains as a regular async function without MCP registration.

    Args:
        structured_output: If True, enable structured output for dict returns.
                          Returns proper JSON objects instead of serialized strings.
                          Defaults to True for better client experience.
    """
    def decorator(func):
        tool_name = func.__name__
        if is_tool_enabled(tool_name):
            logger.debug(f"Registering tool: {tool_name} (structured_output={structured_output})")
            return mcp.tool(structured_output=structured_output)(func)
        else:
            logger.info(f"Tool disabled by configuration: {tool_name}")
            return func
    return decorator


# Initialiser FastMCP
mcp = FastMCP("Bitbucket MCP Server")

# Client Bitbucket singleton
_bitbucket_client: Optional[BitbucketClient] = None


def get_client() -> BitbucketClient:
    """
    Get or create Bitbucket client singleton.

    Returns:
        BitbucketClient instance

    Raises:
        ValueError: If required environment variables are missing
    """
    global _bitbucket_client

    if _bitbucket_client is None:
        credentials = get_credentials()
        _bitbucket_client = BitbucketClient(
            credentials.username,
            credentials.token,
            credentials.workspace
        )
        logger.info(f"Bitbucket client initialized for workspace: {credentials.workspace}")

    return _bitbucket_client


# ========== Repository Tools ==========

@conditional_tool()
async def list_repositories(
    workspace: Optional[str] = None,
    name: Optional[str] = None,
    page_size: int = 30,
    max_pages: Optional[int] = 1
) -> Dict[str, Any]:
    """
    List repositories in workspace with pagination support.

    Args:
        workspace: Workspace name (optional, defaults to configured workspace)
        name: Filter by repository name (partial match supported)
        page_size: Items per page (default: 30)
        max_pages: Maximum pages to fetch (default: 1, max recommended: 10)

    Returns:
        Paginated list of repositories

    Note:
        Fetching more than 10 pages or 300 items will trigger a warning.
    """
    client = get_client()
    result = await client.list_repositories(workspace, name, page_size, max_pages)
    return slim_repository_list(result)


@conditional_tool()
async def get_repository(repo_slug: str, workspace: Optional[str] = None) -> Dict[str, Any]:
    """
    Get repository details.

    Args:
        repo_slug: Repository slug
        workspace: Workspace name (optional, defaults to configured workspace)

    Returns:
        Repository information
    """
    client = get_client()
    result = await client.get_repository(repo_slug, workspace)
    return slim_repository(result)


@conditional_tool()
async def get_repository_tags(
    repo_slug: str,
    workspace: Optional[str] = None,
    page_size: int = 10,
    max_pages: Optional[int] = 1
) -> Dict[str, Any]:
    """
    List repository tags ordered by most recent target date.

    Note: "target date" is the date of the tag's target commit, not the tag
    creation date — a tag placed on an old commit will not sort first.

    Args:
        repo_slug: Repository slug
        workspace: Workspace name (optional, defaults to configured workspace)
        page_size: Items per page (default: 10)
        max_pages: Maximum pages to fetch (default: 1, max recommended: 10)

    Returns:
        Paginated list of repository tags
    """
    client = get_client()
    result = await client.get_repository_tags(repo_slug, workspace, page_size, max_pages)
    return slim_tag_list(result)


# ========== Pull Request Tools ==========

@conditional_tool()
async def get_pull_requests(
    repo_slug: str,
    workspace: Optional[str] = None,
    state: str = "OPEN",
    page_size: int = 30,
    max_pages: Optional[int] = 1
) -> Dict[str, Any]:
    """
    Get pull requests for a repository with pagination support.

    Args:
        repo_slug: Repository slug
        workspace: Workspace name (optional, defaults to configured workspace)
        state: Pull request state (OPEN, MERGED, DECLINED, SUPERSEDED) (default: OPEN)
        page_size: Items per page (default: 30)
        max_pages: Maximum pages to fetch (default: 1, max recommended: 10)

    Returns:
        Paginated list of pull requests

    Note:
        Fetching more than 10 pages or 300 items will trigger a warning.
    """
    client = get_client()
    result = await client.get_pull_requests(repo_slug, workspace, state, page_size, max_pages)
    return slim_pull_request_list(result)


@conditional_tool()
async def get_pull_requests_pending_review(
    repo_slug: str,
    workspace: Optional[str] = None,
    page_size: int = 30,
    max_pages: Optional[int] = 1
) -> Dict[str, Any]:
    """
    Get open pull requests where the current user is a reviewer.

    Use this to find PRs that need your review attention.

    Args:
        repo_slug: Repository slug
        workspace: Workspace name (optional, defaults to configured workspace)
        page_size: Items per page (default: 30)
        max_pages: Maximum pages to fetch (default: 1, max recommended: 10)

    Returns:
        Paginated list of pull requests pending your review
    """
    client = get_client()
    result = await client.get_pull_requests_pending_review(
        repo_slug, workspace, page_size, max_pages
    )
    return slim_pull_request_list(result)


@conditional_tool()
async def get_pull_request(
    repo_slug: str,
    pull_request_id: str,
    workspace: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get details for a specific pull request.

    Args:
        repo_slug: Repository slug
        pull_request_id: Pull request ID
        workspace: Workspace name (optional, defaults to configured workspace)

    Returns:
        Pull request details with comment statistics:
        - comment_stats: Object containing:
          - total (int): Total number of comments
          - resolved (int): Number of resolved comments
          - unresolved (int): Number of unresolved comments
    """
    client = get_client()
    pr_data = await client.get_pull_request(repo_slug, pull_request_id, workspace)
    ws = workspace or client.workspace

    comment_stats = await client.get_pull_request_comment_stats(
        ws, repo_slug, pull_request_id
    )
    pr_data["comment_stats"] = comment_stats

    return slim_pull_request(pr_data)


@conditional_tool()
async def create_pull_request(
    repo_slug: str,
    title: str,
    description: str,
    source_branch: str,
    target_branch: str,
    workspace: Optional[str] = None,
    reviewers: Optional[list] = None,
    draft: bool = False
) -> Dict[str, Any]:
    """
    Create a new pull request.

    Args:
        repo_slug: Repository slug
        title: Pull request title
        description: Pull request description
        source_branch: Source branch name
        target_branch: Target branch name
        workspace: Workspace name (optional, defaults to configured workspace)
        reviewers: List of reviewer UUIDs (optional)
        draft: Whether to create the pull request as a draft (default: False)

    Returns:
        Created pull request details
    """
    client = get_client()
    result = await client.create_pull_request(
        repo_slug, title, description, source_branch, target_branch,
        workspace, reviewers, draft
    )
    return slim_pull_request_created(result)


@conditional_tool()
async def update_pull_request(
    repo_slug: str,
    pull_request_id: str,
    workspace: Optional[str] = None,
    title: Optional[str] = None,
    description: Optional[str] = None,
    reviewers: Optional[list] = None
) -> Dict[str, Any]:
    """
    Update a pull request.

    Args:
        repo_slug: Repository slug
        pull_request_id: Pull request ID
        workspace: Workspace name (optional, defaults to configured workspace)
        title: New pull request title (optional)
        description: New pull request description (optional)
        reviewers: Complete list of reviewer UUIDs to set on the PR (optional).
            WARNING: this REPLACES the entire reviewer list — include all existing reviewers
            you want to keep, plus any new ones. Use get_pull_request first to retrieve
            current reviewer UUIDs. Pass [] to clear all reviewers.

    Returns:
        Updated pull request details
    """
    client = get_client()
    result = await client.update_pull_request(
        repo_slug, pull_request_id, workspace, title, description, reviewers
    )
    return slim_pull_request(result)


@conditional_tool()
async def approve_pull_request(
    repo_slug: str,
    pull_request_id: str,
    workspace: Optional[str] = None
) -> Dict[str, Any]:
    """
    Approve a pull request.

    Args:
        repo_slug: Repository slug
        pull_request_id: Pull request ID
        workspace: Workspace name (optional, defaults to configured workspace)

    Returns:
        Approval details
    """
    client = get_client()
    return await client.approve_pull_request(repo_slug, pull_request_id, workspace)


@conditional_tool()
async def unapprove_pull_request(
    repo_slug: str,
    pull_request_id: str,
    workspace: Optional[str] = None
) -> str:
    """
    Remove approval from a pull request.

    Args:
        repo_slug: Repository slug
        pull_request_id: Pull request ID
        workspace: Workspace name (optional, defaults to configured workspace)

    Returns:
        Success message
    """
    client = get_client()
    await client.unapprove_pull_request(repo_slug, pull_request_id, workspace)
    return "Approval removed successfully"


@conditional_tool()
async def request_changes_pull_request(
    repo_slug: str,
    pull_request_id: str,
    workspace: Optional[str] = None
) -> Dict[str, Any]:
    """
    Request changes on a pull request (sets reviewer status to 'needs work').

    Args:
        repo_slug: Repository slug
        pull_request_id: Pull request ID
        workspace: Workspace name (optional, defaults to configured workspace)

    Returns:
        Participant details with updated state
    """
    client = get_client()
    return await client.request_changes_pull_request(repo_slug, pull_request_id, workspace)


@conditional_tool()
async def unrequest_changes_pull_request(
    repo_slug: str,
    pull_request_id: str,
    workspace: Optional[str] = None
) -> str:
    """
    Remove 'request changes' status from a pull request.

    Args:
        repo_slug: Repository slug
        pull_request_id: Pull request ID
        workspace: Workspace name (optional, defaults to configured workspace)

    Returns:
        Success message
    """
    client = get_client()
    await client.unrequest_changes_pull_request(repo_slug, pull_request_id, workspace)
    return "Request changes removed successfully"


@conditional_tool()
async def decline_pull_request(
    repo_slug: str,
    pull_request_id: str,
    workspace: Optional[str] = None,
    message: Optional[str] = None
) -> Dict[str, Any]:
    """
    Decline a pull request.

    Args:
        repo_slug: Repository slug
        pull_request_id: Pull request ID
        workspace: Workspace name (optional, defaults to configured workspace)
        message: Reason for declining (optional)

    Returns:
        Updated pull request details
    """
    client = get_client()
    result = await client.decline_pull_request(
        repo_slug, pull_request_id, workspace, message
    )
    return slim_pull_request_created(result)


@conditional_tool()
async def merge_pull_request(
    repo_slug: str,
    pull_request_id: str,
    workspace: Optional[str] = None,
    message: Optional[str] = None,
    strategy: str = "merge_commit"
) -> Dict[str, Any]:
    """
    Merge a pull request.

    Args:
        repo_slug: Repository slug
        pull_request_id: Pull request ID
        workspace: Workspace name (optional, defaults to configured workspace)
        message: Merge commit message (optional)
        strategy: Merge strategy (merge_commit, squash, fast_forward) (default: merge_commit)

    Returns:
        Merged pull request details
    """
    client = get_client()
    result = await client.merge_pull_request(
        repo_slug, pull_request_id, workspace, message, strategy
    )
    return slim_pull_request_created(result)


# ========== Pull Request Comment Tools ==========

def _enrich_comment_with_resolution(comment: Dict[str, Any]) -> Dict[str, Any]:
    """
    Enrich a comment with resolution status fields.

    Returns a new dict (does not mutate the input).

    Args:
        comment: Comment object from API

    Returns:
        New dict with added fields: is_resolved, resolved_by, resolved_on
    """
    resolution = comment.get("resolution")
    return {
        **comment,
        "is_resolved": resolution is not None,
        "resolved_by": resolution.get("user", {}).get("display_name") if resolution else None,
        "resolved_on": resolution.get("created_on") if resolution else None,
    }


@conditional_tool()
async def get_pull_request_comments(
    repo_slug: str,
    pull_request_id: str,
    workspace: Optional[str] = None,
    unresolved_only: bool = False,
    page_size: int = 10,
    max_pages: Optional[int] = 1
) -> Dict[str, Any]:
    """
    List comments on a pull request with pagination support.

    Args:
        repo_slug: Repository slug
        pull_request_id: Pull request ID
        workspace: Workspace name (optional, defaults to configured workspace)
        unresolved_only: If true, returns only unresolved comments (default: False)
        page_size: Items per page (default: 10, max recommended: 100)
        max_pages: Maximum pages to fetch (default: 1, max recommended: 10)

    Returns:
        List of comments enriched with resolution status:
        - is_resolved (bool): True if comment is resolved
        - resolved_by (string or null): User display name who resolved the comment
        - resolved_on (string or null): Timestamp when comment was resolved

    Note:
        Fetching more than 10 pages or 300 items will trigger a warning.
    """
    client = get_client()
    result = await client.get_pull_request_comments(
        repo_slug, pull_request_id, workspace, page_size, max_pages, unresolved_only
    )

    if "values" in result:
        comments = result["values"]
        if unresolved_only:
            comments = [c for c in comments if not c.get("resolution")]
        result["values"] = [_enrich_comment_with_resolution(c) for c in comments]

    return slim_comment_list(result)


@conditional_tool()
async def add_pull_request_comment(
    repo_slug: str,
    pull_request_id: str,
    content: str,
    workspace: Optional[str] = None,
    inline_path: Optional[str] = None,
    inline_from: Optional[int] = None,
    inline_to: Optional[int] = None,
    pending: bool = False,
    parent_id: Optional[int] = None
) -> Dict[str, Any]:
    """
    Add a comment to a pull request (general or inline).

    Args:
        repo_slug: Repository slug
        pull_request_id: Pull request ID
        content: Comment content in markdown format
        workspace: Workspace name (optional, defaults to configured workspace)
        inline_path: Path to the file in the repository (for inline comments)
        inline_from: Line number in the old version of the file (for deleted or modified lines)
        inline_to: Line number in the new version of the file (for added or modified lines)
        pending: Whether to create this comment as a pending comment (draft state) (default: False)
        parent_id: ID of the comment to reply to (creates a threaded reply)

    Returns:
        Created comment details
    """
    client = get_client()
    result = await client.add_pull_request_comment(
        repo_slug, pull_request_id, content, workspace,
        inline_path, inline_from, inline_to, pending, parent_id=parent_id
    )
    return slim_comment(_enrich_comment_with_resolution(result))


@conditional_tool()
async def get_pull_request_comment(
    repo_slug: str,
    pull_request_id: str,
    comment_id: str,
    workspace: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get a specific comment on a pull request.

    Args:
        repo_slug: Repository slug
        pull_request_id: Pull request ID
        comment_id: Comment ID
        workspace: Workspace name (optional, defaults to configured workspace)

    Returns:
        Comment details with resolution status
    """
    client = get_client()
    result = await client.get_pull_request_comment(
        repo_slug, pull_request_id, comment_id, workspace
    )
    return slim_comment(_enrich_comment_with_resolution(result))


@conditional_tool()
async def update_pull_request_comment(
    repo_slug: str,
    pull_request_id: str,
    comment_id: str,
    content: str,
    workspace: Optional[str] = None
) -> Dict[str, Any]:
    """
    Update a comment on a pull request.

    Args:
        repo_slug: Repository slug
        pull_request_id: Pull request ID
        comment_id: Comment ID
        content: New comment content in markdown format
        workspace: Workspace name (optional, defaults to configured workspace)

    Returns:
        Updated comment details
    """
    client = get_client()
    result = await client.update_pull_request_comment(
        repo_slug, pull_request_id, comment_id, content, workspace
    )
    return slim_comment(_enrich_comment_with_resolution(result))


@conditional_tool()
async def delete_pull_request_comment(
    repo_slug: str,
    pull_request_id: str,
    comment_id: str,
    workspace: Optional[str] = None
) -> str:
    """
    Delete a comment on a pull request.

    Args:
        repo_slug: Repository slug
        pull_request_id: Pull request ID
        comment_id: Comment ID
        workspace: Workspace name (optional, defaults to configured workspace)

    Returns:
        Success message
    """
    client = get_client()
    await client.delete_pull_request_comment(
        repo_slug, pull_request_id, comment_id, workspace
    )
    return "Comment deleted successfully"


@conditional_tool()
async def resolve_pull_request_comment(
    repo_slug: str,
    pull_request_id: str,
    comment_id: str,
    workspace: Optional[str] = None
) -> Dict[str, Any]:
    """
    Resolve a comment on a pull request.

    Args:
        repo_slug: Repository slug
        pull_request_id: Pull request ID
        comment_id: Comment ID
        workspace: Workspace name (optional, defaults to configured workspace)

    Returns:
        Resolution details
    """
    client = get_client()
    return await client.resolve_pull_request_comment(
        repo_slug, pull_request_id, comment_id, workspace
    )


@conditional_tool()
async def reopen_pull_request_comment(
    repo_slug: str,
    pull_request_id: str,
    comment_id: str,
    workspace: Optional[str] = None
) -> str:
    """
    Reopen (unresolve) a comment on a pull request.

    Args:
        repo_slug: Repository slug
        pull_request_id: Pull request ID
        comment_id: Comment ID
        workspace: Workspace name (optional, defaults to configured workspace)

    Returns:
        Success message
    """
    client = get_client()
    await client.reopen_pull_request_comment(
        repo_slug, pull_request_id, comment_id, workspace
    )
    return "Comment reopened successfully"


# ========== PR Task Tools ==========

@conditional_tool()
async def get_pull_request_tasks(
    repo_slug: str,
    pull_request_id: str,
    workspace: Optional[str] = None,
    page_size: int = 10,
    max_pages: Optional[int] = 1
) -> Dict[str, Any]:
    """
    List tasks on a pull request with pagination support.

    Args:
        repo_slug: Repository slug
        pull_request_id: Pull request ID
        workspace: Workspace name (optional, defaults to configured workspace)
        page_size: Items per page (default: 10, max recommended: 100)
        max_pages: Maximum pages to fetch (default: 1, max recommended: 10)

    Returns:
        Paginated list of tasks with state, content, creator info
    """
    client = get_client()
    result = await client.get_pull_request_tasks(
        repo_slug, pull_request_id, workspace, page_size, max_pages
    )
    return slim_task_list(result)


@conditional_tool()
async def get_pull_request_task(
    repo_slug: str,
    pull_request_id: str,
    task_id: str,
    workspace: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get a specific task on a pull request.

    Args:
        repo_slug: Repository slug
        pull_request_id: Pull request ID
        task_id: Task ID
        workspace: Workspace name (optional, defaults to configured workspace)

    Returns:
        Task details with state, content, creator, resolution info
    """
    client = get_client()
    result = await client.get_pull_request_task(
        repo_slug, pull_request_id, task_id, workspace
    )
    return slim_task(result)


@conditional_tool()
async def create_pull_request_task(
    repo_slug: str,
    pull_request_id: str,
    content: str,
    comment_id: Optional[int] = None,
    workspace: Optional[str] = None
) -> Dict[str, Any]:
    """
    Create a task on a pull request, optionally linked to a specific comment.

    Args:
        repo_slug: Repository slug
        pull_request_id: Pull request ID
        content: Task content in markdown format
        comment_id: Optional comment ID to link the task to a specific comment
        workspace: Workspace name (optional, defaults to configured workspace)

    Returns:
        Created task details
    """
    client = get_client()
    result = await client.create_pull_request_task(
        repo_slug, pull_request_id, content, comment_id, workspace
    )
    return slim_task(result)


@conditional_tool()
async def update_pull_request_task(
    repo_slug: str,
    pull_request_id: str,
    task_id: str,
    content: Optional[str] = None,
    state: Optional[str] = None,
    workspace: Optional[str] = None
) -> Dict[str, Any]:
    """
    Update a pull request task (content and/or state).

    Args:
        repo_slug: Repository slug
        pull_request_id: Pull request ID
        task_id: Task ID
        content: New task content in markdown format (optional)
        state: New task state: UNRESOLVED or RESOLVED (optional)
        workspace: Workspace name (optional, defaults to configured workspace)

    Returns:
        Updated task details
    """
    if state is not None and state not in ("UNRESOLVED", "RESOLVED"):
        raise ValueError(f"Invalid state '{state}'. Must be 'UNRESOLVED' or 'RESOLVED'")
    if content is None and state is None:
        raise ValueError("At least one of 'content' or 'state' must be provided")
    client = get_client()
    result = await client.update_pull_request_task(
        repo_slug, pull_request_id, task_id, content, state, workspace
    )
    return slim_task(result)


@conditional_tool()
async def delete_pull_request_task(
    repo_slug: str,
    pull_request_id: str,
    task_id: str,
    workspace: Optional[str] = None
) -> str:
    """
    Delete a task on a pull request.

    Args:
        repo_slug: Repository slug
        pull_request_id: Pull request ID
        task_id: Task ID
        workspace: Workspace name (optional, defaults to configured workspace)

    Returns:
        Success message
    """
    client = get_client()
    await client.delete_pull_request_task(
        repo_slug, pull_request_id, task_id, workspace
    )
    return "Task deleted successfully"


@conditional_tool()
async def get_pull_request_diff(
    repo_slug: str,
    pull_request_id: str,
    workspace: Optional[str] = None,
    path: Optional[str] = None
) -> str:
    """
    Get diff for a pull request.

    Args:
        repo_slug: Repository slug
        pull_request_id: Pull request ID
        workspace: Workspace name (optional, defaults to configured workspace)
        path: Filter diff to a specific file path to reduce token usage (optional).
              Example: "src/middlewares/authorizationMiddleware.ts"

    Returns:
        Unified diff as string
    """
    client = get_client()
    return await client.get_pull_request_diff(repo_slug, pull_request_id, workspace, path)


@conditional_tool()
async def get_pull_request_patch(
    repo_slug: str,
    pull_request_id: str,
    workspace: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get the patch for a pull request (git format-patch style).

    The patch includes full commit metadata and can be applied with git am.
    Use get_pull_request_diff for a simpler unified diff.

    Args:
        repo_slug: Repository slug
        pull_request_id: Pull request ID
        workspace: Workspace name (optional, defaults to configured workspace)

    Returns:
        Dictionary with patch content as string
    """
    client = get_client()
    return await client.get_pull_request_patch(repo_slug, pull_request_id, workspace)


@conditional_tool()
async def get_pull_request_activity(
    repo_slug: str,
    pull_request_id: str,
    workspace: Optional[str] = None,
    page_size: int = 10,
    max_pages: Optional[int] = 1
) -> Dict[str, Any]:
    """
    Get activity log for a pull request with pagination support.

    Args:
        repo_slug: Repository slug
        pull_request_id: Pull request ID
        workspace: Workspace name (optional, defaults to configured workspace)
        page_size: Items per page (default: 10, max recommended: 100)
        max_pages: Maximum pages to fetch (default: 1, max recommended: 10)

    Returns:
        Activity log with all events. Comment objects enriched with resolution status:
        - is_resolved (bool): True if comment is resolved
        - resolved_by (string or null): User display name who resolved the comment
        - resolved_on (string or null): Timestamp when comment was resolved

    Note:
        Fetching more than 10 pages or 300 items will trigger a warning.
    """
    client = get_client()
    result = await client.get_pull_request_activity(
        repo_slug, pull_request_id, workspace, page_size, max_pages
    )

    if "values" in result:
        for activity in result["values"]:
            if "comment" in activity:
                activity["comment"] = _enrich_comment_with_resolution(activity["comment"])

    return slim_activity_list(result)


@conditional_tool()
async def get_pull_request_commits(
    repo_slug: str,
    pull_request_id: str,
    workspace: Optional[str] = None,
    page_size: int = 10,
    max_pages: Optional[int] = 1
) -> Dict[str, Any]:
    """
    Get commits on a pull request with pagination support.

    Args:
        repo_slug: Repository slug
        pull_request_id: Pull request ID
        workspace: Workspace name (optional, defaults to configured workspace)
        page_size: Items per page (default: 10, max recommended: 100)
        max_pages: Maximum pages to fetch (default: 1, max recommended: 10)

    Returns:
        List of commits

    Note:
        Fetching more than 10 pages or 300 items will trigger a warning.
    """
    client = get_client()
    result = await client.get_pull_request_commits(
        repo_slug, pull_request_id, workspace, page_size, max_pages
    )
    return slim_commit_list(result)


@conditional_tool()
async def get_pull_request_statuses(
    repo_slug: str,
    pull_request_id: str,
    workspace: Optional[str] = None,
    page_size: int = 10,
    max_pages: Optional[int] = 1
) -> Dict[str, Any]:
    """
    Get build/CI statuses for a pull request with pagination support.

    Args:
        repo_slug: Repository slug
        pull_request_id: Pull request ID
        workspace: Workspace name (optional, defaults to configured workspace)
        page_size: Items per page (default: 10, max recommended: 100)
        max_pages: Maximum pages to fetch (default: 1, max recommended: 10)

    Returns:
        List of build statuses (Jenkins, CI/CD, tests, etc.)
        Each status contains:
        - state: SUCCESSFUL, FAILED, INPROGRESS, STOPPED
        - key: Unique identifier for the build
        - name: Build name/description
        - url: Link to the build details
        - created_on: Timestamp of the status

    Note:
        Fetching more than 10 pages or 300 items will trigger a warning.
    """
    client = get_client()
    result = await client.get_pull_request_statuses(
        repo_slug, pull_request_id, workspace, page_size, max_pages
    )
    return slim_status_list(result)


@conditional_tool()
async def get_commit_statuses(
    repo_slug: str,
    commit_hash: str,
    workspace: Optional[str] = None,
    page_size: int = 10,
    max_pages: Optional[int] = 1
) -> Dict[str, Any]:
    """
    Get build/CI statuses for a specific commit (e.g. Jenkins, CI/CD).

    Use this to check the Jenkins build status for any branch commit
    without needing to create a Pull Request first.

    Args:
        repo_slug: Repository slug
        commit_hash: Commit hash (full or short, e.g. "abc1234")
        workspace: Workspace name (optional, defaults to configured workspace)
        page_size: Items per page (default: 10, max recommended: 100)
        max_pages: Maximum pages to fetch (default: 1, max recommended: 10)

    Returns:
        List of build statuses (Jenkins, CI/CD, tests, etc.)
        Each status contains:
        - state: SUCCESSFUL, FAILED, INPROGRESS, STOPPED
        - key: Unique identifier for the build
        - name: Build name/description
        - description: Build result description
        - url: Link to the Jenkins build details
        - created_on: Timestamp of the status
        - updated_on: Timestamp of last update

    Note:
        Requires Jenkins Bitbucket Build Status Notifier plugin to post statuses.
        Fetching more than 10 pages or 300 items will trigger a warning.
    """
    client = get_client()
    result = await client.get_commit_statuses(
        repo_slug, commit_hash, workspace, page_size, max_pages
    )
    return slim_status_list(result)


@conditional_tool()
async def get_pull_request_diffstat(
    repo_slug: str,
    pull_request_id: str,
    workspace: Optional[str] = None,
    page_size: int = 10,
    max_pages: Optional[int] = 1
) -> Dict[str, Any]:
    """
    Get file modification statistics for a pull request with pagination support.

    Args:
        repo_slug: Repository slug
        pull_request_id: Pull request ID
        workspace: Workspace name (optional, defaults to configured workspace)
        page_size: Items per page (default: 10, max recommended: 100)
        max_pages: Maximum pages to fetch (default: 1, max recommended: 10)

    Returns:
        Statistics with lines added/removed per file
        Each file entry contains:
        - status: modified, added, removed, renamed
        - lines_added: Number of lines added
        - lines_removed: Number of lines removed
        - new.path: File path after changes

    Note:
        Fetching more than 10 pages or 300 items will trigger a warning.
    """
    client = get_client()
    result = await client.get_pull_request_diffstat(
        repo_slug, pull_request_id, workspace, page_size, max_pages
    )
    return slim_diffstat_list(result)


# ========== Pipeline Tools ==========

@conditional_tool()
async def list_pipeline_runs(
    repo_slug: str,
    workspace: Optional[str] = None,
    status: Optional[str] = None,
    target_branch: Optional[str] = None,
    page_size: int = 30,
    max_pages: Optional[int] = 1
) -> Dict[str, Any]:
    """
    List pipeline runs for a repository with pagination support.

    Args:
        repo_slug: Repository slug
        workspace: Workspace name (optional, defaults to configured workspace)
        status: Filter pipelines by status (PENDING, IN_PROGRESS, SUCCESSFUL, FAILED, ERROR, STOPPED)
        target_branch: Filter pipelines by target branch
        page_size: Items per page (default: 30)
        max_pages: Maximum pages to fetch (default: 1, max recommended: 10)

    Returns:
        List of pipeline runs

    Note:
        Fetching more than 10 pages or 300 items will trigger a warning.
    """
    client = get_client()
    result = await client.list_pipeline_runs(
        repo_slug, workspace, status, target_branch, page_size, max_pages
    )
    return slim_pipeline_run_list(result)


@conditional_tool()
async def get_pipeline_run(
    repo_slug: str,
    pipeline_uuid: str,
    workspace: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get details for a specific pipeline run.

    Args:
        repo_slug: Repository slug
        pipeline_uuid: Pipeline UUID
        workspace: Workspace name (optional, defaults to configured workspace)

    Returns:
        Pipeline run details
    """
    client = get_client()
    result = await client.get_pipeline_run(repo_slug, pipeline_uuid, workspace)
    return slim_pipeline_run(result)


@conditional_tool()
async def get_pipeline_steps(
    repo_slug: str,
    pipeline_uuid: str,
    workspace: Optional[str] = None,
    page_size: int = 10,
    max_pages: Optional[int] = 1
) -> Dict[str, Any]:
    """
    List steps for a pipeline run with pagination support.

    Args:
        repo_slug: Repository slug
        pipeline_uuid: Pipeline UUID
        workspace: Workspace name (optional, defaults to configured workspace)
        page_size: Items per page (default: 10, max recommended: 100)
        max_pages: Maximum pages to fetch (default: 1, max recommended: 10)

    Returns:
        List of pipeline steps

    Note:
        Fetching more than 10 pages or 300 items will trigger a warning.
    """
    client = get_client()
    result = await client.get_pipeline_steps(
        repo_slug, pipeline_uuid, workspace, page_size, max_pages
    )
    return slim_pipeline_step_list(result)


@conditional_tool()
async def get_pipeline_step_logs(
    repo_slug: str,
    pipeline_uuid: str,
    step_uuid: str,
    workspace: Optional[str] = None
) -> str:
    """
    Get logs for a specific pipeline step.

    Args:
        repo_slug: Repository slug
        pipeline_uuid: Pipeline UUID
        step_uuid: Step UUID
        workspace: Workspace name (optional, defaults to configured workspace)

    Returns:
        Step logs as string
    """
    client = get_client()
    return await client.get_pipeline_step_logs(
        repo_slug, pipeline_uuid, step_uuid, workspace
    )


@conditional_tool()
async def run_pipeline(
    repo_slug: str,
    branch: str,
    workspace: Optional[str] = None
) -> Dict[str, Any]:
    """
    Trigger a new pipeline run on a branch.

    Args:
        repo_slug: Repository slug
        branch: Branch name to run the pipeline on
        workspace: Workspace name (optional, defaults to configured workspace)

    Returns:
        Created pipeline run details
    """
    client = get_client()
    result = await client.run_pipeline(repo_slug, branch, workspace)
    return slim_pipeline_run(result)


@conditional_tool()
async def stop_pipeline(
    repo_slug: str,
    pipeline_uuid: str,
    workspace: Optional[str] = None
) -> str:
    """
    Stop a running pipeline.

    Args:
        repo_slug: Repository slug
        pipeline_uuid: Pipeline UUID to stop
        workspace: Workspace name (optional, defaults to configured workspace)

    Returns:
        Success message
    """
    client = get_client()
    await client.stop_pipeline(repo_slug, pipeline_uuid, workspace)
    return "Pipeline stopped successfully"


# ========== Default Reviewers Tools ==========

@conditional_tool()
async def get_effective_default_reviewers(
    repo_slug: str,
    workspace: Optional[str] = None,
    page_size: int = 30,
    max_pages: Optional[int] = 1
) -> Dict[str, Any]:
    """
    Get effective default reviewers for a repository.

    Args:
        repo_slug: Repository slug
        workspace: Workspace name (optional, defaults to configured workspace)
        page_size: Items per page (default: 30)
        max_pages: Maximum pages to fetch (default: 1, max recommended: 10)

    Returns:
        List of default reviewers for the repository

    Note:
        Fetching more than 10 pages or 300 items will trigger a warning.
    """
    client = get_client()
    result = await client.get_effective_default_reviewers(
        repo_slug, workspace, page_size, max_pages
    )
    return slim_reviewer_list(result)


# ========== Draft PR Tools ==========

@conditional_tool()
async def create_draft_pull_request(
    repo_slug: str,
    title: str,
    description: str,
    source_branch: str,
    target_branch: str,
    workspace: Optional[str] = None,
    reviewers: Optional[list] = None
) -> Dict[str, Any]:
    """
    Create a new pull request as draft. Draft PRs are not ready for review.

    Args:
        repo_slug: Repository slug
        title: Pull request title
        description: Pull request description
        source_branch: Source branch name
        target_branch: Target branch name
        workspace: Workspace name (optional, defaults to configured workspace)
        reviewers: List of reviewer UUIDs (optional)

    Returns:
        Created draft pull request details
    """
    client = get_client()
    result = await client.create_pull_request(
        repo_slug, title, description, source_branch, target_branch,
        workspace, reviewers, draft=True
    )
    return slim_pull_request_created(result)


@conditional_tool()
async def publish_draft_pull_request(
    repo_slug: str,
    pull_request_id: str,
    workspace: Optional[str] = None
) -> Dict[str, Any]:
    """
    Publish a draft pull request (convert DRAFT to OPEN).

    Args:
        repo_slug: Repository slug
        pull_request_id: Pull request ID
        workspace: Workspace name (optional, defaults to configured workspace)

    Returns:
        Updated pull request details
    """
    client = get_client()
    result = await client.publish_draft_pull_request(
        repo_slug, pull_request_id, workspace
    )
    return slim_pull_request_created(result)


@conditional_tool()
async def convert_pull_request_to_draft(
    repo_slug: str,
    pull_request_id: str,
    workspace: Optional[str] = None
) -> Dict[str, Any]:
    """
    Convert an open pull request to draft state.

    Note: This operation is NOT supported by the Bitbucket Cloud API.
    Bitbucket only supports creating PRs as drafts or publishing drafts to open.
    Converting an open PR back to draft is only available in the Bitbucket web UI.

    Args:
        repo_slug: Repository slug
        pull_request_id: Pull request ID
        workspace: Workspace name (optional, defaults to configured workspace)

    Returns:
        Error message explaining the limitation
    """
    return {
        "error": "Not supported by Bitbucket API",
        "message": "Converting an open pull request to draft is not supported by the Bitbucket Cloud REST API. "
                   "This operation is only available in the Bitbucket web UI. "
                   "To work with drafts, create a new PR as draft using create_draft_pull_request.",
        "pr_id": pull_request_id,
        "repo_slug": repo_slug
    }


# ========== Batch Review Tools ==========

@conditional_tool()
async def submit_pull_request_batch_review(
    repo_slug: str,
    pull_request_id: str,
    comments: list,
    review_action: str = "comment_only",
    review_message: Optional[str] = None,
    workspace: Optional[str] = None
) -> Dict[str, Any]:
    """
    Submit a batch review on a pull request: post multiple comments and optionally approve or request changes.

    Note: Bitbucket API does not support pending/draft comments in batch. Each comment is posted immediately.

    Args:
        repo_slug: Repository slug
        pull_request_id: Pull request ID
        comments: List of comment objects. Each comment has:
            - content (str, required): Comment text in markdown
            - inline (dict, optional): For inline comments: {"path": str, "to": int, "from": int}
        review_action: Action after posting comments: "approve", "request_changes", or "comment_only" (default: "comment_only")
        review_message: General review message posted as a top-level comment (optional)
        workspace: Workspace name (optional, defaults to configured workspace)

    Returns:
        Summary with comments_posted count, action taken, and PR details
    """
    if review_action not in ("approve", "request_changes", "comment_only"):
        raise ValueError(f"Invalid review_action '{review_action}'. Must be 'approve', 'request_changes', or 'comment_only'")

    client = get_client()
    comments_posted = 0
    failed_comments = []

    # Post review message as top-level comment if provided
    if review_message:
        try:
            await client.add_pull_request_comment(
                repo_slug, pull_request_id, review_message, workspace
            )
            comments_posted += 1
        except Exception as e:
            failed_comments.append({"index": "review_message", "error": str(e)})

    # Post each comment sequentially (best-effort)
    for i, comment in enumerate(comments):
        content = comment.get("content", "")
        inline = comment.get("inline")

        inline_path = None
        inline_from = None
        inline_to = None
        if inline:
            inline_path = inline.get("path")
            inline_from = inline.get("from")
            inline_to = inline.get("to")

        try:
            await client.add_pull_request_comment(
                repo_slug, pull_request_id, content, workspace,
                inline_path=inline_path, inline_from=inline_from, inline_to=inline_to
            )
            comments_posted += 1
        except Exception as e:
            failed_comments.append({"index": i, "error": str(e)})

    # Execute review action
    if review_action == "approve":
        await client.approve_pull_request(repo_slug, pull_request_id, workspace)
    elif review_action == "request_changes":
        await client.request_changes_pull_request(repo_slug, pull_request_id, workspace)

    # Get updated PR data
    pr_data = await client.get_pull_request(repo_slug, pull_request_id, workspace)

    result = {
        "comments_posted": comments_posted,
        "action": review_action,
        "pr": slim_pull_request(pr_data)
    }
    if failed_comments:
        result["failed_comments"] = failed_comments
        result["partial_failure"] = True

    return result


# ========== Review Summary & Reviewer Suggestion Tools ==========

@conditional_tool()
async def get_pull_request_review_summary(
    repo_slug: str,
    pull_request_id: str,
    workspace: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get a comprehensive review summary for a pull request.

    Fetches PR details first, then aggregates diffstat, unresolved comments,
    and CI statuses in parallel for efficient AI-assisted code review.

    Args:
        repo_slug: Repository slug
        pull_request_id: Pull request ID
        workspace: Workspace name (optional, defaults to configured workspace)

    Returns:
        Structured summary with pr details, diffstat, unresolved comments,
        CI statuses, and review readiness assessment.
        review_readiness: merged | declined | draft | ci_failing | ci_pending |
                          has_unresolved_comments | ready
    """
    client = get_client()

    # Fetch PR first (reused by diffstat to avoid a redundant API call)
    pr_data = await client.get_pull_request(repo_slug, pull_request_id, workspace)

    # Parallel fetch: diffstat (reusing pr_data), unresolved comments, CI statuses
    diffstat_data, comments_data, statuses_data = await asyncio.gather(
        client.get_pull_request_diffstat(repo_slug, pull_request_id, workspace, page_size=100, max_pages=5, pr_data=pr_data),
        client.get_pull_request_comments(repo_slug, pull_request_id, workspace, page_size=100, max_pages=5, unresolved_only=True),
        client.get_pull_request_statuses(repo_slug, pull_request_id, workspace, page_size=100, max_pages=5),
    )

    diffstat_values = diffstat_data.get("values", [])
    total_added = sum(f.get("lines_added", 0) for f in diffstat_values)
    total_removed = sum(f.get("lines_removed", 0) for f in diffstat_values)
    diffstat_summary = {
        "files_changed": len(diffstat_values),
        "lines_added": total_added,
        "lines_removed": total_removed,
        "files": [slim_diffstat_entry(f) for f in diffstat_values]
    }

    # Client-side filter: keep only unresolved comments (resolution=null)
    unresolved_comments = [
        slim_comment(_enrich_comment_with_resolution(c))
        for c in comments_data.get("values", [])
        if not c.get("resolution")
    ]

    ci_statuses = [slim_status(s) for s in statuses_data.get("values", [])]

    pr_state = pr_data.get("state")
    is_draft = pr_data.get("draft") is True
    has_unresolved = len(unresolved_comments) > 0
    ci_failing = any(s.get("state") in ("FAILED", "ERROR", "STOPPED") for s in ci_statuses)
    ci_pending = any(s.get("state") == "INPROGRESS" for s in ci_statuses)

    if pr_state in ("MERGED", "DECLINED"):
        review_readiness = pr_state.lower()
    elif is_draft:
        review_readiness = "draft"
    elif ci_failing:
        review_readiness = "ci_failing"
    elif ci_pending:
        review_readiness = "ci_pending"
    elif has_unresolved:
        review_readiness = "has_unresolved_comments"
    else:
        review_readiness = "ready"

    return {
        "pr": slim_pull_request(pr_data),
        "diffstat": diffstat_summary,
        "unresolved_comments": unresolved_comments,
        "ci_statuses": ci_statuses,
        "review_readiness": review_readiness
    }


@conditional_tool()
async def suggest_pull_request_reviewers(
    repo_slug: str,
    pull_request_id: str,
    max_suggestions: int = 5,
    workspace: Optional[str] = None
) -> Dict[str, Any]:
    """
    Suggest reviewers for a pull request based on default reviewers and recent PR history.

    Combines default reviewers with frequent approvers from recently merged PRs to
    suggest the most relevant reviewers.

    Args:
        repo_slug: Repository slug
        pull_request_id: Pull request ID
        max_suggestions: Maximum number of reviewer suggestions (default: 5)
        workspace: Workspace name (optional, defaults to configured workspace)

    Returns:
        Suggested reviewers with scores and reasons, already-assigned reviewers, and data sources
    """
    client = get_client()

    pr_data, default_reviewers_data, recent_prs_data = await asyncio.gather(
        client.get_pull_request(repo_slug, pull_request_id, workspace),
        client.get_effective_default_reviewers(repo_slug, workspace, page_size=30, max_pages=1),
        client.get_pull_requests(repo_slug, workspace, state="MERGED", limit=20, max_pages=1),
    )

    pr_author = pr_data.get("author", {}).get("uuid")

    already_assigned = [
        {
            "display_name": r.get("display_name") or r.get("user", {}).get("display_name"),
            "uuid": r.get("uuid") or r.get("user", {}).get("uuid"),
        }
        for r in pr_data.get("reviewers", [])
    ]
    assigned_uuids = {r.get("uuid") for r in already_assigned}

    reviewer_scores = {}
    for r in default_reviewers_data.get("values", []):
        user = r.get("user", {})
        uuid = user.get("uuid")
        if uuid and uuid != pr_author:
            reviewer_scores[uuid] = {
                "account_id": uuid,
                "display_name": user.get("display_name"),
                "score": 10,
                "reason": "default_reviewer"
            }

    approver_counts = {}
    for pr in recent_prs_data.get("values", []):
        for participant in pr.get("participants", []):
            if participant.get("approved"):
                user = participant.get("user", {})
                uuid = user.get("uuid")
                if uuid and uuid != pr_author:
                    if uuid not in approver_counts:
                        approver_counts[uuid] = {
                            "display_name": user.get("display_name"),
                            "count": 0
                        }
                    approver_counts[uuid]["count"] += 1

    for uuid, data in approver_counts.items():
        if uuid in reviewer_scores:
            reviewer_scores[uuid]["score"] += data["count"]
            reviewer_scores[uuid]["reason"] = "default_reviewer+frequent_approver"
        else:
            reviewer_scores[uuid] = {
                "account_id": uuid,
                "display_name": data["display_name"],
                "score": data["count"],
                "reason": "frequent_approver"
            }

    suggestions = sorted(
        [r for r in reviewer_scores.values() if r["account_id"] not in assigned_uuids],
        key=lambda x: x["score"],
        reverse=True
    )[:max_suggestions]

    return {
        "suggested_reviewers": suggestions,
        "already_assigned": already_assigned,
        "source": {
            "default_reviewers": len(default_reviewers_data.get("values", [])),
            "historical_approvers": len(approver_counts)
        }
    }


# ========== Issue Tracker Tools ==========

def _handle_issue_tracker(func):
    """Convert IssueTrackerDisabledError into a structured error dict.

    The Bitbucket issue tracker is opt-in per repository. When it is disabled, the
    API returns 404; rather than surface a raw HTTP error, issue tools return a
    clear structured payload so LLM clients can react gracefully.

    functools.wraps is required so FastMCP rebuilds the tool schema from the
    wrapped function's signature.
    """
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except IssueTrackerDisabledError as exc:
            return {
                "error": "issue_tracker_disabled",
                "message": str(exc),
                "workspace": exc.workspace,
                "repo_slug": exc.repo_slug,
            }
    return wrapper


@conditional_tool()
@_handle_issue_tracker
async def list_issues(
    repo_slug: str,
    workspace: Optional[str] = None,
    state: Optional[str] = None,
    kind: Optional[str] = None,
    priority: Optional[str] = None,
    assignee: Optional[str] = None,
    q: Optional[str] = None,
    sort: str = "-created_on",
    page_size: int = 20,
    max_pages: Optional[int] = 1,
    max_items: Optional[int] = None,
) -> Dict[str, Any]:
    """
    List issues in a repository's issue tracker, with filtering and pagination.

    Args:
        repo_slug: Repository slug
        workspace: Workspace name (optional, defaults to configured workspace)
        state: Filter by state (new, open, resolved, on hold, invalid, duplicate, wontfix, closed)
        kind: Filter by kind (bug, enhancement, proposal, task)
        priority: Filter by priority (trivial, minor, major, critical, blocker)
        assignee: Filter by assignee uuid
        q: Raw BBQL query, combined with the other filters using AND
           (e.g. 'created_on > 2024-01-01'). Passed through verbatim (not escaped).
        sort: Sort field (default: -created_on for most recent first)
        page_size: Items per page (default: 20)
        max_pages: Maximum pages to fetch (default: 1, max recommended: 10)
        max_items: Maximum total items to fetch (default: None)

    Returns:
        Paginated list of issues. If the repository has no issue tracker, returns
        {"error": "issue_tracker_disabled", ...}.

    Note:
        Fetching more than 10 pages or 300 items will trigger a warning.
    """
    client = get_client()
    result = await client.list_issues(
        repo_slug, workspace, state, kind, priority, assignee, q, sort,
        page_size, max_pages, max_items,
    )
    return slim_issue_list(result)


@conditional_tool()
@_handle_issue_tracker
async def get_issue(
    repo_slug: str,
    issue_id: str,
    workspace: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Get details for a specific issue.

    Args:
        repo_slug: Repository slug
        issue_id: Issue ID
        workspace: Workspace name (optional, defaults to configured workspace)

    Returns:
        Issue details. If the repository has no issue tracker, returns
        {"error": "issue_tracker_disabled", ...}.
    """
    client = get_client()
    result = await client.get_issue(repo_slug, issue_id, workspace)
    return slim_issue(result)


@conditional_tool()
@_handle_issue_tracker
async def create_issue(
    repo_slug: str,
    title: str,
    content: Optional[str] = None,
    kind: Optional[str] = None,
    priority: Optional[str] = None,
    assignee: Optional[str] = None,
    state: Optional[str] = None,
    workspace: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create a new issue in a repository's issue tracker.

    Args:
        repo_slug: Repository slug
        title: Issue title
        content: Issue description in markdown (optional)
        kind: Issue kind: bug, enhancement, proposal, task (optional)
        priority: Issue priority: trivial, minor, major, critical, blocker (optional)
        assignee: Assignee uuid (optional)
        state: Initial state (optional, e.g. new, open)
        workspace: Workspace name (optional, defaults to configured workspace)

    Returns:
        Created issue details. If the repository has no issue tracker, returns
        {"error": "issue_tracker_disabled", ...}.
    """
    client = get_client()
    result = await client.create_issue(
        repo_slug, title, content, kind, priority, assignee, state, workspace
    )
    return slim_issue(result)


@conditional_tool()
@_handle_issue_tracker
async def update_issue(
    repo_slug: str,
    issue_id: str,
    title: Optional[str] = None,
    content: Optional[str] = None,
    state: Optional[str] = None,
    kind: Optional[str] = None,
    priority: Optional[str] = None,
    assignee: Optional[str] = None,
    workspace: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Update an issue (only the provided fields are changed).

    Args:
        repo_slug: Repository slug
        issue_id: Issue ID
        title: New title (optional)
        content: New description in markdown (optional)
        state: New state: new, open, resolved, on hold, invalid, duplicate, wontfix, closed (optional)
        kind: New kind: bug, enhancement, proposal, task (optional)
        priority: New priority: trivial, minor, major, critical, blocker (optional)
        assignee: New assignee uuid (optional)
        workspace: Workspace name (optional, defaults to configured workspace)

    Returns:
        Updated issue details. If the repository has no issue tracker, returns
        {"error": "issue_tracker_disabled", ...}.
    """
    if all(v is None for v in (title, content, state, kind, priority, assignee)):
        raise ValueError("At least one field to update must be provided")
    client = get_client()
    result = await client.update_issue(
        repo_slug, issue_id, title, content, state, kind, priority, assignee, workspace
    )
    return slim_issue(result)


@conditional_tool()
@_handle_issue_tracker
async def delete_issue(
    repo_slug: str,
    issue_id: str,
    workspace: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Delete an issue.

    Args:
        repo_slug: Repository slug
        issue_id: Issue ID
        workspace: Workspace name (optional, defaults to configured workspace)

    Returns:
        Confirmation {"deleted": True, "issue_id": ...}. If the repository has no
        issue tracker, returns {"error": "issue_tracker_disabled", ...}.
    """
    client = get_client()
    await client.delete_issue(repo_slug, issue_id, workspace)
    return {"deleted": True, "issue_id": issue_id}


@conditional_tool()
@_handle_issue_tracker
async def get_issue_comments(
    repo_slug: str,
    issue_id: str,
    workspace: Optional[str] = None,
    page_size: int = 20,
    max_pages: Optional[int] = 1,
    max_items: Optional[int] = None,
) -> Dict[str, Any]:
    """
    List comments on an issue with pagination support.

    Args:
        repo_slug: Repository slug
        issue_id: Issue ID
        workspace: Workspace name (optional, defaults to configured workspace)
        page_size: Items per page (default: 20, max recommended: 100)
        max_pages: Maximum pages to fetch (default: 1, max recommended: 10)
        max_items: Maximum total items to fetch (default: None)

    Returns:
        Paginated list of issue comments. If the repository has no issue tracker,
        returns {"error": "issue_tracker_disabled", ...}.

    Note:
        Fetching more than 10 pages or 300 items will trigger a warning.
    """
    client = get_client()
    result = await client.get_issue_comments(
        repo_slug, issue_id, workspace, page_size, max_pages, max_items
    )
    return slim_issue_comment_list(result)


@conditional_tool()
@_handle_issue_tracker
async def get_issue_comment(
    repo_slug: str,
    issue_id: str,
    comment_id: str,
    workspace: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Get a specific comment on an issue.

    Args:
        repo_slug: Repository slug
        issue_id: Issue ID
        comment_id: Comment ID
        workspace: Workspace name (optional, defaults to configured workspace)

    Returns:
        Issue comment details. If the repository has no issue tracker, returns
        {"error": "issue_tracker_disabled", ...}.
    """
    client = get_client()
    result = await client.get_issue_comment(repo_slug, issue_id, comment_id, workspace)
    return slim_issue_comment(result)


@conditional_tool()
@_handle_issue_tracker
async def add_issue_comment(
    repo_slug: str,
    issue_id: str,
    content: str,
    workspace: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Add a comment to an issue.

    Args:
        repo_slug: Repository slug
        issue_id: Issue ID
        content: Comment content in markdown
        workspace: Workspace name (optional, defaults to configured workspace)

    Returns:
        Created issue comment details. If the repository has no issue tracker,
        returns {"error": "issue_tracker_disabled", ...}.
    """
    client = get_client()
    result = await client.add_issue_comment(repo_slug, issue_id, content, workspace)
    return slim_issue_comment(result)


@conditional_tool()
@_handle_issue_tracker
async def update_issue_comment(
    repo_slug: str,
    issue_id: str,
    comment_id: str,
    content: str,
    workspace: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Update a comment on an issue.

    Args:
        repo_slug: Repository slug
        issue_id: Issue ID
        comment_id: Comment ID
        content: New comment content in markdown
        workspace: Workspace name (optional, defaults to configured workspace)

    Returns:
        Updated issue comment details. If the repository has no issue tracker,
        returns {"error": "issue_tracker_disabled", ...}.
    """
    client = get_client()
    result = await client.update_issue_comment(
        repo_slug, issue_id, comment_id, content, workspace
    )
    return slim_issue_comment(result)


@conditional_tool()
@_handle_issue_tracker
async def delete_issue_comment(
    repo_slug: str,
    issue_id: str,
    comment_id: str,
    workspace: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Delete a comment on an issue.

    Args:
        repo_slug: Repository slug
        issue_id: Issue ID
        comment_id: Comment ID
        workspace: Workspace name (optional, defaults to configured workspace)

    Returns:
        Confirmation {"deleted": True, "comment_id": ...}. If the repository has no
        issue tracker, returns {"error": "issue_tracker_disabled", ...}.
    """
    client = get_client()
    await client.delete_issue_comment(repo_slug, issue_id, comment_id, workspace)
    return {"deleted": True, "comment_id": comment_id}


# ========== Commits & Source Tools ==========

@conditional_tool()
async def list_commits(
    repo_slug: str,
    revision: Optional[str] = None,
    workspace: Optional[str] = None,
    path: Optional[str] = None,
    include: Optional[str] = None,
    exclude: Optional[str] = None,
    page_size: int = 30,
    max_pages: Optional[int] = 1
) -> Dict[str, Any]:
    """
    List commits for a repository, optionally scoped to a revision or path.

    Args:
        repo_slug: Repository slug
        revision: Branch, tag or commit hash to start from (optional; defaults to all
            branches). A branch name containing '/' is ambiguous here — resolve it to a
            commit hash first (e.g. via get_branch) if listing fails.
        workspace: Workspace name (optional, defaults to configured workspace)
        path: Restrict history to commits touching this file/directory path
        include: Only commits reachable from this ref
        exclude: Exclude commits reachable from this ref
        page_size: Items per page (default: 30)
        max_pages: Maximum pages to fetch (default: 1, max recommended: 10)

    Returns:
        Paginated list of commits
    """
    client = get_client()
    result = await client.list_commits(
        repo_slug, revision, workspace, path, include, exclude, page_size, max_pages
    )
    return slim_commit_list(result)


@conditional_tool()
async def get_commit(
    repo_slug: str,
    commit: str,
    workspace: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get details for a single commit.

    Args:
        repo_slug: Repository slug
        commit: Commit hash (a simple branch/tag name also works)
        workspace: Workspace name (optional, defaults to configured workspace)

    Returns:
        Commit details
    """
    client = get_client()
    result = await client.get_commit(repo_slug, commit, workspace)
    return slim_commit(result)


@conditional_tool()
async def get_commit_comments(
    repo_slug: str,
    commit: str,
    workspace: Optional[str] = None,
    page_size: int = 10,
    max_pages: Optional[int] = 1
) -> Dict[str, Any]:
    """
    List comments on a commit with pagination support.

    Args:
        repo_slug: Repository slug
        commit: Commit hash
        workspace: Workspace name (optional, defaults to configured workspace)
        page_size: Items per page (default: 10)
        max_pages: Maximum pages to fetch (default: 1, max recommended: 10)

    Returns:
        Paginated list of commit comments
    """
    client = get_client()
    result = await client.get_commit_comments(
        repo_slug, commit, workspace, page_size, max_pages
    )
    return slim_commit_comment_list(result)


@conditional_tool()
async def get_commit_comment(
    repo_slug: str,
    commit: str,
    comment_id: str,
    workspace: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get a specific comment on a commit.

    Args:
        repo_slug: Repository slug
        commit: Commit hash
        comment_id: Comment ID
        workspace: Workspace name (optional, defaults to configured workspace)

    Returns:
        Commit comment details
    """
    client = get_client()
    result = await client.get_commit_comment(repo_slug, commit, comment_id, workspace)
    return slim_commit_comment(result)


@conditional_tool()
async def add_commit_comment(
    repo_slug: str,
    commit: str,
    content: str,
    workspace: Optional[str] = None,
    inline_path: Optional[str] = None,
    inline_from: Optional[int] = None,
    inline_to: Optional[int] = None
) -> Dict[str, Any]:
    """
    Add a comment to a commit (general or inline).

    Args:
        repo_slug: Repository slug
        commit: Commit hash
        content: Comment content in markdown format
        workspace: Workspace name (optional, defaults to configured workspace)
        inline_path: Path to the file in the repository (for inline comments)
        inline_from: Line number in the old version of the file
        inline_to: Line number in the new version of the file

    Returns:
        Created comment details
    """
    client = get_client()
    result = await client.add_commit_comment(
        repo_slug, commit, content, workspace, inline_path, inline_from, inline_to
    )
    return slim_commit_comment(result)


@conditional_tool()
async def get_file_content(
    repo_slug: str,
    commit: str,
    path: str,
    workspace: Optional[str] = None,
    max_bytes: int = DEFAULT_MAX_FILE_BYTES
) -> str:
    """
    Get the raw text content of a file at a given commit or branch.

    A metadata pre-check rejects directories, oversized files (> max_bytes) and
    binary files before downloading, to protect the token budget.

    Args:
        repo_slug: Repository slug
        commit: Commit hash (a simple branch/tag name also works; a branch name
            containing '/' is ambiguous on /src — resolve it to a hash first)
        path: File path within the repository
        workspace: Workspace name (optional, defaults to configured workspace)
        max_bytes: Maximum file size to return (default: 262144 = 256 KiB)

    Returns:
        File content as text
    """
    client = get_client()
    return await client.get_file_content(repo_slug, commit, path, workspace, max_bytes)


@conditional_tool()
async def list_directory(
    repo_slug: str,
    commit: str,
    path: str = "",
    workspace: Optional[str] = None,
    page_size: int = 50,
    max_pages: Optional[int] = 1
) -> Dict[str, Any]:
    """
    List the entries (files and sub-directories) of a directory at a commit/branch.

    Args:
        repo_slug: Repository slug
        commit: Commit hash (a simple branch/tag name also works)
        path: Directory path within the repository (empty = repository root)
        workspace: Workspace name (optional, defaults to configured workspace)
        page_size: Items per page (default: 50)
        max_pages: Maximum pages to fetch (default: 1, max recommended: 10)

    Returns:
        Paginated directory listing (path, type, size, mimetype per entry)
    """
    client = get_client()
    result = await client.list_directory(
        repo_slug, commit, path, workspace, page_size, max_pages
    )
    return slim_source_list(result)


# ========== Pipelines Config Tools ==========

@conditional_tool()
async def get_pipeline_config(
    repo_slug: str,
    workspace: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get the repository pipelines configuration (enabled flag, next build number).

    Note: this endpoint requires the `admin:repository` scope. A read-only token
    receives a 403 listing the missing privilege.

    Args:
        repo_slug: Repository slug
        workspace: Workspace name (optional, defaults to configured workspace)

    Returns:
        Pipelines configuration (enabled, next_build_number)
    """
    client = get_client()
    result = await client.get_pipeline_config(repo_slug, workspace)
    return slim_pipeline_config(result)


@conditional_tool()
async def list_pipeline_variables(
    repo_slug: str,
    workspace: Optional[str] = None,
    page_size: int = 20,
    max_pages: Optional[int] = 1
) -> Dict[str, Any]:
    """
    List repository-level pipeline variables.

    Secured variables never expose their value (returned as null).

    Args:
        repo_slug: Repository slug
        workspace: Workspace name (optional, defaults to configured workspace)
        page_size: Items per page (default: 20)
        max_pages: Maximum pages to fetch (default: 1, max recommended: 10)

    Returns:
        Paginated list of pipeline variables
    """
    client = get_client()
    result = await client.list_pipeline_variables(repo_slug, workspace, page_size, max_pages)
    return slim_pipeline_variable_list(result)


@conditional_tool()
async def get_pipeline_variable(
    repo_slug: str,
    variable_uuid: str,
    workspace: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get a single repository-level pipeline variable.

    Args:
        repo_slug: Repository slug
        variable_uuid: Variable UUID
        workspace: Workspace name (optional, defaults to configured workspace)

    Returns:
        Pipeline variable (value is null if secured)
    """
    client = get_client()
    result = await client.get_pipeline_variable(repo_slug, variable_uuid, workspace)
    return slim_pipeline_variable(result)


@conditional_tool()
async def create_pipeline_variable(
    repo_slug: str,
    key: str,
    value: str,
    secured: bool = False,
    workspace: Optional[str] = None
) -> Dict[str, Any]:
    """
    Create a repository-level pipeline variable.

    Args:
        repo_slug: Repository slug
        key: Variable name
        value: Variable value
        secured: Whether the value is secured/masked (default: False)
        workspace: Workspace name (optional, defaults to configured workspace)

    Returns:
        Created variable (value is null if secured)
    """
    client = get_client()
    result = await client.create_pipeline_variable(repo_slug, key, value, secured, workspace)
    return slim_pipeline_variable(result)


@conditional_tool()
async def update_pipeline_variable(
    repo_slug: str,
    variable_uuid: str,
    key: Optional[str] = None,
    value: Optional[str] = None,
    secured: Optional[bool] = None,
    workspace: Optional[str] = None
) -> Dict[str, Any]:
    """
    Update a repository-level pipeline variable (partial update).

    Args:
        repo_slug: Repository slug
        variable_uuid: Variable UUID
        key: New variable name (optional)
        value: New variable value (optional)
        secured: New secured flag (optional)
        workspace: Workspace name (optional, defaults to configured workspace)

    Returns:
        Updated variable (value is null if secured)
    """
    client = get_client()
    result = await client.update_pipeline_variable(
        repo_slug, variable_uuid, key, value, secured, workspace
    )
    return slim_pipeline_variable(result)


@conditional_tool()
async def delete_pipeline_variable(
    repo_slug: str,
    variable_uuid: str,
    workspace: Optional[str] = None
) -> Dict[str, Any]:
    """
    Delete a repository-level pipeline variable.

    Args:
        repo_slug: Repository slug
        variable_uuid: Variable UUID
        workspace: Workspace name (optional, defaults to configured workspace)

    Returns:
        Confirmation {"deleted": True, "variable_uuid": ...}
    """
    client = get_client()
    await client.delete_pipeline_variable(repo_slug, variable_uuid, workspace)
    return {"deleted": True, "variable_uuid": variable_uuid}


@conditional_tool()
async def list_pipeline_schedules(
    repo_slug: str,
    workspace: Optional[str] = None,
    page_size: int = 20,
    max_pages: Optional[int] = 1
) -> Dict[str, Any]:
    """
    List pipeline schedules for a repository.

    Args:
        repo_slug: Repository slug
        workspace: Workspace name (optional, defaults to configured workspace)
        page_size: Items per page (default: 20)
        max_pages: Maximum pages to fetch (default: 1, max recommended: 10)

    Returns:
        Paginated list of pipeline schedules
    """
    client = get_client()
    result = await client.list_pipeline_schedules(repo_slug, workspace, page_size, max_pages)
    return slim_pipeline_schedule_list(result)


@conditional_tool()
async def get_pipeline_schedule(
    repo_slug: str,
    schedule_uuid: str,
    workspace: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get a single pipeline schedule.

    Args:
        repo_slug: Repository slug
        schedule_uuid: Schedule UUID
        workspace: Workspace name (optional, defaults to configured workspace)

    Returns:
        Pipeline schedule
    """
    client = get_client()
    result = await client.get_pipeline_schedule(repo_slug, schedule_uuid, workspace)
    return slim_pipeline_schedule(result)


@conditional_tool()
async def list_pipeline_schedule_executions(
    repo_slug: str,
    schedule_uuid: str,
    workspace: Optional[str] = None,
    page_size: int = 20,
    max_pages: Optional[int] = 1
) -> Dict[str, Any]:
    """
    List the executions of a pipeline schedule.

    Args:
        repo_slug: Repository slug
        schedule_uuid: Schedule UUID
        workspace: Workspace name (optional, defaults to configured workspace)
        page_size: Items per page (default: 20)
        max_pages: Maximum pages to fetch (default: 1, max recommended: 10)

    Returns:
        Paginated list of schedule executions
    """
    client = get_client()
    result = await client.list_pipeline_schedule_executions(
        repo_slug, schedule_uuid, workspace, page_size, max_pages
    )
    return slim_pipeline_schedule_execution_list(result)


@conditional_tool()
async def create_pipeline_schedule(
    repo_slug: str,
    branch: str,
    cron_pattern: str,
    workspace: Optional[str] = None,
    enabled: bool = True,
    selector_pattern: Optional[str] = None
) -> Dict[str, Any]:
    """
    Create a pipeline schedule on a branch.

    Args:
        repo_slug: Repository slug
        branch: Branch the scheduled pipeline runs on
        cron_pattern: Cron expression (Bitbucket 7-field format, e.g. "0 0 6 * * ? *")
        workspace: Workspace name (optional, defaults to configured workspace)
        enabled: Whether the schedule is enabled (default: True)
        selector_pattern: Pipeline selector pattern (defaults to the branch name)

    Returns:
        Created schedule
    """
    client = get_client()
    result = await client.create_pipeline_schedule(
        repo_slug, branch, cron_pattern, workspace, enabled, selector_pattern
    )
    return slim_pipeline_schedule(result)


@conditional_tool()
async def update_pipeline_schedule(
    repo_slug: str,
    schedule_uuid: str,
    enabled: Optional[bool] = None,
    cron_pattern: Optional[str] = None,
    workspace: Optional[str] = None
) -> Dict[str, Any]:
    """
    Update a pipeline schedule (partial update).

    Args:
        repo_slug: Repository slug
        schedule_uuid: Schedule UUID
        enabled: New enabled flag (optional)
        cron_pattern: New cron expression (optional)
        workspace: Workspace name (optional, defaults to configured workspace)

    Returns:
        Updated schedule
    """
    client = get_client()
    result = await client.update_pipeline_schedule(
        repo_slug, schedule_uuid, enabled, cron_pattern, workspace
    )
    return slim_pipeline_schedule(result)


@conditional_tool()
async def delete_pipeline_schedule(
    repo_slug: str,
    schedule_uuid: str,
    workspace: Optional[str] = None
) -> Dict[str, Any]:
    """
    Delete a pipeline schedule.

    Args:
        repo_slug: Repository slug
        schedule_uuid: Schedule UUID
        workspace: Workspace name (optional, defaults to configured workspace)

    Returns:
        Confirmation {"deleted": True, "schedule_uuid": ...}
    """
    client = get_client()
    await client.delete_pipeline_schedule(repo_slug, schedule_uuid, workspace)
    return {"deleted": True, "schedule_uuid": schedule_uuid}


@conditional_tool()
async def list_pipeline_caches(
    repo_slug: str,
    workspace: Optional[str] = None,
    page_size: int = 20,
    max_pages: Optional[int] = 1
) -> Dict[str, Any]:
    """
    List pipeline caches for a repository.

    Args:
        repo_slug: Repository slug
        workspace: Workspace name (optional, defaults to configured workspace)
        page_size: Items per page (default: 20)
        max_pages: Maximum pages to fetch (default: 1, max recommended: 10)

    Returns:
        Paginated list of pipeline caches
    """
    client = get_client()
    result = await client.list_pipeline_caches(repo_slug, workspace, page_size, max_pages)
    return slim_pipeline_cache_list(result)


@conditional_tool()
async def delete_pipeline_cache(
    repo_slug: str,
    cache_uuid: str,
    workspace: Optional[str] = None
) -> Dict[str, Any]:
    """
    Delete a pipeline cache.

    Args:
        repo_slug: Repository slug
        cache_uuid: Cache UUID
        workspace: Workspace name (optional, defaults to configured workspace)

    Returns:
        Confirmation {"deleted": True, "cache_uuid": ...}
    """
    client = get_client()
    await client.delete_pipeline_cache(repo_slug, cache_uuid, workspace)
    return {"deleted": True, "cache_uuid": cache_uuid}
