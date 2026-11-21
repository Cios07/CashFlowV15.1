"""
ui_kit.py — CashFlow
Couche d'interface : rapidité, info-bulles, effets visuels.

  * tooltip()          info-bulle moderne (nom + description), avec délai
  * SmartButton        CTkButton qui affiche automatiquement une info-bulle
  * FastLabel/FastFrame/IconButton
                       widgets Tk natifs 5 à 10 fois plus rapides que CTk,
                       utilisés pour les lignes de tableaux
  * glow_image()       fond dégradé avec halos flous (effet « verre dépoli »)
  * dark_titlebar()    barre de titre sombre / coins arrondis (Windows 11)
  * safe_color()       validation des couleurs hexadécimales
"""
import re, sys, tkinter as tk
import customtkinter as ctk

_get_color = lambda key: "#222222"       # remplacé par setup()
HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def setup(color_getter):
    """main.py fournit sa fonction C(key) pour que les widgets suivent le thème."""
    global _get_color
    _get_color = color_getter


def resource_path(name):
    """Fichier livré avec l'application (compatible PyInstaller : sys._MEIPASS)."""
    import os
    for base in (getattr(sys, "_MEIPASS", None), os.path.dirname(os.path.abspath(__file__)), os.getcwd()):
        if base and os.path.exists(os.path.join(base, name)):
            return os.path.join(base, name)
    return None


def set_window_icon(window):
    """Icône CashFlow dans la barre de titre / barre des tâches (silencieux si absente)."""
    ico, png = resource_path("cashflow.ico"), resource_path("logo_cashflow.png")

    def apply():
        try:
            if ico and sys.platform.startswith("win"):
                window.iconbitmap(ico)
            elif png:
                window._icon_img = tk.PhotoImage(file=png)
                window.iconphoto(True, window._icon_img)
        except Exception:
            pass
    apply()
    window.after(300, apply)       # CTk réapplique son icône par défaut après 200 ms


def safe_color(value, default="#4F8EF7"):
    v = (value or "").strip() if isinstance(value, str) else ""
    return v if HEX_RE.match(v) else default


# ── Échelle (DPI) ─────────────────────────────────────────────────────────────
def _scaling(widget):
    try:
        return float(ctk.ScalingTracker.get_widget_scaling(widget))
    except Exception:
        return 1.0


def _font(font, sc):
    """Reproduit la conversion de police de CTk (taille en pixels)."""
    if font is None:
        font = ("Segoe UI", 12)
    if isinstance(font, ctk.CTkFont):
        return font
    fam, size, *rest = font
    return (fam, -max(1, round(abs(size) * sc)), *rest)


# ── Info-bulles ───────────────────────────────────────────────────────────────
_tip_state = {"win": None, "job": None, "owner": None}


def _hide_tip():
    st = _tip_state
    if st["job"] and st["owner"] is not None:
        try: st["owner"].after_cancel(st["job"])
        except Exception: pass
    st["job"] = None
    if st["win"] is not None:
        try: st["win"].destroy()
        except Exception: pass
    st["win"] = None


def _show_tip(widget, text):
    _hide_tip()
    try:
        if not widget.winfo_exists():
            return
        title, _, desc = text.partition(" — ")
        win = tk.Toplevel(widget)
        win.wm_overrideredirect(True)
        try: win.attributes("-topmost", True); win.attributes("-alpha", 0.97)
        except Exception: pass
        edge = tk.Frame(win, bg=_get_color("accent"))
        edge.pack()
        body = tk.Frame(edge, bg=_get_color("panel"))
        body.pack(padx=1, pady=1)
        tk.Label(body, text=title, bg=_get_color("panel"), fg=_get_color("text"),
                 font=("Segoe UI", 10, "bold"), anchor="w", justify="left",
                 wraplength=380).pack(fill="x", padx=10, pady=(6, 0 if desc else 6))
        if desc:
            tk.Label(body, text=desc, bg=_get_color("panel"), fg=_get_color("subtext"),
                     font=("Segoe UI", 9), anchor="w", justify="left",
                     wraplength=380).pack(fill="x", padx=10, pady=(1, 7))
        win.update_idletasks()
        x = widget.winfo_pointerx() + 14
        y = widget.winfo_pointery() + 18
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        x = min(x, sw - win.winfo_reqwidth() - 8)
        y = y if y + win.winfo_reqheight() < sh - 8 else widget.winfo_pointery() - win.winfo_reqheight() - 10
        win.wm_geometry(f"+{max(0, x)}+{max(0, y)}")
        _tip_state["win"] = win
    except Exception:
        _hide_tip()


