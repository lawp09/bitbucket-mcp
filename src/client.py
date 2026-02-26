"""Bitbucket API Client with Basic Authentication"""

import base64
import logging
from typing import Any, Dict, List, Optional
import httpx

from .utils.pagination import PaginationConfig, aggregate_pages

logger = logging.getLogger(__name__)


class BitbucketClient:
    """Async HTTP client for Bitbucket API 2.0 with Basic Auth"""

    def __init__(self, email: str, token: str, workspace: str):
        """
        Initialize Bitbucket client with Basic Auth.

        Args:
            email: Bitbucket account email
            token: Bitbucket API token
            workspace: Bitbucket workspace name
        """
        self.workspace = workspace
        self.base_url = "https://api.bitbucket.org/2.0"

        # Create Basic Auth header: Authorization: Basic base64(email:token)
        auth_str = f"{email}:{token}"
        auth_bytes = auth_str.encode('utf-8')
        auth_b64 = base64.b64encode(auth_bytes).decode('utf-8')

        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={
                "Authorization": f"Basic {auth_b64}",
                "Content-Type": "application/json",
                "Accept": "application/json"
            },
            timeout=30.0,
            trust_env=False  # Disable proxy from environment for testing
        )

        logger.info(f"Bitbucket client initialized for workspace: {workspace}")

    async def close(self):
        """Close the HTTP client"""
        await self.client.aclose()

    def __repr__(self) -> str:
        """Protected repr to avoid credential leaks in logs/debug."""
        return f"BitbucketClient(workspace={self.workspace!r})"

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        _ = exc_type, exc_val, exc_tb  # Unused but required for protocol
        await self.close()

    # ========== Authentication Test ==========

    async def get_user(self) -> Dict[str, Any]:
        """
        Get authenticated user details (test authentication).

        Returns:
            User information dictionary

        Raises:
            httpx.HTTPStatusError: If authentication fails
        """
        response = await self.client.get("/user")
        response.raise_for_status()
        return response.json()

    # ========== Repositories ==========

    async def list_repositories(
        self,
        workspace: Optional[str] = None,
        name: Optional[str] = None,
        limit: int = 30,
        max_pages: Optional[int] = 1
    ) -> Dict[str, Any]:
        """
        List repositories in workspace with pagination support.

        Args:
            workspace: Workspace name (defaults to self.workspace)
            name: Filter by repository name (partial match)
            limit: Items per page (default: 30)
            max_pages: Maximum pages to fetch (default: 1)

        Returns:
            Paginated list of repositories with aggregated values
        """
        ws = workspace or self.workspace
        config = PaginationConfig(page_size=limit, max_pages=max_pages)
        params = {}
        if name:
            params["q"] = f'name~"{name}"'

        return await aggregate_pages(self.client, f"/repositories/{ws}", params, config)

    async def get_repository(
        self,
        repo_slug: str,
        workspace: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get repository details.

        Args:
            repo_slug: Repository slug
            workspace: Workspace name (defaults to self.workspace)

        Returns:
            Repository information
        """
        ws = workspace or self.workspace
        response = await self.client.get(f"/repositories/{ws}/{repo_slug}")
        response.raise_for_status()
        return response.json()

    # ========== Pull Requests ==========

    async def get_pull_requests(
        self,
        repo_slug: str,
        workspace: Optional[str] = None,
        state: str = "OPEN",
        limit: int = 30,
        max_pages: Optional[int] = 1
    ) -> Dict[str, Any]:
        """
        List pull requests for a repository with pagination support.

        Args:
            repo_slug: Repository slug
            workspace: Workspace name (defaults to self.workspace)
            state: PR state (OPEN, MERGED, DECLINED, SUPERSEDED)
            limit: Items per page (default: 30)
            max_pages: Maximum pages to fetch (default: 1)

        Returns:
            Paginated list of pull requests with aggregated values
        """
        ws = workspace or self.workspace
        config = PaginationConfig(page_size=limit, max_pages=max_pages)
        params = {"state": state}

        return await aggregate_pages(
            self.client,
            f"/repositories/{ws}/{repo_slug}/pullrequests",
            params,
            config
        )

    async def get_pull_request(
        self,
        repo_slug: str,
        pull_request_id: str,
        workspace: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get detailed information about a pull request.

        Args:
            repo_slug: Repository slug
            pull_request_id: Pull request ID
            workspace: Workspace name (defaults to self.workspace)

        Returns:
            Pull request details
        """
        ws = workspace or self.workspace
        response = await self.client.get(
            f"/repositories/{ws}/{repo_slug}/pullrequests/{pull_request_id}"
        )
        response.raise_for_status()
        return response.json()

    async def create_pull_request(
        self,
        repo_slug: str,
        title: str,
        description: str,
        source_branch: str,
        target_branch: str,
        workspace: Optional[str] = None,
        reviewers: Optional[List[str]] = None,
        draft: bool = False
    ) -> Dict[str, Any]:
        """
        Create a new pull request.

        Args:
            repo_slug: Repository slug
            title: PR title
            description: PR description
            source_branch: Source branch name
            target_branch: Target branch name
            workspace: Workspace name (defaults to self.workspace)
            reviewers: List of reviewer usernames
            draft: Whether to create as draft PR

        Returns:
            Created pull request details
        """
        ws = workspace or self.workspace

        payload: Dict[str, Any] = {
            "title": title,
            "description": description,
            "source": {"branch": {"name": source_branch}},
            "destination": {"branch": {"name": target_branch}}
        }

        if reviewers:
            payload["reviewers"] = [{"uuid": r} for r in reviewers]

        if draft:
            payload["draft"] = True

        response = await self.client.post(
            f"/repositories/{ws}/{repo_slug}/pullrequests",
            json=payload
        )
        response.raise_for_status()
        return response.json()

    async def update_pull_request(
        self,
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
            workspace: Workspace name (defaults to self.workspace)
            title: New title
            description: New description

        Returns:
            Updated pull request details
        """
        ws = workspace or self.workspace

        payload = {}
        if title:
            payload["title"] = title
        if description:
            payload["description"] = description

        response = await self.client.put(
            f"/repositories/{ws}/{repo_slug}/pullrequests/{pull_request_id}",
            json=payload
        )
        response.raise_for_status()
        return response.json()

    async def approve_pull_request(
        self,
        repo_slug: str,
        pull_request_id: str,
        workspace: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Approve a pull request.

        Args:
            repo_slug: Repository slug
            pull_request_id: Pull request ID
            workspace: Workspace name (defaults to self.workspace)

        Returns:
            Approval details
        """
        ws = workspace or self.workspace
        response = await self.client.post(
            f"/repositories/{ws}/{repo_slug}/pullrequests/{pull_request_id}/approve",
            json={}  # Body vide requis par l'API Bitbucket
        )
        response.raise_for_status()
        return response.json()

    async def unapprove_pull_request(
        self,
        repo_slug: str,
        pull_request_id: str,
        workspace: Optional[str] = None
    ) -> None:
        """
        Remove approval from a pull request.

        Args:
            repo_slug: Repository slug
            pull_request_id: Pull request ID
            workspace: Workspace name (defaults to self.workspace)
        """
        ws = workspace or self.workspace
        response = await self.client.delete(
            f"/repositories/{ws}/{repo_slug}/pullrequests/{pull_request_id}/approve"
        )
        response.raise_for_status()

    async def request_changes_pull_request(
        self,
        repo_slug: str,
        pull_request_id: str,
        workspace: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Request changes on a pull request (sets status to 'needs work').

        Args:
            repo_slug: Repository slug
            pull_request_id: Pull request ID
            workspace: Workspace name (defaults to self.workspace)

        Returns:
            Participant details with updated state
        """
        ws = workspace or self.workspace
        response = await self.client.post(
            f"/repositories/{ws}/{repo_slug}/pullrequests/{pull_request_id}/request-changes",
            json={}
        )
        response.raise_for_status()
        return response.json()

    async def unrequest_changes_pull_request(
        self,
        repo_slug: str,
        pull_request_id: str,
        workspace: Optional[str] = None
    ) -> None:
        """
        Remove 'request changes' status from a pull request.

        Args:
            repo_slug: Repository slug
            pull_request_id: Pull request ID
            workspace: Workspace name (defaults to self.workspace)
        """
        ws = workspace or self.workspace
        response = await self.client.delete(
            f"/repositories/{ws}/{repo_slug}/pullrequests/{pull_request_id}/request-changes"
        )
        response.raise_for_status()

    async def decline_pull_request(
        self,
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
            workspace: Workspace name (defaults to self.workspace)
            message: Optional reason for declining

        Returns:
            Updated pull request details
        """
        ws = workspace or self.workspace

        payload = {}
        if message:
            payload["message"] = message

        response = await self.client.post(
            f"/repositories/{ws}/{repo_slug}/pullrequests/{pull_request_id}/decline",
            json=payload if payload else None
        )
        response.raise_for_status()
        return response.json()

    async def merge_pull_request(
        self,
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
            workspace: Workspace name (defaults to self.workspace)
            message: Merge commit message
            strategy: Merge strategy (merge_commit, squash, fast_forward)

        Returns:
            Merged pull request details
        """
        ws = workspace or self.workspace

        payload = {"merge_strategy": strategy}
        if message:
            payload["message"] = message

        response = await self.client.post(
            f"/repositories/{ws}/{repo_slug}/pullrequests/{pull_request_id}/merge",
            json=payload
        )
        response.raise_for_status()
        return response.json()

    # ========== PR Comments ==========

    async def get_pull_request_comments(
        self,
        repo_slug: str,
        pull_request_id: str,
        workspace: Optional[str] = None,
        page_size: int = 10,
        max_pages: Optional[int] = 1,
        unresolved_only: bool = False
    ) -> Dict[str, Any]:
        """
        Get all comments on a pull request with pagination support.

        Args:
            repo_slug: Repository slug
            pull_request_id: Pull request ID
            workspace: Workspace name (defaults to self.workspace)
            page_size: Items per page (default: 10)
            max_pages: Maximum pages to fetch (default: 1)
            unresolved_only: Filter to unresolved comments only (default: False)

        Returns:
            Comments with aggregated values, including resolution field
        """
        ws = workspace or self.workspace
        config = PaginationConfig(page_size=page_size, max_pages=max_pages)
        params = {}
        if unresolved_only:
            params["q"] = "resolution=null"

        return await aggregate_pages(
            self.client,
            f"/repositories/{ws}/{repo_slug}/pullrequests/{pull_request_id}/comments",
            params,
            config
        )

    async def add_pull_request_comment(
        self,
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
        Add a comment to a pull request.

        Args:
            repo_slug: Repository slug
            pull_request_id: Pull request ID
            content: Comment content (markdown)
            workspace: Workspace name (defaults to self.workspace)
            inline_path: File path for inline comment
            inline_from: Line number in old version (for deleted/modified lines)
            inline_to: Line number in new version (for added/modified lines)
            pending: Whether to create as pending comment (draft)
            parent_id: Comment ID to reply to (creates a threaded reply)

        Returns:
            Created comment details
        """
        ws = workspace or self.workspace

        payload: Dict[str, Any] = {
            "content": {"raw": content}
        }

        if inline_path:
            inline_data: Dict[str, Any] = {"path": inline_path}
            if inline_from:
                inline_data["from"] = inline_from
            if inline_to:
                inline_data["to"] = inline_to
            payload["inline"] = inline_data

        if pending:
            payload["pending"] = True

        if parent_id is not None:
            payload["parent"] = {"id": parent_id}

        response = await self.client.post(
            f"/repositories/{ws}/{repo_slug}/pullrequests/{pull_request_id}/comments",
            json=payload
        )
        response.raise_for_status()
        return response.json()

    async def get_pull_request_comment(
        self,
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
            workspace: Workspace name (defaults to self.workspace)

        Returns:
            Comment details
        """
        ws = workspace or self.workspace
        response = await self.client.get(
            f"/repositories/{ws}/{repo_slug}/pullrequests/{pull_request_id}/comments/{comment_id}"
        )
        response.raise_for_status()
        return response.json()

    async def update_pull_request_comment(
        self,
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
            content: New comment content (markdown)
            workspace: Workspace name (defaults to self.workspace)

        Returns:
            Updated comment details
        """
        ws = workspace or self.workspace
        response = await self.client.put(
            f"/repositories/{ws}/{repo_slug}/pullrequests/{pull_request_id}/comments/{comment_id}",
            json={"content": {"raw": content}}
        )
        response.raise_for_status()
        return response.json()

    async def delete_pull_request_comment(
        self,
        repo_slug: str,
        pull_request_id: str,
        comment_id: str,
        workspace: Optional[str] = None
    ) -> None:
        """
        Delete a comment on a pull request.

        Args:
            repo_slug: Repository slug
            pull_request_id: Pull request ID
            comment_id: Comment ID
            workspace: Workspace name (defaults to self.workspace)
        """
        ws = workspace or self.workspace
        response = await self.client.delete(
            f"/repositories/{ws}/{repo_slug}/pullrequests/{pull_request_id}/comments/{comment_id}"
        )
        response.raise_for_status()

    async def resolve_pull_request_comment(
        self,
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
            workspace: Workspace name (defaults to self.workspace)

        Returns:
            Resolution details
        """
        ws = workspace or self.workspace
        response = await self.client.post(
            f"/repositories/{ws}/{repo_slug}/pullrequests/{pull_request_id}/comments/{comment_id}/resolve",
            json={}
        )
        response.raise_for_status()
        return response.json()

    async def reopen_pull_request_comment(
        self,
        repo_slug: str,
        pull_request_id: str,
        comment_id: str,
        workspace: Optional[str] = None
    ) -> None:
        """
        Reopen (unresolve) a comment on a pull request.

        Args:
            repo_slug: Repository slug
            pull_request_id: Pull request ID
            comment_id: Comment ID
            workspace: Workspace name (defaults to self.workspace)
        """
        ws = workspace or self.workspace
        response = await self.client.delete(
            f"/repositories/{ws}/{repo_slug}/pullrequests/{pull_request_id}/comments/{comment_id}/resolve"
        )
        response.raise_for_status()

    # ========== PR Tasks ==========

    async def get_pull_request_tasks(
        self,
        repo_slug: str,
        pull_request_id: str,
        workspace: Optional[str] = None,
        page_size: int = 10,
        max_pages: Optional[int] = 1
    ) -> Dict[str, Any]:
        """
        Get tasks on a pull request with pagination support.

        Args:
            repo_slug: Repository slug
            pull_request_id: Pull request ID
            workspace: Workspace name (defaults to self.workspace)
            page_size: Items per page (default: 10)
            max_pages: Maximum pages to fetch (default: 1)

        Returns:
            Paginated list of tasks
        """
        ws = workspace or self.workspace
        config = PaginationConfig(page_size=page_size, max_pages=max_pages)
        return await aggregate_pages(
            self.client,
            f"/repositories/{ws}/{repo_slug}/pullrequests/{pull_request_id}/tasks",
            {},
            config
        )

    async def get_pull_request_task(
        self,
        repo_slug: str,
        pull_request_id: str,
        task_id: str,
        workspace: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get a specific pull request task.

        Args:
            repo_slug: Repository slug
            pull_request_id: Pull request ID
            task_id: Task ID
            workspace: Workspace name (defaults to self.workspace)

        Returns:
            Task object from Bitbucket API
        """
        ws = workspace or self.workspace
        response = await self.client.get(
            f"/repositories/{ws}/{repo_slug}/pullrequests/{pull_request_id}/tasks/{task_id}"
        )
        response.raise_for_status()
        return response.json()

    async def create_pull_request_task(
        self,
        repo_slug: str,
        pull_request_id: str,
        content: str,
        workspace: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create a task on a pull request.

        Args:
            repo_slug: Repository slug
            pull_request_id: Pull request ID
            content: Task content (markdown)
            workspace: Workspace name (defaults to self.workspace)

        Returns:
            Created task object
        """
        ws = workspace or self.workspace
        payload = {
            "content": {"raw": content},
            "state": "UNRESOLVED"
        }
        response = await self.client.post(
            f"/repositories/{ws}/{repo_slug}/pullrequests/{pull_request_id}/tasks",
            json=payload
        )
        response.raise_for_status()
        return response.json()

    async def update_pull_request_task(
        self,
        repo_slug: str,
        pull_request_id: str,
        task_id: str,
        content: Optional[str] = None,
        state: Optional[str] = None,
        workspace: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Update a pull request task.

        Args:
            repo_slug: Repository slug
            pull_request_id: Pull request ID
            task_id: Task ID
            content: New task content (markdown)
            state: New task state (UNRESOLVED or RESOLVED)
            workspace: Workspace name (defaults to self.workspace)

        Returns:
            Updated task object
        """
        ws = workspace or self.workspace
        payload: Dict[str, Any] = {}
        if content is not None:
            payload["content"] = {"raw": content}
        if state is not None:
            payload["state"] = state
        response = await self.client.put(
            f"/repositories/{ws}/{repo_slug}/pullrequests/{pull_request_id}/tasks/{task_id}",
            json=payload
        )
        response.raise_for_status()
        return response.json()

    async def delete_pull_request_task(
        self,
        repo_slug: str,
        pull_request_id: str,
        task_id: str,
        workspace: Optional[str] = None
    ) -> None:
        """
        Delete a pull request task.

        Args:
            repo_slug: Repository slug
            pull_request_id: Pull request ID
            task_id: Task ID
            workspace: Workspace name (defaults to self.workspace)
        """
        ws = workspace or self.workspace
        response = await self.client.delete(
            f"/repositories/{ws}/{repo_slug}/pullrequests/{pull_request_id}/tasks/{task_id}"
        )
        response.raise_for_status()

    # ========== PR Patch ==========

    async def get_pull_request_patch(
        self,
        repo_slug: str,
        pull_request_id: str,
        workspace: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get the patch for a pull request.

        Args:
            repo_slug: Repository slug
            pull_request_id: Pull request ID
            workspace: Workspace name (defaults to self.workspace)

        Returns:
            Dictionary with patch content as string
        """
        ws = workspace or self.workspace
        response = await self.client.get(
            f"/repositories/{ws}/{repo_slug}/pullrequests/{pull_request_id}/patch",
            follow_redirects=True
        )
        response.raise_for_status()
        return {"patch": response.text}

    # ========== PR Discovery ==========

    async def get_pull_requests_pending_review(
        self,
        repo_slug: str,
        workspace: Optional[str] = None,
        page_size: int = 30,
        max_pages: Optional[int] = 1
    ) -> Dict[str, Any]:
        """
        Get open pull requests where the current user is a reviewer.

        Args:
            repo_slug: Repository slug
            workspace: Workspace name (defaults to self.workspace)
            page_size: Items per page (default: 30)
            max_pages: Maximum pages to fetch (default: 1)

        Returns:
            Paginated list of pull requests pending review
        """
        ws = workspace or self.workspace
        config = PaginationConfig(page_size=page_size, max_pages=max_pages)
        params = {"state": "OPEN", "role": "REVIEWER"}
        return await aggregate_pages(
            self.client,
            f"/repositories/{ws}/{repo_slug}/pullrequests",
            params,
            config
        )

    async def get_pull_request_diff(
        self,
        repo_slug: str,
        pull_request_id: str,
        workspace: Optional[str] = None,
        path: Optional[str] = None
    ) -> str:
        """
        Get the unified diff for a pull request.

        Args:
            repo_slug: Repository slug
            pull_request_id: Pull request ID
            workspace: Workspace name (defaults to self.workspace)
            path: Filter diff to a specific file path (optional)

        Returns:
            Unified diff as string
        """
        ws = workspace or self.workspace
        params = {}
        if path:
            params["path"] = path
        response = await self.client.get(
            f"/repositories/{ws}/{repo_slug}/pullrequests/{pull_request_id}/diff",
            params=params,
            follow_redirects=True
        )
        response.raise_for_status()
        return response.text

    async def get_pull_request_activity(
        self,
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
            workspace: Workspace name (defaults to self.workspace)
            page_size: Items per page (default: 10)
            max_pages: Maximum pages to fetch (default: 1)

        Returns:
            Activity log with aggregated values. Comment objects include the resolution field
            showing resolution status (null for unresolved comments, or resolution object with user and timestamp).
        """
        ws = workspace or self.workspace
        config = PaginationConfig(page_size=page_size, max_pages=max_pages)
        return await aggregate_pages(
            self.client,
            f"/repositories/{ws}/{repo_slug}/pullrequests/{pull_request_id}/activity",
            {},
            config
        )

    async def get_pull_request_comment_stats(
        self,
        workspace: str,
        repo_slug: str,
        pull_request_id: int
    ) -> Dict[str, Any]:
        """
        Get comment statistics for a pull request.

        Args:
            workspace: Workspace name
            repo_slug: Repository slug
            pull_request_id: Pull request ID

        Returns:
            Dictionary with comment statistics:
            - total: Total number of comments
            - resolved: Number of resolved comments
            - unresolved: Number of unresolved comments
        """
        comments_response = await self.get_pull_request_comments(
            repo_slug=repo_slug,
            pull_request_id=str(pull_request_id),
            workspace=workspace,
            page_size=50,
            max_pages=None
        )

        comments = comments_response.get("values", [])
        total = len(comments)
        resolved = sum(1 for comment in comments if comment.get("resolution") is not None)
        unresolved = total - resolved

        return {
            "total": total,
            "resolved": resolved,
            "unresolved": unresolved
        }

    async def get_pull_request_commits(
        self,
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
            workspace: Workspace name (defaults to self.workspace)
            page_size: Items per page (default: 10)
            max_pages: Maximum pages to fetch (default: 1)

        Returns:
            Commits with aggregated values
        """
        ws = workspace or self.workspace
        config = PaginationConfig(page_size=page_size, max_pages=max_pages)
        return await aggregate_pages(
            self.client,
            f"/repositories/{ws}/{repo_slug}/pullrequests/{pull_request_id}/commits",
            {},
            config
        )

    # ========== Pipelines ==========

    async def list_pipeline_runs(
        self,
        repo_slug: str,
        workspace: Optional[str] = None,
        status: Optional[str] = None,
        target_branch: Optional[str] = None,
        limit: int = 30,
        max_pages: Optional[int] = 1
    ) -> Dict[str, Any]:
        """
        List pipeline runs for a repository with pagination support.

        Args:
            repo_slug: Repository slug
            workspace: Workspace name (defaults to self.workspace)
            status: Filter by status (PENDING, IN_PROGRESS, SUCCESSFUL, FAILED, etc.)
            target_branch: Filter by target branch
            limit: Items per page (default: 30)
            max_pages: Maximum pages to fetch (default: 1)

        Returns:
            List of pipeline runs with aggregated values
        """
        ws = workspace or self.workspace
        config = PaginationConfig(page_size=limit, max_pages=max_pages)
        params = {}

        if status:
            params["status"] = status
        if target_branch:
            params["target.branch"] = target_branch

        return await aggregate_pages(
            self.client,
            f"/repositories/{ws}/{repo_slug}/pipelines/",
            params,
            config
        )

    async def get_pipeline_run(
        self,
        repo_slug: str,
        pipeline_uuid: str,
        workspace: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get details for a specific pipeline run.

        Args:
            repo_slug: Repository slug
            pipeline_uuid: Pipeline UUID
            workspace: Workspace name (defaults to self.workspace)

        Returns:
            Pipeline run details
        """
        ws = workspace or self.workspace
        response = await self.client.get(
            f"/repositories/{ws}/{repo_slug}/pipelines/{pipeline_uuid}"
        )
        response.raise_for_status()
        return response.json()

    async def get_pipeline_steps(
        self,
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
            workspace: Workspace name (defaults to self.workspace)
            page_size: Items per page (default: 10)
            max_pages: Maximum pages to fetch (default: 1)

        Returns:
            Pipeline steps with aggregated values
        """
        ws = workspace or self.workspace
        config = PaginationConfig(page_size=page_size, max_pages=max_pages)
        return await aggregate_pages(
            self.client,
            f"/repositories/{ws}/{repo_slug}/pipelines/{pipeline_uuid}/steps/",
            {},
            config
        )

    async def get_pipeline_step_logs(
        self,
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
            workspace: Workspace name (defaults to self.workspace)

        Returns:
            Step logs as string
        """
        ws = workspace or self.workspace
        response = await self.client.get(
            f"/repositories/{ws}/{repo_slug}/pipelines/{pipeline_uuid}/steps/{step_uuid}/log"
        )
        response.raise_for_status()
        return response.text

    # ========== Pull Request Build Statuses ==========

    async def get_pull_request_statuses(
        self,
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
            workspace: Workspace name (defaults to self.workspace)
            page_size: Items per page (default: 10)
            max_pages: Maximum pages to fetch (default: 1)

        Returns:
            Build statuses with aggregated values
            Each status contains:
            - state: SUCCESSFUL, FAILED, INPROGRESS, STOPPED
            - key: Unique identifier for the build
            - name: Build name/description
            - url: Link to the build details
            - created_on: Timestamp of the status
        """
        ws = workspace or self.workspace
        config = PaginationConfig(page_size=page_size, max_pages=max_pages)
        return await aggregate_pages(
            self.client,
            f"/repositories/{ws}/{repo_slug}/pullrequests/{pull_request_id}/statuses",
            {},
            config
        )

    # ========== Commit Build Statuses ==========

    async def get_commit_statuses(
        self,
        repo_slug: str,
        commit_hash: str,
        workspace: Optional[str] = None,
        page_size: int = 10,
        max_pages: Optional[int] = 1
    ) -> Dict[str, Any]:
        """
        Get build/CI statuses for a specific commit with pagination support.

        Args:
            repo_slug: Repository slug
            commit_hash: Commit hash (full or short)
            workspace: Workspace name (defaults to self.workspace)
            page_size: Items per page (default: 10)
            max_pages: Maximum pages to fetch (default: 1)

        Returns:
            Build statuses with aggregated values
            Each status contains:
            - state: SUCCESSFUL, FAILED, INPROGRESS, STOPPED
            - key: Unique identifier for the build
            - name: Build name/description
            - url: Link to the build details
            - created_on: Timestamp of the status
        """
        ws = workspace or self.workspace
        config = PaginationConfig(page_size=page_size, max_pages=max_pages)
        return await aggregate_pages(
            self.client,
            f"/repositories/{ws}/{repo_slug}/commit/{commit_hash}/statuses",
            {},
            config
        )

    async def run_pipeline(
        self,
        repo_slug: str,
        branch: str,
        workspace: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Trigger a new pipeline run on a branch.

        Args:
            repo_slug: Repository slug
            branch: Branch name to run the pipeline on
            workspace: Workspace name (defaults to self.workspace)

        Returns:
            Created pipeline run details
        """
        ws = workspace or self.workspace
        payload = {
            "target": {
                "ref_type": "branch",
                "type": "pipeline_ref_target",
                "ref_name": branch
            }
        }
        response = await self.client.post(
            f"/repositories/{ws}/{repo_slug}/pipelines/",
            json=payload
        )
        response.raise_for_status()
        return response.json()

    async def stop_pipeline(
        self,
        repo_slug: str,
        pipeline_uuid: str,
        workspace: Optional[str] = None
    ) -> None:
        """
        Stop a running pipeline.

        Args:
            repo_slug: Repository slug
            pipeline_uuid: Pipeline UUID
            workspace: Workspace name (defaults to self.workspace)
        """
        ws = workspace or self.workspace
        response = await self.client.post(
            f"/repositories/{ws}/{repo_slug}/pipelines/{pipeline_uuid}/stopPipeline",
            json={}
        )
        response.raise_for_status()

    # ========== Default Reviewers ==========

    async def get_effective_default_reviewers(
        self,
        repo_slug: str,
        workspace: Optional[str] = None,
        page_size: int = 30,
        max_pages: Optional[int] = 1
    ) -> Dict[str, Any]:
        """
        Get effective default reviewers for a repository.

        Args:
            repo_slug: Repository slug
            workspace: Workspace name (defaults to self.workspace)
            page_size: Items per page (default: 30)
            max_pages: Maximum pages to fetch (default: 1)

        Returns:
            Paginated list of default reviewers
        """
        ws = workspace or self.workspace
        config = PaginationConfig(page_size=page_size, max_pages=max_pages)
        return await aggregate_pages(
            self.client,
            f"/repositories/{ws}/{repo_slug}/effective-default-reviewers",
            {},
            config
        )

    async def get_pull_request_diffstat(
        self,
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
            workspace: Workspace name (defaults to self.workspace)
            page_size: Items per page (default: 10)
            max_pages: Maximum pages to fetch (default: 1)

        Returns:
            Statistics with lines added/removed per file
            Each file entry contains:
            - status: modified, added, removed, renamed
            - lines_added: Number of lines added
            - lines_removed: Number of lines removed
            - new.path: File path after changes
        """
        ws = workspace or self.workspace
        config = PaginationConfig(page_size=page_size, max_pages=max_pages)

        # First get the PR to extract the diffstat URL from links
        pr_response = await self.client.get(
            f"/repositories/{ws}/{repo_slug}/pullrequests/{pull_request_id}"
        )
        pr_response.raise_for_status()
        pr_data = pr_response.json()

        # Get the diffstat URL from the PR links
        if 'links' in pr_data and 'diffstat' in pr_data['links']:
            diffstat_url = pr_data['links']['diffstat']['href']
            # Remove base URL if present
            if diffstat_url.startswith(self.base_url):
                diffstat_url = diffstat_url[len(self.base_url):]

            return await aggregate_pages(self.client, diffstat_url, {}, config)
        else:
            # Fallback to direct URL if links not available
            return await aggregate_pages(
                self.client,
                f"/repositories/{ws}/{repo_slug}/pullrequests/{pull_request_id}/diffstat",
                {},
                config
            )

    async def publish_draft_pull_request(
        self,
        repo_slug: str,
        pull_request_id: str,
        workspace: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Publish a draft pull request (convert DRAFT to OPEN).

        Args:
            repo_slug: Repository slug
            pull_request_id: Pull request ID
            workspace: Workspace name (defaults to self.workspace)

        Returns:
            Updated pull request details
        """
        ws = workspace or self.workspace
        response = await self.client.put(
            f"/repositories/{ws}/{repo_slug}/pullrequests/{pull_request_id}",
            json={"draft": False}
        )
        response.raise_for_status()
        return response.json()
