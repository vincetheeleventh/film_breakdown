import os
import sys
import threading
import glob
import customtkinter as ctk
import yt_dlp
from tkinter import filedialog, messagebox
from dotenv import load_dotenv

from analyze_film import analyze_video

# ── Palette ───────────────────────────────────────────────────────────────────
PARCHMENT  = "#F5F0E8"   # warm cream — app background
CARD_BG    = "#FDFBF7"   # off-white — card fill
NEAR_BLACK = "#1A1614"   # almost-black — borders & primary text
CRIMSON    = "#8B1A1A"   # deep red — accent, run button
WARM_MID   = "#B8AFA6"   # muted — slider track, disabled
WARM_GRAY  = "#7A6E67"   # subdued — labels, captions

ctk.set_appearance_mode("Light")
ctk.set_default_color_theme("blue")   # individual colors overridden below

PACE_THRESHOLD = {
    1: 40,   # Documentary
    2: 32,   # Drama
    3: 27,   # Standard
    4: 18,   # Fast-paced
    5: 10,   # Action
}
PACE_LABEL = {
    1: "Documentary",
    2: "Drama",
    3: "Standard",
    4: "Fast-paced",
    5: "Action",
}


def _card(parent, **kw):
    """Neobrutalist card: square corners, 2 px black border."""
    return ctk.CTkFrame(
        parent,
        fg_color=CARD_BG,
        corner_radius=0,
        border_width=2,
        border_color=NEAR_BLACK,
        **kw,
    )


class FilmBreakdownApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Film Breakdown")
        self.geometry("600x720")
        self.configure(fg_color=PARCHMENT)
        self.resizable(False, True)

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(6, weight=1)   # log row expands

        self.cancel_event = threading.Event()
        self.video_path   = None

        load_dotenv()

        # ── Header ────────────────────────────────────────────────────────────
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.grid(row=0, column=0, padx=24, pady=(24, 0), sticky="ew")
        hdr.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            hdr, text="FILM BREAKDOWN",
            font=ctk.CTkFont(family="Georgia", size=26, weight="bold"),
            text_color=NEAR_BLACK, anchor="w",
        ).grid(row=0, column=0, sticky="w")

        ctk.CTkLabel(
            hdr, text="AI-POWERED SHOT ANALYSIS",
            font=ctk.CTkFont(family="Georgia", size=10),
            text_color=WARM_GRAY, anchor="w",
        ).grid(row=1, column=0, pady=(1, 0), sticky="w")

        # rule
        ctk.CTkFrame(
            self, fg_color=NEAR_BLACK, height=3, corner_radius=0,
        ).grid(row=1, column=0, padx=24, pady=(10, 18), sticky="ew")

        # ── Video source card ─────────────────────────────────────────────────
        vsrc = _card(self)
        vsrc.grid(row=2, column=0, padx=24, pady=(0, 10), sticky="ew")
        vsrc.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            vsrc, text="VIDEO SOURCE",
            font=ctk.CTkFont(family="Georgia", size=9, weight="bold"),
            text_color=WARM_GRAY,
        ).grid(row=0, column=0, columnspan=4, padx=14, pady=(10, 0), sticky="w")

        self.file_label = ctk.CTkLabel(
            vsrc, text="No file selected",
            font=ctk.CTkFont(size=12),
            text_color=WARM_MID, anchor="w",
        )
        self.file_label.grid(row=1, column=0, columnspan=2,
                              padx=14, pady=(4, 8), sticky="ew")

        self.select_btn = ctk.CTkButton(
            vsrc, text="Browse File",
            corner_radius=0, border_width=2, border_color=NEAR_BLACK,
            fg_color=CARD_BG, hover_color="#EDE8DF",
            text_color=NEAR_BLACK,
            font=ctk.CTkFont(size=12, weight="bold"),
            width=118, height=32,
            command=self.select_video,
        )
        self.select_btn.grid(row=1, column=2, padx=(4, 4), pady=(4, 8))

        ctk.CTkButton(
            vsrc, text="Downloads",
            corner_radius=0, border_width=2, border_color=NEAR_BLACK,
            fg_color=CARD_BG, hover_color="#EDE8DF",
            text_color=NEAR_BLACK,
            font=ctk.CTkFont(size=12),
            width=92, height=32,
            command=self.open_downloads,
        ).grid(row=1, column=3, padx=(0, 14), pady=(4, 8))

        ctk.CTkFrame(vsrc, fg_color=NEAR_BLACK, height=1, corner_radius=0).grid(
            row=2, column=0, columnspan=4, sticky="ew", padx=14)

        ctk.CTkLabel(
            vsrc, text="YouTube URL",
            font=ctk.CTkFont(family="Georgia", size=10),
            text_color=WARM_GRAY,
        ).grid(row=3, column=0, padx=14, pady=(8, 10), sticky="w")

        self.yt_entry = ctk.CTkEntry(
            vsrc,
            placeholder_text="https://www.youtube.com/watch?v=...",
            corner_radius=0, border_width=2, border_color=NEAR_BLACK,
            fg_color=CARD_BG, text_color=NEAR_BLACK,
            font=ctk.CTkFont(size=12),
            height=34,
        )
        self.yt_entry.grid(row=3, column=1, columnspan=3,
                            padx=(0, 14), pady=(8, 10), sticky="ew")
        self.yt_entry.bind("<KeyRelease>", self.check_fields)

        # ── Options card ──────────────────────────────────────────────────────
        opts = _card(self)
        opts.grid(row=3, column=0, padx=24, pady=(0, 10), sticky="ew")
        opts.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            opts, text="CUTTING PACE",
            font=ctk.CTkFont(family="Georgia", size=9, weight="bold"),
            text_color=WARM_GRAY,
        ).grid(row=0, column=0, columnspan=4, padx=14, pady=(10, 2), sticky="w")

        ctk.CTkLabel(
            opts, text="Slower",
            font=ctk.CTkFont(size=10), text_color=WARM_GRAY,
        ).grid(row=1, column=0, padx=(14, 2), pady=4, sticky="w")

        self.threshold_slider = ctk.CTkSlider(
            opts, from_=1, to=5, number_of_steps=4,
            button_color=CRIMSON, button_hover_color="#6B1414",
            progress_color=CRIMSON, fg_color=WARM_MID,
            command=self.on_threshold_change,
        )
        self.threshold_slider.set(4)   # default: Fast-paced
        self.threshold_slider.grid(row=1, column=1, padx=4, pady=4, sticky="ew")

        ctk.CTkLabel(
            opts, text="Faster",
            font=ctk.CTkFont(size=10), text_color=WARM_GRAY,
        ).grid(row=1, column=2, padx=(2, 8), pady=4)

        self.threshold_val_label = ctk.CTkLabel(
            opts, text="Fast-paced",
            font=ctk.CTkFont(family="Georgia", size=11, weight="bold"),
            text_color=CRIMSON,
        )
        self.threshold_val_label.grid(row=1, column=3, padx=(0, 14), pady=4)

        ctk.CTkFrame(opts, fg_color=NEAR_BLACK, height=1, corner_radius=0).grid(
            row=2, column=0, columnspan=4, sticky="ew", padx=14, pady=(4, 0))

        chk_row = ctk.CTkFrame(opts, fg_color="transparent")
        chk_row.grid(row=3, column=0, columnspan=4, padx=14, pady=(8, 12), sticky="w")

        _chk_kw = dict(
            font=ctk.CTkFont(size=12), text_color=NEAR_BLACK,
            fg_color=CRIMSON, hover_color="#6B1414",
            checkmark_color=CARD_BG,
            border_color=NEAR_BLACK, corner_radius=0,
        )

        self.gemini_check = ctk.CTkCheckBox(chk_row, text="Gemini Video AI", **_chk_kw)
        self.gemini_check.pack(side="left", padx=(0, 22))
        self.gemini_check.select()

        self.dialogue_check = ctk.CTkCheckBox(chk_row, text="Dialogue / Subtitles", **_chk_kw)
        self.dialogue_check.pack(side="left")

        # ── Run + Cancel ──────────────────────────────────────────────────────
        run_row = ctk.CTkFrame(self, fg_color="transparent")
        run_row.grid(row=4, column=0, padx=24, pady=(0, 10), sticky="ew")
        run_row.grid_columnconfigure(0, weight=1)

        self.run_btn = ctk.CTkButton(
            run_row,
            text="▶  START BREAKDOWN",
            font=ctk.CTkFont(family="Georgia", size=15, weight="bold"),
            height=52, state="disabled",
            corner_radius=0, border_width=2, border_color=NEAR_BLACK,
            fg_color=CRIMSON, hover_color="#6B1414",
            text_color=PARCHMENT,
            command=self.start_analysis_thread,
        )
        self.run_btn.grid(row=0, column=0, sticky="ew", padx=(0, 8))

        self.cancel_btn = ctk.CTkButton(
            run_row,
            text="✕",
            font=ctk.CTkFont(size=15, weight="bold"),
            width=52, height=52, state="disabled",
            corner_radius=0, border_width=2, border_color=NEAR_BLACK,
            fg_color=CARD_BG, hover_color="#EDE8DF",
            text_color=NEAR_BLACK,
            command=self.cancel_analysis,
        )
        self.cancel_btn.grid(row=0, column=1)

        # ── Progress ──────────────────────────────────────────────────────────
        prog_row = ctk.CTkFrame(self, fg_color="transparent")
        prog_row.grid(row=5, column=0, padx=24, pady=(0, 8), sticky="ew")
        prog_row.grid_columnconfigure(0, weight=1)

        self.progress_bar = ctk.CTkProgressBar(
            prog_row,
            corner_radius=0, border_width=0, height=6,
            progress_color=CRIMSON, fg_color=WARM_MID,
        )
        self.progress_bar.set(0)
        self.progress_bar.grid(row=0, column=0, sticky="ew", padx=(0, 10))

        self.progress_label = ctk.CTkLabel(
            prog_row, text="Shot 0 / 0",
            font=ctk.CTkFont(family="Georgia", size=10),
            text_color=WARM_GRAY, width=90, anchor="e",
        )
        self.progress_label.grid(row=0, column=1)

        # ── Status log ────────────────────────────────────────────────────────
        self.status_box = ctk.CTkTextbox(
            self, state="disabled", height=160,
            corner_radius=0, border_width=2, border_color=NEAR_BLACK,
            fg_color=NEAR_BLACK, text_color="#C4B6AC",
            font=ctk.CTkFont(family="Courier New", size=11),
            scrollbar_button_color=WARM_GRAY,
            scrollbar_button_hover_color=WARM_MID,
        )
        self.status_box.grid(row=6, column=0, padx=24, pady=(0, 24), sticky="nsew")

        self.original_stdout = sys.stdout
        sys.stdout = OutputRedirector(self.status_box, self)

    # ── Video selection ───────────────────────────────────────────────────────

    def select_video(self):
        filetypes = (
            ("Video files", "*.mp4 *.webm *.mkv *.avi *.mov"),
            ("All files", "*.*"),
        )
        filepath = filedialog.askopenfilename(
            title="Select a Video", initialdir=os.getcwd(), filetypes=filetypes)
        if filepath:
            self.video_path = filepath
            self.file_label.configure(
                text=os.path.basename(filepath),
                text_color=NEAR_BLACK,
                font=ctk.CTkFont(size=12, weight="bold"),
            )
            self.yt_entry.delete(0, "end")
            self.check_fields()

    def check_fields(self, event=None):
        if self.video_path or self.yt_entry.get().strip():
            self.run_btn.configure(state="normal")
        else:
            self.run_btn.configure(state="disabled")

    def open_downloads(self):
        downloads_dir = os.path.join(os.getcwd(), "downloads")
        os.makedirs(downloads_dir, exist_ok=True)
        if os.name == "nt":
            os.startfile(downloads_dir)
        elif sys.platform == "darwin":
            import subprocess
            subprocess.Popen(["open", downloads_dir])
        else:
            import subprocess
            subprocess.Popen(["xdg-open", downloads_dir])

    # ── Options ───────────────────────────────────────────────────────────────

    def on_threshold_change(self, value):
        self.threshold_val_label.configure(text=PACE_LABEL[int(value)])

    # ── Analysis control ──────────────────────────────────────────────────────

    def _show_success_dialog(self, xlsx_path):
        """Completion dialog — called on main thread."""
        dialog = ctk.CTkToplevel(self)
        dialog.title("Complete")
        dialog.geometry("420x150")
        dialog.resizable(False, False)
        dialog.configure(fg_color=PARCHMENT)
        dialog.lift()
        dialog.focus()

        ctk.CTkLabel(
            dialog, text="BREAKDOWN COMPLETE",
            font=ctk.CTkFont(family="Georgia", size=15, weight="bold"),
            text_color=NEAR_BLACK,
        ).pack(pady=(22, 4))
        ctk.CTkLabel(
            dialog, text=str(xlsx_path),
            font=ctk.CTkFont(size=10), text_color=WARM_GRAY, wraplength=380,
        ).pack(pady=(0, 14))

        btn_row = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_row.pack()

        def open_xlsx():
            try:
                os.startfile(str(xlsx_path))
            except Exception as e:
                messagebox.showerror("Error", f"Could not open file:\n{e}")
            dialog.destroy()

        ctk.CTkButton(
            btn_row, text="Open Spreadsheet",
            corner_radius=0, border_width=2, border_color=NEAR_BLACK,
            fg_color=CRIMSON, hover_color="#6B1414",
            text_color=PARCHMENT,
            font=ctk.CTkFont(family="Georgia", size=12, weight="bold"),
            width=150, height=36,
            command=open_xlsx,
        ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            btn_row, text="Close",
            corner_radius=0, border_width=2, border_color=NEAR_BLACK,
            fg_color=CARD_BG, hover_color="#EDE8DF",
            text_color=NEAR_BLACK,
            font=ctk.CTkFont(size=12),
            width=80, height=36,
            command=dialog.destroy,
        ).pack(side="left")

    def cancel_analysis(self):
        self.cancel_event.set()
        self.cancel_btn.configure(state="disabled", text="…")
        print("Cancellation requested...")

    def start_analysis_thread(self):
        self.cancel_event.clear()

        self._threshold_value  = PACE_THRESHOLD[int(self.threshold_slider.get())]
        self._use_local_model  = False   # Ollama removed from UI; set in .env if needed
        self._transcribe_audio = bool(self.dialogue_check.get())
        self._use_gemini       = bool(self.gemini_check.get())
        self._flash_suppression = False  # accessible via CLI if needed

        self.select_btn.configure(state="disabled")
        self.run_btn.configure(state="disabled", text="⏳  Analyzing…")
        self.cancel_btn.configure(state="normal", text="✕")
        self.progress_bar.set(0)
        self.progress_label.configure(text="Shot 0 / 0")

        self.status_box.configure(state="normal")
        self.status_box.delete("0.0", "end")
        self.status_box.configure(state="disabled")

        thread = threading.Thread(target=self.run_analysis)
        thread.daemon = True
        thread.start()

    def _on_progress(self, current, total):
        self.after(0, lambda c=current, t=total: self._update_progress_ui(c, t))

    def _update_progress_ui(self, current, total):
        self.progress_bar.set(current / total if total > 0 else 0)
        self.progress_label.configure(text=f"Shot {current} / {total}")

    def run_analysis(self):
        try:
            print("=" * 44)
            print("  FILM BREAKDOWN — starting analysis")
            print("=" * 44)

            target_path = self.video_path
            yt_url      = self.yt_entry.get().strip()

            if yt_url:
                print(f"YouTube URL: {yt_url}")
                print("Downloading via yt-dlp...")

                deno_exe = os.path.join(os.getcwd(), "deno.exe")
                if not os.path.exists(deno_exe) and os.name == "nt":
                    print("\n[Setup] Downloading Deno JS runtime for YouTube age-gates...")
                    import urllib.request, zipfile
                    try:
                        urllib.request.urlretrieve(
                            "https://github.com/denoland/deno/releases/download/v2.1.2/deno-x86_64-pc-windows-msvc.zip",
                            "deno.zip")
                        with zipfile.ZipFile("deno.zip", "r") as z:
                            z.extractall(os.getcwd())
                        os.remove("deno.zip")
                        print("Deno installed.")
                    except Exception as e:
                        print(f"Warning: could not install Deno: {e}")

                os.environ["PATH"] = os.getcwd() + os.pathsep + os.environ.get("PATH", "")
                os.makedirs("downloads", exist_ok=True)

                ydl_opts = {
                    "format":          "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
                    "outtmpl":         "%(title).50s [%(id)s]/%(title).50s [%(id)s].%(ext)s",
                    "paths":           {"home": os.path.join(os.getcwd(), "downloads")},
                    "noplaylist":      True,
                    "quiet":           False,
                    "extractor_args":  {"youtube": {"player_client": ["default", "tv"]}},
                    "writesubtitles":  True,
                    "writeautomaticsub": True,
                    "subtitleslangs":  ["en", "en-US", "en-GB"],
                    "subtitlesformat": "vtt",
                }

                try:
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        info        = ydl.extract_info(yt_url, download=True)
                        target_path = ydl.prepare_filename(info)
                        print(f"Download complete: {target_path}")
                except Exception as e:
                    err_msg = str(e).lower()
                    if "confirm your age" in err_msg or "inappropriate" in err_msg or "cookie" in err_msg:
                        download_success = False
                        if os.path.exists("cookies.txt"):
                            print("\nAge-restricted — using cookies.txt...")
                            ydl_opts["cookiefile"] = os.path.join(os.getcwd(), "cookies.txt")
                            try:
                                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                                    info        = ydl.extract_info(yt_url, download=True)
                                    target_path = ydl.prepare_filename(info)
                                    print(f"Download complete (cookies.txt): {target_path}")
                                download_success = True
                            except Exception as cookies_txt_err:
                                print(f"cookies.txt failed: {cookies_txt_err}")

                        if not download_success:
                            print("\nTrying browser cookies...")
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
                                bname = browser_cfg[0] if len(browser_cfg) == 1 else "arc"
                                print(f"  Trying {bname.upper()} cookies...")
                                ydl_opts["cookiesfrombrowser"] = browser_cfg
                                try:
                                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                                        info        = ydl.extract_info(yt_url, download=True)
                                        target_path = ydl.prepare_filename(info)
                                        print(f"  Downloaded via {bname.upper()}: {target_path}")
                                        success = True
                                        break
                                except Exception as be:
                                    bem = str(be).lower()
                                    if "permission denied" in bem or "locked" in bem:
                                        raise PermissionError(
                                            f"{bname.upper()} is locking its cookie database. "
                                            "Close all browser windows and retry.")
                                    print(f"  {bname.upper()} failed: {be}")

                            download_success = success

                        if not download_success:
                            raise Exception(
                                "Age-restriction bypass failed.\n"
                                "Export YouTube cookies via 'Get cookies.txt LOCALLY' and save as cookies.txt, "
                                "or log into YouTube on Edge and retry.")
                    else:
                        raise e

            if not target_path or not os.path.exists(target_path):
                raise ValueError("No valid video file found.")

            print(f"\nTarget: {target_path}\n")

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
                print("\n— Analysis cancelled. Progress saved.")
                messagebox.showinfo(
                    "Cancelled",
                    "Analysis cancelled.\nRe-run the same video to resume.")
            else:
                print("\n— Done.")
                if result_warnings:
                    for w in result_warnings:
                        messagebox.showwarning("Warning", w)
                from pathlib import Path as _Path
                xlsx_path = _Path(target_path).parent / f"breakdown_{_Path(target_path).stem}.xlsx"
                self.after(0, lambda p=xlsx_path: self._show_success_dialog(p))

        except Exception as e:
            print(f"\n! Error: {e}")
            messagebox.showerror("Error", f"An error occurred:\n{e}")
        finally:
            self.select_btn.configure(state="normal")
            self.run_btn.configure(state="normal", text="▶  START BREAKDOWN")
            self.cancel_btn.configure(state="disabled", text="✕")

    def destroy(self):
        sys.stdout = self.original_stdout
        super().destroy()


class OutputRedirector:
    """Thread-safe stdout redirect to the status log."""
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