def tooltip(widget, text, delay=350):
    """Info-bulle : « Titre — description ». Apparaît après `delay` ms."""
    if not text:
        return

    def enter(_e=None):
        _hide_tip()
        _tip_state["owner"] = widget
        try:
            _tip_state["job"] = widget.after(delay, lambda: _show_tip(widget, text))
        except Exception:
            pass

    def leave(_e=None):
        _hide_tip()

    for seq, fn in (("<Enter>", enter), ("<Leave>", leave),
                    ("<ButtonPress>", leave), ("<Destroy>", leave)):
        try:
            widget.bind(seq, fn, add="+")
        except Exception:
            pass


# Descriptions automatiques (clé = texte du bouton sans espaces superflus)
TIPS = {
    "✕": "Supprimer — Supprime définitivement cet élément (confirmation demandée)",
    "✕ Effacer": "Effacer les filtres — Réinitialise la recherche et affiche tous les résultats",
    "✏️": "Modifier — Ouvre le formulaire pour changer les informations",
    "💬": "Commentaires — Lire ou ajouter des commentaires sur cette transaction",
    "🔀": "Changer de chèque — Réaffecte cette dépense à un autre chèque",
    "✅": "Encaisser — Marque ce chèque comme encaissé à la banque",
    "💸": "Dépense — Enregistre une dépense (éventuellement répartie sur plusieurs chèques)",
    "📋": "Détail du chèque — Affiche l'historique des transactions du chèque",
    "🕐": "Historique — Journal des modifications de ce chèque",
    "⧉": "Dupliquer — Crée un nouveau chèque avec les mêmes informations",
    "📄": "Export PDF — Génère la fiche PDF de ce chèque",
    "🖨️": "Imprimer — Envoie la fiche à l'impression",
    "⚙️": "Champs personnalisés — Ajoute des informations supplémentaires",
    "🔑": "Mot de passe — Change le mot de passe de cet utilisateur",
    "📎": "Pièce jointe — Joindre un fichier justificatif",
    "👁": "Voir la pièce jointe — Ouvre le fichier joint",
    "◀": "Page précédente — Revient à la page de résultats précédente",
    "▶": "Page suivante — Passe à la page de résultats suivante",
    "Chercher": "Chercher — Lance la recherche avec les critères saisis",
    "Fermer": "Fermer — Ferme cette fenêtre",
    "Annuler": "Annuler — Ferme sans enregistrer les modifications",
    "🔧 Recalculer": "Recalculer — Recalcule le solde restant à partir des transactions réelles",
    "⋯": "Plus d'actions — Historique, duplication, export, impression",
    "＋ Ajouter": "Ajouter — Ajoute un nouvel élément à la liste",
    "Parcourir": "Parcourir — Choisir un fichier ou un dossier sur l'ordinateur",
    "Se connecter": "Connexion — Ouvre votre session",
    "☀️ / 🌙  Thème": "Thème — Bascule entre mode clair et mode sombre",
    "⌨️  Raccourcis  (F1)": "Raccourcis clavier — Affiche la liste des raccourcis (F1)",
    "🖨️ Imprimer": "Imprimer — Imprime le tableau de bord",
    "⚙️ Personnaliser": "Personnaliser — Choisir les sections affichées sur le tableau de bord",
    "＋ Nouveau  (Ctrl+N)": "Nouveau — Crée un nouvel élément (Ctrl+N)",
    "💱 Convertisseur": "Convertisseur — Convertit un montant vers la devise secondaire",
    "＋ Ajouter un budget": "Nouveau budget — Fixe un plafond mensuel pour une catégorie",
    "💾 Sauvegarder maintenant": "Sauvegarde — Crée immédiatement une copie de la base de données",
    "Restaurer": "Restaurer — Remplace la base actuelle par cette sauvegarde",
    "📄 Export PDF": "Export PDF — Génère un fichier PDF",
    "📤 Export Excel": "Export Excel — Génère un classeur Excel",
    "✔ Enregistrer tous les paramètres": "Enregistrer — Applique tous les paramètres modifiés",
    "🔑 Réinit. MDP": "Réinitialiser le mot de passe — Définit un nouveau mot de passe pour un utilisateur",
    "＋ Ajouter un chèque": "Nouveau chèque — Enregistre un chèque reçu",
    "✔ Confirmer et enregistrer": "Confirmer — Valide et enregistre l'opération",
    "← Modifier": "Retour — Revient au formulaire pour corriger",
    "Envoyer": "Envoyer — Publie le commentaire",
    "＋ Ajouter un champ": "Ajouter un champ — Crée un champ personnalisé",
    "✔ Enregistrer": "Enregistrer — Sauvegarde les modifications",
    "🔄  Réinitialiser": "Réinitialiser — Efface toutes les données (action irréversible)",
    "🚪  Déconnexion": "Déconnexion — Ferme la session et revient à l'écran de connexion",
    "7j": "7 jours — Statistiques de la dernière semaine",
    "30j": "30 jours — Statistiques du dernier mois",
    "3m": "3 mois — Statistiques du dernier trimestre",
    "1an": "1 an — Statistiques de la dernière année",
    "7 jours": "7 jours — Affiche les 7 derniers jours",
    "30 jours": "30 jours — Affiche les 30 derniers jours",
    "3 mois": "3 mois — Affiche les 3 derniers mois",
    "1 an": "1 an — Affiche la dernière année",
    "Tout": "Tout — Affiche toute la période",
}


