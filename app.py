import tkinter as tk
from tkinter import filedialog, messagebox

# Before pydub: it checks PATH for ffmpeg/ffprobe when the module loads.
try:
    import static_ffmpeg

    static_ffmpeg.add_paths()
except ImportError:
    pass

import speech_recognition as sr
from pydub import AudioSegment
from pydub.effects import normalize
from pydub.exceptions import CouldntDecodeError
import os
import sys
import threading
import time
from tkinter import ttk
import tempfile

# FFmpeg format hints for pydub (anything else: auto-detect)
_FORMAT_BY_EXT = {
    ".aac": "aac",
    ".adts": "aac",
    ".m4a": "mp4",
    ".mp4": "mp4",
    ".mp3": "mp3",
    ".wav": "wav",
    ".flac": "flac",
    ".ogg": "ogg",
    ".opus": "opus",
    ".wma": "asf",
    ".webm": "webm",
    ".aiff": "aiff",
    ".aif": "aiff",
    ".mka": "matroska",
}

# Google Speech Recognition works best with mono 16 kHz PCM; chunk length stays under typical limits
_SPEECH_SAMPLE_RATE_HZ = 16000
_CHUNK_MS = 55 * 1000
_API_PAUSE_SEC = 0.35

# UI themes (GitHub-inspired dark / clean light)
THEMES = {
    "dark": {
        "bg": "#0d1117",
        "panel": "#161b22",
        "panel_alt": "#21262d",
        "input": "#0d1117",
        "text": "#e6edf3",
        "muted": "#8b949e",
        "accent": "#2f81f7",
        "accent_hover": "#58a6ff",
        "border": "#30363d",
        "button_bg": "#21262d",
        "button_fg": "#e6edf3",
        "menu_fg": "#ffffff",
    },
    "light": {
        "bg": "#f6f8fa",
        "panel": "#ffffff",
        "panel_alt": "#eaeef2",
        "input": "#ffffff",
        "text": "#1f2328",
        "muted": "#59636e",
        "accent": "#0969da",
        "accent_hover": "#0550ae",
        "border": "#d0d7de",
        "button_bg": "#f6f8fa",
        "button_fg": "#24292f",
        "menu_fg": "#ffffff",
    },
}

current_theme = "dark"
theme_btn = None

# ปุ่มสลับธีม: โหมดมืดอยู่ → แสดงดวงอาทิตย์ (แตะเพื่อสว่าง); โหมดสว่างอยู่ → แสดงจันทร์ (แตะเพื่อมืด)
_THEME_ICON_TO_LIGHT = "\u2600"  # ☀
_THEME_ICON_TO_DARK = "\u263E"  # ☾


def _load_audio(audio_path):
    """Load audio; if extension does not match the real container (e.g. AAC saved as .wav), fall back to FFmpeg auto-detect."""
    ext = os.path.splitext(audio_path)[1].lower()
    fmt = _FORMAT_BY_EXT.get(ext)
    if fmt:
        try:
            return AudioSegment.from_file(audio_path, format=fmt)
        except CouldntDecodeError:
            pass
    return AudioSegment.from_file(audio_path)


def _prepare_for_speech(audio):
    """Mono 16 kHz, light EQ and level — improves recognition vs raw stereo/48 kHz."""
    out = audio.set_channels(1).set_frame_rate(_SPEECH_SAMPLE_RATE_HZ)
    out = out.high_pass_filter(80)
    return normalize(out)


def _google_best_transcript(recognizer, audio_data, language="th-TH"):
    """Use confidence scores when Google returns multiple hypotheses."""
    result = recognizer.recognize_google(audio_data, language=language, show_all=True)
    if isinstance(result, dict) and result.get("alternative"):
        alts = result["alternative"]
        best = max(
            alts,
            key=lambda a: float(a.get("confidence", 0.0)),
        )
        t = (best.get("transcript") or "").strip()
        if t:
            return t
    if isinstance(result, str) and result.strip():
        return result.strip()
    raise sr.UnknownValueError()


