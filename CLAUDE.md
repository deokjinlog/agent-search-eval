# agent-search-eval

Grep 에이전트(Claude Code 헤드리스) vs BM25 파일 탐색 실험. 실행 순서와 결과는 README.md.

## 원칙
- 질문 속성(has_identifier 등)은 결과를 보기 전에 붙인다. 결과를 보고 슬라이스를 새로 만들면 README에 사후 분석이라고 적는다.
- 에이전트 실행은 격리한다(ase/agent.py의 STRIP_ENV, --strict-mcp-config, 도구는 Grep·Glob·Read만). 격리를 풀지 않는다.
- 실행 기록은 ase/slim.py로 줄인 것만 커밋한다. 세션 메타데이터·사용량 이벤트는 남기지 않는다.
- 결과 숫자를 글이나 README에 옮길 때는 results/summary.json에서 옮긴다.

## 명령
- 테스트: `python -m pytest -q`
- 요약: `python -m ase.report --models haiku sonnet`
