import tkinter as tk
from tkinter import messagebox
import subprocess, threading, os, sys, json, re, time, ctypes, ctypes.wintypes
from datetime import datetime

# ─── Configuração ─────────────────────────────────────────────
SCRCPY_EXE = "base"
ADB_EXE    = "adb.exe"
WIFI_PORT  = 9990
DATA_FILE  = "devices_data.json"
POLL_MS    = 2500
MUTEX_NAME = "MyAndroid_SingleInstance_Mutex"

DEFAULT_DEV_CFG = {
    "fps":        "60",
    "res":        "1080",
    "bitrate":    "8M",
    "audio":      True,
    "auto_conn":  False,   # auto-reconexão
}
# ──────────────────────────────────────────────────────────────

def get_base_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

BASE_DIR   = get_base_dir()
SCRCPY     = os.path.join(BASE_DIR, SCRCPY_EXE)
ADB        = os.path.join(BASE_DIR, ADB_EXE)
DATA_PATH  = os.path.join(BASE_DIR, DATA_FILE)
PRINTS_DIR = os.path.join(BASE_DIR, "Prints")

# ─── Win32 helpers ────────────────────────────────────────────
_user32  = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32

def win_find(title):
    return _user32.FindWindowW(None, title)

def win_rect(hwnd):
    r = ctypes.wintypes.RECT()
    _user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r

def win_is_minimized(hwnd):
    # WINDOWPLACEMENT.showCmd está no offset 8 (uint32)
    class WINDOWPLACEMENT(ctypes.Structure):
        _fields_ = [("length",           ctypes.c_uint),
                    ("flags",            ctypes.c_uint),
                    ("showCmd",          ctypes.c_uint),
                    ("ptMinPosition",    ctypes.wintypes.POINT),
                    ("ptMaxPosition",    ctypes.wintypes.POINT),
                    ("rcNormalPosition", ctypes.wintypes.RECT)]
    wp = WINDOWPLACEMENT()
    wp.length = ctypes.sizeof(wp)
    _user32.GetWindowPlacement(hwnd, ctypes.byref(wp))
    return wp.showCmd == 2  # SW_SHOWMINIMIZED

def win_foreground(hwnd):
    _user32.ShowWindow(hwnd, 9)   # SW_RESTORE
    _user32.SetForegroundWindow(hwnd)

# ─── Instância única ──────────────────────────────────────────
def ensure_single_instance():
    mutex = _kernel32.CreateMutexW(None, True, MUTEX_NAME)
    if _kernel32.GetLastError() == 183:
        hwnd = win_find("My Android")
        if hwnd:
            win_foreground(hwnd)
        sys.exit(0)
    return mutex

# ─── Devices data ─────────────────────────────────────────────
def load_data():
    if os.path.exists(DATA_PATH):
        try:
            with open(DATA_PATH, "r", encoding="utf-8") as f:
                raw = json.load(f)
            return {k: v for k, v in raw.items() if not is_wifi_serial(k)}
        except:
            pass
    return {}