def auto_tip(text, fg=None):
    t = (text or "").strip()
    if not t:
        return None
    if t == "✕" and fg is not None:           # ✕ rouge = supprimer, sinon effacer filtre
        reds = {"#F75F5F", "#D44444", "#FF6B81", _get_color("red")}
        if fg not in reds:
            return "Effacer les filtres — Réinitialise la recherche et les dates"
    return TIPS.get(t) or TIPS.get(t.replace("  ", " ")) or t.strip("＋✔✕ ")


# ── Boutons CTk avec info-bulle automatique ───────────────────────────────────
_OrigButton = ctk.CTkButton


class SmartButton(_OrigButton):
    def __init__(self, master, *args, tip=None, **kw):
        # Lisibilité en thème clair : texte foncé sur les boutons gris clair
        if "text_color" not in kw and kw.get("fg_color") in (_get_color("card2"), _get_color("card")):
            kw["text_color"] = _get_color("text")
        super().__init__(master, *args, **kw)
        t = tip or auto_tip(kw.get("text", ""), kw.get("fg_color"))
        if t:
            tooltip(self, t)


_OrigFrame = ctk.CTkFrame


class GlassFrame(_OrigFrame):
    """Cartes arrondies : fin liseré lumineux = effet « verre »."""
    def __init__(self, master, *args, **kw):
        fg = kw.get("fg_color")
        if (isinstance(fg, str) and kw.get("corner_radius", 0) >= 10
                and "border_width" not in kw
                and fg in (_get_color("card"), _get_color("panel"), _get_color("card2"))):
            kw["border_width"] = 1
            kw["border_color"] = _get_color("border")
        super().__init__(master, *args, **kw)


def install():
    ctk.CTkButton = SmartButton
    ctk.CTkFrame = GlassFrame


# ── Widgets Tk légers pour les tableaux ───────────────────────────────────────
def _pixel(widget):
    root = widget.winfo_toplevel()
    img = getattr(root, "_ui_px", None)
    if img is None:
        img = tk.PhotoImage(master=root, width=1, height=1)
        root._ui_px = img
    return img


def _bg_of(parent):
    try:
        return parent.cget("bg")
    except Exception:
        try:
            return parent.cget("fg_color")
        except Exception:
            return _get_color("bg")


class FastFrame(tk.Frame):
    def __init__(self, master, fg_color=None, width=0, height=0, **_ignored):
        bg = _bg_of(master) if fg_color in (None, "transparent") else fg_color
        super().__init__(master, bg=bg, bd=0, highlightthickness=0)


