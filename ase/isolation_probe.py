"""격리 점검: 같은 한 마디 질문을 격리 수준만 바꿔 헤드리스로 돌리고, system/init에 무엇이 실렸는지 센다.

에이전트 실험(ase.agent)을 돌리기 전에 바깥 세션의 도구·MCP·플러그인·스트림 설정이 섞이는지 확인하는 용도다.
플러그인·스킬은 이름 대신 개수만 남긴다.

    python -m ase.isolation_probe            # → results/isolation_probe.json
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
from pathlib import Path

from .agent import STRIP_ENV

PROMPT = "파일 목록을 보지 말고 '안녕'이라고만 답하세요."
BASE = ["claude", "-p", PROMPT, "--model", "haiku", "--output-format", "stream-json", "--verbose", "--max-turns", "1"]
TOOLS = ["--tools", "Grep,Glob,Read"]
FLAGS = ["--strict-mcp-config", "--setting-sources", "project", "--no-session-persistence"]
CASES = {
    "A 아무것도 안 함": (BASE, False),
    "B --tools만": (BASE + TOOLS, False),
    "C B + 격리 플래그 3개": (BASE + TOOLS + FLAGS, False),
    "D C + --no-chrome": (BASE + TOOLS + FLAGS + ["--no-chrome"], False),
    "E C + --disallowedTools mcp__*": (BASE + TOOLS + FLAGS + ["--disallowedTools", "mcp__*"], False),
    "F 실험 설정 (C + 크롬 MCP 거부 + 환경변수 제거)": (BASE + TOOLS + ["--disallowedTools", "mcp__claude-in-chrome"] + FLAGS, True),
}


def probe(cmd: list[str], strip: bool, cwd: str) -> dict:
    env = {k: v for k, v in os.environ.items() if not (strip and k in STRIP_ENV)}
    p = subprocess.run(cmd, env=env, cwd=cwd, capture_output=True, text=True, timeout=300)
    ev = [json.loads(line) for line in p.stdout.splitlines() if line.strip().startswith("{")]
    init = next((e for e in ev if e.get("type") == "system" and e.get("subtype") == "init"), {})
    tools = init.get("tools", [])
    res = next((e for e in ev if e.get("type") == "result"), {})
    u = res.get("usage") or {}
    return {
        "tools": len(tools),
        "mcp_tools": sum(t.startswith("mcp__") for t in tools),
        "mcp_servers": len(init.get("mcp_servers", [])),
        "plugins": len(init.get("plugins", [])),
        "skills": len(init.get("skills", []) or []),
        "stream_events": sum(e.get("type") == "stream_event" for e in ev),
        "other_event_types": sorted({e.get("type") for e in ev} - {"system", "assistant", "result", "stream_event", "user"}),
        "input_tokens_total": sum((u.get(k) or 0) for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")),
        "exit": p.returncode,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-o", "--output", default="results/isolation_probe.json")
    args = ap.parse_args(argv)
    version = subprocess.run(["claude", "--version"], capture_output=True, text=True).stdout.strip()
    with tempfile.TemporaryDirectory() as empty:
        out = {"claude_version": version, "env_set_in_parent": sorted(k for k in STRIP_ENV if k in os.environ),
               "cases": {name: probe(cmd, strip, empty) for name, (cmd, strip) in CASES.items()}}
    Path(args.output).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    for name, r in out["cases"].items():
        print(f"{name:40s} 도구 {r['tools']:2d} (MCP {r['mcp_tools']:2d})  MCP 서버 {r['mcp_servers']}  플러그인 {r['plugins']}  "
              f"스킬 {r['skills']:2d}  stream_event {r['stream_events']}  input 토큰 {r['input_tokens_total']:,}")
    print(f"→ {args.output} ({version})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
