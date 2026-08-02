# -*- coding: utf-8 -*-
"""
接收端 GUI：从二维码视频 / 摄像头实时画面解码，还原 TXT 文件。

运行: python 二维码解码界面.py
"""

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

import cv2
import zxingcpp
from PIL import Image, ImageTk

from 二维码解码 import Collector, decode_frame, run_from_video


class ReceiverGUI:
    def __init__(self, root):
        self.root = root
        root.title("二维码接收端 - 视频/摄像头解码还原 TXT")
        root.geometry("720x640")
        self.q = queue.Queue()
        self.working = False
        self._stop = threading.Event()
        self.preview_img = None

        frm = ttk.Frame(root, padding=12)
        frm.pack(fill=tk.BOTH, expand=True)
        frm.columnconfigure(1, weight=1)

        # 来源模式
        ttk.Label(frm, text="来源:").grid(row=0, column=0, sticky=tk.W, pady=4)
        self.mode_var = tk.StringVar(value="video")
        ttk.Radiobutton(frm, text="视频文件", value="video", variable=self.mode_var,
                        command=self.on_mode).grid(row=0, column=1, sticky=tk.W)
        ttk.Radiobutton(frm, text="摄像头", value="camera", variable=self.mode_var,
                        command=self.on_mode).grid(row=0, column=2, sticky=tk.W, padx=4)

        # 视频文件
        ttk.Label(frm, text="二维码视频:").grid(row=1, column=0, sticky=tk.W, pady=4)
        self.video_var = tk.StringVar()
        self.video_entry = ttk.Entry(frm, textvariable=self.video_var)
        self.video_entry.grid(row=1, column=1, sticky=tk.EW, pady=4)
        self.video_btn = ttk.Button(frm, text="浏览…", command=self.pick_video)
        self.video_btn.grid(row=1, column=2, padx=4, pady=4)

        # 摄像头
        ttk.Label(frm, text="摄像头编号:").grid(row=2, column=0, sticky=tk.W, pady=4)
        self.cam_var = tk.IntVar(value=0)
        self.cam_spin = ttk.Spinbox(frm, from_=0, to=9, width=6, textvariable=self.cam_var)
        self.cam_spin.grid(row=2, column=1, sticky=tk.W, pady=4)
        ttk.Label(frm, text="视频重扫遍数:").grid(row=2, column=2, sticky=tk.W, pady=4)
        self.loops_var = tk.IntVar(value=3)
        ttk.Spinbox(frm, from_=1, to=20, width=4, textvariable=self.loops_var).grid(
            row=2, column=3, sticky=tk.W, pady=4)

        # 输出
        ttk.Label(frm, text="输出 TXT:").grid(row=3, column=0, sticky=tk.W, pady=4)
        self.out_var = tk.StringVar()
        ttk.Entry(frm, textvariable=self.out_var).grid(row=3, column=1, sticky=tk.EW, pady=4)
        ttk.Button(frm, text="浏览…", command=self.pick_out).grid(row=3, column=2, padx=4, pady=4)

        # 按钮
        btns = ttk.Frame(frm)
        btns.grid(row=4, column=0, columnspan=3, pady=6)
        self.start_btn = ttk.Button(btns, text="开始接收", command=self.start)
        self.start_btn.pack(side=tk.LEFT, padx=4)
        self.stop_btn = ttk.Button(btns, text="停止", command=self.stop, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=4)

        # 进度
        self.bar = ttk.Progressbar(frm, mode="determinate")
        self.bar.grid(row=5, column=0, columnspan=3, sticky=tk.EW, pady=4)
        self.prog_var = tk.StringVar(value="")
        ttk.Label(frm, textvariable=self.prog_var).grid(row=6, column=0, columnspan=3, sticky=tk.W)

        # 预览
        self.preview = ttk.Label(frm, text="（摄像头模式下显示实时画面）", anchor=tk.CENTER)
        self.preview.grid(row=7, column=0, columnspan=3, sticky=tk.NSEW, pady=4)

        # 日志
        ttk.Label(frm, text="日志:").grid(row=8, column=0, sticky=tk.NW, pady=4)
        self.log = scrolledtext.ScrolledText(frm, height=10, state=tk.DISABLED, wrap="word")
        self.log.grid(row=8, column=1, columnspan=2, sticky=tk.NSEW, pady=4)
        frm.rowconfigure(8, weight=1)
        frm.rowconfigure(7, weight=1)

        self.on_mode()
        self.root.after(80, self.poll)

    def on_mode(self):
        cam = self.mode_var.get() == "camera"
        state = tk.NORMAL if cam else tk.DISABLED
        self.cam_spin.configure(state=state)
        self.video_entry.configure(state=tk.DISABLED if cam else tk.NORMAL)
        self.video_btn.configure(state=tk.DISABLED if cam else tk.NORMAL)

    def pick_video(self):
        p = filedialog.askopenfilename(title="选择二维码视频",
                                       filetypes=[("视频", "*.mp4 *.avi *.mov *.mkv *.gif"), ("所有文件", "*.*")])
        if p:
            self.video_var.set(p)
            if not self.out_var.get():
                self.out_var.set(str(Path(p).with_name(Path(p).stem + "还原.txt")))

    def pick_out(self):
        p = filedialog.asksaveasfilename(title="保存 TXT", defaultextension=".txt",
                                         filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")])
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
        out = Path(self.out_var.get() or "还原.txt")
        self.working = True
        self.start_btn.configure(state=tk.DISABLED)
        self.stop_btn.configure(state=tk.NORMAL)
        self.bar.configure(mode="indeterminate")
        self.bar.start(12)
        self.prog_var.set("等待二维码…")
        self._stop.clear()
        mode = self.mode_var.get()
        if mode == "video":
            src = Path(self.video_var.get())
            if not src.exists():
                self._finish()
                messagebox.showerror("错误", "请选择存在的视频文件")
                return
            args = ("video", src, out, self.loops_var.get())
        else:
            args = ("camera", self.cam_var.get(), out, 1)
        threading.Thread(target=self.worker, args=args, daemon=True).start()

    def stop(self):
        self._stop.set()
        self.logmsg("正在停止…")

    def worker(self, mode, source, out, loops):
        collector = Collector()
        try:
            if mode == "video":
                run_from_video(collector, Path(source), loops=loops,
                               log=lambda t: self.q.put(("log", t)),
                               on_frame=self.handle_frame,
                               should_stop=lambda: self._stop.is_set())
            else:
                cap = cv2.VideoCapture(int(source))
                if not cap.isOpened():
                    raise RuntimeError(f"无法打开摄像头 {source}")
                self.q.put(("log", f"摄像头 {source} 已开启，请对准循环播放二维码的屏幕"))
                while not collector.complete and not self._stop.is_set():
                    ok, frame = cap.read()
                    if not ok:
                        continue
                    got, total = collector.progress()
                    text = f"已接收 {got}/{total}" if total else "等待二维码…"
                    preview = frame.copy()
                    cv2.putText(preview, text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1,
                                (0, 255, 0), 2)
                    self.q.put(("preview", preview))
                    self.handle_frame(collector, frame)
                cap.release()
                if not collector.complete and not self._stop.is_set():
                    got, total = collector.progress()
                    raise RuntimeError(f"已停止，共收到 {got}/{total} 帧")

            if not collector.complete:
                raise RuntimeError("未完成接收")

            data = collector.rebuild()
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(data)
            self.q.put(("log", f"CRC 校验通过，已还原: {out}（{len(data)} 字节）"))
            self.q.put(("done", f"解码完成！已还原到:\n{out}"))
        except PermissionError as e:
            self.q.put(("error", f"{e}\n请关闭正在使用该文件的程序后重试"))
        except Exception as e:
            self.q.put(("error", str(e)))

    def handle_frame(self, collector, frame):
        got = decode_frame(frame)
        if got is None:
            return False
        if not collector.add(*got):
            return False
        n, total = collector.progress()
        self.q.put(("progress", n, total))
        return True

    def poll(self):
        try:
            while True:
                msg = self.q.get_nowait()
                kind = msg[0]
                if kind == "log":
                    self.logmsg(msg[1])
                elif kind == "progress":
                    if self.bar.cget("mode") == "indeterminate":
                        self.bar.stop()
                        self.bar.configure(mode="determinate", maximum=msg[2], value=0)
                    self.bar.configure(value=msg[1])
                    self.prog_var.set(f"已接收 {msg[1]}/{msg[2]} 帧")
                elif kind == "preview":
                    frame = msg[1]
                    img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                    img.thumbnail((640, 360))
                    self.preview_img = ImageTk.PhotoImage(img)
                    self.preview.configure(image=self.preview_img, text="")
                elif kind == "done":
                    self.working = False
                    self.bar.stop()
                    self.bar.configure(mode="determinate")
                    self._finish()
                    messagebox.showinfo("完成", msg[1])
                elif kind == "error":
                    self.working = False
                    self.bar.stop()
                    self.bar.configure(mode="determinate")
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
    ReceiverGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
