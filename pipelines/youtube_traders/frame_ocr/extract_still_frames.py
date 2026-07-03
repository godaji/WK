#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
extract_still_frames.py — CMPA-423 (1/3) 정지프레임 추출 (ASR 우회 OCR 파이프라인)

유튜브 위스키 가격영상(@whiskeypick·@whiskeykey)은 진행자가 **가격표(합성 오버레이)가
또렷이 보이는 지점에서 화면을 ≥0.5초 정지**시킨다. 이 스크립트는 영상을 N fps 로 샘플해
**인접 프레임 절대평균차(diff)가 임계 이하로 ≥min_still_sec 연속 유지되는 구간 = 정지구간**
을 검출하고, 구간당 대표 1장(가운데 프레임)을 저장한다.

⚠️ 이 환경엔 **ffmpeg 가 없다** → `cv2.VideoCapture` 로 mp4 를 직접 디코딩한다(ffmpeg 의존 금지).

용법:
  python3 extract_still_frames.py VIDEO.mp4 --video-id k3GQq_-rD1k --out-dir frames/ \\
      [--fps 5] [--min-still-sec 0.5] [--diff-thresh 3.0] [--max-frames 0]

산출:
  frames/{video_id}_{HHMMSS}.jpg   대표 정지프레임(연속 중복 정지구간 dedup)
  frames/manifest.csv              video_id,t_sec,hhmmss,path,mean_diff,n_frames
