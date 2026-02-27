"""Response transformers to reduce token usage for LLM consumers.

Each function takes a raw Bitbucket API response and returns a slimmed version
containing only the fields useful for LLM tool consumption.
"""

from typing import Any, Dict, List, Optional


def _slim_user(user: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Extract essential user fields."""
    if not user:
        return None
    return {
        "display_name": user.get("display_name"),
        "nickname": user.get("nickname"),
        "username": user.get("username"),
    }


def _slim_paginated(data: Dict[str, Any], transform_fn) -> Dict[str, Any]:
    """Apply a transform function to each item in a paginated response."""
    values = [transform_fn(v) for v in data.get("values", [])]
    result = {
        "values": values,
        "count": len(values),
        "page": data.get("page"),
    }
    if "next" in data:
        result["has_more"] = True
    return result


# ========== Repositories ==========

def slim_repository(repo: Dict[str, Any]) -> Dict[str, Any]:
    """Slim a single repository object."""
    mainbranch = repo.get("mainbranch")
    project = repo.get("project")
    return {
        "slug": repo.get("slug"),
        "name": repo.get("name"),
        "full_name": repo.get("full_name"),
        "description": repo.get("description"),
        "language": repo.get("language"),
        "is_private": repo.get("is_private"),
        "project": project.get("key") if project else None,
        "mainbranch": mainbranch.get("name") if mainbranch else None,
        "created_on": repo.get("created_on"),
        "updated_on": repo.get("updated_on"),
        "size": repo.get("size"),
    }


def slim_repository_list(data: Dict[str, Any]) -> Dict[str, Any]:
    """Slim a paginated list of repositories."""
    return _slim_paginated(data, slim_repository)


# ========== Pull Requests ==========

def slim_pull_request_list_item(pr: Dict[str, Any]) -> Dict[str, Any]:
    """Slim a PR for list view (no description)."""
    source = pr.get("source", {})
    destination = pr.get("destination", {})
    return {
        "id": pr.get("id"),
        "title": pr.get("title"),
        "state": pr.get("state"),
        "draft": pr.get("draft"),
        "author": pr.get("author", {}).get("display_name"),
        "source_branch": source.get("branch", {}).get("name"),
        "destination_branch": destination.get("branch", {}).get("name"),
        "comment_count": pr.get("comment_count"),
        "task_count": pr.get("task_count"),
        "created_on": pr.get("created_on"),
        "updated_on": pr.get("updated_on"),
    }


def slim_pull_request_list(data: Dict[str, Any]) -> Dict[str, Any]:
    """Slim a paginated list of pull requests."""
    return _slim_paginated(data, slim_pull_request_list_item)


def slim_pull_request(pr: Dict[str, Any]) -> Dict[str, Any]:
    """Slim a single pull request (detail view, keeps description)."""
    source = pr.get("source", {})
    destination = pr.get("destination", {})

    result = {
        "id": pr.get("id"),
        "title": pr.get("title"),
        "description": pr.get("description"),
        "state": pr.get("state"),
        "draft": pr.get("draft"),
        "author": pr.get("author", {}).get("display_name"),
        "source_branch": source.get("branch", {}).get("name"),
        "destination_branch": destination.get("branch", {}).get("name"),
        "reviewers": [
            {
                "display_name": r.get("display_name") or r.get("user", {}).get("display_name"),
                "approved": r.get("approved"),
            }
            for r in pr.get("reviewers", [])
        ],
        "participants": [
            {
                "display_name": p.get("display_name") or p.get("user", {}).get("display_name"),
                "role": p.get("role"),
                "approved": p.get("approved"),
            }
            for p in pr.get("participants", [])
        ],
        "comment_count": pr.get("comment_count"),
        "task_count": pr.get("task_count"),
        "close_source_branch": pr.get("close_source_branch"),
        "created_on": pr.get("created_on"),
        "updated_on": pr.get("updated_on"),
    }

    if "comment_stats" in pr:
        result["comment_stats"] = pr["comment_stats"]

    return result


def slim_pull_request_created(pr: Dict[str, Any]) -> Dict[str, Any]:
    """Slim a PR creation/update confirmation."""
    source = pr.get("source", {})
    destination = pr.get("destination", {})
    html_link = pr.get("links", {}).get("html", {}).get("href")
    return {
        "id": pr.get("id"),
        "title": pr.get("title"),
        "state": pr.get("state"),
        "draft": pr.get("draft"),
        "source_branch": source.get("branch", {}).get("name"),
        "destination_branch": destination.get("branch", {}).get("name"),
        "url": html_link,
        "created_on": pr.get("created_on"),
    }


# ========== Statuses ==========

def slim_status(status: Dict[str, Any]) -> Dict[str, Any]:
    """Slim a single build status."""
    return {
        "state": status.get("state"),
        "name": status.get("name"),
        "description": status.get("description"),
        "url": status.get("url"),
        "commit_hash": status.get("commit", {}).get("hash", "")[:12],
        "created_on": status.get("created_on"),
        "updated_on": status.get("updated_on"),
    }


def slim_status_list(data: Dict[str, Any]) -> Dict[str, Any]:
    """Slim a paginated list of build statuses."""
    return _slim_paginated(data, slim_status)


# ========== Commits ==========

def slim_commit(commit: Dict[str, Any]) -> Dict[str, Any]:
    """Slim a single commit."""
    author = commit.get("author", {})
    user = author.get("user")
    return {
        "hash": commit.get("hash", "")[:12],
        "message": commit.get("message"),
        "date": commit.get("date"),
        "author": user.get("display_name") if user else author.get("raw"),
    }


def slim_commit_list(data: Dict[str, Any]) -> Dict[str, Any]:
    """Slim a paginated list of commits."""
    return _slim_paginated(data, slim_commit)


# ========== Diffstat ==========

def slim_diffstat_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Slim a single diffstat entry."""
    old = entry.get("old")
    new = entry.get("new")
    return {
        "status": entry.get("status"),
        "lines_added": entry.get("lines_added"),
        "lines_removed": entry.get("lines_removed"),
        "old_path": old.get("path") if old else None,
        "new_path": new.get("path") if new else None,
    }


def slim_diffstat_list(data: Dict[str, Any]) -> Dict[str, Any]:
    """Slim a paginated diffstat response."""
    return _slim_paginated(data, slim_diffstat_entry)


# ========== Comments ==========

def slim_comment(comment: Dict[str, Any]) -> Dict[str, Any]:
    """Slim a single comment."""
    content = comment.get("content", {})
    inline = comment.get("inline")
    parent = comment.get("parent")

    result = {
        "id": comment.get("id"),
        "content": content.get("raw"),
        "author": _slim_user(comment.get("user")),
        "created_on": comment.get("created_on"),
        "updated_on": comment.get("updated_on"),
        "is_resolved": comment.get("is_resolved"),
        "resolved_by": comment.get("resolved_by"),
        "resolved_on": comment.get("resolved_on"),
        "pending": comment.get("pending"),
    }

    if inline:
        result["inline"] = {
            "path": inline.get("path"),
            "from": inline.get("from"),
            "to": inline.get("to"),
        }

    if parent:
        result["parent_id"] = parent.get("id")

    return result


def slim_comment_list(data: Dict[str, Any]) -> Dict[str, Any]:
    """Slim a paginated list of comments."""
    return _slim_paginated(data, slim_comment)


# ========== Tasks ==========

def slim_task(task: Dict[str, Any]) -> Dict[str, Any]:
    """Slim a PR task response to reduce LLM token usage."""
    resolved_by = task.get("resolved_by")
    comment = task.get("comment")
    result = {
        "id": task.get("id"),
        "state": task.get("state"),
        "content": task.get("content", {}).get("raw"),
        "creator": task.get("creator", {}).get("display_name"),
        "created_on": task.get("created_on"),
        "updated_on": task.get("updated_on"),
        "resolved_on": task.get("resolved_on"),
        "resolved_by": resolved_by.get("display_name") if resolved_by else None,
        "pending": task.get("pending", False),
    }
    if comment:
        result["comment_id"] = comment.get("id")
    return result


def slim_task_list(data: Dict[str, Any]) -> Dict[str, Any]:
    """Slim a paginated list of tasks."""
    return _slim_paginated(data, slim_task)


# ========== Activity ==========

def _slim_activity_update(update: Dict[str, Any]) -> Dict[str, Any]:
    """Slim an activity update entry."""
    return {
        "state": update.get("state"),
        "draft": update.get("draft"),
        "title": update.get("title"),
        "date": update.get("date"),
        "author": _slim_user(update.get("author")),
    }


def _slim_activity_approval(approval: Dict[str, Any]) -> Dict[str, Any]:
    """Slim an activity approval entry."""
    return {
        "date": approval.get("date"),
        "user": _slim_user(approval.get("user")),
    }


def slim_activity_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Slim a single activity entry."""
    result = {}

    if "update" in entry:
        result["type"] = "update"
        result["update"] = _slim_activity_update(entry["update"])
    elif "comment" in entry:
        result["type"] = "comment"
        result["comment"] = slim_comment(entry["comment"])
    elif "approval" in entry:
        result["type"] = "approval"
        result["approval"] = _slim_activity_approval(entry["approval"])
    else:
        result["type"] = "unknown"

    return result


def slim_activity_list(data: Dict[str, Any]) -> Dict[str, Any]:
    """Slim a paginated list of activity entries."""
    return _slim_paginated(data, slim_activity_entry)


# ========== Pipelines ==========

def slim_pipeline_run(run: Dict[str, Any]) -> Dict[str, Any]:
    """Slim a single pipeline run."""
    target = run.get("target", {})
    ref = target.get("ref_name") or target.get("selector", {}).get("pattern")
    return {
        "uuid": run.get("uuid"),
        "build_number": run.get("build_number"),
        "state": run.get("state", {}).get("name"),
        "state_result": run.get("state", {}).get("result", {}).get("name"),
        "target_branch": ref,
        "trigger": run.get("trigger", {}).get("name"),
        "duration_in_seconds": run.get("duration_in_seconds"),
        "created_on": run.get("created_on"),
        "completed_on": run.get("completed_on"),
    }


def slim_pipeline_run_list(data: Dict[str, Any]) -> Dict[str, Any]:
    """Slim a paginated list of pipeline runs."""
    return _slim_paginated(data, slim_pipeline_run)


def slim_pipeline_step(step: Dict[str, Any]) -> Dict[str, Any]:
    """Slim a single pipeline step."""
    return {
        "uuid": step.get("uuid"),
        "name": step.get("name"),
        "state": step.get("state", {}).get("name"),
        "state_result": step.get("state", {}).get("result", {}).get("name"),
        "duration_in_seconds": step.get("duration_in_seconds"),
        "started_on": step.get("started_on"),
        "completed_on": step.get("completed_on"),
    }


def slim_pipeline_step_list(data: Dict[str, Any]) -> Dict[str, Any]:
    """Slim a paginated list of pipeline steps."""
    return _slim_paginated(data, slim_pipeline_step)


# ========== Default Reviewers ==========

def slim_reviewer(reviewer: Dict[str, Any]) -> Dict[str, Any]:
    """Slim a single default reviewer."""
    user = reviewer.get("user", {})
    return {
        "display_name": user.get("display_name"),
        "nickname": user.get("nickname"),
        "uuid": user.get("uuid"),
        "reviewer_type": reviewer.get("reviewer_type"),
    }


def slim_reviewer_list(data: Dict[str, Any]) -> Dict[str, Any]:
    """Slim a paginated list of default reviewers."""
    return _slim_paginated(data, slim_reviewer)
