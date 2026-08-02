# -*- coding: utf-8 -*-
"""
接收端：从二维码视频（或摄像头实时画面）解码，重组还原 TXT 文件。

用法:
    python 二维码解码.py 视频.mp4                # 从视频文件解码，输出 还原.txt
    python 二维码解码.py 视频.mp4 -o 还原.txt
    python 二维码解码.py --camera 0              # 摄像头对准播放二维码的屏幕实时解码
    python 二维码解码.py --camera 0 -o 还原.txt

说明:
    - 支持视频内多个二维码帧循环播放，按序号自动去重、补齐，无需按顺序播放。
    - 不依赖视频帧率；手机以任意帧率摄录生成的视频均可直接还原。
    - 全部帧到齐后自动重组并做 CRC 校验，然后退出。
"""

import argparse
import struct
import time
import zlib
from pathlib import Path

import cv2
import zxingcpp

MAGIC = b"QRTX"
VERSION = 1
HEADER_LEN = 19


class ParseError(Exception):
    pass


def parse_frame(data: bytes):
    """解析一帧二进制负载，返回 (total, index, chunk, file_crc)。失败抛 ParseError。"""
    if len(data) < HEADER_LEN or data[:4] != MAGIC:
        raise ParseError("not our frame")
    if data[4] != VERSION:
        raise ParseError("version mismatch")
    total, index, dlen, file_crc, chunk_crc = struct.unpack(">HHHII", data[5:HEADER_LEN])
    chunk = data[HEADER_LEN:HEADER_LEN + dlen]
    if len(chunk) != dlen:
        raise ParseError("truncated chunk")
    if zlib.crc32(chunk) & 0xFFFFFFFF != chunk_crc:
        raise ParseError("chunk crc mismatch")
    if index >= total:
        raise ParseError("bad index")
    return total, index, chunk, file_crc


def decode_frame(frame_bgr):
    """解码一帧图像中的第一个有效二维码帧，返回 parse_frame 结果或 None。

    先按原图解码；失败时依次尝试灰度、对比度增强、放大/缩小等预处理，
    对手机摄录产生的模糊、噪点和不同画幅/帧率更稳健。
    """
    candidates = [frame_bgr]
    try:
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        candidates.append(gray)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
        candidates.append(clahe)
        h, w = frame_bgr.shape[:2]
        longest = max(h, w)
        if 0 < longest < 900:
            scale = min(2.0, 1400.0 / longest)
            if scale > 1.1:
                candidates.append(cv2.resize(
                    frame_bgr, None, fx=scale, fy=scale,
                    interpolation=cv2.INTER_CUBIC))
        elif longest > 1600:
            scale = 1600.0 / longest
            candidates.append(cv2.resize(
                frame_bgr, None, fx=scale, fy=scale,
                interpolation=cv2.INTER_AREA))
    except Exception:
        pass
    for img in candidates:
        try:
            results = zxingcpp.read_barcodes(
                img,
                formats=zxingcpp.BarcodeFormat.QRCode,
                try_invert=False,
            )
        except Exception:
            continue
        for r in results:
            try:
                return parse_frame(r.bytes)
            except ParseError:
                continue
    return None


def _fingerprint(frame, size: int = 48):
    """把一帧缩成 48x48 灰度指纹，用于判断内容是否变化。"""
    try:
        small = cv2.resize(frame, (size, size), interpolation=cv2.INTER_AREA)
        if small.ndim == 3:
            small = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        return small.astype("float32")
    except Exception:
        return None


def _similar(a, b, threshold: float = 4.0) -> bool:
    """判断两帧指纹是否足够接近，用于跳过高帧率录屏中的重复/轻微噪点帧。"""
    if a is None or b is None:
        return False
    try:
        return float(cv2.absdiff(a, b).mean()) <= threshold
    except Exception:
        return False


class Collector:
    """收集各序号分块，全部到齐后重组。"""

    def __init__(self):
        self.chunks = {}
        self.total = None
        self.file_crc = None

    def add(self, total, index, chunk, file_crc):
        if self.total is None:
            self.total = total
            self.file_crc = file_crc
        if total != self.total or file_crc != self.file_crc:
            return False  # 不来自同一文件，忽略
        self.chunks[index] = chunk
        return True

    @property
    def complete(self):
        return self.total is not None and len(self.chunks) == self.total

    def rebuild(self) -> bytes:
        if not self.complete:
            raise RuntimeError("数据未到齐")
        buf = b"".join(self.chunks[i] for i in range(self.total))
        if zlib.crc32(buf) & 0xFFFFFFFF != self.file_crc:
            raise RuntimeError("CRC 校验失败，文件已损坏，请重新接收")
        return buf

    def progress(self):
        if self.total is None:
            return 0, 0
        return len(self.chunks), self.total


def process_frame(collector, frame_bgr) -> bool:
    """处理一帧，返回 True 表示已全部到齐。"""
    got = decode_frame(frame_bgr)
    if got is None:
        return False
    if not collector.add(*got):
        return collector.complete
    got_n, total = collector.progress()
    print(f"  已接收 {got_n}/{total} 帧", end="\r")
    return collector.complete


