import yt_dlp
import tkinter as tk
from tkinter import ttk
import threading
import queue
import os
import re
import sys
import subprocess

download_queue = queue.Queue()
stop_flag = False

os.makedirs("music", exist_ok=True)

def convert_to_mp3_with_progress(input_file, output_file, total_duration):
    """手動執行轉檔並解析進度"""
    ffmpeg_path = os.path.join(get_bin_dir(), "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg")
    
    # 建立轉換指令
    cmd = [
        ffmpeg_path,
        "-i", input_file,
        "-vn",
        "-ar", "44100",
        "-ac", "2",
        "-ab", "320k",
        "-f", "mp3",
        "-y", # 覆蓋現有檔案
        output_file
    ]

    # 使用 subprocess 開啟進程並導向錯誤輸出 (ffmpeg 的進度通常在 stderr)
    process = subprocess.Popen(cmd, stderr=subprocess.STDOUT, stdout=subprocess.PIPE, universal_newlines=True, encoding='utf-8')

    # 正則表達式抓取 time=HH:MM:SS
    time_re = re.compile(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)")

    for line in process.stdout:
        if stop_flag:
            process.terminate()
            break
        search = time_re.search(line)
        if search and total_duration > 0:
            hours, mins, secs = map(float, search.groups())
            current_seconds = hours * 3600 + mins * 60 + secs
            
            # 計算百分比
            percent = min((current_seconds / total_duration) * 100, 100)
            
            # 更新 UI (呼叫你原本的 update_progress)
            root.after(0, update_progress, percent, "", "轉檔中")

    process.wait()
    
def get_duration(input_file):
    """取得音訊檔案的總秒數"""
    ffprobe_path = os.path.join(get_bin_dir(), "ffprobe.exe" if sys.platform == "win32" else "ffprobe")
    cmd = [
        ffprobe_path,
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        input_file
    ]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        return float(result.stdout.strip())
    except ValueError:
        return 0
    
def get_bin_dir():
    """取得執行檔或 PyInstaller 解壓縮後的暫存目錄"""
    try:
        # PyInstaller 執行時的暫存目錄
        return sys._MEIPASS
    except AttributeError:
        # 開發環境下的當前目錄
        return os.path.abspath(".")

from urllib.parse import urlparse, parse_qs

def clean_url(url):
    parsed = urlparse(url)

    # youtu.be/xxxx
    if parsed.netloc == "youtu.be":
        return f"https://www.youtube.com/watch?v={parsed.path[1:]}"

    # youtube.com/watch?v=xxxx
    if "youtube.com" in parsed.netloc:
        qs = parse_qs(parsed.query)
        if "v" in qs:
            return f"https://www.youtube.com/watch?v={qs['v'][0]}"

    return url


def progress_hook(d):
    if stop_flag:
        raise Exception("Stopped")
    
    if d["status"] == "downloading":

        downloaded = d.get("downloaded_bytes", 0)
        total = d.get("total_bytes") or d.get("total_bytes_estimate", 1)

        percent = downloaded / total * 100

        speed = d.get("_speed_str", "")

        root.after(0, update_progress, percent, speed, "下載")

    elif d["status"] == "finished":

        root.after(0, update_progress, 100, "", "下載")
        root.after(0, status_label.config, {"text": "轉換 MP3 中..."})


def download_worker():
    global stop_flag
    while True:
        url = download_queue.get()
        if url is None: break

        stop_flag = False
        
        root.after(0, update_progress, 0, "", "下載")
        # 修改 ydl_opts，移除自動轉檔，只負責下載最好的音訊
        ydl_opts = {
            "format": "bestaudio/best",
            "noplaylist": True,   # 加回來
            "restrictfilenames": True,  # 加回來
            "outtmpl": "music/%(title)s.%(ext)s",
            "progress_hooks": [progress_hook],
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                if stop_flag:
                    raise Exception("Stopped by user")
                info = ydl.extract_info(url, download=True)
                downloaded_file = ydl.prepare_filename(info)
                
                # 下載完畢後，手動進行轉檔
                output_mp3 = os.path.splitext(downloaded_file)[0] + ".mp3"
                
                # 1. 取得總長度
                total_sec = get_duration(downloaded_file)
                
                # 2. 開始轉檔並顯示進度
                convert_to_mp3_with_progress(downloaded_file, output_mp3, total_sec)
                
                # 3. 刪除原始下載的非 mp3 檔案 (選做)
                if os.path.exists(downloaded_file) and downloaded_file != output_mp3:
                    os.remove(downloaded_file)

            root.after(0, status_label.config, {"text": "完成"})
            root.after(0, queue_list.delete, 0)  # 移除佇列中的項目
        except Exception as e:
            if stop_flag:
                root.after(0, status_label.config, {"text": "已停止"})
            else:
                root.after(0, status_label.config, {"text": f"錯誤: {e}"})
                
        finally:
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

status_label = tk.Label(root, text="等待下載")
status_label.pack()

tk.Label(root, text="下載佇列").pack()

queue_list = tk.Listbox(root, width=80, height=10)
queue_list.pack()

start_worker()

root.mainloop()