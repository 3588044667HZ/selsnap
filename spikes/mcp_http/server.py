import argparse
import threading

from mcp.server.mcpserver import MCPServer

mcp = MCPServer("spike-streamable-http", version="1.0.0")

_counter = 0
_counter_lock = threading.Lock()


@mcp.tool()
def echo(text: str) -> str:
    """原样返回输入文本。"""
    return text


@mcp.tool()
def counter() -> int:
    """返回服务端全局递增计数。"""
    global _counter
    # 同步工具由 SDK 放到工作线程执行，加锁保证并发调用下计数不丢。
    with _counter_lock:
        _counter += 1
        return _counter


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--path", default="/mcp")
    args = parser.parse_args()
    mcp.run(
        transport="streamable-http",
        host=args.host,
        port=args.port,
        streamable_http_path=args.path,
    )


if __name__ == "__main__":
    main()
