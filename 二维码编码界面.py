# -*- coding: utf-8 -*-
"""
发送端 GUI：TXT 文件 -> 循环播放二维码视频（MP4 / GIF）。

运行: python 二维码编码界面.py
"""

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

import cv2

from 二维码编码 import EC_MAP, encode_file, hold_frames, make_qr_pil, to_video_frame


class SenderGUI:
    def __init__(self, root):
        self.root = root
        root.title("二维码发送端 - TXT 转循环播放二维码视频")
        root.geometry("680x560")
        self.q = queue.Queue()
        self.working = False

        frm = ttk.Frame(root, padding=12)
        frm.pack(fill=tk.BOTH, expand=True)
        frm.columnconfigure(1, weight=1)

        # 输入文件
        ttk.Label(frm, text="源文件:").grid(row=0, column=0, sticky=tk.W, pady=4)
        self.src_var = tk.StringVar()
        ttk.Entry(frm, textvariable=self.src_var).grid(row=0, column=1, sticky=tk.EW, pady=4)
        ttk.Button(frm, text="浏览…", command=self.pick_file).grid(row=0, column=2, padx=4, pady=4)

        # 输出文件
        ttk.Label(frm, text="输出视频:").grid(row=1, column=0, sticky=tk.W, pady=4)
        self.out_var = tk.StringVar()
        ttk.Entry(frm, textvariable=self.out_var).grid(row=1, column=1, sticky=tk.EW, pady=4)
        ttk.Button(frm, text="浏览…", command=self.pick_out).grid(row=1, column=2, padx=4, pady=4)

        # 参数
        opt = ttk.Frame(frm)
        opt.grid(row=2, column=0, columnspan=3, sticky=tk.W, pady=6)
        ttk.Label(opt, text="每帧字节数:").pack(side=tk.LEFT)
        self.chunk_var = tk.IntVar(value=100)
        ttk.Spinbox(opt, from_=1, to=2000, width=5, textvariable=self.chunk_var).pack(side=tk.LEFT, padx=(2, 10))
        ttk.Label(opt, text="纠错级别:").pack(side=tk.LEFT)
        self.ec_var = tk.StringVar(value="H")
        ttk.Combobox(opt, textvariable=self.ec_var, values=list(EC_MAP), width=3,
                     state="readonly").pack(side=tk.LEFT, padx=(2, 10))
        ttk.Label(opt, text="重复次数:").pack(side=tk.LEFT)
        self.rep_var = tk.IntVar(value=2)
        ttk.Spinbox(opt, from_=1, to=10, width=4, textvariable=self.rep_var).pack(side=tk.LEFT, padx=(2, 10))
        ttk.Label(opt, text="每秒二维码数:").pack(side=tk.LEFT)
        self.speed_var = tk.DoubleVar(value=5.0)
        ttk.Spinbox(opt, from_=1, to=60, width=4, increment=1, textvariable=self.speed_var).pack(side=tk.LEFT, padx=(2, 10))
        ttk.Label(opt, text="画面边长:").pack(side=tk.LEFT)
        self.size_var = tk.IntVar(value=1080)
        ttk.Spinbox(opt, from_=400, to=2000, width=5, textvariable=self.size_var).pack(side=tk.LEFT, padx=2)
        self.gif_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(opt, text="同时生成 GIF", variable=self.gif_var).pack(side=tk.LEFT, padx=14)

        # 按钮
        btns = ttk.Frame(frm)
        btns.grid(row=3, column=0, columnspan=3, pady=6)
        self.start_btn = ttk.Button(btns, text="开始编码", command=self.start)
        self.start_btn.pack(side=tk.LEFT, padx=4)
        self.stop_btn = ttk.Button(btns, text="停止", command=self.stop, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=4)

        # 进度
        ttk.Label(frm, text="进度:").grid(row=4, column=0, sticky=tk.W, pady=4)
        self.bar = ttk.Progressbar(frm, mode="determinate")
        self.bar.grid(row=4, column=1, columnspan=2, sticky=tk.EW, pady=4)
        self.prog_var = tk.StringVar(value="")
        ttk.Label(frm, textvariable=self.prog_var).grid(row=5, column=1, columnspan=2, sticky=tk.W)

        # 日志
        ttk.Label(frm, text="日志:").grid(row=6, column=0, sticky=tk.NW, pady=4)
        self.log = scrolledtext.ScrolledText(frm, height=14, state=tk.DISABLED, wrap="word")
        self.log.grid(row=6, column=1, columnspan=2, sticky=tk.NSEW, pady=4)
        frm.rowconfigure(6, weight=1)

        self._stop = threading.Event()
        self.root.after(80, self.poll)

    def pick_file(self):
        p = filedialog.askopenfilename(title="选择 TXT 文件", filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")])
        if p:
            self.src_var.set(p)
            if not self.out_var.get():
                self.out_var.set(str(Path(p).with_suffix(Path(p).suffix + ".qr.mp4")))

    def pick_out(self):
        p = filedialog.asksaveasfilename(title="保存视频", defaultextension=".mp4",
                                         filetypes=[("MP4 视频", "*.mp4"), ("所有文件", "*.*")])
        if p:
            self.out_var.set(p)

    def logmsg(self, text):
        self.log.configure(state=tk.NORMAL)
        self.log.insert(tk.END, text + "\n")
        self.log.see(tk.END)
        self.log.configure(state=tk.DISABLED)

    def start(self):
        if self.working:
            return
        src = Path(self.src_var.get())
        if not src.exists():
            messagebox.showerror("错误", "请先选择存在的源文件")
            return
        out = Path(self.out_var.get()) or src.with_suffix(".qr.mp4")
        self.working = True
        self.start_btn.configure(state=tk.DISABLED)
        self.stop_btn.configure(state=tk.NORMAL)
        self.bar.configure(mode="determinate", maximum=100, value=0)
        self._stop.clear()
        args = (src, out, self.chunk_var.get(), self.ec_var.get(), self.rep_var.get(),
                self.speed_var.get(), self.size_var.get(), self.gif_var.get())
        threading.Thread(target=self.worker, args=args, daemon=True).start()

    def stop(self):
        self._stop.set()
        self.logmsg("正在停止…")

    def worker(self, src, out, chunk_size, ec, repeats, speed, size, gif):
        try:
            data = src.read_bytes()
            frames, file_crc, total = encode_file(data, chunk_size)
            qr_speed = max(float(speed), 0.001)
            seconds_per_frame = 1.0 / qr_speed / repeats
            fps = max(qr_speed * repeats, 1.0)
            self.q.put(("setup", total))
            self.q.put(("log", f"文件 {len(data)} 字节, 共 {total} 块 × {repeats} 次重复, "
                              f"每秒 {qr_speed:.1f} 张二维码, 帧率 {fps:.0f}fps, "
                              f"纠错级别 {ec}, CRC {file_crc:08X}"))
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            writer = cv2.VideoWriter(str(out), fourcc, fps, (size, size))
            if not writer.isOpened():
                raise RuntimeError(f"无法创建视频文件: {out}")
            try:
                ec_const = EC_MAP[ec]
                per_copy = hold_frames(fps, seconds_per_frame)
                for i, fb in enumerate(frames):
                    if self._stop.is_set():
                        self.q.put(("log", "已停止"))
                        self.q.put(("done", "已停止"))
                        return
                    frame = cv2.cvtColor(to_video_frame(make_qr_pil(fb, ec_const), size),
                                         cv2.COLOR_GRAY2BGR)
                    for _ in range(repeats * per_copy):
                        writer.write(frame)
                    self.q.put(("progress", i + 1, total))
            finally:
                writer.release()
            self.q.put(("log", f"视频已生成: {out}"))
            if gif:
                from 二维码编码 import write_gif
                gif_path = out.with_suffix(".gif")
                write_gif(frames, gif_path, size, seconds_per_frame, repeats, ec_const)
                self.q.put(("log", f"GIF 已生成: {gif_path}"))
            self.q.put(("done", "编码完成"))
        except PermissionError as e:
            self.q.put(("error", f"{e}\n请关闭正在使用该文件的程序后重试"))
        except Exception as e:
            self.q.put(("error", str(e)))

    def poll(self):
        try:
            while True:
                msg = self.q.get_nowait()
                kind = msg[0]
                if kind == "log":
                    self.logmsg(msg[1])
                elif kind == "setup":
                    self.bar.configure(mode="determinate", maximum=msg[1], value=0)
                elif kind == "progress":
                    self.bar.configure(value=msg[1])
                    self.prog_var.set(f"{msg[1]}/{msg[2]}")
                elif kind == "done":
                    self.working = False
                    self.bar.configure(value=self.bar["maximum"])
                    self.logmsg(msg[1])
                    self._finish()
                    messagebox.showinfo("完成", msg[1])
                elif kind == "error":
                    self.working = False
                    self._finish()
                    messagebox.showerror("错误", msg[1])
        except queue.Empty:
            pass
        self.root.after(80, self.poll)

    def _finish(self):
        self.start_btn.configure(state=tk.NORMAL)
        self.stop_btn.configure(state=tk.DISABLED)


def main():
    root = tk.Tk()
    SenderGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
