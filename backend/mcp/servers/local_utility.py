"""Read-only local utility tools used to validate and extend agent orchestration."""

import json
from datetime import UTC, datetime

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("AniOS Local Utilities")


# Return the current UTC time without relying on model knowledge or host locale.
@mcp.tool()
async def current_time() -> str:
    """Return the current UTC date and time."""
    now = datetime.now(UTC)
    return json.dumps(
        {
            "timezone": "UTC",
            "iso8601": now.isoformat(timespec="seconds"),
            "utc_offset": "+0000",
        }
    )


# Run the local utility server over stdio for the AniOS MCP client.
def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
