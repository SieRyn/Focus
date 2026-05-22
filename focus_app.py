#!/usr/bin/env python3
"""Focus — Goals & Habits Tracker  v4.0.0"""

import tkinter as tk
from tkinter import font as tkfont, colorchooser, ttk, messagebox
import json, sys, calendar, time, threading, subprocess, os, signal
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

# ── Version & Paths ───────────────────────────────────────────────────────────
VERSION = "4.0.0"
if getattr(sys, 'frozen', False): BASE_DIR = Path(sys.executable).parent
else:                              BASE_DIR = Path(__file__).parent
DATA_FILE    = BASE_DIR / "focus_data.json"
CONFIG_FILE  = BASE_DIR / "focus_config.json"
UPDATE_SCRIPT= BASE_DIR / "focus_app.py"

DEFAULT_SYSTEM_PROMPT = (
    "You are a personal productivity and wellbeing coach inside the Focus app. "
    "You have access to the user's real data below. Be concise, insightful, and actionable. "
    "Speak directly. Do not use excessive bullet points. Reference their actual data when relevant."
)

def load_config():
    d = {"update_url":"","version_url":"","ollama_model":"llama3.2",
         "ollama_path":"","system_prompt":DEFAULT_SYSTEM_PROMPT}
    if CONFIG_FILE.exists():
        try: d.update(json.loads(CONFIG_FILE.read_text(encoding="utf-8")))
        except: pass
    return d

def save_config(c): CONFIG_FILE.write_text(json.dumps(c,indent=2),encoding="utf-8")

def load():
    if DATA_FILE.exists():
        try: return json.loads(DATA_FILE.read_text(encoding="utf-8"))
        except: pass
    return {"long":[],"monthly":[],"weekly":[],"habits":[],"checks":{},
            "graphs":[],"metrics":[],"events":[]}

def save_data(d): DATA_FILE.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding="utf-8")

# ── Palette ───────────────────────────────────────────────────────────────────
BG="#F5F2EB"; SURF="#FAFAF7"; SURF2="#EFECE4"
INK="#0F0F0E"; INK2="#3A3935"; INK3="#6B6860"; INK4="#A8A59F"
STREAK="#C8A96E"; GREEN="#5A7A5A"; NAVY="#4A6A8A"
PRESET_COLORS=["#0F0F0E","#C8A96E","#5A7A5A","#7A5A5A","#4A6A8A","#8A5A7A","#5A8A7A","#A87A4A"]

# ══════════════════════════════════════════════════════════════════════════════
# OLLAMA
# ══════════════════════════════════════════════════════════════════════════════
class OllamaManager:
    def __init__(self,cfg):
        self.cfg=cfg; self._proc=None
        self._model=cfg.get("ollama_model","llama3.2")
        self._base="http://localhost:11434"; self.status="stopped"

    def _find_ollama(self):
        custom=self.cfg.get("ollama_path","").strip()
        if custom and Path(custom).exists(): return custom
        for c in [r"C:\Users\{}\AppData\Local\Programs\Ollama\ollama.exe".format(os.environ.get("USERNAME","")),
                  r"C:\Program Files\Ollama\ollama.exe","ollama"]:
            try: subprocess.run([c,"--version"],capture_output=True,timeout=3); return c
            except: pass
        return None

    def _already_running(self):
        try: urllib.request.urlopen(f"{self._base}/api/tags",timeout=2); return True
        except: return False

    def start(self,on_ready=None,on_error=None):
        def _run():
            if self._already_running():
                self.status="ready"
                if on_ready: on_ready(); return
            exe=self._find_ollama()
            if not exe:
                self.status="no_ollama"
                if on_error: on_error("Ollama not found. Download from ollama.com"); return
            self.status="starting"
            try:
                kw=dict(stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                if sys.platform=="win32": kw["creationflags"]=subprocess.CREATE_NO_WINDOW
                self._proc=subprocess.Popen([exe,"serve"],**kw)
            except Exception as e:
                self.status="error"
                if on_error: on_error(str(e)); return
            for _ in range(40):
                time.sleep(0.5)
                if self._already_running():
                    self.status="ready"
                    if on_ready: on_ready(); return
            self.status="error"
            if on_error: on_error("Ollama started but didn't respond.")
        threading.Thread(target=_run,daemon=True).start()

    def stop(self):
        if self._proc:
            try:
                if sys.platform=="win32": self._proc.terminate()
                else: self._proc.send_signal(signal.SIGTERM)
                self._proc.wait(timeout=5)
            except: pass
            self._proc=None
        self.status="stopped"

    def list_models(self):
        try:
            with urllib.request.urlopen(f"{self._base}/api/tags",timeout=5) as r:
                return [m["name"] for m in json.loads(r.read()).get("models",[])]
        except: return []

    def chat(self,messages,on_token=None,on_done=None,on_error=None):
        model=self._model
        def _run():
            payload=json.dumps({"model":model,"messages":messages,"stream":True}).encode()
            try:
                req=urllib.request.Request(f"{self._base}/api/chat",data=payload,
                                           headers={"Content-Type":"application/json"})
                full=""
                with urllib.request.urlopen(req,timeout=120) as resp:
                    for raw in resp:
                        line=raw.decode().strip()
                        if not line: continue
                        try:
                            obj=json.loads(line); tok=obj.get("message",{}).get("content","")
                            if tok:
                                full+=tok
                                if on_token: on_token(tok)
                            if obj.get("done"):
                                if on_done: on_done(full); return
                        except: pass
            except Exception as e:
                if on_error: on_error(str(e))
        threading.Thread(target=_run,daemon=True).start()

# ══════════════════════════════════════════════════════════════════════════════
# UPDATER
# ══════════════════════════════════════════════════════════════════════════════
class Updater:
    def __init__(self,cfg): self.cfg=cfg
    def check(self,callback):
        url=self.cfg.get("version_url","").strip()
        if not url: callback(None); return
        def _run():
            try:
                with urllib.request.urlopen(url,timeout=8) as r: remote=r.read().decode().strip()
                callback(remote if self._newer(remote,VERSION) else None)
            except: callback(None)
        threading.Thread(target=_run,daemon=True).start()
    def apply(self,on_done,on_error):
        url=self.cfg.get("update_url","").strip()
        if not url: on_error("No update URL configured."); return
        def _run():
            try:
                with urllib.request.urlopen(url,timeout=30) as r: new=r.read()
                tmp=UPDATE_SCRIPT.with_suffix(".tmp"); tmp.write_bytes(new); tmp.replace(UPDATE_SCRIPT)
                on_done()
            except Exception as e: on_error(str(e))
        threading.Thread(target=_run,daemon=True).start()
    @staticmethod
    def _newer(r,l):
        def p(v): return [int(x) for x in v.strip().split(".")]
        try: return p(r)>p(l)
        except: return False

# ══════════════════════════════════════════════════════════════════════════════
# SPLASH
# ══════════════════════════════════════════════════════════════════════════════
class SplashScreen(tk.Toplevel):
    def __init__(self,parent,on_done):
        super().__init__(parent); self.on_done=on_done
        self.overrideredirect(True)
        sw=self.winfo_screenwidth(); sh=self.winfo_screenheight()
        W,H=520,300; self.geometry(f"{W}x{H}+{(sw-W)//2}+{(sh-H)//2}")
        self.configure(bg=INK); self.lift(); self.attributes("-topmost",True)
        border=tk.Frame(self,bg=INK3,padx=1,pady=1); border.place(relx=0,rely=0,relwidth=1,relheight=1)
        inner=tk.Frame(border,bg=INK); inner.place(relx=0,rely=0,relwidth=1,relheight=1)
        self._c=tk.Canvas(inner,bg=INK,highlightthickness=0); self._c.place(relx=0,rely=0,relwidth=1,relheight=1)
        self._ft=tkfont.Font(family="Georgia",size=13,slant="italic")
        self._fm=tkfont.Font(family="Georgia",size=28)
        self._fs=tkfont.Font(family="Consolas",size=9)
        self._fd=tkfont.Font(family="Consolas",size=8)
        cx=260
        self._c.create_line(cx-60,60,cx+60,60,fill=INK3,width=1)
        self._c.create_text(cx,90,text="FOCUS",font=self._fm,fill=BG,anchor="center")
        self._c.create_line(cx-60,120,cx+60,120,fill=INK3,width=1)
        self._greeting="Welcome back, sir."
        self._tid=self._c.create_text(cx,165,text="",font=self._ft,fill=INK4,anchor="center")
        self._c.create_text(cx,200,text=date.today().strftime("%A  ·  %B %d, %Y").upper(),font=self._fd,fill=INK3,anchor="center")
        self._did=self._c.create_text(cx,234,text="",font=self._fs,fill=INK3,anchor="center")
        self._c.create_text(cx,274,text=f"v{VERSION}",font=self._fd,fill=INK3,anchor="center")
        self._bbg=self._c.create_rectangle(cx-120,252,cx+120,255,fill=INK2,outline="")
        self._bfg=self._c.create_rectangle(cx-120,252,cx-120,255,fill=INK4,outline="")
        self._ci=0; self._dp=0; self._prog=0.0; self._done=False
        self.after(400,self._type_next)

    def _type_next(self):
        if self._done: return
        if self._ci<=len(self._greeting):
            self._c.itemconfig(self._tid,text=self._greeting[:self._ci]); self._ci+=1
            self.after(55 if self._ci<len(self._greeting) else 80,self._type_next)
        else: self.after(200,self._animate)

    def _animate(self):
        if self._done: return
        syms=["·  ·  ·","●  ·  ·","●  ●  ·","●  ●  ●","·  ·  ·"]
        self._c.itemconfig(self._did,text=syms[self._dp%len(syms)]); self._dp+=1
        self._prog=min(1.0,self._prog+0.07)
        cx=260; x1=cx-120; x2=cx+120
        self._c.coords(self._bfg,x1,252,x1+(x2-x1)*self._prog,255)
        if self._prog>=1.0 and self._dp>=6: self._done=True; self.after(260,self._finish)
        else: self.after(120,self._animate)

    def _finish(self): self.destroy(); self.on_done()

# ══════════════════════════════════════════════════════════════════════════════
# DROPDOWN NAV BUTTON
# ══════════════════════════════════════════════════════════════════════════════
class DropdownNavBtn(tk.Frame):
    """A nav button that shows a dropdown menu of sub-items on click."""
    def __init__(self, parent, label, items, app, active_key_var, **kw):
        super().__init__(parent, bg=SURF, **kw)
        self.app=app; self.items=items; self.active_key_var=active_key_var
        self._menu_open=False
        self._btn=tk.Button(self,text=label.upper()+"  ▾",font=app.F["nav"],
                            bg=SURF,fg=INK3,relief="flat",bd=0,padx=14,cursor="hand2",
                            command=self._toggle)
        self._btn.pack(fill="both",expand=True)
        self._popup=None

    def set_active(self,is_active):
        self._btn.config(bg=BG if is_active else SURF,
                         fg=INK if is_active else INK3,
                         font=self.app.F["nav_bold"] if is_active else self.app.F["nav"])

    def _toggle(self):
        if self._menu_open: self._close(); return
        self._menu_open=True
        # Build popup below this widget
        x=self.winfo_rootx(); y=self.winfo_rooty()+self.winfo_height()
        self._popup=tk.Toplevel(self); self._popup.overrideredirect(True)
        self._popup.geometry(f"+{x}+{y}"); self._popup.configure(bg=INK4)
        frame=tk.Frame(self._popup,bg=SURF,padx=1,pady=1); frame.pack()
        for key,lbl in self.items:
            def cmd(k=key): self._close(); self.app.show(k)
            tk.Button(frame,text=lbl,font=self.app.F["small"],bg=SURF,fg=INK2,
                      relief="flat",bd=0,padx=20,pady=8,cursor="hand2",anchor="w",width=16,
                      command=cmd).pack(fill="x")
        self._popup.bind("<FocusOut>",lambda e:self._close())
        self._popup.focus_set()
        self.app.bind("<Button-1>",lambda e:self._close(),"+")

    def _close(self):
        self._menu_open=False
        if self._popup:
            try: self._popup.destroy()
            except: pass
            self._popup=None

# ══════════════════════════════════════════════════════════════════════════════
# MAIN APP
# ══════════════════════════════════════════════════════════════════════════════
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"Focus  v{VERSION}"); self.geometry("1080x720"); self.minsize(860,600)
        self.configure(bg=BG); self.withdraw()
        self.data=load(); self.config=load_config()
        self.ollama=OllamaManager(self.config); self.updater=Updater(self.config)
        # Persist AI chat across tab switches
        self._ai_history=[]; self._ai_widgets=[]
        for key in ("graphs","metrics","events"):
            if key not in self.data: self.data[key]=[]
        self.F={
            "serif":   tkfont.Font(family="Georgia", size=22),
            "serif_md":tkfont.Font(family="Georgia", size=13),
            "serif_sm":tkfont.Font(family="Georgia", size=11),
            "body":    tkfont.Font(family="Segoe UI",size=10),
            "small":   tkfont.Font(family="Segoe UI",size=9),
            "bold":    tkfont.Font(family="Segoe UI",size=10,weight="bold"),
            "nav":     tkfont.Font(family="Segoe UI",size=9),
            "nav_bold":tkfont.Font(family="Segoe UI",size=9,weight="bold"),
            "mono":    tkfont.Font(family="Consolas", size=8),
            "mono_lg": tkfont.Font(family="Georgia", size=16),
            "plus":    tkfont.Font(family="Segoe UI",size=14),
            "tiny":    tkfont.Font(family="Consolas", size=7),
        }
        self.protocol("WM_DELETE_WINDOW",self._on_close)
        self._build()
        SplashScreen(self,self._after_splash)

    def _after_splash(self):
        self.deiconify(); self.lift(); self.show("long")
        self.ollama.start(on_ready=lambda:self.after(0,self._ollama_ready),
                          on_error=lambda m:self.after(0,lambda:self._ollama_err(m)))
        self.updater.check(lambda v:self.after(0,lambda:self._update_notify(v)) if v else None)

    def _ollama_ready(self):
        models=self.ollama.list_models(); model=self.config.get("ollama_model","llama3.2")
        if not any(model in m for m in models):
            self.status_var.set(f"⚠  Model '{model}' not found. Run: ollama pull {model}")
        else:
            self.status_var.set(f"● Ollama ready  ({model})"); self.after(3000,lambda:self.status_var.set(""))

    def _ollama_err(self,msg):
        self.status_var.set("⚠  Ollama not installed — AI Coach unavailable" if "not found" in msg.lower() else f"⚠  Ollama: {msg}")

    def _update_notify(self,v):
        if messagebox.askyesno("Update Available",f"Focus v{v} is available (you have v{VERSION}).\n\nDownload and apply now?"):
            self.status_var.set("Downloading update…")
            self.updater.apply(
                lambda:self.after(0,lambda:(messagebox.showinfo("Update Applied","Please close and reopen Focus."),self.status_var.set("✓ Update ready — please restart"))),
                lambda m:self.after(0,lambda:self.status_var.set(f"Update failed: {m}")))

    def _on_close(self): self.ollama.stop(); self.destroy()

    def _build(self):
        hdr=tk.Frame(self,bg=BG); hdr.pack(fill="x",padx=30,pady=(14,12))
        tk.Label(hdr,text="Focus",font=self.F["serif"],bg=BG,fg=INK).pack(side="left")
        tk.Label(hdr,text=date.today().strftime("%A, %B %d %Y").upper(),
                 font=self.F["mono"],bg=BG,fg=INK4).pack(side="left",padx=14)
        tk.Button(hdr,text="⚙",font=self.F["body"],bg=BG,fg=INK4,relief="flat",bd=0,
                  cursor="hand2",command=self._open_settings).pack(side="right")
        tk.Frame(self,bg=INK4,height=1).pack(fill="x")

        # Nav bar with dropdowns
        self.nav_bar=tk.Frame(self,bg=SURF,height=42); self.nav_bar.pack(fill="x"); self.nav_bar.pack_propagate(False)
        self._current_key=None
        self._dropdown_btns={}

        # Goals dropdown
        goals_dd=DropdownNavBtn(self.nav_bar,"Goals",
            [("long","Long-term"),("monthly","Monthly"),("weekly","Weekly")],
            self,None)
        goals_dd.pack(side="left",fill="y")
        self._dropdown_btns["goals"]=goals_dd
        self._goal_keys={"long","monthly","weekly"}

        # Habits (direct)
        hb=tk.Button(self.nav_bar,text="HABITS & CALENDAR",font=self.F["nav"],
                     bg=SURF,fg=INK3,relief="flat",bd=0,padx=14,cursor="hand2",
                     command=lambda:self.show("habits"))
        hb.pack(side="left",fill="y")
        self._dropdown_btns["habits"]=hb

        # Performance dropdown
        perf_dd=DropdownNavBtn(self.nav_bar,"Performance",
            [("metrics","Metrics"),("graphs","Graphs"),("ai","AI Coach")],
            self,None)
        perf_dd.pack(side="left",fill="y")
        self._dropdown_btns["performance"]=perf_dd
        self._perf_keys={"metrics","graphs","ai"}

        tk.Frame(self,bg=INK4,height=1).pack(fill="x")
        self.content=tk.Frame(self,bg=BG); self.content.pack(fill="both",expand=True)
        self.status_var=tk.StringVar()
        tk.Label(self,textvariable=self.status_var,font=self.F["mono"],bg=BG,fg=INK4,anchor="e").pack(fill="x",padx=20,pady=3)

    def _update_nav(self,key):
        # Goals group
        goals_active = key in self._goal_keys
        self._dropdown_btns["goals"].set_active(goals_active)
        # Habits
        hb=self._dropdown_btns["habits"]
        hb.config(bg=BG if key=="habits" else SURF,
                  fg=INK if key=="habits" else INK3,
                  font=self.F["nav_bold"] if key=="habits" else self.F["nav"])
        # Performance group
        perf_active = key in self._perf_keys
        self._dropdown_btns["performance"].set_active(perf_active)

    def show(self,key):
        self._current_key=key
        self._update_nav(key)
        # Preserve AI view instance
        if key=="ai" and hasattr(self,"_ai_view_instance") and self._ai_view_instance:
            for w in self.content.winfo_children(): w.destroy()
            self._ai_view_instance=AICoachView(self.content,self)
            self._ai_view_instance.pack(fill="both",expand=True)
            return
        for w in self.content.winfo_children(): w.destroy()
        views={"habits":HabitsView,"graphs":GraphsView,"metrics":MetricsView,"ai":AICoachView}
        if key in views:
            v=views[key](self.content,self); v.pack(fill="both",expand=True)
            if key=="ai": self._ai_view_instance=v
        else:
            titles={"long":("Long-term Goals","The things worth orienting your life around."),
                    "monthly":("Monthly Goals","What you intend to accomplish this month."),
                    "weekly":("Weekly Goals","Concrete targets for the next seven days.")}
            GoalView(self.content,self,key,*titles[key]).pack(fill="both",expand=True)

    def persist(self):
        save_data(self.data); self.status_var.set("● Saved")
        self.after(1400,lambda:self.status_var.set(""))

    def _open_settings(self): SettingsDialog(self)