def save_data(data):
    try:
        with open(DATA_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except:
        pass

def get_dev_cfg(data, usb_serial):
    entry = data.get(usb_serial, {})
    cfg   = dict(DEFAULT_DEV_CFG)
    for k in DEFAULT_DEV_CFG:
        if k in entry:
            cfg[k] = entry[k]
    return cfg

def save_dev_cfg(data, usb_serial, cfg):
    entry = data.setdefault(usb_serial, {})
    for k in DEFAULT_DEV_CFG:
        entry[k] = cfg[k]
    save_data(data)

# ─── ADB ──────────────────────────────────────────────────────
def run_adb(*args, timeout=8):
    try:
        r = subprocess.run(
            [ADB, *args], capture_output=True, text=True,
            timeout=timeout, cwd=BASE_DIR,
            creationflags=subprocess.CREATE_NO_WINDOW)
        return r.stdout.strip()
    except:
        return ""

def is_wifi_serial(s):
    return bool(re.match(r'^\d+\.\d+\.\d+\.\d+:\d+$', s))

def get_ip_from_device(serial):
    out = run_adb("-s", serial, "shell", "ifconfig wlan0")
    m = re.search(r'inet addr:([\d.]+)', out)
    if m: return m.group(1)
    out = run_adb("-s", serial, "shell", "ip addr show wlan0")
    m = re.search(r'inet ([\d.]+)/', out)
    if m: return m.group(1)
    return None

def fetch_raw_devices():
    out  = run_adb("devices", "-l")
    devs = []
    for linha in out.splitlines()[1:]:
        linha = linha.strip()
        if not linha: continue
        partes = linha.split()
        if len(partes) < 2: continue
        serial, status = partes[0], partes[1]
        modelo = next((p.replace("model:","").replace("_"," ")
                       for p in partes if p.startswith("model:")), serial)
        devs.append({"serial": serial, "modelo": modelo, "status": status})
    return devs

def build_groups(raw_devs, data):
    usb_map, wifi_map = {}, {}
    for d in raw_devs:
        (wifi_map if is_wifi_serial(d["serial"]) else usb_map)[d["serial"]] = d
    groups = []
    for usb_serial, entry in data.items():
        usb_d       = usb_map.get(usb_serial)
        usb_on      = usb_d is not None and usb_d["status"] == "device"
        modelo      = usb_d["modelo"] if usb_d else entry.get("_modelo", usb_serial)
        wifi_serial = entry.get("wifi_serial")
        wifi_on     = False
        if wifi_serial:
            wd      = wifi_map.get(wifi_serial)
            wifi_on = wd is not None and wd["status"] != "offline"
        if not usb_on and not wifi_on:
            continue
        groups.append({"key": usb_serial, "usb_serial": usb_serial,
                        "usb_on": usb_on, "wifi_serial": wifi_serial,
                        "wifi_on": wifi_on, "modelo": modelo})
    return groups

# ─── Título da janela scrcpy ──────────────────────────────────
def build_window_title(nome, tipo, cfg):
    audio_icon = "🔊" if cfg.get("audio", True) else "🔇"
    fps  = cfg.get("fps", "60")
    res  = cfg.get("res", "1080")
    return f"{nome} - {tipo} - {fps}FPS - {res}P {audio_icon}"

# ─── Lança scrcpy ─────────────────────────────────────────────
def launch_scrcpy(target, title, cfg):
    env = os.environ.copy()
    env["SCRCPY_SERVER_PATH"] = os.path.join(BASE_DIR, "server")

    fps_val = cfg.get("fps", "60")
    res_val = cfg.get("res", "1080")
    bit_val = cfg.get("bitrate", "8M")

    cmd = [SCRCPY,
           "-s", target,
           "--window-title", title,
           "--gamepad=uhid",
           "--print-fps",
           f"--max-fps={fps_val}",
           "--stay-awake",
           "-m", res_val,
           "-b", bit_val]
    if not cfg.get("audio", True):
        cmd.append("--no-audio")

    proc = subprocess.Popen(cmd, cwd=BASE_DIR, env=env,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    return proc

# ─── Toolbar grudada no scrcpy ────────────────────────────────
class DeviceToolbar(tk.Toplevel):
    FOLLOW_MS = 80    # ms entre verificações de posição
    TOOLBAR_W = 48    # largura da toolbar

    def __init__(self, parent, serial, nome, window_title,
                 open_settings_cb, on_close_cb=None):
        super().__init__(parent)
        self.serial           = serial
        self.nome             = nome
        self.window_title     = window_title
        self.open_settings_cb = open_settings_cb
        self.on_close_cb      = on_close_cb
        self._following       = True
        self._scrcpy_hwnd     = None
        self._last_rect       = None

        self.overrideredirect(True)
        self.configure(bg="#141414")
        self.attributes("-topmost", False)   # NÃO fica acima de tudo
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build()
        self.update_idletasks()

        # Começa oculto até achar o scrcpy
        self.withdraw()
        self._follow_loop()

    # ── Layout ────────────────────────────────────────────────
    def _build(self):
        # ── TOP: cfg, print, vol+, vol- ──
        top = tk.Frame(self, bg="#141414")
        top.pack(side="top", fill="x")

        def tbtn(parent, sym, tip, cmd):
            b = tk.Button(parent, text=sym,
                          font=("Segoe UI Emoji", 15),
                          bg="#141414", fg="#cccccc",
                          activebackground="#2a2a2a",
                          activeforeground="#ffffff",
                          relief="flat", cursor="hand2",
                          width=2, pady=7, bd=0,
                          command=cmd)
            b.pack(fill="x", pady=1)
            b.bind("<Enter>", lambda e, t=tip: self._tip(t))
            b.bind("<Leave>", lambda e: self._tip(""))
            return b

        def sep(parent):
            tk.Frame(parent, bg="#2a2a2a", height=1).pack(
                fill="x", padx=5, pady=2)

        tbtn(top, "⚙",  "Configurações",  self.open_settings_cb)
        sep(top)
        tbtn(top, "📷", "Print da tela",  self._screenshot)
        sep(top)
        tbtn(top, "🔊", "Volume +",       self._vol_up)
        tbtn(top, "🔉", "Volume −",       self._vol_down)

        # ── SPACER ──
        self._spacer = tk.Frame(self, bg="#141414")
        self._spacer.pack(fill="both", expand=True)

        # ── BOTTOM: nav ──
        sep(self)
        bot = tk.Frame(self, bg="#141414")
        bot.pack(side="bottom", fill="x")

        tbtn(bot, "◀", "Voltar",    self._nav_back)
        tbtn(bot, "⏺", "Home",      self._nav_home)
        tbtn(bot, "▦", "Recentes",  self._nav_recents)

        # Tooltip
        self.lbl_tip = tk.Label(self, text="",
                                font=("Segoe UI", 6),
                                bg="#141414", fg="#555555",
                                wraplength=self.TOOLBAR_W - 2)
        self.lbl_tip.pack(side="bottom", fill="x")

    def _tip(self, text):
        self.lbl_tip.config(text=text)

    # ── Seguimento ────────────────────────────────────────────
    def _follow_loop(self):
        if not self._following:
            return
        try:
            self._snap()
        except Exception:
            pass
        self.after(self.FOLLOW_MS, self._follow_loop)

    def _find_hwnd(self):
        hwnd = win_find(self.window_title)
        if hwnd:
            self._scrcpy_hwnd = hwnd
        return self._scrcpy_hwnd

    def _snap(self):
        hwnd = self._find_hwnd()
        if not hwnd:
            return

        if win_is_minimized(hwnd):
            self.withdraw()
            return

        self.deiconify()

        r = win_rect(hwnd)
        new_rect = (r.left, r.top, r.right, r.bottom)
        if new_rect == self._last_rect:
            return
        self._last_rect = new_rect

        # Cola EXATAMENTE na borda direita, sem gap
        sx = r.right
        sy = r.top
        sh = r.bottom - r.top

        self.geometry(f"{self.TOOLBAR_W}x{sh}+{sx}+{sy}")

        # Mantém a toolbar imediatamente atrás do scrcpy na ordem Z
        self._stay_behind(hwnd)

    def _stay_behind(self, scrcpy_hwnd):
        """Coloca a toolbar logo atrás da janela do scrcpy na ordem Z."""
        HWND_NOTOPMOST = ctypes.wintypes.HWND(-2)
        SWP_NOACTIVATE  = 0x0010
        SWP_NOMOVE      = 0x0002
        SWP_NOSIZE      = 0x0001
        SWP_FLAGS       = SWP_NOACTIVATE | SWP_NOMOVE | SWP_NOSIZE

        # Primeiro garante que toolbar NÃO é always-on-top
        toolbar_hwnd = self.winfo_id()
        ctypes.windll.user32.SetWindowPos(
            toolbar_hwnd, HWND_NOTOPMOST, 0, 0, 0, 0, SWP_FLAGS)

        # Coloca a toolbar imediatamente DEPOIS do scrcpy na ordem Z
        # (scrcpy.hwnd = insert after → toolbar fica logo abaixo)
        ctypes.windll.user32.SetWindowPos(
            toolbar_hwnd, scrcpy_hwnd, 0, 0, 0, 0, SWP_FLAGS)

    # ── Fechar ────────────────────────────────────────────────
    def _on_close(self):
        self._following = False
        if self.on_close_cb:
            self.on_close_cb()
        try:
            self.destroy()
        except Exception:
            pass

    # ── Ações ────────────────────────────────────────────────
    def _screenshot(self):
        os.makedirs(PRINTS_DIR, exist_ok=True)
        ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(PRINTS_DIR, f"print_{ts}.png")
        def run():
            try:
                out = subprocess.check_output(
                    [ADB, "-s", self.serial, "exec-out", "screencap", "-p"],
                    cwd=BASE_DIR,
                    creationflags=subprocess.CREATE_NO_WINDOW)
                with open(path, "wb") as f:
                    f.write(out)
                self.after(0, lambda: messagebox.showinfo(
                    "Print salvo", f"Salvo em:\nPrints\\print_{ts}.png"))
            except Exception as ex:
                self.after(0, lambda: messagebox.showerror("Erro", str(ex)))
        threading.Thread(target=run, daemon=True).start()

    def _adb(self, *args):
        threading.Thread(
            target=lambda: run_adb("-s", self.serial, *args),
            daemon=True).start()

    def _vol_up(self):    self._adb("shell", "input keyevent KEYCODE_VOLUME_UP")
    def _vol_down(self):  self._adb("shell", "input keyevent KEYCODE_VOLUME_DOWN")
    def _nav_back(self):  self._adb("shell", "input keyevent KEYCODE_BACK")
    def _nav_home(self):  self._adb("shell", "input keyevent KEYCODE_HOME")
    def _nav_recents(self): self._adb("shell", "input keyevent KEYCODE_APP_SWITCH")


# ─── Janela de Configurações ──────────────────────────────────
class SettingsWindow(tk.Toplevel):
    # Opções de cada campo + "Custom"
    FPS_OPTS  = ["30", "60", "120", "240"]
    RES_OPTS  = ["540", "720", "1080", "1440"]
    BIT_OPTS  = ["4M", "8M", "16M", "32M"]

    def __init__(self, parent, usb_serial, nome, data, on_save):
        super().__init__(parent)
        self.usb_serial = usb_serial
        self.data       = data
        self.on_save    = on_save
        self.cfg        = get_dev_cfg(data, usb_serial)

        self.title(f"Configurações — {nome}")
        self.geometry("360x340")
        self.resizable(False, False)
        self.configure(bg="#1e1e1e")
        self.grab_set()
        self._build()

    def _build(self):
        tk.Label(self, text="Configurações de Transmissão",
                 font=("Segoe UI", 11, "bold"),
                 bg="#1e1e1e", fg="#ffffff").pack(pady=(14, 4))

        self.var_fps  = tk.StringVar(value=self.cfg["fps"])
        self.var_res  = tk.StringVar(value=self.cfg["res"])
        self.var_bit  = tk.StringVar(value=self.cfg["bitrate"])
        self.var_aud  = tk.BooleanVar(value=self.cfg["audio"])
        self.var_auto = tk.BooleanVar(value=self.cfg.get("auto_conn", False))

        pad = {"padx": 20, "pady": 4}

        def dropdown_row(label, var, options, all_opts):
            f = tk.Frame(self, bg="#1e1e1e")
            f.pack(fill="x", **pad)
            tk.Label(f, text=label, font=("Segoe UI", 9),
                     bg="#1e1e1e", fg="#aaaaaa",
                     width=14, anchor="w").pack(side="left")

            # Valor exibido no botão
            display = tk.StringVar(value=var.get()
                                   if var.get() in all_opts else "Custom")
            btn_dd = tk.Button(f, textvariable=display,
                               font=("Segoe UI", 8, "bold"),
                               bg="#1976d2", fg="#ffffff",
                               activebackground="#1565c0",
                               relief="flat", cursor="hand2",
                               padx=10, pady=3, width=8)
            btn_dd.pack(side="left", padx=2)

            # Entry para Custom (oculto por padrão)
            ent_var = tk.StringVar(value=var.get())
            ent = tk.Entry(f, textvariable=ent_var,
                           font=("Segoe UI", 8),
                           bg="#2d2d2d", fg="#ffffff",
                           insertbackground="#ffffff",
                           relief="flat", width=8)

            def show_menu():
                menu = tk.Menu(self, tearoff=0,
                               bg="#2d2d2d", fg="#ffffff",
                               activebackground="#1976d2",
                               activeforeground="#ffffff",
                               font=("Segoe UI", 9))
                for opt in all_opts:
                    def pick(o=opt):
                        var.set(o)
                        display.set(o)
                        ent.pack_forget()
                    menu.add_command(label=opt, command=pick)

                def pick_custom():
                    display.set("Custom")
                    ent.pack(side="left", padx=2)
                    ent.focus_set()
                    def sync(*_):
                        var.set(ent_var.get())
                    ent_var.trace_add("write", sync)
                menu.add_separator()
                menu.add_command(label="Custom...", command=pick_custom)

                menu.tk_popup(btn_dd.winfo_rootx(),
                              btn_dd.winfo_rooty() + btn_dd.winfo_height())

            btn_dd.config(command=show_menu)

            # Se valor atual é custom, mostra o entry
            if var.get() not in all_opts:
                display.set("Custom")
                ent.pack(side="left", padx=2)

        dropdown_row("FPS",       self.var_fps, self.FPS_OPTS, self.FPS_OPTS)
        dropdown_row("Resolução", self.var_res, self.RES_OPTS, self.RES_OPTS)
        dropdown_row("Bitrate",   self.var_bit, self.BIT_OPTS, self.BIT_OPTS)

        # Áudio
        fa = tk.Frame(self, bg="#1e1e1e")
        fa.pack(fill="x", **pad)
        tk.Label(fa, text="Áudio no Windows",
                 font=("Segoe UI", 9), bg="#1e1e1e", fg="#aaaaaa",
                 width=14, anchor="w").pack(side="left")
        tk.Checkbutton(fa, variable=self.var_aud,
                       text="Ativado", font=("Segoe UI", 9),
                       bg="#1e1e1e", fg="#ffffff",
                       selectcolor="#1976d2",
                       activebackground="#1e1e1e",
                       cursor="hand2").pack(side="left")

        # Auto Conexão
        fc = tk.Frame(self, bg="#1e1e1e")
        fc.pack(fill="x", **pad)
        tk.Label(fc, text="Auto Conexão",
                 font=("Segoe UI", 9), bg="#1e1e1e", fg="#aaaaaa",
                 width=14, anchor="w").pack(side="left")
        tk.Checkbutton(fc, variable=self.var_auto,
                       text="Conectar automaticamente",
                       font=("Segoe UI", 9),
                       bg="#1e1e1e", fg="#ffffff",
                       selectcolor="#1976d2",
                       activebackground="#1e1e1e",
                       cursor="hand2").pack(side="left")

        tk.Button(self, text="💾  Salvar e Reconectar",
                  font=("Segoe UI", 10, "bold"),
                  bg="#1976d2", fg="#ffffff",
                  activebackground="#1565c0",
                  relief="flat", cursor="hand2",
                  padx=20, pady=7,
                  command=self._save).pack(pady=14)

    def _save(self):
        self.cfg["fps"]       = self.var_fps.get()
        self.cfg["res"]       = self.var_res.get()
        self.cfg["bitrate"]   = self.var_bit.get()
        self.cfg["audio"]     = self.var_aud.get()
        self.cfg["auto_conn"] = self.var_auto.get()
        save_dev_cfg(self.data, self.usb_serial, self.cfg)
        self.on_save(self.cfg)
        self.destroy()


# ─── App principal ────────────────────────────────────────────
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("My Android")
        self.geometry("560x440")
        self.resizable(False, False)
        self.configure(bg="#1e1e1e")

        ico = os.path.join(BASE_DIR, "icone.ico")
        if os.path.exists(ico):
            try:
                self.iconbitmap(ico)
            except:
                pass

        self.data      = load_data()
        self._rows     = {}
        self._polling  = True
        # key → {"proc": Popen, "toolbar": DeviceToolbar,
        #         "title": str, "modo": str}
        self._sessions = {}

        self._build_ui()
        self._poll()

    def _build_ui(self):
        hdr = tk.Frame(self, bg="#111111", pady=10)
        hdr.pack(fill="x")
        tk.Label(hdr, text="My Android",
                 font=("Segoe UI", 15, "bold"),
                 bg="#111111", fg="#ffffff").pack()
        tk.Label(hdr, text="Dispositivos detectados automaticamente",
                 font=("Segoe UI", 8), bg="#111111", fg="#555555").pack()

        self.frame_lista = tk.Frame(self, bg="#1e1e1e")
        self.frame_lista.pack(fill="both", expand=True, padx=18, pady=10)

        ftr = tk.Frame(self, bg="#141414", pady=5)
        ftr.pack(fill="x")
        self.lbl_status = tk.Label(ftr, text="Aguardando...",
                                   font=("Segoe UI", 8),
                                   bg="#141414", fg="#444444")
        self.lbl_status.pack(side="left", padx=14)

    # ── Polling ───────────────────────────────────────────────
    def _poll(self):
        if not self._polling: return
        threading.Thread(target=self._fetch, daemon=True).start()

    def _fetch(self):
        raw = fetch_raw_devices()
        for d in raw:
            if is_wifi_serial(d["serial"]): continue
            if d["status"] != "device": continue
            usb = d["serial"]
            ip  = get_ip_from_device(usb)
            if not ip: continue
            new_wifi = f"{ip}:{WIFI_PORT}"
            entry    = self.data.setdefault(usb, {})
            old_wifi = entry.get("wifi_serial")
            entry["_modelo"] = d["modelo"]
            if old_wifi != new_wifi:
                if old_wifi: run_adb("disconnect", old_wifi)
                entry["wifi_serial"] = new_wifi
                save_data(self.data)
                run_adb("-s", usb, "tcpip", str(WIFI_PORT))
                time.sleep(0.6)
                run_adb("connect", new_wifi)
            else:
                run_adb("connect", new_wifi)

        groups = build_groups(raw, self.data)
        self.after(0, self._update_ui, groups)

    def _update_ui(self, groups):
        keys_now = {g["key"] for g in groups}

        for k in list(self._rows.keys()):
            if k not in keys_now:
                self._rows[k]["frame"].destroy()
                del self._rows[k]

        for g in groups:
            if g["key"] not in self._rows:
                self._build_row(g)
            else:
                self._update_row(g)

        # ── Auto conexão ──────────────────────────────────────
        for g in groups:
            key = g["key"]
            cfg = get_dev_cfg(self.data, key)
            if cfg.get("auto_conn") and key not in self._sessions:
                # Escolhe modo disponível: USB > WiFi
                if g["usb_on"]:
                    row = self._rows.get(key)
                    if row:
                        row["modo_var"].set("usb")
                    self._conectar(key)
                elif g["wifi_on"]:
                    row = self._rows.get(key)
                    if row:
                        row["modo_var"].set("wifi")
                    self._conectar(key)

        # ── Auto reconexão (perdeu USB/WiFi com sessão ativa) ──
        for key, sess in list(self._sessions.items()):
            if not sess.get("proc"): continue
            if sess["proc"].poll() is None: continue  # ainda rodando
            # processo encerrou — tenta reconectar se auto_conn
            cfg = get_dev_cfg(self.data, key)
            if not cfg.get("auto_conn"): continue
            g_list = [g for g in groups if g["key"] == key]
            if not g_list: continue
            g = g_list[0]
            # Modo oposto ao que estava
            old_modo = sess.get("modo", "usb")
            if old_modo == "usb" and g["wifi_on"]:
                row = self._rows.get(key)
                if row: row["modo_var"].set("wifi")
                self._session_ended(key)
                self._conectar(key)
            elif old_modo == "wifi" and g["usb_on"]:
                row = self._rows.get(key)
                if row: row["modo_var"].set("usb")
                self._session_ended(key)
                self._conectar(key)

        n = len(groups)
        self.lbl_status.config(
            text=(f"{n} dispositivo{'s' if n!=1 else ''} encontrado{'s' if n!=1 else ''}"
                  if n else "Nenhum dispositivo conectado"))
        self.after(POLL_MS, self._poll)

    # ── Row ───────────────────────────────────────────────────
    def _get_name(self, key, modelo):
        return self.data.get(key, {}).get("name", modelo)

    def _build_row(self, g):
        key    = g["key"]
        modelo = g["modelo"]

        frame = tk.Frame(self.frame_lista, bg="#2a2a2a",
                         pady=7, padx=10,
                         highlightbackground="#3a3a3a",
                         highlightthickness=1)
        frame.pack(fill="x", pady=3)

        left = tk.Frame(frame, bg="#2a2a2a")
        left.pack(side="left", fill="x", expand=True)

        tk.Label(left, text="📱", font=("Segoe UI", 16),
                 bg="#2a2a2a").pack(side="left", padx=(0, 7))

        info = tk.Frame(left, bg="#2a2a2a")
        info.pack(side="left")

        nome     = self._get_name(key, modelo)
        lbl_nome = tk.Label(info, text=nome,
                            font=("Segoe UI", 10, "bold"),
                            bg="#2a2a2a", fg="#ffffff",
                            cursor="hand2", anchor="w")
        lbl_nome.pack(anchor="w")
        lbl_nome.bind("<Button-1>",
                      lambda e, k=key, m=modelo: self._editar_nome(k, m))

        lbl_usb  = tk.Label(info, text="", font=("Segoe UI", 7),
                            bg="#2a2a2a", anchor="w")
        lbl_usb.pack(anchor="w")
        lbl_wifi = tk.Label(info, text="", font=("Segoe UI", 7),
                            bg="#2a2a2a", anchor="w")
        lbl_wifi.pack(anchor="w")

        right    = tk.Frame(frame, bg="#2a2a2a")
        right.pack(side="right", anchor="center")

        modo_var = tk.StringVar(value="usb")

        btn_cfg = tk.Button(right, text="⚙",
                            font=("Segoe UI", 11),
                            bg="#2a2a2a", fg="#666666",
                            activebackground="#333333",
                            activeforeground="#aaaaaa",
                            relief="flat", cursor="hand2",
                            padx=4, pady=4, bd=0)
        btn_cfg.pack(side="left", padx=(0, 4))
        btn_cfg.config(command=lambda k=key: self._open_settings(k))

        btn_modo = tk.Button(right, text="USB ▾",
                             font=("Segoe UI", 8, "bold"),
                             bg="#1a3a1a", fg="#4caf50",
                             activebackground="#224422",
                             activeforeground="#66bb6a",
                             relief="flat", cursor="hand2",
                             padx=9, pady=5, bd=0)
        btn_modo.pack(side="left", padx=(0, 2))

        btn_conectar = tk.Button(right, text="Conectar",
                                 font=("Segoe UI", 9, "bold"),
                                 bg="#1976d2", fg="#ffffff",
                                 activebackground="#1565c0",
                                 activeforeground="#ffffff",
                                 relief="flat", cursor="hand2",
                                 padx=11, pady=5, bd=0)
        btn_conectar.pack(side="left")

        self._rows[key] = {
            "frame": frame, "lbl_nome": lbl_nome,
            "lbl_usb": lbl_usb, "lbl_wifi": lbl_wifi,
            "btn_modo": btn_modo, "btn_conectar": btn_conectar,
            "btn_cfg": btn_cfg,
            "modo_var": modo_var, "modelo": modelo, "g": g,
            "tem_gaveta": False,
        }

        btn_modo.config(command=lambda k=key: self._abrir_menu(k))
        btn_conectar.config(command=lambda k=key: self._conectar(k))
        self._update_row(g)

    def _update_row(self, g):
        key = g["key"]
        row = self._rows.get(key)
        if not row: return
        row["g"] = g

        if g["usb_serial"]:
            cor = "#4caf50" if g["usb_on"] else "#555555"
            row["lbl_usb"].config(
                text=f"🔌 {g['usb_serial']}  •  {'ON' if g['usb_on'] else 'OFF'}",
                fg=cor)
        else:
            row["lbl_usb"].config(text="")

        if g["wifi_serial"]:
            cor = "#4caf50" if g["wifi_on"] else "#555555"
            row["lbl_wifi"].config(
                text=f"📶 {g['wifi_serial']}  •  {'ON' if g['wifi_on'] else 'OFF'}",
                fg=cor)
        else:
            row["lbl_wifi"].config(text="")

        usb_on  = g["usb_on"]
        wifi_on = g["wifi_on"]
        modo    = row["modo_var"].get()

        if modo == "usb" and not usb_on and wifi_on:
            modo = "wifi"; row["modo_var"].set("wifi")
        elif modo == "wifi" and not wifi_on and usb_on:
            modo = "usb";  row["modo_var"].set("usb")

        btn = row["btn_modo"]
        if usb_on and wifi_on:
            row["tem_gaveta"] = True
            btn.config(state="normal", cursor="hand2")
            if modo == "wifi":
                btn.config(text="Wi-Fi ▾", bg="#1a2a3a", fg="#42a5f5",
                           activebackground="#1e3550",
                           activeforeground="#64b5f6")
                row["btn_conectar"].config(bg="#00796b",
                                           activebackground="#00695c")
            else:
                btn.config(text="USB ▾", bg="#1a3a1a", fg="#4caf50",
                           activebackground="#224422",
                           activeforeground="#66bb6a")
                row["btn_conectar"].config(bg="#1976d2",
                                           activebackground="#1565c0")
        elif usb_on:
            row["tem_gaveta"] = False
            row["modo_var"].set("usb"); modo = "usb"
            btn.config(text="USB", state="disabled", cursor="",
                       bg="#1a3a1a", fg="#4caf50",
                       activebackground="#1a3a1a", activeforeground="#4caf50")
            row["btn_conectar"].config(bg="#1976d2",
                                       activebackground="#1565c0")
        else:
            row["tem_gaveta"] = False
            row["modo_var"].set("wifi"); modo = "wifi"
            btn.config(text="Wi-Fi", state="disabled", cursor="",
                       bg="#1a2a3a", fg="#42a5f5",
                       activebackground="#1a2a3a", activeforeground="#42a5f5")
            row["btn_conectar"].config(bg="#00796b",
                                       activebackground="#00695c")

        has_session = key in self._sessions
        row["frame"].config(
            highlightbackground="#1976d2" if has_session else "#3a3a3a")

    # ── Menu USB/WiFi ─────────────────────────────────────────
    def _abrir_menu(self, key):
        row = self._rows.get(key)
        if not row or not row["tem_gaveta"]: return
        g    = row["g"]
        modo = row["modo_var"].get()

        menu = tk.Menu(self, tearoff=0, bg="#2d2d2d", fg="#ffffff",
                       activebackground="#333333", activeforeground="#ffffff",
                       font=("Segoe UI", 9), bd=0)

        def set_usb():
            row["modo_var"].set("usb")
            row["btn_modo"].config(text="USB ▾", bg="#1a3a1a", fg="#4caf50",
                                   activebackground="#224422",
                                   activeforeground="#66bb6a")
            row["btn_conectar"].config(bg="#1976d2",
                                       activebackground="#1565c0")

        def set_wifi():
            row["modo_var"].set("wifi")
            row["btn_modo"].config(text="Wi-Fi ▾", bg="#1a2a3a", fg="#42a5f5",
                                   activebackground="#1e3550",
                                   activeforeground="#64b5f6")
            row["btn_conectar"].config(bg="#00796b",
                                       activebackground="#00695c")

        if g["usb_on"]:
            menu.add_command(label="🔌  USB" + ("  ✓" if modo=="usb" else ""),
                             command=set_usb)
        if g["wifi_on"]:
            menu.add_command(label="📶  Wi-Fi" + ("  ✓" if modo=="wifi" else ""),
                             command=set_wifi)

        btn = row["btn_modo"]
        menu.tk_popup(btn.winfo_rootx(),
                      btn.winfo_rooty() + btn.winfo_height())

    # ── Configurações ─────────────────────────────────────────
    def _open_settings(self, key):
        row  = self._rows.get(key)
        if not row: return
        nome = self._get_name(key, row["modelo"])

        def on_save(new_cfg):
            if key in self._sessions:
                self._reconectar(key, new_cfg)

        SettingsWindow(self, key, nome, self.data, on_save)

    def _reconectar(self, key, cfg):
        sess = self._sessions.get(key)
        if sess:
            tb = sess.get("toolbar")
            if tb:
                try:
                    if tb.winfo_exists(): tb.destroy()
                except:
                    pass
            proc = sess.get("proc")
            if proc:
                try: proc.terminate()
                except: pass
            del self._sessions[key]
        self.after(800, lambda: self._conectar(key, force_cfg=cfg))

    # ── Conectar ──────────────────────────────────────────────
    def _conectar(self, key, force_cfg=None):
        row = self._rows.get(key)
        if not row: return
        g    = row["g"]
        modo = row["modo_var"].get()
        nome = self._get_name(key, row["modelo"])
        btn  = row["btn_conectar"]
        cfg  = force_cfg if force_cfg else get_dev_cfg(self.data, key)

        target = g["wifi_serial"] if modo=="wifi" else g["usb_serial"]
        if not target:
            messagebox.showerror("Erro", "Serial não disponível.")
            return

        tipo  = "WI-FI" if modo=="wifi" else "USB"
        title = build_window_title(nome, tipo, cfg)

        # ── Gerencia sessão existente ──────────────────────────
        sess = self._sessions.get(key)
        if sess:
            existing_title = sess.get("title", "")
            existing_hwnd  = win_find(existing_title)

            if existing_title == title and existing_hwnd:
                # Mesmo modo e janela já existe → só traz para frente
                win_foreground(existing_hwnd)
                self.after(600, lambda: btn.config(
                    state="normal", text="Conectar"))
                return
            else:
                # Modo diferente → fecha a sessão atual primeiro
                tb = sess.get("toolbar")
                if tb:
                    try:
                        if tb.winfo_exists(): tb.destroy()
                    except: pass
                proc = sess.get("proc")
                if proc:
                    try: proc.terminate()
                    except: pass
                # Aguarda o processo encerrar
                if proc:
                    try: proc.wait(timeout=3)
                    except: pass
                del self._sessions[key]

        btn.config(state="disabled", text="Aguarde...")

        def run():
            try:
                proc = launch_scrcpy(target, title, cfg)

                def make_session():
                    tb = DeviceToolbar(
                        self,
                        serial=target,
                        nome=nome,
                        window_title=title,
                        open_settings_cb=lambda k=key: self._open_settings(k),
                        on_close_cb=lambda k=key: self._session_ended(k))
                    self._sessions[key] = {
                        "proc":    proc,
                        "toolbar": tb,
                        "title":   title,
                        "modo":    modo,
                    }
                    row["frame"].config(highlightbackground="#1976d2")

                self.after(0, make_session)

                def watch():
                    proc.wait()
                    self.after(0, lambda: self._session_ended(key))
                threading.Thread(target=watch, daemon=True).start()

            except FileNotFoundError:
                self.after(0, messagebox.showerror, "Erro",
                           f"Arquivo 'base' não encontrado em:\n{BASE_DIR}")
            finally:
                self.after(500, lambda: btn.config(
                    state="normal", text="Conectar"))

        threading.Thread(target=run, daemon=True).start()

    def _session_ended(self, key):
        sess = self._sessions.pop(key, None)
        if sess:
            tb = sess.get("toolbar")
            if tb:
                try:
                    if tb.winfo_exists(): tb.destroy()
                except: pass
        row = self._rows.get(key)
        if row:
            row["frame"].config(highlightbackground="#3a3a3a")

    # ── Editar nome ───────────────────────────────────────────
    def _editar_nome(self, key, modelo):
        row = self._rows.get(key)
        if not row: return
        lbl        = row["lbl_nome"]
        nome_atual = self._get_name(key, modelo)
        lbl.pack_forget()
        entry = tk.Entry(lbl.master, font=("Segoe UI", 10, "bold"),
                         bg="#3a3a3a", fg="#ffffff",
                         insertbackground="#ffffff",
                         relief="flat", width=20)
        entry.insert(0, nome_atual)
        entry.pack(anchor="w")
        entry.focus_set()
        entry.select_range(0, tk.END)

        def salvar(event=None):
            novo = entry.get().strip() or modelo
            self.data.setdefault(key, {})["name"] = novo
            save_data(self.data)
            entry.destroy()
            lbl.config(text=novo)
            lbl.pack(anchor="w")

        def cancelar(event=None):
            entry.destroy()
            lbl.pack(anchor="w")

        entry.bind("<Return>",   salvar)
        entry.bind("<Escape>",   cancelar)
        entry.bind("<FocusOut>", salvar)

    def on_close(self):
        self._polling = False
        for key, sess in list(self._sessions.items()):
            tb = sess.get("toolbar")
            if tb:
                try:
                    if tb.winfo_exists(): tb.destroy()
                except: pass
        self.destroy()


if __name__ == "__main__":
    _mutex = ensure_single_instance()
    app    = App()
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    app.mainloop()
