"""Photo workspace layout. Conversion and queue behavior live in photo_panel."""
import tkinter as tk
from tkinter import ttk

from visual_theme import Card, INK, MUTED, ACCENT, LINE, SOFT, STAGE
import photo_engine as photos


def build_workspace(self):
    from photo_panel import PRESETS, SIZES
    app, p = self.app, self.app.px
    self.frame.grid_columnconfigure(0, weight=3, minsize=p(440))
    self.frame.grid_columnconfigure(1, weight=2, minsize=p(265))
    self.frame.grid_rowconfigure(0, weight=1)

    queue_card = Card(self.frame,p)
    queue_card.grid(row=0,column=0,sticky="nsew",pady=(0,p(10)))
    queue = queue_card.content
    queue.grid_columnconfigure(0,weight=1)
    queue.grid_rowconfigure(2,weight=1)
    self.queue_titlebar = tk.Frame(queue,bg="white")
    self.queue_titlebar.grid(row=0,column=0,sticky="ew",padx=p(10),pady=(p(5),p(8)))
    self.label(self.queue_titlebar,"照片清單",14,bold=True).pack(side="left")
    self.label(self.queue_titlebar,"支援拖放與整個資料夾",11,color=MUTED).pack(side="right")
    toolbar = tk.Frame(queue,bg="white")
    toolbar.grid(row=1,column=0,sticky="ew",padx=p(10),pady=(0,p(8)))
    self.add_button = ttk.Button(toolbar,text="加入照片",style="Secondary.TButton",
        image=app.visuals.icon("add",16),compound="left",command=self.choose_files)
    self.add_button.pack(side="left")
    self.folder_button = ttk.Button(toolbar,text="資料夾",image=app.visuals.icon("folder",16,MUTED),
        compound="left",command=self.choose_folder)
    self.folder_button.pack(side="left",padx=(p(6),0))
    self.remove_button = ttk.Button(toolbar,text="移出",style="Quiet.TButton",command=self.remove_selected)
    self.remove_button.pack(side="right")
    self.clear_button = ttk.Button(toolbar,text="清空",style="Quiet.TButton",command=self.clear)
    self.clear_button.pack(side="right",padx=(0,p(4)))

    queue_frame = tk.Frame(queue,bg="white")
    queue_frame.grid(row=2,column=0,sticky="nsew",padx=p(10))
    self.tree = ttk.Treeview(queue_frame,columns=("name","bytes","status"),show="headings",height=5,selectmode="extended")
    for key,title in (("name","照片名稱"),("bytes","原始大小"),("status","狀態")):
        self.tree.heading(key,text=title,anchor="w")
    self.tree.column("name",width=p(250),minwidth=p(100))
    self.tree.column("bytes",width=p(80),minwidth=p(65),stretch=False)
    self.tree.column("status",width=p(105),minwidth=p(80),stretch=False)
    self.tree.tag_configure("alternate",background="#fafbfe")
    self.tree.tag_configure("done",foreground="#16836c")
    self.tree.tag_configure("error",foreground="#b64c58")
    scroll = ttk.Scrollbar(queue_frame,orient="vertical",command=self.tree.yview)
    self.tree.configure(yscrollcommand=scroll.set)
    self.tree.pack(side="left",fill="both",expand=True)
    scroll.pack(side="right",fill="y")
    self.tree.bind("<<TreeviewSelect>>",lambda event:self.schedule_preview())
    self.tree.bind("<Delete>",lambda event:self.remove_selected())
    self.tree.bind("<Control-a>",self.select_all)
    self.empty = tk.Label(queue_frame,text="拖入照片，開始轉檔\n或使用上方按鈕加入",image=app.visuals.icon("photos",38,"#a5b0d0"),
        compound="top",bg="white",fg=MUTED,font=app.font(13),justify="center",pady=p(7))
    self.empty.place(relx=.5,rely=.6,anchor="center")
    def size_empty(event=None):
        self.empty.configure(image="" if queue_frame.winfo_height()<p(150) else app.visuals.icon("photos",38,"#a5b0d0"))
    queue_frame.bind("<Configure>",size_empty)
    self.count = self.label(queue,"尚未加入照片",11,color=MUTED)
    self.count.grid(row=3,column=0,sticky="ew",padx=p(10),pady=(p(7),p(5)))

    settings_card = Card(self.frame,p)
    settings_card.grid(row=1,column=0,sticky="ew",pady=(0,p(10)))
    settings = settings_card.content
    settings.grid_columnconfigure(0,weight=1)
    top = tk.Frame(settings,bg="white")
    top.grid(row=0,column=0,sticky="ew",padx=p(10),pady=(p(5),p(8)))
    self.label(top,"輸出設定",14,bold=True).pack(side="left")
    self.preset_combo = ttk.Combobox(top,textvariable=self.preset,values=list(PRESETS),width=22,
        state="readonly",font=app.font(12))
    self.preset_combo.pack(side="right")
    self.preset_combo.bind("<<ComboboxSelected>>",lambda event:self.apply_preset())
    fields = tk.Frame(settings,bg="white")
    fields.grid(row=1,column=0,sticky="ew",padx=p(10))
    fields.grid_columnconfigure(0,weight=1,uniform="fields")
    fields.grid_columnconfigure(1,weight=1,uniform="fields")
    for row,col,title in ((0,0,"輸出格式"),(0,1,"照片品質"),(2,0,"最長邊（保持比例）"),(2,1,"透明區域背景")):
        self.label(fields,title,11,color=MUTED).grid(row=row,column=col,sticky="w",pady=(p(7) if row else 0,p(4)))
    self.format_combo = ttk.Combobox(fields,textvariable=self.format,values=photos.available_formats(),
        state="readonly",width=8,font=app.font(13))
    self.format_combo.grid(row=1,column=0,sticky="ew",padx=(0,p(10)))
    self.format_combo.bind("<<ComboboxSelected>>",lambda event:self.refresh_options())
    quality = tk.Frame(fields,bg="white")
    quality.grid(row=1,column=1,sticky="ew")
    quality.grid_columnconfigure(0,weight=1)
    self.quality_slider = ttk.Scale(quality,from_=1,to=100,variable=self.quality,
        command=lambda value:self.quality_changed(value))
    self.quality_slider.grid(row=0,column=0,sticky="ew")
    self.quality_label = self.label(quality,"90",13,color=ACCENT,bold=True)
    self.quality_label.grid(row=0,column=1,padx=(p(8),0))
    self.resize_combo = ttk.Combobox(fields,textvariable=self.resize,values=SIZES,state="readonly",width=16,font=app.font(13))
    self.resize_combo.grid(row=3,column=0,sticky="ew",padx=(0,p(10)))
    self.resize_combo.bind("<<ComboboxSelected>>",lambda event:self.refresh_options())
    self.background_combo = ttk.Combobox(fields,textvariable=self.background,values=("白色背景","黑色背景"),
        state="readonly",width=12,font=app.font(13))
    self.background_combo.grid(row=3,column=1,sticky="ew")
    self.background_combo.bind("<<ComboboxSelected>>",lambda event:self.refresh_options())
    extras = tk.Frame(settings,bg="white")
    extras.grid(row=2,column=0,sticky="ew",padx=p(10),pady=(p(7),p(6)))
    self.metadata_button = ttk.Checkbutton(extras,text="保留拍攝資訊（含位置）",variable=self.metadata,command=self.refresh_options)
    self.metadata_button.pack(side="left")
    self.custom_frame = tk.Frame(extras,bg="white")
    self.label(self.custom_frame,"長邊",11).pack(side="left")
    self.custom_entry = ttk.Entry(self.custom_frame,textvariable=self.custom_edge,width=6,font=app.font(12))
    self.custom_entry.pack(side="left",padx=p(4))
    self.label(self.custom_frame,"px",11).pack(side="left")
    self.custom_entry.bind("<KeyRelease>",lambda event:self.schedule_preview())
    self.note = self.label(settings,"",11,color=MUTED)
    self.note.grid(row=3,column=0,sticky="ew",padx=p(10),pady=(0,p(6)))
    destination = tk.Frame(settings,bg="white")
    destination.grid(row=4,column=0,sticky="ew",padx=p(10),pady=(0,p(5)))
    destination.grid_columnconfigure(1,weight=1)
    self.label(destination,"儲存至",11,color=MUTED).grid(row=0,column=0,padx=(0,p(7)))
    self.output_entry = ttk.Entry(destination,textvariable=self.output,font=app.font(12),width=16)
    self.output_entry.grid(row=0,column=1,sticky="ew")
    self.output_entry.bind("<KeyRelease>",lambda event:setattr(self,"output_chosen",True))
    self.browse_button = ttk.Button(destination,text="瀏覽",command=self.choose_output,style="Small.TButton")
    self.browse_button.grid(row=0,column=2,padx=(p(6),0))

    preview_card = Card(self.frame,p)
    preview_card.grid(row=0,column=1,rowspan=2,sticky="nsew",padx=(p(12),0),pady=(0,p(10)))
    self.preview_frame = preview_card.content
    self.preview_frame.grid_columnconfigure(0,weight=1)
    self.preview_frame.grid_rowconfigure(2,weight=1)
    title = tk.Frame(self.preview_frame,bg="white")
    title.grid(row=0,column=0,sticky="ew",padx=p(10),pady=(p(5),p(8)))
    self.label(title,"照片預覽",14,bold=True).pack(side="left")
    self.zoom_button = ttk.Button(title,text="放大",command=self.show_preview,width=4,style="Small.TButton")
    self.zoom_button.pack(side="right")
    toggles = tk.Frame(self.preview_frame,bg="white")
    toggles.grid(row=1,column=0,sticky="ew",padx=p(10),pady=(0,p(8)))
    self.before_button = ttk.Radiobutton(toggles,text="原圖",value="before",variable=self.preview_choice,command=self.render_preview)
    self.before_button.pack(side="left")
    self.after_button = ttk.Radiobutton(toggles,text="轉檔結果",value="after",variable=self.preview_choice,command=self.render_preview)
    self.after_button.pack(side="left",padx=(p(12),0))
    self.canvas = tk.Canvas(self.preview_frame,bg=STAGE,highlightthickness=0,bd=0,width=1,height=1)
    self.canvas.grid(row=2,column=0,sticky="nsew",padx=p(8))
    self.canvas.bind("<Configure>",lambda event:self.render_preview())
    self.canvas.bind("<Double-1>",lambda event:self.show_preview())
    self.preview_info = self.label(self.preview_frame,"選取一張照片，查看轉檔效果。",12,color=MUTED,wraplength=p(290),justify="left")
    self.preview_info.grid(row=3,column=0,sticky="ew",padx=p(10),pady=p(10))
