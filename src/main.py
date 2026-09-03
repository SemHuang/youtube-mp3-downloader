import yt_dlp
import yt_dlp.utils
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
import queue
import os
import re
import sys
import subprocess
import pickle
import shutil
from urllib.parse import urlparse, parse_qs

from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

download_queue = queue.Queue()
stop_flag = False
drive_creds = None

os.makedirs("music", exist_ok=True)

yt_dlp.utils.std_headers['User-Agent'] = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'


# ── 路徑工具 ─────────────────────────────────────────────

def get_bin_dir():
    try:
        return sys._MEIPASS
    except AttributeError:
        src_dir = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(src_dir, "..", "ffmpeg")


def get_base_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


SRC_DIR = os.path.dirname(os.path.abspath(__file__))
CREDS_PATH = os.path.join(get_bin_dir() if getattr(sys, "frozen", False) else SRC_DIR, "credentials.json")
TOKEN_PATH = os.path.join(get_base_dir(), "token.pickle")
COOKIES_PATH = os.path.join(get_base_dir(), "cookies.txt")


# ── yt-dlp 更新 ──────────────────────────────────────────

def check_update():
    """檢查並更新 yt-dlp"""
    update_btn.config(state="disabled", text="更新中...")
    set_status("正在更新 yt-dlp...")

    def _update():
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", "-U", "yt-dlp"],
                capture_output=True, text=True, check=False,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            if result.returncode == 0:
                # 取得新版本號
                import importlib
                importlib.reload(yt_dlp)
                version = yt_dlp.version.__version__
                root.after(0, _update_done, True, f"yt-dlp 已更新到 {version}")
            else:
                root.after(0, _update_done, False, "更新失敗，請手動更新")
        except Exception as e:
            root.after(0, _update_done, False, f"更新失敗: {e}")

    def _update_done(success, msg):
        update_btn.config(state="normal", text="檢查更新")
        set_status(msg)
        if success:
            messagebox.showinfo("更新完成", msg)

    threading.Thread(target=_update, daemon=True).start()


def get_ytdlp_version():
    try:
        return yt_dlp.version.__version__
    except Exception:
        return "未知"


# ── ffmpeg 工具 ──────────────────────────────────────────

def convert_to_mp3_with_progress(input_file, output_file, total_duration):
    ffmpeg_path = os.path.join(get_bin_dir(), "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg")
    cmd = [
        ffmpeg_path,
        "-i", input_file,
        "-vn", "-ar", "44100", "-ac", "2", "-ab", "320k",
        "-f", "mp3", "-y",
        output_file
    ]
    process = subprocess.Popen(
        cmd, stderr=subprocess.STDOUT, stdout=subprocess.PIPE,
        universal_newlines=True, encoding="utf-8",
        creationflags=subprocess.CREATE_NO_WINDOW
    )
    time_re = re.compile(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)")
    for line in process.stdout:
        if stop_flag:
            process.terminate()
            break
        m = time_re.search(line)
        if m and total_duration > 0:
            h, mi, s = map(float, m.groups())
            percent = min((h * 3600 + mi * 60 + s) / total_duration * 100, 100)
            root.after(0, update_progress, percent, "", "轉檔中")
    process.wait()


def get_duration(input_file):
    ffprobe_path = os.path.join(get_bin_dir(), "ffprobe.exe" if sys.platform == "win32" else "ffprobe")
    cmd = [
        ffprobe_path, "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        input_file
    ]
    result = subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, creationflags=subprocess.CREATE_NO_WINDOW
    )
    try:
        return float(result.stdout.strip())
    except ValueError:
        return 0


# ── Google Drive ─────────────────────────────────────────

SCOPES = [
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/userinfo.email",
    "openid"
]


def google_login():
    def _login():
        global drive_creds
        try:
            flow = InstalledAppFlow.from_client_secrets_file(CREDS_PATH, SCOPES)
            creds = flow.run_local_server(port=0, prompt="select_account")
            drive_creds = creds
            with open(TOKEN_PATH, "wb") as f:
                pickle.dump(creds, f)
            service = build("oauth2", "v2", credentials=creds)
            info = service.userinfo().get().execute()
            email = info.get("email", "未知帳號")
            root.after(0, _update_login_ui, email)
        except Exception as e:
            root.after(0, set_status, f"登入失敗: {e}")

    threading.Thread(target=_login, daemon=True).start()


