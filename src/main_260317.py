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


def resource_path(relative):

    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative)


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

        root.after(0, update_progress, percent, speed)

    elif d["status"] == "finished":

        root.after(0, status_label.config, {"text": "轉換 MP3 中..."})


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
            "ffmpeg_location": resource_path("ffmpeg"),
            "progress_hooks": [progress_hook],
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


def update_progress(percent, speed):

    progress["value"] = percent
    status_label.config(text=f"{percent:.1f}%  {speed}")


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
progress.pack(pady=10)

status_label = tk.Label(root, text="等待下載")
status_label.pack()

tk.Label(root, text="下載佇列").pack()

queue_list = tk.Listbox(root, width=80, height=10)
queue_list.pack()

start_worker()

root.mainloop()