"""
import argparse
import csv
import os
import sys

import cv2
import numpy as np


def hhmmss(t_sec: float) -> str:
    t = int(round(t_sec))
    return f"{t // 3600:02d}{(t % 3600) // 60:02d}{t % 60:02d}"


def downscale_gray(frame, width=320):
    """diff 계산용: 그레이스케일 + 다운스케일(노이즈·연산량 절감)."""
    h, w = frame.shape[:2]
    if w > width:
        frame = cv2.resize(frame, (width, int(h * width / w)), interpolation=cv2.INTER_AREA)
    return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)


def _roi_view(small, roi):
    """다운스케일 그레이의 ROI(상대좌표 x0,y0,x1,y1) 하위영역을 반환. roi=None 이면 전체.
    @whiskeykey 처럼 **가격표 영역이 우측 상단에 고정**된 walking-tour 영상은, 배경(매대)이
    계속 움직여 전역 diff 가 늘 커서 정지검출이 실패한다. 가격표 ROI 안에서만 diff 를 재면
    배경 움직임을 무시하고 **오버레이(제품/가격)가 바뀌는 시점**에만 변화가 잡힌다(보드 지시)."""
    if not roi:
        return small
    h, w = small.shape[:2]
    x0, y0, x1, y1 = roi
    ax0, ay0 = max(0, int(x0 * w)), max(0, int(y0 * h))
    ax1, ay1 = min(w, int(x1 * w)), min(h, int(y1 * h))
    if ax1 - ax0 < 4 or ay1 - ay0 < 4:
        return small
    return small[ay0:ay1, ax0:ax1]


def extract(video_path, video_id, out_dir, fps=5.0, min_still_sec=0.5,
            diff_thresh=3.0, max_frames=0, roi=None, gap_fill_sec=30.0):
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise SystemExit(f"[still] 영상 열기 실패(cv2): {video_path}")
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    dur = total / src_fps if total else 0
    step = max(1, int(round(src_fps / fps)))          # 원본 프레임 N개마다 1개 샘플
    eff_fps = src_fps / step                            # 실제 샘플링 fps
    min_run = max(2, int(round(min_still_sec * eff_fps)))  # 정지로 인정할 최소 연속 샘플 수
    print(f"[still] {video_path}: {src_fps:.1f}fps src, {total}f (~{dur:.0f}s), "
          f"sample step={step} (~{eff_fps:.1f}fps), still>={min_run} samples "
          f"(>= {min_still_sec}s), diff<{diff_thresh}"
          f"{f', roi={roi}' if roi else ''}", file=sys.stderr)

    os.makedirs(out_dir, exist_ok=True)
    manifest = []

    prev_small = None
    # run = 현재까지 누적된 정지 프레임들 [(idx, frame, diff), ...]
    run = []
    idx = 0           # 샘플 인덱스 기준 원본 프레임 번호
    sampled = 0

    def flush_run():
        """정지 구간이 충분히 길면 가운데 프레임을 대표로 저장."""
        if len(run) < min_run:
            return
        mid = run[len(run) // 2]
        f_idx, frame, _ = mid
        t_sec = f_idx / src_fps
        tag = hhmmss(t_sec)
        path = os.path.join(out_dir, f"{video_id}_{tag}.jpg")
        # 같은 초에 두 구간이 떨어지면 파일명 충돌 → 접미사
        suffix = 0
        while os.path.exists(path):
            suffix += 1
            path = os.path.join(out_dir, f"{video_id}_{tag}_{suffix}.jpg")
        cv2.imwrite(path, frame, [cv2.IMWRITE_JPEG_QUALITY, 92])
        mean_diff = float(np.mean([d for _, _, d in run[1:]])) if len(run) > 1 else 0.0
        manifest.append({
            "video_id": video_id, "t_sec": round(t_sec, 2), "hhmmss": tag,
            "path": os.path.relpath(path, out_dir), "mean_diff": round(mean_diff, 3),
            "n_frames": len(run),
        })

    while True:
        ok = cap.grab()
        if not ok:
            break
        if idx % step == 0:
            ok, frame = cap.retrieve()
            if not ok:
                break
            small = _roi_view(downscale_gray(frame), roi)   # roi=None 이면 전체(whiskeypick)
            if prev_small is not None and prev_small.shape == small.shape:
                diff = float(np.mean(cv2.absdiff(small, prev_small)))
            else:
                diff = 0.0
            prev_small = small
            sampled += 1
            if diff < diff_thresh:
                run.append((idx, frame, diff))          # 정지 지속
            else:
                flush_run()                              # 움직임 → 직전 정지구간 마감
                run = [(idx, frame, diff)]               # 새 구간 시작(현 프레임이 기준)
            if max_frames and sampled >= max_frames:
                break
        idx += 1
    flush_run()
    cap.release()

    # dedup: 인접 대표 프레임이 사실상 동일(같은 위스키 정지가 끊겼다 이어진 경우)하면 병합.
    # roi 가 있으면 가격표 영역에서만 비교(배경이 비슷해도 다른 제품이면 보존).
    # gap_fill_sec 보다 멀리 떨어진 프레임은 dedup 에서 보호한다.
    manifest = _dedup_adjacent(manifest, out_dir, roi=roi, max_time_gap=gap_fill_sec)

    # 슬라이드형 영상(Costco 등) — 정지검출이 놓친 큰 구간에 강제 샘플 추가.
    if gap_fill_sec > 0 and dur > 0:
        manifest = _gap_fill(manifest, video_path, video_id, out_dir, dur, gap_fill_sec)

    # 커버리지 경고: 마지막 프레임이 영상 총 길이의 50% 이전이면 경고.
    if dur > 0 and manifest:
        last_t = manifest[-1]["t_sec"]
        coverage = last_t / dur
        if coverage < 0.5:
            print(f"[still] ⚠️  커버리지 {coverage:.0%} (마지막 프레임 {last_t:.0f}s / 총 {dur:.0f}s) "
                  f"— 영상 후반 누락 가능. gap_fill_sec={gap_fill_sec}", file=sys.stderr)

    mpath = os.path.join(out_dir, "manifest.csv")
    with open(mpath, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["video_id", "t_sec", "hhmmss", "path",
                                          "mean_diff", "n_frames"])
        w.writeheader()
        w.writerows(manifest)
    print(f"[still] 정지구간 {len(manifest)}개 저장 → {out_dir} (manifest: {mpath})",
          file=sys.stderr)
    return manifest


def _dedup_adjacent(manifest, out_dir, sim_thresh=2.0, roi=None, max_time_gap=30.0):
    """연속 대표 프레임이 거의 동일하면(같은 화면 정지가 잠깐 끊긴 것) 뒤엣것 제거.
    roi 가 있으면 가격표 영역에서만 비교(배경 유사·제품 상이 시 보존).
    max_time_gap 초보다 멀리 떨어진 프레임은 시각적 유사성과 무관하게 보존한다
    (슬라이드형 영상에서 마지막 닫는 슬라이드가 첫 슬라이드와 비슷해 지워지는 버그 방지)."""
    if len(manifest) < 2:
        return manifest
    kept = [manifest[0]]
    prev = _roi_view(downscale_gray(cv2.imread(os.path.join(out_dir, manifest[0]["path"]))), roi)
    for m in manifest[1:]:
        t_gap = m["t_sec"] - kept[-1]["t_sec"]
        if t_gap > max_time_gap:
            # 시간 간격이 크면 다른 콘텐츠 — 유사도 무관하게 보존
            cur = _roi_view(downscale_gray(cv2.imread(os.path.join(out_dir, m["path"]))), roi)
            kept.append(m); prev = cur; continue
        cur = _roi_view(downscale_gray(cv2.imread(os.path.join(out_dir, m["path"]))), roi)
        if cur.shape != prev.shape:
            kept.append(m); prev = cur; continue
        d = float(np.mean(cv2.absdiff(cur, prev)))
        if d < sim_thresh:
            os.remove(os.path.join(out_dir, m["path"]))   # 중복 파일 삭제
            continue
        kept.append(m)
        prev = cur
    return kept


def _gap_fill(manifest, video_path, video_id, out_dir, dur, gap_fill_sec=30.0):
    """manifest 에 gap_fill_sec 초 이상 비어있는 구간이 있으면 강제 샘플 프레임을 추가한다.
    슬라이드형 영상(Costco 가격표 슬라이드)처럼 diff 임계가 걸리지 않아 정지검출이 누락하는
    구간을 보완한다. 강제 샘플은 mean_diff=-1.0, n_frames=0 으로 표기해 정상 정지구간과 구분."""
    boundaries = [0.0] + [m["t_sec"] for m in manifest] + [dur]
    extras = []
    cap = cv2.VideoCapture(video_path)
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0

    for i in range(len(boundaries) - 1):
        seg_start = boundaries[i] + (1.0 if i > 0 else 0.0)
        seg_end = boundaries[i + 1] - (1.0 if i < len(boundaries) - 2 else 0.0)
        gap = seg_end - seg_start
        if gap < gap_fill_sec:
            continue
        n = max(1, int(gap // gap_fill_sec))
        interval = gap / n
        for j in range(n):
            t = seg_start + interval * (j + 0.5)
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
            ok, frame = cap.read()
            if not ok:
                continue
            tag = hhmmss(t)
            path = os.path.join(out_dir, f"{video_id}_{tag}_gf.jpg")
            suffix = 0
            while os.path.exists(path):
                suffix += 1
                path = os.path.join(out_dir, f"{video_id}_{tag}_gf{suffix}.jpg")
            cv2.imwrite(path, frame, [cv2.IMWRITE_JPEG_QUALITY, 92])
            extras.append({
                "video_id": video_id, "t_sec": round(t, 2), "hhmmss": tag,
                "path": os.path.relpath(path, out_dir), "mean_diff": -1.0,
                "n_frames": 0,
            })

    cap.release()
    if extras:
        print(f"[still] gap_fill: {len(extras)}개 강제샘플 추가 (gap>{gap_fill_sec}s 구간)",
              file=sys.stderr)
        manifest = sorted(manifest + extras, key=lambda m: m["t_sec"])
    return manifest


def extract_change(video_path, video_id, out_dir, fps=5.0,
                   change_thresh=4.0, settle_sec=0.5, roi=None):
    """ROI 변화감지 모드 — 슬라이드형 영상(Costco/@whiskeykey) 전용.

    정지를 기다리는 대신 ROI diff 가 change_thresh 이상으로 뛰면 '전환 감지'로 보고,
    settle_sec 후 첫 프레임을 대표로 저장한다. 슬라이드당 1장이 깔끔하게 추출된다.
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise SystemExit(f"[change] 영상 열기 실패(cv2): {video_path}")
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    dur = total / src_fps if total else 0
    step = max(1, int(round(src_fps / fps)))
    settle_frames = max(1, int(round(settle_sec * src_fps / step)))  # settle 구간 샘플 수
    print(f"[change] {video_path}: {src_fps:.1f}fps src, ~{dur:.0f}s, "
          f"roi={roi}, change_thresh={change_thresh}, settle={settle_sec}s",
          file=sys.stderr)

    os.makedirs(out_dir, exist_ok=True)
    manifest = []
    prev_small = None
    in_transition = False
    frames_since_transition = 0
    idx = 0

    while True:
        ok = cap.grab()
        if not ok:
            break
        if idx % step == 0:
            ok, frame = cap.retrieve()
            if not ok:
                break
            small = _roi_view(downscale_gray(frame), roi)
            if prev_small is not None and prev_small.shape == small.shape:
                diff = float(np.mean(cv2.absdiff(small, prev_small)))
            else:
                diff = 0.0
            prev_small = small

            if diff >= change_thresh:
                in_transition = True
                frames_since_transition = 0
            elif in_transition:
                frames_since_transition += 1
                if frames_since_transition == settle_frames:
                    # settle_sec 후 첫 안정 프레임 저장
                    in_transition = False
                    t_sec = idx / src_fps
                    tag = hhmmss(t_sec)
                    path = os.path.join(out_dir, f"{video_id}_{tag}.jpg")
                    suffix = 0
                    while os.path.exists(path):
                        suffix += 1
                        path = os.path.join(out_dir, f"{video_id}_{tag}_{suffix}.jpg")
                    cv2.imwrite(path, frame, [cv2.IMWRITE_JPEG_QUALITY, 92])
                    manifest.append({
                        "video_id": video_id, "t_sec": round(t_sec, 2), "hhmmss": tag,
                        "path": os.path.relpath(path, out_dir), "mean_diff": round(diff, 3),
                        "n_frames": settle_frames,
                    })
        idx += 1

    # 영상 시작(0~settle_sec) 도 첫 슬라이드일 수 있어 transition 없이 누락 가능 — 첫 프레임 보강
    if not manifest or manifest[0]["t_sec"] > 5.0:
        cap2 = cv2.VideoCapture(video_path)
        cap2.set(cv2.CAP_PROP_POS_MSEC, 1000)
        ok, frame0 = cap2.read()
        cap2.release()
        if ok:
            path0 = os.path.join(out_dir, f"{video_id}_000001_start.jpg")
            cv2.imwrite(path0, frame0, [cv2.IMWRITE_JPEG_QUALITY, 92])
            manifest.insert(0, {
                "video_id": video_id, "t_sec": 1.0, "hhmmss": "000001",
                "path": os.path.relpath(path0, out_dir), "mean_diff": 0.0, "n_frames": 1,
            })

    cap.release()
    print(f"[change] 전환감지 {len(manifest)}개 저장 → {out_dir}", file=sys.stderr)

    mpath = os.path.join(out_dir, "manifest.csv")
    with open(mpath, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["video_id", "t_sec", "hhmmss",
                                          "path", "mean_diff", "n_frames"])
        w.writeheader()
        w.writerows(manifest)
    return manifest