def convert_audio_to_text(audio_path, progress_cb=None):
    """progress_cb(percent_0_100, detail_thai) — รายงานความคืบหน้าของไฟล์นี้เท่านั้น (หลายไฟล์จะถูกรวมเปอร์เซ็นต์ใน worker)"""

    def report(pct, msg):
        if progress_cb:
            progress_cb(min(100.0, max(0.0, float(pct))), msg)

    recognizer = sr.Recognizer()
    recognizer.dynamic_energy_threshold = True
    report(3, "โหลดเสียง…")
    audio = _prepare_for_speech(_load_audio(audio_path))
    if len(audio) == 0:
        report(100, "ไม่มีข้อมูลเสียงในไฟล์")
        return ""

    chunk_size = _CHUNK_MS
    total_ms = len(audio)
    num_chunks = max(1, (total_ms + chunk_size - 1) // chunk_size)
    duration_min = total_ms / 1000.0 / 60.0
    text = ""
    chunk_idx = 0
    # Use a temporary wav per chunk to avoid conflicts and ensure cleanup
    for i in range(0, len(audio), chunk_size):
        chunk_idx += 1
        # 10–98% ตามช่วง (เหลือหัวท้ายให้โหลด/จบ)
        pct_file = 10 + (88 * chunk_idx / num_chunks)
        report(
            pct_file,
            f"{chunk_idx}/{num_chunks} · ~{duration_min:.1f} นาที",
        )
        chunk = audio[i : i + chunk_size]
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
            tmp_path = tmp.name
        try:
            chunk.export(
                tmp_path,
                format="wav",
                parameters=["-ac", "1", "-ar", str(_SPEECH_SAMPLE_RATE_HZ)],
            )
            # Do not use adjust_for_ambient_noise here: it consumes the start of each chunk and hurts accuracy at splits.
            with sr.AudioFile(tmp_path) as source:
                audio_data = recognizer.record(source)
                try:
                    text_chunk = _google_best_transcript(recognizer, audio_data, language="th-TH")
                    text += text_chunk + " "
                except sr.UnknownValueError:
                    text += "[Unrecognized] "
                except sr.RequestError as e:
                    raise Exception(
                        f"Could not request results from Google Speech Recognition service; {e}"
                    )
        finally:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        time.sleep(_API_PAUSE_SEC)
    report(100, "จบไฟล์")
    return text.strip()

def open_file():
    file_paths = filedialog.askopenfilenames(
        filetypes=[
            (
                "ไฟล์เสียง (FFmpeg)",
                "*.wav *.mp3 *.aac *.m4a *.flac *.ogg *.opus *.wma *.webm *.mp4 *.aiff *.aif *.mka",
            ),
            ("AAC / M4A", "*.aac *.m4a"),
            ("ทุกไฟล์", "*.*"),
        ]
    )
    if file_paths:
        entry_var.set(";".join(file_paths))

def schedule_progress(pct, msg):
    """อัปเดตแถบความคืบหน้าแบบ thread-safe (เรียกจาก worker thread)"""
    pct = min(100.0, max(0.0, float(pct)))
    root.after(0, lambda p=pct, m=msg: _apply_progress(p, m))


def _apply_progress(pct, msg):
    try:
        progress_bar.stop()
    except (tk.TclError, AttributeError):
        pass
    progress_bar.config(mode="determinate", maximum=100, value=pct)
    progress_label.config(text=f"{msg}  {pct:.0f}%")


def transcribe_audio():
    file_paths = entry_var.get().split(";")
    if not file_paths or file_paths == ['']:
        messagebox.showwarning("Warning", "กรุณาเลือกไฟล์เสียง")
        return

    def worker(paths):
        valid_paths = [p for p in paths if p]
        n_files = len(valid_paths)
        try:
            set_busy(True)
            schedule_progress(0, "เริ่มประมวลผล…")
            result_text.config(state=tk.NORMAL)
            result_text.delete(1.0, tk.END)
            if n_files == 0:
                return
            for fi, file_path in enumerate(valid_paths):
                name = os.path.basename(file_path)

                def file_progress(pct_in_file, msg, fi=fi, n_files=n_files, name=name):
                    overall = (fi * 100.0 + pct_in_file) / n_files
                    schedule_progress(
                        overall,
                        f"{fi + 1}/{n_files} {name} · {msg}",
                    )

                try:
                    text = convert_audio_to_text(file_path, progress_cb=file_progress)
                    result_text.insert(
                        tk.END,
                        f"ข้อความที่ได้จาก {name}:\n{text}\n\n",
                    )
                except Exception as e:
                    result_text.insert(
                        tk.END,
                        f"เกิดข้อผิดพลาดจาก {name}: {e}\n\n",
                    )
        finally:
            try:
                result_text.config(state=tk.DISABLED)
            except tk.TclError:
                pass
            if n_files:
                schedule_progress(100, "เสร็จสิ้น")
                set_busy(False, "เสร็จสิ้น")
            else:
                schedule_progress(0, "พร้อมทำงาน")
                set_busy(False, "พร้อมทำงาน")

    threading.Thread(target=worker, args=(file_paths,), daemon=True).start()

def set_busy(is_busy, status=None):
    # Disable/enable UI while processing and update status
    browse_button.config(state=tk.DISABLED if is_busy else tk.NORMAL)
    transcribe_button.config(state=tk.DISABLED if is_busy else tk.NORMAL)
    save_button.config(state=tk.DISABLED if is_busy else tk.NORMAL)
    clear_button.config(state=tk.DISABLED if is_busy else tk.NORMAL)
    exit_button.config(state=tk.DISABLED if is_busy else tk.NORMAL)
    if theme_btn is not None:
        theme_btn.config(state=tk.DISABLED if is_busy else tk.NORMAL)
    if status is not None:
        progress_label.config(text=status)

def save_text():
    text_content = result_text.get(1.0, tk.END)
    if not text_content.strip():
        messagebox.showwarning("Warning", "ไม่มีข้อความให้บันทึก")
        return

    file_path = filedialog.asksaveasfilename(defaultextension=".txt", filetypes=[("Text Files", "*.txt")])
    if file_path:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(text_content)
        messagebox.showinfo("Information", "บันทึกข้อความสำเร็จ")

def clear_text():
    result_text.config(state=tk.NORMAL)
    result_text.delete(1.0, tk.END)
    result_text.config(state=tk.DISABLED)

def show_info():
    messagebox.showinfo("ติดต่อผู้พัฒนา", "Email: Patcharaalumaree@gmail.com\nGitHub: https://github.com/MrPatchara")

def _app_base_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def _try_set_window_icon():
    paths = []
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        paths.append(os.path.join(sys._MEIPASS, "voice.ico"))
    paths.append(os.path.join(_app_base_dir(), "voice.ico"))
    for ico in paths:
        if os.path.isfile(ico):
            try:
                root.iconbitmap(default=ico)
                return
            except tk.TclError:
                pass


root = tk.Tk()
root.title("แปลงเสียงเป็นข้อความ")
root.geometry("520x420")
root.minsize(420, 320)

_try_set_window_icon()

RETRO_FONT = ("Segoe UI", 9)
RETRO_TITLE_FONT = ("Segoe UI Semibold", 12)
RETRO_SMALL = ("Segoe UI", 8)

style = ttk.Style()
style.theme_use("clam")

menubar = tk.Menu(root)
root.config(menu=menubar)
file_menu = tk.Menu(menubar, tearoff=0)
file_menu.add_command(label="เลือกไฟล์", command=open_file)
file_menu.add_command(label="บันทึกข้อความ", command=save_text)
file_menu.add_command(label="ล้างข้อความ", command=clear_text)
file_menu.add_separator()
file_menu.add_command(label="ออก", command=root.quit)
menubar.add_cascade(label="ไฟล์", menu=file_menu)

view_menu = tk.Menu(menubar, tearoff=0)
menubar.add_cascade(label="มุมมอง", menu=view_menu)

help_menu = tk.Menu(menubar, tearoff=0)
help_menu.add_command(label="ข้อมูลผู้พัฒนา", command=show_info)
menubar.add_cascade(label="ช่วยเหลือ", menu=help_menu)

entry_var = tk.StringVar()

frame = ttk.Frame(root, style="TFrame", padding=(8, 8))
frame.pack(fill="both", expand=True, padx=8, pady=8)

header = ttk.Frame(frame, style="Header.TFrame", padding=0)
header.grid(row=0, column=0, sticky="ew", pady=(0, 2))
header.columnconfigure(0, weight=1)

title = ttk.Label(header, text="แปลงเสียงเป็นข้อความ", style="Title.TLabel")
title.grid(row=0, column=0, sticky="w")

theme_btn = ttk.Button(header, style="ThemeToggle.TButton")
theme_btn.grid(row=0, column=1, padx=(8, 0), sticky="e")

sep = ttk.Separator(frame, orient="horizontal")
sep.grid(row=1, column=0, sticky="ew", pady=(4, 6))

control_panel = ttk.Frame(frame, style="Panel.TFrame", padding=8)
control_panel.grid(row=2, column=0, sticky="ew")
control_panel.columnconfigure(1, weight=1)
control_panel.columnconfigure(2, weight=0, minsize=88)

label = ttk.Label(control_panel, text="ไฟล์เสียง")
label.grid(row=0, column=0, padx=(0, 6), pady=2, sticky="w")

entry = ttk.Entry(control_panel, textvariable=entry_var)
entry.grid(row=0, column=1, padx=(2, 4), pady=2, sticky="ew")

browse_button = ttk.Button(control_panel, text="เลือก…", command=open_file, width=9)
browse_button.grid(row=0, column=2, padx=(4, 2), pady=2, sticky="e")

transcribe_button = ttk.Button(
    control_panel,
    text="แปลงเป็นข้อความ",
    command=transcribe_audio,
    style="Accent.TButton",
)
transcribe_button.grid(row=1, column=0, columnspan=3, pady=(8, 6), sticky="ew")

progress_label = ttk.Label(control_panel, text="พร้อมทำงาน", style="Status.TLabel")
progress_label.grid(row=2, column=0, columnspan=3, sticky="w")

progress_bar = ttk.Progressbar(
    control_panel,
    mode="determinate",
    maximum=100,
    value=0,
)
progress_bar.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(4, 0))

