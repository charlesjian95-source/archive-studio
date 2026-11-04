"""Traditional Chinese Windows desktop UI for Archive Studio."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import archive_engine as engine
from photo_panel import PhotoPanel
import photo_engine as photos
from visual_theme import Visuals, Card, BG, INK, MUTED, ACCENT, LINE, NAV

APP_NAME = "Archive Studio 檔案工具"
MODES = {
    "compress": ("壓縮檔案", "將檔案與資料夾打包，選擇適合的壓縮格式。", "開始壓縮"),
    "extract": ("解壓縮", "選擇壓縮包，將內容完整展開到新的資料夾。", "開始解壓縮"),
    "convert": ("轉換格式", "保留壓縮包內的檔案結構，轉成另一種壓縮格式。", "開始轉換"),
    "photos": ("照片轉檔", "批次轉換、縮小照片，先預覽再輸出。", "開始照片轉檔"),
}


def readable_size(size):
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return (str(int(value)) if unit == "B" else "%.1f" % value) + " " + unit
        value /= 1024


class WindowsDrop:
    """Use Windows shell file drops; no additional runtime dependency."""
    def __init__(self, widget, on_drop):
        self.widget = widget
        self.on_drop = on_drop
        self.hwnd = None
        if sys.platform != "win32":
            return
        user = ctypes.WinDLL("user32", use_last_error=True)
        shell = ctypes.WinDLL("shell32", use_last_error=True)
        pointer = ctypes.c_ssize_t
        self.proc_type = ctypes.WINFUNCTYPE(pointer, wintypes.HWND, wintypes.UINT,
                                           wintypes.WPARAM, wintypes.LPARAM)
        user.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        user.GetAncestor.restype = wintypes.HWND
        user.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, pointer]
        user.SetWindowLongPtrW.restype = pointer
        user.CallWindowProcW.argtypes = [pointer, wintypes.HWND, wintypes.UINT,
                                         wintypes.WPARAM, wintypes.LPARAM]
        user.CallWindowProcW.restype = pointer
        shell.DragAcceptFiles.argtypes = [wintypes.HWND, wintypes.BOOL]
        shell.DragQueryFileW.argtypes = [wintypes.HANDLE, wintypes.UINT,
                                        wintypes.LPWSTR, wintypes.UINT]
        shell.DragQueryFileW.restype = wintypes.UINT
        shell.DragFinish.argtypes = [wintypes.HANDLE]
        widget.update_idletasks()
        self.hwnd = user.GetAncestor(widget.winfo_id(), 2)

        def window_proc(hwnd, message, wparam, lparam):
            if message == 0x233:  # WM_DROPFILES
                paths = []
                try:
                    count = shell.DragQueryFileW(wparam, 0xFFFFFFFF, None, 0)
                    for index in range(count):
                        length = shell.DragQueryFileW(wparam, index, None, 0)
                        buffer = ctypes.create_unicode_buffer(length + 1)
                        shell.DragQueryFileW(wparam, index, buffer, length + 1)
                        paths.append(buffer.value)
                finally:
                    shell.DragFinish(wparam)
                widget.after_idle(lambda: on_drop(paths))
                return 0
            return user.CallWindowProcW(self.original, hwnd, message, wparam, lparam)

        self.callback = self.proc_type(window_proc)
        self.original = user.SetWindowLongPtrW(
            self.hwnd, -4, ctypes.cast(self.callback, ctypes.c_void_p).value)
        if not self.original:
            raise ctypes.WinError(ctypes.get_last_error())
        shell.DragAcceptFiles(self.hwnd, True)
        self.user, self.shell = user, shell

    def close(self):
        if self.hwnd:
            self.shell.DragAcceptFiles(self.hwnd, False)
            self.user.SetWindowLongPtrW(self.hwnd, -4, self.original)
            self.hwnd = None


class ArchiveApp:
    def __init__(self, root, launch=None, ui_scale=None, persist_preferences=None):
        self.root = root
        self.scale = ui_scale or max(1.0, float(root.winfo_fpixels("1i")) / 96)
        self.mode = "compress"
        self.selections = {key: [] for key in MODES}
        self.busy = False
        self.cancel = threading.Event()
        self.events = queue.Queue()
        self.last_result = None
        self.mode_results = {key: None for key in MODES}
        self.persist_preferences = bool(getattr(sys, "frozen", False)) if persist_preferences is None else persist_preferences
        self.last_input_dir = str(Path.home())
        self.output_chosen = False
        self.name = tk.StringVar(value="我的壓縮包")
        self.output = tk.StringVar(value=str(Path.home() / "Downloads" / "Archive Studio"))
        self.format = tk.StringVar(value="ZIP")
        self.level = tk.StringVar(value="標準 · 速度與大小平衡")
        root.title(APP_NAME + "  1.3")
        root.configure(bg=BG)
        width, height = root.winfo_screenwidth(), root.winfo_screenheight()
        if sys.platform == "win32":
            work = wintypes.RECT()
            if ctypes.windll.user32.SystemParametersInfoW(48, 0, ctypes.byref(work), 0):
                width, height = work.right - work.left, work.bottom - work.top
        w, h = min(self.px(1120), width - self.px(48)), min(self.px(800), height - self.px(42))
        root.geometry("%dx%d" % (w, h))
        root.minsize(min(self.px(820), w), min(self.px(680), h))
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.option_add("*Font", self.font())
        self.compact = None
        self.setup_styles()
        self.build()
        self.switch_mode("compress")
        root.bind("<Configure>", self.adapt_layout, add="+")
        root.bind("<Control-o>", lambda event: self.choose_files() if not self.busy else None)
        root.bind("<Control-Shift-O>", lambda event: self.choose_folder() if not self.busy else None)
        root.bind("<Control-Return>", lambda event: self.start())
        root.bind("<Escape>", lambda event: self.cancel_work() if self.busy else None)
        self.poll_job = self.root.after(80, self.poll)
        self.drop = None
        try:
            self.drop = WindowsDrop(root, self.add_paths)
        except (OSError, AttributeError):
            self.drop_hint.configure(text="點選「加入檔案」或「加入資料夾」開始")
        if launch:
            mode, paths = launch
            self.switch_mode(mode)
            if paths:
                self.add_paths(paths)

    def px(self, value):
        return max(1, round(value * self.scale))

    def font(self, size=14, bold=False):
        return ("Microsoft JhengHei UI", -self.px(size), "bold" if bold else "normal")

    def setup_styles(self):
        self.visuals = Visuals(self)
        self.visuals.apply()

    def label(self, parent, text, size=14, color=INK, bold=False, **kwargs):
        return tk.Label(parent, text=text, font=self.font(size, bold), fg=color,
                        bg=parent.cget("bg"), anchor="w", bd=0, highlightthickness=0,padx=0,pady=0,**kwargs)

    def build(self):
        p = self.px
        body = tk.Frame(self.root, bg=BG)
        body.pack(fill="both", expand=True, padx=p(24), pady=p(20))
        body.grid_columnconfigure(0, weight=1)
        body.grid_rowconfigure(2, weight=1)
        header = tk.Frame(body, bg=BG)
        header.grid(row=0, column=0, sticky="ew", pady=(0, p(16)))
        header.grid_columnconfigure(1, weight=1)
        brand_icon = tk.Label(header, image=self.visuals.icon("brand",42), bg=BG, bd=0)
        brand_icon.grid(row=0,column=0,rowspan=2,padx=(0,p(12)))
        self.brand = self.label(header, "Archive Studio", 23, INK, True)
        self.brand.configure(font=("Segoe UI",-p(24),"bold"))
        self.brand.grid(row=0, column=1, sticky="w")
        self.integration_button = ttk.Button(header, text="Windows 整合", style="Ghost.TButton",
            image=self.visuals.icon("settings",17,MUTED),compound="left",command=self.install_integration)
        self.integration_button.grid(row=0, column=3, rowspan=2, sticky="e",padx=(p(12),0))
        self.local_badge = self.label(header,"●  本機處理",12,"#188675")
        self.local_badge.grid(row=0,column=2,rowspan=2,sticky="e")
        self.header_subtitle = self.label(header, "壓縮、解壓縮與照片轉檔", 12, MUTED)
        self.header_subtitle.grid(
            row=1, column=1, sticky="w", pady=(p(2), 0))
        nav_card = Card(body,p,color=NAV,outline=NAV,radius=14,inset=4)
        nav_card.grid(row=1,column=0,sticky="ew",pady=(0,p(14)))
        navrow = nav_card.content
        self.nav = {}
        for index, (key, text) in enumerate((("compress", "壓縮檔案"), ("extract", "解壓縮"),
                                           ("convert", "壓縮包互轉"), ("photos", "照片轉檔"))):
            navrow.grid_columnconfigure(index, weight=1, uniform="tabs")
            button = ttk.Button(navrow, text=text, style="Mode.TButton", image=self.visuals.icon(key,19),compound="left",
                                command=lambda k=key: self.switch_mode(k))
            button.grid(row=0, column=index, sticky="ew",
                        padx=(0 if index == 0 else p(4), 0 if index == 3 else p(4)))
            self.nav[key] = button
        files_card = Card(body,p)
        files_card.grid(row=2, column=0, sticky="nsew", pady=(0, p(12)))
        files = files_card.content
        files.grid_columnconfigure(0, weight=1)
        files.grid_rowconfigure(2, weight=1)
        titlebar = self.files_titlebar = tk.Frame(files, bg="white")
        titlebar.grid(row=0, column=0, sticky="ew", padx=p(16), pady=(p(12), p(8)))
        titlebar.grid_columnconfigure(0, weight=1)
        self.files_title = self.label(titlebar, "待處理檔案", 14, INK, True)
        self.files_title.grid(row=0, column=0, sticky="w")
        self.count = self.label(titlebar, "尚未加入", 12, MUTED)
        self.count.grid(row=0, column=1, sticky="e")
        bar = tk.Frame(files, bg="white")
        bar.grid(row=1, column=0, sticky="ew", padx=p(16), pady=(0, p(10)))
        self.add_button = ttk.Button(bar, text="加入檔案", style="Secondary.TButton",image=self.visuals.icon("add",16),compound="left",command=self.choose_files)
        self.add_button.pack(side="left")
        self.folder_button = ttk.Button(bar, text="加入資料夾",image=self.visuals.icon("folder",16,MUTED),compound="left",command=self.choose_folder)
        self.folder_button.pack(side="left", padx=(p(8), 0))
        self.remove_button = ttk.Button(bar, text="移出清單", style="Quiet.TButton",command=self.remove_selected)
        self.remove_button.pack(side="right")
        self.clear_button = ttk.Button(bar, text="清空",style="Quiet.TButton",command=self.clear_list)
        self.clear_button.pack(side="right", padx=(0, p(8)))
        tree_frame = tk.Frame(files, bg="white")
        tree_frame.grid(row=2, column=0, sticky="nsew", padx=p(16))
        self.tree = ttk.Treeview(tree_frame, columns=("name", "kind", "size"),
                                show="headings", height=6, selectmode="extended")
        self.tree.heading("name", text="檔案名稱", anchor="w")
        self.tree.heading("kind", text="類型", anchor="w")
        self.tree.heading("size", text="大小", anchor="e")
        self.tree.tag_configure("alternate",background="#fafbfe")
        self.tree.column("name", width=p(420), minwidth=p(170))
        self.tree.column("kind", width=p(90), stretch=False)
        self.tree.column("size", width=p(105), stretch=False, anchor="e")
        scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<Delete>", lambda event: self.remove_selected())
        self.tree.bind("<Control-a>", lambda event: self.tree.selection_set(self.tree.get_children()))
        scroll.pack(side="right", fill="y")
        self.empty_state = tk.Label(tree_frame, text="把檔案拖到這裡\n或點選上方「加入檔案」", bg="white",
                                    fg=MUTED, font=self.font(13), justify="center",bd=0,pady=p(8),
                                    image=self.visuals.icon("folder",38,"#a5b0d0"),compound="top")
        self.empty_state.place(relx=0.5, rely=0.55, anchor="center")
        self.drop_hint = self.label(files, "將檔案或資料夾拖到這裡，或使用上方按鈕加入。", 12, MUTED)
        self.drop_hint.grid(row=3, column=0, sticky="ew", padx=p(16), pady=(p(8), p(10)))
        self.title = self.files_title
        self.subtitle = self.drop_hint

        settings_card = Card(body,p)
        settings_card.grid(row=3, column=0, sticky="ew", pady=(0, p(12)))
        settings = settings_card.content
        settings.grid_columnconfigure(0, weight=1)
        self.label(settings, "輸出設定", 14, INK, True).grid(
            row=0, column=0, sticky="w", padx=p(16), pady=(p(12), p(8)))
        row = tk.Frame(settings, bg="white")
        row.grid(row=1, column=0, sticky="ew", padx=p(16))
        row.grid_columnconfigure(0, weight=3)
        row.grid_columnconfigure(1, weight=1)
        row.grid_columnconfigure(2, weight=2)
        self.name_label = self.label(row, "壓縮包名稱", 12, MUTED)
        self.name_label.grid(row=0, column=0, sticky="w", pady=(0, p(4)))
        self.name_entry = ttk.Entry(row, textvariable=self.name, width=22, font=self.font())
        self.name_entry.grid(row=1, column=0, sticky="ew", padx=(0, p(12)))
        self.label(row, "格式", 12, MUTED).grid(row=0, column=1, sticky="w", pady=(0, p(4)))
        self.format_combo = ttk.Combobox(row, textvariable=self.format,
                                        values=list(engine.FORMATS), state="readonly", width=9, font=self.font())
        self.format_combo.grid(row=1, column=1, sticky="ew", padx=(0, p(12)))
        self.format_combo.bind("<<ComboboxSelected>>", lambda e: self.refresh_format())
        self.label(row, "壓縮程度", 12, MUTED).grid(row=0, column=2, sticky="w", pady=(0, p(4)))
        self.level_combo = ttk.Combobox(row, textvariable=self.level, state="readonly", width=23, font=self.font(),
                                       values=("快速 · 優先節省時間", "標準 · 速度與大小平衡",
                                               "最小 · 花較多時間壓縮"))
        self.level_combo.grid(row=1, column=2, sticky="ew")
        self.format_note = self.label(settings, "", 12, MUTED)
        self.format_note.grid(row=2, column=0, sticky="ew", padx=p(16), pady=(p(6), p(8)))
        outputrow = tk.Frame(settings, bg="white")
        outputrow.grid(row=3, column=0, sticky="ew", padx=p(16), pady=(0, p(12)))
        outputrow.grid_columnconfigure(1, weight=1)
        self.label(outputrow, "儲存位置", 12, MUTED).grid(row=0, column=0, padx=(0, p(10)))
        self.output_entry = ttk.Entry(outputrow, textvariable=self.output, width=25, font=self.font())
        self.output_entry.grid(row=0, column=1, sticky="ew")
        self.browse_button = ttk.Button(outputrow, text="瀏覽…", command=self.choose_output)
        self.browse_button.grid(row=0, column=2, padx=(p(8), 0))
        self.output_entry.bind("<KeyRelease>", lambda e: setattr(self, "output_chosen", True))

        bottom = tk.Frame(body, bg=BG)
        bottom.grid(row=4, column=0, sticky="ew")
        bottom.grid_columnconfigure(0, weight=1)
        self.status = self.label(bottom, "準備就緒", 13, INK, True)
        self.status.grid(row=0, column=0, sticky="ew")
        self.percent = self.label(bottom, "0%", 12, MUTED)
        self.percent.grid(row=0, column=1, sticky="e")
        self.progress = ttk.Progressbar(bottom, maximum=100, mode="determinate")
        self.progress.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(p(7), p(7)))
        self.detail = self.label(bottom, "原始檔保留；同名輸出自動編號。", 12, MUTED, wraplength=p(760))
        self.detail.grid(row=2, column=0, columnspan=2, sticky="ew")
        actions = tk.Frame(bottom, bg=BG)
        actions.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(p(10), 0))
        self.open_button = ttk.Button(actions, text="開啟輸出位置",style="Footer.TButton",image=self.visuals.icon("open",16,MUTED),compound="left",command=self.open_result,
                                      state="disabled")
        self.open_button.pack(side="left")
        self.result_button = ttk.Button(actions, text="查看逐張結果",style="Footer.TButton",command=lambda: self.photo_panel.show_results(), state="disabled")
        self.start_button = ttk.Button(actions, style="Primary.TButton", text="開始壓縮",
                                      command=self.start)
        self.start_button.pack(side="right")
        self.cancel_button = ttk.Button(actions, text="取消",style="Footer.TButton",command=self.cancel_work, state="disabled")
        self.cancel_button.pack(side="right", padx=(0, p(8)))
        self.archive_files = files_card
        self.archive_settings = settings_card
        self.photo_panel = PhotoPanel(self, body, persist=self.persist_preferences)

    def adapt_layout(self, event=None):
        if event is not None and event.widget is not self.root:
            return
        compact = self.root.winfo_height() < self.px(740)
        if compact == self.compact:
            return
        self.compact = compact
        for widget in (self.header_subtitle, self.files_titlebar, self.format_note,
                       self.drop_hint, self.detail):
            if compact:
                widget.grid_remove()
            else:
                widget.grid()
        self.photo_panel.adapt_layout(compact)

    def switch_mode(self, mode):
        if self.busy:
            return
        self.mode = mode
        self.last_result = self.mode_results[mode]
        self.open_button.configure(state="normal" if self.last_result else "disabled")
        title, subtitle, action = MODES[mode]
        self.start_button.configure(text=action)
        for key, button in self.nav.items():
            button.configure(style="Selected.Mode.TButton" if key == mode else "Mode.TButton")
        if mode == "photos":
            self.archive_files.grid_remove()
            self.archive_settings.grid_remove()
            self.photo_panel.frame.grid(row=2, column=0, rowspan=2, sticky="nsew")
            self.result_button.pack(side="left", padx=(self.px(8), 0))
            self.result_button.configure(state="normal" if self.photo_panel.result else "disabled")
            self.status.configure(text="加入照片後，選取一張即可預覽。", fg=INK)
            self.detail.configure(text="HEIC／HEIF、JPG、PNG、WebP、AVIF、TIFF、BMP。")
            self.photo_panel.schedule_preview()
            self.update_start_state()
            return
        self.photo_panel.frame.grid_remove()
        self.archive_files.grid()
        self.archive_settings.grid()
        self.result_button.pack_forget()
        self.add_button.configure(text="加入檔案" if mode == "compress" else "選擇壓縮包")
        self.empty_state.configure(image=self.visuals.icon("folder" if mode=="compress" else mode,38,"#a5b0d0"))
        if mode == "compress":
            self.folder_button.pack(side="left", padx=(self.px(8), 0))
            self.drop_hint.configure(text="將檔案或資料夾拖到這裡，或使用上方按鈕加入。")
        else:
            self.folder_button.pack_forget()
            self.drop_hint.configure(text="拖入一個壓縮包，或按「選擇壓縮包」。")
        self.files_title.configure(text="待壓縮的檔案與資料夾" if mode == "compress" else
                                  "要解壓縮的壓縮包" if mode == "extract" else "要轉換的壓縮包")
        self.refresh_tree()
        self.refresh_format()
        if self.selections[mode]:
            self.suggest_name()
        self.status.configure(text="準備就緒", fg=INK)
        self.detail.configure(text="原始檔保留；同名輸出自動編號。")
        self.update_start_state()

    def install_integration(self):
        try:
            from windows_integration import register
            register()
            messagebox.showinfo("右鍵選單已加入", "對檔案或資料夾按右鍵，即可使用 Archive Studio。\nWindows 11 請展開「顯示其他選項」。", parent=self.root)
        except Exception as exc:
            messagebox.showerror("無法加入右鍵選單", str(exc), parent=self.root)


    def refresh_format(self):
        if self.mode == "photos":
            return
        extracting = self.mode == "extract"
        self.name_entry.configure(state="disabled" if extracting or self.busy else "normal")
        self.format_combo.configure(state="disabled" if extracting or self.busy else "readonly")
        self.level_combo.configure(state="disabled" if extracting or self.busy or
                                   self.format.get() == "TAR" else "readonly")
        self.name_label.configure(text="解壓後依原檔命名" if extracting else "壓縮包名稱")
        text = ("解壓後另建資料夾，不會覆蓋既有檔案。" if extracting else
                "TAR 只打包，不縮小檔案；需要壓縮請選 ZIP 或 TAR.GZ。"
                if self.format.get() == "TAR" else
                "ZIP 適合 Windows 分享；TAR.GZ 適合跨平台使用。")
        self.format_note.configure(text=text)

    def suggest_name(self):
        if self.mode == "photos":
            return
        paths = self.selections[self.mode]
        if not paths:
            return
        path = Path(paths[0])
        self.name.set(engine.archive_stem(path) if self.mode != "compress" else path.stem)
        if not self.output_chosen:
            self.output.set(str(path.parent / "壓縮結果"))

    def add_paths(self, paths):
        if self.busy:
            return
        if self.mode == "photos":
            self.photo_panel.add_paths(paths)
            return
        valid = []
        for value in paths:
            path = Path(value)
            if not path.exists():
                messagebox.showerror("找不到檔案", str(path), parent=self.root)
                return
            if self.mode != "compress" and not path.is_file():
                messagebox.showinfo("請選擇壓縮包", "解壓縮與轉換格式需要一個壓縮包檔案。", parent=self.root)
                return
            valid.append(str(path.absolute()))
        if self.mode != "compress":
            if len(valid) != 1:
                messagebox.showinfo("一次處理一個壓縮包", "請只加入一個壓縮包。", parent=self.root)
                return
            self.selections[self.mode] = valid
        else:
            current = self.selections[self.mode]
            for path in valid:
                if os.path.normcase(path) not in {os.path.normcase(p) for p in current}:
                    current.append(path)
        self.refresh_tree()
        self.suggest_name()
        if valid:
            self.last_input_dir = str(Path(valid[0]).parent)

    def refresh_tree(self):
        self.tree.delete(*self.tree.get_children())
        paths = self.selections[self.mode]
        if paths:
            self.empty_state.place_forget()
        else:
            self.empty_state.configure(text="把檔案或資料夾拖到這裡\n或點選上方按鈕加入"
                                       if self.mode == "compress" else
                                       "把壓縮包拖到這裡\n或點選「選擇壓縮包」")
            self.empty_state.place(relx=0.5, rely=0.55, anchor="center")
        for index, value in enumerate(paths):
            path = Path(value)
            try:
                directory = path.is_dir()
                kind = "資料夾" if directory else (path.suffix.upper().lstrip(".") or "檔案")
                size = "—" if directory else readable_size(path.stat().st_size)
            except OSError:
                kind, size = "無法讀取", "—"
            self.tree.insert("", "end", iid=str(index), values=(path.name, kind, size),tags=("alternate",) if index%2 else ())
        self.count.configure(text=str(len(paths)) + " 個項目" if paths else "尚未加入")
        self.update_start_state()

    def choose_files(self):
        if self.mode == "photos":
            self.photo_panel.choose_files()
            return
        types = [("壓縮包", "*.zip *.tar *.gz *.tgz *.bz2 *.xz"), ("所有檔案", "*.*")]
        if self.mode == "compress":
            paths = filedialog.askopenfilenames(parent=self.root, title="加入要壓縮的檔案", initialdir=self.last_input_dir, filetypes=[("所有檔案", "*")])
        else:
            path = filedialog.askopenfilename(parent=self.root, title="選擇壓縮包", initialdir=self.last_input_dir, filetypes=types)
            paths = [path] if path else []
        if paths:
            self.add_paths(paths)

    def choose_folder(self):
        if self.mode == "photos":
            self.photo_panel.choose_folder()
            return
        if self.mode != "compress":
            self.choose_files()
            return
        path = filedialog.askdirectory(parent=self.root, title="加入要壓縮的資料夾", initialdir=self.last_input_dir)
        if path:
            self.add_paths([path])

    def remove_selected(self):
        if self.busy:
            return
        if self.mode == "photos":
            self.photo_panel.remove_selected()
            return
        selected = {int(index) for index in self.tree.selection()}
        self.selections[self.mode] = [p for i, p in enumerate(self.selections[self.mode])
                                      if i not in selected]
        self.refresh_tree()

    def clear_list(self):
        if self.mode == "photos":
            self.photo_panel.clear()
            return
        if not self.busy:
            self.selections[self.mode] = []
            self.refresh_tree()

    def choose_output(self):
        if self.mode == "photos":
            self.photo_panel.choose_output()
            return
        path = filedialog.askdirectory(parent=self.root, title="選擇輸出資料夾")
        if path:
            self.output.set(path)
            self.output_chosen = True

    def set_busy(self, value):
        self.busy = value
        for button in (self.add_button, self.folder_button, self.remove_button,
                       self.clear_button, self.browse_button, self.start_button, self.integration_button):
            button.configure(state="disabled" if value else "normal")
        for button in self.nav.values():
            button.configure(state="disabled" if value else "normal")
        self.output_entry.configure(state="disabled" if value else "normal")
        self.cancel_button.configure(state="normal" if value else "disabled")
        self.refresh_format()
        self.photo_panel.set_busy(value)
        self.update_start_state()

    def update_start_state(self):
        available = bool(self.selections[self.mode])
        if self.mode == "photos":
            available = bool(self.photo_panel.sources) and not self.photo_panel.loading
        self.start_button.configure(state="normal" if available and not self.busy else "disabled")

    def start(self):
        if self.busy:
            return
        if self.mode == "photos":
            self.photo_panel.start()
            return
        paths = self.selections[self.mode][:]
        if not paths:
            messagebox.showinfo("先加入檔案", "請先選擇檔案、資料夾或壓縮包。", parent=self.root)
            return
        if not self.output.get().strip():
            messagebox.showinfo("選擇儲存位置", "請選擇輸出資料夾。", parent=self.root)
            return
        mode, output, name, fmt = self.mode, self.output.get(), self.name.get(), self.format.get()
        if mode != "extract":
            try:
                engine.archive_name(name, fmt)
            except engine.ArchiveError as exc:
                messagebox.showerror("檔名無效", str(exc), parent=self.root)
                return
        level = 1 if self.level.get().startswith("快速") else 9 if self.level.get().startswith("最小") else 6
        self.cancel.clear()
        self.last_result = None
        self.open_button.configure(state="disabled")
        self.progress["value"] = 0
        self.percent.configure(text="0%")
        self.status.configure(text="正在檢查來源檔案…", fg=INK)
        self.detail.configure(text="處理中，你可以隨時取消。")
        self.set_busy(True)

        def progress(fraction, current, done, total):
            self.events.put(("progress", (fraction, current, done, total)))

        def worker():
            try:
                if mode == "compress":
                    result = engine.compress(paths, output, name, fmt, level, progress, self.cancel)
                elif mode == "convert":
                    result = engine.convert(paths[0], output, name, fmt, level, progress, self.cancel)
                else:
                    result = engine.extract(paths[0], output, progress, self.cancel)
                self.events.put(("done", result))
            except engine.Cancelled as exc:
                self.events.put(("cancelled", str(exc)))
            except Exception as exc:
                self.events.put(("error", str(exc) or type(exc).__name__))

        threading.Thread(target=worker, daemon=True).start()

    def poll(self):
        latest = None
        terminal = None
        while True:
            try:
                event, data = self.events.get_nowait()
            except queue.Empty:
                break
            if event.startswith("photo_"):
                self.photo_panel.handle_event(event, data)
            elif event == "progress":
                latest = data
            else:
                terminal = (event, data)
        if latest:
            fraction, current, done, total = latest
            self.progress["value"] = fraction * 100
            self.percent.configure(text=str(int(fraction * 100)) + "%")
            self.status.configure(text="正在處理：" + (current[:42] + "…" if len(current) > 42 else current))
            self.detail.configure(text=readable_size(done) + " / " + readable_size(total))
        if terminal:
            event, data = terminal
            self.set_busy(False)
            if event == "done":
                self.last_result = data
                self.mode_results[self.mode] = data
                self.progress["value"] = 100
                self.percent.configure(text="100%")
                self.status.configure(text="完成！已處理 " + str(data.files) + " 個檔案", fg="#26846a")
                info = readable_size(data.output_bytes) + " · %.1f 秒" % data.seconds
                if self.mode != "extract" and data.original_bytes:
                    saving = (1 - data.output_bytes / data.original_bytes) * 100
                    info += (" · 減少 %.1f%%" % saving if saving >= 0 else
                             " · 此內容壓縮後未縮小")
                self.detail.configure(text=data.path.name + "   /   " + info)
                self.open_button.configure(state="normal")
                if self.mode == "photos":
                    self.photo_panel.finish(data)
            else:
                self.status.configure(text="工作已取消" if event == "cancelled" else "無法完成", fg=MUTED if event == "cancelled" else "#b64c58")
                self.detail.configure(text="原始檔案已保留。請查看訊息中的原因與未完成檔案位置。")
                if event == "cancelled":
                    messagebox.showinfo("工作已取消", data, parent=self.root)
                else:
                    messagebox.showerror("無法完成", data, parent=self.root)
        self.poll_job = self.root.after(80, self.poll)

    def cancel_work(self):
        self.cancel.set()
        self.cancel_button.configure(state="disabled")
        self.status.configure(text="正在取消，請稍候…")

    def open_result(self):
        if self.last_result:
            path = self.last_result.path
            folder = path if path.is_dir() else path.parent
            try:
                os.startfile(str(folder))
            except OSError as exc:
                messagebox.showerror("無法開啟資料夾", str(exc), parent=self.root)

    def close(self):
        if self.busy:
            messagebox.showinfo("檔案處理中", "請先按「取消」，等待工作停止後再關閉程式。", parent=self.root)
            return
        if getattr(self, "poll_job", None):
            self.root.after_cancel(self.poll_job)
            self.poll_job = None
        if self.drop:
            self.drop.close()
        self.photo_panel.close()
        self.root.destroy()


def parse_launch(arguments=None):
    import argparse
    parser = argparse.ArgumentParser(description=APP_NAME)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--compress", action="store_true")
    group.add_argument("--extract", action="store_true")
    group.add_argument("--convert", action="store_true")
    group.add_argument("--photos", action="store_true")
    parser.add_argument("--register-shell", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--diagnostic", metavar="REPORT")
    parser.add_argument("--diagnostic-run", action="store_true")
    parser.add_argument("paths", nargs="*")
    args = parser.parse_args(arguments)
    mode = "photos" if args.photos else "convert" if args.convert else "extract" if args.extract else "compress"
    if not any((args.compress, args.extract, args.convert, args.photos)) and args.paths:
        if all(Path(value).is_file() and Path(value).suffix.lower() in photos.EXTENSIONS for value in args.paths):
            mode = "photos"
    if not any((args.compress, args.extract, args.convert, args.photos)) and len(args.paths) == 1:
        path = Path(args.paths[0])
        if path.is_file() and path.name.lower().endswith((".zip", ".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tar.xz")):
            mode = "extract"
    return args, (mode, args.paths)


def enable_dpi_awareness():
    if sys.platform == "win32":
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass


def main():
    args, launch = parse_launch()
    if args.register_shell:
        from windows_integration import register
        register()
        if not args.quiet:
            root = tk.Tk()
            root.withdraw()
            messagebox.showinfo("已加入", "Archive Studio 右鍵選單與開始功能表捷徑已加入。", parent=root)
            root.destroy()
        return
    enable_dpi_awareness()
    root = tk.Tk()
    icon = Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / "assets" / "studio.ico"
    if icon.exists():
        root.iconbitmap(str(icon))
    app = ArchiveApp(root, launch=launch, persist_preferences=not bool(args.diagnostic))
    if args.diagnostic:
        import json
        import time
        root.update()
        deadline = time.monotonic() + 30
        while app.photo_panel.loading and time.monotonic() < deadline:
            root.update()
            time.sleep(.01)
        if args.diagnostic_run:
            if app.mode == "photos":
                app.photo_panel.output.set(str(Path(args.diagnostic).parent / "converted"))
            app.start()
            while app.busy and time.monotonic() < deadline:
                root.update()
                time.sleep(.01)
        tree = app.photo_panel.tree if app.mode == "photos" else app.tree
        report = {"mode": app.mode, "paths": app.selections[app.mode],
                  "rows": [list(tree.item(i, "values")) for i in tree.get_children()],
                  "window": [root.winfo_width(), root.winfo_height()], "scale": app.scale,
                  "start_button_visible": bool(app.start_button.winfo_ismapped()),
                  "result": str(app.last_result.path) if app.last_result else None,
                  "files": app.last_result.files if app.last_result else 0,
                  "failures": getattr(app.last_result, "failures", 0),
                  "codecs": list(photos.available_formats())}
        Path(args.diagnostic).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        app.close()
        return
    root.mainloop()


if __name__ == "__main__":
    main()
