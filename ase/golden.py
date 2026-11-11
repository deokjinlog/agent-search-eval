"""커밋 기록으로 골든셋을 만든다 (SWE-bench 방식).

질문 하나 = 커밋 하나.
- 질문 텍스트: 커밋 제목에서 'feat(scope):' 같은 앞머리를 뗀 문장
- 정답: 그 커밋이 '수정'한 코드 파일 (테스트·문서·데이터 제외, 새로 만든 파일 제외)
- 기준 시점: 부모 커밋 (에이전트와 BM25는 이 시점의 파일만 본다)
- 질문 속성(결과를 보기 전에 붙임): 질문에 기준 시점 코드와 같은 영문 단어가 있는가 (has_identifier)

    python -m ase.golden --repo ../deokjinlog/should-i-still-hold-this-stock --repo ... -o data/golden.jsonl
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

CODE_EXT = {".py", ".js", ".mjs", ".ts", ".html"}
TEST_PATTERN = re.compile(r"(^|/)tests?/|(^|/)test_[^/]*$|_test\.[a-z]+$|\.test\.[a-z]+$|(^|/)test_cases\.py$")
SKIP_TYPES = {"docs", "data", "chore", "style", "test", "tests", "ci", "build", "revert", "merge"}
PREFIX = re.compile(r"^(?P<type>[a-zA-Z]+)(\([^)]*\))?!?:\s*")
IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")
MAX_GOLD = 4
MAX_CHANGED = 12


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout


def is_code(path: str) -> bool:
    return Path(path).suffix in CODE_EXT and not TEST_PATTERN.search(path)


def question_text(subject: str) -> tuple[str, str | None]:
    m = PREFIX.match(subject)
    if not m:
        return subject.strip(), None
    return subject[m.end():].strip(), m.group("type").lower()


def code_identifiers(repo: Path, commit: str) -> set[str]:
    """기준 시점 코드 파일(테스트 제외)에 나오는 영문 단어(3자 이상)와 파일 이름."""
    names: set[str] = set()
    for path in git(repo, "ls-tree", "-r", "--name-only", commit).splitlines():
        if not is_code(path):
            continue
        names.add(Path(path).stem)
        names.update(IDENT.findall(git(repo, "show", f"{commit}:{path}")))
    return names


def candidates(repo: Path):
    log = git(repo, "log", "--no-merges", "--format=%H%x1f%P%x1f%s", "--reverse")
    for line in log.splitlines():
        sha, parents, subject = line.split("\x1f")
        if not parents or " " in parents:
            continue
        text, ctype = question_text(subject)
        if ctype in SKIP_TYPES:
            continue
        status = git(repo, "diff", "--name-status", "--no-renames", parents, sha).splitlines()
        if not status or len(status) > MAX_CHANGED:
            continue
        gold = sorted(p for s, p in (row.split("\t", 1) for row in status) if s == "M" and is_code(p))
        if not 1 <= len(gold) <= MAX_GOLD:
            continue
        yield {"commit": sha, "base": parents, "subject": subject, "question": text, "type": ctype, "gold": gold}


def build(repos: list[Path]) -> list[dict]:
    rows = []
    for repo in repos:
        name = repo.resolve().name
        for i, c in enumerate(candidates(repo), 1):
            idents = code_identifiers(repo, c["base"])
            hits = sorted({t for t in IDENT.findall(c["question"]) if t in idents})
            rows.append({
                "qid": f"{name[:5]}-{c['commit'][:7]}",
                "repo": name,
                **c,
                "has_identifier": bool(hits),
                "identifiers": hits,
            })
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", action="append", required=True, type=Path)
    ap.add_argument("-o", "--output", type=Path, default=Path("data/golden.jsonl"))
    args = ap.parse_args(argv)
    rows = build(args.repo)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"질문 {len(rows)}개 → {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