text_panel = ttk.Frame(frame, style="Panel.TFrame", padding=6)
text_panel.grid(row=3, column=0, sticky="nsew", pady=(6, 0))
frame.rowconfigure(3, weight=1)
text_panel.columnconfigure(0, weight=1)
text_panel.rowconfigure(0, weight=1)

result_text = tk.Text(
    text_panel,
    wrap="word",
    relief="flat",
    bd=0,
    highlightthickness=1,
    font=("Segoe UI", 9),
    padx=6,
    pady=6,
)
result_text.grid(row=0, column=0, sticky="nsew")
result_text.config(state=tk.DISABLED)

actions_panel = ttk.Frame(frame, style="Panel.TFrame", padding=(4, 4))
actions_panel.grid(row=4, column=0, sticky="ew", pady=(6, 0))
actions_panel.columnconfigure((0, 1, 2), weight=1)

save_button = ttk.Button(actions_panel, text="บันทึกข้อความ", command=save_text)
save_button.grid(row=0, column=0, padx=4, pady=4, sticky="ew")

clear_button = ttk.Button(actions_panel, text="ล้างข้อความ", command=clear_text)
clear_button.grid(row=0, column=1, padx=4, pady=4, sticky="ew")

exit_button = ttk.Button(actions_panel, text="ออก", command=root.quit)
exit_button.grid(row=0, column=2, padx=4, pady=4, sticky="ew")