class FastLabel(tk.Label):
    """Étiquette Tk avec taille en pixels (même signature utile que CTkLabel)."""
    def __init__(self, master, text="", font=None, text_color=None,
                 width=100, height=28, anchor="center", fg_color=None, **_ignored):
        sc = _scaling(master)
        bg = _bg_of(master) if fg_color in (None, "transparent") else fg_color
        super().__init__(master, text=text, font=_font(font, sc),
                         fg=text_color or _get_color("text"), bg=bg, anchor=anchor,
                         image=_pixel(master), compound="center",
                         width=int(width * sc), height=int(height * sc),
                         bd=0, padx=0, pady=0, highlightthickness=0)

    def configure(self, cnf=None, **kw):
        if "text_color" in kw: kw["fg"] = kw.pop("text_color")
        if "fg_color" in kw:
            v = kw.pop("fg_color"); kw["bg"] = _bg_of(self.master) if v == "transparent" else v
        return super().configure(cnf, **kw) if cnf else super().configure(**kw)
    config = configure


class IconButton(tk.Label):
    """Petit bouton d'action (icône) ultra-léger, avec survol et info-bulle."""
    def __init__(self, master, text="", command=None, fg_color=None, hover_color=None,
                 width=28, height=28, font=None, text_color=None, tip=None, **_ignored):
        sc = _scaling(master)
        self._fg = fg_color or _get_color("card2")
        self._hv = hover_color or _get_color("hover")
        self._cmd = command
        super().__init__(master, text=text, font=_font(font or ("Segoe UI", 11), sc),
                         fg=text_color or _get_color("text"), bg=self._fg,
                         image=_pixel(master), compound="center",
                         width=int(width * sc), height=int(height * sc),
                         bd=0, padx=0, pady=0, highlightthickness=0, cursor="hand2")
        self.bind("<Enter>", lambda e: self.configure(bg=self._hv))
        self.bind("<Leave>", lambda e: self.configure(bg=self._fg))
        self.bind("<ButtonRelease-1>", self._click)
        t = tip or auto_tip(text, fg_color)
        if t:
            tooltip(self, t)

    def _click(self, e):
        if self._cmd and 0 <= e.x < self.winfo_width() and 0 <= e.y < self.winfo_height():
            _hide_tip()
            self._cmd()


# ── Effets visuels ────────────────────────────────────────────────────────────
def glow_image(width, height, base_top, base_bottom, blobs, blur=None, radius=0):
    """Dégradé vertical + halos de couleur floutés (PIL). Retourne une PIL.Image."""
    from PIL import Image, ImageDraw, ImageFilter

    def rgb(h):
        h = h.lstrip("#"); return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))

    top, bot = rgb(base_top), rgb(base_bottom)
    grad = Image.new("RGB", (1, height))
    for y in range(height):
        t = y / max(1, height - 1)
        grad.putpixel((0, y), tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(3)))
    img = grad.resize((width, height)).convert("RGBA")
    layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for (cx, cy, r, color, alpha) in blobs:
        x, y, rr = cx * width, cy * height, r * min(width, height)
        d.ellipse((x - rr, y - rr, x + rr, y + rr), fill=rgb(color) + (alpha,))
    layer = layer.filter(ImageFilter.GaussianBlur(blur or min(width, height) * 0.16))
    out = Image.alpha_composite(img, layer)
    if radius:
        mask = Image.new("L", (width * 3, height * 3), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, width * 3 - 1, height * 3 - 1),
                                               radius * 3, fill=255)
        out.putalpha(mask.resize((width, height), Image.LANCZOS))
        return out
    return out.convert("RGB")


def glow_ctk_image(width, height, *a, **k):
    img = glow_image(width, height, *a, **k)
    return ctk.CTkImage(light_image=img, dark_image=img, size=(width, height))


