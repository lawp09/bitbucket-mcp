"""MCP Server for Bitbucket API"""

import os
import sys
import json
import logging
from pathlib import Path
from typing import Optional, Dict, Any
from mcp.server.fastmcp import FastMCP
from .client import BitbucketClient

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
        email = os.getenv("BITBUCKET_USERNAME")
        token = os.getenv("BITBUCKET_TOKEN")
        workspace = os.getenv("BITBUCKET_WORKSPACE")

        if not all([email, token, workspace]):
            raise ValueError(
                "Missing required environment variables: "
                "BITBUCKET_USERNAME, BITBUCKET_TOKEN, BITBUCKET_WORKSPACE"
            )

        _bitbucket_client = BitbucketClient(email, token, workspace)
        logger.info(f"Bitbucket client initialized for workspace: {workspace}")

    return _bitbucket_client


# ========== Repository Tools ==========

@conditional_tool()
async def list_repositories(
    workspace: Optional[str] = None,
    name: Optional[str] = None,
    limit: int = 30
) -> Dict[str, Any]:
    """
    List repositories in workspace.

    Args:
        workspace: Workspace name (optional, defaults to configured workspace)
        name: Filter by repository name (partial match supported)
        limit: Maximum number of repositories to return (default: 30)

    Returns:
        Paginated list of repositories
    """
    client = get_client()
    return await client.list_repositories(workspace, name, limit)


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
    return await client.get_repository(repo_slug, workspace)


# ========== Pull Request Tools ==========

@conditional_tool()
async def get_pull_requests(
    repo_slug: str,
    workspace: Optional[str] = None,
    state: str = "OPEN",
    limit: int = 30
) -> Dict[str, Any]:
    """
    Get pull requests for a repository.

    Args:
        repo_slug: Repository slug
        workspace: Workspace name (optional, defaults to configured workspace)
        state: Pull request state (OPEN, MERGED, DECLINED, SUPERSEDED) (default: OPEN)
        limit: Maximum number of pull requests to return (default: 30)

    Returns:
        Paginated list of pull requests
    """
    client = get_client()
    return await client.get_pull_requests(repo_slug, workspace, state, limit)


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
        Pull request details
    """
    client = get_client()
    return await client.get_pull_request(repo_slug, pull_request_id, workspace)


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
    return await client.create_pull_request(
        repo_slug, title, description, source_branch, target_branch,
        workspace, reviewers, draft
    )


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
    return await client.update_pull_request(
        repo_slug, pull_request_id, workspace, title, description
    )


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
    return await client.decline_pull_request(
        repo_slug, pull_request_id, workspace, message
    )


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
    return await client.merge_pull_request(
        repo_slug, pull_request_id, workspace, message, strategy
    )


# ========== Pull Request Comment Tools ==========

@conditional_tool()
async def get_pull_request_comments(
    repo_slug: str,
    pull_request_id: str,
    workspace: Optional[str] = None
) -> Dict[str, Any]:
    """
    List comments on a pull request.

    Args:
        repo_slug: Repository slug
        pull_request_id: Pull request ID
        workspace: Workspace name (optional, defaults to configured workspace)

    Returns:
        List of comments
    """
    client = get_client()
    return await client.get_pull_request_comments(repo_slug, pull_request_id, workspace)


@conditional_tool()
async def add_pull_request_comment(
    repo_slug: str,
    pull_request_id: str,
    content: str,
    workspace: Optional[str] = None,
    inline_path: Optional[str] = None,
    inline_from: Optional[int] = None,
    inline_to: Optional[int] = None,
    pending: bool = False
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

    Returns:
        Created comment details
    """
    client = get_client()
    return await client.add_pull_request_comment(
        repo_slug, pull_request_id, content, workspace,
        inline_path, inline_from, inline_to, pending
    )


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
    workspace: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get activity log for a pull request.

    Args:
        repo_slug: Repository slug
        pull_request_id: Pull request ID
        workspace: Workspace name (optional, defaults to configured workspace)

    Returns:
        Activity log with all events
    """
    client = get_client()
    return await client.get_pull_request_activity(repo_slug, pull_request_id, workspace)


@conditional_tool()
async def get_pull_request_commits(
    repo_slug: str,
    pull_request_id: str,
    workspace: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get commits on a pull request.

    Args:
        repo_slug: Repository slug
        pull_request_id: Pull request ID
        workspace: Workspace name (optional, defaults to configured workspace)

    Returns:
        List of commits
    """
    client = get_client()
    return await client.get_pull_request_commits(repo_slug, pull_request_id, workspace)


@conditional_tool()
async def get_pull_request_statuses(
    repo_slug: str,
    pull_request_id: str,
    workspace: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get build/CI statuses for a pull request.

    Args:
        repo_slug: Repository slug
        pull_request_id: Pull request ID
        workspace: Workspace name (optional, defaults to configured workspace)

    Returns:
        List of build statuses (Jenkins, CI/CD, tests, etc.)
        Each status contains:
        - state: SUCCESSFUL, FAILED, INPROGRESS, STOPPED
        - key: Unique identifier for the build
        - name: Build name/description
        - url: Link to the build details
        - created_on: Timestamp of the status
    """
    client = get_client()
    return await client.get_pull_request_statuses(repo_slug, pull_request_id, workspace)


@conditional_tool()
async def get_pull_request_diffstat(
    repo_slug: str,
    pull_request_id: str,
    workspace: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get file modification statistics for a pull request.

    Args:
        repo_slug: Repository slug
        pull_request_id: Pull request ID
        workspace: Workspace name (optional, defaults to configured workspace)

    Returns:
        Statistics with lines added/removed per file
        Each file entry contains:
        - status: modified, added, removed, renamed
        - lines_added: Number of lines added
        - lines_removed: Number of lines removed
        - new.path: File path after changes
    """
    client = get_client()
    return await client.get_pull_request_diffstat(repo_slug, pull_request_id, workspace)


# ========== Pipeline Tools ==========

@conditional_tool()
async def list_pipeline_runs(
    repo_slug: str,
    workspace: Optional[str] = None,
    status: Optional[str] = None,
    target_branch: Optional[str] = None,
    limit: int = 30
) -> Dict[str, Any]:
    """
    List pipeline runs for a repository.

    Args:
        repo_slug: Repository slug
        workspace: Workspace name (optional, defaults to configured workspace)
        status: Filter pipelines by status (PENDING, IN_PROGRESS, SUCCESSFUL, FAILED, ERROR, STOPPED)
        target_branch: Filter pipelines by target branch
        limit: Maximum number of pipelines to return (default: 30)

    Returns:
        List of pipeline runs
    """
    client = get_client()
    return await client.list_pipeline_runs(
        repo_slug, workspace, status, target_branch, limit
    )


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
    return await client.get_pipeline_run(repo_slug, pipeline_uuid, workspace)


@conditional_tool()
async def get_pipeline_steps(
    repo_slug: str,
    pipeline_uuid: str,
    workspace: Optional[str] = None
) -> Dict[str, Any]:
    """
    List steps for a pipeline run.

    Args:
        repo_slug: Repository slug
        pipeline_uuid: Pipeline UUID
        workspace: Workspace name (optional, defaults to configured workspace)

    Returns:
        List of pipeline steps
    """
    client = get_client()
    return await client.get_pipeline_steps(repo_slug, pipeline_uuid, workspace)


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