def google_logout():
    global drive_creds
    drive_creds = None
    if os.path.exists(TOKEN_PATH):
        os.remove(TOKEN_PATH)
    _update_login_ui(None)


def load_saved_login():
    global drive_creds
    if not os.path.exists(TOKEN_PATH):
        return
    try:
        with open(TOKEN_PATH, "rb") as f:
            creds = pickle.load(f)
        if creds and creds.valid:
            drive_creds = creds
        elif creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            drive_creds = creds
            with open(TOKEN_PATH, "wb") as f:
                pickle.dump(creds, f)
        else:
            return
        service = build("oauth2", "v2", credentials=drive_creds)
        info = service.userinfo().get().execute()
        email = info.get("email", "未知帳號")
        root.after(0, _update_login_ui, email)
    except Exception:
        drive_creds = None


def _update_login_ui(email):
    if email:
        login_label.config(text=f"已登入：{email}")
        login_btn.config(text="切換帳號")
        logout_btn.config(state="normal")
        upload_check.config(state="normal")
    else:
        login_label.config(text="尚未登入 Google")
        login_btn.config(text="登入 Google")
        logout_btn.config(state="disabled")
        upload_var.set(False)
        upload_check.config(state="disabled")


def upload_to_drive(filepath):
    try:
        root.after(0, set_status, "上傳到 Google Drive...")
        service = build("drive", "v3", credentials=drive_creds)
        filename = os.path.basename(filepath)
        media = MediaFileUpload(filepath, mimetype="audio/mpeg", resumable=True)
        service.files().create(
            body={"name": filename},
            media_body=media,
            fields="id"
        ).execute()
        root.after(0, set_status, "上傳完成！")
    except Exception as e:
        root.after(0, set_status, f"上傳失敗: {e}")


# ── Cookies ──────────────────────────────────────────────

def import_cookies():
    src = filedialog.askopenfilename(
        title="選擇 cookies.txt",
        filetypes=[("Text files", "*.txt")]
    )
    if not src:
        return
    try:
        shutil.copy(src, COOKIES_PATH)
        _update_cookies_ui(True)
    except Exception as e:
        cookies_label.config(text=f"匯入失敗: {e}", fg="red")


def _update_cookies_ui(exists):
    if exists:
        cookies_label.config(text="cookies 已匯入 ✓", fg="green")
    else:
        cookies_label.config(text="尚未匯入 cookies", fg="gray")


# ── URL 清理 ─────────────────────────────────────────────

def clean_url(url):
    parsed = urlparse(url)
    if parsed.netloc == "youtu.be":
        return f"https://www.youtube.com/watch?v={parsed.path[1:]}"
    if "youtube.com" in parsed.netloc:
        qs = parse_qs(parsed.query)
        if "v" in qs:
            return f"https://www.youtube.com/watch?v={qs['v'][0]}"
    return url


# ── 下載核心 ─────────────────────────────────────────────

def progress_hook(d):
    if stop_flag:
        raise Exception("Stopped")
    if d["status"] == "downloading":
        downloaded = d.get("downloaded_bytes", 0)
        total = d.get("total_bytes") or d.get("total_bytes_estimate", 1)
        root.after(0, update_progress, downloaded / total * 100, d.get("_speed_str", ""), "下載")
    elif d["status"] == "finished":
        root.after(0, update_progress, 100, "", "下載")
        root.after(0, set_status, "轉換 MP3 中...")