def dark_titlebar(window, dark=True):
    """Windows 10/11 : barre de titre sombre + coins arrondis (sans effet ailleurs)."""
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes
        window.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        val = ctypes.c_int(1 if dark else 0)
        for attr in (20, 19):                         # DWMWA_USE_IMMERSIVE_DARK_MODE
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(val), 4)
        corner = ctypes.c_int(2)                      # DWMWCP_ROUND
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(corner), 4)
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════════
# CanvasTable : tableau dessiné sur UN seul Canvas (≈ 20× plus rapide que des
# centaines de widgets). Gère : en-têtes triables, survol de ligne, boutons
# d'action avec info-bulles, info-bulles sur cellules tronquées.
# ═══════════════════════════════════════════════════════════════════════════════
import tkinter.font as _tkfont
_FONT_CACHE = {}


def _tkfont_for(widget, font, sc):
    root = widget.winfo_toplevel()
    key = (id(root), tuple(font), round(sc, 2))
    f = _FONT_CACHE.get(key)
    if f is None:
        fam, size, *rest = font
        f = _tkfont.Font(root=root, family=fam, size=-max(1, round(abs(size) * sc)),
                         weight="bold" if "bold" in rest else "normal")
        _FONT_CACHE[key] = f
    return f


def _mix(c1, c2, t):
    def rgb(h): h = h.lstrip("#"); return [int(h[i:i + 2], 16) for i in (0, 2, 4)]
    a, b = rgb(c1), rgb(c2)
    return "#%02x%02x%02x" % tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


