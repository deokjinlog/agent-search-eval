"""Grep 에이전트 arm: 단어 검색 반복.

Claude Code를 헤드리스(-p)로 띄우고 도구를 Grep·Glob·Read 세 개로 제한한다.
작업 폴더는 기준 시점 스냅샷이라 .git이 없고, 파일을 고칠 도구도 없다.
호출 기록은 stream-json으로 받아 채점에 필요한 이벤트만 runs/<model>/<qid>/r<n>.jsonl.gz 에 남긴다 (trajectory).

    python -m ase.agent --golden data/golden.jsonl --runs 3 --model haiku --jobs 4
"""

from __future__ import annotations

import argparse
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .common import ROOT, load_golden, snapshot
from .slim import slim_file

RUNS_DIR = ROOT / "runs"
TOOLS = "Grep,Glob,Read"
MAX_TURNS = 30
TIMEOUT_S = 900

PROMPT = """이 폴더는 한 저장소의 특정 시점 코드입니다. 아래 변경 요청을 구현하려면 수정해야 할 기존 소스 파일을 찾으세요.

- 파일을 고치지 말고 찾기만 합니다.
- 테스트 파일, 문서, 데이터 파일은 답에서 뺍니다.
- 마지막 줄에는 저장소 루트 기준 상대경로의 JSON 배열 하나만 씁니다. 예: ["src/a.py", "web/b.html"]

변경 요청: {question}
"""

# 바깥 세션의 메모리·플러그인·추가 폴더·메시지 채널·브라우저 도구가 실험 세션에 섞이지 않게 뺀다.
STRIP_ENV = (
    "CLAUDE_CODE_ENABLE_CFC",
    "CLAUDE_CHROME_PERMISSION_MODE",
    "CLAUDE_CODE_CHROME_LATE_MCP_SERVER",
    "CLAUDE_CODE_INCLUDE_PARTIAL_MESSAGES",
    "CLAUDE_ADDITIONAL_DIRECTORIES",
    "CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD",
    "CLAUDE_CODE_POST_TURN_MEMORY",
    "CLAUDE_CODE_POST_TURN_MEMORY_CONFIG",
    "CLAUDE_CODE_SYNC_PLUGINS",
    "CLAUDE_CODE_SYNC_SKILLS",
    "CLAUDE_CODE_MESSAGING_SOCKET",
    "CLAUDE_CODE_MESSAGING_TOKEN",
    "CLAUDE_CODE_TEE_SDK_STDOUT",
    "CLAUDE_CODE_DIAGNOSTICS_FILE",
)


def command(model: str, question: str) -> list[str]:
    return [
        "claude", "-p", PROMPT.format(question=question),
        "--model", model,
        "--tools", TOOLS,
        "--disallowedTools", "mcp__claude-in-chrome",
        "--max-turns", str(MAX_TURNS),
        "--output-format", "stream-json", "--verbose",
        "--strict-mcp-config",
        "--setting-sources", "project",
        "--no-session-persistence",
    ]


def run_one(q: dict, n: int, model: str) -> tuple[str, int, str]:
    out = RUNS_DIR / model / q["qid"] / f"r{n}.jsonl"
    if out.with_name(out.name + ".gz").exists() or (out.exists() and '"type":"result"' in out.read_text(encoding="utf-8")):
        return q["qid"], n, "skip"
    out.parent.mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if k not in STRIP_ENV}
    with out.open("w", encoding="utf-8") as f:
        try:
            proc = subprocess.run(command(model, q["question"]), cwd=snapshot(q), env=env,
                                  stdout=f, stderr=subprocess.PIPE, text=True, timeout=TIMEOUT_S)
            status = "ok" if proc.returncode == 0 else f"exit {proc.returncode}: {proc.stderr[-200:]}"
        except subprocess.TimeoutExpired:
            status = "timeout"
    slim_file(out)  # 채점에 필요한 이벤트만 남겨 r<n>.jsonl.gz로 줄인다
    return q["qid"], n, status


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--golden", default="data/golden.jsonl")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--model", default="haiku")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--only", nargs="*", help="이 qid만 실행")
    args = ap.parse_args(argv)
    qs = [q for q in load_golden(args.golden) if not args.only or q["qid"] in args.only]
    for q in qs:
        snapshot(q)
    jobs = [(q, n) for n in range(1, args.runs + 1) for q in qs]
    with ThreadPoolExecutor(args.jobs) as pool:
        futures = [pool.submit(run_one, q, n, args.model) for q, n in jobs]
        for i, fut in enumerate(as_completed(futures), 1):
            qid, n, status = fut.result()
            print(f"[{i}/{len(jobs)}] {qid} r{n} {status}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
