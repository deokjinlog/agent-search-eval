"""실행 기록을 채점에 필요한 것만 남겨 gzip으로 줄인다.

남기는 것: 도구 호출·도구 결과·답 텍스트·호출별 usage·최종 result의 주요 값.
버리는 것: 세션 초기화 정보(경로·설정), 사용량 한도 이벤트, thinking 블록, 기타 시스템 이벤트.

    python -m ase.slim runs/haiku runs/sonnet
"""

from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

RESULT_KEYS = ("type", "subtype", "is_error", "result", "num_turns", "duration_ms", "total_cost_usd", "usage", "modelUsage")
USAGE_KEYS = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens")


def slim_event(e: dict) -> dict | None:
    t = e.get("type")
    if t == "assistant":
        m = e["message"]
        content = [c for c in m.get("content", []) if c.get("type") in ("text", "tool_use")]
        usage = {k: (m.get("usage") or {}).get(k, 0) for k in USAGE_KEYS}
        return {"type": t, "message": {"id": m["id"], "model": m.get("model"), "content": content, "usage": usage}}
    if t == "user":
        content = e.get("message", {}).get("content", [])
        if isinstance(content, list):
            content = [c for c in content if c.get("type") == "tool_result"]
            if content:
                return {"type": t, "message": {"content": content}}
        return None
    if t == "result":
        return {k: e[k] for k in RESULT_KEYS if k in e}
    return None


def slim_file(path: Path) -> Path:
    raw = gzip.decompress(path.read_bytes()).decode("utf-8") if path.suffix == ".gz" else path.read_text(encoding="utf-8")
    events = [slim_event(json.loads(line)) for line in raw.splitlines() if line.strip()]
    text = "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events if e)
    out = path if path.suffix == ".gz" else path.with_name(path.name + ".gz")
    out.write_bytes(gzip.compress(text.encode("utf-8"), compresslevel=9, mtime=0))
    if out != path:
        path.unlink()
    return out


def main(argv=None) -> int:
    dirs = [Path(d) for d in (argv if argv is not None else sys.argv[1:])]
    files = [p for d in dirs for p in sorted(d.rglob("r*.jsonl*"))]
    for p in files:
        slim_file(p)
    print(f"{len(files)}개 정리")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