class CanvasTable(tk.Canvas):
    def __init__(self, master, columns, row_h=40, head_h=38, sort=None, on_sort=None,
                 pad=8, bg=None):
        """columns = [(clé, libellé, largeur_px, triable_bool), ...]"""
        self._sc = _scaling(master)
        sc = self._sc
        self._head_h, self._row_h = int(head_h * sc), int(row_h * sc)
        super().__init__(master, bg=bg or _get_color("bg"), highlightthickness=0, bd=0,
                         height=self._head_h)
        self._cols = columns
        self._sort, self._on_sort = sort or (None, None), on_sort
        self._xs, x = [], int(6 * sc)
        for (_k, _l, w, _s) in columns:
            self._xs.append(x); x += int((w + pad) * sc)
        self._total_w = x
        self.configure(width=self._total_w)
        self._y = self._head_h
        self._rects, self._rowbg, self._btn_n = [], [], 0
        self._hover = None
        self._hv_color = _mix(_get_color("card"), _get_color("accent"), 0.16)
        self._fb = _tkfont_for(self, ("Segoe UI", 12), sc)
        self._draw_header()
        self.bind("<Configure>", self._on_conf)
        self.bind("<Motion>", self._on_motion)
        self.bind("<Leave>", self._on_leave)

    # ── en-tête ──────────────────────────────────────────────────────────────
    def _draw_header(self):
        sc = self._sc
        self._rad = int(8 * sc)
        self._head_rect = self._rrect(0, 2, self._total_w, self._head_h - 2, self._rad,
                                      fill=_get_color("card2"), outline="")
        f = _tkfont_for(self, ("Segoe UI", 11, "bold"), sc)
        sb, sd = self._sort
        for i, (key, label, w, sortable) in enumerate(self._cols):
            arrow = (" ▲" if sd == "ASC" else " ▼") if (sortable and sb == key) else ""
            item = self.create_text(self._xs[i] + int(4 * sc), self._head_h // 2,
                                    text=label + arrow, anchor="w", font=f,
                                    fill=_get_color("text") if arrow else _get_color("subtext"))
            if sortable and self._on_sort:
                new_dir = "ASC" if (sb == key and sd == "DESC") else "DESC"
                self.tag_bind(item, "<Button-1>", lambda e, k=key, d=new_dir: self._on_sort(k, d))
                self.tag_bind(item, "<Enter>", lambda e, it=item: (
                    self.itemconfigure(it, fill=_get_color("accent")), self.configure(cursor="hand2")))
                self.tag_bind(item, "<Leave>", lambda e, it=item, a=arrow: (
                    self.itemconfigure(it, fill=_get_color("text") if a else _get_color("subtext")),
                    self.configure(cursor="")))
                self._tip(item, f"Trier — Trie le tableau par « {label} » (cliquer à nouveau pour inverser)")

    # ── info-bulle sur un élément ────────────────────────────────────────────
    def _tip(self, item, text):
        def enter(_e):
            _hide_tip(); _tip_state["owner"] = self
            _tip_state["job"] = self.after(350, lambda: _show_tip(self, text))
        self.tag_bind(item, "<Enter>", enter, add="+")
        self.tag_bind(item, "<Leave>", lambda e: _hide_tip(), add="+")
        self.tag_bind(item, "<ButtonPress-1>", lambda e: _hide_tip(), add="+")

    # ── lignes ───────────────────────────────────────────────────────────────
    @staticmethod
    def _pts(x0, y0, x1, y1, r):
        return [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1, x1 - r, y1,
                x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]

    def _rrect(self, x0, y0, x1, y1, r, **kw):
        return self.create_polygon(self._pts(x0, y0, x1, y1, r), smooth=True, **kw)

    def add_row(self, bg, cells, buttons=None):
        """cells = [(texte, couleur, (famille,taille[,gras]), info-bulle|None), ...]
           buttons = [(icône, fond, survol, commande, info-bulle, couleur_texte), ...]"""
        sc, y0 = self._sc, self._y
        y1 = y0 + self._row_h
        cy = (y0 + y1) // 2
        rect = self._rrect(0, y0 + 2, max(self._total_w, self.winfo_width()), y1 - 2,
                           self._rad, fill=bg, outline="")
        self._rects.append((rect, y0 + 2, y1 - 2)); self._rowbg.append(bg)
        for i, cell in enumerate(cells):
            text, color, font, tip = (tuple(cell) + (None, None, None))[:4]
            f = _tkfont_for(self, font, sc) if font else self._fb
            item = self.create_text(self._xs[i] + int(4 * sc), cy, text=text, fill=color,
                                    font=f, anchor="w")
            if tip:
                self._tip(item, tip)
        if buttons:
            x = self._xs[len(cells)] + int(4 * sc)
            bs = int(28 * sc); bw = int(30 * sc); fi = _tkfont_for(self, ("Segoe UI", 10), sc)
            for (icon, fg, hv, cmd, tip, tcol) in buttons:
                tag = f"b{self._btn_n}"; self._btn_n += 1
                r = self._rrect(x, cy - bs // 2, x + bw, cy + bs // 2, int(7 * sc), fill=fg, outline="")
                t = self.create_text(x + bw // 2, cy, text=icon, font=fi,
                                     fill=tcol or _get_color("text"))
                self.addtag_withtag(tag, r); self.addtag_withtag(tag, t)
                self.tag_bind(tag, "<Enter>", lambda e, r=r, h=hv: (
                    self.itemconfigure(r, fill=h), self.configure(cursor="hand2")))
                self.tag_bind(tag, "<Leave>", lambda e, r=r, f=fg: (
                    self.itemconfigure(r, fill=f), self.configure(cursor="")))
                self.tag_bind(tag, "<ButtonRelease-1>",
                              lambda e, c=cmd: (_hide_tip(), self.after(10, c)))
                if tip:
                    self._tip(tag, tip)
                x += bw + int(3 * sc)
        self._y = y1

    def finish(self):
        self.configure(height=self._y + int(4 * self._sc))

    # ── survol / redimensionnement ───────────────────────────────────────────
    def _on_conf(self, e):
        w = max(e.width, self._total_w)
        self.coords(self._head_rect, *self._pts(0, 2, w, self._head_h - 2, self._rad))
        for rect, y0, y1 in self._rects:
            self.coords(rect, *self._pts(0, y0, w, y1, self._rad))

    def _on_motion(self, e):
        idx = (self.canvasy(e.y) - self._head_h) // self._row_h
        idx = int(idx) if 0 <= idx < len(self._rects) else None
        if idx == self._hover:
            return
        if self._hover is not None and self._hover < len(self._rects):
            self.itemconfigure(self._rects[self._hover][0], fill=self._rowbg[self._hover])
        self._hover = idx
        if idx is not None:
            self.itemconfigure(self._rects[idx][0], fill=_mix(self._rowbg[idx], _get_color("accent"), 0.16))

    def _on_leave(self, _e):
        if self._hover is not None and self._hover < len(self._rects):
            self.itemconfigure(self._rects[self._hover][0], fill=self._rowbg[self._hover])
        self._hover = None