def download_worker():
    global stop_flag
    while True:
        url = download_queue.get()
        if url is None:
            break
        stop_flag = False
        root.after(0, update_progress, 0, "", "下載")

        ydl_opts = {
            "format": "bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio",
            "noplaylist": True,
            "restrictfilenames": True,
            "outtmpl": "music/%(title)s.%(ext)s",
            "progress_hooks": [progress_hook],
            "cookiefile": COOKIES_PATH if os.path.exists(COOKIES_PATH) else None,
            "retries": 10,
            "fragment_retries": 10,
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                if stop_flag:
                    raise Exception("Stopped by user")
                info = ydl.extract_info(url, download=True)
                downloaded_file = ydl.prepare_filename(info)
            output_mp3 = os.path.splitext(downloaded_file)[0] + ".mp3"
            total_sec = get_duration(downloaded_file)
            convert_to_mp3_with_progress(downloaded_file, output_mp3, total_sec)
            if os.path.exists(downloaded_file) and downloaded_file != output_mp3:
                os.remove(downloaded_file)
            if upload_var.get() and drive_creds:
                upload_to_drive(output_mp3)
            else:
                root.after(0, set_status, "完成")
            root.after(0, queue_list.delete, 0)
        except Exception as e:
            if stop_flag:
                root.after(0, set_status, "已停止")
            else:
                root.after(0, set_status, f"錯誤: {e}")
        finally:
            download_queue.task_done()


# ── UI 工具 ──────────────────────────────────────────────

def add_queue():
    url = url_entry.get().strip()
    if not url:
        return
    url = clean_url(url)
    download_queue.put(url)
    queue_list.insert(tk.END, url)
    url_entry.delete(0, tk.END)
    set_status("已加入佇列")


def stop_download():
    global stop_flag
    stop_flag = True
    set_status("停止中...")


def update_progress(percent, speed, phase=""):
    progress["value"] = percent
    phase_str = f"[{phase}] " if phase else ""
    speed_str = f"  {speed}" if speed else ""
    set_status(f"{phase_str}{percent:.1f}%{speed_str}")


def set_status(text):
    status_box.config(state="normal")
    status_box.delete("1.0", tk.END)
    status_box.insert(tk.END, text)
    status_box.config(state="disabled")


def start_worker():
    t = threading.Thread(target=download_worker, daemon=True)
    t.start()


# ── GUI ──────────────────────────────────────────────────

root = tk.Tk()
root.title("YouTube MP3 Downloader Pro")
root.geometry("650x600")

tk.Label(root, text="YouTube URL").pack(pady=5)
url_entry = tk.Entry(root, width=70)
url_entry.pack()

frame = tk.Frame(root)
frame.pack(pady=8)
tk.Button(frame, text="加入佇列", command=add_queue).pack(side="left", padx=5)
tk.Button(frame, text="停止下載", command=stop_download).pack(side="left", padx=5)

# Google Drive 區塊
drive_frame = tk.LabelFrame(root, text="Google Drive", padx=8, pady=6)
drive_frame.pack(fill="x", padx=20, pady=4)

login_label = tk.Label(drive_frame, text="尚未登入 Google", fg="gray")
login_label.pack(side="left", padx=5)

btn_frame = tk.Frame(drive_frame)
btn_frame.pack(side="right")
login_btn = tk.Button(btn_frame, text="登入 Google", command=google_login)
login_btn.pack(side="left", padx=4)
logout_btn = tk.Button(btn_frame, text="登出", command=google_logout, state="disabled")
logout_btn.pack(side="left", padx=4)

upload_var = tk.BooleanVar()
upload_check = tk.Checkbutton(drive_frame, text="下載完自動上傳", variable=upload_var, state="disabled")
upload_check.pack(side="left", padx=10)

# Cookies 區塊
cookies_frame = tk.LabelFrame(root, text="YouTube Cookies", padx=8, pady=6)
cookies_frame.pack(fill="x", padx=20, pady=4)

cookies_label = tk.Label(cookies_frame, text="尚未匯入 cookies", fg="gray")
cookies_label.pack(side="left", padx=5)

tk.Button(cookies_frame, text="匯入 cookies.txt", command=import_cookies).pack(side="right", padx=4)

# yt-dlp 更新區塊
update_frame = tk.LabelFrame(root, text="yt-dlp", padx=8, pady=6)
update_frame.pack(fill="x", padx=20, pady=4)

version_label = tk.Label(update_frame, text=f"目前版本：{get_ytdlp_version()}", fg="gray")
version_label.pack(side="left", padx=5)

update_btn = tk.Button(update_frame, text="檢查更新", command=check_update)
update_btn.pack(side="right", padx=4)

# 進度條
progress = ttk.Progressbar(root, length=400, maximum=100)
progress.pack(pady=6)

status_box = tk.Text(root, height=2, width=60, state="disabled",
                     relief="flat", bg=root.cget("bg"))
status_box.pack()

tk.Label(root, text="下載佇列").pack()
queue_list = tk.Listbox(root, width=80, height=6)
queue_list.pack()

start_worker()
set_status("等待下載")
root.after(500, load_saved_login)
root.after(500, lambda: _update_cookies_ui(os.path.exists(COOKIES_PATH)))

root.mainloop()
