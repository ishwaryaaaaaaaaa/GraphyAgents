"""Start mcp_server.py over stdio and talk to it with a real MCP client."""
import asyncio
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parent.parent


async def main():
    params = StdioServerParameters(command=sys.executable, args=[str(ROOT / "mcp_server.py")],
                                   cwd=str(ROOT))
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print("tools:", sorted(t.name for t in tools.tools))
            r = await session.call_tool("remember", {"user": "mcp_smoke", "key": "diet_style",
                                                     "value": "vegetarian", "day": 1})
            print("remember ->", r.content[0].text)
            r = await session.call_tool("get_facts", {"user": "mcp_smoke", "day": 1})
            print("get_facts ->", r.content[0].text)


if __name__ == "__main__":
    asyncio.run(main())