def main():
    ap = argparse.ArgumentParser(description="영상 → 정지프레임 추출(cv2, ffmpeg 불필요)")
    ap.add_argument("video", help="입력 mp4 경로")
    ap.add_argument("--video-id", required=True, help="유튜브 video_id (파일명/출처)")
    ap.add_argument("--out-dir", default="frames", help="대표 프레임 저장 폴더")
    ap.add_argument("--fps", type=float, default=5.0, help="샘플링 fps (기본 5)")
    ap.add_argument("--min-still-sec", type=float, default=0.5,
                    help="정지로 인정할 최소 지속 시간(초, 기본 0.5)")
    ap.add_argument("--diff-thresh", type=float, default=3.0,
                    help="인접 프레임 절대평균차 임계(이하=정지, 기본 3.0)")
    ap.add_argument("--max-frames", type=int, default=0, help="샘플 상한(0=전체)")
    ap.add_argument("--roi", default=None,
                    help="diff 계산 영역(상대좌표 'x0,y0,x1,y1'). 가격표가 고정된 채널"
                         "(@whiskeykey 우측 상단)에서 배경 움직임 무시·오버레이 변화만 추출")
    ap.add_argument("--gap-fill", type=float, default=30.0, metavar="SEC",
                    help="정지검출이 누락한 구간 중 이 초보다 긴 구간은 강제 샘플 추가 "
                         "(슬라이드형 영상 보완, 기본 30.0; 0=비활성)")
    ap.add_argument("--mode", choices=["still", "change"], default="still",
                    help="still=정지감지(기본, @whiskeypick), change=변화감지(@whiskeykey 슬라이드형)")
    ap.add_argument("--change-thresh", type=float, default=4.0,
                    help="change 모드: ROI diff 임계(이상=전환, 기본 4.0)")
    ap.add_argument("--settle-sec", type=float, default=0.5,
                    help="change 모드: 전환 후 안정 대기 시간(초, 기본 0.5)")
    a = ap.parse_args()
    roi = None
    if a.roi:
        try:
            roi = tuple(float(x) for x in a.roi.split(","))
            assert len(roi) == 4
        except (ValueError, AssertionError):
            ap.error("--roi 는 'x0,y0,x1,y1' 상대좌표 4개여야 합니다")
    if a.mode == "change":
        extract_change(a.video, a.video_id, a.out_dir, a.fps,
                       a.change_thresh, a.settle_sec, roi=roi)
    else:
        extract(a.video, a.video_id, a.out_dir, a.fps, a.min_still_sec,
                a.diff_thresh, a.max_frames, roi=roi, gap_fill_sec=a.gap_fill)


if __name__ == "__main__":
    main()
