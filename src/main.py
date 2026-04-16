import yt_dlp
import tkinter as tk
from tkinter import ttk
import threading
import queue
import os
import re
import sys

download_queue = queue.Queue()
stop_flag = False

os.makedirs("music", exist_ok=True)


def get_bin_dir():
    """取得執行檔或 PyInstaller 解壓縮後的暫存目錄"""
    try:
        # PyInstaller 執行時的暫存目錄
        return sys._MEIPASS
    except AttributeError:
        # 開發環境下的當前目錄
        return os.path.abspath(".")
    
def clean_url(url):

    match = re.search(r"v=([a-zA-Z0-9_-]+)", url)

    if match:
        return f"https://www.youtube.com/watch?v={match.group(1)}"

    return url


def progress_hook(d):

    if d["status"] == "downloading":

        downloaded = d.get("downloaded_bytes", 0)
        total = d.get("total_bytes") or d.get("total_bytes_estimate", 1)

        percent = downloaded / total * 100

        speed = d.get("_speed_str", "")

        root.after(0, update_progress, percent, speed, "下載")

    elif d["status"] == "finished":

        root.after(0, update_progress, 100, "", "下載")
        root.after(0, status_label.config, {"text": "轉換 MP3 中..."})


def postprocessor_hook(d):

    if d["status"] == "started":

        root.after(0, update_progress, 0, "", "轉換 MP3")
        root.after(0, status_label.config, {"text": "轉換 MP3 中..."})

    elif d["status"] == "processing":

        # yt-dlp provides elapsed/total when available
        elapsed = d.get("elapsed_time")
        total_time = d.get("total_time")

        if elapsed is not None and total_time and total_time > 0:
            percent = min(elapsed / total_time * 100, 99)
            root.after(0, update_progress, percent, "", "轉換 MP3")
        else:
            # Pulse the bar to show activity when exact progress is unavailable
            root.after(0, pulse_progress)

    elif d["status"] == "finished":

        root.after(0, update_progress, 100, "", "轉換 MP3")


def download_worker():

    global stop_flag

    while True:

        url = download_queue.get()

        if url is None:
            break

        stop_flag = False

        ydl_opts = {
            "format": "bestaudio/best",
            "noplaylist": True,
            "restrictfilenames": True,
            "outtmpl": "music/%(title)s.%(ext)s",
            "ffmpeg_location": get_bin_dir(),
            "progress_hooks": [progress_hook],
            "postprocessor_hooks": [postprocessor_hook],
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "320"
            }],
        }

        try:

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:

                if stop_flag:
                    break

                ydl.download([url])

            root.after(0, status_label.config, {"text": "完成"})

        except Exception as e:

            if stop_flag:
                root.after(0, status_label.config, {"text": "已停止"})
            else:
                root.after(0, status_label.config, {"text": f"錯誤: {e}"})

        download_queue.task_done()


def add_queue():

    url = url_entry.get()

    if url == "":
        return

    url = clean_url(url)

    download_queue.put(url)

    queue_list.insert(tk.END, url)

    status_label.config(text="已加入佇列")


def stop_download():

    global stop_flag
    stop_flag = True
    status_label.config(text="停止中...")


def update_progress(percent, speed, phase=""):

    progress["value"] = percent
    phase_str = f"[{phase}] " if phase else ""
    speed_str = f"  {speed}" if speed else ""
    status_label.config(text=f"{phase_str}{percent:.1f}%{speed_str}")


def pulse_progress():
    """Animate the bar slightly to indicate activity when exact % is unknown."""
    current = progress["value"]
    next_val = (current + 2) % 100
    progress["value"] = next_val


def start_worker():

    t = threading.Thread(target=download_worker, daemon=True)
    t.start()


# GUI

root = tk.Tk()

root.title("YouTube MP3 Downloader Pro")
root.geometry("650x420")

tk.Label(root, text="YouTube URL").pack(pady=5)

url_entry = tk.Entry(root, width=70)
url_entry.pack()

frame = tk.Frame(root)
frame.pack(pady=10)

tk.Button(frame, text="加入佇列", command=add_queue).pack(side="left", padx=5)
tk.Button(frame, text="停止下載", command=stop_download).pack(side="left", padx=5)

progress = ttk.Progressbar(root, length=400, maximum=100)
progress.pack(pady=5)

phase_label = tk.Label(root, text="", font=("Arial", 9), fg="gray")
phase_label.pack()

status_label = tk.Label(root, text="等待下載")
status_label.pack()

tk.Label(root, text="下載佇列").pack()

queue_list = tk.Listbox(root, width=80, height=10)
queue_list.pack()

start_worker()

root.mainloop()