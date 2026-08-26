"""Live subprocess output capture for the SotN randomizer command."""

import asyncio
import sys
from pathlib import Path
from typing import TextIO


async def run_process(*command: str, cwd: Path) -> tuple[str, str]:
    process = await asyncio.create_subprocess_exec(
        *command,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    assert process.stdout is not None
    assert process.stderr is not None
    stdout_text, stderr_text = await asyncio.gather(
        _capture_and_echo(process.stdout, sys.stdout),
        _capture_and_echo(process.stderr, sys.stderr),
    )
    await process.wait()
    if process.returncode != 0:
        detail = (stderr_text or stdout_text).strip()
        raise RuntimeError(f"Command exited with code {process.returncode}: {detail[-1000:]}")
    return stdout_text, stderr_text


async def _capture_and_echo(stream: asyncio.StreamReader, destination: TextIO) -> str:
    chunks = []
    while chunk := await stream.readline():
        text = chunk.decode(errors="replace")
        chunks.append(text)
        print(text, end="", file=destination, flush=True)
    return "".join(chunks)
