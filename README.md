# DLB Player Mod Merger

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Latest Release](https://img.shields.io/github/v/release/KuroKim/DLB_Mod_Merger)](https://github.com/KuroKim/DLB_Mod_Merger/releases)

A powerful yet simple command-line tool for intelligently merging Dying Light mods that edit `player_variables.scr` and other game files. Stop choosing between your favorite mods—use them all!

This tool solves the classic problem where installing one mod overwrites another because they both modify the same files. It combines their features into a single, stable mod pack.

## Key Features

-   **✨ Smart Merging:** Automatically combines all non-conflicting changes from your mods into one master `player_variables.scr`.
-   **🤝 Interactive Conflict Resolution:** If two mods change the same setting (e.g., inventory size), the tool will stop and ask you which version you want to keep. You have full control!
-   **🗃️ Additional File Handling:** The tool also detects other files in mod archives (like weather scripts). If it finds duplicates, it will ask you which one to include in the final `.pak`.
-   **🤖 Automatic `.pak` Creation:** The final result is a clean, ready-to-use `data3.pak` file, placed in a familiar output folder. No extra steps needed.
-   ** ZIP & 7z Support:** No need to unpack anything! Just drop your mods in `.zip` or `.7z` format directly into the folder.

---

## How to Use (For Users)

Getting started is incredibly simple. The required original game file (`data0.pak`) is already included in the release for your convenience.

1.  Go to the **[Releases](https://github.com/KuroKim/DLB_Mod_Merger/releases)** page on the right.
2.  Download the latest release archive (e.g., `DLB_Mod_Merger_v1.0.zip`).
3.  Extract the archive to a folder on your computer. You will see this structure:
    ```
    /DLB_Mod_Merger/
    |-- mod_merger.exe         (The application)
    |-- /01_Original_Game_File/ (Contains data0.pak)
    |-- /02_Put_Mods_Here/      (This is where your mods go)
    ```
4.  Place all the mods you want to merge (as `.zip` or `.7z` archives) into the **`02_Put_Mods_Here`** folder.
5.  Double-click **`mod_merger.exe`** to run it.
6.  Follow the on-screen instructions and answer any questions if conflicts are found.
7.  Once finished, a new folder named **`OUTPUT_Merged_Mod`** will appear. Inside, you will find your new, perfectly merged `data3.pak`.
8.  Copy this `data3.pak` into your game installation folder at `\Dying Light\ph_ft\source\`, replacing any existing file if prompted.

---

## How to Build from Source (For Advanced Users)

This tool is completely open-source. If you have concerns about running an `.exe` file, want to compile it for another OS like Linux, or simply want to see how it works, you can build it yourself.

**Prerequisites:**
-   [Python](https://www.python.org/downloads/) (version 3.10 or newer is recommended).
-   [Git](https://git-scm.com/downloads).

**Steps:**

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/KuroKim/DLB_Mod_Merger.git
    cd DLB_Mod_Merger
    ```

2.  **Create a virtual environment (recommended):**
    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows, use `venv\Scripts\activate`
    ```

3.  **Install dependencies:**
    The project uses a few Python libraries. Install them easily with this command:
    ```bash
    pip install -r requirements.txt
    ```

4.  **Build the executable:**
    Use PyInstaller to package the script into a single `.exe` file.
    ```bash
    pyinstaller --onefile mod_merger.py
    ```

5.  **Find your file:**
    The finished `mod_merger.exe` will be located in the `dist` folder. You can then create the `01_Original_Game_File` and `02_Put_Mods_Here` folders alongside it to replicate the release structure.

## How It Works

The logic is straightforward:
1.  The tool reads the original `player_variables.scr` from the provided `data0.pak`.
2.  It scans the `02_Put_Mods_Here` folder, opening each `.zip` or `.7z` archive in memory.
3.  It finds all instances of `player_variables.scr` and other files inside the mod archives.
4.  It compares each mod's `player_variables.scr` to the original, identifying every changed line.
5.  It builds a "changes map." If multiple mods alter the same line, it flags it as a conflict.
6.  It asks the user to resolve all conflicts.
7.  Finally, it applies all chosen changes to the original file and packages the result, along with any other files, into a new `data3.pak`.

## License

This project is licensed under the MIT License. See the `LICENSE` file for details.```