def run_from_video(collector, video_path: Path, loops: int = 3, log=None,
                   on_frame=None, should_stop=None):
    """从视频文件解码，可自动循环重扫多遍补齐漏掉的块。

    - loops: 最多重扫遍数（录屏可能丢帧/遮挡，循环播放的视频多录几遍即可补齐）
    - on_frame: 每帧解码后的回调（GUI 用），接收 (collector, frame)，None 则直接处理
    - should_stop: 返回 True 时提前退出（GUI 停止按钮）
    """
    out = log if log else print
    probe = cv2.VideoCapture(str(video_path))
    if not probe.isOpened():
        raise RuntimeError(f"无法打开视频: {video_path}")
    fps = probe.get(cv2.CAP_PROP_FPS)
    n_frames = int(probe.get(cv2.CAP_PROP_FRAME_COUNT))
    probe.release()
    out(f"开始解码视频: {video_path}（{n_frames} 帧, {fps if fps else 0:.1f} fps）")

    last_fp = None  # 最近一次成功解码帧的指纹；相近内容跳过，避免对同一码重复解码
    for loop in range(1, loops + 1):
        # 每一遍重新打开文件，兼容手机录制的可变帧率视频（seek 可能失败）
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            raise RuntimeError(f"无法打开视频: {video_path}")
        if loops > 1:
            out(f"第 {loop}/{loops} 遍扫描…")
        while True:
            if should_stop and should_stop():
                cap.release()
                return
            ok, frame = cap.read()
            if not ok:
                break
            fp = _fingerprint(frame)
            if last_fp is not None and _similar(last_fp, fp):
                continue  # 与刚成功解码的帧内容基本一致（高帧率录屏/重复帧），跳过
            if on_frame is not None:
                decoded = on_frame(collector, frame)
            else:
                decoded = False
                got = decode_frame(frame)
                if got is not None and collector.add(*got):
                    decoded = True
                    n, total = collector.progress()
                    if log is not None:
                        out(f"  已接收 {n}/{total} 帧")
                    else:
                        print(f"  已接收 {n}/{total} 帧", end="\r")
            if decoded:
                last_fp = fp
            if collector.complete:
                cap.release()
                out("")
                return
        cap.release()
        if collector.complete:
            out("")
            return
        got, total = collector.progress()
        out(f"  本遍已收 {got}/{total}")
    out("")
    if not collector.complete:
        got, total = collector.progress()
        raise RuntimeError(
            f"扫描 {loops} 遍后仍缺 {total - got} 帧（共 {total} 帧）。\n"
            f"建议：播放时让视频循环播放并录制 2~3 个完整循环，或加大发送端 "
            f"停留时间 -t / 重复次数 -r。")


def run_from_camera(collector, camera_index: int):
    cap = cv2.VideoCapture(camera_index)
    if not cap.isOpened():
        raise SystemExit(f"无法打开摄像头 {camera_index}")
    print(f"摄像头 {camera_index} 已开启，请将循环播放的二维码视频对准镜头…")
    print("按 Esc 退出。")
    while not collector.complete:
        ok, frame = cap.read()
        if not ok:
            time.sleep(0.02)
            continue
        got, total = collector.progress()
        text = f"已接收 {got}/{total}" if total else "等待二维码…"
        preview = frame.copy()
        cv2.putText(preview, text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
        cv2.imshow("QR Receiver", preview)
        process_frame(collector, frame)
        if cv2.waitKey(1) & 0xFF == 27:
            break
    cap.release()
    cv2.destroyAllWindows()
    print()
    if not collector.complete:
        got, total = collector.progress()
        raise SystemExit(f"已退出，共收到 {got}/{total} 帧")


def main():
    ap = argparse.ArgumentParser(description="从二维码视频/摄像头还原 TXT 文件")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("video", nargs="?", help="二维码视频文件路径")
    src.add_argument("--camera", type=int, metavar="N", help="使用摄像头 N 实时解码")
    ap.add_argument("-o", "--output", help="输出 TXT 路径（默认 <视频名>还原.txt）")
    ap.add_argument("-l", "--loops", type=int, default=3,
                    help="视频文件最多重扫遍数，用于补齐录屏丢掉的帧（默认 3）")
    args = ap.parse_args()

    if args.video:
        out = Path(args.output) if args.output else Path(args.video).with_name(
            Path(args.video).stem + "还原.txt")
        collector = Collector()
        run_from_video(collector, Path(args.video), loops=args.loops)
    else:
        out = Path(args.output) if args.output else Path("还原.txt")
        collector = Collector()
        run_from_camera(collector, args.camera)

    data = collector.rebuild()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    got, total = collector.progress()
    print(f"解码完成: {total}/{total} 帧，CRC 校验通过。")
    print(f"已还原: {out}（{len(data)} 字节）")


if __name__ == "__main__":
    main()
