"""MCP Server for Bitbucket API"""

import os
import sys
import json
import logging
from pathlib import Path
from typing import Optional, Dict, Any
from mcp.server.fastmcp import FastMCP
from .client import BitbucketClient
from .utils.credentials import get_credentials
from .utils.transformers import (
    slim_repository, slim_repository_list,
    slim_pull_request, slim_pull_request_list, slim_pull_request_created,
    slim_status_list,
    slim_commit_list,
    slim_diffstat_list,
    slim_comment, slim_comment_list,
    slim_activity_list,
    slim_pipeline_run, slim_pipeline_run_list,
    slim_pipeline_step_list,
)

# Configuration logging vers stderr uniquement (container-friendly)
logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


# ========== Tool Configuration ==========

def load_tools_config() -> Dict[str, bool]:
    """
    Load tool configuration from configs/tools.json.

    Returns:
        Dictionary mapping tool names to their enabled status
    """
    # Get project root (parent of src directory)
    project_root = Path(__file__).parent.parent
    config_file = project_root / "configs" / "tools.json"

    enabled_tools = {}

    try:
        if config_file.exists():
            with open(config_file, 'r') as f:
                config = json.load(f)

            # Flatten the nested structure to get tool_name -> enabled mapping
            for category, tools in config.get("tools", {}).items():
                for tool_name, tool_config in tools.items():
                    enabled_tools[tool_name] = tool_config.get("enabled", True)

            logger.info(f"Loaded tool configuration from {config_file}")
            logger.info(f"Enabled tools: {sum(enabled_tools.values())}/{len(enabled_tools)}")
        else:
            logger.warning(f"Tool configuration file not found: {config_file}")
            logger.info("All tools will be enabled by default")
    except Exception as e:
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
        reviewers: List of reviewer usernames (optional)
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
    description: Optional[str] = None
) -> Dict[str, Any]:
    """
    Update a pull request.

    Args:
        repo_slug: Repository slug
        pull_request_id: Pull request ID
        workspace: Workspace name (optional, defaults to configured workspace)
        title: New pull request title (optional)
        description: New pull request description (optional)

    Returns:
        Updated pull request details
    """
    client = get_client()
    result = await client.update_pull_request(
        repo_slug, pull_request_id, workspace, title, description
    )
    return slim_pull_request_created(result)


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

    Args:
        comment: Comment object from API

    Returns:
        Comment with added fields: is_resolved, resolved_by, resolved_on
    """
    resolution = comment.get("resolution")
    comment["is_resolved"] = resolution is not None

    if resolution:
        comment["resolved_by"] = resolution.get("user", {}).get("display_name")
        comment["resolved_on"] = resolution.get("created_on")
    else:
        comment["resolved_by"] = None
        comment["resolved_on"] = None

    return comment


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
        result["values"] = [_enrich_comment_with_resolution(comment) for comment in result["values"]]

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
async def get_pull_request_diff(
    repo_slug: str,
    pull_request_id: str,
    workspace: Optional[str] = None
) -> str:
    """
    Get diff for a pull request.

    Args:
        repo_slug: Repository slug
        pull_request_id: Pull request ID
        workspace: Workspace name (optional, defaults to configured workspace)

    Returns:
        Unified diff as string
    """
    client = get_client()
    return await client.get_pull_request_diff(repo_slug, pull_request_id, workspace)


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