# ══════════════════════════════════════════════════════════════════════════════
# SETTINGS
# ══════════════════════════════════════════════════════════════════════════════
class SettingsDialog(tk.Toplevel):
    def __init__(self,app):
        super().__init__(app); self.app=app
        self.title("Settings"); self.geometry("600x560"); self.resizable(False,False)
        self.configure(bg=BG); self.grab_set()
        pad=tk.Frame(self,bg=BG); pad.pack(fill="both",expand=True,padx=30,pady=24)
        tk.Label(pad,text="Settings",font=app.F["serif_md"],bg=BG,fg=INK).pack(anchor="w",pady=(0,16))

        def sec(t):
            tk.Label(pad,text=t,font=app.F["mono"],bg=BG,fg=INK4).pack(anchor="w",pady=(10,3))
            tk.Frame(pad,bg=SURF2,height=1).pack(fill="x",pady=(0,6))
        def row(lbl,wfn):
            r=tk.Frame(pad,bg=BG); r.pack(fill="x",pady=3)
            tk.Label(r,text=lbl,font=app.F["small"],bg=BG,fg=INK3,width=20,anchor="w").pack(side="left"); wfn(r)

        cfg=app.config
        sec("OLLAMA")
        self.v_model=tk.StringVar(value=cfg.get("ollama_model","llama3.2"))
        row("Model name",lambda r:tk.Entry(r,textvariable=self.v_model,font=app.F["body"],bg=SURF,fg=INK,relief="flat",bd=6,insertbackground=INK,width=20).pack(side="left"))
        self.v_opath=tk.StringVar(value=cfg.get("ollama_path",""))
        row("Ollama path (optional)",lambda r:tk.Entry(r,textvariable=self.v_opath,font=app.F["body"],bg=SURF,fg=INK,relief="flat",bd=6,insertbackground=INK,width=30).pack(side="left"))
        models=app.ollama.list_models()
        if models: row("Installed models",lambda r:tk.Label(r,text=", ".join(models),font=app.F["tiny"],bg=BG,fg=INK4,anchor="w").pack(side="left"))

        sec("AI SYSTEM PROMPT")
        tk.Label(pad,text="Customise the AI's personality and instructions.",font=app.F["tiny"],bg=BG,fg=INK4).pack(anchor="w",pady=(0,4))
        sp_frame=tk.Frame(pad,bg=INK4); sp_frame.pack(fill="x",pady=(0,4))
        sp_inner=tk.Frame(sp_frame,bg=SURF); sp_inner.pack(fill="x",padx=1,pady=1)
        self.v_sysprompt=tk.Text(sp_inner,font=app.F["small"],bg=SURF,fg=INK,relief="flat",
                                  bd=6,height=5,wrap="word",insertbackground=INK)
        self.v_sysprompt.insert("1.0",cfg.get("system_prompt",DEFAULT_SYSTEM_PROMPT))
        self.v_sysprompt.pack(fill="x")
        tk.Button(pad,text="Reset to default",font=app.F["tiny"],bg=SURF2,fg=INK4,relief="flat",bd=0,
                  cursor="hand2",command=lambda:(self.v_sysprompt.delete("1.0","end"),
                  self.v_sysprompt.insert("1.0",DEFAULT_SYSTEM_PROMPT))).pack(anchor="e",pady=(0,4))

        sec("AUTO-UPDATE  (optional)")
        self.v_ver_url=tk.StringVar(value=cfg.get("version_url",""))
        row("version.txt URL",lambda r:tk.Entry(r,textvariable=self.v_ver_url,font=app.F["tiny"],bg=SURF,fg=INK,relief="flat",bd=6,insertbackground=INK,width=38).pack(side="left",fill="x",expand=True))
        self.v_upd_url=tk.StringVar(value=cfg.get("update_url",""))
        row("focus_app.py URL",lambda r:tk.Entry(r,textvariable=self.v_upd_url,font=app.F["tiny"],bg=SURF,fg=INK,relief="flat",bd=6,insertbackground=INK,width=38).pack(side="left",fill="x",expand=True))

        sec("INFO")
        tk.Label(pad,text=f"Version  v{VERSION}    ·    Data  {DATA_FILE}",font=app.F["tiny"],bg=BG,fg=INK4).pack(anchor="w")

        btns=tk.Frame(pad,bg=BG); btns.pack(fill="x",pady=(16,0))
        tk.Button(btns,text="Check for update",font=app.F["small"],bg=SURF2,fg=INK3,relief="flat",bd=0,padx=12,pady=6,cursor="hand2",command=self._check_now).pack(side="left")
        tk.Button(btns,text="Save",font=app.F["bold"],bg=INK,fg=BG,relief="flat",bd=0,padx=22,pady=6,cursor="hand2",command=self._save).pack(side="right")
        tk.Button(btns,text="Cancel",font=app.F["body"],bg=SURF2,fg=INK3,relief="flat",bd=0,padx=14,pady=6,cursor="hand2",command=self.destroy).pack(side="right",padx=8)

    def _save(self):
        self.app.config.update({"ollama_model":self.v_model.get().strip(),"ollama_path":self.v_opath.get().strip(),
                                 "version_url":self.v_ver_url.get().strip(),"update_url":self.v_upd_url.get().strip(),
                                 "system_prompt":self.v_sysprompt.get("1.0","end").strip()})
        save_config(self.app.config)
        self.app.ollama.cfg=self.app.config; self.app.ollama._model=self.app.config["ollama_model"]
        self.app.updater.cfg=self.app.config; self.destroy()

    def _check_now(self):
        self.app.updater.cfg={"version_url":self.v_ver_url.get().strip(),"update_url":self.v_upd_url.get().strip()}
        self.app.updater.check(lambda v:messagebox.showinfo("Update",f"New version available: v{v}" if v else "You're up to date!",parent=self))

