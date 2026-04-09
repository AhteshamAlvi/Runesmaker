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


class RunesmakerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Runesmaker")
        self.root.geometry("620x600")
        self.root.resizable(True, True)

        self.languages = load_languages(LANGUAGES_FILE)
        self.translations = {}  # {language_name: translation_text}
        self.current_index = 0
        self.csv_path = None
        self.generated_svg_path = None
        self.generated_json_path = None

        self._build_ui()
        self._show_language()
        self._update_dropdown()

    def _build_ui(self):
        pad = {"padx": 10, "pady": 5}

        # --- Rune Name ---
        name_frame = ttk.LabelFrame(self.root, text="Rune Name (press Enter to load existing)", padding=10)
        name_frame.pack(fill="x", **pad)

        self.name_var = tk.StringVar(value="")
        name_entry = ttk.Entry(name_frame, textvariable=self.name_var, font=("", 14))
        name_entry.pack(fill="x")
        name_entry.bind("<Return>", lambda e: self._load_rune())

        # --- Language Dropdown ---
        dropdown_frame = ttk.LabelFrame(self.root, text="Language Browser", padding=10)
        dropdown_frame.pack(fill="x", **pad)

        self.dropdown_var = tk.StringVar()
        self.dropdown = ttk.Combobox(dropdown_frame, textvariable=self.dropdown_var,
                                     state="readonly", font=("", 12))
        self.dropdown.pack(fill="x")
        self.dropdown.bind("<<ComboboxSelected>>", self._on_dropdown_select)

        # --- Translation Entry ---
        entry_frame = ttk.LabelFrame(self.root, text="Translation Entry", padding=10)
        entry_frame.pack(fill="x", **pad)

        self.lang_label = ttk.Label(entry_frame, text="", font=("", 14, "bold"))
        self.lang_label.pack(anchor="w")

        self.trans_var = tk.StringVar()
        self.trans_entry = ttk.Entry(entry_frame, textvariable=self.trans_var, font=("", 16))
        self.trans_entry.pack(fill="x", pady=(5, 10))
        self.trans_entry.bind("<Return>", lambda e: self._next())

        nav_row = ttk.Frame(entry_frame)
        nav_row.pack(fill="x")
        ttk.Button(nav_row, text="\u2190 Prev", command=self._prev).pack(side="left")
        ttk.Button(nav_row, text="Skip", command=self._skip).pack(side="left", padx=10)
        ttk.Button(nav_row, text="Next \u2192", command=self._next).pack(side="left")

        self.progress_label = ttk.Label(entry_frame, text="")
        self.progress_label.pack(anchor="e", pady=(5, 0))

        self.progress_bar = ttk.Progressbar(entry_frame, maximum=len(self.languages))
        self.progress_bar.pack(fill="x", pady=(2, 0))

        # --- Save ---
        save_frame = ttk.Frame(self.root)
        save_frame.pack(fill="x", padx=10, pady=(5, 0))

        self.save_btn = ttk.Button(save_frame, text="Save CSV", command=self._save)
        self.save_btn.pack(side="left")

        self.save_status_var = tk.StringVar(value="")
        ttk.Label(save_frame, textvariable=self.save_status_var, foreground="gray").pack(side="left", padx=10)

        # --- Generate & Render ---
        action_frame = ttk.LabelFrame(self.root, text="Generate & Render", padding=10)
        action_frame.pack(fill="x", **pad)

        blend_row = ttk.Frame(action_frame)
        blend_row.pack(fill="x", pady=(0, 8))
        ttk.Label(blend_row, text="Blend:").pack(side="left")
        self.blend_var = tk.StringVar(value="mean")
        ttk.Radiobutton(blend_row, text="mean", variable=self.blend_var, value="mean").pack(side="left", padx=(10, 5))
        ttk.Radiobutton(blend_row, text="median", variable=self.blend_var, value="median").pack(side="left")

        btn_row = ttk.Frame(action_frame)
        btn_row.pack(fill="x")
        self.gen_btn = ttk.Button(btn_row, text="Generate", command=self._generate)
        self.gen_btn.pack(side="left")
        self.render_btn = ttk.Button(btn_row, text="Render", command=self._render, state="disabled")
        self.render_btn.pack(side="left", padx=10)

        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(action_frame, textvariable=self.status_var, foreground="gray").pack(anchor="w", pady=(5, 0))


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

        # Set dropdown selection to current language
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
        """Load an existing rune's CSV and preview when Enter is pressed on the name field."""
        name = self.name_var.get().strip()
        if not name:
            return

        # Try to load CSV
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
            # New rune — clear everything
            self.translations.clear()
            self.csv_path = None
            self.current_index = 0
            self._show_language()
            self._update_dropdown()
            self.save_status_var.set(f"New rune: {name}")

        # Try to load existing preview
        rune_dir = os.path.join(OUTPUT_DIR, f"{name} Rune")
        svg_path = os.path.join(rune_dir, f"{name}.svg")
        json_path = os.path.join(rune_dir, f"{name}.json")

        if os.path.isfile(svg_path):
            self.generated_svg_path = svg_path
            self.generated_json_path = json_path
            self.render_btn.config(state="normal")
            self.status_var.set(f"Loaded existing rune from {rune_dir}")
        else:
            self.generated_svg_path = None
            self.generated_json_path = None
            self.render_btn.config(state="disabled")

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

        if not self.translations:
            messagebox.showwarning("No translations", "Enter at least one translation first.")
            return

        self.csv_path = os.path.join(TRANSLATIONS_DIR, f"{name}.csv")
        self._write_csv(self.csv_path)
        filled = len(self.translations)
        self.save_status_var.set(f"Saved {filled} translations to {self.csv_path}")

    # --- Generate ---

    def _generate(self):
        self._save_current()

        name = self.name_var.get().strip()
        if not name:
            messagebox.showwarning("Missing name", "Enter a rune name first.")
            return

        if not self.translations:
            messagebox.showwarning("No translations", "Enter at least one translation first.")
            return

        # Always save CSV before generating
        self.csv_path = os.path.join(TRANSLATIONS_DIR, f"{name}.csv")
        self._write_csv(self.csv_path)

        self.gen_btn.config(state="disabled")
        self.render_btn.config(state="disabled")
        self.status_var.set("Generating...")

        blend = self.blend_var.get()
        threading.Thread(target=self._run_generate, args=(self.csv_path, name, blend), daemon=True).start()

    def _run_generate(self, csv_path, name, blend):
        try:
            from pipeline.loader import load_translations
            from pipeline.glyph_extract import extract_glyphs
            from pipeline.vectorize import vectorize_contours
            from pipeline.blend import blend_rune
            from pipeline.export import save_svg, save_json

            # Output goes into output/<name> Rune/
            rune_dir = os.path.join(OUTPUT_DIR, f"{name} Rune")
            os.makedirs(rune_dir, exist_ok=True)

            translations = load_translations(csv_path)
            contours = extract_glyphs(translations)

            if not contours:
                self.root.after(0, self._gen_error, "No glyphs extracted. Add fonts to fonts/ directory.")
                return

            vectors = vectorize_contours(contours)
            rune = blend_rune(vectors, method=blend)

            svg_path = os.path.join(rune_dir, f"{name}.svg")
            json_path = os.path.join(rune_dir, f"{name}.json")
            save_svg(rune, svg_path)
            save_json(rune, json_path)

            self.generated_svg_path = svg_path
            self.generated_json_path = json_path
            self.root.after(0, self._gen_done, svg_path)

        except Exception as e:
            self.root.after(0, self._gen_error, str(e))

    def _gen_done(self, svg_path):
        self.status_var.set(f"Done! Saved to {svg_path}")
        self.gen_btn.config(state="normal")
        self.render_btn.config(state="normal")
        self._open_preview(svg_path)

    def _gen_error(self, msg):
        self.status_var.set(f"Error: {msg}")
        self.gen_btn.config(state="normal")

    # --- Render ---

    def _render(self):
        if not self.generated_json_path or not os.path.isfile(self.generated_json_path):
            messagebox.showerror("Missing JSON", "Generate a rune first.")
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
        self.status_var.set("Rendering...")

        threading.Thread(target=self._run_render, daemon=True).start()

    def _run_render(self):
        try:
            result = subprocess.run(
                [RENDERER_BIN, self.generated_json_path],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode != 0:
                self.root.after(0, self._render_error, result.stderr or "Renderer exited with error")
            else:
                self.root.after(0, self._render_done)
        except subprocess.TimeoutExpired:
            self.root.after(0, self._render_error, "Renderer timed out")
        except Exception as e:
            self.root.after(0, self._render_error, str(e))

    def _render_done(self):
        self.status_var.set("Render complete!")
        self.render_btn.config(state="normal")

    def _render_error(self, msg):
        self.status_var.set(f"Render error: {msg}")
        self.render_btn.config(state="normal")

    # --- SVG Preview Popup ---

    def _open_preview(self, svg_path):
        """Open a new window showing the rune SVG preview."""
        name = self.name_var.get().strip() or "Rune"

        win = tk.Toplevel(self.root)
        win.title(f"Preview — {name}")
        win.geometry("500x520")
        win.resizable(True, True)

        try:
            import cairosvg
            from PIL import Image, ImageTk

            png_data = cairosvg.svg2png(url=svg_path, output_width=460, output_height=460,
                                        background_color="black")
            image = Image.open(io.BytesIO(png_data))
            photo = ImageTk.PhotoImage(image)

            label = ttk.Label(win, image=photo)
            label.pack(padx=10, pady=10)
            label._photo = photo

        except ImportError:
            ttk.Label(win, text=f"SVG saved to:\n{svg_path}\n\n(Install cairosvg + Pillow for preview)",
                      wraplength=450).pack(padx=20, pady=20)
        except Exception as e:
            ttk.Label(win, text=f"Preview error: {e}", wraplength=450).pack(padx=20, pady=20)

        ttk.Label(win, text=svg_path, foreground="gray").pack(pady=(0, 10))


def main():
    root = tk.Tk()
    RunesmakerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
