# Changelog - Bitbucket MCP Server Python

## [1.1.0] - 2025-10-31

### 🎉 New Features

#### API Client
- **`get_pull_request_statuses()`** - Retrieves CI/CD build statuses (Jenkins, tests)
- **`get_pull_request_diffstat()`** - Retrieves file modification statistics

#### MCP Tools
- **`get_pull_request_statuses`** - MCP tool to get build statuses
- **`get_pull_request_diffstat`** - MCP tool to get diff statistics

### 📊 Technical Details

#### get_pull_request_statuses
Retrieves build/CI statuses associated with a pull request.

**Endpoint**: `/repositories/{workspace}/{repo}/pullrequests/{id}/statuses`

**Returns**:
- `state`: SUCCESSFUL, FAILED, INPROGRESS, STOPPED
- `key`: Unique build identifier
- `name`: Build name/description
- `url`: Link to build details
- `created_on`: Status timestamp

**Response example**:
```json
{
  "values": [
    {
      "state": "SUCCESSFUL",
      "name": "Jenkins » my-api » feature/branch #5",
      "url": "https://jenkins...",
      "description": "This commit looks good."
    }
  ]
}
```

#### get_pull_request_diffstat
Retrieves modification statistics for each PR file.

**Endpoint**: Dynamically uses the URL from PR's `links.diffstat.href`

**Returns**:
- `status`: modified, added, removed, renamed
- `lines_added`: Number of lines added
- `lines_removed`: Number of lines removed
- `new.path`: File path after modifications

**Response example**:
```json
{
  "values": [
    {
      "status": "modified",
      "new": {"path": "src/repositories/users/userRepositoryV2Impl.ts"},
      "lines_added": 56,
      "lines_removed": 28
    }
  ]
}
```

### ✅ Tests

- Unit tests added to verify new methods presence
- Integration tests validated on real PR #873
- 11/11 tests passing successfully

### 📈 Validation on PR #873

**get_pull_request_statuses**:
- ✅ 1 Jenkins status found
- State: SUCCESSFUL
- Build #5 on feature branch

**get_pull_request_diffstat**:
- ✅ 5 files modified
- Total: +102 lines, -74 lines
- TypeScript files and tests affected

### 🔧 Changes

#### Modified files:
1. `src/client.py` - Added 2 new methods (+81 lines)
2. `src/server.py` - Added 2 new MCP tools (+54 lines)
3. `README.md` - Documentation of new features
4. `tests/test_client.py` - Methods presence test
5. `tests/test_server.py` - Tools registration test

### 📦 Deployment

Container rebuilt and redeployed successfully:
- Image: `bitbucket-mcp-py:latest`
- Build ID: `de10583516b7`
- Container: `f1cadb56342a`

---

## [1.0.0] - 2025-10-31

### Initial Version

- Correct Basic Auth authentication
- 20+ initial MCP tools
- Podman container support
- Complete unit tests
- Comprehensive documentation