# ══════════════════════════════════════════════════════════════════════════════
# SCROLL HELPER
# ══════════════════════════════════════════════════════════════════════════════
def make_scroll_area(parent,bg=BG):
    outer=tk.Frame(parent,bg=bg)
    canvas=tk.Canvas(outer,bg=bg,highlightthickness=0,bd=0)
    sb=tk.Scrollbar(outer,orient="vertical",command=canvas.yview)
    canvas.configure(yscrollcommand=sb.set)
    sb.pack(side="right",fill="y"); canvas.pack(side="left",fill="both",expand=True)
    inner=tk.Frame(canvas,bg=bg)
    win=canvas.create_window((0,0),window=inner,anchor="nw")
    inner.bind("<Configure>",lambda e:canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.bind("<Configure>",lambda e:canvas.itemconfig(win,width=e.width))
    canvas.bind_all("<MouseWheel>",lambda e:canvas.yview_scroll(-(e.delta//120),"units"))
    return outer,inner

# ══════════════════════════════════════════════════════════════════════════════
# GOAL VIEW
# ══════════════════════════════════════════════════════════════════════════════
class GoalView(tk.Frame):
    def __init__(self,parent,app,key,title,subtitle):
        super().__init__(parent,bg=BG); self.app=app; self.key=key
        pad=tk.Frame(self,bg=BG); pad.pack(fill="x",padx=30,pady=(26,0))
        tk.Label(pad,text=title,font=app.F["serif"],bg=BG,fg=INK).pack(anchor="w")
        tk.Label(pad,text=subtitle,font=app.F["small"],bg=BG,fg=INK4).pack(anchor="w")
        inp=tk.Frame(self,bg=INK4); inp.pack(fill="x",padx=30,pady=(18,0))
        inner=tk.Frame(inp,bg=SURF); inner.pack(fill="x",padx=1,pady=1)
        self.entry=tk.Entry(inner,font=app.F["body"],bg=SURF,fg=INK,relief="flat",bd=8,insertbackground=INK)
        self.entry.pack(side="left",fill="both",expand=True)
        self.entry.bind("<Return>",lambda e:self._add()); self.entry.focus_set()
        tk.Button(inner,text="+",font=app.F["plus"],bg=INK,fg=BG,relief="flat",bd=0,padx=16,cursor="hand2",command=self._add).pack(side="right")
        so,self.lf=make_scroll_area(self); so.pack(fill="both",expand=True,padx=30,pady=(18,10))
        self._render()

    def _add(self):
        v=self.entry.get().strip()
        if not v: return
        self.app.data[self.key].append({"id":int(time.time()*1000),"text":v})
        self.entry.delete(0,"end"); self.app.persist(); self._render()

    def _del(self,iid):
        self.app.data[self.key]=[i for i in self.app.data[self.key] if i["id"]!=iid]
        self.app.persist(); self._render()

    def _render(self):
        for w in self.lf.winfo_children(): w.destroy()
        items=self.app.data.get(self.key,[])
        tk.Frame(self.lf,bg=INK4,height=1).pack(fill="x")
        if not items: tk.Label(self.lf,text="Nothing here yet.",font=self.app.F["small"],bg=BG,fg=INK4,pady=30).pack()
        else:
            for idx,item in enumerate(items):
                row=tk.Frame(self.lf,bg=BG); row.pack(fill="x")
                tk.Label(row,text=f"{idx+1:02d}",font=self.app.F["mono"],bg=BG,fg=INK4,width=4).pack(side="left",padx=(2,8),pady=12)
                tk.Label(row,text=item["text"],font=self.app.F["body"],bg=BG,fg=INK2,anchor="w",wraplength=700,justify="left").pack(side="left",fill="x",expand=True,pady=12)
                tk.Button(row,text="×",font=self.app.F["body"],bg=BG,fg=INK4,relief="flat",bd=0,cursor="hand2",command=lambda i=item["id"]:self._del(i)).pack(side="right",padx=10)
                tk.Frame(self.lf,bg=INK4,height=1).pack(fill="x")

# ══════════════════════════════════════════════════════════════════════════════
# HABITS + CALENDAR WITH EVENTS
# ══════════════════════════════════════════════════════════════════════════════
class EventDialog(tk.Toplevel):
    def __init__(self,parent,app,date_str,event=None,callback=None):
        super().__init__(parent); self.app=app; self.callback=callback; self._edit=event
        self.title("Add Event" if not event else "Edit Event")
        self.geometry("380x260"); self.resizable(False,False); self.configure(bg=BG); self.grab_set()
        pad=tk.Frame(self,bg=BG); pad.pack(fill="both",expand=True,padx=26,pady=20)
        tk.Label(pad,text=f"Event  ·  {date_str}",font=app.F["serif_md"],bg=BG,fg=INK).pack(anchor="w",pady=(0,16))
        def row(lbl):
            f=tk.Frame(pad,bg=BG); f.pack(fill="x",pady=5)
            tk.Label(f,text=lbl,font=app.F["mono"],bg=BG,fg=INK4,width=10,anchor="w").pack(side="left"); return f
        r=row("TITLE"); self.v_title=tk.StringVar(value=event.get("title","") if event else "")
        e=tk.Entry(r,textvariable=self.v_title,font=app.F["body"],bg=SURF,fg=INK,relief="flat",bd=6,insertbackground=INK,width=28)
        e.pack(side="left"); e.focus_set()
        r=row("TIME"); self.v_time=tk.StringVar(value=event.get("time","") if event else "")
        tk.Entry(r,textvariable=self.v_time,font=app.F["body"],bg=SURF,fg=INK,relief="flat",bd=6,insertbackground=INK,width=12).pack(side="left")
        tk.Label(r,text="e.g. 09:00",font=app.F["tiny"],bg=BG,fg=INK4).pack(side="left",padx=6)
        r=row("NOTE"); self.v_note=tk.StringVar(value=event.get("note","") if event else "")
        tk.Entry(r,textvariable=self.v_note,font=app.F["body"],bg=SURF,fg=INK,relief="flat",bd=6,insertbackground=INK,width=28).pack(side="left",fill="x",expand=True)
        btns=tk.Frame(pad,bg=BG); btns.pack(fill="x",pady=(14,0))
        tk.Button(btns,text="Save",font=app.F["bold"],bg=INK,fg=BG,relief="flat",bd=0,padx=20,pady=7,cursor="hand2",command=self._save).pack(side="right")
        if event: tk.Button(btns,text="Delete",font=app.F["small"],bg=SURF2,fg=INK3,relief="flat",bd=0,padx=14,pady=7,cursor="hand2",command=self._delete).pack(side="right",padx=6)
        tk.Button(btns,text="Cancel",font=app.F["body"],bg=SURF2,fg=INK3,relief="flat",bd=0,padx=14,pady=7,cursor="hand2",command=self.destroy).pack(side="right",padx=6)
        e.bind("<Return>",lambda ev:self._save())

    def _save(self):
        title=self.v_title.get().strip()
        if not title: return
        ev={"title":title,"time":self.v_time.get().strip(),"note":self.v_note.get().strip()}
        if self.callback: self.callback("save",ev,self._edit)
        self.destroy()

    def _delete(self):
        if self.callback: self.callback("delete",None,self._edit)
        self.destroy()

class HabitsView(tk.Frame):
    def __init__(self,parent,app):
        super().__init__(parent,bg=BG); self.app=app
        self.sel=None; self.cy=date.today().year; self.cm=date.today().month

        pad=tk.Frame(self,bg=BG); pad.pack(fill="x",padx=30,pady=(26,0))
        tk.Label(pad,text="Habits & Calendar",font=app.F["serif"],bg=BG,fg=INK).pack(side="left")
        tk.Label(pad,text="Track habits and events side by side.",font=app.F["small"],bg=BG,fg=INK4).pack(side="left",padx=14)

        inp=tk.Frame(self,bg=INK4); inp.pack(fill="x",padx=30,pady=(18,0))
        inner=tk.Frame(inp,bg=SURF); inner.pack(fill="x",padx=1,pady=1)
        self.entry=tk.Entry(inner,font=app.F["body"],bg=SURF,fg=INK,relief="flat",bd=8,insertbackground=INK)
        self.entry.pack(side="left",fill="both",expand=True)
        self.entry.bind("<Return>",lambda e:self._add())
        tk.Button(inner,text="+",font=app.F["plus"],bg=INK,fg=BG,relief="flat",bd=0,padx=16,cursor="hand2",command=self._add).pack(side="right")

        split=tk.Frame(self,bg=BG); split.pack(fill="both",expand=True,padx=30,pady=(18,10))
        left=tk.Frame(split,bg=BG,width=260); left.pack(side="left",fill="y"); left.pack_propagate(False)
        tk.Label(left,text="HABITS",font=app.F["mono"],bg=BG,fg=INK4).pack(anchor="w",pady=(0,8))
        self.hlist=tk.Frame(left,bg=BG); self.hlist.pack(fill="both",expand=True)
        tk.Frame(split,bg=INK4,width=1).pack(side="left",fill="y",padx=20)
        self.right=tk.Frame(split,bg=BG); self.right.pack(side="left",fill="both",expand=True)
        self.hint=tk.Label(self.right,text="← Select a habit to see its calendar\nor click any date to add an event",
                           font=app.F["small"],bg=BG,fg=INK4,justify="center")
        self.hint.pack(pady=40)
        self.cal=tk.Frame(self.right,bg=BG)
        self._render_habits()
        # Auto-show calendar (for events even with no habit)
        self.hint.pack_forget(); self.cal.pack(fill="both",expand=True); self._render_cal()

    # ── Streak helpers ────────────────────────────────────────────────────────
    def _cset(self,hid): return set(self.app.data["checks"].get(str(hid),[]))
    def _streak(self,hid):
        c=self._cset(hid); d=date.today(); n=0
        if d.isoformat() not in c: d-=timedelta(1)
        while d.isoformat() in c: n+=1; d-=timedelta(1)
        return n
    def _longest(self,hid):
        raw=sorted(self._cset(hid))
        if not raw: return 0
        best=cur=1
        for i in range(1,len(raw)):
            diff=(date.fromisoformat(raw[i])-date.fromisoformat(raw[i-1])).days
            if diff==1: cur+=1; best=max(best,cur)
            elif diff>1: cur=1
        return best

    # ── Habit actions ─────────────────────────────────────────────────────────
    def _add(self):
        v=self.entry.get().strip()
        if not v: return
        hid=int(time.time()*1000)
        self.app.data["habits"].append({"id":hid,"name":v})
        self.app.data["checks"][str(hid)]=[]
        self.entry.delete(0,"end"); self.app.persist(); self._render_habits()

    def _del(self,hid):
        self.app.data["habits"]=[h for h in self.app.data["habits"] if h["id"]!=hid]
        self.app.data["checks"].pop(str(hid),None)
        if self.sel==hid: self.sel=None
        self.app.persist(); self._render_habits(); self._render_cal()

    def _select(self,hid):
        self.sel=hid; self._render_habits()
        self.hint.pack_forget(); self.cal.pack(fill="both",expand=True); self._render_cal()

    def _toggle(self,hid,key):
        c=self.app.data["checks"].setdefault(str(hid),[])
        if key in c: c.remove(key)
        else: c.append(key)
        self.app.persist(); self._render_habits(); self._render_cal()

    def _chm(self,d):
        self.cm+=d
        if self.cm>12: self.cm=1; self.cy+=1
        if self.cm<1: self.cm=12; self.cy-=1
        self._render_cal()

    # ── Event actions ─────────────────────────────────────────────────────────
    def _open_event_dialog(self,date_str,event=None):
        EventDialog(self,self.app,date_str,event=event,
                    callback=lambda action,ev,old:self._on_event(action,date_str,ev,old))

    def _on_event(self,action,date_str,ev,old):
        events=self.app.data.setdefault("events",[])
        if action=="delete" and old:
            self.app.data["events"]=[e for e in events
                if not(e["date"]==old["date"] and e["title"]==old["title"])]
        elif action=="save":
            ev["date"]=date_str
            if old:
                for i,e in enumerate(events):
                    if e["date"]==old["date"] and e["title"]==old["title"]: events[i]=ev; break
            else: events.append(ev)
        self.app.persist(); self._render_cal()

    # ── Render habits list ────────────────────────────────────────────────────
    def _render_habits(self):
        for w in self.hlist.winfo_children(): w.destroy()
        habits=self.app.data.get("habits",[])
        tk.Frame(self.hlist,bg=INK4,height=1).pack(fill="x")
        if not habits:
            tk.Label(self.hlist,text="No habits yet.",font=self.app.F["small"],bg=BG,fg=INK4,pady=16).pack()
        else:
            today=date.today()
            for h in habits:
                streak=self._streak(h["id"]); sel=h["id"]==self.sel
                checks=self._cset(h["id"])
                # Progress: completions in last 30 days
                done30=sum(1 for i in range(30) if (today-timedelta(i)).isoformat() in checks)
                pct=done30/30

                outer=tk.Frame(self.hlist,bg=BG); outer.pack(fill="x",pady=0)
                row=tk.Frame(outer,bg=BG,cursor="hand2"); row.pack(fill="x")
                row.bind("<Button-1>",lambda e,hid=h["id"]:self._select(hid))

                dot=tk.Label(row,text="●",font=tkfont.Font(family="Segoe UI",size=7),bg=BG,fg=INK if sel else INK4,cursor="hand2")
                dot.pack(side="left",padx=(4,6),pady=8); dot.bind("<Button-1>",lambda e,hid=h["id"]:self._select(hid))

                nf=tkfont.Font(family="Segoe UI",size=10,weight="bold" if sel else "normal")
                nl=tk.Label(row,text=h["name"],font=nf,bg=BG,fg=INK if sel else INK3,anchor="w",cursor="hand2")
                nl.pack(side="left",fill="x",expand=True,pady=8); nl.bind("<Button-1>",lambda e,hid=h["id"]:self._select(hid))

                if streak>0: tk.Label(row,text=f"{streak}d",font=self.app.F["mono"],bg=BG,fg=STREAK).pack(side="left",padx=4)
                tk.Button(row,text="×",font=self.app.F["body"],bg=BG,fg=INK4,relief="flat",bd=0,cursor="hand2",
                          command=lambda hid=h["id"]:self._del(hid)).pack(side="right",padx=6)

                # Progress bar
                bar_outer=tk.Frame(outer,bg=SURF2,height=4); bar_outer.pack(fill="x",padx=10,pady=(0,4))
                bar_outer.update_idletasks()
                bar_fill=tk.Frame(bar_outer,bg=STREAK if pct>=0.7 else INK3 if pct>=0.3 else INK4,height=4)
                bar_fill.place(relx=0,rely=0,relwidth=pct,relheight=1)
                tk.Label(outer,text=f"{done30}/30 days",font=self.app.F["tiny"],bg=BG,fg=INK4,anchor="w").pack(fill="x",padx=10,pady=(0,3))

                tk.Frame(self.hlist,bg=INK4,height=1).pack(fill="x")

    # ── Render calendar ───────────────────────────────────────────────────────
    def _render_cal(self):
        for w in self.cal.winfo_children(): w.destroy()
        hid=self.sel; checks=self._cset(hid) if hid else set()
        today=date.today()
        events_by_date={}
        for ev in self.app.data.get("events",[]):
            events_by_date.setdefault(ev["date"],[]).append(ev)

        # Nav row
        nav=tk.Frame(self.cal,bg=BG); nav.pack(fill="x",pady=(0,10))
        tk.Button(nav,text="‹",font=self.app.F["body"],bg=BG,fg=INK3,relief="flat",bd=0,cursor="hand2",command=lambda:self._chm(-1)).pack(side="left")
        tk.Label(nav,text=date(self.cy,self.cm,1).strftime("%B %Y"),font=self.app.F["serif_md"],bg=BG,fg=INK).pack(side="left",padx=10)
        tk.Button(nav,text="›",font=self.app.F["body"],bg=BG,fg=INK3,relief="flat",bd=0,cursor="hand2",command=lambda:self._chm(1)).pack(side="left")
        if hid: tk.Label(nav,text=f"showing: {next((h['name'] for h in self.app.data['habits'] if h['id']==hid),'?')}",
                         font=self.app.F["tiny"],bg=BG,fg=INK4).pack(side="left",padx=14)
        tk.Label(nav,text="click date to add event",font=self.app.F["tiny"],bg=BG,fg=INK4).pack(side="right",padx=6)

        # Day header
        grid=tk.Frame(self.cal,bg=BG); grid.pack()
        for col,dn in enumerate(["SUN","MON","TUE","WED","THU","FRI","SAT"]):
            tk.Label(grid,text=dn,font=self.app.F["mono"],bg=BG,fg=INK4,width=6,anchor="center").grid(row=0,column=col,padx=2,pady=(0,4))

        first_wd=(date(self.cy,self.cm,1).weekday()+1)%7
        days_in=calendar.monthrange(self.cy,self.cm)[1]
        r,c=1,first_wd
        for d in range(1,days_in+1):
            cd=date(self.cy,self.cm,d); key=cd.isoformat()
            future=cd>today; is_today=cd==today; checked=key in checks
            has_event=key in events_by_date

            if checked: cbg,cfg2,hl=INK,BG,INK
            elif is_today: cbg,cfg2,hl=BG,INK,INK
            elif future: cbg,cfg2,hl=BG,INK4,BG
            else: cbg,cfg2,hl=SURF,INK3,SURF2

            cell_f=tk.Frame(grid,bg=BG); cell_f.grid(row=r,column=c,padx=2,pady=2)
            cell=tk.Label(cell_f,text=str(d),font=self.app.F["mono"],bg=cbg,fg=cfg2,
                          width=5,height=2,anchor="center",
                          highlightbackground=hl,highlightthickness=1)
            cell.pack()
            if has_event:
                dot_col=NAVY if not checked else STREAK
                tk.Label(cell_f,text="•",font=tkfont.Font(family="Segoe UI",size=7),
                         bg=BG,fg=dot_col).pack()

            if not future:
                cell.config(cursor="hand2")
                if hid: cell.bind("<Button-1>",lambda e,hid=hid,k=key:self._toggle(hid,k))
                cell.bind("<Button-3>",lambda e,k=key,evs=events_by_date.get(key,[]):self._open_event_dialog(k,evs[0] if evs else None))

            # Left-click on event dot = open event dialog
            if has_event:
                for ev in events_by_date[key]:
                    tk.Label(cell_f,text=ev["title"][:8],font=self.app.F["tiny"],
                             bg=BG,fg=NAVY,cursor="hand2").pack()
            # Right-click on empty date to add event
            cell_f.bind("<Button-3>",lambda e,k=key,evs=events_by_date.get(key,[]):self._open_event_dialog(k,evs[0] if evs else None))

            c+=1
            if c==7: c=0; r+=1

        tk.Label(self.cal,text="Left-click = toggle habit  ·  Right-click = add/edit event",
                 font=self.app.F["tiny"],bg=BG,fg=INK4).pack(pady=(6,0))

        # Stats (only if habit selected)
        if hid:
            stats=tk.Frame(self.cal,bg=SURF2); stats.pack(fill="x",pady=(14,0))
            for lbl,val,color in [("CURRENT STREAK",f"{self._streak(hid)} days",STREAK),
                                   ("LONGEST STREAK",f"{self._longest(hid)} days",INK),
                                   ("TOTAL",f"{len(checks)} completions",INK)]:
                sf=tk.Frame(stats,bg=SURF2); sf.pack(side="left",padx=18,pady=12)
                tk.Label(sf,text=lbl,font=self.app.F["mono"],bg=SURF2,fg=INK4).pack(anchor="w")
                tk.Label(sf,text=val,font=self.app.F["mono_lg"],bg=SURF2,fg=color).pack(anchor="w")


# ══════════════════════════════════════════════════════════════════════════════
# METRICS  (unchanged)
# ══════════════════════════════════════════════════════════════════════════════
class MetricEntryDialog(tk.Toplevel):
    def __init__(self,parent,app,metric,entry=None,callback=None):
        super().__init__(parent); self.app=app; self.metric=metric; self.callback=callback
        self.title("Add Entry" if entry is None else "Edit Entry")
        self.geometry("360x280"); self.resizable(False,False); self.configure(bg=BG); self.grab_set()
        self._edit=entry
        pad=tk.Frame(self,bg=BG); pad.pack(fill="both",expand=True,padx=28,pady=22)
        tk.Label(pad,text=metric["name"],font=app.F["serif_md"],bg=BG,fg=INK).pack(anchor="w",pady=(0,18))
        def row(lbl):
            f=tk.Frame(pad,bg=BG); f.pack(fill="x",pady=5)
            tk.Label(f,text=lbl,font=app.F["mono"],bg=BG,fg=INK4,width=12,anchor="w").pack(side="left"); return f
        r=row("DATE"); self.v_date=tk.StringVar(value=entry["date"] if entry else date.today().isoformat())
        tk.Entry(r,textvariable=self.v_date,font=app.F["body"],bg=SURF,fg=INK,relief="flat",bd=6,insertbackground=INK,width=16).pack(side="left")
        tk.Label(r,text="YYYY-MM-DD",font=app.F["tiny"],bg=BG,fg=INK4).pack(side="left",padx=6)
        r=row(f"VALUE ({metric.get('unit','')})".upper()); self.v_val=tk.StringVar(value=str(entry["value"]) if entry else "")
        tk.Entry(r,textvariable=self.v_val,font=app.F["body"],bg=SURF,fg=INK,relief="flat",bd=6,insertbackground=INK,width=14).pack(side="left")
        r=row("NOTE"); self.v_note=tk.StringVar(value=entry.get("note","") if entry else "")
        tk.Entry(r,textvariable=self.v_note,font=app.F["body"],bg=SURF,fg=INK,relief="flat",bd=6,insertbackground=INK,width=24).pack(side="left",fill="x",expand=True)
        btns=tk.Frame(pad,bg=BG); btns.pack(fill="x",pady=(18,0))
        tk.Button(btns,text="Save",font=app.F["bold"],bg=INK,fg=BG,relief="flat",bd=0,padx=20,pady=7,cursor="hand2",command=self._save).pack(side="right")
        tk.Button(btns,text="Cancel",font=app.F["body"],bg=SURF2,fg=INK3,relief="flat",bd=0,padx=14,pady=7,cursor="hand2",command=self.destroy).pack(side="right",padx=8)
    def _save(self):
        try: val=float(self.v_val.get())
        except: return
        ds=self.v_date.get().strip()
        try: datetime.strptime(ds,"%Y-%m-%d")
        except: return
        e={"date":ds,"value":val,"note":self.v_note.get().strip()}
        if self.callback: self.callback(e,self._edit)
        self.destroy()

class MetricSettingsDialog(tk.Toplevel):
    def __init__(self,parent,app,metric=None,callback=None):
        super().__init__(parent); self.app=app; self.callback=callback
        self.title("Metric Settings"); self.geometry("400x360"); self.resizable(False,False); self.configure(bg=BG); self.grab_set()
        self.cfg=dict(metric) if metric else {"id":int(time.time()*1000),"name":"","unit":"","color":INK,"entries":[]}
        self._cc=self.cfg.get("color",INK)
        pad=tk.Frame(self,bg=BG); pad.pack(fill="both",expand=True,padx=28,pady=22)
        tk.Label(pad,text="Metric Settings",font=app.F["serif_md"],bg=BG,fg=INK).pack(anchor="w",pady=(0,20))
        def row(lbl):
            f=tk.Frame(pad,bg=BG); f.pack(fill="x",pady=7)
            tk.Label(f,text=lbl,font=app.F["mono"],bg=BG,fg=INK4,width=12,anchor="w").pack(side="left"); return f
        r=row("NAME"); self.v_name=tk.StringVar(value=self.cfg.get("name",""))
        tk.Entry(r,textvariable=self.v_name,font=app.F["body"],bg=SURF,fg=INK,relief="flat",bd=6,insertbackground=INK,width=22).pack(side="left")
        r=row("UNIT"); self.v_unit=tk.StringVar(value=self.cfg.get("unit",""))
        tk.Entry(r,textvariable=self.v_unit,font=app.F["body"],bg=SURF,fg=INK,relief="flat",bd=6,insertbackground=INK,width=12).pack(side="left")
        tk.Label(r,text="e.g. kg, km, hrs, bpm",font=app.F["tiny"],bg=BG,fg=INK4).pack(side="left",padx=8)
        r=row("COLOUR"); self.cprev=tk.Frame(r,bg=self._cc,width=22,height=22,highlightbackground=INK4,highlightthickness=1)
        self.cprev.pack(side="left",padx=(0,8))
        for c in PRESET_COLORS:
            sw=tk.Frame(r,bg=c,width=16,height=16,cursor="hand2",highlightbackground=INK4,highlightthickness=1)
            sw.pack(side="left",padx=2); sw.bind("<Button-1>",lambda e,col=c:self._pick(col))
        tk.Button(r,text="…",font=app.F["small"],bg=SURF2,fg=INK3,relief="flat",bd=0,padx=6,cursor="hand2",command=self._custom).pack(side="left",padx=(6,0))
        tk.Label(pad,text="QUICK ADD",font=app.F["mono"],bg=BG,fg=INK4).pack(anchor="w",pady=(10,4))
        sugg=tk.Frame(pad,bg=BG); sugg.pack(fill="x",pady=4)
        for nm,un in [("Weight","kg"),("Sleep","hrs"),("Mood","/ 10"),("Steps","k"),("Water","L"),("Heart Rate","bpm")]:
            def fill(n=nm,u=un): self.v_name.set(n); self.v_unit.set(u)
            tk.Button(sugg,text=nm,font=app.F["tiny"],bg=SURF2,fg=INK3,relief="flat",bd=0,padx=8,pady=4,cursor="hand2",command=fill).pack(side="left",padx=2,pady=2)
        btns=tk.Frame(pad,bg=BG); btns.pack(fill="x",pady=(16,0))
        tk.Button(btns,text="Save",font=app.F["bold"],bg=INK,fg=BG,relief="flat",bd=0,padx=20,pady=7,cursor="hand2",command=self._save).pack(side="right")
        tk.Button(btns,text="Cancel",font=app.F["body"],bg=SURF2,fg=INK3,relief="flat",bd=0,padx=14,pady=7,cursor="hand2",command=self.destroy).pack(side="right",padx=8)
    def _pick(self,col): self._cc=col; self.cprev.config(bg=col)
    def _custom(self):
        res=colorchooser.askcolor(color=self._cc,parent=self,title="Pick colour")
        if res and res[1]: self._cc=res[1]; self.cprev.config(bg=res[1])
    def _save(self):
        nm=self.v_name.get().strip()
        if not nm: return
        self.cfg["name"]=nm; self.cfg["unit"]=self.v_unit.get().strip(); self.cfg["color"]=self._cc
        if self.callback: self.callback(self.cfg)
        self.destroy()

class MetricsView(tk.Frame):
    def __init__(self,parent,app):
        super().__init__(parent,bg=BG); self.app=app; self.sel_id=None
        pad=tk.Frame(self,bg=BG); pad.pack(fill="x",padx=30,pady=(26,0))
        tk.Label(pad,text="Metrics",font=app.F["serif"],bg=BG,fg=INK).pack(side="left")
        tk.Button(pad,text="+ New Metric",font=app.F["small"],bg=INK,fg=BG,relief="flat",bd=0,padx=14,pady=6,cursor="hand2",command=self._new).pack(side="right")
        tk.Label(pad,text="Track anything over time.",font=app.F["small"],bg=BG,fg=INK4).pack(side="left",padx=14)
        tk.Frame(self,bg=INK4,height=1).pack(fill="x",padx=30,pady=(14,0))
        split=tk.Frame(self,bg=BG); split.pack(fill="both",expand=True,padx=30,pady=(16,10))
        left=tk.Frame(split,bg=BG,width=230); left.pack(side="left",fill="y"); left.pack_propagate(False)
        tk.Label(left,text="TRACKERS",font=app.F["mono"],bg=BG,fg=INK4).pack(anchor="w",pady=(0,8))
        self.mlist=tk.Frame(left,bg=BG); self.mlist.pack(fill="both",expand=True)
        tk.Frame(split,bg=INK4,width=1).pack(side="left",fill="y",padx=20)
        self.right=tk.Frame(split,bg=BG); self.right.pack(side="left",fill="both",expand=True)
        self.hint=tk.Label(self.right,text="← Select a metric to log data",font=app.F["small"],bg=BG,fg=INK4); self.hint.pack(pady=60)
        self.detail=tk.Frame(self.right,bg=BG); self._render_list()
    def _mid(self,mid): return next((m for m in self.app.data["metrics"] if m["id"]==mid),None)
    def _new(self): MetricSettingsDialog(self,self.app,callback=self._on_ms)
    def _edit_m(self,mid):
        m=self._mid(mid)
        if m: MetricSettingsDialog(self,self.app,metric=dict(m),callback=self._on_ms)
    def _on_ms(self,cfg):
        metrics=self.app.data["metrics"]; ix=next((i for i,m in enumerate(metrics) if m["id"]==cfg["id"]),None)
        if ix is not None: cfg["entries"]=metrics[ix].get("entries",[]); metrics[ix]=cfg
        else:
            if "entries" not in cfg: cfg["entries"]=[]
            metrics.append(cfg)
        self.app.persist(); self._render_list(); self._select(cfg["id"])
    def _del_m(self,mid):
        self.app.data["metrics"]=[m for m in self.app.data["metrics"] if m["id"]!=mid]
        if self.sel_id==mid: self.sel_id=None; self.detail.pack_forget(); self.hint.pack(pady=60)
        self.app.persist(); self._render_list()
    def _select(self,mid):
        self.sel_id=mid; self._render_list(); self.hint.pack_forget(); self.detail.pack(fill="both",expand=True); self._render_detail()
    def _render_list(self):
        for w in self.mlist.winfo_children(): w.destroy()
        metrics=self.app.data.get("metrics",[])
        tk.Frame(self.mlist,bg=INK4,height=1).pack(fill="x")
        if not metrics: tk.Label(self.mlist,text="No metrics yet.",font=self.app.F["small"],bg=BG,fg=INK4,pady=20).pack()
        else:
            for m in metrics:
                sel=m["id"]==self.sel_id; entries=m.get("entries",[])
                row=tk.Frame(self.mlist,bg=BG,cursor="hand2"); row.pack(fill="x")
                row.bind("<Button-1>",lambda e,mid=m["id"]:self._select(mid))
                dot=tk.Label(row,text="■",font=tkfont.Font(family="Segoe UI",size=8),bg=BG,fg=m.get("color",INK),cursor="hand2")
                dot.pack(side="left",padx=(4,6),pady=10); dot.bind("<Button-1>",lambda e,mid=m["id"]:self._select(mid))
                nf=tkfont.Font(family="Segoe UI",size=10,weight="bold" if sel else "normal")
                nl=tk.Label(row,text=m["name"],font=nf,bg=BG,fg=INK if sel else INK3,anchor="w",cursor="hand2")
                nl.pack(side="left",fill="x",expand=True,pady=10); nl.bind("<Button-1>",lambda e,mid=m["id"]:self._select(mid))
                tk.Label(row,text=str(len(entries)),font=self.app.F["mono"],bg=BG,fg=INK4).pack(side="left",padx=4)
                tk.Button(row,text="×",font=self.app.F["body"],bg=BG,fg=INK4,relief="flat",bd=0,cursor="hand2",command=lambda mid=m["id"]:self._del_m(mid)).pack(side="right",padx=8)
                tk.Frame(self.mlist,bg=INK4,height=1).pack(fill="x")
    def _render_detail(self):
        for w in self.detail.winfo_children(): w.destroy()
        mid=self.sel_id; m=self._mid(mid)
        if not m: return
        entries=sorted(m.get("entries",[]),key=lambda e:e["date"],reverse=True)
        hdr=tk.Frame(self.detail,bg=BG); hdr.pack(fill="x",pady=(0,14))
        tk.Label(hdr,text=m["name"],font=self.app.F["serif_md"],bg=BG,fg=INK).pack(side="left")
        if m.get("unit"): tk.Label(hdr,text=m["unit"],font=self.app.F["mono"],bg=BG,fg=INK4).pack(side="left",padx=8)
        tk.Button(hdr,text="✎ Settings",font=self.app.F["small"],bg=SURF2,fg=INK3,relief="flat",bd=0,padx=10,pady=4,cursor="hand2",command=lambda:self._edit_m(mid)).pack(side="right",padx=(6,0))
        tk.Button(hdr,text="+ Log Entry",font=self.app.F["small"],bg=INK,fg=BG,relief="flat",bd=0,padx=10,pady=4,cursor="hand2",command=lambda:self._add_e(mid)).pack(side="right")
        if entries:
            vals=[e["value"] for e in sorted(entries,key=lambda e:e["date"])]
            latest=entries[0]["value"]; avg=sum(vals)/len(vals); mn,mx=min(vals),max(vals)
            sr=tk.Frame(self.detail,bg=SURF2); sr.pack(fill="x",pady=(0,14))
            for lbl,val,col in [("LATEST",f"{latest} {m.get('unit','')}",m.get("color",INK)),("AVG",f"{avg:.1f}",INK),("MIN",str(mn),INK),("MAX",str(mx),INK),("ENTRIES",str(len(entries)),INK)]:
                sf=tk.Frame(sr,bg=SURF2); sf.pack(side="left",padx=16,pady=10)
                tk.Label(sf,text=lbl,font=self.app.F["mono"],bg=SURF2,fg=INK4).pack(anchor="w")
                tk.Label(sf,text=str(val),font=self.app.F["mono_lg"],bg=SURF2,fg=col).pack(anchor="w")
            spark=tk.Canvas(self.detail,bg=BG,height=80,highlightthickness=0); spark.pack(fill="x",pady=(0,12))
            spark.bind("<Configure>",lambda e,v=vals,col=m.get("color",INK):self._draw_spark(e.widget,v,col))
            self.after(50,lambda v=vals,col=m.get("color",INK):self._draw_spark(spark,v,col))
        tk.Frame(self.detail,bg=INK4,height=1).pack(fill="x",pady=(0,8))
        outer,inner=make_scroll_area(self.detail); outer.pack(fill="both",expand=True)
        ch=tk.Frame(inner,bg=SURF2); ch.pack(fill="x")
        for txt,w2 in [("DATE",120),("VALUE",100),("NOTE",300),("",60)]:
            tk.Label(ch,text=txt,font=self.app.F["mono"],bg=SURF2,fg=INK4,width=w2//8,anchor="w").pack(side="left",padx=8,pady=6)
        if not entries: tk.Label(inner,text='No entries yet.',font=self.app.F["small"],bg=BG,fg=INK4,pady=20).pack()
        else:
            for e in entries:
                row=tk.Frame(inner,bg=BG); row.pack(fill="x")
                tk.Label(row,text=e["date"],font=self.app.F["mono"],bg=BG,fg=INK3,width=14,anchor="w").pack(side="left",padx=8,pady=9)
                tk.Label(row,text=f"{e['value']} {m.get('unit','')}",font=self.app.F["bold"],bg=BG,fg=m.get("color",INK),anchor="w",width=12).pack(side="left",padx=4)
                tk.Label(row,text=e.get("note",""),font=self.app.F["small"],bg=BG,fg=INK4,anchor="w").pack(side="left",fill="x",expand=True,padx=4)
                tk.Button(row,text="✎",font=self.app.F["tiny"],bg=BG,fg=INK4,relief="flat",bd=0,cursor="hand2",command=lambda en=e:self._edit_e(mid,en)).pack(side="right",padx=2)
                tk.Button(row,text="×",font=self.app.F["body"],bg=BG,fg=INK4,relief="flat",bd=0,cursor="hand2",command=lambda en=e:self._del_e(mid,en)).pack(side="right",padx=4)
                tk.Frame(inner,bg=SURF2,height=1).pack(fill="x")
    def _draw_spark(self,canvas,vals,color):
        canvas.delete("all"); w=canvas.winfo_width(); h=canvas.winfo_height()
        if w<10 or len(vals)<2: return
        pl,pr,pt,pb=8,8,10,24; gw=w-pl-pr; gh=h-pt-pb
        mn=min(vals); mx=max(vals); rng=mx-mn or 1; n=len(vals)
        def px(i): return pl+(i/(n-1))*gw
        def py(v): return pt+gh-((v-mn)/rng)*gh
        pts=[(pl,pt+gh)]+[(px(i),py(v)) for i,v in enumerate(vals)]+[(px(n-1),pt+gh)]
        canvas.create_polygon(pts,fill=color,outline="",stipple="gray25")
        for i in range(n-1): canvas.create_line(px(i),py(vals[i]),px(i+1),py(vals[i+1]),fill=color,width=2,capstyle="round")
        lx,ly=px(n-1),py(vals[-1]); canvas.create_oval(lx-4,ly-4,lx+4,ly+4,fill=color,outline=BG,width=2)
        canvas.create_text(8,pt+gh+8,text=f"min {mn}",font=("Consolas",7),fill=INK4,anchor="w")
        canvas.create_text(w-8,pt+gh+8,text=f"max {mx}",font=("Consolas",7),fill=INK4,anchor="e")
    def _add_e(self,mid):
        m=self._mid(mid)
        if m: MetricEntryDialog(self,self.app,m,callback=lambda e,old:self._on_es(mid,e,old))
    def _edit_e(self,mid,entry):
        m=self._mid(mid)
        if m: MetricEntryDialog(self,self.app,m,entry=entry,callback=lambda e,old:self._on_es(mid,e,old))
    def _on_es(self,mid,new_entry,old_entry):
        m=self._mid(mid)
        if not m: return
        entries=m.setdefault("entries",[])
        if old_entry:
            for i,e in enumerate(entries):
                if e["date"]==old_entry["date"] and e["value"]==old_entry["value"]: entries[i]=new_entry; break
        else: entries.append(new_entry)
        self.app.persist(); self._render_detail()
    def _del_e(self,mid,entry):
        m=self._mid(mid)
        if not m: return
        m["entries"]=[e for e in m.get("entries",[]) if not(e["date"]==entry["date"] and e["value"]==entry["value"])]
        self.app.persist(); self._render_detail()


# ══════════════════════════════════════════════════════════════════════════════
# GRAPHS
# ══════════════════════════════════════════════════════════════════════════════
def build_habit_series(app,hid,rd):
    c=set(app.data["checks"].get(str(hid),[])); t=date.today()
    return [((t-timedelta(days=i)).isoformat(),1 if (t-timedelta(days=i)).isoformat() in c else 0) for i in range(rd-1,-1,-1)]
def build_habit_weekly(app,hid,wk):
    c=set(app.data["checks"].get(str(hid),[])); t=date.today(); s=[]
    for w in range(wk-1,-1,-1):
        st=t-timedelta(days=t.weekday())-timedelta(weeks=w)
        s.append((st.strftime("%b %d"),sum(1 for i in range(7) if (st+timedelta(i)).isoformat() in c)))
    return s
def build_habit_cumulative(app,hid,rd):
    raw=build_habit_series(app,hid,rd); cum,tot=[],0
    for d,v in raw: tot+=v; cum.append((d,tot))
    return cum
def build_habit_streak_history(app,hid,rd):
    c=set(app.data["checks"].get(str(hid),[])); t=date.today(); s=[]
    for i in range(rd-1,-1,-1):
        d=t-timedelta(days=i); k=d.isoformat(); n=0; dd=d
        if k not in c: dd-=timedelta(1)
        while dd.isoformat() in c: n+=1; dd-=timedelta(1)
        s.append((k,n))
    return s
def build_metric_series(app,mid,rd):
    m=next((x for x in app.data.get("metrics",[]) if x["id"]==mid),None)
    if not m: return []
    t=date.today(); cutoff=(t-timedelta(days=rd)).isoformat()
    pts=sorted([e for e in m.get("entries",[]) if e["date"]>=cutoff],key=lambda e:e["date"])
    return [(e["date"],e["value"]) for e in pts]

class GraphCanvas(tk.Canvas):
    PAD_L=56;PAD_R=20;PAD_T=36;PAD_B=46
    def __init__(self,parent,app,cfg,**kw):
        super().__init__(parent,bg=BG,highlightthickness=0,bd=0,**kw)
        self.app=app;self.cfg=cfg;self.bind("<Configure>",lambda e:self.draw())
    def draw(self):
        self.delete("all");w=self.winfo_width();h=self.winfo_height()
        if w<20 or h<20: return
        cfg=self.cfg;title=cfg.get("title","Graph");gtype=cfg.get("type","bar");color=cfg.get("color",INK)
        rd=int(cfg.get("range",30));st=cfg.get("source_type","habit");sid=cfg.get("source_id") or cfg.get("habit_id");mm=cfg.get("metric","daily")
        self.create_text(w//2,16,text=title,font=("Georgia",11),fill=INK,anchor="center")
        if not sid: self.create_text(w//2,h//2,text="No data source linked.",font=("Segoe UI",9),fill=INK4,anchor="center");return
        if st=="metric": series=build_metric_series(self.app,sid,rd)
        elif mm=="weekly": series=build_habit_weekly(self.app,sid,max(2,rd//7))
        elif mm=="cumulative": series=build_habit_cumulative(self.app,sid,rd)
        elif mm=="streak": series=build_habit_streak_history(self.app,sid,rd)
        else: series=build_habit_series(self.app,sid,rd)
        if not series: self.create_text(w//2,h//2,text="No data yet.",font=("Segoe UI",9),fill=INK4,anchor="center");return
        pl=self.PAD_L;pr=self.PAD_R;pt=self.PAD_T;pb=self.PAD_B;gw=w-pl-pr;gh=h-pt-pb
        if gw<10 or gh<10: return
        vals=[v for _,v in series];mv=max(vals) if max(vals)>0 else 1;n=len(series)
        def px(i): return pl+(i/(n-1))*gw if n>1 else pl+gw//2
        def py(v): return pt+gh-(v/mv)*gh
        for i in range(5):
            yv=(mv/4)*i;yp=pt+gh-(yv/mv)*gh
            self.create_line(pl,yp,pl+gw,yp,fill=SURF2,width=1)
            self.create_text(pl-6,yp,text=str(int(yv)) if yv==int(yv) else f"{yv:.1f}",font=("Consolas",7),fill=INK4,anchor="e")
        self.create_line(pl,pt,pl,pt+gh,fill=INK4,width=1);self.create_line(pl,pt+gh,pl+gw,pt+gh,fill=INK4,width=1)
        lev=max(1,n//8)
        for i,(lbl,_) in enumerate(series):
            if i%lev==0 or i==n-1:
                xp=pl+(i/(n-1))*gw if n>1 else pl+gw//2
                self.create_text(xp,pt+gh+12,text=lbl[5:] if len(lbl)==10 else lbl,font=("Consolas",7),fill=INK4,anchor="n")
        if gtype=="heatmap" and st=="habit":
            wn=rd//7;cw=max(4,gw//max(wn,1));ch2=max(4,gh//7);t2=date.today()
            cc=set(self.app.data["checks"].get(str(sid),[]))
            for wi in range(wn):
                for di in range(7):
                    d=t2-timedelta(days=(wn-1-wi)*7+(6-di))
                    cx2=pl+wi*cw;cy2=pt+di*ch2
                    self.create_rectangle(cx2+1,cy2+1,cx2+cw-1,cy2+ch2-1,fill=color if d.isoformat() in cc else SURF2,outline="")
            for di,day in enumerate(["M","T","W","T","F","S","S"]):
                self.create_text(pl-8,pt+di*ch2+ch2//2,text=day,font=("Consolas",7),fill=INK4,anchor="e")
            return
        if gtype=="bar":
            bw=max(2,gw/n-2)
            for i,(_,v) in enumerate(series):
                xp=pl+(i/n)*gw+(gw/n-bw)/2
                if v>0: self.create_rectangle(xp,py(v),xp+bw,pt+gh,fill=color,outline="")
            return
        pts2=[(px(i),py(v)) for i,(_,v) in enumerate(series)]
        if gtype=="area":
            poly=[pl,pt+gh]+[c for p in pts2 for c in p]+[px(n-1),pt+gh]
            self.create_polygon(poly,fill=color,outline="",stipple="gray25")
        if len(pts2)>1:
            for i in range(len(pts2)-1): self.create_line(pts2[i][0],pts2[i][1],pts2[i+1][0],pts2[i+1][1],fill=color,width=2,capstyle="round",joinstyle="round")
        if gtype in("line","area"):
            for xp2,yp2 in pts2: self.create_oval(xp2-3,yp2-3,xp2+3,yp2+3,fill=color,outline=BG,width=1)

class GraphDialog(tk.Toplevel):
    def __init__(self,parent,app,cfg=None,callback=None):
        super().__init__(parent);self.app=app;self.callback=callback
        self.title("Graph Settings");self.geometry("500x600");self.resizable(False,False);self.configure(bg=BG);self.grab_set()
        self.cfg=dict(cfg) if cfg else {"id":int(time.time()*1000),"title":"New Graph","type":"bar","metric":"daily","range":30,"color":INK,"source_type":"habit","source_id":None}
        if "habit_id" in self.cfg and "source_id" not in self.cfg: self.cfg["source_id"]=self.cfg.pop("habit_id");self.cfg["source_type"]="habit"
        self._cc=self.cfg.get("color",INK);self._build()
    def _row(self,parent,label):
        f=tk.Frame(parent,bg=BG);f.pack(fill="x",pady=6)
        tk.Label(f,text=label,font=self.app.F["mono"],bg=BG,fg=INK4,width=14,anchor="w").pack(side="left");return f
    def _build(self):
        pad=tk.Frame(self,bg=BG);pad.pack(fill="both",expand=True,padx=28,pady=24)
        tk.Label(pad,text="Graph Settings",font=self.app.F["serif_md"],bg=BG,fg=INK).pack(anchor="w",pady=(0,18))
        r=self._row(pad,"TITLE");self.v_title=tk.StringVar(value=self.cfg.get("title",""))
        tk.Entry(r,textvariable=self.v_title,font=self.app.F["body"],bg=SURF,fg=INK,relief="flat",bd=6,insertbackground=INK).pack(side="left",fill="x",expand=True)
        r=self._row(pad,"CHART TYPE");self.v_type=tk.StringVar(value=self.cfg.get("type","bar"))
        for val,lbl in [("bar","Bar"),("line","Line"),("area","Area"),("heatmap","Heatmap")]:
            tk.Radiobutton(r,text=lbl,variable=self.v_type,value=val,font=self.app.F["small"],bg=BG,fg=INK2,activebackground=BG,selectcolor=BG).pack(side="left",padx=(0,8))
        r=self._row(pad,"METRIC");self.v_metric=tk.StringVar(value=self.cfg.get("metric","daily"))
        for val,lbl in [("daily","Daily"),("weekly","Weekly"),("cumulative","Cumulative"),("streak","Streak")]:
            tk.Radiobutton(r,text=lbl,variable=self.v_metric,value=val,font=self.app.F["small"],bg=BG,fg=INK2,activebackground=BG,selectcolor=BG).pack(side="left",padx=(0,8))
        r=self._row(pad,"TIME RANGE");self.v_range=tk.StringVar(value=str(self.cfg.get("range",30)))
        for val,lbl in [("14","2 wks"),("30","30 d"),("60","60 d"),("90","90 d"),("180","6 mo"),("365","1 yr")]:
            tk.Radiobutton(r,text=lbl,variable=self.v_range,value=val,font=self.app.F["small"],bg=BG,fg=INK2,activebackground=BG,selectcolor=BG).pack(side="left",padx=(0,6))
        r=self._row(pad,"COLOUR");self.cprev=tk.Frame(r,bg=self._cc,width=22,height=22,highlightbackground=INK4,highlightthickness=1)
        self.cprev.pack(side="left",padx=(0,8))
        for c in PRESET_COLORS:
            sw=tk.Frame(r,bg=c,width=16,height=16,cursor="hand2",highlightbackground=INK4,highlightthickness=1)
            sw.pack(side="left",padx=2);sw.bind("<Button-1>",lambda e,col=c:self._pick(col))
        tk.Button(r,text="…",font=self.app.F["small"],bg=SURF2,fg=INK3,relief="flat",bd=0,padx=6,cursor="hand2",command=self._custom).pack(side="left",padx=(6,0))
        r=self._row(pad,"DATA SOURCE");self.v_stype=tk.StringVar(value=self.cfg.get("source_type","habit"))
        tk.Radiobutton(r,text="Habit",variable=self.v_stype,value="habit",font=self.app.F["small"],bg=BG,fg=INK2,activebackground=BG,selectcolor=BG,command=self._refresh_src).pack(side="left",padx=(0,8))
        tk.Radiobutton(r,text="Metric",variable=self.v_stype,value="metric",font=self.app.F["small"],bg=BG,fg=INK2,activebackground=BG,selectcolor=BG,command=self._refresh_src).pack(side="left",padx=(0,8))
        r=self._row(pad,"LINKED TO");self._scf=tk.Frame(r,bg=SURF,highlightbackground=INK4,highlightthickness=1);self._scf.pack(side="left")
        self._sc=ttk.Combobox(self._scf,font=self.app.F["small"],state="readonly",width=26);self._sc.pack(padx=1,pady=1)
        self._refresh_src()
        btns=tk.Frame(pad,bg=BG);btns.pack(fill="x",pady=(18,0))
        tk.Button(btns,text="Save",font=self.app.F["bold"],bg=INK,fg=BG,relief="flat",bd=0,padx=22,pady=8,cursor="hand2",command=self._save).pack(side="right")
        tk.Button(btns,text="Cancel",font=self.app.F["body"],bg=SURF2,fg=INK3,relief="flat",bd=0,padx=16,pady=8,cursor="hand2",command=self.destroy).pack(side="right",padx=8)
    def _refresh_src(self):
        st=self.v_stype.get();cur=self.cfg.get("source_id")
        if st=="habit": items=self.app.data.get("habits",[]); names=["(none)"]+[h["name"] for h in items]; ids=[None]+[h["id"] for h in items]
        else: items=self.app.data.get("metrics",[]); names=["(none)"]+[m["name"] for m in items]; ids=[None]+[m["id"] for m in items]
        self._sids=ids;self._sc["values"]=names;self._sc.current(ids.index(cur) if cur in ids else 0)
    def _pick(self,col): self._cc=col;self.cprev.config(bg=col)
    def _custom(self):
        res=colorchooser.askcolor(color=self._cc,parent=self,title="Pick colour")
        if res and res[1]: self._cc=res[1];self.cprev.config(bg=res[1])
    def _save(self):
        self.cfg["title"]=self.v_title.get().strip() or "Graph";self.cfg["type"]=self.v_type.get()
        self.cfg["metric"]=self.v_metric.get();self.cfg["range"]=int(self.v_range.get())
        self.cfg["color"]=self._cc;self.cfg["source_type"]=self.v_stype.get()
        self.cfg["source_id"]=self._sids[self._sc.current()];self.cfg.pop("habit_id",None)
        if self.callback: self.callback(self.cfg)
        self.destroy()

class GraphsView(tk.Frame):
    def __init__(self,parent,app):
        super().__init__(parent,bg=BG);self.app=app
        pad=tk.Frame(self,bg=BG);pad.pack(fill="x",padx=30,pady=(26,0))
        tk.Label(pad,text="Graphs",font=app.F["serif"],bg=BG,fg=INK).pack(side="left")
        tk.Button(pad,text="+ New Graph",font=app.F["small"],bg=INK,fg=BG,relief="flat",bd=0,padx=14,pady=6,cursor="hand2",command=self._new).pack(side="right")
        tk.Label(pad,text="Visualise habits and metrics.",font=app.F["small"],bg=BG,fg=INK4).pack(side="left",padx=14)
        tk.Frame(self,bg=INK4,height=1).pack(fill="x",padx=30,pady=(14,0))
        so,self.gf=make_scroll_area(self);so.pack(fill="both",expand=True,padx=30,pady=(14,10));self._render()
    def _new(self): GraphDialog(self,self.app,callback=self._on_save)
    def _edit(self,cfg): GraphDialog(self,self.app,cfg=cfg,callback=self._on_save)
    def _on_save(self,cfg):
        gs=self.app.data.setdefault("graphs",[]);ix=next((i for i,g in enumerate(gs) if g["id"]==cfg["id"]),None)
        if ix is not None: gs[ix]=cfg
        else: gs.append(cfg)
        self.app.persist();self._render()
    def _del(self,gid):
        self.app.data["graphs"]=[g for g in self.app.data["graphs"] if g["id"]!=gid]
        self.app.persist();self._render()
    def _render(self):
        for w in self.gf.winfo_children(): w.destroy()
        graphs=self.app.data.get("graphs",[])
        if not graphs: tk.Label(self.gf,text='No graphs yet.',font=self.app.F["small"],bg=BG,fg=INK4,pady=40).pack();return
        COLS=2
        for idx,g in enumerate(graphs):
            ri=idx//COLS;ci=idx%COLS
            card=tk.Frame(self.gf,bg=SURF,highlightbackground=INK4,highlightthickness=1)
            card.grid(row=ri,column=ci,padx=8,pady=8,sticky="nsew");self.gf.columnconfigure(ci,weight=1)
            hdr=tk.Frame(card,bg=SURF2);hdr.pack(fill="x")
            tk.Label(hdr,text=g.get("title","Graph"),font=self.app.F["serif_sm"],bg=SURF2,fg=INK,anchor="w").pack(side="left",padx=10,pady=8)
            sid=g.get("source_id") or g.get("habit_id");stype=g.get("source_type","habit")
            if sid:
                if stype=="metric": sn=next((m["name"] for m in self.app.data.get("metrics",[]) if m["id"]==sid),"");sym="◆"
                else: sn=next((h["name"] for h in self.app.data.get("habits",[]) if h["id"]==sid),"");sym="⬤"
                if sn: tk.Label(hdr,text=f"{sym} {sn}",font=self.app.F["mono"],bg=SURF2,fg=g.get("color",INK)).pack(side="left",padx=4)
            tk.Label(hdr,text=g.get("type","bar").upper(),font=self.app.F["mono"],bg=SURF2,fg=INK4).pack(side="left",padx=6)
            tk.Button(hdr,text="×",font=self.app.F["body"],bg=SURF2,fg=INK4,relief="flat",bd=0,cursor="hand2",command=lambda gid=g["id"]:self._del(gid)).pack(side="right",padx=6,pady=6)
            tk.Button(hdr,text="✎",font=self.app.F["body"],bg=SURF2,fg=INK3,relief="flat",bd=0,cursor="hand2",command=lambda gc=dict(g):self._edit(gc)).pack(side="right",padx=2,pady=6)
            gc=GraphCanvas(card,self.app,g,height=220);gc.pack(fill="both",expand=True,padx=4,pady=(4,8))
            card.update_idletasks();gc.draw()


# ══════════════════════════════════════════════════════════════════════════════
# AI COACH  — persistent history, copyable bubbles, custom system prompt
# ══════════════════════════════════════════════════════════════════════════════
def build_context(data):
    today=date.today().isoformat()
    lines=[f"Today is {today}.","","=== USER'S FOCUS DATA ==="]
    for key,label in [("long","Long-term Goals"),("monthly","Monthly Goals"),("weekly","Weekly Goals")]:
        items=data.get(key,[])
        lines.append(f"\n{label}:")
        lines+=[f"  - {i['text']}" for i in items] if items else ["  (none)"]
    lines.append("\nDaily Habits:")
    habits=data.get("habits",[]); checks_all=data.get("checks",{})
    for h in habits:
        checks=set(checks_all.get(str(h["id"]),[])); streak=0; d=date.today()
        if d.isoformat() not in checks: d-=timedelta(1)
        while d.isoformat() in checks: streak+=1; d-=timedelta(1)
        recent_30=sum(1 for i in range(30) if (date.today()-timedelta(i)).isoformat() in checks)
        lines.append(f"  - {h['name']}  |  streak: {streak} days  |  last 30 days: {recent_30}/30")
    if not habits: lines.append("  (none)")
    lines.append("\nMetrics (last 5 entries each):")
    for m in data.get("metrics",[]):
        entries=sorted(m.get("entries",[]),key=lambda e:e["date"],reverse=True)[:5]
        vals=[f"{e['date']}: {e['value']} {m.get('unit','')}" for e in entries]
        lines.append(f"  {m['name']}: "+(",  ".join(vals) if vals else "(no data)"))
    return "\n".join(lines)

class AICoachView(tk.Frame):
    def __init__(self,parent,app):
        super().__init__(parent,bg=BG); self.app=app
        # Use app-level persistent history so switching tabs doesn't clear it
        if not hasattr(app,"_ai_history"): app._ai_history=[]
        if not hasattr(app,"_ai_streaming"): app._ai_streaming=False
        self._streaming_ref=lambda:app._ai_streaming

        # Header
        pad=tk.Frame(self,bg=BG); pad.pack(fill="x",padx=30,pady=(26,0))
        tk.Label(pad,text="AI Coach",font=app.F["serif"],bg=BG,fg=INK).pack(side="left")
        sc=GREEN if app.ollama.status=="ready" else INK4
        st=f"● {app.config.get('ollama_model','?')}" if app.ollama.status=="ready" else f"○ Ollama {app.ollama.status}"
        self._ollama_lbl=tk.Label(pad,text=st,font=app.F["mono"],bg=BG,fg=sc); self._ollama_lbl.pack(side="right")
        tk.Button(pad,text="Clear",font=app.F["small"],bg=SURF2,fg=INK3,relief="flat",bd=0,padx=10,pady=4,cursor="hand2",command=self._clear).pack(side="right",padx=8)
        tk.Label(pad,text="Powered by Ollama — local & private.",font=app.F["small"],bg=BG,fg=INK4).pack(side="left",padx=14)
        tk.Frame(self,bg=INK4,height=1).pack(fill="x",padx=30,pady=(14,0))

        # Chips
        cf=tk.Frame(self,bg=BG); cf.pack(fill="x",padx=30,pady=(10,0))
        tk.Label(cf,text="SUGGESTIONS",font=app.F["mono"],bg=BG,fg=INK4).pack(side="left",padx=(0,10))
        for s in ["Review my week","Analyse my habits","What patterns do you see?","Help me stay on track","Reflect on my goals"]:
            tk.Button(cf,text=s,font=app.F["tiny"],bg=SURF2,fg=INK3,relief="flat",bd=0,padx=10,pady=5,cursor="hand2",command=lambda msg=s:self._send(msg)).pack(side="left",padx=3)

        # Chat area
        chat_outer=tk.Frame(self,bg=BG); chat_outer.pack(fill="both",expand=True,padx=30,pady=(12,0))
        self._cc=tk.Canvas(chat_outer,bg=BG,highlightthickness=0,bd=0)
        sb=tk.Scrollbar(chat_outer,orient="vertical",command=self._cc.yview)
        self._cc.configure(yscrollcommand=sb.set)
        sb.pack(side="right",fill="y"); self._cc.pack(side="left",fill="both",expand=True)
        self._ci=tk.Frame(self._cc,bg=BG)
        self._cw=self._cc.create_window((0,0),window=self._ci,anchor="nw")
        self._ci.bind("<Configure>",lambda e:self._cc.configure(scrollregion=self._cc.bbox("all")))
        self._cc.bind("<Configure>",lambda e:self._cc.itemconfig(self._cw,width=e.width))
        self._cc.bind_all("<MouseWheel>",lambda e:self._cc.yview_scroll(-(e.delta//120),"units"))

        # Input
        io=tk.Frame(self,bg=INK4); io.pack(fill="x",padx=30,pady=(10,16))
        ii=tk.Frame(io,bg=SURF); ii.pack(fill="x",padx=1,pady=1)
        self._entry=tk.Entry(ii,font=app.F["body"],bg=SURF,fg=INK,relief="flat",bd=10,insertbackground=INK)
        self._entry.pack(side="left",fill="both",expand=True)
        self._entry.bind("<Return>",lambda e:self._send())
        self._send_btn=tk.Button(ii,text="Send",font=app.F["bold"],bg=INK,fg=BG,relief="flat",bd=0,padx=18,cursor="hand2",command=self._send)
        self._send_btn.pack(side="right")

        # Restore history bubbles
        if app._ai_history:
            for msg in app._ai_history:
                self._render_bubble(msg["role"],msg["content"])
        else:
            self._render_bubble("assistant",f"Hello. I have full context of your goals, habits, and metrics.\n\nOllama status: {app.ollama.status}. Ask me anything about your progress.")

        if app.ollama.status!="ready": self._poll_ollama()

    def _poll_ollama(self):
        st=self.app.ollama.status
        self._ollama_lbl.config(text=f"● {self.app.config.get('ollama_model','?')}" if st=="ready" else f"○ Ollama {st}",
                                fg=GREEN if st=="ready" else INK4)
        if st not in("ready","error","no_ollama","stopped"): self.after(1500,self._poll_ollama)

    def _clear(self):
        self.app._ai_history=[]
        for w in self._ci.winfo_children(): w.destroy()
        self._render_bubble("assistant","Conversation cleared. What would you like to explore?")

    def _render_bubble(self,role,text):
        is_user=role=="user"
        outer=tk.Frame(self._ci,bg=BG); outer.pack(fill="x",pady=4,padx=8)
        bbg=INK if is_user else SURF2; bfg=BG if is_user else INK2

        # Use Text widget for AI (selectable/copyable), Label for user
        if is_user:
            lbl=tk.Label(outer,text=text,font=self.app.F["body"],bg=bbg,fg=bfg,
                         wraplength=560,justify="left",padx=14,pady=10,anchor="w")
            lbl.pack(side="right")
        else:
            # Text widget — selectable, so user can copy
            txt=tk.Text(outer,font=self.app.F["body"],bg=bbg,fg=bfg,
                        relief="flat",bd=0,padx=14,pady=10,wrap="word",
                        height=1,cursor="arrow",state="normal")
            txt.insert("1.0",text)
            txt.config(state="disabled")
            txt.pack(side="left",fill="x",expand=True)
            # Auto-resize height
            self._resize_text(txt,text)
            # Copy button
            tk.Button(outer,text="⎘",font=self.app.F["tiny"],bg=BG,fg=INK4,
                      relief="flat",bd=0,cursor="hand2",padx=4,
                      command=lambda t=text:self._copy(t)).pack(side="right",anchor="n",pady=6,padx=2)

        tag=tk.Label(outer,text="YOU" if is_user else "AI",font=self.app.F["tiny"],bg=BG,fg=INK4)
        tag.pack(side="right" if is_user else "left",padx=6,anchor="s")
        self._scroll_bottom()
        return txt if not is_user else lbl

    def _resize_text(self,widget,text):
        lines=text.count("\n")+1
        chars=len(text)
        estimated=max(lines,chars//80+1,2)
        widget.config(height=min(estimated,30))

    def _copy(self,text):
        self.clipboard_clear(); self.clipboard_append(text)
        self.app.status_var.set("✓ Copied to clipboard"); self.after(1500,lambda:self.app.status_var.set(""))

    def _scroll_bottom(self):
        self._cc.update_idletasks(); self._cc.yview_moveto(1.0)

    def _send(self,text=None):
        if self.app._ai_streaming: return
        msg=text or self._entry.get().strip()
        if not msg: return
        self._entry.delete(0,"end")
        if self.app.ollama.status!="ready":
            self._render_bubble("assistant",f"Ollama isn't ready (status: {self.app.ollama.status}).\nInstall from ollama.com then restart Focus."); return

        self._render_bubble("user",msg)
        self.app._ai_history.append({"role":"user","content":msg})
        self.app._ai_streaming=True
        self._send_btn.config(state="disabled",text="…")

        # System prompt from config + live data context
        system_prompt=self.app.config.get("system_prompt",DEFAULT_SYSTEM_PROMPT)+"\n\n"+build_context(self.app.data)
        messages=[{"role":"system","content":system_prompt}]+self.app._ai_history

        # Streaming bubble (Text widget)
        ai_txt=self._render_bubble("assistant","")
        full_text=[]

        def on_token(tok):
            full_text.append(tok)
            combined="".join(full_text)
            def update():
                ai_txt.config(state="normal"); ai_txt.delete("1.0","end")
                ai_txt.insert("1.0",combined); ai_txt.config(state="disabled")
                self._resize_text(ai_txt,combined); self._scroll_bottom()
            self.after(0,update)

        def on_done(full):
            self.app._ai_history.append({"role":"assistant","content":full})
            self.app._ai_streaming=False
            self.after(0,lambda:self._send_btn.config(state="normal",text="Send"))

        def on_error(err):
            def show():
                ai_txt.config(state="normal"); ai_txt.delete("1.0","end")
                ai_txt.insert("1.0",f"Error: {err}"); ai_txt.config(state="disabled")
                self._resize_text(ai_txt,f"Error: {err}")
            self.after(0,show); self.app._ai_streaming=False
            self.after(0,lambda:self._send_btn.config(state="normal",text="Send"))

        self.app.ollama.chat(messages,on_token=on_token,on_done=on_done,on_error=on_error)


# ══════════════════════════════════════════════════════════════════════════════
# ENTRY
# ══════════════════════════════════════════════════════════════════════════════
if __name__=="__main__":
    App().mainloop()
