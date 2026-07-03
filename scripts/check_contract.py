#!/usr/bin/env python3
"""check_contract.py — 자산 계약(Asset Contract) 기계 검증기. CMPA-161/162 Phase 1.

자산의 input/run/output 규약을 적은 계약 yaml(예: contracts/whisky-price-intelligence.yaml)을
읽어, **이미 생성된 OUTPUT 산출물**이 계약을 지키는지 검사한다.

검증 항목(OUTPUT 프로토콜):
  (a) 선언된 각 artifact 파일이 실제로 존재하는가.
  (b) CSV artifact 의 실제 헤더가 계약 `schema` 필드를 **모두 포함**하는가(누락=FAIL).
  (c) artifact 의 `required_meta` 마커(예: report_date='리포트 생성일',
      collected_date='데이터 기준일')가 산출물 안에 실제로 존재하는가(+패턴).
  (d) `invariants` 중 `machine_check: true` 인 것(예: totals 토큰 1,829/1,435 가
      리포트에 그대로 살아있는지)을 검사.

설계 규약:
  - **결정론적·네트워크 호출 없음.** 이미 디스크에 있는 산출물만 읽는다.
  - 위반 시 비0 exit + 위반 항목을 한 줄씩 명확히 출력.
  - PASS 시 마지막 줄에 `CONTRACT OK: <asset> v<version>`.

용법:
  python3 scripts/check_contract.py --contract contracts/whisky-price-intelligence.yaml
"""
from __future__ import annotations

import argparse
import csv
import glob as _glob
import os
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    print("FAIL: PyYAML 미설치 — `pip install pyyaml` 필요", file=sys.stderr)
    raise SystemExit(2)


def _repo_root(contract_path: Path) -> Path:
    """계약은 <root>/contracts/<asset>.yaml 에 산다 → root = contracts 의 부모."""
    p = contract_path.resolve()
    if p.parent.name == "contracts":
        return p.parent.parent
    return p.parent  # 폴백: 계약 파일과 같은 디렉터리를 root 로


def _read_header(path: Path, encoding: str) -> list[str]:
    with open(path, encoding=encoding, newline="") as f:
        reader = csv.reader(f)
        for row in reader:
            return [c.strip() for c in row]
    return []


def _resolve_artifact(root: Path, art: dict, violations: list[str]) -> Path | None:
    """artifact 파일 경로를 해석. glob/resolve 가 있으면 그걸로 실제 파일을 고른다."""
    aid = art.get("id", "?")
    g = art.get("glob")
    if g:
        matches = sorted(_glob.glob(str(root / g)))
        if not matches:
            violations.append(f"[{aid}] artifact 없음: glob `{g}` 매칭 0건")
            return None
        # resolve: latest_by_filename → 파일명 사전순 최신(YYYY-MM-DD 박힌 정본 규약)
        chosen = matches[-1] if art.get("resolve", "latest_by_filename") == "latest_by_filename" else matches[0]
        return Path(chosen)
    # glob 없으면 path 를 그대로(placeholder <...> 없는 정확 경로여야 함)
    path = art.get("path", "")
    if "<" in path or "*" in path:
        violations.append(f"[{aid}] path 에 placeholder/glob 가 있으나 `glob:` 미정의 → 해석 불가: {path}")
        return None
    p = root / path
    if not p.exists():
        violations.append(f"[{aid}] artifact 없음: {path}")
        return None
    return p


def _check_schema(aid: str, fpath: Path, art: dict, violations: list[str]) -> None:
    schema = art.get("schema")
    if not schema:
        return
    enc = art.get("encoding", "utf-8")
    header = _read_header(fpath, enc)
    missing = [c for c in schema if c not in header]
    if missing:
        violations.append(
            f"[{aid}] schema 위반: 헤더에 누락된 컬럼 {missing} "
            f"(실제 헤더: {header})"
        )


def _check_required_meta(aid: str, fpath: Path, art: dict, violations: list[str]) -> None:
    req = art.get("required_meta")
    if not req:
        return
    text = fpath.read_text(encoding=art.get("encoding", "utf-8"), errors="replace")
    for meta in req:
        key = meta.get("key", "?")
        marker = meta.get("marker", "")
        if marker and marker not in text:
            violations.append(f"[{aid}] required_meta '{key}' 누락: 마커 '{marker}' 를 산출물에서 못 찾음")
            continue
        pat = meta.get("pattern")
        if pat:
            # 마커 뒤(같은 줄/근처)에 패턴이 있는지 — 우선 문서 전역에서 패턴 존재 확인
            if not re.search(pat, text):
                violations.append(f"[{aid}] required_meta '{key}': 마커는 있으나 패턴 /{pat}/ 매칭 없음")


def _check_invariants(root: Path, artifacts_by_id: dict, invariants: list, violations: list[str]) -> None:
    for inv in invariants:
        if not isinstance(inv, dict) or not inv.get("machine_check"):
            continue
        iid = inv.get("id", "?")
        target = inv.get("artifact")
        fpath = artifacts_by_id.get(target)
        if fpath is None:
            violations.append(f"[invariant {iid}] 대상 artifact '{target}' 를 해석하지 못해 검사 불가")
            continue
        text = fpath.read_text(encoding="utf-8", errors="replace")
        for token in inv.get("must_contain", []):
            if token not in text:
                violations.append(
                    f"[invariant {iid}] 위반: 필수 토큰 '{token}' 가 {target} 에 없음 — {inv.get('rule','')}"
                )


def main() -> int:
    ap = argparse.ArgumentParser(description="자산 계약 기계 검증기 (결정론적·네트워크 없음)")
    ap.add_argument("--contract", required=True, help="계약 yaml 경로")
    args = ap.parse_args()

    contract_path = Path(args.contract)
    if not contract_path.exists():
        print(f"FAIL: 계약 파일 없음 {contract_path}", file=sys.stderr)
        return 2

    contract = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
    root = _repo_root(contract_path)
    asset = contract.get("asset", "?")
    version = contract.get("version", "?")

    print(f"[check_contract] asset={asset} v{version} (root={root})")

    output = contract.get("output", {}) or {}
    artifacts = output.get("artifacts", []) or []
    invariants = output.get("invariants", []) or []

    violations: list[str] = []
    artifacts_by_id: dict[str, Path] = {}

    # (a) 존재 + 해석
    for art in artifacts:
        aid = art.get("id", "?")
        fpath = _resolve_artifact(root, art, violations)
        if fpath is None:
            continue
        artifacts_by_id[aid] = fpath
        rel = os.path.relpath(fpath, root)
        print(f"  [artifact] {aid} → {rel}")
        # (b) schema
        _check_schema(aid, fpath, art, violations)
        # (c) required_meta
        _check_required_meta(aid, fpath, art, violations)

    # (d) invariants(machine_check)
    _check_invariants(root, artifacts_by_id, invariants, violations)

    if violations:
        print(f"\nCONTRACT VIOLATION: {asset} v{version} — {len(violations)}건")
        for v in violations:
            print(f"  ✗ {v}")
        return 1

    print(f"\nCONTRACT OK: {asset} v{version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
