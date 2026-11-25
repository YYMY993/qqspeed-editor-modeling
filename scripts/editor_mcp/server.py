"""QQ Speed editor MCP. Stdout is reserved for the stdio protocol."""
import sys
from threading import Lock
from typing import Literal

from mcp.server.fastmcp import FastMCP

from controller import Controller
from panel import Unavailable

app = FastMCP("qqspeed-editor")
control = Controller()
lock = Lock()


def run(call, *args):
    with lock:
        try:
            return call(*args)
        except Unavailable as exc:
            return {"status": "blocked", "reason": str(exc)}
        except Exception as exc:
            print(f"Editor error: {exc!r}", file=sys.stderr)
            return {"status": "error", "reason": type(exc).__name__}


@app.tool()
def editor_status() -> dict:
    """Find the Windows editor and check input privilege and foreground, without capturing an image."""
    return run(control.status)


@app.tool()
def read_editor(activate: bool = False) -> dict:
    """Read the current panel. For a selected primitive return 12 named decimal fields.
    Set activate=true to bring the editor forward. A writable observation expires after 60 seconds."""
    return run(control.observe, activate)


@app.tool()
def nudge_field(observation: str,
                field: Literal["position.x", "position.y", "position.z",
                               "rotation.x", "rotation.y", "rotation.z"],
                expected_before: str, expected_after: str) -> dict:
    """Click one named +/- button once. expected_after is the exact value expected after ONE step.
    Acquire a fresh observation per call. Only verified indicates success. Never auto-retry uncertain."""
    return run(control.nudge, observation, field, expected_before, expected_after)


if __name__ == "__main__":
    app.run(transport="stdio")
