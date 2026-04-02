# GTA V User Music Manager

## What It Does
- Manages GTA V / GTAV Enhanced User Music tracks in one place.
- Downloads songs from YouTube by song search, video URL, playlist URL, or comma-separated batch input.
- Renames downloads into a clean `Artist - Song` format when possible.
- Lets you preview, search, sort, and delete tracks from your User Music folder.

## Supported Download Modes
1. Single song search
   Type a song name. For better results, include the artist name too.
   Example: `Luis Fonsi Despacito`

2. YouTube video URL
   Paste a direct YouTube song/video URL.

3. YouTube playlist URL
   Paste one playlist URL to download the full playlist.
   Use one playlist at a time.

4. Batch download
   Type multiple entries separated by commas.
   Example: `Luis Fonsi Despacito, The Weeknd Blinding Lights, Adele Hello`

## How To Use
1. Run `GTA Muisc Manager.exe`.
2. Check the folder path at the top.
3. If the default GTA User Music folder was not found, click `Browse...` and set it manually.
4. Use the sync input box to search songs or paste YouTube URLs.
5. Click `SYNC LIBRARY` to download and import tracks.
6. Use the Stored Tracks search box to filter your library.
7. Use the sort menus to sort by date added, alphabetical order, or song length in ascending or descending order.
8. Use the play button to preview a track.
9. Use the red hover `X` button to delete the selected song file from the visible library list.

## Single-EXE Build Notes
- The app keeps its config file in the same folder as the `.exe`.
- The single-file build bundles the Python libraries and the required `ffmpeg` tools inside the executable.
- End users do not need to place `ffmpeg.exe` or `ffprobe.exe` beside the final `.exe`.
- Internet is required for downloads.
- Search matching in the library is typo-tolerant for small spelling mistakes.
- If a downloaded filename already exists, the app keeps both files by creating a numbered name instead of overwriting the old one.

## Safety
- Delete actions target the exact file shown in the visible list, not the whole folder.
- Even so, keep backups of your music if it matters to you.
- This tool is provided without warranty. Use at your own risk.
