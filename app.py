import os
import sys
import threading
import glob
import customtkinter as ctk
import yt_dlp
from tkinter import filedialog, messagebox
from dotenv import set_key, load_dotenv

from analyze_film import analyze_video

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

# Maps the 1-5 user-facing pace level to ContentDetector threshold values.
# Lower threshold = more sensitive = detects more cuts.
PACE_THRESHOLD = {
    1: 40,  # Documentary / slow art film
    2: 32,  # Drama / interview
    3: 27,  # Standard (default)
    4: 18,  # Fast-paced / commercial
    5: 10,  # Action / music video
}
PACE_LABEL = {
    1: "Documentary",
    2: "Drama",
    3: "Standard",
    4: "Fast-paced",
    5: "Action",
}

class FilmBreakdownApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("🎬 Film Breakdown AI")
        self.geometry("620x800")

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(5, weight=1)  # status box expands

        self.cancel_event = threading.Event()
        self.video_path   = None

        # ── Row 0: API Key ────────────────────────────────────────────────────
        self.api_frame = ctk.CTkFrame(self)
        self.api_frame.grid(row=0, column=0, padx=20, pady=(20, 10), sticky="ew")
        self.api_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(self.api_frame, text="Moonshot API Key:", font=("Arial", 14, "bold")).grid(
            row=0, column=0, padx=10, pady=10, sticky="w")
        self.api_entry = ctk.CTkEntry(self.api_frame, show="*", placeholder_text="Enter API Key...")
        self.api_entry.grid(row=0, column=1, padx=10, pady=10, sticky="ew")
        ctk.CTkButton(self.api_frame, text="Save to .env", width=100, command=self.save_api_key).grid(
            row=0, column=2, padx=10, pady=10)

        ctk.CTkLabel(self.api_frame, text="Gemini API Key:", font=("Arial", 14, "bold")).grid(
            row=1, column=0, padx=10, pady=(0, 10), sticky="w")
        self.gemini_entry = ctk.CTkEntry(self.api_frame, show="*", placeholder_text="Enter Gemini API Key...")
        self.gemini_entry.grid(row=1, column=1, padx=10, pady=(0, 10), sticky="ew")
        ctk.CTkButton(self.api_frame, text="Save to .env", width=100, command=self.save_gemini_key).grid(
            row=1, column=2, padx=10, pady=(0, 10))

        load_dotenv()
        existing_key = os.environ.get("MOONSHOT_API_KEY", os.environ.get("KIMI_API_KEY", ""))
        if existing_key:
            self.api_entry.insert(0, existing_key)
        existing_gemini_key = os.environ.get("GEMINI_API_KEY", "")
        if existing_gemini_key:
            self.gemini_entry.insert(0, existing_gemini_key)

        # ── Row 1: Video Selection ────────────────────────────────────────────
        self.video_frame = ctk.CTkFrame(self)
        self.video_frame.grid(row=1, column=0, padx=20, pady=(0, 10), sticky="ew")
        self.video_frame.grid_columnconfigure(1, weight=1)

        self.file_label = ctk.CTkLabel(
            self.video_frame, text="No Video Selected", font=("Arial", 14, "italic"), text_color="gray")
        self.file_label.grid(row=0, column=0, columnspan=2, padx=10, pady=(15, 0), sticky="ew")

        self.select_btn = ctk.CTkButton(
            self.video_frame, text="📁 Browse Local Video", command=self.select_video, width=150)
        self.select_btn.grid(row=0, column=2, padx=(10, 4), pady=(15, 0))

        self.open_downloads_btn = ctk.CTkButton(
            self.video_frame, text="📂 Downloads", command=self.open_downloads,
            width=110, fg_color="#444444", hover_color="#555555")
        self.open_downloads_btn.grid(row=0, column=3, padx=(0, 10), pady=(15, 0))

        ctk.CTkLabel(self.video_frame, text="Or YouTube URL:").grid(
            row=1, column=0, padx=10, pady=15, sticky="w")
        self.yt_entry = ctk.CTkEntry(
            self.video_frame, placeholder_text="https://www.youtube.com/watch?v=...")
        self.yt_entry.grid(row=1, column=1, columnspan=2, padx=10, pady=15, sticky="ew")
        self.yt_entry.bind("<KeyRelease>", self.check_fields)

        # ── Row 2: Options ────────────────────────────────────────────────────
        self.options_frame = ctk.CTkFrame(self)
        self.options_frame.grid(row=2, column=0, padx=20, pady=(0, 10), sticky="ew")
        self.options_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(self.options_frame, text="Cutting Pace:").grid(
            row=0, column=0, padx=10, pady=(12, 2), sticky="w")
        self.threshold_slider = ctk.CTkSlider(
            self.options_frame, from_=1, to=5, number_of_steps=4,
            command=self.on_threshold_change)
        self.threshold_slider.set(3)
        self.threshold_slider.grid(row=0, column=1, padx=10, pady=(12, 2), sticky="ew")
        self.threshold_val_label = ctk.CTkLabel(
            self.options_frame, text="Standard", width=95, anchor="w")
        self.threshold_val_label.grid(row=0, column=2, padx=(0, 10), pady=(12, 2))

        ctk.CTkLabel(
            self.options_frame,
            text="1 = Documentary (15s+ shots)  ·  2 = Drama (6–15s)  ·  3 = Standard (3–6s)  ·  4 = Fast-paced (1–3s)  ·  5 = Action / music video (<1s)",
            font=("Arial", 11), text_color="gray", wraplength=560, justify="left"
        ).grid(row=1, column=0, columnspan=3, padx=10, pady=(0, 8), sticky="w")

        self.local_model_check = ctk.CTkCheckBox(
            self.options_frame, text="Use local Ollama model (no API key needed)")
        self.local_model_check.grid(
            row=2, column=0, columnspan=3, padx=10, pady=(0, 6), sticky="w")

        self.dialogue_check = ctk.CTkCheckBox(
            self.options_frame,
            text="Has dialogue / voiceover  (uses existing subtitles, or WhisperX if none found)")
        self.dialogue_check.grid(
            row=3, column=0, columnspan=3, padx=10, pady=(0, 6), sticky="w")

        self.gemini_check = ctk.CTkCheckBox(
            self.options_frame,
            text="Use Gemini Video AI  (uploads full video; sees motion & character continuity)")
        self.gemini_check.grid(
            row=4, column=0, columnspan=3, padx=10, pady=(0, 6), sticky="w")

        self.flash_check = ctk.CTkCheckBox(
            self.options_frame,
            text="Flash suppression  (ignores scenes < 1.5s — use for strobe / flashing content)")
        self.flash_check.grid(
            row=5, column=0, columnspan=3, padx=10, pady=(0, 12), sticky="w")

        # ── Row 3: Run + Cancel ───────────────────────────────────────────────
        self.controls_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.controls_frame.grid(row=3, column=0, padx=20, pady=(0, 5), sticky="ew")
        self.controls_frame.grid_columnconfigure(0, weight=1)

        self.run_btn = ctk.CTkButton(
            self.controls_frame, text="▶ Start Breakdown Analysis",
            font=("Arial", 16, "bold"), height=50, state="disabled",
            fg_color="green", hover_color="darkgreen",
            command=self.start_analysis_thread)
        self.run_btn.grid(row=0, column=0, sticky="ew", padx=(0, 5))

        self.cancel_btn = ctk.CTkButton(
            self.controls_frame, text="✕ Cancel", width=90, height=50,
            state="disabled", fg_color="#555555", hover_color="#777777",
            command=self.cancel_analysis)
        self.cancel_btn.grid(row=0, column=1)

        # ── Row 4: Progress bar ───────────────────────────────────────────────
        self.progress_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.progress_frame.grid(row=4, column=0, padx=20, pady=(5, 5), sticky="ew")
        self.progress_frame.grid_columnconfigure(0, weight=1)

        self.progress_bar = ctk.CTkProgressBar(self.progress_frame)
        self.progress_bar.set(0)
        self.progress_bar.grid(row=0, column=0, sticky="ew", padx=(0, 10))

        self.progress_label = ctk.CTkLabel(
            self.progress_frame, text="Shot 0 / 0", width=90, anchor="e")
        self.progress_label.grid(row=0, column=1)

        # ── Row 5: Status log ─────────────────────────────────────────────────
        self.status_box = ctk.CTkTextbox(self, state="disabled", height=150)
        self.status_box.grid(row=5, column=0, padx=20, pady=(0, 20), sticky="nsew")

        # Thread-safe stdout redirect
        self.original_stdout = sys.stdout
        sys.stdout = OutputRedirector(self.status_box, self)

    # ── API key ───────────────────────────────────────────────────────────────

    def save_api_key(self):
        key = self.api_entry.get().strip()
        if not key:
            messagebox.showwarning("Warning", "API Key field is empty.")
            return
        env_path = os.path.join(os.getcwd(), ".env")
        set_key(env_path, "KIMI_API_KEY", key)
        os.environ["KIMI_API_KEY"] = key
        messagebox.showinfo("Success", "API Key successfully saved to .env file!")

    def save_gemini_key(self):
        key = self.gemini_entry.get().strip()
        if not key:
            messagebox.showwarning("Warning", "Gemini API Key field is empty.")
            return
        env_path = os.path.join(os.getcwd(), ".env")
        set_key(env_path, "GEMINI_API_KEY", key)
        os.environ["GEMINI_API_KEY"] = key
        messagebox.showinfo("Success", "Gemini API Key successfully saved to .env file!")

    # ── Video selection ───────────────────────────────────────────────────────

    def select_video(self):
        filetypes = (
            ("Video files", "*.mp4 *.webm *.mkv *.avi *.mov"),
            ("All files", "*.*")
        )
        filepath = filedialog.askopenfilename(
            title="Select a Video", initialdir=os.getcwd(), filetypes=filetypes)
        if filepath:
            self.video_path = filepath
            self.file_label.configure(
                text=os.path.basename(filepath), text_color="white", font=("Arial", 14, "bold"))
            self.yt_entry.delete(0, "end")
            self.check_fields()

    def check_fields(self, event=None):
        if self.video_path or self.yt_entry.get().strip():
            self.run_btn.configure(state="normal")
        else:
            self.run_btn.configure(state="disabled")

    def open_downloads(self):
        downloads_dir = os.path.join(os.getcwd(), 'downloads')
        os.makedirs(downloads_dir, exist_ok=True)
        if os.name == 'nt':
            os.startfile(downloads_dir)
        elif sys.platform == 'darwin':
            import subprocess
            subprocess.Popen(['open', downloads_dir])
        else:
            import subprocess
            subprocess.Popen(['xdg-open', downloads_dir])

    # ── Options ───────────────────────────────────────────────────────────────

    def on_threshold_change(self, value):
        self.threshold_val_label.configure(text=PACE_LABEL[int(value)])

    # ── Analysis control ──────────────────────────────────────────────────────

    def cancel_analysis(self):
        self.cancel_event.set()
        self.cancel_btn.configure(state="disabled", text="Cancelling...")
        print("Cancellation requested...")

    def start_analysis_thread(self):
        self.cancel_event.clear()

        # Capture UI values on the main thread before the worker starts
        self._threshold_value   = PACE_THRESHOLD[int(self.threshold_slider.get())]
        self._use_local_model   = bool(self.local_model_check.get())
        self._transcribe_audio  = bool(self.dialogue_check.get())
        self._use_gemini        = bool(self.gemini_check.get())
        self._flash_suppression = bool(self.flash_check.get())

        self.select_btn.configure(state="disabled")
        self.run_btn.configure(state="disabled", text="⏳ Analyzing...")
        self.cancel_btn.configure(state="normal", text="✕ Cancel")
        self.progress_bar.set(0)
        self.progress_label.configure(text="Shot 0 / 0")

        self.status_box.configure(state="normal")
        self.status_box.delete("0.0", "end")
        self.status_box.configure(state="disabled")

        thread = threading.Thread(target=self.run_analysis)
        thread.daemon = True
        thread.start()

    def _on_progress(self, current, total):
        """Called from the worker thread — schedule the UI update on the main thread."""
        self.after(0, lambda c=current, t=total: self._update_progress_ui(c, t))

    def _update_progress_ui(self, current, total):
        progress = current / total if total > 0 else 0
        self.progress_bar.set(progress)
        self.progress_label.configure(text=f"Shot {current} / {total}")

    def run_analysis(self):
        try:
            print("====================================")
            print("Starting Film Breakdown Tool")

            target_path = self.video_path
            yt_url      = self.yt_entry.get().strip()

            if yt_url:
                print(f"YouTube URL detected: {yt_url}")
                print("Downloading video using yt-dlp...")

                deno_exe = os.path.join(os.getcwd(), "deno.exe")
                if not os.path.exists(deno_exe) and os.name == "nt":
                    print("\n[One-Time Setup]: Downloading tiny JS Runtime (Deno) to parse YouTube Age-Gates...")
                    import urllib.request
                    import zipfile
                    try:
                        urllib.request.urlretrieve(
                            'https://github.com/denoland/deno/releases/download/v2.1.2/deno-x86_64-pc-windows-msvc.zip',
                            'deno.zip')
                        with zipfile.ZipFile('deno.zip', 'r') as zip_ref:
                            zip_ref.extractall(os.getcwd())
                        os.remove('deno.zip')
                        print("JS Runtime configured successfully!")
                    except Exception as e:
                        print(f"Warning: Could not auto-download JS Runtime: {e}")

                os.environ["PATH"] = os.getcwd() + os.pathsep + os.environ.get("PATH", "")
                os.makedirs("downloads", exist_ok=True)

                ydl_opts = {
                    'format':          'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
                    'outtmpl':         '%(title).50s [%(id)s]/%(title).50s [%(id)s].%(ext)s',
                    'paths':           {'home': os.path.join(os.getcwd(), 'downloads')},
                    'noplaylist':      True,
                    'quiet':           False,
                    'extractor_args':  {'youtube': {'player_client': ['default', 'tv']}},
                    'writesubtitles':  True,
                    'writeautomaticsub': True,
                    'subtitleslangs':  ['en', 'en-US', 'en-GB'],
                    'subtitlesformat': 'vtt'
                }

                try:
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        info        = ydl.extract_info(yt_url, download=True)
                        target_path = ydl.prepare_filename(info)
                        print(f"Download complete: {target_path}")
                except Exception as e:
                    err_msg = str(e).lower()
                    if "confirm your age" in err_msg or "inappropriate for some users" in err_msg or "cookie" in err_msg:
                        download_success = False
                        if os.path.exists("cookies.txt"):
                            print("\nAge-restricted video detected; found local 'cookies.txt'. Using that...")
                            ydl_opts["cookiefile"] = os.path.join(os.getcwd(), "cookies.txt")
                            try:
                                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                                    info        = ydl.extract_info(yt_url, download=True)
                                    target_path = ydl.prepare_filename(info)
                                    print(f"Download complete via cookies.txt: {target_path}")
                                download_success = True
                            except Exception as cookies_txt_err:
                                print(f"Failed using cookies.txt: {cookies_txt_err}")

                        if not download_success:
                            print("\nAttempting to bypass using local browser cookies...")

                            arc_dirs = glob.glob(os.path.join(
                                os.environ.get("LOCALAPPDATA", ""),
                                "Packages", "TheBrowserCompany.Arc*",
                                "LocalCache", "Local", "Arc", "User Data"))

                            browsers_to_try = []
                            if arc_dirs:
                                browsers_to_try.append(("chrome", arc_dirs[0]))
                            browsers_to_try.extend([("edge",), ("chrome",)])

                            success = False
                            for browser_cfg in browsers_to_try:
                                browser_name = browser_cfg[0] if len(browser_cfg) == 1 else "arc"
                                print(f"Trying to extract logged-in cookies from: {browser_name.upper()}...")
                                ydl_opts["cookiesfrombrowser"] = browser_cfg
                                try:
                                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                                        info        = ydl.extract_info(yt_url, download=True)
                                        target_path = ydl.prepare_filename(info)
                                        print(f"Download complete via {browser_name.upper()} cookies: {target_path}")
                                        success = True
                                        break
                                except Exception as browser_err:
                                    browser_err_msg = str(browser_err).lower()
                                    if "permission denied" in browser_err_msg or "locked" in browser_err_msg:
                                        raise PermissionError(
                                            f"Your {browser_name.upper()} browser is actively locking its cookie database! "
                                            "Please completely CLOSE your browser (all windows) and hit Start again.")
                                    print(f"Failed extracting from {browser_name.upper()}: {browser_err}")

                            download_success = success

                        if not download_success:
                            raise Exception(
                                "Failed to bypass age-restriction. Please either:\n"
                                "1. Install the 'Get cookies.txt LOCALLY' extension, export your YouTube cookies, "
                                "and save them as 'cookies.txt' in this directory.\n"
                                "2. Or, log into YouTube on Microsoft Edge and let the script run.")
                    else:
                        raise e

            if not target_path or not os.path.exists(target_path):
                raise ValueError("No valid video file could be found to process.")

            print(f"Target: {target_path}")
            print("====================================\n")

            result_warnings = analyze_video(
                target_path,
                mock_test=False,
                threshold=self._threshold_value,
                cancel_event=self.cancel_event,
                progress_callback=self._on_progress,
                use_local_model=self._use_local_model,
                transcribe_audio=self._transcribe_audio,
                use_gemini=self._use_gemini,
                flash_suppression=self._flash_suppression,
            )

            if self.cancel_event.is_set():
                print("\n⚠️ Analysis cancelled. Progress saved — re-run to resume.")
                messagebox.showinfo(
                    "Cancelled",
                    "Analysis cancelled. Progress has been saved.\nRe-run the same video to resume.")
            else:
                print("\n✅ Process Completed Successfully!")
                if result_warnings:
                    for w in result_warnings:
                        messagebox.showwarning("Warning", w)
                messagebox.showinfo(
                    "Success",
                    "Film Breakdown completed!\nCheck the video folder for the generated .xlsx file.")

        except Exception as e:
            print(f"\n❌ Error during execution: {e}")
            messagebox.showerror("Error", f"An error occurred:\n{e}")
        finally:
            self.select_btn.configure(state="normal")
            self.run_btn.configure(state="normal", text="▶ Start Breakdown Analysis")
            self.cancel_btn.configure(state="disabled", text="✕ Cancel")

    def destroy(self):
        sys.stdout = self.original_stdout
        super().destroy()


class OutputRedirector:
    """Thread-safe stdout redirect — schedules all writes on the Tk main thread."""
    def __init__(self, text_widget, app):
        self.text_widget = text_widget
        self.app         = app

    def write(self, string):
        self.app.after(0, lambda s=string: self._do_write(s))

    def _do_write(self, string):
        self.text_widget.configure(state="normal")
        self.text_widget.insert("end", string)
        self.text_widget.see("end")
        self.text_widget.configure(state="disabled")

    def flush(self):
        pass


if __name__ == "__main__":
    app = FilmBreakdownApp()
    app.mainloop()
