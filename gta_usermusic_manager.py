import os
import re
import sys
import json
import difflib
import ctypes
import threading
import time
import customtkinter as ctk
from tkinter import filedialog, messagebox
import yt_dlp
import pygame
from mutagen.mp3 import MP3

# --- CONFIGURATION & STYLING ---
ctk.set_appearance_mode("Dark")
ACCENT_COLOR = "#FF3131"
BG_COLOR = "#0D0D0D"
CARD_COLOR = "#1A1A1A"
DELETE_BTN_COLOR = "#2B2B2B"
DELETE_BTN_HOVER = ACCENT_COLOR
PLAY_SYMBOL = "▶"
PAUSE_SYMBOL = "⏸"
SEARCH_DELAY_MS = 350
MIN_SEARCH_LENGTH = 3
TOOLTIP_TEXT = (
    "Supported Modes -\n"
    "1.) Single song (mention artist name for accurate results)\n"
    "2.) Youtube URL's (Playlist Supported too but a single playlist at a time)\n"
    "3.) Batch download (type multiple songs (artist) entries separated by a comma)"
)

class GTAMusicManager(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("GTA V Music Manager 2026")
        self.geometry("1100x850")
        self.configure(fg_color=BG_COLOR)

        pygame.mixer.init()

        # --- PORTABLE & CONFIG LOGIC ---
        if getattr(sys, 'frozen', False):
            # Running as EXE
            self.app_dir = os.path.dirname(sys.executable)
        else:
            # Running as Script
            self.app_dir = os.path.dirname(os.path.abspath(__file__))
        self.bundle_dir = getattr(sys, "_MEIPASS", self.app_dir)
        self.engine_dir = os.path.join(self.app_dir, "engine")

        self.config_file = os.path.join(self.app_dir, "manager_config.txt")
        self.config = self.load_config()
        self.default_gta_path = self.find_gta_user_music_path() or ""
        self.default_path_placeholder = (
            f"Default: {self.default_gta_path}"
            if self.default_gta_path
            else "Default Path Cant be Found, Set manually"
        )
        self.current_target_path = self.config.get("target_path") or self.default_gta_path

        # State
        self.playing_filename = None
        self.song_duration = 0
        self.is_paused = False
        self.is_seeking = False
        self.seek_offset = 0
        self.active_widgets = {} 
        self.current_volume = 0.5 
        self.placeholder_state = {}
        self.pending_search_job = None
        self.pending_refresh_job = None
        self.library_cache = {}
        self.library_index = {}
        self.sort_mode = ctk.StringVar(value="Date Added")
        self.sort_direction = ctk.StringVar(value=self.config.get("sort_direction", "Descending"))
        self.tooltip_window = None
        self.tooltip_hide_job = None

        self.configure_window_icon()
        self.setup_ui()
        self.maybe_show_disclaimer()
        self.check_ffmpeg()
        self.refresh_file_list()
        self.update_playback_loop()

    def configure_window_icon(self):
        icon_path = next(
            (
                os.path.join(base_dir, "app.ico")
                for base_dir in (self.app_dir, self.engine_dir, self.bundle_dir)
                if os.path.exists(os.path.join(base_dir, "app.ico"))
            ),
            None
        )
        if not icon_path:
            return

        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("GTAV.UserMusicManager")
        except Exception:
            pass

        try:
            self.iconbitmap(icon_path)
        except Exception:
            pass

    def load_config(self):
        default_config = {"target_path": "", "hide_disclaimer": False, "sort_direction": "Descending"}
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, "r") as f:
                    raw = f.read().strip()
                if not raw:
                    return default_config
                try:
                    loaded = json.loads(raw)
                    if isinstance(loaded, dict):
                        return {**default_config, **loaded}
                except json.JSONDecodeError:
                    # Backward compatibility: old config only stored the folder path.
                    if os.path.exists(raw):
                        default_config["target_path"] = raw
                        return default_config
            except Exception:
                return default_config
        return default_config

    def save_config(self, **updates):
        try:
            self.config.update(updates)
            with open(self.config_file, "w") as f:
                json.dump(self.config, f, indent=2)
        except Exception:
            pass

    def get_documents_roots(self):
        roots = []
        home = os.path.expanduser("~")
        env_candidates = [
            os.environ.get("USERPROFILE"),
            os.environ.get("HOMEDRIVE") and os.environ.get("HOMEPATH") and os.path.join(os.environ["HOMEDRIVE"], os.environ["HOMEPATH"].lstrip("\\/")),
            home
        ]
        env_candidates = [path for path in env_candidates if path]

        for base in env_candidates:
            roots.extend([
                os.path.join(base, "Documents"),
                os.path.join(base, "OneDrive", "Documents")
            ])

        for env_name in ("PUBLIC",):
            base = os.environ.get(env_name)
            if base:
                roots.append(os.path.join(base, "Documents"))

        for drive in ("D:\\", "E:\\", "F:\\", "G:\\"):
            if not os.path.isdir(drive):
                continue
            roots.append(os.path.join(drive, "Documents"))
            try:
                with os.scandir(drive) as drive_entries:
                    for entry in drive_entries:
                        if entry.is_dir():
                            nested_docs = os.path.join(entry.path, "Documents")
                            if os.path.isdir(nested_docs):
                                roots.append(nested_docs)
            except OSError:
                continue

        deduped = []
        seen = set()
        for path in roots:
            normalized = os.path.normcase(os.path.normpath(path))
            if normalized in seen:
                continue
            seen.add(normalized)
            deduped.append(path)
        return deduped

    def find_gta_user_music_path(self):
        saved_path = self.config.get("target_path", "")
        if saved_path and os.path.exists(saved_path):
            return saved_path

        suffixes = [
            os.path.join("Rockstar Games", "GTA V", "User Music"),
            os.path.join("Rockstar Games", "GTAV", "User Music"),
            os.path.join("Rockstar Games", "GTAV Enhanced", "User Music"),
            os.path.join("Rockstar Games", "GTA V Enhanced", "User Music")
        ]

        for root in self.get_documents_roots():
            for suffix in suffixes:
                candidate = os.path.join(root, suffix)
                if os.path.exists(candidate):
                    return candidate

        candidate_roots = []
        for root in self.get_documents_roots():
            if os.path.exists(root):
                candidate_roots.append(root)
        for drive in ("D:\\", "E:\\", "F:\\", "G:\\"):
            docs_candidate = os.path.join(drive, "Documents")
            if os.path.exists(docs_candidate):
                candidate_roots.append(docs_candidate)

        for root in candidate_roots:
            for rockstar_dir in ("Rockstar Games", "RockstarGames"):
                rockstar_path = os.path.join(root, rockstar_dir)
                if not os.path.isdir(rockstar_path):
                    continue
                for current_root, dirnames, _filenames in os.walk(rockstar_path):
                    dirnames[:] = [name for name in dirnames if len(name) < 80]
                    if os.path.basename(current_root).lower() == "user music":
                        return current_root

        return ""

    def maybe_show_disclaimer(self):
        if self.config.get("hide_disclaimer"):
            return
        dialog = ctk.CTkToplevel(self)
        dialog.title("Disclaimer")
        dialog.geometry("460x230")
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()

        frame = ctk.CTkFrame(dialog, fg_color=CARD_COLOR, corner_radius=14)
        frame.pack(fill="both", expand=True, padx=16, pady=16)

        label = ctk.CTkLabel(
            frame,
            text=(
                "This app is heavily vibecoded and reviewed only to the extent of the developer's knowledge.\n\n"
                "There is no warranty. Use at your own risk."
            ),
            justify="left",
            anchor="w",
            wraplength=400,
            font=("Segoe UI", 13)
        )
        label.pack(fill="x", padx=16, pady=(18, 14))

        button_row = ctk.CTkFrame(frame, fg_color="transparent")
        button_row.pack(fill="x", padx=16, pady=(0, 16))

        def close_dialog(hide_forever):
            if hide_forever:
                self.save_config(hide_disclaimer=True)
            dialog.destroy()

        ok_btn = ctk.CTkButton(button_row, text="OK", fg_color="#303030", hover_color="#404040", command=lambda: close_dialog(False))
        ok_btn.pack(side="left")
        dont_show_btn = ctk.CTkButton(button_row, text="Don't Show Again", fg_color=ACCENT_COLOR, hover_color="#D32F2F", command=lambda: close_dialog(True))
        dont_show_btn.pack(side="right")

        dialog.protocol("WM_DELETE_WINDOW", lambda: close_dialog(False))
        self.wait_window(dialog)

    def check_ffmpeg(self):
        # Check if ffmpeg is in the app folder for friends' portability
        ffmpeg_exists = any(
            os.path.exists(os.path.join(base_dir, "ffmpeg.exe"))
            for base_dir in {self.app_dir, self.engine_dir, self.bundle_dir}
        )
        if not ffmpeg_exists:
            # Check system path as fallback
            try:
                import subprocess
                subprocess.run(['ffmpeg', '-version'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except:
                self.status_label.configure(text="● WARNING: ffmpeg.exe MISSING IN FOLDER", text_color="#FFCC00")

    def setup_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(4, weight=1)

        # --- HEADER ---
        self.header_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.header_frame.grid(row=0, column=0, padx=30, pady=(30, 10), sticky="w")
        
        self.header_label = ctk.CTkLabel(self.header_frame, text="GTAV", font=("Impact", 42), text_color=ACCENT_COLOR)
        self.header_label.pack(side="left")
        self.sub_header = ctk.CTkLabel(self.header_frame, text=" USER MUSIC MANAGER", font=("Segoe UI Semibold", 18), text_color="white")
        self.sub_header.pack(side="left", padx=10, pady=(15, 0))

        # --- PATH CONFIG ---
        self.path_frame = ctk.CTkFrame(self, fg_color=CARD_COLOR, corner_radius=15, height=60)
        self.path_frame.grid(row=1, column=0, padx=30, pady=10, sticky="ew")
        self.path_frame.grid_columnconfigure(0, weight=1)

        self.path_entry = ctk.CTkEntry(
            self.path_frame, 
            height=45, 
            fg_color="#000000", 
            border_color="#333", 
            font=("Segoe UI", 12)
        )
        self.path_entry.grid(row=0, column=0, padx=15, pady=10, sticky="ew")
        self.register_entry_placeholder(self.path_entry, self.default_path_placeholder)
        if self.current_target_path != self.default_gta_path:
            self.set_entry_text(self.path_entry, self.current_target_path)

        self.browse_btn = ctk.CTkButton(
            self.path_frame, text="CHANGE FOLDER", fg_color="#222", hover_color=ACCENT_COLOR, 
            width=140, height=45, font=("Segoe UI Bold", 12), command=self.browse_path
        )
        self.browse_btn.grid(row=0, column=1, padx=(0, 15), pady=10)

        # --- DOWNLOAD ENGINE ---
        self.dl_card = ctk.CTkFrame(self, fg_color=CARD_COLOR, corner_radius=15)
        self.dl_card.grid(row=2, column=0, padx=30, pady=10, sticky="ew")
        self.dl_card.grid_columnconfigure(1, weight=1)

        self.info_btn = ctk.CTkButton(
            self.dl_card,
            text="i",
            width=36,
            height=36,
            corner_radius=18,
            fg_color="#202020",
            hover_color=ACCENT_COLOR,
            font=("Segoe UI Bold", 16)
        )
        self.info_btn.grid(row=0, column=0, padx=(20, 10), pady=20)
        self.info_btn.bind("<Enter>", self.show_download_tooltip)
        self.info_btn.bind("<Leave>", self.schedule_tooltip_hide)

        self.url_input = ctk.CTkEntry(
            self.dl_card,
            height=50, fg_color="#000", border_color=ACCENT_COLOR, font=("Segoe UI", 14)
        )
        self.url_input.grid(row=0, column=1, padx=(0, 20), pady=20, sticky="ew")
        self.register_entry_placeholder(self.url_input, "Search Songs, Paste URL's, Check \"i button\" for more info")

        self.sync_btn = ctk.CTkButton(
            self.dl_card, text="SYNC LIBRARY", fg_color=ACCENT_COLOR, hover_color="#D32F2F", 
            height=50, width=180, font=("Segoe UI Black", 14), command=self.start_download_thread
        )
        self.sync_btn.grid(row=0, column=2, padx=(0, 20), pady=20)

        # --- STATUS & SEARCH ---
        self.info_row = ctk.CTkFrame(self, fg_color="transparent")
        self.info_row.grid(row=3, column=0, padx=35, pady=(10, 0), sticky="ew")
        self.info_row.grid_columnconfigure(0, weight=1)

        self.status_label = ctk.CTkLabel(self.info_row, text="● SYSTEM READY", font=("Segoe UI Bold", 11), text_color="#00FF41")
        self.status_label.grid(row=0, column=0, sticky="w")

        self.controls_row = ctk.CTkFrame(self.info_row, fg_color="transparent")
        self.controls_row.grid(row=0, column=1, sticky="e")

        self.sort_menu = ctk.CTkOptionMenu(
            self.controls_row,
            values=["Date Added", "Alphabetical", "Length"],
            variable=self.sort_mode,
            width=145,
            height=30,
            fg_color="#242424",
            button_color="#303030",
            button_hover_color=ACCENT_COLOR,
            dropdown_fg_color="#181818",
            dropdown_hover_color="#2C2C2C",
            command=lambda _choice: self.schedule_refresh(0)
        )
        self.sort_menu.pack(side="left", padx=(0, 10))

        self.sort_direction_menu = ctk.CTkOptionMenu(
            self.controls_row,
            values=["Descending", "Ascending"],
            variable=self.sort_direction,
            width=120,
            height=30,
            fg_color="#242424",
            button_color="#303030",
            button_hover_color=ACCENT_COLOR,
            dropdown_fg_color="#181818",
            dropdown_hover_color="#2C2C2C",
            command=self.on_sort_direction_change
        )
        self.sort_direction_menu.pack(side="left", padx=(0, 10))

        self.search_bar = ctk.CTkEntry(self.controls_row, width=220, height=30, fg_color="#1a1a1a", border_width=1)
        self.search_bar.pack(side="left")
        self.register_entry_placeholder(self.search_bar, "Filter library...")
        self.search_bar.bind("<KeyRelease>", self.on_library_search_keyrelease, add="+")

        # --- LIBRARY ---
        self.scroll_container = ctk.CTkScrollableFrame(self, fg_color="transparent", label_text="STORED TRACKS", label_font=("Segoe UI Bold", 12))
        self.scroll_container.grid(row=4, column=0, padx=30, pady=(10, 30), sticky="nsew")

    def register_entry_placeholder(self, entry, placeholder_text):
        self.placeholder_state[entry] = {"text": placeholder_text, "active": False}
        entry.bind("<FocusOut>", lambda _event, e=entry: self.restore_placeholder_if_needed(e), add="+")
        entry.bind("<KeyPress>", lambda event, e=entry: self.handle_placeholder_keypress(e, event), add="+")
        entry.bind("<<Paste>>", lambda _event, e=entry: self.prepare_entry_for_input(e), add="+")
        self.restore_placeholder_if_needed(entry)

    def restore_placeholder_if_needed(self, entry):
        state = self.placeholder_state[entry]
        current_text = entry.get()
        if state["active"] and current_text == state["text"]:
            entry.configure(text_color="#7A7A7A")
            return
        if current_text:
            state["active"] = False
            entry.configure(text_color="white")
            return
        entry.delete(0, "end")
        entry.insert(0, state["text"])
        entry.configure(text_color="#7A7A7A")
        state["active"] = True

    def handle_placeholder_keypress(self, entry, event):
        state = self.placeholder_state.get(entry)
        if not state or not state["active"]:
            return None

        if event.keysym in {"Left", "Right", "Up", "Down", "Home", "End", "Tab", "Shift_L", "Shift_R", "Control_L", "Control_R"}:
            return None

        if event.keysym in {"BackSpace", "Delete"}:
            self.prepare_entry_for_input(entry)
            return "break"

        if event.char and event.char.isprintable():
            self.prepare_entry_for_input(entry)
            return None

        return "break" if self.placeholder_state[entry]["active"] else None

    def prepare_entry_for_input(self, entry):
        if entry in self.placeholder_state and self.placeholder_state[entry]["active"]:
            entry.delete(0, "end")
            self.placeholder_state[entry]["active"] = False
            entry.configure(text_color="white")

    def get_entry_text(self, entry):
        state = self.placeholder_state.get(entry)
        if state and state["active"]:
            return ""
        return entry.get().strip()

    def set_entry_text(self, entry, value):
        entry.delete(0, "end")
        entry.insert(0, value)
        if entry in self.placeholder_state:
            self.placeholder_state[entry]["active"] = False
        entry.configure(text_color="white")

    def show_download_tooltip(self, _event=None):
        if self.tooltip_hide_job:
            self.after_cancel(self.tooltip_hide_job)
            self.tooltip_hide_job = None
        if self.tooltip_window is not None:
            return

        self.tooltip_window = ctk.CTkToplevel(self)
        self.tooltip_window.overrideredirect(True)
        self.tooltip_window.attributes("-topmost", True)
        x = self.info_btn.winfo_rootx() + 18
        y = self.info_btn.winfo_rooty() + self.info_btn.winfo_height() + 10
        self.tooltip_window.geometry(f"+{x}+{y}")
        tooltip_frame = ctk.CTkFrame(self.tooltip_window, fg_color="#141414", border_width=1, border_color="#3A3A3A", corner_radius=10)
        tooltip_frame.pack(fill="both", expand=True)
        tooltip_label = ctk.CTkLabel(
            tooltip_frame,
            text=TOOLTIP_TEXT,
            justify="left",
            anchor="w",
            padx=14,
            pady=12,
            font=("Segoe UI", 12),
            text_color="#E5E5E5"
        )
        tooltip_label.pack(fill="both", expand=True)
        for widget in (self.tooltip_window, tooltip_frame, tooltip_label):
            widget.bind("<Enter>", self.cancel_tooltip_hide, add="+")
            widget.bind("<Leave>", self.schedule_tooltip_hide, add="+")

    def cancel_tooltip_hide(self, _event=None):
        if self.tooltip_hide_job:
            self.after_cancel(self.tooltip_hide_job)
            self.tooltip_hide_job = None

    def schedule_tooltip_hide(self, _event=None):
        self.cancel_tooltip_hide()
        self.tooltip_hide_job = self.after(120, self.hide_download_tooltip)

    def hide_download_tooltip(self, _event=None):
        self.tooltip_hide_job = None
        if self.tooltip_window is not None:
            self.tooltip_window.destroy()
            self.tooltip_window = None

    def on_sort_direction_change(self, choice):
        self.save_config(sort_direction=choice)
        self.schedule_refresh(0)

    def on_library_search_keyrelease(self, _event=None):
        if self.pending_search_job:
            self.after_cancel(self.pending_search_job)
        term = self.get_entry_text(self.search_bar)
        delay = 0 if not term else SEARCH_DELAY_MS
        self.pending_search_job = self.after(delay, self.apply_library_search)

    def apply_library_search(self):
        self.pending_search_job = None
        self.schedule_refresh(0)

    def schedule_refresh(self, delay=0):
        if self.pending_refresh_job:
            self.after_cancel(self.pending_refresh_job)
        self.pending_refresh_job = self.after(delay, self.refresh_file_list)

    def get_active_path(self):
        val = self.get_entry_text(self.path_entry)
        return val if val else self.default_gta_path

    def browse_path(self):
        path = filedialog.askdirectory()
        if path:
            self.set_entry_text(self.path_entry, path)
            self.save_config(target_path=path)
            self.refresh_file_list()

    def refresh_file_list(self):
        self.pending_refresh_job = None
        for widget in self.scroll_container.winfo_children():
            widget.destroy()
        self.active_widgets = {}
        self.library_index = {}
        path = self.get_active_path()
        if not os.path.exists(path):
            return

        files = self.get_library_files(path)
        term = self.normalize_for_compare(self.get_entry_text(self.search_bar))
        if len(term) >= MIN_SEARCH_LENGTH:
            files = [song for song in files if self.library_matches_search(song["name"], term)]

        sort_mode = self.sort_mode.get()
        reverse_sort = self.sort_direction.get() == "Descending"
        if sort_mode == "Alphabetical":
            files.sort(key=lambda song: self.normalize_for_compare(song["name"]), reverse=reverse_sort)
        elif sort_mode == "Length":
            files.sort(key=lambda song: (self.get_song_duration(song["path"]), self.normalize_for_compare(song["name"])), reverse=reverse_sort)
        else:
            files.sort(key=lambda song: (song["added_at"], self.normalize_for_compare(song["name"])), reverse=reverse_sort)

        for song in files:
            self.library_index[song["name"]] = song["path"]
            self.create_song_item(song["name"])

    def get_library_files(self, path):
        files = []
        try:
            with os.scandir(path) as entries:
                for entry in entries:
                    if not entry.is_file() or not entry.name.lower().endswith(".mp3"):
                        continue
                    stat = entry.stat()
                    cache = self.library_cache.get(entry.path)
                    if not cache or cache.get("mtime") != stat.st_mtime:
                        cache = {
                            "mtime": stat.st_mtime,
                            "duration": cache.get("duration") if cache else None
                        }
                        self.library_cache[entry.path] = cache
                    files.append({
                        "name": entry.name,
                        "path": entry.path,
                        "added_at": getattr(stat, "st_ctime", stat.st_mtime)
                    })
        except OSError:
            return []
        return files

    def get_song_duration(self, file_path):
        cache = self.library_cache.setdefault(file_path, {"mtime": None, "duration": None})
        if cache.get("duration") is None:
            try:
                cache["duration"] = MP3(file_path).info.length
            except Exception:
                cache["duration"] = 0
        return cache["duration"]

    def get_song_path(self, filename):
        return self.library_index.get(filename)

    def library_matches_search(self, filename, normalized_term):
        haystack = self.normalize_for_compare(os.path.splitext(filename)[0])
        term_tokens = [token for token in normalized_term.split() if token]
        haystack_tokens = [token for token in haystack.split() if token]
        if not term_tokens:
            return True
        if normalized_term in haystack:
            return True
        if all(token in haystack for token in term_tokens):
            return True
        if self.fuzzy_text_match(normalized_term, haystack):
            return True
        return all(self.fuzzy_token_match(token, haystack_tokens) for token in term_tokens)

    def fuzzy_text_match(self, term, candidate):
        if not term or not candidate:
            return False
        ratio = difflib.SequenceMatcher(None, term, candidate).ratio()
        return ratio >= 0.74

    def fuzzy_token_match(self, query_token, candidate_tokens):
        for candidate in candidate_tokens:
            if query_token == candidate:
                return True
            if abs(len(query_token) - len(candidate)) > 3:
                continue
            ratio = difflib.SequenceMatcher(None, query_token, candidate).ratio()
            if ratio >= 0.72:
                return True
        return False

    def create_song_item(self, fname):
        item = ctk.CTkFrame(self.scroll_container, fg_color="#121212", corner_radius=10)
        item.pack(fill="x", pady=4, padx=5)
        top_row = ctk.CTkFrame(item, fg_color="transparent")
        top_row.pack(fill="x", padx=15, pady=10)
        play_btn = ctk.CTkButton(top_row, text=PLAY_SYMBOL, width=35, height=35, fg_color="#222", hover_color=ACCENT_COLOR, command=lambda: self.toggle_song(fname))
        play_btn.pack(side="left")
        name_lbl = ctk.CTkLabel(top_row, text=fname, font=("Segoe UI", 13), anchor="w")
        name_lbl.pack(side="left", padx=15, fill="x", expand=True)
        del_btn = ctk.CTkButton(
            top_row,
            text="✕",
            width=32,
            height=32,
            corner_radius=8,
            fg_color=DELETE_BTN_COLOR,
            text_color="#BEBEBE",
            hover_color=DELETE_BTN_HOVER,
            border_width=1,
            border_color="#3F3F3F",
            font=("Segoe UI Bold", 12),
            command=lambda: self.delete_file(fname)
        )
        del_btn.pack(side="right")
        player_row = ctk.CTkFrame(item, fg_color="#0a0a0a", height=0)
        self.active_widgets[fname] = {"frame": player_row, "play_btn": play_btn, "slider": None, "time_lbl": None, "vol_slider": None, "is_loaded": False}

        if fname == self.playing_filename:
            self.restore_song_row(fname)

    def ensure_song_controls(self, filename):
        ui = self.active_widgets[filename]
        if ui["is_loaded"]:
            return ui

        ui["frame"].pack(fill="x")
        inner = ctk.CTkFrame(ui["frame"], fg_color="transparent")
        inner.pack(fill="x", padx=15, pady=10)
        ui["slider"] = ctk.CTkSlider(inner, from_=0, to=max(self.song_duration, 1), height=15, button_color=ACCENT_COLOR, progress_color=ACCENT_COLOR)
        ui["slider"].pack(side="left", fill="x", expand=True, padx=(0, 10))
        ui["slider"].set(0)
        ui["slider"].bind("<ButtonPress-1>", lambda _event: setattr(self, 'is_seeking', True))
        ui["slider"].bind("<ButtonRelease-1>", lambda _event: self.seek_song(ui["slider"].get()))
        ui["time_lbl"] = ctk.CTkLabel(inner, text="0:00 / 0:00", font=("Consolas", 11), text_color="gray", width=80)
        ui["time_lbl"].pack(side="left", padx=(0, 10))
        vol_lbl = ctk.CTkLabel(inner, text="Vol", font=("Segoe UI Bold", 10), text_color="#555")
        vol_lbl.pack(side="left", padx=(5, 5))
        ui["vol_slider"] = ctk.CTkSlider(inner, from_=0, to=1, height=15, width=80, button_color=ACCENT_COLOR, progress_color=ACCENT_COLOR, command=self.set_volume)
        ui["vol_slider"].pack(side="left")
        ui["vol_slider"].set(self.current_volume)
        ui["is_loaded"] = True
        return ui

    def restore_song_row(self, filename):
        ui = self.active_widgets.get(filename)
        if not ui:
            return

        ui = self.ensure_song_controls(filename)
        ui["frame"].pack(fill="x")
        ui["slider"].configure(to=max(self.song_duration, 1))
        ui["vol_slider"].set(self.current_volume)
        current_pos = self.get_current_song_position()
        ui["slider"].set(current_pos)
        curr_str = time.strftime('%M:%S', time.gmtime(max(0, current_pos)))
        total_str = time.strftime('%M:%S', time.gmtime(max(self.song_duration, current_pos)))
        ui["time_lbl"].configure(text=f"{curr_str} / {total_str}")
        ui["play_btn"].configure(
            text=PLAY_SYMBOL if self.is_paused else PAUSE_SYMBOL,
            fg_color="#444" if self.is_paused else ACCENT_COLOR
        )

    def toggle_song(self, filename):
        if self.playing_filename == filename:
            if self.is_paused:
                pygame.mixer.music.unpause()
                self.is_paused = False
                self.active_widgets[filename]["play_btn"].configure(text=PAUSE_SYMBOL, fg_color=ACCENT_COLOR)
            else:
                pygame.mixer.music.pause()
                self.is_paused = True
                self.active_widgets[filename]["play_btn"].configure(text=PLAY_SYMBOL, fg_color="#444")
        else:
            self.play_new_song(filename)

    def play_new_song(self, filename):
        if self.playing_filename and self.playing_filename in self.active_widgets:
            prev = self.active_widgets[self.playing_filename]
            prev["frame"].pack_forget()
            prev["play_btn"].configure(text=PLAY_SYMBOL, fg_color="#222")
        full_path = self.get_song_path(filename)
        if not full_path or not os.path.isfile(full_path):
            messagebox.showerror("Error", f"Track file could not be found:\n{filename}")
            return
        try:
            self.song_duration = self.get_song_duration(full_path)
            pygame.mixer.music.load(full_path)
            pygame.mixer.music.set_volume(self.current_volume)
            pygame.mixer.music.play()
            self.playing_filename = filename
            self.is_paused = False
            self.seek_offset = 0
            self.restore_song_row(filename)
        except Exception as e:
            messagebox.showerror("Error", f"Playback Failed: {e}")

    def set_volume(self, val):
        self.current_volume = float(val)
        pygame.mixer.music.set_volume(self.current_volume)

    def seek_song(self, val):
        if self.playing_filename:
            pygame.mixer.music.play(start=val)
            self.seek_offset = val
            self.is_seeking = False
            if self.is_paused:
                self.is_paused = False
                self.active_widgets[self.playing_filename]["play_btn"].configure(text=PAUSE_SYMBOL, fg_color=ACCENT_COLOR)

    def get_current_song_position(self):
        if not self.playing_filename:
            return 0
        mixer_pos = pygame.mixer.music.get_pos()
        if mixer_pos < 0:
            return self.seek_offset
        return max(0, (mixer_pos / 1000.0) + self.seek_offset)

    def update_playback_loop(self):
        if self.playing_filename and not self.is_paused and not self.is_seeking:
            current_pos = self.get_current_song_position()
            ui = self.active_widgets.get(self.playing_filename)
            if ui and ui["slider"]:
                ui["slider"].set(current_pos)
                curr_str = time.strftime('%M:%S', time.gmtime(max(0, current_pos)))
                total_str = time.strftime('%M:%S', time.gmtime(self.song_duration))
                ui["time_lbl"].configure(text=f"{curr_str} / {total_str}")
        self.after(200, self.update_playback_loop)

    def delete_file(self, filename):
        if messagebox.askyesno("Confirm", f"Delete {filename}?"):
            file_path = self.get_song_path(filename)
            if not file_path or not os.path.isfile(file_path):
                messagebox.showerror("Error", f"Track file could not be found:\n{filename}")
                self.refresh_file_list()
                return
            if self.playing_filename == filename:
                pygame.mixer.music.stop()
                try:
                    pygame.mixer.music.unload()
                except pygame.error:
                    pass
                self.playing_filename = None
                self.song_duration = 0
                self.seek_offset = 0
            try: 
                os.remove(file_path)
                self.library_cache.pop(file_path, None)
                self.library_index.pop(filename, None)
                self.refresh_file_list()
            except Exception as e: 
                messagebox.showerror("Error", f"File in use or blocked.\n{e}")

    def normalize_spacing(self, text):
        return re.sub(r'\s+', ' ', (text or '')).strip()

    def normalize_for_compare(self, text):
        text = (text or '').lower().replace('&', ' and ')
        text = re.sub(r'[^a-z0-9]+', ' ', text)
        return self.normalize_spacing(text)

    def tokenize(self, text):
        return [token for token in self.normalize_for_compare(text).split() if token]

    def remove_noise_fragments(self, text):
        noise_patterns = [
            r'\(.*?(official|lyrics?|audio|video|visualizer|hd|4k|hq|explicit|clean|remaster(?:ed)?|version|edit|shorts?).*?\)',
            r'\[.*?(official|lyrics?|audio|video|visualizer|hd|4k|hq|explicit|clean|remaster(?:ed)?|version|edit|shorts?).*?\]',
            r'\bofficial\s+(music\s+)?video\b',
            r'\bofficial\s+(music\s+)?audio\b',
            r'\bofficial\b',
            r'\blyric\s+video\b',
            r'\blyrics?\b',
            r'\baudio\s+only\b',
            r'\baudio\b',
            r'\bvisuali[sz]er\b',
            r'\btopic\b',
            r'\bfull\s+song\b',
            r'\bhigh\s+quality\b',
            r'\bhq\b',
            r'\bhd\b',
            r'\b4k\b',
            r'\b1080p\b',
            r'\b720p\b',
            r'\bexplicit\b',
            r'\bclean\b',
            r'\bversion\b',
            r'\bremaster(?:ed)?\b',
            r'\bvevo\b',
            r'\bshorts?\b'
        ]
        cleaned = text or ''
        for pattern in noise_patterns:
            cleaned = re.sub(pattern, ' ', cleaned, flags=re.IGNORECASE)
        cleaned = cleaned.replace('|', ' ')
        return self.normalize_spacing(cleaned)

    def cleanup_person_name(self, text):
        text = self.remove_noise_fragments(text)
        text = re.sub(r'\b(?:official|topic)\b', ' ', text, flags=re.IGNORECASE)
        text = re.sub(r'\b(?:vevo|records?|music|channel)\b$', ' ', text, flags=re.IGNORECASE)
        return self.normalize_spacing(text.strip(" -_,:;"))

    def cleanup_song_title(self, text):
        text = self.remove_noise_fragments(text)
        text = re.sub(r'\b(?:feat|ft)\.?\b.*$', ' ', text, flags=re.IGNORECASE)
        text = re.sub(r'\b(?:prod|produced)\s+by\b.*$', ' ', text, flags=re.IGNORECASE)
        text = re.sub(r'^[\-\|,:;/]+|[\-\|,:;/]+$', ' ', text)
        return self.normalize_spacing(text.strip(" -_,:;"))

    def smart_title_case(self, text):
        small_words = {"a", "an", "and", "as", "at", "by", "for", "in", "of", "on", "or", "the", "to", "vs", "x"}
        words = []
        for raw_word in self.normalize_spacing(text).split():
            lower = raw_word.lower()
            if re.search(r'[A-Z].*[A-Z]', raw_word) or (raw_word.isupper() and len(raw_word) <= 4):
                words.append(raw_word)
            elif "'" in raw_word:
                words.append("'".join(part.capitalize() if part else part for part in lower.split("'")))
            elif "-" in raw_word:
                words.append("-".join(part.capitalize() if part else part for part in lower.split("-")))
            elif lower in small_words and words:
                words.append(lower)
            else:
                words.append(lower.capitalize())
        return " ".join(words)

    def looks_like_reasonable_artist(self, text):
        tokens = self.tokenize(text)
        if not tokens or len(tokens) > 6:
            return False
        banned = {"official", "video", "audio", "lyrics", "music", "song"}
        return not any(token in banned for token in tokens)

    def looks_like_reasonable_song(self, text):
        tokens = self.tokenize(text)
        if not tokens or len(tokens) > 10:
            return False
        banned = {"official", "video", "audio", "lyrics"}
        return not all(token in banned for token in tokens)

    def similarity_score(self, a, b):
        a_tokens = set(self.tokenize(a))
        b_tokens = set(self.tokenize(b))
        if not a_tokens or not b_tokens:
            return 0
        return int((len(a_tokens & b_tokens) / len(a_tokens | b_tokens)) * 100)

    def extract_artist_title_pair(self, title, artist_hint):
        cleaned_title = self.cleanup_song_title(title)
        cleaned_hint = self.cleanup_person_name(artist_hint)
        if not cleaned_title:
            return None, None

        separators = [' - ', ' – ', ' — ', ' | ', ' : ', ': ', ' / ', ', ']
        best_pair = (None, None)
        best_score = -1

        for separator in separators:
            if separator not in cleaned_title:
                continue
            left, right = [part.strip() for part in cleaned_title.split(separator, 1)]
            for artist_part, song_part in ((left, right), (right, left)):
                if not self.looks_like_reasonable_artist(artist_part) or not self.looks_like_reasonable_song(song_part):
                    continue
                score = self.similarity_score(artist_part, cleaned_hint)
                if separator == ' - ':
                    score += 12
                elif separator == ', ':
                    score += 8
                if score > best_score:
                    best_pair = (artist_part, song_part)
                    best_score = score

        if best_pair[0] and best_score >= 15:
            return best_pair

        title_tokens = self.tokenize(cleaned_title)
        hint_tokens = self.tokenize(cleaned_hint)
        original_words = cleaned_title.split()
        if hint_tokens and len(title_tokens) > len(hint_tokens):
            if title_tokens[:len(hint_tokens)] == hint_tokens:
                song_part = " ".join(original_words[len(hint_tokens):])
                if self.looks_like_reasonable_song(song_part):
                    return cleaned_hint, song_part
            if title_tokens[-len(hint_tokens):] == hint_tokens:
                song_part = " ".join(original_words[:-len(hint_tokens)])
                if self.looks_like_reasonable_song(song_part):
                    return cleaned_hint, song_part

        return None, None

    def clean_smart_title(self, entry, query=''):
        artist_meta = entry.get('artist') or entry.get('album_artist') or entry.get('creator') or ''
        track_meta = entry.get('track') or ''
        uploader = entry.get('uploader') or entry.get('channel') or ''
        title = entry.get('title') or query or 'Unknown Track'

        artist = self.cleanup_person_name(artist_meta or uploader)
        song = self.cleanup_song_title(track_meta)

        if not song:
            parsed_artist, parsed_song = self.extract_artist_title_pair(title, artist)
            if parsed_artist and parsed_song:
                artist = parsed_artist
                song = parsed_song

        if not song:
            song = self.cleanup_song_title(title)

        if not artist:
            artist = "Unknown Artist"
        if not song:
            song = self.cleanup_song_title(query) or "Unknown Song"

        artist = self.smart_title_case(artist)
        song = self.smart_title_case(song)
        return f"{artist} - {song}"

    def score_search_result(self, query, entry):
        title = entry.get('title') or ''
        uploader = entry.get('uploader') or entry.get('channel') or ''
        description = entry.get('description') or ''
        duration = entry.get('duration') or 0
        categories = ' '.join(entry.get('categories') or [])

        haystack = ' '.join([title, uploader, description, categories])
        haystack_norm = self.normalize_for_compare(haystack)
        query_norm = self.normalize_for_compare(query)
        query_tokens = [token for token in query_norm.split() if token not in {'song', 'music', 'official', 'audio', 'video'}]
        matched_tokens = sum(1 for token in query_tokens if token in haystack_norm)

        score = 0
        if query_norm and query_norm in haystack_norm:
            score += 70
        score += matched_tokens * 18
        if query_tokens:
            score += int((matched_tokens / len(query_tokens)) * 35)

        positive_terms = [
            'official audio', 'official video', 'music video', 'lyrics', 'topic',
            'artist', 'song', 'audio', 'vevo'
        ]
        negative_terms = [
            'reaction', 'trailer', 'teaser', 'interview', 'tutorial', 'how to',
            'shorts', 'meme', 'scene', 'status', 'edit', 'live', 'concert',
            'cover', 'karaoke', 'instrumental', 'nightcore', 'slowed', 'reverb',
            'remix', 'podcast', 'episode', 'full movie'
        ]

        title_norm = self.normalize_for_compare(title)
        uploader_norm = self.normalize_for_compare(uploader)
        desc_norm = self.normalize_for_compare(description)

        for term in positive_terms:
            if term in title_norm or term in uploader_norm:
                score += 10
        for term in negative_terms:
            if term in title_norm or term in desc_norm:
                score -= 20

        if duration:
            if 110 <= duration <= 420:
                score += 18
            elif 80 <= duration <= 540:
                score += 8
            else:
                score -= 12

        if entry.get('artist') or entry.get('track'):
            score += 25
        if 'music' in categories.lower():
            score += 20
        if 'topic' in uploader_norm or 'vevo' in uploader_norm:
            score += 15

        return score

    def pick_best_search_entry(self, query, entries):
        ranked = sorted(entries or [], key=lambda entry: self.score_search_result(query, entry), reverse=True)
        return ranked[0] if ranked else None

    def is_url(self, text):
        lowered = (text or "").lower()
        return lowered.startswith("http://") or lowered.startswith("https://")

    def is_playlist_url(self, text):
        return "list=" in (text or "").lower()

    def sanitize_filename_component(self, text):
        cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1F]', ' ', text or '')
        cleaned = self.normalize_spacing(cleaned).strip(" .")
        return cleaned or "Unknown"

    def build_safe_output_name(self, entry, query=""):
        clean_title = self.clean_smart_title(entry, query)
        parts = [self.sanitize_filename_component(part) for part in clean_title.split(" - ", 1)]
        if len(parts) == 2:
            return f"{parts[0]} - {parts[1]}.mp3"
        return f"{self.sanitize_filename_component(clean_title)}.mp3"

    def make_unique_output_path(self, final_path):
        if not os.path.exists(final_path):
            return final_path
        stem, ext = os.path.splitext(final_path)
        counter = 2
        while True:
            candidate = f"{stem} ({counter}){ext}"
            if not os.path.exists(candidate):
                return candidate
            counter += 1

    def rename_downloaded_entry(self, path, ydl, entry, query=""):
        orig_mp3 = os.path.splitext(ydl.prepare_filename(entry))[0] + ".mp3"
        clean_name = self.build_safe_output_name(entry, query)
        final_path = os.path.join(path, clean_name)
        if os.path.exists(orig_mp3) and os.path.abspath(orig_mp3) != os.path.abspath(final_path):
            final_path = self.make_unique_output_path(final_path)
            os.rename(orig_mp3, final_path)

    def start_download_thread(self):
        txt = self.get_entry_text(self.url_input)
        if not txt:
            return
        self.save_config(target_path=self.get_active_path()) # Save path on sync
        queries = txt.split(',')
        self.sync_btn.configure(state="disabled", text="SYNCING...")
        threading.Thread(target=self.run_download_logic, args=(queries,), daemon=True).start()

    def dl_hook(self, d):
        if d['status'] == 'downloading':
            p = d.get('_percent_str', '0%')
            s = d.get('_speed_str', 'N/A')
            self.after(0, lambda: self.status_label.configure(text=f"● DOWNLOADING: {p} ({s})", text_color=ACCENT_COLOR))

    def run_download_logic(self, queries):
        path = self.get_active_path()
        # Look for ffmpeg in app folder
        local_ffmpeg = next(
            (
                os.path.join(base_dir, "ffmpeg.exe")
                for base_dir in (self.app_dir, self.engine_dir, self.bundle_dir)
                if os.path.exists(os.path.join(base_dir, "ffmpeg.exe"))
            ),
            None
        )
        
        opts = {
            'format': 'bestaudio/best',
            'postprocessors': [{'key': 'FFmpegExtractAudio','preferredcodec': 'mp3','preferredquality': '192'}],
            'outtmpl': os.path.join(path, '%(title)s.%(ext)s'),
            'progress_hooks': [self.dl_hook],
            'match_filter': yt_dlp.utils.match_filter_func("!is_live & duration < 660"),
            'ffmpeg_location': local_ffmpeg,
            'quiet': True, 'no_warnings': True
        }

        for q in queries:
            q = q.strip()
            if not q: continue
            self.after(0, lambda q=q: self.status_label.configure(text=f"● SEARCHING: {q}", text_color="#3399ff"))
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    if self.is_url(q):
                        info = ydl.extract_info(q, download=True)
                        if self.is_playlist_url(q):
                            entries = [entry for entry in (info.get('entries') or []) if entry]
                            if not entries:
                                raise ValueError(f"No downloadable tracks found in playlist '{q}'.")
                            for playlist_entry in entries:
                                self.rename_downloaded_entry(path, ydl, playlist_entry, playlist_entry.get('title', ''))
                            continue
                        entry = info.get('entries', [info])[0]
                    else:
                        search_info = ydl.extract_info(f"ytsearch8:{q}", download=False)
                        entry = self.pick_best_search_entry(q, search_info.get('entries', []))
                        if not entry:
                            raise ValueError(f"No strong song match found for '{q}'.")
                        target_url = entry.get('webpage_url') or entry.get('url')
                        info = ydl.extract_info(target_url, download=True)
                        entry = info.get('entries', [info])[0]
                    self.rename_downloaded_entry(path, ydl, entry, q)
            except Exception as e: self.after(0, lambda e=e: messagebox.showerror("Download Error", str(e)))
        self.after(0, self.finish_download)

    def finish_download(self):
        self.sync_btn.configure(state="normal", text="SYNC LIBRARY")
        self.url_input.delete(0, 'end')
        self.restore_placeholder_if_needed(self.url_input)
        self.status_label.configure(text="● ALL SYSTEMS NOMINAL", text_color="#00FF41")
        self.refresh_file_list()

if __name__ == "__main__":
    app = GTAMusicManager()
    app.mainloop()
