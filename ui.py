"""Runesmaker UI — translate, generate, and render runes from one window."""

import csv
import io
import os
import subprocess
import threading
import tkinter as tk
from tkinter import ttk, messagebox

# Project paths
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TRANSLATIONS_DIR = os.path.join(SCRIPT_DIR, "translations")
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "output")
LANGUAGES_FILE = os.path.join(TRANSLATIONS_DIR, "languages.txt")
RENDERER_BIN = os.path.join(SCRIPT_DIR, "renderer", "build", "rune_renderer")


def load_languages(path):
    """Parse languages.txt (tab-separated: id\\tname) into a list of names."""
    languages = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split("\t", 1)
            if len(parts) == 2:
                languages.append(parts[1])
            else:
                languages.append(parts[0])
    return languages


def _is_dark_mode():
    """Detect if the system is in dark mode (macOS)."""
    try:
        import subprocess as sp
        result = sp.run(
            ["defaults", "read", "-g", "AppleInterfaceStyle"],
            capture_output=True, text=True, timeout=2
        )
        return result.stdout.strip().lower() == "dark"
    except Exception:
        return False


class RunesmakerApp:
    def __init__(self, root):
        self.root = root
        self.dark_mode = _is_dark_mode()

        # --- Window setup ---
        self.root.title("Runesmaker")
        self.root.geometry("620x660")
        self.root.resizable(True, True)

        # --- IMPORTANT: Initialize state FIRST ---
        self.languages = load_languages(LANGUAGES_FILE)
        self.translations = {}
        self.current_index = 0
        self.csv_path = None
        self.generated_map_path = None   # {name}_map.json — 3D rune map only
        self.generated_svg_path = None   # {name}.svg       — 2D projection
        self.generated_json_path = None  # {name}.json      — full JSON for renderer


        # --- Build UI directly into root (no Canvas scroll wrapper needed) ---
        self._build_ui(self.root)

        # --- THEN update UI ---
        self._show_language()
        self._update_dropdown()

    def _build_ui(self, parent):
        pad = {"padx": 10, "pady": 4}

        # --- Rune Name ---
        name_frame = ttk.LabelFrame(parent, text="Rune Name (press Enter to load existing)", padding=8)
        name_frame.pack(fill="x", **pad)

        self.name_var = tk.StringVar(value="")
        name_entry = ttk.Entry(name_frame, textvariable=self.name_var, font=("", 14))
        name_entry.pack(fill="x")
        name_entry.bind("<Return>", lambda e: self._load_rune())

        # --- Language Dropdown ---
        dropdown_frame = ttk.LabelFrame(parent, text="Language Browser", padding=8)
        dropdown_frame.pack(fill="x", **pad)

        self.dropdown_var = tk.StringVar()
        self.dropdown = ttk.Combobox(dropdown_frame, textvariable=self.dropdown_var,
                                     state="readonly", font=("", 12))
        self.dropdown.pack(fill="x")
        self.dropdown.bind("<<ComboboxSelected>>", self._on_dropdown_select)

        # --- Translation Entry ---
        entry_frame = ttk.LabelFrame(parent, text="Translation Entry", padding=8)
        entry_frame.pack(fill="x", **pad)

        self.lang_label = ttk.Label(entry_frame, text="", font=("", 14, "bold"))
        self.lang_label.pack(anchor="w")

        self.trans_var = tk.StringVar()
        self.trans_entry = ttk.Entry(entry_frame, textvariable=self.trans_var, font=("", 16))
        self.trans_entry.pack(fill="x", pady=(4, 8))
        self.trans_entry.bind("<Return>", lambda e: self._next())

        nav_row = ttk.Frame(entry_frame)
        nav_row.pack(fill="x")
        ttk.Button(nav_row, text="\u2190 Prev", command=self._prev).pack(side="left")
        ttk.Button(nav_row, text="Skip", command=self._skip).pack(side="left", padx=10)
        ttk.Button(nav_row, text="Next \u2192", command=self._next).pack(side="left")

        self.progress_label = ttk.Label(entry_frame, text="")
        self.progress_label.pack(anchor="e", pady=(4, 0))

        self.progress_bar = ttk.Progressbar(entry_frame, maximum=len(self.languages))
        self.progress_bar.pack(fill="x", pady=(2, 0))

        # --- Auto-Translate ---
        auto_frame = ttk.LabelFrame(parent, text="Auto-Translate", padding=8)
        auto_frame.pack(fill="x", **pad)

        word_row = ttk.Frame(auto_frame)
        word_row.pack(fill="x", pady=(0, 4))
        ttk.Label(word_row, text="Word:").pack(side="left")
        self.word_var = tk.StringVar()
        ttk.Entry(word_row, textvariable=self.word_var, font=("", 14)).pack(side="left", fill="x", expand=True, padx=(8, 0))

        auto_btn_row = ttk.Frame(auto_frame)
        auto_btn_row.pack(fill="x")
        self.auto_btn = ttk.Button(auto_btn_row, text="Auto-Translate", command=self._auto_translate)
        self.auto_btn.pack(side="left")

        self.auto_status_var = tk.StringVar(
            value=f"Covers {len(self.languages)} languages via Google Translate"
        )
        ttk.Label(auto_frame, textvariable=self.auto_status_var, foreground="gray").pack(anchor="w", pady=(4, 0))

        # --- Save & View ---
        save_frame = ttk.Frame(parent)
        save_frame.pack(fill="x", padx=10, pady=(0, 4))

        self.save_btn = ttk.Button(save_frame, text="Save CSV", command=self._save)
        self.save_btn.pack(side="left")

        ttk.Button(save_frame, text="View All", command=self._view_all).pack(side="left", padx=10)

        self.save_status_var = tk.StringVar(value="")
        ttk.Label(save_frame, textvariable=self.save_status_var, foreground="gray").pack(side="left", padx=10)

        # --- Pipeline (3 stages) ---
        action_frame = ttk.LabelFrame(parent, text="Pipeline", padding=8)
        action_frame.pack(fill="x", **pad)

        # Stage 1 — Generate 3D map
        stage1_row = ttk.Frame(action_frame)
        stage1_row.pack(fill="x", pady=(0, 4))
        ttk.Label(stage1_row, text="1.", width=2).pack(side="left")
        self.gen_btn = ttk.Button(stage1_row, text="Generate", command=self._generate)
        self.gen_btn.pack(side="left")
        self.view_map_btn = ttk.Button(stage1_row, text="View Map ▶",
                                       command=self._view_map, state="disabled")
        self.view_map_btn.pack(side="left", padx=(6, 0))
        ttk.Label(stage1_row, text="— build 3D rune map", foreground="gray").pack(side="left", padx=(8, 0))

        # Stage 2 — Project to 2D SVG
        stage2_row = ttk.Frame(action_frame)
        stage2_row.pack(fill="x", pady=(0, 4))
        ttk.Label(stage2_row, text="2.", width=2).pack(side="left")
        self.project_btn = ttk.Button(stage2_row, text="Project", command=self._project, state="disabled")
        self.project_btn.pack(side="left")
        ttk.Label(stage2_row, text="— project to 2D glyph SVG", foreground="gray").pack(side="left", padx=(8, 0))

        # Stage 3 — Render 3D Vulkan
        stage3_row = ttk.Frame(action_frame)
        stage3_row.pack(fill="x")
        ttk.Label(stage3_row, text="3.", width=2).pack(side="left")
        self.render_btn = ttk.Button(stage3_row, text="Render", command=self._render, state="disabled")
        self.render_btn.pack(side="left")
        ttk.Label(stage3_row, text="— render 3D rune in Vulkan", foreground="gray").pack(side="left", padx=(8, 0))

        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(action_frame, textvariable=self.status_var, foreground="gray").pack(anchor="w", pady=(8, 0))

    # --- Dropdown ---

    def _update_dropdown(self):
        """Rebuild dropdown items with fill indicators, unfilled first."""
        unfilled = [(i, lang) for i, lang in enumerate(self.languages) if lang not in self.translations]
        filled = [(i, lang) for i, lang in enumerate(self.languages) if lang in self.translations]
        self._dropdown_order = unfilled + filled

        items = []
        for i, lang in self._dropdown_order:
            marker = "\u2713" if lang in self.translations else "\u2717"
            items.append(f"{marker}  {lang}")
        self.dropdown["values"] = items

        for dd_idx, (lang_idx, _) in enumerate(self._dropdown_order):
            if lang_idx == self.current_index:
                self.dropdown_var.set(items[dd_idx])
                break

    def _on_dropdown_select(self, event):
        """Jump to the language selected in the dropdown."""
        self._save_current()
        sel = self.dropdown.current()
        if sel >= 0:
            self.current_index = self._dropdown_order[sel][0]
            self._show_language()

    # --- Load existing rune ---

    def _load_rune(self):
        """Load an existing rune's CSV and preview when Enter is pressed."""
        name = self.name_var.get().strip()
        if not name:
            return

        csv_path = os.path.join(TRANSLATIONS_DIR, f"{name}.csv")
        if os.path.isfile(csv_path):
            self.translations.clear()
            with open(csv_path, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    lang = row["language"].strip()
                    text = row["translation"].strip()
                    if lang and text:
                        self.translations[lang] = text
            self.csv_path = csv_path
            self.current_index = 0
            self._show_language()
            self._update_dropdown()
            filled = len(self.translations)
            self.save_status_var.set(f"Loaded {filled} translations from {csv_path}")
        else:
            self.translations.clear()
            self.csv_path = None
            self.current_index = 0
            self._show_language()
            self._update_dropdown()
            self.save_status_var.set(f"New rune: {name}")

        rune_dir  = os.path.join(OUTPUT_DIR, f"{name} Rune")
        map_path  = os.path.join(rune_dir, f"{name}_map.json")
        svg_path  = os.path.join(rune_dir, f"{name}.svg")
        json_path = os.path.join(rune_dir, f"{name}.json")

        # Restore pipeline state from whatever output files exist
        self.generated_map_path  = map_path  if os.path.isfile(map_path)  else None
        self.generated_svg_path  = svg_path  if os.path.isfile(svg_path)  else None
        self.generated_json_path = json_path if os.path.isfile(json_path) else None

        map_ready  = self.generated_map_path  is not None
        json_ready = self.generated_json_path is not None

        self.view_map_btn.config(state="normal"   if map_ready  else "disabled")
        self.project_btn.config( state="normal"   if map_ready  else "disabled")
        self.render_btn.config(  state="normal"   if json_ready else "disabled")

        if json_ready:
            self.status_var.set(f"Loaded existing rune from {rune_dir}")
        elif map_ready:
            self.status_var.set(f"Map loaded — press Project to generate SVG")
        else:
            self.status_var.set("Ready")

    # --- Navigation ---

    def _save_current(self):
        lang = self.languages[self.current_index]
        text = self.trans_var.get().strip()
        if text:
            self.translations[lang] = text
        elif lang in self.translations:
            del self.translations[lang]

    def _show_language(self):
        lang = self.languages[self.current_index]
        self.lang_label.config(
            text=f"Language {self.current_index + 1} of {len(self.languages)}: {lang}"
        )
        self.trans_var.set(self.translations.get(lang, ""))
        self.trans_entry.focus_set()
        self._update_progress()
        self._update_dropdown()

    def _update_progress(self):
        filled = len(self.translations)
        self.progress_label.config(text=f"{filled} / {len(self.languages)} filled")
        self.progress_bar["value"] = filled

    def _next(self):
        self._save_current()
        # Jump to the next unfilled language (in order), or the next one if all filled
        for i in range(self.current_index + 1, len(self.languages)):
            if self.languages[i] not in self.translations:
                self.current_index = i
                self._show_language()
                return
        # Nothing unfilled after current — wrap around and check from the start
        for i in range(0, self.current_index):
            if self.languages[i] not in self.translations:
                self.current_index = i
                self._show_language()
                return
        # All filled — just go to the next one sequentially
        if self.current_index < len(self.languages) - 1:
            self.current_index += 1
        self._show_language()

    def _skip(self):
        if self.current_index < len(self.languages) - 1:
            self.current_index += 1
        self._show_language()

    def _prev(self):
        self._save_current()
        if self.current_index > 0:
            self.current_index -= 1
        self._show_language()

    # --- Auto-Translate ---

    def _auto_translate(self):
        self._save_current()

        word = self.word_var.get().strip()
        if not word:
            messagebox.showwarning("Missing word", "Enter a word to translate.")
            return

        self.auto_btn.config(state="disabled")
        self.auto_status_var.set("Auto-translating... 0%")

        threading.Thread(target=self._run_auto_translate, args=(word,), daemon=True).start()

    def _run_auto_translate(self, word):
        try:
            from pipeline.auto_translate import auto_translate

            def on_progress(done, total):
                pct = int(done / total * 100)
                self.root.after(0, self.auto_status_var.set, f"Auto-translating... {pct}% ({done}/{total})")

            results = auto_translate(word, self.languages, on_progress=on_progress)
            self.root.after(0, self._auto_translate_done, results)

        except Exception as e:
            self.root.after(0, self._auto_translate_error, str(e))

    def _auto_translate_done(self, results):
        filled_count = 0
        for lang, text in results.items():
            self.translations[lang] = text
            filled_count += 1

        self.auto_btn.config(state="normal")
        total_filled = len(self.translations)
        remaining = len(self.languages) - total_filled
        self.auto_status_var.set(
            f"Auto-filled {filled_count} languages. "
            f"{total_filled}/{len(self.languages)} total. "
            f"{remaining} remaining for manual entry."
        )
        # Jump to the first unfilled language
        for i, lang in enumerate(self.languages):
            if lang not in self.translations:
                self.current_index = i
                break
        self._show_language()
        self._update_dropdown()

    def _auto_translate_error(self, msg):
        self.auto_btn.config(state="normal")
        self.auto_status_var.set(f"Error: {msg}")

    # --- Save CSV ---

    def _write_csv(self, path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["language", "translation"])
            for lang in self.languages:
                if lang in self.translations:
                    writer.writerow([lang, self.translations[lang]])

    def _save(self):
        self._save_current()

        name = self.name_var.get().strip()
        if not name:
            messagebox.showwarning("Missing name", "Enter a rune name first.")
            return

        filled = len(self.translations)
        total = len(self.languages)
        missing = total - filled

        if missing > 0:
            missing_langs = [lang for lang in self.languages if lang not in self.translations]
            preview = ", ".join(missing_langs[:5])
            suffix = f" and {len(missing_langs) - 5} more..." if len(missing_langs) > 5 else ""
            messagebox.showwarning(
                "Incomplete translations",
                f"{missing} languages are still empty:\n\n{preview}{suffix}\n\n"
                f"All {len(self.languages)} languages must be filled before saving."
            )
            return

        self.csv_path = os.path.join(TRANSLATIONS_DIR, f"{name}.csv")
        self._write_csv(self.csv_path)
        self.save_status_var.set(f"Saved {filled} translations to {self.csv_path}")

    # --- View All (Treeview — native scrolling, fast, dark-mode aware) ---

    def _view_all(self):
        """Open a window with all languages using ttk.Treeview for native scroll."""
        self._save_current()

        name = self.name_var.get().strip() or "Translations"

        win = tk.Toplevel(self.root)
        win.title(f"All Translations -- {name}")
        win.geometry("750x600")
        win.resizable(True, True)

        # Header
        header = ttk.Frame(win)
        header.pack(fill="x", padx=10, pady=(10, 5))

        filled = len(self.translations)
        total = len(self.languages)
        ttk.Label(header, text=f"{filled} / {total} filled", font=("", 12)).pack(side="left")

        # Container for Treeview + scrollbar
        container = ttk.Frame(win)
        container.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        # Configure style for dark mode
        style = ttk.Style(win)
        if self.dark_mode:
            style.configure("ViewAll.Treeview",
                            background="#1e1e1e",
                            foreground="white",
                            fieldbackground="#1e1e1e",
                            rowheight=26,
                            font=("", 12))
            style.configure("ViewAll.Treeview.Heading",
                            background="#333333",
                            foreground="white",
                            font=("", 12, "bold"))
            style.map("ViewAll.Treeview",
                       background=[("selected", "#3a3a3a")],
                       foreground=[("selected", "white")])
        else:
            style.configure("ViewAll.Treeview",
                            rowheight=26,
                            font=("", 12))
            style.configure("ViewAll.Treeview.Heading",
                            font=("", 12, "bold"))

        columns = ("num", "status", "language", "translation")
        tree = ttk.Treeview(container, columns=columns, show="headings",
                            selectmode="none", style="ViewAll.Treeview")

        tree.heading("num", text="#", anchor="w")
        tree.heading("status", text="", anchor="center")
        tree.heading("language", text="Language", anchor="w")
        tree.heading("translation", text="Translation", anchor="w")

        tree.column("num", width=40, minwidth=30, stretch=False)
        tree.column("status", width=30, minwidth=30, stretch=False)
        tree.column("language", width=220, minwidth=150, stretch=False)
        tree.column("translation", width=400, minwidth=200, stretch=True)

        # Tag colors — bright enough for both light and dark
        tree.tag_configure("filled", foreground="#2ecc40")
        tree.tag_configure("empty", foreground="#ff4136")

        for i, lang in enumerate(self.languages):
            text = self.translations.get(lang, "")
            marker = "\u2713" if text else "\u2717"
            tag = "filled" if text else "empty"
            display_text = text if text else "(empty)"
            tree.insert("", "end",
                        values=(f"{i+1}", marker, lang, display_text),
                        tags=(tag,))

        scrollbar = ttk.Scrollbar(container, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)

        tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    # --- Stage 1: Generate 3D rune map ---

    def _generate(self):
        self._save_current()

        name = self.name_var.get().strip()
        if not name:
            messagebox.showwarning("Missing name", "Enter a rune name first.")
            return

        if not self.translations:
            messagebox.showwarning("No translations", "Enter at least one translation first.")
            return

        self.csv_path = os.path.join(TRANSLATIONS_DIR, f"{name}.csv")
        self._write_csv(self.csv_path)

        self.gen_btn.config(state="disabled")
        self.view_map_btn.config(state="disabled")
        self.project_btn.config(state="disabled")
        self.render_btn.config(state="disabled")
        self.status_var.set("Generating 3D rune map...")

        threading.Thread(target=self._run_generate, args=(self.csv_path, name), daemon=True).start()

    def _run_generate(self, csv_path, name):
        try:
            from pipeline.loader import load_translations
            from pipeline.glyph_extract import extract_glyphs
            from pipeline.weights import compute_weights
            from pipeline.rune_map import build_rune_map
            from pipeline.export import save_map

            rune_dir = os.path.join(OUTPUT_DIR, f"{name} Rune")
            os.makedirs(rune_dir, exist_ok=True)

            translations = load_translations(csv_path)
            contours = extract_glyphs(translations)

            if not contours:
                self.root.after(0, self._gen_error, "No glyphs extracted. Add fonts to fonts/ directory.")
                return

            weights  = compute_weights(contours)
            rune_map = build_rune_map(contours, weights)

            map_path = os.path.join(rune_dir, f"{name}_map.json")
            save_map(rune_map, map_path)

            self.generated_map_path = map_path
            self.root.after(0, self._gen_done, map_path,
                            len(contours), len(rune_map.curves))

        except Exception as e:
            self.root.after(0, self._gen_error, str(e))

    def _gen_done(self, map_path, n_langs, n_streamlines):
        self.status_var.set(
            f"3D map built — {n_langs} languages → {n_streamlines} streamlines. "
            "Press Project to generate SVG."
        )
        self.gen_btn.config(state="normal")
        self.view_map_btn.config(state="normal")
        self.project_btn.config(state="normal")

    def _gen_error(self, msg):
        self.status_var.set(f"Error: {msg}")
        self.gen_btn.config(state="normal")

    # --- Stage 1b: View 3D map (interactive, rotatable, live language filter) ---

    def _view_map(self):
        if not self.generated_map_path or not os.path.isfile(self.generated_map_path):
            messagebox.showerror("No map", "Generate a 3D map first.")
            return

        import json
        import math
        import colorsys
        import numpy as np
        from pipeline.rune_map import rebuild_from_encodings

        with open(self.generated_map_path) as f:
            data = json.load(f)

        name = self.name_var.get().strip() or "Rune"

        # ── Parse data ────────────────────────────────────────────────────
        # Streamlines (the 8 seed curves)
        raw_curves  = [np.array(s, dtype=np.float64) for s in data["streamlines"]]
        raw_blended = np.array(data["blended"], dtype=np.float64)

        # Per-language metadata (for table + interactive rebuild)
        lang_entries = data.get("languages", [])
        encodings    = data.get("encodings", [])
        n_langs      = len(lang_entries)

        # Steps = length of each streamline
        steps = len(raw_blended)

        # Language display data
        langs = [e["language"] for e in lang_entries]
        wts   = [float(e["weight"]) for e in lang_entries]

        # Color per language: high weight → red, low weight → blue
        wts_arr      = np.array(wts)
        w_lo, w_hi   = wts_arr.min(), wts_arr.max()
        w_span       = (w_hi - w_lo) or 1.0
        def lang_color(w):
            t   = (w - w_lo) / w_span
            hue = (1.0 - t) * 0.65
            r, g, b = colorsys.hsv_to_rgb(hue, 0.85, 0.92)
            return f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"
        lang_colors  = [lang_color(w) for w in wts]
        sorted_langs = sorted(range(n_langs), key=lambda i: wts[i], reverse=True)

        # Color per streamline (fixed hue wheel — streamlines ≠ languages)
        n_curves = len(raw_curves)
        def curve_color(i):
            r, g, b = colorsys.hsv_to_rgb(i / max(n_curves, 1), 0.6, 0.85)
            return f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"
        curve_colors = [curve_color(i) for i in range(n_curves)]

        # ── Mutable view state (updated by language toggles) ──────────────
        view = {
            "curves":      raw_curves,
            "blended":     raw_blended,
            "rebuilding":  False,
        }

        # ── Window ────────────────────────────────────────────────────────
        win = tk.Toplevel(self.root)
        win.title(f"3D Map — {name}")
        win.geometry("700x900")
        win.resizable(True, True)

        hdr = ttk.Frame(win)
        hdr.pack(fill="x", padx=12, pady=(10, 2))
        ttk.Label(hdr,
                  text=f"{n_langs} languages  ·  {n_curves} streamlines  ·  {steps} steps",
                  font=("", 12, "bold")).pack(side="left")
        ttk.Label(hdr, text="drag to rotate  ·  scroll to zoom",
                  foreground="gray").pack(side="right")

        rebuild_status = tk.StringVar(value="")
        ttk.Label(win, textvariable=rebuild_status,
                  foreground="gray").pack(anchor="e", padx=12)

        # ── 3D Canvas ─────────────────────────────────────────────────────
        CS  = 500
        PAD = 36

        canvas = tk.Canvas(win, width=CS, height=CS,
                           bg="#111111", highlightthickness=0)
        canvas.pack(padx=12, pady=(2, 6))

        cam = {"az": 0.4, "el": 0.25, "zoom": 1.0, "mx": 0, "my": 0}

        def make_R(az, el):
            ca, sa = math.cos(az), math.sin(az)
            ce, se = math.cos(el), math.sin(el)
            Ry = np.array([[ ca, 0, sa], [0, 1, 0], [-sa, 0, ca]])
            Rx = np.array([[1, 0, 0], [0, ce, -se], [0, se, ce]])
            return Rx @ Ry

        def to_canvas(pts):
            """Project (N,3) array → flat [x,y,...] canvas list."""
            R    = make_R(cam["az"], cam["el"])
            rot  = pts @ R.T
            zoom = cam["zoom"]
            px   = CS/2 + rot[:, 0] * zoom * (CS/2 - PAD)
            py   = CS/2 - rot[:, 1] * zoom * (CS/2 - PAD)
            out  = []
            for x, y in zip(px.tolist(), py.tolist()):
                out.append(x); out.append(y)
            return out, rot[:, 2]

        def draw_axes():
            R    = make_R(cam["az"], cam["el"])
            tips = np.array([[0.18,0,0],[0,0.18,0],[0,0,0.18]])
            rot  = tips @ R.T
            zoom = cam["zoom"]
            ox, oy = CS/2, CS/2
            for i, (col, lbl) in enumerate([("#ff5555","X"),("#55ff55","Y"),("#5555ff","Z")]):
                ex = CS/2 + rot[i,0] * zoom * (CS/2 - PAD)
                ey = CS/2 - rot[i,1] * zoom * (CS/2 - PAD)
                canvas.create_line(ox, oy, ex, ey, fill=col, width=2)
                canvas.create_text(ex, ey - 8, text=lbl, fill=col, font=("", 8))

        def redraw():
            canvas.delete("all")
            curves  = view["curves"]
            blended = view["blended"]

            # Depth-sort streamlines back → front
            R = make_R(cam["az"], cam["el"])
            depths = [(c @ R.T)[:, 2].mean() for c in curves]
            order  = np.argsort(depths)

            for i in order:
                coords, _ = to_canvas(curves[i])
                if len(coords) >= 4:
                    canvas.create_line(*coords, fill=curve_colors[i],
                                       width=1, smooth=True)

            # Blended (9th streamline from origin) — thick white
            coords, _ = to_canvas(blended)
            if len(coords) >= 4:
                canvas.create_line(*coords, fill="white", width=3, smooth=True)

            draw_axes()
            canvas.create_text(PAD, 16, text="─── origin streamline",
                               fill="white", anchor="w", font=("", 9))

        # ── Mouse bindings ────────────────────────────────────────────────
        def on_press(e):
            cam["mx"], cam["my"] = e.x, e.y

        def on_drag(e):
            dx, dy = e.x - cam["mx"], e.y - cam["my"]
            cam["az"] += dx * 0.008
            cam["el"]  = max(-math.pi/2 + 0.01,
                             min(math.pi/2 - 0.01, cam["el"] + dy * 0.008))
            cam["mx"], cam["my"] = e.x, e.y
            redraw()

        def on_scroll(e):
            factor = 1.1 if (getattr(e, "delta", 0) > 0
                             or getattr(e, "num", 0) == 4) else 1/1.1
            cam["zoom"] = max(0.2, min(5.0, cam["zoom"] * factor))
            redraw()

        canvas.bind("<ButtonPress-1>", on_press)
        canvas.bind("<B1-Motion>",     on_drag)
        canvas.bind("<MouseWheel>",    on_scroll)
        canvas.bind("<Button-4>",      on_scroll)
        canvas.bind("<Button-5>",      on_scroll)

        # ── Language selection table ──────────────────────────────────────
        tbl_frame = ttk.LabelFrame(
            win, text="Languages — click to show/hide  (rebuilds field with selected languages)",
            padding=6)
        tbl_frame.pack(fill="both", expand=True, padx=12, pady=(0, 10))

        btn_row = ttk.Frame(tbl_frame)
        btn_row.pack(fill="x", pady=(0, 4))

        selected_langs = set(range(n_langs))   # indices into lang_entries / encodings

        def _rebuild(active_indices):
            """Run rebuild_from_encodings in a background thread."""
            if view["rebuilding"]:
                return
            if not encodings:
                redraw()
                return
            view["rebuilding"] = True
            rebuild_status.set("Rebuilding field…")

            active_enc = [encodings[i] for i in sorted(active_indices)]

            def worker():
                try:
                    new_curves, new_blended = rebuild_from_encodings(
                        active_enc, steps=steps)
                    win.after(0, _apply, new_curves, new_blended)
                except Exception as exc:
                    win.after(0, lambda: rebuild_status.set(f"Error: {exc}"))
                    win.after(0, lambda: setattr(view, "rebuilding", False))

            def _apply(new_curves, new_blended):
                view["curves"]     = new_curves
                view["blended"]    = new_blended
                view["rebuilding"] = False
                rebuild_status.set(
                    f"Showing {len(active_enc)} / {n_langs} languages")
                redraw()

            threading.Thread(target=worker, daemon=True).start()

        def select_all():
            selected_langs.update(range(n_langs))
            for i in range(n_langs):
                tree.set(str(i), "check", "✓")
                tree.tag_configure(f"lc{i}", foreground=lang_colors[i])
            _rebuild(selected_langs)

        def select_none():
            # Keep at least the top-weighted language visible
            selected_langs.clear()
            for i in range(n_langs):
                tree.set(str(i), "check", "✗")
                tree.tag_configure(f"lc{i}", foreground="#555555")
            _rebuild(selected_langs)

        ttk.Button(btn_row, text="Select All",  command=select_all).pack(side="left")
        ttk.Button(btn_row, text="Select None", command=select_none).pack(side="left", padx=(6,0))

        tree = ttk.Treeview(tbl_frame,
                            columns=("check", "swatch", "language", "effect"),
                            show="headings", selectmode="none", height=8)
        tree.heading("check",    text="")
        tree.heading("swatch",   text="")
        tree.heading("language", text="Language")
        tree.heading("effect",   text="How much this affects the final Rune")
        tree.column("check",    width=22,  stretch=False, anchor="center")
        tree.column("swatch",   width=18,  stretch=False, anchor="center")
        tree.column("language", width=190, stretch=True)
        tree.column("effect",   width=210, stretch=False, anchor="e")

        # Rows sorted heaviest → lightest; iid = original language index
        for rank, i in enumerate(sorted_langs):
            tree.insert("", "end", iid=str(i),
                        values=("✓", "■", langs[i], f"{wts[i]*100:.3f}%"),
                        tags=(f"lc{i}",))
            tree.tag_configure(f"lc{i}", foreground=lang_colors[i])

        def on_row_click(event):
            item = tree.identify_row(event.y)
            if not item:
                return
            i = int(item)
            if i in selected_langs:
                selected_langs.discard(i)
                tree.set(item, "check", "✗")
                tree.tag_configure(f"lc{i}", foreground="#555555")
            else:
                selected_langs.add(i)
                tree.set(item, "check", "✓")
                tree.tag_configure(f"lc{i}", foreground=lang_colors[i])
            _rebuild(selected_langs)

        tree.bind("<ButtonRelease-1>", on_row_click)

        sb = ttk.Scrollbar(tbl_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        redraw()

    # --- Stage 2: Project 3D map → 2D SVG ---

    def _project(self):
        if not self.generated_map_path or not os.path.isfile(self.generated_map_path):
            messagebox.showerror("No map", "Generate a 3D map first.")
            return

        name = self.name_var.get().strip()
        if not name:
            messagebox.showwarning("Missing name", "Enter a rune name first.")
            return

        self.project_btn.config(state="disabled")
        self.render_btn.config(state="disabled")
        self.status_var.set("Projecting to 2D SVG...")

        rune_dir = os.path.join(OUTPUT_DIR, f"{name} Rune")
        threading.Thread(target=self._run_project, args=(self.generated_map_path, rune_dir, name), daemon=True).start()

    def _run_project(self, map_path, rune_dir, name):
        try:
            from pipeline.project import project
            from pipeline.export import load_map, save_svg, save_json

            rune_map = load_map(map_path)
            proj_2d  = project(rune_map)

            svg_path  = os.path.join(rune_dir, f"{name}.svg")
            json_path = os.path.join(rune_dir, f"{name}.json")
            save_svg(proj_2d, svg_path)
            save_json(rune_map, proj_2d, json_path)

            self.generated_svg_path  = svg_path
            self.generated_json_path = json_path
            self.root.after(0, self._project_done, svg_path)

        except Exception as e:
            self.root.after(0, self._project_error, str(e))

    def _project_done(self, svg_path):
        self.status_var.set(f"SVG saved — {svg_path}")
        self.project_btn.config(state="normal")
        self.render_btn.config(state="normal")
        self._open_preview(svg_path)

    def _project_error(self, msg):
        self.status_var.set(f"Project error: {msg}")
        self.project_btn.config(state="normal")

    # --- Stage 3: Render 3D Vulkan ---

    def _render(self):
        if not self.generated_json_path or not os.path.isfile(self.generated_json_path):
            messagebox.showerror("Missing JSON", "Project to 2D first.")
            return

        if not os.path.isfile(RENDERER_BIN):
            messagebox.showinfo(
                "Renderer not built",
                f"The renderer binary was not found at:\n{RENDERER_BIN}\n\n"
                "Build it with:\n"
                "  cd renderer && mkdir -p build && cd build && cmake .. && make"
            )
            return

        self.render_btn.config(state="disabled")
        self.status_var.set("Rendering 3D rune...")
        threading.Thread(target=self._run_renderer, args=(self.generated_json_path, "render_btn"), daemon=True).start()

    def _run_renderer(self, json_path, btn_attr):
        """Launch the Vulkan renderer on any JSON path (map or full)."""
        try:
            env = os.environ.copy()
            icd_path = "/opt/homebrew/etc/vulkan/icd.d/MoltenVK_icd.json"
            if os.path.isfile(icd_path):
                env["VK_ICD_FILENAMES"] = icd_path
                env["VK_DRIVER_FILES"] = icd_path
            lib_path = "/opt/homebrew/lib"
            if os.path.isdir(lib_path):
                existing = env.get("DYLD_LIBRARY_PATH", "")
                env["DYLD_LIBRARY_PATH"] = f"{lib_path}:{existing}" if existing else lib_path

            result = subprocess.run(
                [RENDERER_BIN, json_path],
                capture_output=True, text=True, env=env
            )
            if result.returncode != 0 and result.stderr and result.stderr.strip():
                self.root.after(0, self._renderer_error, result.stderr.strip(), btn_attr)
            else:
                self.root.after(0, self._renderer_done, btn_attr)
        except Exception as e:
            self.root.after(0, self._renderer_error, str(e), btn_attr)

    def _renderer_done(self, btn_attr):
        self.status_var.set("Renderer closed.")
        btn = getattr(self, btn_attr, None)
        if btn:
            btn.config(state="normal")

    def _renderer_error(self, msg, btn_attr):
        self.status_var.set(f"Render error: {msg}")
        btn = getattr(self, btn_attr, None)
        if btn:
            btn.config(state="normal")

    # --- SVG Preview Popup ---

    def _open_preview(self, svg_path):
        """Open a new window showing the rune SVG preview."""
        name = self.name_var.get().strip() or "Rune"

        win = tk.Toplevel(self.root)
        win.title(f"Preview -- {name}")
        win.geometry("500x520")
        win.resizable(True, True)

        try:
            import cairosvg
            from PIL import Image, ImageTk

            png_data = cairosvg.svg2png(
                url=svg_path, output_width=460, output_height=460,
                background_color="black"
            )
            image = Image.open(io.BytesIO(png_data))
            photo = ImageTk.PhotoImage(image)

            label = ttk.Label(win, image=photo)
            label.pack(padx=10, pady=10)
            label._photo = photo

        except ImportError:
            ttk.Label(
                win,
                text=f"SVG saved to:\n{svg_path}\n\n(Install cairosvg + Pillow for preview)",
                wraplength=450
            ).pack(padx=20, pady=20)
        except Exception as e:
            ttk.Label(win, text=f"Preview error: {e}", wraplength=450).pack(padx=20, pady=20)

        ttk.Label(win, text=svg_path, foreground="gray").pack(pady=(0, 10))


def main():
    root = tk.Tk()
    RunesmakerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
