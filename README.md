# 🎬 Film Breakdown AI

An automated video analysis tool for professional filmmakers, editors, and film students. This tool ingests a localized video file or a public YouTube link, automatically dissects it shot-by-shot using `PySceneDetect`, downloads the aligned subtitles using `youtube-transcript-api`, and uses the **Moonshot Kimi K2.5 Vision API** to generate a granular, contextual spreadsheet breakdown.

## 🚀 Features
- **Painless UI**: Fully featured CustomTkinter GUI for easy execution and parsing.
- **YouTube Integration**: Simply drop a YouTube URL; it auto-downloads the video via `yt-dlp` and its subtitles without you ever touching a file.
- **Shot-by-Shot Contextual Analysis**: Powered by Kimi K2.5's massive context window, the model receives prior narrative data alongside every keyframe.
- **Dynamic Excel Generations**: Exports right into `.xlsx` using Pandas. Includes perfectly scaled visual thumbnails for each shot alongside extracted timestamps, dialogue/subtitle logs, shot types, inferred camera movement, and character tracking.

---

## 🛠 For New Users

### Prerequisites
1. **Python 3.10+**
2. A **Moonshot API Key**: Get one at [platform.moonshot.cn](https://platform.moonshot.cn/console/api-keys). Note that you need credits in your account before utilizing Vision models.

### Installation & Execution (For Beginners)

If you just open Command Prompt (CMD) in this folder and type `python app.py`, you will likely get a bunch of "Module Not Found" errors. This happens because the custom tools this app uses are not installed on your entire computer globally by default.

Because of this, we've built an auto-launcher to handle everything for you! 

**Just double-click the `run_app.bat` file.** 
*(It will automatically create a private "virtual environment" bubble, install all requirements, and open the app UI for you.)*

#### What if I want to run it manually via Command Line?
If you'd prefer to manage your environment explicitly:
1. Open up Command Prompt (CMD) or PowerShell and navigate to this folder.
2. **Create the bubble (first time only):**
   ```bash
   python -m venv venv
   ```
   *This creates a new folder called `venv` that contains a private copy of Python.*
3. **Step into the bubble:**
   You must "activate" the environment every time you open a new terminal to use the app.
   ```bash
   .\venv\Scripts\activate
   ```
   *(You will know it worked if you see `(venv)` appear at the beginning of your command line.)*
4. **Install the tools (first time only):**
   ```bash
   pip install -r requirements.txt
   ```
   *(This tells the bubble to download all the necessary tools listed in the text file.)*
5. **Launch the App:**
   ```bash
   python app.py
   ```
   *As long as `(venv)` is showing on your terminal, `python` knows to look inside the bubble for the tools.*

If you close the terminal and come back tomorrow, simply run step 3, then step 5!

6. Enter your `KIMI_API_KEY` in the top field within the app and save it.
7. Browse for a local video or paste a YouTube link, then click **Start Breakdown Analysis**.

*(The finalized breakdown `.xlsx` file and the generated thumbnail frames will be dropped into the directory the original video resides in!)*

---

## 👨‍💻 For New Developers

### Project Structure
- `app.py`: The Main UI Layer utilizing `customtkinter`. It is heavily decoupled from the parsing logic to allow rapid thread deployment.
- `analyze_film.py`: The core brain. It handles the `scenedetect` logic, frame slicing via `OpenCV`, YouTube subtitle pinging via Regex + ID matching, LLM prompt engineering, and Pandas to Excel conversion logic.
- `requirements.txt`: Contains all vital dependencies including `yt-dlp`.

### How It Works under the Hood
To avoid expensive "Video Processing" algorithms, we map out the video in 2 Dimensions using `PySceneDetect` to grab the specific timestamp of a harsh cut.

```python
# From `analyze_film.py`
target_frame = start_frame + 8  # We grab the visual ~330ms after the cut
```
We grab the frame exactly 8 frames *after* a scene starts to ensure we've bypassed any cross-fade bleed and reliably capture an image exactly when a viewer would register it. 

### To-Do / Roadmap
- Introduce audio waveform parsing to grab cuts that `scenedetect` misses.
- Allow swapping of different foundational models (e.g. OpenAI GPT-4o).
- Implement persistent SQLite DB instances for historical lookup instead of wiping logs.
