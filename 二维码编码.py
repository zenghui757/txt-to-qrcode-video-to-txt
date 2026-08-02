# -*- coding: utf-8 -*-
import argparse, struct, zlib
from pathlib import Path
import cv2, numpy as np, qrcode

MAGIC, VERSION = b"QRTX", 1
EC_MAP = {
    "L": qrcode.constants.ERROR_CORRECT_L,
    "M": qrcode.constants.ERROR_CORRECT_M,
    "Q": qrcode.constants.ERROR_CORRECT_Q,
    "H": qrcode.constants.ERROR_CORRECT_H,
}
EC = EC_MAP["H"]


def encode_file(data, n=100):
    crc = zlib.crc32(data) & 0xffffffff
    cs = [data[i:i+n] for i in range(0, len(data), n)] or [b""]
    frames = [
        MAGIC + bytes([VERSION]) + struct.pack(
            ">HHHII", len(cs), i, len(c), crc, zlib.crc32(c) & 0xffffffff) + c
        for i, c in enumerate(cs)
    ]
    return frames, crc, len(cs)


def make_qr_pil(data, ec=None):
    q = qrcode.QRCode(version=None, error_correction=ec or EC, box_size=10, border=6)
    q.add_data(data, optimize=0)
    q.make(fit=True)
    return q.make_image(fill_color="black", back_color="white")


def hold_frames(fps, sec):
    return max(1, round(fps * sec))


def to_video_frame(q, size=1080):
    im = np.array(q.convert("L"))
    if im.shape[0] >= size:
        return im[:size, :size]
    m = int(size * .12)
    s = (size - 2 * m) / max(im.shape)
    if s != 1:
        im = cv2.resize(im, None, fx=s, fy=s, interpolation=cv2.INTER_NEAREST)
    out = np.full((size, size), 255, np.uint8)
    y, x = (size - im.shape[0]) // 2, (size - im.shape[1]) // 2
    out[y:y + im.shape[0], x:x + im.shape[1]] = im
    return out


def write_video(frames, out, size=1080, sec=.1, fps=10., rep=2, ec=None):
    w = cv2.VideoWriter(str(out), cv2.VideoWriter_fourcc(*"mp4v"), fps, (size, size))
    if not w.isOpened():
        raise RuntimeError(f"无法创建: {out}")
    try:
        for f in frames:
            im = cv2.cvtColor(to_video_frame(make_qr_pil(f, ec), size), cv2.COLOR_GRAY2BGR)
            for _ in range(rep * hold_frames(fps, sec)):
                w.write(im)
    finally:
        w.release()


def write_gif(frames, out, size=1080, sec=.1, rep=2, ec=None):
    from PIL import Image
    ims = []
    for f in frames:
        ims += [Image.fromarray(to_video_frame(make_qr_pil(f, ec), size))] * rep
    ims[0].save(str(out), save_all=True, append_images=ims[1:],
                duration=max(1, int(sec * 1000)), loop=0)


def main():
    ap = argparse.ArgumentParser(description="TXT -> 屏幕二维码视频")
    ap.add_argument("input")
    ap.add_argument("-o", "--output")
    ap.add_argument("-s", "--chunk-size", type=int, default=100)
    ap.add_argument("-e", "--error-correction", choices=EC_MAP, default="H")
    ap.add_argument("-r", "--repeats", type=int, default=2)
    ap.add_argument("-q", "--qr-speed", type=float, default=5.0, help="每秒二维码张数")
    ap.add_argument("--size", type=int, default=1080)
    ap.add_argument("--gif", action="store_true")
    a = ap.parse_args()
    if a.qr_speed <= 0:
        raise SystemExit("qr-speed 必须 > 0")
    src = Path(a.input)
    frames, _, n = encode_file(src.read_bytes(), a.chunk_size)
    sec = 1.0 / (a.qr_speed * a.repeats)
    fps = a.qr_speed * a.repeats
    out = Path(a.output) if a.output else src.with_suffix(src.suffix + ".qr.mp4")
    out.parent.mkdir(parents=True, exist_ok=True)
    ec = EC_MAP[a.error_correction]
    write_video(frames, out, a.size, sec, fps, a.repeats, ec)
    print(f"已生成: {out}（{n} 张二维码，每秒 {a.qr_speed:g} 张）")
    if a.gif:
        write_gif(frames, out.with_suffix(".gif"), a.size, sec, a.repeats, ec)
        print(f"已生成: {out.with_suffix('.gif')}")


if __name__ == "__main__":
    main()
