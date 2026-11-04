"""Photo workspace: batch queue, selected-image preview, presets, and per-file outcomes."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

import photo_engine as photos
from archive_engine import ArchiveError, Cancelled

PRESETS = {
    "自訂": None,
    "通用 JPG · 高畫質": ("JPG", 90, "保留原尺寸"),
    "網頁 WebP · 較小檔案": ("WebP", 80, "1920 px"),
    "PNG · 保留透明": ("PNG", 90, "保留原尺寸"),
    "分享 JPG · 長邊 1600": ("JPG", 82, "1600 px"),
}
SIZES = ("保留原尺寸", "3840 px", "2560 px", "1920 px", "1600 px", "1280 px", "自訂長邊")


def size_text(value):
    value = float(value)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return (str(int(value)) if unit == "B" else "%.1f" % value) + " " + unit
        value /= 1024


class PhotoPanel:
    def __init__(self, app, parent, persist=False):
        self.app, self.root = app, app.root
        self.sources = []
        self.loading = False
        self.alive = True
        self.result = None
        self.preview_data = None
        self.preview_version = 0
        self.preview_job = None
        self.preview_future = None
        self.preview_cancel = threading.Event()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="photo-preview")
        self.persist = persist
        self.preferences = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ArchiveStudio" / "photo-preferences.json"
        self.last_folder = str(Path.home() / "Pictures")
        self.output_chosen = False
        self.preset = tk.StringVar(value="通用 JPG · 高畫質")
        self.format = tk.StringVar(value="JPG")
        self.quality = tk.DoubleVar(value=90)
        self.resize = tk.StringVar(value="保留原尺寸")
        self.custom_edge = tk.StringVar(value="1920")
        self.metadata = tk.BooleanVar(value=False)
        self.background = tk.StringVar(value="白色背景")
        self.output = tk.StringVar(value=str(Path.home() / "Pictures" / "轉檔結果"))
        self.preview_choice = tk.StringVar(value="after")
        self._load_preferences()
        self.frame = tk.Frame(parent, bg=parent.cget("bg"))
        self.build()
        self.refresh_options(mark_custom=False)

    def _load_preferences(self):
        if not self.persist:
            return
        try:
            data = json.loads(self.preferences.read_text(encoding="utf-8"))
            if data.get("format") in photos.available_formats():
                self.format.set(data["format"])
            quality = data.get("quality", 90)
            if type(quality) is int and 1 <= quality <= 100:
                self.quality.set(quality)
            if data.get("resize") in SIZES:
                self.resize.set(data["resize"])
            edge = str(data.get("custom_edge", "1920"))
            if edge.isdigit() and 1 <= int(edge) <= 20000:
                self.custom_edge.set(edge)
            self.metadata.set(data.get("metadata") is True)
            if data.get("background") in ("白色背景", "黑色背景"):
                self.background.set(data["background"])
            if data.get("last_folder") and Path(data["last_folder"]).is_dir():
                self.last_folder = data["last_folder"]
            if data.get("output") and Path(data["output"]).is_dir():
                self.output.set(data["output"])
                self.output_chosen = True
            self.preset.set("自訂")
        except (OSError, ValueError, TypeError):
            pass

    def save_preferences(self):
        if not self.persist:
            return
        data = {"format": self.format.get(), "quality": round(self.quality.get()),
                "resize": self.resize.get(), "custom_edge": self.custom_edge.get(),
                "metadata": self.metadata.get(), "background": self.background.get(),
                "last_folder": self.last_folder, "output": self.output.get()}
        try:
            self.preferences.parent.mkdir(parents=True, exist_ok=True)
            self.preferences.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass

    def label(self, parent, text, size=13, **kwargs):
        return self.app.label(parent, text, size=size, **kwargs)

    def build(self):
        from photo_workspace import build_workspace
        build_workspace(self)

    def adapt_layout(self, compact):
        for widget in (self.queue_titlebar, self.count, self.note):
            if compact:
                widget.grid_remove()
            else:
                widget.grid()
        self.preview_info.grid()

    def options(self):
        value = self.resize.get()
        if value == "保留原尺寸":
            edge = 0
        elif value == "自訂長邊":
            try:
                edge = int(self.custom_edge.get())
            except ValueError as exc:
                raise ArchiveError("請輸入有效的最長邊像素。") from exc
            if not 1 <= edge <= 20000:
                raise ArchiveError("最長邊請輸入 1 到 20,000。")
        else:
            edge = int(value.split()[0])
        return photos.Options(self.format.get(), round(float(self.quality.get())), edge,
                              self.metadata.get(), "white" if self.background.get()=="白色背景" else "black")

    def quality_changed(self, value):
        self.quality_label.configure(text=str(round(float(value))))
        self.preset.set("自訂")
        self.schedule_preview()

    def apply_preset(self):
        values = PRESETS[self.preset.get()]
        if values:
            self.format.set(values[0])
            self.quality.set(values[1])
            self.resize.set(values[2])
            self.refresh_options(mark_custom=False)

    def refresh_options(self, mark_custom=True):
        if mark_custom:
            self.preset.set("自訂")
        lossy = self.format.get() in ("JPG", "WebP", "AVIF")
        self.quality_slider.configure(state="normal" if lossy and not self.app.busy else "disabled")
        self.quality_label.configure(text=str(round(self.quality.get())) if lossy else "無損")
        self.background_combo.configure(state="readonly" if self.format.get() in ("JPG","BMP") and not self.app.busy else "disabled")
        self.metadata_button.configure(state="normal" if self.format.get()!="BMP" and not self.app.busy else "disabled")
        if self.resize.get()=="自訂長邊":
            self.custom_frame.pack(side="right")
        else:
            self.custom_frame.pack_forget()
        self.note.configure(text="JPG／BMP 會套用背景色，原圖保留。"
                            if self.format.get() in ("JPG","BMP") else
                            "保留透明背景與來源資料夾結構。")
        self.schedule_preview()

    def choose_files(self):
        paths = filedialog.askopenfilenames(parent=self.root, title="加入要轉換的照片", initialdir=self.last_folder,
            filetypes=[("照片", "*.jpg *.jpeg *.jfif *.png *.webp *.heic *.heif *.avif *.bmp *.tif *.tiff *.gif"), ("所有檔案", "*")])
        if paths:
            self.add_paths(paths)

    def choose_folder(self):
        path = filedialog.askdirectory(parent=self.root, title="加入照片資料夾（含子資料夾）", initialdir=self.last_folder)
        if path:
            self.add_paths([path])

    def choose_output(self):
        path = filedialog.askdirectory(parent=self.root, title="選擇照片輸出位置")
        if path:
            self.output.set(path)
            self.output_chosen=True

    def add_paths(self, paths):
        if self.app.busy or self.loading or not paths:
            return
        self.loading=True
        self.app.start_button.configure(state="disabled")
        self.add_button.configure(state="disabled")
        self.folder_button.configure(state="disabled")
        self.count.configure(text="正在尋找照片…")
        inputs=list(paths)
        def worker():
            try:
                discovery=photos.discover(inputs)
                self.app.events.put(("photo_added", (discovery,inputs)))
            except Exception as exc:
                self.app.events.put(("photo_add_error",str(exc)))
        threading.Thread(target=worker,daemon=True).start()

    def handle_event(self, event, data):
        if not self.alive:
            return
        if event in ("photo_added","photo_add_error"):
            self.loading=False
            self.add_button.configure(state="normal")
            self.folder_button.configure(state="normal")
            self.app.update_start_state()
        if event=="photo_added":
            discovery,inputs=data
            known={os.path.normcase(str(s.path)) for s in self.sources}
            incoming = [source for source in discovery.sources if os.path.normcase(str(source.path)) not in known]
            if len(self.sources) + len(incoming) > photos.MAX_FILES:
                self.count.configure(text="照片數量超過上限，這次加入已取消。")
                messagebox.showerror("照片太多", "單批最多加入 10,000 張照片，請分批處理。", parent=self.root)
                return
            for source in discovery.sources:
                if os.path.normcase(str(source.path)) not in known:
                    self.sources.append(source)
                    known.add(os.path.normcase(str(source.path)))
            first=Path(inputs[0])
            self.last_folder=str(first if first.is_dir() else first.parent)
            if self.sources and not self.output_chosen:
                self.output.set(str(first.parent / "照片轉檔結果"))
            self.rebuild()
            if discovery.skipped:
                self.count.configure(text=self.count.cget("text")+" · 略過 %d 個非照片／連結"%discovery.skipped)
            if not discovery.sources:
                self.app.status.configure(text="這些項目裡沒有可加入的照片。",fg="#67768c")
            self.app.update_start_state()
        elif event=="photo_add_error":
            self.count.configure(text="加入失敗")
            messagebox.showerror("無法加入照片",data,parent=self.root)
        elif event=="photo_preview":
            generation,result,error=data
            if generation!=self.preview_version:
                if result:
                    result.before.close(); result.after.close()
                return
            if self.preview_data:
                self.preview_data.before.close(); self.preview_data.after.close()
            self.preview_data=result
            if error:
                self.preview_info.configure(text=error)
                self.render_preview()
            else:
                ow,oh=result.original_size; nw,nh=result.output_size
                self.preview_info.configure(text="原圖 %d × %d · %s\n輸出 %d × %d · 約 %s"%(ow,oh,size_text(result.input_bytes),nw,nh,size_text(result.output_bytes)))
                self.render_preview()
        elif event=="photo_item":
            index,item=data
            iid=str(index)
            if self.tree.exists(iid):
                status={"done":"完成 · "+size_text(item.output_bytes),"error":"失敗","cancelled":"已取消","pending":"尚未處理"}[item.status]
                values=list(self.tree.item(iid,"values")); values[2]=status
                self.tree.item(iid,values=values,tags=(item.status,))
                self.tree.see(iid)

    def rebuild(self):
        self.tree.delete(*self.tree.get_children())
        for index,source in enumerate(self.sources):
            try: size=size_text(source.path.stat().st_size)
            except OSError: size="無法讀取"
            self.tree.insert("","end",iid=str(index),values=(source.path.name,size,"待處理"),tags=("alternate",) if index%2 else ())
        self.app.selections["photos"]=[str(source.path) for source in self.sources]
        self.count.configure(text="%d 張照片"%len(self.sources))
        if self.sources:
            self.empty.place_forget()
            self.tree.selection_set("0")
            self.schedule_preview()
        else:
            self.empty.place(relx=.5,rely=.6,anchor="center")
            self.preview_version+=1
            if self.preview_data:
                self.preview_data.before.close(); self.preview_data.after.close()
                self.preview_data = None
            self.canvas.delete("all")
            self.preview_info.configure(text="選取一張照片即可預覽。")
            self.render_preview()
        self.app.update_start_state()

    def remove_selected(self):
        if self.app.busy or self.loading: return
        selected={int(i) for i in self.tree.selection()}
        self.sources=[s for i,s in enumerate(self.sources) if i not in selected]
        self.rebuild()

    def clear(self):
        if not self.app.busy and not self.loading:
            self.sources=[]
            self.rebuild()

    def select_all(self,event=None):
        self.tree.selection_set(self.tree.get_children())
        return "break"

    def schedule_preview(self):
        if not self.alive: return
        self.preview_cancel.set()
        self.preview_cancel = threading.Event()
        if self.preview_job:
            self.root.after_cancel(self.preview_job)
        self.preview_version+=1
        self.preview_job=self.root.after(300,self.start_preview)

    def start_preview(self):
        self.preview_job=None
        selected=self.tree.selection()
        if not selected or self.app.busy: return
        source=self.sources[int(selected[0])].path
        generation=self.preview_version
        cancel=self.preview_cancel
        try: options=self.options()
        except ArchiveError as exc:
            self.preview_info.configure(text=str(exc)); return
        self.preview_info.configure(text="正在產生轉檔預覽…")
        if self.preview_future:
            self.preview_future.cancel()
        def worker():
            try:
                result=photos.preview(source,options,cancel)
                self.app.events.put(("photo_preview",(generation,result,None)))
            except Exception as exc:
                self.app.events.put(("photo_preview",(generation,None,str(exc))))
        self.preview_future=self.executor.submit(worker)

    def render_preview(self):
        if not self.alive: return
        width, height = self.canvas.winfo_width(), self.canvas.winfo_height()
        self.preview_info.configure(wraplength=max(self.app.px(160),self.preview_frame.winfo_width()-self.app.px(28)))
        if not self.preview_data:
            self.canvas.delete("all")
            self.canvas.create_image(width/2,height/2-self.app.px(18),image=self.app.visuals.icon("photos",50,"#b3bed4"))
            self.canvas.create_text(width/2,height/2+self.app.px(27),text="選取照片，查看轉檔效果",fill="#8996ad",font=self.app.font(12))
            return
        image=self.preview_data.before if self.preview_choice.get()=="before" else self.preview_data.after
        thumb=image.copy()
        width=max(1,self.canvas.winfo_width()-self.app.px(12))
        height=max(1,self.canvas.winfo_height()-self.app.px(12))
        thumb.thumbnail((width,height),Image.Resampling.LANCZOS)
        self.tk_preview=ImageTk.PhotoImage(thumb,master=self.root)
        self.canvas.delete("all")
        if thumb.mode == "RGBA" and thumb.getextrema()[3][0] < 255:
            x0=(self.canvas.winfo_width()-thumb.width)/2
            y0=(self.canvas.winfo_height()-thumb.height)/2
            step=self.app.px(12)
            for y in range(0,thumb.height,step):
                for x in range(0,thumb.width,step):
                    self.canvas.create_rectangle(x0+x,y0+y,x0+min(x+step,thumb.width),y0+min(y+step,thumb.height),
                        fill="white" if ((x//step+y//step)%2==0) else "#e2e7f0",outline="")
        self.canvas.create_image(self.canvas.winfo_width()/2,self.canvas.winfo_height()/2,image=self.tk_preview)
        thumb.close()

    def set_busy(self,value):
        for widget in (self.add_button,self.folder_button,self.remove_button,self.clear_button,self.browse_button):
            widget.configure(state="disabled" if value else "normal")
        for widget in (self.preset_combo,self.format_combo,self.resize_combo):
            widget.configure(state="disabled" if value else "readonly")
        self.output_entry.configure(state="disabled" if value else "normal")
        self.custom_entry.configure(state="disabled" if value else "normal")
        self.refresh_options(mark_custom=False)

    def show_preview(self):
        if not self.preview_data:
            return
        win = tk.Toplevel(self.root)
        win.title("照片預覽 · 原圖與轉檔結果")
        p = self.app.px
        width = min(p(1060), self.root.winfo_screenwidth() - p(80))
        height = min(p(700), self.root.winfo_screenheight() - p(100))
        win.geometry("%dx%d" % (width, height))
        win.configure(bg="#f2f5fa")
        win.grid_rowconfigure(1, weight=1)
        for col in range(2):
            win.grid_columnconfigure(col, weight=1, uniform="preview")
        data = self.preview_data
        images = [data.before.copy(), data.after.copy()]
        original = "原圖 · %d × %d · %s" % (*data.original_size, size_text(data.input_bytes))
        converted = "轉檔預覽 · %d × %d · 約 %s" % (*data.output_size, size_text(data.output_bytes))
        canvases = []
        for index, title in enumerate((original, converted)):
            self.label(win, title, 13, bold=True).grid(row=0, column=index, sticky="ew", padx=p(14), pady=p(14))
            canvas = tk.Canvas(win, background="#e9ecf3", highlightthickness=0)
            canvas.grid(row=1, column=index, sticky="nsew", padx=p(10), pady=(0, p(14)))
            canvases.append(canvas)
        references = {}
        def render(event=None):
            for index, canvas in enumerate(canvases):
                thumb = images[index].copy()
                thumb.thumbnail((max(1,canvas.winfo_width()-p(15)),max(1,canvas.winfo_height()-p(15))), Image.Resampling.LANCZOS)
                references[index] = ImageTk.PhotoImage(thumb, master=win)
                canvas.delete("all")
                canvas.create_image(canvas.winfo_width()/2,canvas.winfo_height()/2,image=references[index])
                thumb.close()
        for canvas in canvases:
            canvas.bind("<Configure>", render)
        def close():
            for image in images:
                image.close()
            win.destroy()
        win.protocol("WM_DELETE_WINDOW", close)

    def start(self):
        if self.loading or not self.sources: return
        try:
            options=self.options(); options.validate()
            if not self.output.get().strip(): raise ArchiveError("請選擇照片儲存位置。")
        except ArchiveError as exc:
            messagebox.showerror("請檢查照片設定",str(exc),parent=self.root); return
        sources=tuple(self.sources); output=self.output.get()
        self.preview_version += 1
        self.preview_cancel.set()
        if self.preview_future:
            self.preview_future.cancel()
        self.result=None
        self.app.last_result=None
        self.app.open_button.configure(state="disabled")
        self.app.result_button.configure(state="disabled")
        for iid in self.tree.get_children():
            values=list(self.tree.item(iid,"values")); values[2]="待處理"
            self.tree.item(iid,values=values,tags=())
        self.app.cancel.clear()
        self.app.progress["value"]=0
        self.app.percent.configure(text="0%")
        self.app.status.configure(text="正在轉換照片…",fg="#20263a")
        self.app.detail.configure(text="完成的照片會保留；取消後可查看逐張結果。")
        self.save_preferences()
        self.app.set_busy(True)
        def worker():
            try:
                result=photos.convert_batch(sources,output,options,
                    progress=lambda *data:self.app.events.put(("progress",data)),
                    item_callback=lambda *data:self.app.events.put(("photo_item",data)),
                    cancel=self.app.cancel)
                self.app.events.put(("done",result))
            except Cancelled as exc:
                self.app.events.put(("cancelled",str(exc)))
            except Exception as exc:
                self.app.events.put(("error",str(exc)))
        threading.Thread(target=worker,daemon=True).start()

    def finish(self,result):
        self.result=result
        if result.cancelled:
            text="已取消 · 完成 %d 張，失敗 %d 張"%(result.files,result.failures)
            color="#67768c"
        else:
            text="完成 %d 張照片"%result.files
            if result.failures: text+=" · %d 張失敗（查看結果）"%result.failures
            color="#267862" if not result.failures else "#b64c58"
        self.app.status.configure(text=text,fg=color)
        self.app.detail.configure(text="%s → %s · %.1f 秒 · 原始照片保留"%(size_text(result.original_bytes),size_text(result.output_bytes),result.seconds))
        self.app.percent.configure(text="已取消" if result.cancelled else "100%")
        self.app.progress["value"]=100 if not result.cancelled else self.app.progress["value"]
        self.app.result_button.configure(state="normal")

    def show_results(self):
        if not self.result: return
        win=tk.Toplevel(self.root)
        win.title("照片轉檔結果")
        win.geometry("%dx%d"%(self.app.px(800),self.app.px(440)))
        win.configure(bg="#f2f5fa")
        rows=tk.Frame(win,bg="#f2f5fa")
        rows.pack(fill="both",expand=True,padx=self.app.px(14),pady=self.app.px(14))
        tree=ttk.Treeview(rows,columns=("source","status","detail"),show="headings")
        for key,title,width in (("source","照片",230),("status","結果",80),("detail","輸出檔案／原因",440)):
            tree.heading(key,text=title); tree.column(key,width=self.app.px(width),minwidth=self.app.px(60))
        scroll=ttk.Scrollbar(rows,orient="vertical",command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.pack(side="left",fill="both",expand=True)
        scroll.pack(side="right",fill="y")
        for index,item in enumerate(self.result.items):
            status={"done":"完成","error":"失敗","cancelled":"已取消","pending":"尚未處理"}[item.status]
            detail=str(item.output) if item.status=="done" else item.message
            tree.insert("","end",iid=str(index),values=(item.source.name,status,detail))
        detail=tk.Text(win,height=3,wrap="word",font=self.app.font(12),relief="flat")
        detail.pack(fill="x",padx=self.app.px(14),pady=(0,self.app.px(12)))
        def select(event=None):
            selected=tree.selection()
            if selected:
                item=self.result.items[int(selected[0])]
                detail.delete("1.0","end"); detail.insert("1.0",str(item.source)+"\n"+(str(item.output) if item.output else item.message))
        tree.bind("<<TreeviewSelect>>",select)
        def open_selected(event=None):
            selected=tree.selection()
            if selected:
                item=self.result.items[int(selected[0])]
                if item.status=="done" and item.output:
                    try: os.startfile(str(item.output))
                    except OSError as exc: messagebox.showerror("無法開啟照片",str(exc),parent=win)
        tree.bind("<Double-1>",open_selected)

    def close(self):
        self.alive=False
        self.preview_cancel.set()
        if self.preview_job:
            self.root.after_cancel(self.preview_job)
            self.preview_job=None
        if self.preview_future: self.preview_future.cancel()
        self.executor.shutdown(wait=False,cancel_futures=True)
        self.save_preferences()
        if self.preview_data:
            self.preview_data.before.close(); self.preview_data.after.close()
