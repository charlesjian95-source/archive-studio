"""Code-native desktop visuals shared by the archive and photo workspaces."""
import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageDraw, ImageTk

BG = "#f2f5fa"
INK = "#182338"
MUTED = "#67768c"
ACCENT = "#4f46e5"
LINE = "#e2e8f0"
SOFT = "#eef0ff"
NAV = "#e8edf5"
STAGE = "#f5f7fb"


class Card(tk.Frame):
    """A rounded surface with an ordinary Tk frame for its contents."""
    def __init__(self, parent, px, color="white", outline=LINE, radius=14, inset=7, **kwargs):
        super().__init__(parent, bg=parent.cget("bg"), bd=0, highlightthickness=0, **kwargs)
        self.color, self.outline, self.radius = color, outline, px(radius)
        self.canvas = tk.Canvas(self, bg=parent.cget("bg"), highlightthickness=0, bd=0)
        self.canvas.place(x=0, y=0, relwidth=1, relheight=1)
        self.content = tk.Frame(self, bg=color, bd=0)
        self.content.pack(fill="both", expand=True, padx=px(inset), pady=px(inset))
        self.bind("<Configure>", self.paint, add="+")

    def paint(self, event=None):
        w, h, r = self.winfo_width()-1, self.winfo_height()-1, self.radius
        r = min(r, max(1,w//2), max(1,h//2))
        points = (r,1,w-r,1,w,1,w,r,w,h-r,w,h,w-r,h,r,h,1,h,1,h-r,1,r,1,1)
        self.canvas.delete("surface")
        self.canvas.create_polygon(points, smooth=True, splinesteps=24, fill=self.color,
                                   outline=self.outline, width=1, tags="surface")
        self.canvas.tk.call("lower", self.canvas._w)


class Visuals:
    def __init__(self, app):
        self.app, self.root, self.px = app, app.root, app.px
        self.images = {}

    def icon(self, name, size=20, color=ACCENT):
        key = (name, size, color)
        if key in self.images:
            return self.images[key]
        side = self.px(size)
        factor = 3
        image = Image.new("RGBA", (side*factor, side*factor))
        draw = ImageDraw.Draw(image)
        u = side*factor/24
        def box(points): return tuple(round(v*u) for v in points)
        line = max(2, round(1.6*u))
        if name == "brand":
            draw.rounded_rectangle(box((0,0,24,24)), radius=round(6*u), fill=ACCENT)
            draw.rounded_rectangle(box((6,5,18,20)), radius=round(2*u), outline="white", width=line)
            draw.line(box((12,5,12,15)), fill="#c7d2fe", width=line)
            for y in (7,10,13):
                draw.line(box((10.5,y,13.5,y)), fill="white", width=max(1,round(u)))
            draw.rounded_rectangle(box((10,15,14,18)), radius=round(u), fill="white")
        elif name in ("compress", "extract"):
            draw.rounded_rectangle(box((4,4,20,20)), radius=round(3*u), outline=color, width=line)
            draw.line(box((4,9,20,9)), fill=color, width=line)
            if name == "compress":
                draw.line(box((12,12,12,18)), fill=color, width=line)
                draw.line(box((9,15,12,18,15,15)), fill=color, width=line, joint="curve")
            else:
                draw.line(box((12,18,12,12)), fill=color, width=line)
                draw.line(box((9,15,12,12,15,15)), fill=color, width=line, joint="curve")
        elif name == "convert":
            draw.line(box((4,8,19,8,16,5)), fill=color, width=line, joint="curve")
            draw.line(box((20,16,5,16,8,19)), fill=color, width=line, joint="curve")
        elif name == "photos":
            draw.rounded_rectangle(box((3,4,21,20)), radius=round(3*u), outline=color, width=line)
            draw.ellipse(box((6,7,10,11)), fill=color)
            draw.line(box((4,17,10,12,14,16,17,13,21,17)), fill=color, width=line, joint="curve")
        elif name == "folder":
            draw.line(box((3,8,3,5,10,5,13,8,21,8,21,20,3,20,3,8,21,8)), fill=color, width=line, joint="curve")
        elif name == "add":
            draw.line(box((12,5,12,19)), fill=color, width=line)
            draw.line(box((5,12,19,12)), fill=color, width=line)
        elif name == "settings":
            for y, x in ((6,9),(12,16),(18,7)):
                draw.line(box((3,y,21,y)), fill=color, width=line)
                draw.ellipse(box((x-2,y-2,x+2,y+2)), fill=BG, outline=color, width=max(1,round(u)))
        elif name == "open":
            draw.line(box((13,4,21,4,21,12)), fill=color, width=line)
            draw.line(box((21,4,11,14)), fill=color, width=line)
            draw.line(box((9,5,4,5,4,20,19,20,19,15)), fill=color, width=line, joint="curve")
        image = image.resize((side,side), Image.Resampling.LANCZOS)
        result = ImageTk.PhotoImage(image, master=self.root)
        self.images[key] = result
        return result

    def apply(self):
        app, p = self.app, self.px
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(".", font=app.font(), background=BG, foreground=INK)
        style.configure("TCheckbutton", background="white", foreground=MUTED, padding=0)
        style.map("TCheckbutton", background=[("active","white")], foreground=[("disabled","#9aa5b5")])
        style.configure("TRadiobutton", background="white", foreground=MUTED, padding=(p(2),p(3)))
        style.map("TRadiobutton", background=[("active","white")], foreground=[("selected",ACCENT)])

        def skin(name, fill, hover, text, outline=None, padding=(12,8), disabled="#edf0f5"):
            states = []
            for variant, color, edge in (("normal",fill,outline),("hover",hover,outline),
                                         ("pressed",hover,outline),("disabled",disabled,None),
                                         ("focus",fill,ACCENT)):
                side = p(42)
                im = Image.new("RGBA", (side*3,side*3))
                d = ImageDraw.Draw(im)
                d.rounded_rectangle((1,1,side*3-2,side*3-2), radius=p(7)*3, fill=color,
                                    outline=edge, width=3 if edge else 1)
                im = im.resize((side,side),Image.Resampling.LANCZOS)
                photo = ImageTk.PhotoImage(im,master=self.root)
                self.images[(name,variant)] = photo
                states.append(photo)
            element = "Studio."+name
            style.element_create(element,"image",states[0],("disabled",states[3]),
                ("pressed",states[2]),("active",states[1]),("focus",states[4]),border=p(7),padding=0,width=0,height=0,sticky="nsew")
            style.layout(name,[(element,{"sticky":"nsew","children":[("Button.padding",{
                "sticky":"nsew","children":[("Button.label",{"sticky":"nsew"})]})]})])
            style.configure(name,font=app.font(13),foreground=text,padding=(p(padding[0]),p(padding[1])),
                            background="white",borderwidth=0,anchor="center")
            style.map(name,foreground=[("disabled","#9ca7b6")])

        skin("TButton","white","#f5f6fe",INK,LINE)
        skin("Primary.TButton",ACCENT,"#4338ca","white",padding=(23,11),disabled="#b8b9e6")
        style.configure("Primary.TButton",font=app.font(14,True))
        style.map("Primary.TButton",foreground=[("disabled","white")])
        skin("Secondary.TButton",SOFT,"#e1e5ff",ACCENT,padding=(12,8))
        skin("Quiet.TButton","white","#f0f3f8",MUTED,padding=(9,8))
        skin("Ghost.TButton",BG,"#e8edf5",MUTED,padding=(9,8))
        skin("Footer.TButton",BG,"#e8edf5",INK,LINE,padding=(12,8))
        style.configure("Footer.TButton",background=BG)
        style.configure("Ghost.TButton",background=BG)
        style.configure("Primary.TButton",background=BG)
        skin("Small.TButton","white",SOFT,ACCENT,LINE,padding=(9,5))
        skin("Mode.TButton",NAV,"#f5f7fb",MUTED,padding=(12,9),disabled=NAV)
        skin("Selected.Mode.TButton","white","white",ACCENT,"#d9dff4",padding=(12,9))
        style.configure("Selected.Mode.TButton",font=app.font(13,True))
        style.configure("Mode.TButton",background=NAV)
        style.configure("Selected.Mode.TButton",background=NAV)

        # Input fields keep native editing and dropdown behavior, with softer borders.
        style.configure("TEntry",fieldbackground="#fafbfe",foreground=INK,padding=(p(10),p(7)),
                        bordercolor=LINE,lightcolor=LINE,darkcolor=LINE,insertcolor=ACCENT)
        style.map("TEntry",bordercolor=[("focus",ACCENT)],fieldbackground=[("disabled","#f0f3f7")])
        style.configure("TCombobox",fieldbackground="#fafbfe",foreground=INK,padding=(p(9),p(7)),
                        bordercolor=LINE,lightcolor=LINE,darkcolor=LINE,background="#fafbfe",arrowsize=p(12))
        style.map("TCombobox",fieldbackground=[("readonly","#fafbfe"),("disabled","#f0f3f7")],
                  foreground=[("readonly",INK),("disabled","#9aa5b5")],bordercolor=[("focus",ACCENT)])
        self.root.option_add("*TCombobox*Listbox.font",app.font(13))
        self.root.option_add("*TCombobox*Listbox.selectBackground",SOFT)
        self.root.option_add("*TCombobox*Listbox.selectForeground",ACCENT)
        style.configure("Treeview",background="white",fieldbackground="white",font=app.font(13),
                        rowheight=p(36),borderwidth=0,foreground=INK)
        style.layout("Treeview",[("Treeview.treearea",{"sticky":"nsew"})])
        style.configure("Treeview.Heading",background="#f7f9fc",foreground=MUTED,
                        font=app.font(12,True),padding=(p(10),p(7)),borderwidth=0,relief="flat")
        style.layout("Treeview.Heading",[("Treeheading.padding",{"sticky":"nsew","children":[
            ("Treeheading.text",{"sticky":"we"})]})])
        style.map("Treeview",background=[("selected",SOFT)],foreground=[("selected",ACCENT)])
        style.configure("Vertical.TScrollbar",arrowsize=p(10),width=p(10),borderwidth=0,
                        background="#d6deea",troughcolor="white",lightcolor="white",darkcolor="white")
        style.configure("Horizontal.TProgressbar",background=ACCENT,troughcolor="#e9edf5",
                        borderwidth=0,thickness=p(4),lightcolor=ACCENT,darkcolor=ACCENT)
        style.configure("Horizontal.TScale",background="white",troughcolor="#e8ecf5",
                        sliderlength=p(14),sliderrelief="flat",borderwidth=0)