def apply_theme(name):
    global current_theme
    current_theme = name
    c = THEMES[name]
    root.configure(bg=c["bg"])
    style.configure("TFrame", background=c["bg"])
    style.configure("Header.TFrame", background=c["bg"])
    style.configure("Panel.TFrame", background=c["panel"])
    style.configure(
        "TLabel",
        background=c["bg"],
        foreground=c["text"],
        font=RETRO_FONT,
    )
    style.configure(
        "Title.TLabel",
        background=c["bg"],
        foreground=c["accent"],
        font=RETRO_TITLE_FONT,
    )
    style.configure(
        "Hint.TLabel",
        background=c["bg"],
        foreground=c["muted"],
        font=RETRO_SMALL,
    )
    style.configure(
        "Status.TLabel",
        background=c["panel"],
        foreground=c["muted"],
        font=RETRO_SMALL,
    )
    style.configure(
        "TButton",
        background=c["button_bg"],
        foreground=c["button_fg"],
        padding=(8, 5),
        font=RETRO_FONT,
        borderwidth=0,
    )
    style.map(
        "TButton",
        background=[("active", c["panel_alt"]), ("pressed", c["panel_alt"])],
        foreground=[("active", c["text"]), ("disabled", c["muted"])],
    )
    style.configure(
        "Accent.TButton",
        background=c["accent"],
        foreground="#ffffff",
        padding=(10, 6),
        font=("Segoe UI Semibold", 9),
    )
    style.map(
        "Accent.TButton",
        background=[("active", c["accent_hover"]), ("disabled", c["panel_alt"])],
        foreground=[("active", "#ffffff"), ("disabled", c["muted"])],
    )
    style.configure(
        "Ghost.TButton",
        background=c["bg"],
        foreground=c["accent"],
        padding=(6, 3),
        font=RETRO_SMALL,
    )
    style.map(
        "Ghost.TButton",
        background=[("active", c["panel_alt"])],
        foreground=[("active", c["accent_hover"])],
    )
    style.configure(
        "ThemeToggle.TButton",
        background=c["bg"],
        foreground=c["accent"],
        padding=(8, 4),
        font=("Segoe UI", 12),
        width=3,
    )
    style.map(
        "ThemeToggle.TButton",
        background=[("active", c["panel_alt"])],
        foreground=[("active", c["accent_hover"])],
    )
    style.configure(
        "TEntry",
        fieldbackground=c["input"],
        foreground=c["text"],
        insertcolor=c["text"],
        padding=6,
        font=RETRO_FONT,
    )
    style.map("TEntry", fieldbackground=[("focus", c["panel_alt"])])
    style.configure(
        "TProgressbar",
        troughcolor=c["panel_alt"],
        background=c["accent"],
    )
    style.configure("TSeparator", background=c["border"])
    result_text.configure(
        bg=c["input"],
        fg=c["text"],
        insertbackground=c["text"],
        highlightbackground=c["border"],
        highlightcolor=c["accent"],
        selectbackground=c["accent"],
        selectforeground="#ffffff",
    )
    for m in (menubar, file_menu, view_menu, help_menu):
        m.configure(
            bg=c["panel"],
            fg=c["text"],
            activebackground=c["accent"],
            activeforeground=c["menu_fg"],
        )
    theme_btn.configure(
        text=_THEME_ICON_TO_LIGHT if name == "dark" else _THEME_ICON_TO_DARK
    )


def toggle_theme():
    apply_theme("light" if current_theme == "dark" else "dark")


theme_btn.configure(command=toggle_theme)
view_menu.add_command(label="สลับธีม", command=toggle_theme)

apply_theme("dark")
root.mainloop()
