"""Response transformers to reduce token usage for LLM consumers.

Each function takes a raw Bitbucket API response and returns a slimmed version
containing only the fields useful for LLM tool consumption.
"""

from typing import Any, Dict, Optional


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
    # Propagated explicitly: this whitelist would otherwise drop the truncation signal
    # set by aggregate_pages when the server-side page hard cap kicked in.
    if data.get("truncated"):
        result["truncated"] = True
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


def slim_tag(tag: Dict[str, Any]) -> Dict[str, Any]:
    """Slim a single repository tag."""
    target = tag.get("target") or {}
    tagger = tag.get("tagger") or {}
    date = target.get("date") or tagger.get("date") or tag.get("date")
    message = target.get("message") or tag.get("message")
    return {
        "name": tag.get("name"),
        "date": date,
        "target_hash": target.get("hash", "")[:12],
        "message": message,
    }


def slim_tag_list(data: Dict[str, Any]) -> Dict[str, Any]:
    """Slim a paginated list of repository tags."""
    return _slim_paginated(data, slim_tag)


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
        "author_uuid": pr.get("author", {}).get("uuid"),
        "source_branch": source.get("branch", {}).get("name"),
        "destination_branch": destination.get("branch", {}).get("name"),
        "reviewers": [
            {
                "display_name": r.get("display_name"),
                "uuid": r.get("uuid"),
                "approved": r.get("approved"),
            }
            for r in pr.get("reviewers", [])
        ],
        "participants": [
            {
                "display_name": p.get("user", {}).get("display_name"),
                "uuid": p.get("user", {}).get("uuid"),
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


# ========== Source (file/directory browsing) ==========

def slim_source_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Slim a single source tree entry (file or directory).

    Bitbucket tags each entry with ``type`` = ``commit_file`` or
    ``commit_directory``. ``size``/``mimetype`` are only present on files. The
    per-entry commit is intentionally omitted: every entry of one listing shares
    the same commit, which ``slim_source_list`` hoists to a single top-level field.
    """
    return {
        "path": entry.get("path"),
        "type": entry.get("type"),
        "size": entry.get("size"),
        "mimetype": entry.get("mimetype"),
    }


def slim_source_list(data: Dict[str, Any]) -> Dict[str, Any]:
    """Slim a paginated directory listing from the ``/src`` endpoint.

    The resolved commit hash is hoisted to a single top-level ``commit`` field
    instead of being repeated on every entry (saves tokens on large directories,
    since all entries of a listing are at the same commit).
    """
    result = _slim_paginated(data, slim_source_entry)
    commit_hash = None
    for entry in data.get("values", []):
        commit = entry.get("commit") or {}
        if commit.get("hash"):
            commit_hash = commit["hash"][:12]
            break
    result["commit"] = commit_hash
    return result


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


def slim_commit_comment(comment: Dict[str, Any]) -> Dict[str, Any]:
    """Slim a single commit comment.

    Distinct from ``slim_comment`` (PR comments): commit comments have no
    resolution lifecycle, so the ``is_resolved``/``resolved_*``/``pending``
    fields are deliberately omitted to avoid emitting confusing null noise.
    """
    content = comment.get("content", {})
    inline = comment.get("inline")
    parent = comment.get("parent")

    result = {
        "id": comment.get("id"),
        "content": content.get("raw"),
        "author": _slim_user(comment.get("user")),
        "created_on": comment.get("created_on"),
        "updated_on": comment.get("updated_on"),
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


def slim_commit_comment_list(data: Dict[str, Any]) -> Dict[str, Any]:
    """Slim a paginated list of commit comments."""
    return _slim_paginated(data, slim_commit_comment)


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
    target = run.get("target") or {}
    ref = target.get("ref_name") or (target.get("selector") or {}).get("pattern")
    state = run.get("state") or {}
    return {
        "uuid": run.get("uuid"),
        "build_number": run.get("build_number"),
        "state": state.get("name"),
        "state_result": (state.get("result") or {}).get("name"),
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
    state = step.get("state") or {}
    return {
        "uuid": step.get("uuid"),
        "name": step.get("name"),
        "state": state.get("name"),
        "state_result": (state.get("result") or {}).get("name"),
        "duration_in_seconds": step.get("duration_in_seconds"),
        "started_on": step.get("started_on"),
        "completed_on": step.get("completed_on"),
    }


def slim_pipeline_step_list(data: Dict[str, Any]) -> Dict[str, Any]:
    """Slim a paginated list of pipeline steps."""
    return _slim_paginated(data, slim_pipeline_step)


# ========== Pipelines Config (variables, schedules, caches) ==========

def slim_pipeline_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """Slim a repository pipelines configuration object."""
    build = config.get("build_number_settings") or {}
    return {
        "enabled": config.get("enabled"),
        "next_build_number": build.get("next_build_number"),
    }


def slim_pipeline_variable(variable: Dict[str, Any]) -> Dict[str, Any]:
    """Slim a pipeline variable.

    Secured variables never expose their value (the API omits it); force
    ``value`` to None so a secret is never surfaced even if the field leaks.
    """
    # Strict check: only an explicit True masks. A null/missing flag means the
    # variable is not secured (so its value is safe to surface).
    secured = variable.get("secured") is True
    return {
        "uuid": variable.get("uuid"),
        "key": variable.get("key"),
        "value": None if secured else variable.get("value"),
        "secured": secured,
    }


def slim_pipeline_variable_list(data: Dict[str, Any]) -> Dict[str, Any]:
    """Slim a paginated list of pipeline variables."""
    return _slim_paginated(data, slim_pipeline_variable)


def slim_pipeline_schedule(schedule: Dict[str, Any]) -> Dict[str, Any]:
    """Slim a pipeline schedule."""
    target = schedule.get("target") or {}
    selector = target.get("selector") or {}
    return {
        "uuid": schedule.get("uuid"),
        "enabled": schedule.get("enabled"),
        "cron_pattern": schedule.get("cron_pattern"),
        "target_ref": target.get("ref_name"),
        "selector_pattern": selector.get("pattern"),
        "created_on": schedule.get("created_on"),
        "updated_on": schedule.get("updated_on"),
    }


def slim_pipeline_schedule_list(data: Dict[str, Any]) -> Dict[str, Any]:
    """Slim a paginated list of pipeline schedules."""
    return _slim_paginated(data, slim_pipeline_schedule)


def slim_pipeline_schedule_execution(execution: Dict[str, Any]) -> Dict[str, Any]:
    """Slim a single scheduled-pipeline execution record."""
    state = execution.get("state") or {}
    pipeline = execution.get("pipeline") or {}
    return {
        "state": state.get("name"),
        # result is null while the pipeline is still in progress
        "state_result": (state.get("result") or {}).get("name"),
        "pipeline_uuid": pipeline.get("uuid"),
        "build_number": pipeline.get("build_number"),
        "created_on": execution.get("created_on"),
    }


def slim_pipeline_schedule_execution_list(data: Dict[str, Any]) -> Dict[str, Any]:
    """Slim a paginated list of scheduled-pipeline executions."""
    return _slim_paginated(data, slim_pipeline_schedule_execution)


def slim_pipeline_cache(cache: Dict[str, Any]) -> Dict[str, Any]:
    """Slim a pipeline cache entry."""
    return {
        "uuid": cache.get("uuid"),
        "name": cache.get("name"),
        "path": cache.get("path"),
        "file_size_bytes": cache.get("file_size_bytes"),
        "created_on": cache.get("created_on"),
    }


def slim_pipeline_cache_list(data: Dict[str, Any]) -> Dict[str, Any]:
    """Slim a paginated list of pipeline caches."""
    return _slim_paginated(data, slim_pipeline_cache)


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


# ========== Issues ==========

def _slim_issue_user(user: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Like _slim_user but keeps the uuid.

    Issues identify assignees/reporters by uuid (filtering via assignee.uuid,
    create/update via {"uuid": ...}); keeping it lets a consumer read a uuid from
    get_issue/list_issues and reuse it to reassign or filter.
    """
    slimmed = _slim_user(user)
    if slimmed is not None:
        slimmed["uuid"] = (user or {}).get("uuid")
    return slimmed


def slim_issue(issue: Dict[str, Any]) -> Dict[str, Any]:
    """Slim a single issue object."""
    content = issue.get("content") or {}
    component = issue.get("component") or {}
    milestone = issue.get("milestone") or {}
    return {
        "id": issue.get("id"),
        "title": issue.get("title"),
        "content": content.get("raw"),
        "state": issue.get("state"),
        "kind": issue.get("kind"),
        "priority": issue.get("priority"),
        "reporter": _slim_issue_user(issue.get("reporter")),
        "assignee": _slim_issue_user(issue.get("assignee")),
        "component": component.get("name"),
        "milestone": milestone.get("name"),
        "votes": issue.get("votes"),
        "watches": issue.get("watches"),
        "created_on": issue.get("created_on"),
        "updated_on": issue.get("updated_on"),
    }


def slim_issue_list(data: Dict[str, Any]) -> Dict[str, Any]:
    """Slim a paginated list of issues."""
    return _slim_paginated(data, slim_issue)


def slim_issue_comment(comment: Dict[str, Any]) -> Dict[str, Any]:
    """Slim a single issue comment.

    Issue comments are not resolvable (unlike PR comments), so no resolution fields.
    """
    content = comment.get("content") or {}
    return {
        "id": comment.get("id"),
        "content": content.get("raw"),
        "author": _slim_user(comment.get("user")),
        "created_on": comment.get("created_on"),
        "updated_on": comment.get("updated_on"),
    }


def slim_issue_comment_list(data: Dict[str, Any]) -> Dict[str, Any]:
    """Slim a paginated list of issue comments."""
    return _slim_paginated(data, slim_issue_comment)


# ========== Deployments & Environments ==========

def slim_environment(env: Dict[str, Any]) -> Dict[str, Any]:
    """Slim a single deployment environment."""
    env_type = env.get("environment_type") or {}
    return {
        "uuid": env.get("uuid"),
        "name": env.get("name"),
        "environment_type": env_type.get("name"),
        "slug": env.get("slug"),
        "rank": env.get("rank"),
        "hidden": env.get("hidden", False),
    }


def slim_environment_list(data: Dict[str, Any]) -> Dict[str, Any]:
    """Slim a paginated list of environments."""
    return _slim_paginated(data, slim_environment)


def slim_deployment(dep: Dict[str, Any]) -> Dict[str, Any]:
    """Slim a single deployment.

    State model: ``state.name`` is the lifecycle phase (PENDING / IN_PROGRESS /
    COMPLETED / UNDEPLOYED) and ``state.status.name`` is the COMPLETED sub-result
    (SUCCESSFUL / FAILED / STOPPED). The sub-status is null while a deployment is
    still running, so the ``or {}`` guard is required. The deployed commit lives
    under ``deployable.commit.hash`` (canonical); ``release.commit`` / top-level
    ``commit`` are tolerated as fallbacks.
    """
    state = dep.get("state") or {}
    environment = dep.get("environment") or {}
    deployable = dep.get("deployable") or {}
    release = dep.get("release") or {}
    commit = deployable.get("commit") or release.get("commit") or dep.get("commit") or {}
    return {
        "uuid": dep.get("uuid"),
        "state": state.get("name"),
        "status": (state.get("status") or {}).get("name"),
        "environment": environment.get("name"),
        "environment_uuid": environment.get("uuid"),
        "commit": (commit.get("hash") or "")[:12] or None,
        "release_name": release.get("name"),
        "created_on": dep.get("created_on"),
        "last_update_time": dep.get("last_update_time"),
    }


def slim_deployment_list(data: Dict[str, Any]) -> Dict[str, Any]:
    """Slim a paginated list of deployments."""
    return _slim_paginated(data, slim_deployment)


def slim_deployment_variable(variable: Dict[str, Any]) -> Dict[str, Any]:
    """Slim a deployment environment variable.

    Secured variables never expose their value (the API omits it); force ``value``
    to None whenever ``secured`` is True so a secret is never surfaced even if the
    field leaks. Mirrors ``slim_pipeline_variable``.
    """
    secured = variable.get("secured") is True
    return {
        "uuid": variable.get("uuid"),
        "key": variable.get("key"),
        "value": None if secured else variable.get("value"),
        "secured": secured,
    }


def slim_deployment_variable_list(data: Dict[str, Any]) -> Dict[str, Any]:
    """Slim a paginated list of deployment variables."""
    return _slim_paginated(data, slim_deployment_variable)


# ========== Branch Restrictions & Workspace Governance ==========

def _slim_workspace_user(user: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Extract identity fields for governance APIs.

    Unlike ``_slim_user`` (which keeps the deprecated ``username``), this keeps the
    GDPR-era identifiers ``account_id`` and ``uuid`` — the only values accepted by
    ``get_workspace_member`` and by branch-restriction user payloads.
    """
    if not user:
        return None
    return {
        "account_id": user.get("account_id"),
        "display_name": user.get("display_name"),
        "nickname": user.get("nickname"),
        "uuid": user.get("uuid"),
    }


def slim_branch_restriction(restriction: Dict[str, Any]) -> Dict[str, Any]:
    """Slim a single branch restriction (branch protection rule)."""
    return {
        "id": restriction.get("id"),
        "kind": restriction.get("kind"),
        "pattern": restriction.get("pattern"),
        "branch_match_kind": restriction.get("branch_match_kind"),
        "branch_type": restriction.get("branch_type"),
        "value": restriction.get("value"),
        "users": [
            u.get("account_id") or u.get("display_name")
            for u in restriction.get("users") or []
        ],
        "groups": [
            g.get("slug") or g.get("name")
            for g in restriction.get("groups") or []
        ],
    }


def slim_branch_restriction_list(data: Dict[str, Any]) -> Dict[str, Any]:
    """Slim a paginated list of branch restrictions."""
    return _slim_paginated(data, slim_branch_restriction)


def slim_workspace_membership(member: Dict[str, Any]) -> Dict[str, Any]:
    """Slim a workspace membership (``/members``).

    The members endpoint carries no per-user permission — that lives on
    ``/permissions`` (see ``slim_workspace_permission``).
    """
    return {
        "user": _slim_workspace_user(member.get("user")),
    }


def slim_workspace_membership_list(data: Dict[str, Any]) -> Dict[str, Any]:
    """Slim a paginated list of workspace memberships."""
    return _slim_paginated(data, slim_workspace_membership)


def slim_workspace_permission(perm: Dict[str, Any]) -> Dict[str, Any]:
    """Slim a workspace permission entry (``/permissions``: permission + user)."""
    return {
        "permission": perm.get("permission"),
        "user": _slim_workspace_user(perm.get("user")),
    }


def slim_workspace_permission_list(data: Dict[str, Any]) -> Dict[str, Any]:
    """Slim a paginated list of workspace permissions."""
    return _slim_paginated(data, slim_workspace_permission)


def slim_repository_permission(perm: Dict[str, Any]) -> Dict[str, Any]:
    """Slim a repository permission entry (permission + user + repository)."""
    repository = perm.get("repository") or {}
    return {
        "permission": perm.get("permission"),
        "user": _slim_workspace_user(perm.get("user")),
        "repository": repository.get("full_name") or repository.get("name"),
    }


def slim_repository_permission_list(data: Dict[str, Any]) -> Dict[str, Any]:
    """Slim a paginated list of repository permissions."""
    return _slim_paginated(data, slim_repository_permission)
