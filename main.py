"""
main.py v5 — CashFlow
Corrections :
 - update_transaction recalcule montant_restant chèque lié
 - delete_transaction : recalcul propre + blocage suppression entrée initiale
Nouveautés :
 - Dépense multi-chèques avec répartition visuelle
 - Date d'échéance sur chèques + alertes au démarrage
 - Numérotation automatique des chèques
 - Solde restant en temps réel dans les formulaires
 - Dashboard avec filtre période (7j / 30j / 3mois / 1an / perso)
 - Page Rapports (mensuel, catégories, chèque individuel, général)
 - Pièces jointes sur transactions
 - Notes enrichies (texte long)
 - Budget mensuel par catégorie
 - Thème clair / sombre (bascule) 
 - Notifications démarrage (chèques échus, alertes seuil)
 - Multi-devises dans paramètres
 - Aperçu PDF (fenêtre dédiée)
 - Performance : chargement lazy, threading pour stats
"""
import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox, filedialog
from datetime import datetime, date
import os, threading, subprocess, sys

import database as db
from database import (
    init_db, authenticate, get_devise, get_parametre, set_parametre,
    get_solde_caisse, get_solde_periode,
    get_all_cheques, add_cheque, update_cheque, encaisser_cheque,
    depense_sur_cheque, depense_multi_cheques, delete_cheque,
    get_cheque_transactions, get_cheques_alertes, get_cheques_echus,
    get_next_numero_cheque, export_cheque_pdf,
    get_transactions, add_transaction, update_transaction, delete_transaction,
    get_categories, add_category, update_category, delete_category,
    get_all_users, add_user, change_password, delete_user,
    get_seuil_alerte, get_stats_categories, get_evolution_solde,
    get_stats_mensuelles, get_top_depenses, get_historique, recherche_globale,
    backup_db, get_backups, restore_backup, reset_all_data,
    export_to_excel, export_to_pdf,
    export_rapport_mensuel_pdf, export_rapport_categories_pdf,
    export_rapport_cheques_pdf, export_cheque_excel,
    get_budgets, set_budget, delete_budget,
    save_piece_jointe, get_piece_jointe_path,
    get_champs_custom_cheque, set_champs_custom_cheque,
    get_champs_custom_transaction, set_champs_custom_transaction,
    get_devise_secondaire, get_taux_conversion, convertir,
    get_cheques_par_statut_count,
    recalculer_cheque, recalculer_tous_cheques,
    changer_cheque_depense,
    get_historique_cheque, get_historique_filtre,
    get_commentaires, add_commentaire, delete_commentaire,
    check_export_planifie, reset_password_by_admin, get_all_logins,
    get_all_cheques_v2, get_cheques_archives, dupliquer_cheque,
    recherche_par_montant,
    importer_transactions_csv, importer_transactions_excel,
    get_csv_headers, get_excel_headers,
    export_journal_excel, export_journal_pdf,
    get_comparatif_mensuel,
)

import ui_kit
from ui_kit import tooltip, FastLabel, FastFrame, IconButton, CanvasTable, safe_color

# ── Thème ──────────────────────────────────────────────────────────────────────
_THEME = {"mode": "dark"}

def _apply_theme(mode):
    _THEME["mode"] = mode
    ctk.set_appearance_mode(mode)

ctk.set_default_color_theme("blue")

# Palettes dark / light
PALETTES = {
    "dark": {
        "bg":"#0A0E1F","panel":"#111833","card":"#161E3D","card2":"#212840",
        "hover":"#263050","border":"#2C3A6E","accent":"#4F8EF7","accent2":"#7C5CFC",
        "green":"#3DD68C","orange":"#F5A623","red":"#F75F5F","text":"#EEF1FF",
        "subtext":"#8D97C4","white":"#FFFFFF","row_alt":"#131A38",
    },
    "light": {
        "bg":"#EDF1FC","panel":"#FFFFFF","card":"#FFFFFF","card2":"#E8EDF8",
        "hover":"#D8E2F8","border":"#C9D3EE","accent":"#3570D4","accent2":"#5A3CC0",
        "green":"#1E9E6A","orange":"#D4890A","red":"#D44444","text":"#1A2048",
        "subtext":"#5B6590","white":"#FFFFFF","row_alt":"#F4F7FE",
    }
}

def C(key): return PALETTES[_THEME["mode"]][key]

STATUT_COLORS = {
    "en_attente":            ("#F5A623","🕐 En attente"),
    "encaisse":              ("#3DD68C","✅ Encaissé"),
    "partiellement_utilise": ("#4F8EF7","⚡ Partiel"),
    "cloture":               ("#7A8099","🔒 Clôturé"),
}
FT  = ("Segoe UI",22,"bold")
FH2 = ("Segoe UI",15,"bold")
FH3 = ("Segoe UI",13,"bold")
FB  = ("Segoe UI",12)
FS  = ("Segoe UI",10)

current_user = None
PAGE_SIZE    = 50

NAV_TIPS = {
    "dashboard":"Tableau de bord — Vue d'ensemble : solde, entrées, sorties, alertes (Ctrl+D)",
    "recherche":"Recherche globale — Retrouve un chèque ou une transaction par mot-clé ou montant (Ctrl+F)",
    "cheques":"Chèques — Liste, ajout, modification et suivi des chèques (Ctrl+H)",
    "transactions":"Transactions — Toutes les entrées et sorties de la caisse (Ctrl+T)",
    "stats":"Statistiques — Graphiques par catégorie, mois et période (Ctrl+S)",
    "rapports":"Rapports — Exports PDF / Excel : mensuel, catégories, chèques (Ctrl+R)",
    "budgets":"Budgets — Plafonds mensuels de dépenses par catégorie (Ctrl+B)",
    "categories":"Catégories — Gérer les catégories, couleurs et icônes",
    "sauvegardes":"Sauvegardes — Créer ou restaurer une copie de la base de données",
    "journal":"Journal — Historique de toutes les actions des utilisateurs",
    "parametres":"Paramètres — Société, devise, seuils d'alerte, export automatique",
    "users":"Utilisateurs — Comptes, rôles et mots de passe",
}

TRUNC = {"designation":32,"beneficiaire":22,"numero":14,"cat_nom":18,
         "reference":14,"notes":22,"action":20,"detail":35}

def trunc(text, key="designation"):
    if not text: return ""
    lim = TRUNC.get(key,25); t=str(text)
    return t if len(t)<=lim else t[:lim-1]+"…"

# Info-bulles sur tous les boutons + cartes à liseré « verre » (voir ui_kit.py)
ui_kit.setup(C)
ui_kit.install()


# ═══════════════════════════════════════════════════════════════════════════════
# CONNEXION
# ═══════════════════════════════════════════════════════════════════════════════
class LoginWindow(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("CashFlow — Connexion")
        self.geometry("420x580"); self.resizable(False,False)
        self.configure(fg_color=C("bg")); self._build()
        self.after(60,lambda:ui_kit.dark_titlebar(self,_THEME["mode"]=="dark"))
        ui_kit.set_window_icon(self)

    def _build(self):
        pil=ui_kit.glow_image(420,580,"#0A0F2E","#1B1347",
            [(0.08,0.10,0.60,"#5B8CFF",210),(0.98,0.45,0.55,"#9B6BFF",200),
             (0.25,0.97,0.60,"#2EE6D6",130)])
        self._bg_img=ctk.CTkImage(light_image=pil,dark_image=pil,size=(420,580))
        top=pil.crop((0,0,420,190)); has_logo=False
        lp=ui_kit.resource_path("logo_cashflow_horizontal_sombre.png")
        if lp:
            try:
                from PIL import Image as _Im
                lg=_Im.open(lp).convert("RGBA"); lg.thumbnail((320,100),_Im.LANCZOS)
                top=top.convert("RGBA"); top.alpha_composite(lg,((420-lg.width)//2,(190-lg.height)//2-6))
                top=top.convert("RGB"); has_logo=True
            except Exception:
                pass
        self._top_img=ctk.CTkImage(light_image=top,dark_image=top,size=(420,190))
        ctk.CTkLabel(self,text="",image=self._bg_img).place(x=0,y=0,relwidth=1,relheight=1)
        ctk.CTkLabel(self,text="" if has_logo else "💼\nCashFlow\nSuivi chèques & caisse",
                     image=self._top_img,compound="center",
                     font=("Segoe UI",22,"bold"),text_color="#FFFFFF").pack()
        fr=ctk.CTkFrame(self,fg_color="#141B40",corner_radius=0,
                        border_width=1,border_color="#41539A")
        fr.pack(padx=40,pady=(6,0),fill="x")
        ctk.CTkLabel(fr,text="Identifiant",font=FS,text_color="#9FAAD8",
                     anchor="w").pack(padx=20,pady=(18,3),fill="x")
        self._e_login=ctk.CTkEntry(fr,height=42,font=FB,corner_radius=12,
                                    fg_color="#1D2750",border_color="#36447F")
        self._e_login.pack(padx=20,fill="x")
        ctk.CTkLabel(fr,text="Mot de passe",font=FS,text_color="#9FAAD8",
                     anchor="w").pack(padx=20,pady=(14,3),fill="x")
        self._e_pwd=ctk.CTkEntry(fr,height=42,font=FB,show="●",corner_radius=12,
                                  fg_color="#1D2750",border_color="#36447F")
        self._e_pwd.pack(padx=20,fill="x")
        self._e_login.bind("<Return>",lambda e:self._do_login())
        self._e_pwd.bind("<Return>",lambda e:self._do_login())
        self._err=ctk.CTkLabel(fr,text="",font=FS,text_color=C("red"))
        self._err.pack(pady=(8,0))
        ctk.CTkButton(fr,text="  Se connecter",height=46,font=FH3,corner_radius=12,
                      fg_color="#4F8EF7",hover_color="#3570D4",
                      command=self._do_login).pack(padx=20,pady=(10,22),fill="x")
        self._e_login.focus_set()

    def _do_login(self):
        login=self._e_login.get().strip(); pwd=self._e_pwd.get()
        user,status=authenticate(login,pwd)
        if status=="ok":
            global current_user; current_user=user
            self.destroy(); MainApp().mainloop()
        elif status=="bloque":
            self._err.configure(text="🔒 Compte bloqué (trop de tentatives).")
        else:
            r=status.split(":")[-1] if ":" in status else "?"
            self._err.configure(text=f"❌ Identifiants incorrects. {r} tentative(s) restante(s).")


# ═══════════════════════════════════════════════════════════════════════════════
# APPLICATION PRINCIPALE
# ═══════════════════════════════════════════════════════════════════════════════
class MainApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(f"CashFlow — {current_user['nom']}")
        self.geometry("1440x900"); self.minsize(1100,700)
        self.configure(fg_color=C("bg"))
        self._active_page=None; self._tr_page=0
        self._tr_sort=("date_transaction","DESC")
        self._ch_sort=("created_at","DESC")
        self._toast_lbl=None; self._nav_btns={}
        self._build_layout()
        self._navigate("dashboard")
        self.after(60,lambda:ui_kit.dark_titlebar(self,_THEME["mode"]=="dark"))
        ui_kit.set_window_icon(self)
        # Raccourcis
        self.bind("<Control-n>",lambda e:self._sc_new())
        self.bind("<Control-e>",lambda e:self._export_excel())
        self.bind("<Control-p>",lambda e:self._export_pdf())
        self.bind("<Control-f>",lambda e:self._navigate("recherche"))
        self.bind("<Control-r>",lambda e:self._navigate("rapports"))
        self.bind("<Control-b>",lambda e:self._navigate("budgets"))
        self.bind("<Control-h>",lambda e:self._navigate("cheques"))
        self.bind("<Control-t>",lambda e:self._navigate("transactions"))
        self.bind("<Control-d>",lambda e:self._navigate("dashboard"))
        self.bind("<Control-s>",lambda e:self._navigate("stats"))
        self.bind("<F5>",lambda e:self._navigate(self._active_page))
        self.bind("<F1>",lambda e:self._show_shortcuts())
        self.protocol("WM_DELETE_WINDOW",self._on_close)
        # Auto-backup
        if get_parametre("auto_backup","1")=="1":
            threading.Thread(target=_safe_backup,daemon=True).start()
        # Export automatique planifié (1er du mois)
        threading.Thread(target=self._check_export_planifie,daemon=True).start()
        # Alertes au démarrage (différé pour ne pas bloquer l'affichage)
        self.after(800, self._check_alertes_demarrage)

    def _on_close(self):
        if messagebox.askyesno("Quitter","Voulez-vous quitter CashFlow ?"):
            self.destroy()

    # ── Layout ────────────────────────────────────────────────────────────────
    def _build_layout(self):
        self.sidebar=ctk.CTkFrame(self,width=240,fg_color=C("panel"),corner_radius=0)
        self.sidebar.pack(side="left",fill="y"); self.sidebar.pack_propagate(False)

        dark=_THEME["mode"]=="dark"
        self._banner_img=ui_kit.glow_ctk_image(
            216,100,"#22337A" if dark else "#CFE0FF","#141C45" if dark else "#F1F5FF",
            [(0.12,0.2,0.55,"#5B8CFF",200),(0.92,0.9,0.55,"#9B6BFF",180),
             (0.65,0.05,0.30,"#2EE6D6",120)],radius=16)
        has_logo=False
        lp=ui_kit.resource_path("logo_cashflow_horizontal_sombre.png" if dark else "logo_cashflow_horizontal_clair.png")
        if lp:
            try:
                from PIL import Image as _Im
                bi=ui_kit.glow_image(216,100,"#22337A" if dark else "#CFE0FF","#141C45" if dark else "#F1F5FF",
                    [(0.12,0.2,0.55,"#5B8CFF",200),(0.92,0.9,0.55,"#9B6BFF",180),(0.65,0.05,0.30,"#2EE6D6",120)],radius=16).convert("RGBA")
                lg=_Im.open(lp).convert("RGBA"); lg.thumbnail((170,46),_Im.LANCZOS)
                bi.alpha_composite(lg,((216-lg.width)//2,12))
                self._banner_img=ctk.CTkImage(light_image=bi,dark_image=bi,size=(216,100)); has_logo=True
            except Exception:
                pass
        ctk.CTkLabel(self.sidebar,text=(f"\n\n👤 {current_user['nom']}" if has_logo
                                         else f"💼  CashFlow\n👤 {current_user['nom']}"),
                     image=self._banner_img,compound="center",
                     font=("Segoe UI",14,"bold"),
                     text_color="#FFFFFF" if dark else "#1A2250").pack(padx=12,pady=(14,10))
        ctk.CTkFrame(self.sidebar,height=1,fg_color=C("border")).pack(fill="x",padx=14,pady=(0,12))

        nav=[("🏠  Tableau de bord","dashboard"),
             ("🔍  Recherche globale","recherche"),
             ("📋  Chèques","cheques"),
             ("💸  Transactions","transactions"),
             ("📊  Statistiques","stats"),
             ("📄  Rapports","rapports"),
             ("🎯  Budgets","budgets"),
             ("🗂️  Catégories","categories"),
             ("🗄️  Sauvegardes","sauvegardes"),
             ("📜  Journal","journal"),
             ("⚙️  Paramètres","parametres"),
             ("👥  Utilisateurs","users")]
        self._nav_btns={}
        for label,key in nav:
            btn=ctk.CTkButton(self.sidebar,text=label,anchor="w",height=36,tip=NAV_TIPS.get(key),
                              corner_radius=10,font=FB,fg_color="transparent",
                              hover_color=C("hover"),text_color=C("subtext"),
                              command=lambda k=key:self._navigate(k))
            btn.pack(padx=10,pady=1,fill="x"); self._nav_btns[key]=btn

        # Compteur chèques actifs
        ctk.CTkFrame(self.sidebar,height=1,fg_color=C("border")).pack(fill="x",padx=14,pady=(10,6))
        self._sidebar_stats_fr=ctk.CTkFrame(self.sidebar,fg_color=C("card"),corner_radius=10)
        self._sidebar_stats_fr.pack(padx=10,fill="x",pady=(0,4))
        self._update_sidebar_stats()

        # Bascule thème
        theme_fr=ctk.CTkFrame(self.sidebar,fg_color="transparent")
        theme_fr.pack(padx=10,pady=(8,4),fill="x",side="bottom")
        ctk.CTkButton(theme_fr,text="☀️ / 🌙  Thème",anchor="w",height=34,
                      corner_radius=10,font=FB,fg_color="transparent",
                      hover_color=C("hover"),text_color=C("subtext"),
                      command=self._toggle_theme).pack(fill="x")
        ctk.CTkButton(self.sidebar,text="⌨️  Raccourcis  (F1)",anchor="w",height=32,
                      corner_radius=10,font=FS,fg_color="transparent",
                      hover_color=C("hover"),text_color=C("subtext"),
                      command=self._show_shortcuts).pack(padx=10,pady=1,fill="x",side="bottom")

        for txt,color,cmd in [("🔄  Réinitialiser",C("orange"),self._confirm_reset),
                               ("🚪  Déconnexion",C("red"),self._logout)]:
            ctk.CTkButton(self.sidebar,text=txt,anchor="w",height=34,corner_radius=10,
                          font=FB,fg_color="transparent",hover_color=C("hover"),
                          text_color=color,command=cmd).pack(padx=10,pady=1,fill="x",side="bottom")
        ctk.CTkFrame(self.sidebar,height=4,fg_color="transparent").pack(side="bottom")

        self.content=ctk.CTkFrame(self,fg_color=C("bg"),corner_radius=0)
        self.content.pack(side="left",fill="both",expand=True)
        self._toast_lbl=ctk.CTkLabel(self,text="",font=FB,corner_radius=10,
                                      fg_color=C("green"),text_color=C("white"))

    def _update_sidebar_stats(self):
        """Met à jour le compteur de chèques dans la sidebar."""
        for w in self._sidebar_stats_fr.winfo_children(): w.destroy()
        try:
            counts=get_cheques_par_statut_count()
            actifs=counts.get("en_attente",0)+counts.get("partiellement_utilise",0)
            echus=len(get_cheques_echus())
            ctk.CTkLabel(self._sidebar_stats_fr,text="Chèques actifs",
                         font=("Segoe UI",9),text_color=C("subtext")).pack(padx=8,pady=(6,1),anchor="w")
            fr2=ctk.CTkFrame(self._sidebar_stats_fr,fg_color="transparent"); fr2.pack(padx=8,pady=(0,6),fill="x")
            ctk.CTkLabel(fr2,text=str(actifs),font=("Segoe UI",20,"bold"),
                         text_color=C("accent")).pack(side="left")
            if echus:
                ctk.CTkLabel(fr2,text=f"  ⏰{echus} échu(s)",font=("Segoe UI",9),
                             text_color=C("red")).pack(side="left",pady=(8,0))
        except: pass

    def _toggle_theme(self):
        new_mode = "light" if _THEME["mode"]=="dark" else "dark"
        page_courante = self._active_page or "dashboard"
        _apply_theme(new_mode)
        # Détruire TOUT le contenu de la fenêtre principale
        for w in self.winfo_children():
            w.destroy()
        # Réinitialiser les références qui seront recréées par _build_layout
        self._toast_lbl = None
        self._nav_btns  = {}
        # Reconfigurer la fenêtre racine
        self.configure(fg_color=C("bg"))
        # Reconstruire sidebar + content from scratch
        self._build_layout()
        # Naviguer vers la page qui était active
        self._navigate(page_courante)

    def _navigate(self, key):
        self._active_page=key
        for k,btn in self._nav_btns.items():
            btn.configure(fg_color=C("accent") if k==key else "transparent",
                          text_color=C("white") if k==key else C("subtext"))
        self.content.pack_forget()          # pas de re-layout pendant la construction
        for w in self.content.winfo_children(): w.destroy()
        # Rafraîchir compteur sidebar
        try: self._update_sidebar_stats()
        except: pass
        pages={
            "dashboard":self._page_dashboard,
            "recherche":self._page_recherche,
            "cheques":self._page_cheques,
            "transactions":self._page_transactions,
            "stats":self._page_stats,
            "rapports":self._page_rapports,
            "budgets":self._page_budgets,
            "categories":self._page_categories,
            "sauvegardes":self._page_sauvegardes,
            "journal":self._page_journal,
            "parametres":self._page_parametres,
            "users":self._page_users,
        }
        try: pages[key]()
        finally:
            self.content.pack(side="left",fill="both",expand=True)

    def toast(self, msg, color=None):
        if not self._toast_lbl: return
        self._toast_lbl.configure(text=f"  {msg}  ",fg_color=color or C("green"))
        self._toast_lbl.place(relx=0.5,rely=0.97,anchor="s")
        self.after(3500,lambda:self._toast_lbl.place_forget() if self._toast_lbl else None)

    def _sc_new(self):
        if self._active_page=="cheques":        self._dlg_cheque()
        elif self._active_page=="transactions": self._dlg_transaction("entree")

    def _check_alertes_demarrage(self):
        echus   = get_cheques_echus()
        alertes = get_cheques_alertes()
        msgs    = []
        if echus:
            msgs.append(f"⏰ {len(echus)} chèque(s) avec échéance dépassée !")
        if alertes:
            msgs.append(f"⚠️ {len(alertes)} chèque(s) sous le seuil d'alerte !")
        if msgs:
            messagebox.showwarning("Alertes au démarrage", "\n".join(msgs)+
                                   "\n\nConsultez la page Chèques pour les détails.")

    # ── Helpers ───────────────────────────────────────────────────────────────
    def _row_bg(self, idx): return C("card") if idx%2==0 else C("row_alt")

    def _sort_hdr(self, parent, label, col_key, current_sort, callback, width, col_idx):
        sb,sd=current_sort
        arrow=(" ▲" if sd=="ASC" else " ▼") if sb==col_key else ""
        btn=ctk.CTkButton(parent,text=label+arrow,anchor="w",height=30,
                           font=("Segoe UI",11,"bold"),fg_color=C("card2"),
                           hover_color=C("hover"),text_color=C("subtext"),
                           corner_radius=6,width=width,
                           command=lambda:callback(col_key,
                               "ASC" if (sb==col_key and sd=="DESC") else "DESC"))
        btn.grid(row=0,column=col_idx,padx=4,pady=5,sticky="w")

    def _lbl(self, parent, text, key, col, width, color=None, row=0, full=None):
        txt=trunc(text,key)
        lbl=FastLabel(parent,text=txt,font=FB,
                      text_color=color or C("text"),width=width,anchor="w")
        lbl.grid(row=row,column=col,padx=6,pady=7,sticky="w")
        ft=full or (str(text) if str(text)!=txt else None)
        if ft: tooltip(lbl,ft)
        return lbl

    def _page_header(self, frame, title):
        hdr=ctk.CTkFrame(frame,fg_color="transparent")
        hdr.pack(fill="x",padx=28,pady=(22,0))
        ctk.CTkLabel(hdr,text=title,font=FT,text_color=C("text")).pack(side="left")
        return hdr

    def _dlg(self, title, w=500, h=560):
        d=ctk.CTkToplevel(self); d.title(title)
        d.geometry(f"{w}x{h}"); d.resizable(False,False)
        d.configure(fg_color=C("bg")); d.grab_set(); d.focus_force()
        return d

    def _sf_form(self, dlg, title):
        ctk.CTkLabel(dlg,text=title,font=FH2,text_color=C("text")).pack(pady=(16,4),padx=20,anchor="w")
        ctk.CTkFrame(dlg,height=1,fg_color=C("border")).pack(fill="x",padx=20,pady=(0,8))
        sf=ctk.CTkScrollableFrame(dlg,fg_color=C("panel"),corner_radius=12)
        sf.pack(fill="both",expand=True,padx=16,pady=(0,4))
        return sf

    def _field(self, parent, label, ph="", default="", show=None):
        ctk.CTkLabel(parent,text=label,font=FS,text_color=C("subtext"),
                     anchor="w").pack(fill="x",padx=20,pady=(12,2))
        kw={}; kw["show"]=show if show else None
        if kw["show"] is None: del kw["show"]
        e=ctk.CTkEntry(parent,height=40,font=FB,placeholder_text=ph,
                       fg_color=C("card2"),border_color=C("border"),**kw)
        e.pack(fill="x",padx=20)
        if default: e.insert(0,str(default))
        return e

    def _field_text(self, parent, label, default="", height=80):
        """Champ texte multiligne pour notes enrichies."""
        ctk.CTkLabel(parent,text=label,font=FS,text_color=C("subtext"),
                     anchor="w").pack(fill="x",padx=20,pady=(12,2))
        t=ctk.CTkTextbox(parent,height=height,font=FB,
                          fg_color=C("card2"),border_color=C("border"),border_width=2)
        t.pack(fill="x",padx=20)
        if default: t.insert("1.0",str(default))
        return t

    def _btns(self, dlg, label, cmd, color=None):
        bf=ctk.CTkFrame(dlg,fg_color=C("panel"))
        bf.pack(fill="x",padx=16,pady=(8,16))
        ctk.CTkButton(bf,text=label,height=44,font=FH3,
                      fg_color=color or C("accent"),command=cmd).pack(fill="x",pady=(0,6),padx=4)
        ctk.CTkButton(bf,text="Annuler",height=36,font=FB,
                      fg_color=C("card2"),hover_color=C("hover"),
                      command=dlg.destroy).pack(fill="x",padx=4)

    def _opt(self, parent, label, values, var):
        ctk.CTkLabel(parent,text=label,font=FS,text_color=C("subtext"),
                     anchor="w").pack(fill="x",padx=20,pady=(12,2))
        ctk.CTkOptionMenu(parent,values=values,variable=var,
                          fg_color=C("card2"),button_color=C("accent"),
                          height=40,font=FB).pack(fill="x",padx=20)

    # ── DASHBOARD ─────────────────────────────────────────────────────────────
    def _page_dashboard(self, jours="0"):
        self._dash_jours = str(jours)
        outer=ctk.CTkScrollableFrame(self.content,fg_color=C("bg"))
        outer.pack(fill="both",expand=True)
        self._dash_outer=outer

        hdr=self._page_header(outer,"Tableau de bord")
        ctk.CTkLabel(hdr,text=f"🕐 {datetime.now().strftime('%d/%m/%Y %H:%M')}",
                     font=FS,text_color=C("subtext")).pack(side="right",pady=(6,0))
        ctk.CTkButton(hdr,text="🖨️ Imprimer",height=32,font=FS,
                      fg_color=C("card2"),hover_color=C("hover"),
                      command=self._print_dashboard).pack(side="right",padx=8,pady=(4,0))
        ctk.CTkButton(hdr,text="⚙️ Personnaliser",height=32,font=FS,
                      fg_color=C("card2"),hover_color=C("hover"),
                      command=self._dlg_personnaliser_dashboard).pack(side="right",padx=8,pady=(4,0))

        # Filtres période — boutons fixes, ne font que rafraîchir le contenu
        pf=ctk.CTkFrame(outer,fg_color=C("panel"),corner_radius=10)
        pf.pack(fill="x",padx=28,pady=(14,0))
        ctk.CTkLabel(pf,text="Période :",font=FS,text_color=C("subtext")).pack(side="left",padx=14,pady=8)
        self._dash_period_btns={}
        for j,label in [("7","7 jours"),("30","30 jours"),("90","3 mois"),("365","1 an"),("0","Tout")]:
            b=ctk.CTkButton(pf,text=label,width=72,height=28,font=FS,
                            fg_color=C("accent") if j==self._dash_jours else C("card2"),
                            hover_color=C("hover"),
                            command=lambda d=j:self._set_dash_periode(d))
            b.pack(side="left",padx=2,pady=6)
            self._dash_period_btns[j]=b

        # Zone de contenu qui sera vidée/recréée à chaque changement de période
        body=ctk.CTkFrame(outer,fg_color="transparent")
        body.pack(fill="both",expand=True)
        self._dash_body=body
        self._refresh_dashboard_body()

    def _set_dash_periode(self, jours):
        self._dash_jours=str(jours)
        for j,b in self._dash_period_btns.items():
            b.configure(fg_color=C("accent") if j==self._dash_jours else C("card2"))
        self._refresh_dashboard_body()

    def _refresh_dashboard_body(self):
        body=self._dash_body
        for w in body.winfo_children(): w.destroy()
        jours=self._dash_jours
        devise=get_devise()
        kpis_actifs=self._get_kpis_actifs()

        try:
            if jours=="0":
                solde,entrees,sorties,_=get_solde_caisse()
                dd=df=""
            else:
                from datetime import timedelta as _td
                d_fin=date.today()
                d_deb=d_fin-_td(days=int(jours))
                dd,df=d_deb.isoformat(),d_fin.isoformat()
                solde,entrees,sorties=get_solde_periode(dd,df)
            ch_actifs=[c for c in get_all_cheques() if c["statut"] not in ("cloture",)]
            alertes   =get_cheques_alertes()
            echus     =get_cheques_echus()
        except Exception as ex:
            ctk.CTkLabel(body,text=f"❌ Erreur chargement : {ex}",
                         font=FB,text_color=C("red")).pack(pady=30)
            return

        # Indicateur de santé financière
        if "sante" in kpis_actifs:
            score,niveau,couleur,raison=self._calc_sante_financiere(solde,ch_actifs,alertes,echus)
            sf=ctk.CTkFrame(body,fg_color=C("card"),corner_radius=14)
            sf.pack(fill="x",padx=28,pady=(16,0))
            row=ctk.CTkFrame(sf,fg_color="transparent"); row.pack(fill="x",padx=18,pady=14)
            dot=ctk.CTkFrame(row,width=18,height=18,corner_radius=9,fg_color=couleur)
            dot.pack(side="left",padx=(0,10)); dot.pack_propagate(False)
            txtf=ctk.CTkFrame(row,fg_color="transparent"); txtf.pack(side="left",fill="x",expand=True)
            ctk.CTkLabel(txtf,text=f"Santé financière : {niveau}",font=FH3,
                         text_color=couleur).pack(anchor="w")
            ctk.CTkLabel(txtf,text=raison,font=FS,text_color=C("subtext")).pack(anchor="w")

        # KPI cards
        if "kpi" in kpis_actifs:
            kf=ctk.CTkFrame(body,fg_color="transparent")
            kf.pack(fill="x",padx=24,pady=(16,0)); kf.columnconfigure((0,1,2,3),weight=1)
            kpis=[
                ("Solde",f"{solde:,.0f} {devise}",C("accent"),"💰"),
                ("Entrées",f"{entrees:,.0f} {devise}",C("green"),"📈"),
                ("Sorties",f"{sorties:,.0f} {devise}",C("red"),"📉"),
                ("Chèques actifs",str(len(ch_actifs)),C("orange"),"📋"),
            ]
            for i,(title,val,color,icon) in enumerate(kpis):
                card=ctk.CTkFrame(kf,fg_color=C("card"),corner_radius=14)
                card.grid(row=0,column=i,padx=6,pady=6,sticky="ew")
                ctk.CTkLabel(card,text=icon,font=("Segoe UI",26)).pack(padx=18,pady=(16,3),anchor="w")
                ctk.CTkLabel(card,text=val,font=("Segoe UI",16,"bold"),
                             text_color=color).pack(padx=18,anchor="w")
                ctk.CTkLabel(card,text=title,font=FS,text_color=C("subtext")
                             ).pack(padx=18,pady=(2,14),anchor="w")

        # Alertes échéance
        if "alertes" in kpis_actifs and echus:
            ef=ctk.CTkFrame(body,fg_color="#3A0A0A",corner_radius=10)
            ef.pack(fill="x",padx=28,pady=(14,0))
            ctk.CTkLabel(ef,text=f"⏰  {len(echus)} chèque(s) avec échéance dépassée :",
                         font=FH3,text_color="#F75F5F").pack(padx=14,pady=(10,4),anchor="w")
            for ch in echus[:3]:
                ctk.CTkLabel(ef,text=f"  #{ch['numero']} — {ch['beneficiaire']}  "
                             f"(échéance : {ch.get('date_echeance','')})",
                             font=FB,text_color="#E8EAF0").pack(padx=14,pady=1,anchor="w")
            ctk.CTkFrame(ef,height=4,fg_color="transparent").pack()

        # Alertes seuil
        if "alertes" in kpis_actifs and alertes:
            seuil=get_seuil_alerte()
            af=ctk.CTkFrame(body,fg_color="#2A1A0A",corner_radius=10)
            af.pack(fill="x",padx=28,pady=(10,0))
            ctk.CTkLabel(af,text=f"⚠️  {len(alertes)} chèque(s) sous {seuil:.0f}% restant :",
                         font=FH3,text_color=C("orange")).pack(padx=14,pady=(10,4),anchor="w")
            for ch in alertes[:3]:
                pct=ch["montant_restant"]/ch["montant_initial"]*100 if ch["montant_initial"] else 0
                ctk.CTkLabel(af,text=f"  #{ch['numero']} — {ch['beneficiaire']}  "
                             f"({pct:.0f}% restant, {ch['montant_restant']:,.0f} {devise})",
                             font=FB,text_color="#E8EAF0").pack(padx=14,pady=1,anchor="w")
            ctk.CTkFrame(af,height=4,fg_color="transparent").pack()

        # Top dépenses
        if "top" in kpis_actifs:
            top=get_top_depenses(5,dd,df)
            if top:
                tf=ctk.CTkFrame(body,fg_color=C("card"),corner_radius=14)
                tf.pack(fill="x",padx=28,pady=(16,0))
                ctk.CTkLabel(tf,text="🔝 Top 5 dépenses",font=FH3,text_color=C("text")
                             ).pack(padx=18,pady=(14,8),anchor="w")
                max_t=top[0]["total"] if top else 1
                for t in top:
                    rf=ctk.CTkFrame(tf,fg_color="transparent")
                    rf.pack(fill="x",padx=18,pady=2)
                    ctk.CTkLabel(rf,text=trunc(t["designation"],"designation"),
                                 font=FB,text_color=C("text"),width=240,anchor="w").pack(side="left")
                    pct=t["total"]/max_t
                    bar=ctk.CTkProgressBar(rf,width=160,height=10,
                                            fg_color=C("card2"),progress_color=C("red"))
                    bar.set(pct); bar.pack(side="left",padx=8)
                    ctk.CTkLabel(rf,text=f"{t['total']:,.0f} {devise}",
                                 font=FB,text_color=C("red")).pack(side="left")
                ctk.CTkFrame(tf,height=8,fg_color="transparent").pack()

        # Graphique rapide (chargé en thread)
        if "graphique" in kpis_actifs:
            chart_fr=ctk.CTkFrame(body,fg_color=C("card"),corner_radius=14)
            chart_fr.pack(fill="x",padx=28,pady=(16,20))
            ctk.CTkLabel(chart_fr,text="📈 Évolution du solde",font=FH3,
                         text_color=C("text")).pack(padx=18,pady=(14,4),anchor="w")
            loading=ctk.CTkLabel(chart_fr,text="Chargement du graphique…",
                                  font=FS,text_color=C("subtext"))
            loading.pack(pady=20)
            def load_chart(target_jours=jours, target_frame=chart_fr, target_loading=loading):
                try:
                    import matplotlib.pyplot as plt
                    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
                    nb=int(target_jours) if target_jours!="0" else 365
                    dates,soldes=get_evolution_solde(nb)
                    BG=C("card"); TXT=C("text"); GRID=C("border")
                    fig,ax=plt.subplots(figsize=(10,2.8),facecolor=BG)
                    ax.set_facecolor(BG)
                    if dates:
                        ax.plot(dates,soldes,color=C("accent"),linewidth=2.5,marker="o",markersize=4)
                        ax.fill_between(dates,soldes,alpha=0.12,color=C("accent"))
                    ax.tick_params(colors=TXT,labelsize=8); ax.xaxis.set_tick_params(rotation=35)
                    for s in ax.spines.values(): s.set_edgecolor(GRID)
                    ax.grid(color=GRID,linewidth=0.4,alpha=0.6)
                    fig.tight_layout()
                    def show():
                        # Vérifier que le frame existe toujours (l'utilisateur n'a pas changé de page/période entretemps)
                        if not target_frame.winfo_exists(): plt.close(fig); return
                        if self._dash_jours != target_jours: plt.close(fig); return
                        try: target_loading.destroy()
                        except: pass
                        FigureCanvasTkAgg(fig,master=target_frame).get_tk_widget().pack(
                            padx=10,pady=(0,10),fill="x")
                        plt.close(fig)
                    self.after(0,show)
                except Exception: pass
            threading.Thread(target=load_chart,daemon=True).start()

    # ── KPI personnalisables ───────────────────────────────────────────────────
    def _get_kpis_actifs(self):
        raw=get_parametre("dashboard_kpis","sante,kpi,alertes,top,graphique")
        return set(k.strip() for k in raw.split(",") if k.strip())

    def _dlg_personnaliser_dashboard(self):
        dlg=self._dlg("⚙️ Personnaliser le tableau de bord",460,440)
        sf=self._sf_form(dlg,"Sections à afficher")
        actifs=self._get_kpis_actifs()
        options=[
            ("sante","💚 Indicateur de santé financière"),
            ("kpi","💰 Cartes KPI (solde, entrées, sorties…)"),
            ("alertes","⚠️ Alertes (échéances, seuils)"),
            ("top","🔝 Top 5 dépenses"),
            ("graphique","📈 Graphique évolution du solde"),
        ]
        vars_={}
        for key,label in options:
            v=ctk.BooleanVar(value=key in actifs)
            cb=ctk.CTkCheckBox(sf,text=label,variable=v,font=FB,
                               text_color=C("text"),fg_color=C("accent"))
            cb.pack(padx=20,pady=8,anchor="w")
            vars_[key]=v
        def submit():
            selected=[k for k,v in vars_.items() if v.get()]
            set_parametre("dashboard_kpis",",".join(selected) if selected else "kpi")
            dlg.destroy(); self.toast("✅ Préférences enregistrées.")
            self._refresh_dashboard_body()
        self._btns(dlg,"✔ Enregistrer",submit)

    # ── Indicateur santé financière ────────────────────────────────────────────
    def _calc_sante_financiere(self, solde, ch_actifs, alertes, echus):
        """Retourne (score, niveau, couleur, raison)."""
        score=100
        raisons=[]
        if solde<0:
            score-=50; raisons.append("solde négatif")
        elif solde<100000:
            score-=15; raisons.append("solde faible")
        if echus:
            score-=min(30,len(echus)*10); raisons.append(f"{len(echus)} chèque(s) échu(s)")
        if alertes:
            score-=min(20,len(alertes)*5); raisons.append(f"{len(alertes)} chèque(s) sous seuil")
        score=max(0,score)
        if score>=75:
            niveau,couleur="Bonne",C("green")
        elif score>=45:
            niveau,couleur="Moyenne",C("orange")
        else:
            niveau,couleur="À surveiller",C("red")
        raison=", ".join(raisons) if raisons else "Aucun problème détecté"
        return score,niveau,couleur,raison.capitalize()

    # ── RECHERCHE ─────────────────────────────────────────────────────────────
    def _page_recherche(self):
        frame=ctk.CTkFrame(self.content,fg_color=C("bg"))
        frame.pack(fill="both",expand=True)
        self._page_header(frame,"Recherche globale")
        sf_top=ctk.CTkFrame(frame,fg_color=C("panel"),corner_radius=10)
        sf_top.pack(fill="x",padx=28,pady=(14,0))
        self._rech_var=ctk.StringVar()
        e=ctk.CTkEntry(sf_top,height=40,font=FB,fg_color=C("card2"),
                       border_color=C("border"),textvariable=self._rech_var,
                       placeholder_text="Numéro chèque, bénéficiaire, désignation, notes…")
        e.pack(side="left",fill="x",expand=True,padx=14,pady=10)
        e.bind("<Return>",lambda ev:self._do_recherche(sf_res))
        ctk.CTkButton(sf_top,text="Chercher",height=38,width=100,
                      fg_color=C("accent"),font=FB,
                      command=lambda:self._do_recherche(sf_res)).pack(side="left",padx=(4,14))
        e.focus()

        # Recherche par montant
        sf_mnt=ctk.CTkFrame(frame,fg_color=C("panel"),corner_radius=10)
        sf_mnt.pack(fill="x",padx=28,pady=(10,0))
        ctk.CTkLabel(sf_mnt,text="💰 Par montant :",font=FS,
                     text_color=C("subtext")).pack(side="left",padx=(14,6),pady=10)
        e_min=ctk.CTkEntry(sf_mnt,width=130,height=36,font=FB,fg_color=C("card2"),
                           border_color=C("border"),placeholder_text="Min")
        e_min.pack(side="left",padx=3)
        ctk.CTkLabel(sf_mnt,text="—",font=FB,text_color=C("subtext")).pack(side="left",padx=4)
        e_max=ctk.CTkEntry(sf_mnt,width=130,height=36,font=FB,fg_color=C("card2"),
                           border_color=C("border"),placeholder_text="Max")
        e_max.pack(side="left",padx=3)
        type_mnt=ctk.StringVar(value="Tous")
        ctk.CTkOptionMenu(sf_mnt,values=["Tous","Entrée","Sortie"],variable=type_mnt,
                          fg_color=C("card2"),button_color=C("accent"),
                          height=36,font=FB,width=110).pack(side="left",padx=6)
        def chercher_montant():
            try:
                mn=float(e_min.get().strip() or 0)
                mx=float(e_max.get().strip() or 999999999)
            except:
                self.toast("⚠️ Montants invalides.",C("orange")); return
            tm={"Tous":None,"Entrée":"entree","Sortie":"sortie"}.get(type_mnt.get())
            for w in sf_res.winfo_children(): w.destroy()
            results=recherche_par_montant(mn,mx,tm)
            ctk.CTkLabel(sf_res,
                text=f"Transactions entre {mn:,.0f} et {mx:,.0f} {get_devise()} ({len(results)})",
                font=FH2,text_color=C("text")).pack(anchor="w",pady=(8,6))
            if results: self._table_transactions(sf_res,results,compact=True)
            else: ctk.CTkLabel(sf_res,text="Aucun résultat.",font=FB,
                               text_color=C("subtext")).pack(anchor="w",padx=8)
        ctk.CTkButton(sf_mnt,text="Chercher",height=36,width=90,fg_color=C("accent"),font=FB,
                      command=chercher_montant).pack(side="left",padx=8)

        sf_res=ctk.CTkScrollableFrame(frame,fg_color=C("bg"))
        sf_res.pack(fill="both",expand=True,padx=28,pady=14)
        ctk.CTkLabel(sf_res,text="Tapez un terme ou un montant et appuyez sur Chercher.",
                     font=FB,text_color=C("subtext")).pack(pady=30)

    def _do_recherche(self, sf_res):
        terme=self._rech_var.get().strip()
        for w in sf_res.winfo_children(): w.destroy()
        if not terme:
            ctk.CTkLabel(sf_res,text="Entrez un terme de recherche.",
                         font=FB,text_color=C("subtext")).pack(pady=30); return
        ch_res,tr_res=recherche_globale(terme)
        ctk.CTkLabel(sf_res,text=f"Chèques ({len(ch_res)})",
                     font=FH2,text_color=C("text")).pack(anchor="w",pady=(8,6))
        if ch_res: self._table_cheques(sf_res,ch_res,compact=True)
        else: ctk.CTkLabel(sf_res,text="Aucun chèque.",font=FB,text_color=C("subtext")).pack(anchor="w",padx=8)
        ctk.CTkLabel(sf_res,text=f"Transactions ({len(tr_res)})",
                     font=FH2,text_color=C("text")).pack(anchor="w",pady=(18,6))
        if tr_res: self._table_transactions(sf_res,tr_res,compact=True)
        else: ctk.CTkLabel(sf_res,text="Aucune transaction.",font=FB,text_color=C("subtext")).pack(anchor="w",padx=8)

    # ── CHÈQUES ───────────────────────────────────────────────────────────────
    def _page_cheques(self):
        self._ch_page=0
        frame=ctk.CTkFrame(self.content,fg_color=C("bg"))
        frame.pack(fill="both",expand=True)
        hdr=self._page_header(frame,"Chèques")
        bf_hdr=ctk.CTkFrame(hdr,fg_color="transparent"); bf_hdr.pack(side="right")
        ctk.CTkButton(bf_hdr,text="＋ Nouveau  (Ctrl+N)",font=FB,height=36,
                      fg_color=C("accent"),hover_color="#3570D4",
                      command=self._dlg_cheque).pack(side="left",padx=(0,4))
        ctk.CTkButton(bf_hdr,text="🔧 Recalculer",font=FB,height=36,
                      fg_color=C("orange"),hover_color="#D4890A",
                      command=self._dlg_recalcul_cheques).pack(side="left")

        flt=ctk.CTkFrame(frame,fg_color=C("panel"),corner_radius=10)
        flt.pack(fill="x",padx=28,pady=(14,0))
        ctk.CTkLabel(flt,text="🔍",font=FB,text_color=C("subtext")).pack(side="left",padx=(14,3),pady=10)
        self._ch_sv=tk.StringVar()
        ctk.CTkEntry(flt,height=34,font=FB,fg_color=C("card2"),border_color=C("border"),
                     textvariable=self._ch_sv,
                     placeholder_text="Numéro, bénéficiaire, banque…"
                     ).pack(side="left",padx=4,fill="x",expand=True)
        self._ch_statut=ctk.StringVar(value="Tous")
        ctk.CTkOptionMenu(flt,values=["Tous","En attente","Encaissé","Partiel","Clôturé"],
                          variable=self._ch_statut,fg_color=C("card2"),button_color=C("accent"),
                          height=34,font=FB,
                          command=lambda _:self._refresh_cheques(sf)).pack(side="left",padx=6)
        self._ch_archives=ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(flt,text="Afficher archivés",variable=self._ch_archives,
                        font=FS,text_color=C("subtext"),fg_color=C("accent"),
                        width=20,height=20,
                        command=lambda:self._refresh_cheques(sf)).pack(side="left",padx=10)
        ctk.CTkButton(flt,text="Chercher",height=34,width=88,fg_color=C("accent"),font=FB,
                      command=lambda:self._refresh_cheques(sf)).pack(side="left",padx=2)
        ctk.CTkButton(flt,text="✕ Effacer",height=34,width=88,
                      fg_color=C("card2"),hover_color=C("hover"),font=FB,
                      command=lambda:[self._ch_sv.set(""),
                                      self._ch_statut.set("Tous"),
                                      self._ch_archives.set(False),
                                      self._refresh_cheques(sf)]).pack(side="left",padx=(2,12))

        pf=ctk.CTkFrame(frame,fg_color="transparent")
        pf.pack(fill="x",padx=28,pady=(8,0))
        self._ch_page_lbl=ctk.CTkLabel(pf,text="",font=FS,text_color=C("subtext"))
        self._ch_page_lbl.pack(side="left")
        # side="right" : le 1er bouton packé est le plus à droite → on pack ▶ d'abord
        ctk.CTkButton(pf,text="▶",width=32,height=26,font=FB,fg_color=C("card2"),
                      hover_color=C("hover"),command=lambda:self._ch_next(sf)).pack(side="right",padx=2)
        ctk.CTkButton(pf,text="◀",width=32,height=26,font=FB,fg_color=C("card2"),
                      hover_color=C("hover"),command=lambda:self._ch_prev(sf)).pack(side="right",padx=2)

        sf=ctk.CTkScrollableFrame(frame,fg_color=C("bg"))
        sf.pack(fill="both",expand=True,padx=28,pady=(4,12))
        self._ch_sf=sf; self._refresh_cheques(sf)

    def _refresh_cheques(self, sf):
        for w in sf.winfo_children(): w.destroy()
        sm={"En attente":"en_attente","Encaissé":"encaisse",
            "Partiel":"partiellement_utilise","Clôturé":"cloture"}
        s=sm.get(self._ch_statut.get() if hasattr(self,"_ch_statut") else "Tous","")
        q=self._ch_sv.get() if hasattr(self,"_ch_sv") else ""
        archives=self._ch_archives.get() if hasattr(self,"_ch_archives") else False
        sb,sd=self._ch_sort
        data,total=get_all_cheques_v2(search=q,statut=s,sort_by=sb,sort_dir=sd,
                                      inclure_archives=archives,
                                      page=self._ch_page,page_size=PAGE_SIZE)
        pages=max(1,(total+PAGE_SIZE-1)//PAGE_SIZE)
        self._ch_total=total
        if hasattr(self,"_ch_page_lbl"):
            self._ch_page_lbl.configure(text=f"Page {self._ch_page+1}/{pages}  ({total} chèque(s))")
        self._table_cheques(sf,data,compact=False,rf=sf)

    def _ch_prev(self, sf):
        if self._ch_page>0: self._ch_page-=1; self._refresh_cheques(sf)
    def _ch_next(self, sf):
        pages=max(1,(getattr(self,"_ch_total",0)+PAGE_SIZE-1)//PAGE_SIZE)
        if self._ch_page<pages-1: self._ch_page+=1; self._refresh_cheques(sf)

    def _ch_sort_click(self, col, dir_):
        self._ch_sort=(col,dir_); self._refresh_cheques(self._ch_sf)

    def _menu_cheque(self, ch):
        """Menu « ⋯ » : actions secondaires d'un chèque (libellés explicites)."""
        m=tk.Menu(self,tearoff=0,bg=C("panel"),fg=C("text"),bd=0,relief="flat",
                  activebackground=C("accent"),activeforeground="#FFFFFF",font=("Segoe UI",10))
        for label,cmd in [
            ("🕐   Historique des modifications",lambda:self._dlg_historique_cheque(ch)),
            ("⧉   Dupliquer ce chèque",lambda:self._do_dupliquer_cheque(ch)),
            ("📄   Exporter la fiche en PDF",lambda:self._export_cheque_pdf(ch)),
            ("🖨️   Imprimer la fiche",lambda:self._print_cheque(ch)),
            ("⚙️   Champs personnalisés",lambda:self._dlg_champs_custom("cheque",ch["id"],f"#{ch['numero']}")),
        ]:
            m.add_command(label=label,command=cmd)
        try: m.tk_popup(self.winfo_pointerx(),self.winfo_pointery())
        finally: m.grab_release()

    def _table_cheques(self, parent, cheques, compact=False, rf=None):
        devise=get_devise()
        cols=[("numero","Numéro",105,True),("beneficiaire","Bénéficiaire",165,True),
              ("montant_initial","Initial",125,True),("montant_restant","Restant",125,True),
              ("date_emission","Émission",95,True),("date_echeance","Échéance",95,True),
              ("statut","Statut",120,True),("","Actions",205,False)]
        tbl=CanvasTable(parent,cols,sort=self._ch_sort,
                        on_sort=None if compact else self._ch_sort_click,bg=C("bg"))
        tbl.pack(fill="x",pady=(0,6))
        if not cheques:
            tbl.finish()
            ctk.CTkLabel(parent,text="Aucun chèque.",font=FB,
                         text_color=C("subtext")).pack(pady=20); return
        seuil=get_seuil_alerte(); today=date.today().isoformat()
        FSB=("Segoe UI",11,"bold")
        for idx,ch in enumerate(cheques):
            pct=ch["montant_restant"]/ch["montant_initial"]*100 if ch["montant_initial"] else 100
            alerte_seuil=pct<seuil and ch["statut"] not in ("cloture","encaisse")
            echu=bool(ch.get("date_echeance","") and ch["date_echeance"]<today
                      and ch["statut"] not in ("cloture","encaisse"))
            bg="#3A0A0A" if echu else ("#2A1A0A" if alerte_seuil else self._row_bg(idx))
            color_s,label_s=STATUT_COLORS.get(ch["statut"],(C("subtext"),ch["statut"]))
            num=str(ch["numero"]); ben=str(ch["beneficiaire"] or "")
            cells=[(trunc(num,"numero"),C("text"),FB,num if len(num)>TRUNC["numero"] else None),
                   (trunc(ben,"beneficiaire"),C("text"),FB,ben if len(ben)>TRUNC["beneficiaire"] else None),
                   (f"{ch['montant_initial']:,.0f} {devise}",C("text"),FB,None),
                   (f"{ch['montant_restant']:,.0f} {devise}",C("orange") if alerte_seuil else C("text"),FB,
                    f"Solde faible — Seulement {pct:.0f}% du montant restant" if alerte_seuil else None),
                   (ch["date_emission"],C("text"),FB,None),
                   (ch.get("date_echeance","") or "—",C("red") if echu else C("subtext"),FB,
                    "Échéance dépassée — Ce chèque n'est ni clôturé ni encaissé" if echu else None),
                   (label_s,color_s,FSB,None)]
            btns=None
            if not compact:
                btns=[("✏️",C("card2"),C("hover"),lambda c=ch:self._dlg_cheque(c),
                       "Modifier — Change le montant, le bénéficiaire, les dates ou les notes",None),
                      ("💸",C("orange"),C("hover"),lambda c=ch:self._dlg_depense_multi(c),
                       "Dépense — Enregistre une dépense sur ce chèque (ou répartie sur plusieurs)",None),
                      ("📋",C("accent"),C("hover"),lambda c=ch:self._dlg_hist_cheque(c),
                       "Détail — Liste toutes les transactions liées à ce chèque",None)]
                if ch["statut"] not in ("encaisse","cloture"):
                    btns.append(("✅",C("green"),"#2A9E6A",lambda c=ch:self._do_encaisser(c),
                                 "Encaisser — Marque ce chèque comme encaissé à la banque",None))
                btns.append(("⋯",C("card2"),C("hover"),lambda c=ch:self._menu_cheque(c),
                             "Plus d'actions — Historique, duplication, export PDF, impression, champs personnalisés",None))
                btns.append(("✕",C("red"),"#C44",lambda c=ch:self._del_cheque(c),
                             "Supprimer — Supprime ce chèque et ses transactions (confirmation demandée)","#FFFFFF"))
            tbl.add_row(bg,cells,btns)
        tbl.finish()

    # ── TRANSACTIONS ──────────────────────────────────────────────────────────
    def _page_transactions(self):
        self._tr_page=0
        frame=ctk.CTkFrame(self.content,fg_color=C("bg"))
        frame.pack(fill="both",expand=True)
        hdr=self._page_header(frame,"Transactions")
        bf=ctk.CTkFrame(hdr,fg_color="transparent"); bf.pack(side="right")
        for txt,fg,cmd in [
            ("＋ Entrée",C("green"),lambda:self._dlg_transaction("entree")),
            ("＋ Sortie",C("red"),lambda:self._dlg_transaction("sortie")),
            ("＋ Dépense chèque",C("orange"),self._dlg_depense_directe),
            ("📥 Importer",C("card2"),self._dlg_import),
            ("📤 Excel",C("card2"),self._export_excel),
            ("📄 PDF",C("card2"),self._export_pdf),
        ]:
            ctk.CTkButton(bf,text=txt,height=34,font=FB,fg_color=fg,
                          hover_color=C("hover"),command=cmd).pack(side="left",padx=2)

        flt=ctk.CTkFrame(frame,fg_color=C("panel"),corner_radius=10)
        flt.pack(fill="x",padx=28,pady=(14,0))
        ctk.CTkLabel(flt,text="Du:",font=FS,text_color=C("subtext")).pack(side="left",padx=(14,2),pady=10)
        self._tr_dd=ctk.CTkEntry(flt,width=104,height=32,font=FB,fg_color=C("card2"),
                                  border_color=C("border"),placeholder_text="AAAA-MM-JJ")
        self._tr_dd.pack(side="left",padx=3)
        ctk.CTkLabel(flt,text="Au:",font=FS,text_color=C("subtext")).pack(side="left",padx=(6,2))
        self._tr_df=ctk.CTkEntry(flt,width=104,height=32,font=FB,fg_color=C("card2"),
                                  border_color=C("border"),placeholder_text="AAAA-MM-JJ")
        self._tr_df.pack(side="left",padx=3)
        self._tr_type=ctk.StringVar(value="Tous")
        ctk.CTkOptionMenu(flt,values=["Tous","Entrée","Sortie"],variable=self._tr_type,
                          fg_color=C("card2"),button_color=C("accent"),height=32,font=FB,
                          command=lambda _:self._refresh_tr(sf)).pack(side="left",padx=6)
        cats=get_categories()
        self._tr_cats=cats
        cat_names=["Toutes catégories"]+[f"{c['icone']} {c['nom']}" for c in cats]
        self._tr_cat_var=ctk.StringVar(value="Toutes catégories")
        ctk.CTkOptionMenu(flt,values=cat_names,variable=self._tr_cat_var,
                          fg_color=C("card2"),button_color=C("accent"),height=32,font=FB,
                          command=lambda _:self._refresh_tr(sf)).pack(side="left",padx=4)
        self._tr_sv=tk.StringVar()
        ctk.CTkEntry(flt,width=160,height=32,font=FB,fg_color=C("card2"),
                     border_color=C("border"),textvariable=self._tr_sv,
                     placeholder_text="Désignation, réf…"
                     ).pack(side="left",padx=4)
        ctk.CTkButton(flt,text="Chercher",height=32,width=80,fg_color=C("accent"),font=FB,
                      command=lambda:self._refresh_tr(sf)).pack(side="left",padx=2)
        ctk.CTkButton(flt,text="✕",height=32,width=36,
                      fg_color=C("card2"),hover_color=C("hover"),font=FB,
                      command=lambda:[self._tr_dd.delete(0,"end"),
                                      self._tr_df.delete(0,"end"),
                                      self._tr_type.set("Tous"),
                                      self._tr_cat_var.set("Toutes catégories"),
                                      self._tr_sv.set(""),
                                      self._refresh_tr(sf)]).pack(side="left",padx=(2,12))

        pf=ctk.CTkFrame(frame,fg_color="transparent")
        pf.pack(fill="x",padx=28,pady=(8,0))
        self._page_lbl=ctk.CTkLabel(pf,text="",font=FS,text_color=C("subtext"))
        self._page_lbl.pack(side="left")
        # side="right" : le 1er bouton packé est le plus à droite → on pack ▶ d'abord
        ctk.CTkButton(pf,text="▶",width=32,height=26,font=FB,fg_color=C("card2"),
                      hover_color=C("hover"),command=lambda:self._tr_next(sf)).pack(side="right",padx=2)
        ctk.CTkButton(pf,text="◀",width=32,height=26,font=FB,fg_color=C("card2"),
                      hover_color=C("hover"),command=lambda:self._tr_prev(sf)).pack(side="right",padx=2)

        sf=ctk.CTkScrollableFrame(frame,fg_color=C("bg"))
        sf.pack(fill="both",expand=True,padx=28,pady=(4,12))
        self._tr_sf=sf; self._refresh_tr(sf)

    def _get_tr_data(self):
        dd =self._tr_dd.get()  if hasattr(self,"_tr_dd")  else ""
        df =self._tr_df.get()  if hasattr(self,"_tr_df")  else ""
        tv =self._tr_type.get()if hasattr(self,"_tr_type")else "Tous"
        sr =self._tr_sv.get()  if hasattr(self,"_tr_sv")  else ""
        type_={"Entrée":"entree","Sortie":"sortie"}.get(tv)
        cat_id=None
        if hasattr(self,"_tr_cat_var") and hasattr(self,"_tr_cats"):
            sel=self._tr_cat_var.get()
            if sel!="Toutes catégories":
                for c in self._tr_cats:
                    if c["nom"] in sel: cat_id=c["id"]; break
        sb,sd=self._tr_sort
        return get_transactions(date_debut=dd,date_fin=df,type_=type_,
                                search=sr,categorie_id=cat_id,sort_by=sb,sort_dir=sd)

    def _refresh_tr(self, sf):
        for w in sf.winfo_children(): w.destroy()
        all_tr=self._get_tr_data(); total=len(all_tr)
        start=self._tr_page*PAGE_SIZE; pg_tr=all_tr[start:start+PAGE_SIZE]
        pages=max(1,(total+PAGE_SIZE-1)//PAGE_SIZE)
        self._tr_total=total
        self._page_lbl.configure(text=f"Page {self._tr_page+1}/{pages}  ({total} transaction(s))")
        self._table_transactions(sf,pg_tr,compact=False,rf=sf,all_tr=all_tr,start=start)

    def _tr_prev(self, sf):
        if self._tr_page>0: self._tr_page-=1; self._refresh_tr(sf)
    def _tr_next(self, sf):
        pages=max(1,(getattr(self,"_tr_total",0)+PAGE_SIZE-1)//PAGE_SIZE)
        if self._tr_page<pages-1: self._tr_page+=1; self._refresh_tr(sf)
    def _tr_sort_click(self, col, dir_):
        self._tr_sort=(col,dir_)
        if hasattr(self,"_tr_sf"): self._refresh_tr(self._tr_sf)

    def _table_transactions(self, parent, transactions, compact=False,
                             rf=None, all_tr=None, start=0):
        devise=get_devise()
        cols=[("date_transaction","Date",100,True),("type","Type",75,True),
              ("designation","Désignation",210,True),("cat_nom","Catégorie",120,False),
              ("montant","Montant",120,True),("solde","Solde",120,False),
              ("reference","Réf.",80,False),("","Actions",125,False)]
        tbl=CanvasTable(parent,cols,sort=self._tr_sort,
                        on_sort=None if compact else self._tr_sort_click,bg=C("bg"))
        tbl.pack(fill="x",pady=(0,6))
        if not transactions:
            tbl.finish()
            ctk.CTkLabel(parent,text="Aucune transaction.",font=FB,
                         text_color=C("subtext")).pack(pady=20); return
        s_ouv=float(get_parametre("solde_ouverture","0"))
        # Solde cumulé calculé dans l'ordre CHRONOLOGIQUE (et non dans l'ordre d'affichage)
        bal={}; run=s_ouv
        for t in sorted(all_tr or transactions,key=lambda x:(x["date_transaction"],x["id"])):
            run+=t["montant"] if t["type"]=="entree" else -t["montant"]
            bal[t["id"]]=run
        FBB=("Segoe UI",12,"bold")
        for idx,t in enumerate(transactions):
            solde_c=bal.get(t["id"],0)
            is_e=t["type"]=="entree"
            color=C("green") if is_e else C("red")
            des=str(t["designation"] or "")
            cat=f"{t.get('cat_icone','') or ''} {t.get('cat_nom','') or '—'}"
            pj=t.get("piece_jointe")
            cells=[(t["date_transaction"],C("subtext"),FB,None),
                   ("↑ Entrée" if is_e else "↓ Sortie",color,FB,None),
                   (trunc(des,"designation"),C("text"),FB,des if len(des)>TRUNC["designation"] else None),
                   (cat,C("subtext"),FB,None),
                   (f"{t['montant']:,.0f}",color,FBB,None),
                   (f"{solde_c:,.0f}",C("green") if solde_c>=0 else C("red"),FB,None),
                   (("📎 " if pj else "")+trunc(t.get("reference",""),"reference"),C("subtext"),FS,
                    f"Pièce jointe — {pj}" if pj else None)]
            btns=None
            if not compact:
                btns=[("✏️",C("card2"),C("hover"),lambda tr=t:self._dlg_transaction(tr["type"],tr),
                       "Modifier — Change le montant, la date, la catégorie ou les notes",None),
                      ("💬",C("card2"),C("hover"),lambda tr=t:self._dlg_commentaires(tr),
                       "Commentaires — Lire ou ajouter des commentaires sur cette transaction",None)]
                if t.get("cheque_id") and t["type"]=="sortie":
                    btns.append(("🔀",C("card2"),C("hover"),lambda tr=t:self._dlg_changer_cheque_depense(tr),
                                 "Changer de chèque — Réaffecte cette dépense à un autre chèque",None))
                if not (t.get("cheque_id") and t["type"]=="entree"):
                    btns.append(("✕",C("red"),"#C44",lambda tid=t["id"]:self._del_transaction(tid),
                                 "Supprimer — Supprime cette transaction (confirmation demandée)","#FFFFFF"))
            tbl.add_row(self._row_bg(idx),cells,btns)
        tbl.finish()

    # ── STATISTIQUES ──────────────────────────────────────────────────────────
    def _reload_stats(self, frame, jours):
        for w in frame.winfo_children(): w.destroy()
        hdr=self._page_header(frame,"Statistiques")
        pf=ctk.CTkFrame(hdr,fg_color="transparent"); pf.pack(side="right")
        for j,label in [("7","7j"),("30","30j"),("90","3m"),("365","1an")]:
            ctk.CTkButton(pf,text=label,width=52,height=28,font=FS,
                          fg_color=C("accent") if j==str(jours) else C("card2"),
                          hover_color=C("hover"),
                          command=lambda d=j:self._reload_stats(frame,int(d))
                          ).pack(side="left",padx=2)
        loading=ctk.CTkLabel(frame,text="⏳ Chargement des graphiques…",
                              font=FH3,text_color=C("subtext"))
        loading.pack(pady=30)
        def load():
            try: self._render_stats(frame,jours,loading)
            except Exception as ex:
                def show_err(): loading.configure(text=f"Erreur : {ex}")
                self.after(0,show_err)
        threading.Thread(target=load,daemon=True).start()

    def _page_stats(self, jours=30):
        frame=ctk.CTkScrollableFrame(self.content,fg_color=C("bg"))
        frame.pack(fill="both",expand=True)
        self._reload_stats(frame,jours)

    def _render_stats(self, frame, nb_jours, loading_lbl=None):
        import matplotlib.pyplot as plt
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
        import matplotlib.patches as mpatches
        devise=get_devise()
        BG=C("bg"); GRID=C("border"); TXT=C("text")

        charts=[]

        # Évolution solde
        dates,soldes=get_evolution_solde(nb_jours)
        fig,ax=plt.subplots(figsize=(10,3),facecolor=BG)
        ax.set_facecolor(BG)
        if dates:
            ax.plot(dates,soldes,color=C("accent"),linewidth=2.5,marker="o",markersize=4)
            ax.fill_between(dates,soldes,alpha=0.13,color=C("accent"))
        ax.xaxis.set_tick_params(rotation=38); ax.grid(color=GRID,linewidth=0.4,alpha=0.6)
        ax.tick_params(colors=TXT,labelsize=8)
        for s in ax.spines.values(): s.set_edgecolor(GRID)
        ax.set_title(f"Évolution du solde ({nb_jours}j)",color=TXT,fontsize=11,pad=8)
        fig.tight_layout(); charts.append(("Évolution solde",fig))

        # Stats mensuelles
        stats_m=get_stats_mensuelles()
        if stats_m:
            import numpy as np
            mois_noms=["Jan","Fév","Mar","Avr","Mai","Jun","Jul","Aoû","Sep","Oct","Nov","Déc"]
            xs=[mois_noms[int(s["mois"])-1] for s in stats_m]
            ent=[s["entrees"] for s in stats_m]; sor=[s["sorties"] for s in stats_m]
            x=np.arange(len(xs)); w=0.35
            fig2,ax2=plt.subplots(figsize=(10,3),facecolor=BG)
            ax2.set_facecolor(BG)
            ax2.bar(x-w/2,ent,w,color=C("green"),label="Entrées",edgecolor=BG)
            ax2.bar(x+w/2,sor,w,color=C("red"),label="Sorties",edgecolor=BG)
            ax2.set_xticks(x); ax2.set_xticklabels(xs)
            ax2.legend(facecolor=BG,edgecolor=GRID,labelcolor=TXT,fontsize=8)
            ax2.grid(axis="y",color=GRID,linewidth=0.4,alpha=0.6)
            ax2.tick_params(colors=TXT,labelsize=8)
            for s in ax2.spines.values(): s.set_edgecolor(GRID)
            ax2.set_title(f"Entrées vs Sorties ({date.today().year})",color=TXT,fontsize=11,pad=8)
            fig2.tight_layout(); charts.append(("Stats mensuelles",fig2))

        # Répartition dépenses
        stats=get_stats_categories()
        if stats:
            labels=[s["nom"] for s in stats]; values=[s["total"] for s in stats]
            cp=[safe_color(s["couleur"]) for s in stats]
            fig3,ax3=plt.subplots(figsize=(7,3.5),facecolor=BG)
            ax3.set_facecolor(BG)
            _,_,autos=ax3.pie(values,colors=cp,autopct="%1.1f%%",startangle=140,
                               pctdistance=0.82,wedgeprops={"linewidth":1.5,"edgecolor":BG})
            for t in autos: t.set_color(TXT); t.set_fontsize(9)
            patches=[mpatches.Patch(color=c,label=l) for c,l in zip(cp,labels)]
            ax3.legend(handles=patches,loc="lower right",fontsize=8,
                       facecolor=BG,edgecolor=GRID,labelcolor=TXT)
            ax3.set_title("Répartition dépenses",color=TXT,fontsize=11,pad=8)
            fig3.tight_layout(); charts.append(("Répartition",fig3))

        # Comparatif mois par mois (12 derniers mois)
        comp=get_comparatif_mensuel(date.today().year,12)
        if comp:
            labels4=[c["label"] for c in comp]
            ent4=[c["entrees"] for c in comp]; sor4=[c["sorties"] for c in comp]
            sol4=[c["solde"] for c in comp]
            fig4,ax4=plt.subplots(figsize=(10,3),facecolor=BG)
            ax4.set_facecolor(BG)
            ax4.plot(labels4,ent4,color=C("green"),linewidth=2,marker="o",markersize=3,label="Entrées")
            ax4.plot(labels4,sor4,color=C("red"),linewidth=2,marker="o",markersize=3,label="Sorties")
            ax4.plot(labels4,sol4,color=C("accent"),linewidth=2,marker="s",markersize=3,
                     linestyle="--",label="Solde mois")
            ax4.xaxis.set_tick_params(rotation=40)
            ax4.legend(facecolor=BG,edgecolor=GRID,labelcolor=TXT,fontsize=8)
            ax4.grid(color=GRID,linewidth=0.4,alpha=0.6)
            ax4.tick_params(colors=TXT,labelsize=7)
            for s in ax4.spines.values(): s.set_edgecolor(GRID)
            ax4.set_title("Comparatif mois par mois (12 derniers)",color=TXT,fontsize=11,pad=8)
            fig4.tight_layout(); charts.append(("Comparatif mensuel",fig4))

        def show_charts():
            if loading_lbl:
                try: loading_lbl.destroy()
                except: pass
            for _,fig in charts:
                card=ctk.CTkFrame(frame,fg_color=C("card"),corner_radius=12)
                card.pack(fill="x",padx=28,pady=(0,14))
                FigureCanvasTkAgg(fig,master=card).get_tk_widget().pack(padx=10,pady=10,fill="x")
                plt.close(fig)
        self.after(0,show_charts)

    # ── RAPPORTS ──────────────────────────────────────────────────────────────
    def _page_rapports(self):
        frame=ctk.CTkScrollableFrame(self.content,fg_color=C("bg"))
        frame.pack(fill="both",expand=True)
        hdr=self._page_header(frame,"Rapports & Exports")
        # Convertisseur devise dans le header
        if get_devise_secondaire():
            ctk.CTkButton(hdr,text=f"💱 Convertisseur",height=34,font=FB,
                          fg_color=C("card2"),hover_color=C("hover"),
                          command=self._dlg_convertisseur).pack(side="right",padx=6)

        def section(title, color):
            fr=ctk.CTkFrame(frame,fg_color=C("card"),corner_radius=14)
            fr.pack(fill="x",padx=28,pady=(16,0))
            ctk.CTkLabel(fr,text=title,font=FH3,text_color=color).pack(padx=18,pady=(14,8),anchor="w")
            return fr

        def btn_row(parent, buttons):
            """Ligne de boutons PDF / Excel / Aperçu / Imprimer."""
            fr=ctk.CTkFrame(parent,fg_color="transparent"); fr.pack(side="left",padx=8)
            for txt,fg,cmd in buttons:
                ctk.CTkButton(fr,text=txt,height=34,width=100,fg_color=fg,font=FB,
                              command=cmd).pack(side="left",padx=3)
            return fr

        # ── Rapport général
        s1=section("📊 Rapport général","#4F8EF7")
        rf1=ctk.CTkFrame(s1,fg_color="transparent"); rf1.pack(fill="x",padx=18,pady=(0,14))
        ctk.CTkLabel(rf1,text="Du :",font=FS,text_color=C("subtext")).grid(row=0,column=0,padx=(0,4),pady=6)
        e_dd=ctk.CTkEntry(rf1,width=115,height=34,font=FB,fg_color=C("card2"),
                           placeholder_text="AAAA-MM-JJ"); e_dd.grid(row=0,column=1,padx=3)
        ctk.CTkLabel(rf1,text="Au :",font=FS,text_color=C("subtext")).grid(row=0,column=2,padx=(6,4))
        e_df=ctk.CTkEntry(rf1,width=115,height=34,font=FB,fg_color=C("card2"),
                           placeholder_text="AAAA-MM-JJ"); e_df.grid(row=0,column=3,padx=3)
        def rap_gen_pdf():
            fp=filedialog.asksaveasfilename(defaultextension=".pdf",
                filetypes=[("PDF","*.pdf")],initialfile=f"rapport_{date.today()}.pdf")
            if not fp: return
            ok,msg=export_to_pdf(fp,e_dd.get().strip(),e_df.get().strip())
            self.toast(("✅ " if ok else "❌ ")+msg,C("green") if ok else C("red"))
        def rap_gen_apercu():
            self._apercu_et_export(export_to_pdf,e_dd.get().strip(),e_df.get().strip(),
                                   suffix=f"rapport_{date.today()}")
        def rap_gen_print():
            import tempfile; fp=os.path.join(tempfile.gettempdir(),"cg_print_gen.pdf")
            ok,msg=export_to_pdf(fp,e_dd.get().strip(),e_df.get().strip())
            if ok: self._print_direct(fp)
            else:  self.toast("❌ "+msg,C("red"))
        def rap_gen_xl():
            fp=filedialog.asksaveasfilename(defaultextension=".xlsx",
                filetypes=[("Excel","*.xlsx")],initialfile=f"rapport_{date.today()}.xlsx")
            if not fp: return
            try: export_to_excel(fp,e_dd.get().strip(),e_df.get().strip()); self.toast("✅ Excel OK.")
            except Exception as ex: self.toast(f"❌ {ex}",C("red"))
        bf1=ctk.CTkFrame(rf1,fg_color="transparent"); bf1.grid(row=0,column=4,padx=10)
        for txt,fg,cmd in [("📄 PDF",C("accent"),rap_gen_pdf),
                            ("👁 Aperçu",C("card2"),rap_gen_apercu),
                            ("🖨️ Imprimer",C("card2"),rap_gen_print),
                            ("📤 Excel",C("green"),rap_gen_xl)]:
            ctk.CTkButton(bf1,text=txt,height=34,width=94,fg_color=fg,
                          hover_color=C("hover"),font=FB,command=cmd).pack(side="left",padx=2)

        # ── Rapport mensuel
        s2=section("📅 Rapport mensuel","#3DD68C")
        rf2=ctk.CTkFrame(s2,fg_color="transparent"); rf2.pack(fill="x",padx=18,pady=(0,14))
        mois_opts=[f"{i:02d} — {n}" for i,n in enumerate(
            ["Janvier","Février","Mars","Avril","Mai","Juin",
             "Juillet","Août","Septembre","Octobre","Novembre","Décembre"],1)]
        m_var=ctk.StringVar(value=mois_opts[date.today().month-1])
        ctk.CTkOptionMenu(rf2,values=mois_opts,variable=m_var,
                          fg_color=C("card2"),button_color=C("accent"),
                          height=34,font=FB,width=220).grid(row=0,column=0,padx=(0,6))
        annees=[str(y) for y in range(date.today().year,date.today().year-5,-1)]
        a_var=ctk.StringVar(value=str(date.today().year))
        ctk.CTkOptionMenu(rf2,values=annees,variable=a_var,
                          fg_color=C("card2"),button_color=C("accent"),
                          height=34,font=FB,width=100).grid(row=0,column=1,padx=4)
        def _get_ma(): return int(m_var.get()[:2]), int(a_var.get())
        def rap_mensuel_pdf():
            m,a=_get_ma()
            fp=filedialog.asksaveasfilename(defaultextension=".pdf",
                filetypes=[("PDF","*.pdf")],initialfile=f"rapport_{a}_{m:02d}.pdf")
            if not fp: return
            ok,msg=export_rapport_mensuel_pdf(fp,a,m)
            self.toast(("✅ " if ok else "❌ ")+msg,C("green") if ok else C("red"))
        def rap_mensuel_apercu():
            m,a=_get_ma()
            self._apercu_et_export(export_rapport_mensuel_pdf,a,m,suffix=f"rapport_{a}_{m:02d}")
        def rap_mensuel_print():
            m,a=_get_ma()
            import tempfile; fp=os.path.join(tempfile.gettempdir(),"cg_print_mens.pdf")
            ok,msg=export_rapport_mensuel_pdf(fp,a,m)
            if ok: self._print_direct(fp)
            else:  self.toast("❌ "+msg,C("red"))
        bf2=ctk.CTkFrame(rf2,fg_color="transparent"); bf2.grid(row=0,column=2,padx=10)
        for txt,fg,cmd in [("📄 PDF",C("accent"),rap_mensuel_pdf),
                            ("👁 Aperçu",C("card2"),rap_mensuel_apercu),
                            ("🖨️ Imprimer",C("card2"),rap_mensuel_print)]:
            ctk.CTkButton(bf2,text=txt,height=34,width=94,fg_color=fg,
                          hover_color=C("hover"),font=FB,command=cmd).pack(side="left",padx=2)

        # ── Rapport catégories
        s3=section("🗂️ Rapport par catégorie","#F5A623")
        rf3=ctk.CTkFrame(s3,fg_color="transparent"); rf3.pack(fill="x",padx=18,pady=(0,14))
        ctk.CTkLabel(rf3,text="Du :",font=FS,text_color=C("subtext")).grid(row=0,column=0,padx=(0,4))
        e_cdd=ctk.CTkEntry(rf3,width=115,height=34,font=FB,fg_color=C("card2"),
                            placeholder_text="AAAA-MM-JJ"); e_cdd.grid(row=0,column=1,padx=3)
        ctk.CTkLabel(rf3,text="Au :",font=FS,text_color=C("subtext")).grid(row=0,column=2,padx=(6,4))
        e_cdf=ctk.CTkEntry(rf3,width=115,height=34,font=FB,fg_color=C("card2"),
                            placeholder_text="AAAA-MM-JJ"); e_cdf.grid(row=0,column=3,padx=3)
        def rap_cats_pdf():
            fp=filedialog.asksaveasfilename(defaultextension=".pdf",
                filetypes=[("PDF","*.pdf")],initialfile=f"rapport_categories_{date.today()}.pdf")
            if not fp: return
            ok,msg=export_rapport_categories_pdf(fp,e_cdd.get().strip(),e_cdf.get().strip())
            self.toast(("✅ " if ok else "❌ ")+msg,C("green") if ok else C("red"))
        def rap_cats_apercu():
            self._apercu_et_export(export_rapport_categories_pdf,
                                   e_cdd.get().strip(),e_cdf.get().strip(),suffix="rapport_categories")
        def rap_cats_print():
            import tempfile; fp=os.path.join(tempfile.gettempdir(),"cg_print_cats.pdf")
            ok,msg=export_rapport_categories_pdf(fp,e_cdd.get().strip(),e_cdf.get().strip())
            if ok: self._print_direct(fp)
            else:  self.toast("❌ "+msg,C("red"))
        bf3=ctk.CTkFrame(rf3,fg_color="transparent"); bf3.grid(row=0,column=4,padx=10)
        for txt,fg,cmd in [("📄 PDF",C("orange"),rap_cats_pdf),
                            ("👁 Aperçu",C("card2"),rap_cats_apercu),
                            ("🖨️ Imprimer",C("card2"),rap_cats_print)]:
            ctk.CTkButton(bf3,text=txt,height=34,width=94,fg_color=fg,
                          hover_color=C("hover"),font=FB,command=cmd).pack(side="left",padx=2)

        # ── Rapport chèques (filtrable)
        s4=section("📋 Rapport chèques","#F75F5F")
        rf4=ctk.CTkFrame(s4,fg_color="transparent"); rf4.pack(fill="x",padx=18,pady=(0,14))
        st_opts=["Tous","En attente","Encaissé","Partiel","Clôturé"]
        st_var=ctk.StringVar(value="Tous")
        ctk.CTkOptionMenu(rf4,values=st_opts,variable=st_var,
                          fg_color=C("card2"),button_color=C("accent"),
                          height=34,font=FB,width=160).grid(row=0,column=0,padx=(0,6))
        ctk.CTkLabel(rf4,text="Du :",font=FS,text_color=C("subtext")).grid(row=0,column=1,padx=(6,4))
        e_chdd=ctk.CTkEntry(rf4,width=115,height=34,font=FB,fg_color=C("card2"),
                             placeholder_text="AAAA-MM-JJ"); e_chdd.grid(row=0,column=2,padx=3)
        ctk.CTkLabel(rf4,text="Au :",font=FS,text_color=C("subtext")).grid(row=0,column=3,padx=(6,4))
        e_chdf=ctk.CTkEntry(rf4,width=115,height=34,font=FB,fg_color=C("card2"),
                             placeholder_text="AAAA-MM-JJ"); e_chdf.grid(row=0,column=4,padx=3)
        st_map={"Tous":"","En attente":"en_attente","Encaissé":"encaisse",
                "Partiel":"partiellement_utilise","Clôturé":"cloture"}
        def rap_ch_pdf():
            st=st_map.get(st_var.get(),"")
            fp=filedialog.asksaveasfilename(defaultextension=".pdf",
                filetypes=[("PDF","*.pdf")],initialfile=f"rapport_cheques_{date.today()}.pdf")
            if not fp: return
            ok,msg=export_rapport_cheques_pdf(fp,st,e_chdd.get().strip(),e_chdf.get().strip())
            self.toast(("✅ " if ok else "❌ ")+msg,C("green") if ok else C("red"))
        def rap_ch_print():
            st=st_map.get(st_var.get(),"")
            import tempfile; fp=os.path.join(tempfile.gettempdir(),"cg_print_cheques.pdf")
            ok,msg=export_rapport_cheques_pdf(fp,st,e_chdd.get().strip(),e_chdf.get().strip())
            if ok: self._print_direct(fp)
            else:  self.toast("❌ "+msg,C("red"))
        bf4=ctk.CTkFrame(rf4,fg_color="transparent"); bf4.grid(row=0,column=5,padx=10)
        for txt,fg,cmd in [("📄 PDF",C("red"),rap_ch_pdf),
                            ("🖨️ Imprimer",C("card2"),rap_ch_print)]:
            ctk.CTkButton(bf4,text=txt,height=34,width=100,fg_color=fg,
                          hover_color=C("hover"),font=FB,command=cmd).pack(side="left",padx=2)

        # ── Fiche chèque individuel (PDF + Excel + Aperçu + Imprimer)
        s5=section("🔖 Fiche chèque individuel","#7C5CFC")
        rf5=ctk.CTkFrame(s5,fg_color="transparent"); rf5.pack(fill="x",padx=18,pady=(0,14))
        cheques=get_all_cheques()
        ch_names=[f"#{c['numero']} — {c['beneficiaire']}" for c in cheques]
        ch_var=ctk.StringVar(value=ch_names[0] if ch_names else "Aucun chèque")
        ctk.CTkOptionMenu(rf5,values=ch_names or ["Aucun chèque"],variable=ch_var,
                          fg_color=C("card2"),button_color=C("accent"),
                          height=34,font=FB,width=300).grid(row=0,column=0,padx=(0,8))
        def _get_ch():
            if not cheques: return None
            idx=ch_names.index(ch_var.get()); return cheques[idx]
        def fiche_pdf():
            ch=_get_ch()
            if not ch: self.toast("⚠️ Aucun chèque.",C("orange")); return
            fp=filedialog.asksaveasfilename(defaultextension=".pdf",
                filetypes=[("PDF","*.pdf")],initialfile=f"cheque_{ch['numero']}.pdf")
            if not fp: return
            ok,msg=export_cheque_pdf(fp,ch["id"])
            self.toast(("✅ " if ok else "❌ ")+msg,C("green") if ok else C("red"))
        def fiche_apercu():
            ch=_get_ch()
            if not ch: return
            import tempfile; fp=os.path.join(tempfile.gettempdir(),f"cg_ch_{ch['numero']}.pdf")
            ok,msg=export_cheque_pdf(fp,ch["id"])
            if ok: self._apercu_pdf(fp)
            else:  self.toast("❌ "+msg,C("red"))
        def fiche_print():
            ch=_get_ch()
            if not ch: return
            self._print_cheque(ch)
        def fiche_excel():
            ch=_get_ch()
            if not ch: return
            fp=filedialog.asksaveasfilename(defaultextension=".xlsx",
                filetypes=[("Excel","*.xlsx")],initialfile=f"cheque_{ch['numero']}.xlsx")
            if not fp: return
            ok,msg=export_cheque_excel(fp,ch["id"])
            self.toast(("✅ " if ok else "❌ ")+msg,C("green") if ok else C("red"))
        bf5=ctk.CTkFrame(rf5,fg_color="transparent"); bf5.grid(row=0,column=1,padx=10)
        for txt,fg,cmd in [("📄 PDF","#7C5CFC",fiche_pdf),
                            ("👁 Aperçu",C("card2"),fiche_apercu),
                            ("🖨️ Imprimer",C("card2"),fiche_print),
                            ("📤 Excel",C("green"),fiche_excel)]:
            ctk.CTkButton(bf5,text=txt,height=34,width=94,fg_color=fg,
                          hover_color=C("hover"),font=FB,command=cmd).pack(side="left",padx=2)

        ctk.CTkFrame(frame,height=20,fg_color="transparent").pack()

    # ── BUDGETS ───────────────────────────────────────────────────────────────
    def _page_budgets(self):
        frame=ctk.CTkFrame(self.content,fg_color=C("bg"))
        frame.pack(fill="both",expand=True)
        hdr=self._page_header(frame,"Budgets mensuels")

        ctrl=ctk.CTkFrame(hdr,fg_color="transparent"); ctrl.pack(side="right")
        mois_opts=[f"{i:02d}" for i in range(1,13)]
        self._bud_mois=ctk.StringVar(value=f"{date.today().month:02d}")
        ctk.CTkOptionMenu(ctrl,values=mois_opts,variable=self._bud_mois,
                          fg_color=C("card2"),button_color=C("accent"),
                          height=32,font=FB,width=80,
                          command=lambda _:self._refresh_budgets(sf)).pack(side="left",padx=4)
        annees=[str(y) for y in range(date.today().year,date.today().year-4,-1)]
        self._bud_annee=ctk.StringVar(value=str(date.today().year))
        ctk.CTkOptionMenu(ctrl,values=annees,variable=self._bud_annee,
                          fg_color=C("card2"),button_color=C("accent"),
                          height=32,font=FB,width=100,
                          command=lambda _:self._refresh_budgets(sf)).pack(side="left",padx=4)

        sf=ctk.CTkScrollableFrame(frame,fg_color=C("bg"))
        sf.pack(fill="both",expand=True,padx=28,pady=12)
        self._bud_sf=sf; self._refresh_budgets(sf)

    def _refresh_budgets(self, sf):
        for w in sf.winfo_children(): w.destroy()
        annee=int(self._bud_annee.get()); mois=int(self._bud_mois.get())
        devise=get_devise()
        budgets=get_budgets(annee,mois)
        cats_sortie=get_categories(type_="sortie")

        # Bouton ajout budget
        bf=ctk.CTkFrame(sf,fg_color="transparent"); bf.pack(fill="x",pady=(0,12))
        cats_sans_budget={c["id"] for c in cats_sortie}-{b["categorie_id"] for b in budgets}
        cats_dispo=[c for c in cats_sortie if c["id"] in cats_sans_budget]
        if cats_dispo:
            ctk.CTkButton(bf,text="＋ Ajouter un budget",height=34,fg_color=C("accent"),font=FB,
                          command=lambda:self._dlg_budget(cats_dispo,annee,mois,sf)
                          ).pack(side="left")

        if not budgets:
            ctk.CTkLabel(sf,text="Aucun budget défini pour ce mois. Cliquez sur Ajouter.",
                         font=FB,text_color=C("subtext")).pack(pady=30)
            return

        # En-tête
        hdr=ctk.CTkFrame(sf,fg_color=C("card2"),corner_radius=8)
        hdr.pack(fill="x",pady=(0,4))
        for i,(col,w) in enumerate(zip(["Catégorie","Budget","Dépensé","Restant","Avancement","Action"],
                                        [180,120,120,120,200,80])):
            ctk.CTkLabel(hdr,text=col,font=("Segoe UI",11,"bold"),
                         text_color=C("subtext"),width=w).grid(row=0,column=i,padx=6,pady=7,sticky="w")

        for idx,b in enumerate(budgets):
            dep=b["depense"]; bud=b["montant"]
            pct=min(dep/bud,1.0) if bud>0 else 0
            over=dep>bud
            row=ctk.CTkFrame(sf,fg_color=self._row_bg(idx),corner_radius=8)
            row.pack(fill="x",pady=2)
            ctk.CTkLabel(row,text=f"{b.get('cat_icone','') or ''} {b['cat_nom']}",
                         font=FB,text_color=C("text"),width=180,anchor="w").grid(row=0,column=0,padx=6,pady=8,sticky="w")
            ctk.CTkLabel(row,text=f"{bud:,.0f} {devise}",font=FB,text_color=C("text"),
                         width=120,anchor="w").grid(row=0,column=1,padx=6,pady=8,sticky="w")
            ctk.CTkLabel(row,text=f"{dep:,.0f} {devise}",font=FB,
                         text_color=C("red") if over else C("text"),
                         width=120,anchor="w").grid(row=0,column=2,padx=6,pady=8,sticky="w")
            rest=bud-dep
            ctk.CTkLabel(row,text=f"{rest:,.0f} {devise}",font=FB,
                         text_color=C("red") if rest<0 else C("green"),
                         width=120,anchor="w").grid(row=0,column=3,padx=6,pady=8,sticky="w")
            bar=ctk.CTkProgressBar(row,width=190,height=12,
                                    fg_color=C("card2"),
                                    progress_color=C("red") if over else C("green"))
            bar.set(pct); bar.grid(row=0,column=4,padx=6,pady=8,sticky="w")
            af=ctk.CTkFrame(row,fg_color="transparent"); af.grid(row=0,column=5,padx=4,pady=4)
            ctk.CTkButton(af,text="✏️",width=30,height=28,font=FS,
                          fg_color=C("card2"),hover_color=C("hover"),
                          command=lambda bx=b:self._dlg_budget_edit(bx,annee,mois,sf)
                          ).pack(side="left",padx=1)
            ctk.CTkButton(af,text="✕",width=28,height=28,font=FS,
                          fg_color=C("red"),hover_color="#C44",
                          command=lambda bx=b:self._del_budget(bx,annee,mois,sf)
                          ).pack(side="left",padx=1)

        # Graphique camembert budget vs dépensé
        chart_fr=ctk.CTkFrame(sf,fg_color=C("card"),corner_radius=14)
        chart_fr.pack(fill="x",pady=(16,8))
        ctk.CTkLabel(chart_fr,text="📊 Budget vs Dépensé par catégorie",font=FH3,
                     text_color=C("text")).pack(padx=18,pady=(14,4),anchor="w")
        loading=ctk.CTkLabel(chart_fr,text="Chargement…",font=FS,text_color=C("subtext"))
        loading.pack(pady=16)
        def load_pie(target_frame=chart_fr,target_loading=loading,data=budgets):
            try:
                import matplotlib.pyplot as plt
                from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
                BG=C("card"); TXT=C("text"); GRID=C("border")
                labels=[f"{b['cat_icone']} {b['cat_nom']}" for b in data]
                budg=[b["montant"] for b in data]
                dep =[b["depense"] for b in data]
                import numpy as np
                x=np.arange(len(labels)); w=0.35
                fig,ax=plt.subplots(figsize=(10,3.2),facecolor=BG)
                ax.set_facecolor(BG)
                ax.bar(x-w/2,budg,w,color=C("accent"),label="Budget",edgecolor=BG)
                ax.bar(x+w/2,dep,w,color=C("orange"),label="Dépensé",edgecolor=BG)
                ax.set_xticks(x); ax.set_xticklabels(labels,rotation=20,ha="right",fontsize=8)
                ax.legend(facecolor=BG,edgecolor=GRID,labelcolor=TXT,fontsize=8)
                ax.grid(axis="y",color=GRID,linewidth=0.4,alpha=0.6)
                ax.tick_params(colors=TXT,labelsize=8)
                for s in ax.spines.values(): s.set_edgecolor(GRID)
                fig.tight_layout()
                def show():
                    if not target_frame.winfo_exists(): plt.close(fig); return
                    try: target_loading.destroy()
                    except: pass
                    FigureCanvasTkAgg(fig,master=target_frame).get_tk_widget().pack(
                        padx=10,pady=(0,10),fill="x")
                    plt.close(fig)
                self.after(0,show)
            except Exception: pass
        threading.Thread(target=load_pie,daemon=True).start()

    def _dlg_budget(self, cats_dispo, annee, mois, sf):
        dlg=self._dlg("Nouveau budget",440,360)
        f=self._sf_form(dlg,"Nouveau budget")
        cat_names=[f"{c['icone']} {c['nom']}" for c in cats_dispo]
        cat_var=ctk.StringVar(value=cat_names[0]); self._opt(f,"Catégorie",cat_names,cat_var)
        f_mnt=self._field(f,"Montant budget *","ex: 500000")
        def submit():
            idx=cat_names.index(cat_var.get())
            try: mnt=float(f_mnt.get().strip())
            except: self.toast("⚠️ Montant invalide.",C("orange")); return
            set_budget(cats_dispo[idx]["id"],annee,mois,mnt)
            dlg.destroy(); self.toast("✅ Budget défini."); self._refresh_budgets(sf)
        self._btns(dlg,"✔ Enregistrer",submit)

    def _dlg_budget_edit(self, b, annee, mois, sf):
        dlg=self._dlg("Modifier budget",440,300)
        f=self._sf_form(dlg,f"Budget — {b['cat_nom']}")
        f_mnt=self._field(f,"Montant budget *",default=b["montant"])
        def submit():
            try: mnt=float(f_mnt.get().strip())
            except: self.toast("⚠️ Montant invalide.",C("orange")); return
            set_budget(b["categorie_id"],annee,mois,mnt)
            dlg.destroy(); self.toast("✅ Budget modifié."); self._refresh_budgets(sf)
        self._btns(dlg,"✔ Enregistrer",submit)

    def _del_budget(self, b, annee, mois, sf):
        if messagebox.askyesno("Supprimer",f"Supprimer le budget pour {b['cat_nom']} ?"):
            delete_budget(b["categorie_id"],annee,mois)
            self.toast("🗑️ Budget supprimé.",C("subtext")); self._refresh_budgets(sf)

    # ── CATÉGORIES ────────────────────────────────────────────────────────────
    def _page_categories(self):
        frame=ctk.CTkFrame(self.content,fg_color=C("bg"))
        frame.pack(fill="both",expand=True)
        hdr=self._page_header(frame,"Catégories")
        sf=ctk.CTkScrollableFrame(frame,fg_color=C("bg"))
        sf.pack(fill="both",expand=True,padx=28,pady=12)
        ctk.CTkButton(hdr,text="＋ Ajouter",height=36,fg_color=C("accent"),font=FB,
                      command=lambda:self._dlg_category(sf=sf)).pack(side="right")
        self._refresh_cats(sf)

    def _refresh_cats(self, sf):
        for w in sf.winfo_children(): w.destroy()
        cats=get_categories()
        hdr=ctk.CTkFrame(sf,fg_color=C("card2"),corner_radius=8); hdr.pack(fill="x",pady=(0,4))
        for i,(col,w) in enumerate(zip(["Icône","Nom","Type","Couleur","Actions"],[60,200,100,100,120])):
            ctk.CTkLabel(hdr,text=col,font=("Segoe UI",11,"bold"),
                         text_color=C("subtext"),width=w).grid(row=0,column=i,padx=6,pady=7,sticky="w")
        for idx,cat in enumerate(cats):
            row=ctk.CTkFrame(sf,fg_color=self._row_bg(idx),corner_radius=8); row.pack(fill="x",pady=2)
            ctk.CTkLabel(row,text=cat["icone"],font=("Segoe UI",18),width=60).grid(row=0,column=0,padx=6,pady=8)
            ctk.CTkLabel(row,text=cat["nom"],font=FB,text_color=C("text"),
                         width=200,anchor="w").grid(row=0,column=1,padx=6,pady=8,sticky="w")
            ctk.CTkLabel(row,text="Entrée" if cat.get("type")=="entree" else "Sortie",
                         font=FB,text_color=C("subtext"),width=100,anchor="w").grid(row=0,column=2,padx=6,pady=8,sticky="w")
            ctk.CTkFrame(row,width=28,height=18,fg_color=safe_color(cat["couleur"]),corner_radius=4
                         ).grid(row=0,column=3,padx=24,pady=8,sticky="w")
            af=ctk.CTkFrame(row,fg_color="transparent"); af.grid(row=0,column=4,padx=6,pady=6)
            ctk.CTkButton(af,text="✏️",width=30,height=28,font=FS,
                          fg_color=C("card2"),hover_color=C("hover"),
                          command=lambda c=cat:self._dlg_category(c,sf)).pack(side="left",padx=2)
            ctk.CTkButton(af,text="✕",width=28,height=28,font=FS,
                          fg_color=C("red"),hover_color="#C44",
                          command=lambda cid=cat["id"]:self._del_cat(cid,sf)).pack(side="left",padx=2)

    # ── SAUVEGARDES ───────────────────────────────────────────────────────────
    def _page_sauvegardes(self):
        frame=ctk.CTkFrame(self.content,fg_color=C("bg")); frame.pack(fill="both",expand=True)
        hdr=self._page_header(frame,"Sauvegardes")
        ctk.CTkButton(hdr,text="💾 Sauvegarder maintenant",height=36,
                      fg_color=C("accent"),font=FB,
                      command=lambda:self._do_backup(sf)).pack(side="right")
        info=ctk.CTkFrame(frame,fg_color=C("panel"),corner_radius=10); info.pack(fill="x",padx=28,pady=(14,0))
        ctk.CTkLabel(info,text="ℹ️  Sauvegarde auto au démarrage. Les 10 dernières sont conservées. Dossier : sauvegardes/",
                     font=FS,text_color=C("subtext")).pack(padx=14,pady=10)
        sf=ctk.CTkScrollableFrame(frame,fg_color=C("bg")); sf.pack(fill="both",expand=True,padx=28,pady=12)
        self._refresh_backups(sf)

    def _refresh_backups(self, sf):
        for w in sf.winfo_children(): w.destroy()
        backups=get_backups()
        if not backups:
            ctk.CTkLabel(sf,text="Aucune sauvegarde.",font=FB,text_color=C("subtext")).pack(pady=20); return
        hdr=ctk.CTkFrame(sf,fg_color=C("card2"),corner_radius=8); hdr.pack(fill="x",pady=(0,4))
        for i,(col,w) in enumerate(zip(["Fichier","Date","Action"],[380,200,120])):
            ctk.CTkLabel(hdr,text=col,font=("Segoe UI",11,"bold"),
                         text_color=C("subtext"),width=w).grid(row=0,column=i,padx=8,pady=7,sticky="w")
        for idx,fname in enumerate(backups):
            ts=fname.replace("caisse_gestion_","").replace(".db","")
            try: dt=datetime.strptime(ts,"%Y%m%d_%H%M%S").strftime("%d/%m/%Y %H:%M:%S")
            except: dt=ts
            row=ctk.CTkFrame(sf,fg_color=self._row_bg(idx),corner_radius=8); row.pack(fill="x",pady=2)
            ctk.CTkLabel(row,text=fname,font=FB,text_color=C("text"),
                         width=380,anchor="w").grid(row=0,column=0,padx=8,pady=8,sticky="w")
            ctk.CTkLabel(row,text=dt,font=FB,text_color=C("subtext"),
                         width=200,anchor="w").grid(row=0,column=1,padx=8,pady=8,sticky="w")
            ctk.CTkButton(row,text="Restaurer",width=88,height=28,font=FS,
                          fg_color=C("orange"),hover_color="#D4891A",
                          command=lambda f=fname:self._do_restore(f,sf)
                          ).grid(row=0,column=2,padx=8,pady=6)

    def _do_backup(self, sf):
        try: backup_db(); self._refresh_backups(sf); self.toast("✅ Sauvegarde créée.")
        except Exception as e: self.toast(f"❌ {e}",C("red"))
    def _do_restore(self, fname, sf):
        if messagebox.askyesno("Restaurer",f"Restaurer :\n{fname}\n\nLes données actuelles seront remplacées."):
            ok,msg=restore_backup(fname)
            self.toast(("✅ " if ok else "❌ ")+msg,C("green") if ok else C("red"))
            if ok: self._refresh_backups(sf)

    # ── JOURNAL ───────────────────────────────────────────────────────────────
    def _page_journal(self):
        frame=ctk.CTkFrame(self.content,fg_color=C("bg")); frame.pack(fill="both",expand=True)
        hdr=self._page_header(frame,"📜 Journal d'activité")
        bf_j=ctk.CTkFrame(hdr,fg_color="transparent"); bf_j.pack(side="right")
        ctk.CTkButton(bf_j,text="📄 Export PDF",height=32,font=FS,
                      fg_color=C("card2"),hover_color=C("hover"),
                      command=lambda:self._export_journal("pdf")).pack(side="left",padx=2)
        ctk.CTkButton(bf_j,text="📤 Export Excel",height=32,font=FS,
                      fg_color=C("card2"),hover_color=C("hover"),
                      command=lambda:self._export_journal("excel")).pack(side="left",padx=2)

        # Filtres
        flt=ctk.CTkFrame(frame,fg_color=C("panel"),corner_radius=10)
        flt.pack(fill="x",padx=28,pady=(14,0))
        ctk.CTkLabel(flt,text="🔍",font=FB,text_color=C("subtext")).pack(side="left",padx=(14,2),pady=10)
        self._jrn_sv=tk.StringVar()
        ctk.CTkEntry(flt,height=32,font=FB,fg_color=C("card2"),border_color=C("border"),
                     textvariable=self._jrn_sv,
                     placeholder_text="Chercher action, détail, utilisateur…"
                     ).pack(side="left",padx=4,fill="x",expand=True)
        ctk.CTkLabel(flt,text="Du:",font=FS,text_color=C("subtext")).pack(side="left",padx=(8,2))
        self._jrn_dd=ctk.CTkEntry(flt,width=104,height=32,font=FB,fg_color=C("card2"),
                                   border_color=C("border"),placeholder_text="AAAA-MM-JJ")
        self._jrn_dd.pack(side="left",padx=2)
        ctk.CTkLabel(flt,text="Au:",font=FS,text_color=C("subtext")).pack(side="left",padx=(6,2))
        self._jrn_df=ctk.CTkEntry(flt,width=104,height=32,font=FB,fg_color=C("card2"),
                                   border_color=C("border"),placeholder_text="AAAA-MM-JJ")
        self._jrn_df.pack(side="left",padx=2)
        # Filtre utilisateur
        users=get_all_users(); user_names=["Tous"]+[u["nom"] for u in users]
        self._jrn_usr=ctk.StringVar(value="Tous")
        ctk.CTkOptionMenu(flt,values=user_names,variable=self._jrn_usr,
                          fg_color=C("card2"),button_color=C("accent"),
                          height=32,font=FB,width=120).pack(side="left",padx=4)
        ctk.CTkButton(flt,text="Chercher",height=32,width=88,fg_color=C("accent"),font=FB,
                      command=lambda:self._refresh_journal(sf)).pack(side="left",padx=3)
        ctk.CTkButton(flt,text="✕",height=32,width=36,fg_color=C("card2"),
                      hover_color=C("hover"),font=FB,
                      command=lambda:[self._jrn_sv.set(""),
                                      self._jrn_dd.delete(0,"end"),
                                      self._jrn_df.delete(0,"end"),
                                      self._jrn_usr.set("Tous"),
                                      self._refresh_journal(sf)]
                      ).pack(side="left",padx=(2,12))

        sf=ctk.CTkScrollableFrame(frame,fg_color=C("bg")); sf.pack(fill="both",expand=True,padx=28,pady=12)
        self._jrn_sf=sf; self._refresh_journal(sf)

    def _get_journal_logs(self):
        search =self._jrn_sv.get().strip()  if hasattr(self,"_jrn_sv")  else ""
        dd     =self._jrn_dd.get().strip()  if hasattr(self,"_jrn_dd")  else ""
        df     =self._jrn_df.get().strip()  if hasattr(self,"_jrn_df")  else ""
        usr_nom=self._jrn_usr.get()         if hasattr(self,"_jrn_usr") else "Tous"
        users  =get_all_users()
        uid    =next((u["id"] for u in users if u["nom"]==usr_nom),None) if usr_nom!="Tous" else None
        return get_historique_filtre(search=search,user_id=uid,date_debut=dd,date_fin=df,limit=500)

    def _export_journal(self, fmt):
        logs=self._get_journal_logs()
        if not logs: self.toast("⚠️ Aucune entrée à exporter.",C("orange")); return
        if fmt=="pdf":
            fp=filedialog.asksaveasfilename(defaultextension=".pdf",
                filetypes=[("PDF","*.pdf")],initialfile=f"journal_{date.today()}.pdf")
            if not fp: return
            ok,msg=export_journal_pdf(fp,logs)
        else:
            fp=filedialog.asksaveasfilename(defaultextension=".xlsx",
                filetypes=[("Excel","*.xlsx")],initialfile=f"journal_{date.today()}.xlsx")
            if not fp: return
            ok,msg=export_journal_excel(fp,logs)
        self.toast(("✅ " if ok else "❌ ")+msg,C("green") if ok else C("red"))

    def _refresh_journal(self, sf):
        for w in sf.winfo_children(): w.destroy()
        logs=self._get_journal_logs()
        ctk.CTkLabel(sf,text=f"{len(logs)} entrée(s)",font=FS,
                     text_color=C("subtext")).pack(anchor="w",pady=(0,6))
        if not logs:
            ctk.CTkLabel(sf,text="Aucune entrée.",font=FB,text_color=C("subtext")).pack(pady=20); return
        MAXJ=200
        if len(logs)>MAXJ:
            ctk.CTkLabel(sf,text=f"Affichage des {MAXJ} plus récentes — affinez avec les filtres "
                                 f"(les exports contiennent tout).",font=FS,
                         text_color=C("orange")).pack(anchor="w",pady=(0,6))
        tbl=CanvasTable(sf,[("","Date/Heure",155,False),("","Action",155,False),
                            ("","Détail",320,False),("","Utilisateur",140,False)],
                        row_h=36,bg=C("bg"))
        tbl.pack(fill="x")
        FSB=("Segoe UI",11,"bold")
        for idx,log in enumerate(logs[:MAXJ]):
            detail=log.get("detail","") or ""
            tbl.add_row(self._row_bg(idx),[
                (log["created_at"][:16],C("subtext"),FB,None),
                (log["action"],C("accent"),FSB,None),
                (trunc(detail,"detail"),C("text"),FB,detail if len(detail)>TRUNC["detail"] else None),
                (log.get("user_nom","") or "",C("subtext"),FB,None)])
        tbl.finish()

    # ── PARAMÈTRES ────────────────────────────────────────────────────────────
    def _page_parametres(self):
        frame=ctk.CTkScrollableFrame(self.content,fg_color=C("bg")); frame.pack(fill="both",expand=True)
        self._page_header(frame,"⚙️ Paramètres")

        def section(title):
            fr=ctk.CTkFrame(frame,fg_color=C("panel"),corner_radius=14)
            fr.pack(padx=28,pady=(16,0),fill="x")
            ctk.CTkLabel(fr,text=title,font=FH3,text_color=C("accent")).pack(padx=24,pady=(14,4),anchor="w")
            return fr

        # Société
        s1=section("🏢 Société"); fields1={}
        for cle,label,val in [
            ("societe","Nom de la société",get_parametre("societe","")),
            ("adresse","Adresse",get_parametre("adresse","")),
            ("telephone","Téléphone",get_parametre("telephone","")),
        ]:
            ctk.CTkLabel(s1,text=label,font=FS,text_color=C("subtext"),anchor="w").pack(fill="x",padx=24,pady=(8,2))
            e=ctk.CTkEntry(s1,height=40,font=FB,fg_color=C("card2"),border_color=C("border"))
            e.insert(0,val); e.pack(fill="x",padx=24); fields1[cle]=e

        # Logo
        ctk.CTkLabel(s1,text="Logo (chemin image PNG/JPG)",font=FS,text_color=C("subtext"),
                     anchor="w").pack(fill="x",padx=24,pady=(8,2))
        logo_fr=ctk.CTkFrame(s1,fg_color="transparent"); logo_fr.pack(fill="x",padx=24)
        logo_e=ctk.CTkEntry(logo_fr,height=40,font=FB,fg_color=C("card2"),border_color=C("border"))
        logo_e.insert(0,get_parametre("logo_path","")); logo_e.pack(side="left",fill="x",expand=True)
        ctk.CTkButton(logo_fr,text="Parcourir",height=40,width=100,font=FB,
                      fg_color=C("card2"),hover_color=C("hover"),
                      command=lambda:logo_e.delete(0,"end") or logo_e.insert(0,
                          filedialog.askopenfilename(filetypes=[("Images","*.png *.jpg *.jpeg")]) or logo_e.get())
                      ).pack(side="left",padx=(6,0))
        fields1["logo_path"]=logo_e

        # Caisse
        s2=section("💰 Caisse & Devise"); fields2={}
        for cle,label,val in [
            ("solde_ouverture","Solde d'ouverture",get_parametre("solde_ouverture","0")),
            ("devise","Devise principale (ex: FCFA, XOF, €)",get_parametre("devise","FCFA")),
            ("seuil_alerte","Seuil alerte chèque (%)",get_parametre("seuil_alerte","10")),
        ]:
            ctk.CTkLabel(s2,text=label,font=FS,text_color=C("subtext"),anchor="w").pack(fill="x",padx=24,pady=(8,2))
            e=ctk.CTkEntry(s2,height=40,font=FB,fg_color=C("card2"),border_color=C("border"))
            e.insert(0,val); e.pack(fill="x",padx=24); fields2[cle]=e

        # Sauvegarde
        s3=section("🗄️ Sauvegarde")
        auto_var=ctk.StringVar(value="Oui" if get_parametre("auto_backup","1")=="1" else "Non")
        ctk.CTkLabel(s3,text="Sauvegarde automatique au démarrage",font=FS,
                     text_color=C("subtext"),anchor="w").pack(fill="x",padx=24,pady=(8,2))
        ctk.CTkOptionMenu(s3,values=["Oui","Non"],variable=auto_var,
                          fg_color=C("card2"),button_color=C("accent"),
                          height=40,font=FB).pack(fill="x",padx=24,pady=(0,14))

        # Export automatique
        s4=section("📅 Export automatique (1er du mois)")
        exp_var=ctk.StringVar(value="Oui" if get_parametre("export_auto","0")=="1" else "Non")
        ctk.CTkLabel(s4,text="Activer l'export Excel automatique le 1er de chaque mois",
                     font=FS,text_color=C("subtext"),anchor="w").pack(fill="x",padx=24,pady=(8,2))
        ctk.CTkOptionMenu(s4,values=["Non","Oui"],variable=exp_var,
                          fg_color=C("card2"),button_color=C("accent"),
                          height=40,font=FB).pack(fill="x",padx=24,pady=(0,8))
        ctk.CTkLabel(s4,text="Dossier de destination",font=FS,
                     text_color=C("subtext"),anchor="w").pack(fill="x",padx=24,pady=(0,2))
        exp_dir_fr=ctk.CTkFrame(s4,fg_color="transparent"); exp_dir_fr.pack(fill="x",padx=24,pady=(0,14))
        exp_dir_e=ctk.CTkEntry(exp_dir_fr,height=40,font=FB,fg_color=C("card2"),border_color=C("border"))
        exp_dir_e.insert(0,get_parametre("export_auto_dossier",""))
        exp_dir_e.pack(side="left",fill="x",expand=True)
        ctk.CTkButton(exp_dir_fr,text="Parcourir",height=40,width=100,font=FB,
                      fg_color=C("card2"),hover_color=C("hover"),
                      command=lambda:exp_dir_e.delete(0,"end") or exp_dir_e.insert(0,
                          filedialog.askdirectory() or exp_dir_e.get())
                      ).pack(side="left",padx=(6,0))

        def save():
            for cle,e in {**fields1,**fields2}.items():
                val=e.get().strip()
                if cle in ("solde_ouverture","seuil_alerte"):
                    try: float(val)
                    except: self.toast(f"⚠️ {cle} invalide.",C("orange")); return
                set_parametre(cle,val)
            set_parametre("auto_backup","1" if auto_var.get()=="Oui" else "0")
            set_parametre("export_auto","1" if exp_var.get()=="Oui" else "0")
            set_parametre("export_auto_dossier",exp_dir_e.get().strip())
            self.toast("✅ Paramètres sauvegardés.")

        ctk.CTkButton(frame,text="✔ Enregistrer tous les paramètres",height=44,font=FH3,
                      fg_color=C("accent"),command=save).pack(fill="x",padx=28,pady=(20,28))

    # ── UTILISATEURS ──────────────────────────────────────────────────────────
    def _page_users(self):
        if current_user["role"]!="admin":
            fr=ctk.CTkFrame(self.content,fg_color=C("bg")); fr.pack(fill="both",expand=True)
            ctk.CTkLabel(fr,text="🔒 Accès réservé à l'administrateur.",
                         font=FH2,text_color=C("red")).pack(expand=True); return
        frame=ctk.CTkFrame(self.content,fg_color=C("bg")); frame.pack(fill="both",expand=True)
        hdr=self._page_header(frame,"Utilisateurs")
        sf=ctk.CTkScrollableFrame(frame,fg_color=C("bg")); sf.pack(fill="both",expand=True,padx=28,pady=12)
        bf_u=ctk.CTkFrame(hdr,fg_color="transparent"); bf_u.pack(side="right")
        ctk.CTkButton(bf_u,text="＋ Ajouter",height=36,fg_color=C("accent"),font=FB,
                      command=lambda:self._dlg_add_user(sf)).pack(side="left",padx=(0,4))
        ctk.CTkButton(bf_u,text="🔑 Réinit. MDP",height=36,fg_color=C("orange"),font=FB,
                      command=self._dlg_reset_pwd_admin).pack(side="left")
        self._refresh_users(sf)

    def _refresh_users(self, sf):
        for w in sf.winfo_children(): w.destroy()
        users=get_all_users()
        hdr=ctk.CTkFrame(sf,fg_color=C("card2"),corner_radius=8); hdr.pack(fill="x",pady=(0,4))
        for i,(col,w) in enumerate(zip(["Nom","Login","Rôle","Créé le","Actions"],[180,140,130,150,140])):
            ctk.CTkLabel(hdr,text=col,font=("Segoe UI",11,"bold"),
                         text_color=C("subtext"),width=w).grid(row=0,column=i,padx=6,pady=7,sticky="w")
        for idx,u in enumerate(users):
            row=ctk.CTkFrame(sf,fg_color=self._row_bg(idx),corner_radius=8); row.pack(fill="x",pady=2)
            for i,(val,w) in enumerate(zip([u["nom"],u["login"],
                "👑 Admin" if u["role"]=="admin" else "👤 Utilisateur",
                u["created_at"][:10]],[180,140,130,150])):
                ctk.CTkLabel(row,text=val,font=FB,text_color=C("text"),
                             width=w,anchor="w").grid(row=0,column=i,padx=6,pady=8,sticky="w")
            af=ctk.CTkFrame(row,fg_color="transparent"); af.grid(row=0,column=4,padx=6,pady=6)
            ctk.CTkButton(af,text="🔑",width=32,height=28,font=FS,
                          fg_color=C("card2"),hover_color=C("hover"),
                          command=lambda uid=u["id"]:self._dlg_pwd(uid)).pack(side="left",padx=2)
            if u["id"]!=current_user["id"]:
                ctk.CTkButton(af,text="✕",width=28,height=28,font=FS,
                              fg_color=C("red"),hover_color="#C44",
                              command=lambda uid=u["id"]:self._del_user(uid,sf)).pack(side="left",padx=2)

    # ── DIALOGUES ─────────────────────────────────────────────────────────────
    # Chèque
    def _dlg_cheque(self, cheque=None):
        edit=cheque is not None
        dlg=self._dlg("Modifier chèque" if edit else "Nouveau chèque",520,620)
        sf=self._sf_form(dlg,"Modifier chèque" if edit else "Nouveau chèque")
        auto_num=get_next_numero_cheque() if not edit else ""
        f_num =self._field(sf,"Numéro *","ex: CHQ-0001",default=cheque["numero"] if edit else auto_num)
        f_mnt =self._field(sf,"Montant *","ex: 500000",default=cheque["montant_initial"] if edit else "")
        f_date=self._field(sf,"Date émission *","AAAA-MM-JJ",
                           default=cheque["date_emission"] if edit else date.today().isoformat())
        f_ech =self._field(sf,"Date échéance","AAAA-MM-JJ (optionnel)",
                           default=cheque.get("date_echeance","") if edit else "")
        f_ben =self._field(sf,"Bénéficiaire *","Nom/entreprise",default=cheque["beneficiaire"] if edit else "")
        f_bnq =self._field(sf,"Banque","ex: BICICI",default=cheque.get("banque","") if edit else "")
        f_nts =self._field_text(sf,"Notes",default=cheque.get("notes","") if edit else "",height=70)

        # Solde restant temps réel
        devise=get_devise()
        if edit:
            lbl_rest=ctk.CTkLabel(sf,text=f"💰 Restant actuel : {cheque['montant_restant']:,.0f} {devise}",
                                   font=FH3,text_color=C("green"))
            lbl_rest.pack(padx=20,pady=(4,0),anchor="w")
            def on_mnt_change(*_):
                try:
                    diff=float(f_mnt.get())-cheque["montant_initial"]
                    nr=max(0,cheque["montant_restant"]+diff)
                    lbl_rest.configure(text=f"💰 Restant après modif : {nr:,.0f} {devise}",
                                       text_color=C("green") if nr>0 else C("red"))
                except: pass
            f_mnt.bind("<KeyRelease>",on_mnt_change)

        def submit():
            num=f_num.get().strip(); mnt_s=f_mnt.get().strip()
            dt=f_date.get().strip(); ben=f_ben.get().strip()
            if not all([num,mnt_s,dt,ben]): self.toast("⚠️ Champs manquants.",C("orange")); return
            try: mnt=float(mnt_s)
            except: self.toast("⚠️ Montant invalide.",C("orange")); return
            nts=f_nts.get("1.0","end").strip()
            if edit:
                ok,msg=update_cheque(cheque["id"],num,mnt,dt,ben,
                                     f_bnq.get().strip(),nts,f_ech.get().strip(),current_user["id"])
            else:
                ok,msg=add_cheque(num,mnt,dt,ben,
                                  f_bnq.get().strip(),nts,f_ech.get().strip(),current_user["id"])
            if ok: dlg.destroy(); self.toast("✅ "+msg); self._navigate("cheques")
            else: self.toast("❌ "+msg,C("red"))
        self._btns(dlg,"✔ Enregistrer",submit)

    # Dépense multi-chèques (remplace _dlg_depense)
    def _dlg_depense_multi(self, cheque_initial=None):
        devise=get_devise()
        dlg=self._dlg("Nouvelle dépense",580,680)
        sf=self._sf_form(dlg,"Dépense sur chèque(s)")

        f_mnt =self._field(sf,"Montant total *","ex: 150000")
        f_dsg =self._field(sf,"Désignation *","ex: Règlement fournisseur")
        f_date=self._field(sf,"Date *","AAAA-MM-JJ",default=date.today().isoformat())
        f_nts =self._field_text(sf,"Notes",height=60)
        cats  =get_categories(type_="sortie")
        cat_names=["— Aucune —"]+[f"{c['icone']} {c['nom']}" for c in cats]
        cat_var=ctk.StringVar(value=cat_names[0]); self._opt(sf,"Catégorie",cat_names,cat_var)

        # Zone répartition chèques
        ctk.CTkLabel(sf,text="Répartition sur chèques",font=FH3,text_color=C("accent")).pack(padx=20,pady=(14,4),anchor="w")
        cheques_dispo=[c for c in get_all_cheques() if c["statut"] not in ("cloture",)]
        repartition_fr=ctk.CTkScrollableFrame(sf,fg_color=C("card2"),corner_radius=10,height=160)
        repartition_fr.pack(fill="x",padx=20)
        lignes=[]  # [(cheque, entry_widget)]

        def ajouter_ligne(ch=None, montant=""):
            rf=ctk.CTkFrame(repartition_fr,fg_color="transparent"); rf.pack(fill="x",pady=4,padx=8)
            ch_names=[f"#{c['numero']} — {c['beneficiaire']} ({c['montant_restant']:,.0f} {devise})"
                      for c in cheques_dispo]
            ch_var_l=ctk.StringVar(value=ch_names[0] if not ch else
                f"#{ch['numero']} — {ch['beneficiaire']} ({ch['montant_restant']:,.0f} {devise})")
            ctk.CTkOptionMenu(rf,values=ch_names,variable=ch_var_l,
                              fg_color=C("card"),button_color=C("accent"),
                              height=34,font=FB,width=310).pack(side="left",padx=(0,6))
            e_mnt=ctk.CTkEntry(rf,width=130,height=34,font=FB,fg_color=C("card"),
                                border_color=C("border"),placeholder_text="Montant…")
            if montant: e_mnt.insert(0,str(montant))
            e_mnt.pack(side="left",padx=(0,6))
            e_mnt.bind("<KeyRelease>",lambda _:update_reste())
            def rm(row=rf,entry=e_mnt,var=ch_var_l):
                for i,(v,e) in enumerate(lignes):
                    if e is entry: lignes.pop(i); break
                row.destroy(); update_reste()
            ctk.CTkButton(rf,text="✕",width=28,height=34,font=FS,
                          fg_color=C("red"),hover_color="#C44",
                          command=rm).pack(side="left")
            lignes.append((ch_var_l,e_mnt))
            update_reste()

        def update_reste(*_):
            try:
                total=float(f_mnt.get().strip() or 0)
                saisi=sum(float(e.get() or 0) for _,e in lignes)
                reste=total-saisi
                lbl_reste.configure(text=f"Reste à répartir : {reste:,.0f} {devise}",
                                     text_color=C("red") if reste<-0.01 else (C("green") if abs(reste)<0.01 else C("orange")))
            except: pass
        f_mnt.bind("<KeyRelease>",update_reste)

        ctk.CTkButton(sf,text="＋ Ajouter un chèque",height=32,font=FB,
                      fg_color=C("card2"),hover_color=C("hover"),
                      command=lambda:ajouter_ligne()).pack(padx=20,pady=(6,0),anchor="w")
        lbl_reste=ctk.CTkLabel(sf,text="Reste à répartir : — FCFA",font=FH3,text_color=C("subtext"))
        lbl_reste.pack(padx=20,pady=(6,0),anchor="w")

        # Ligne initiale
        ajouter_ligne(cheque_initial)

        def submit():
            mnt_s=f_mnt.get().strip(); dsg=f_dsg.get().strip(); dt=f_date.get().strip()
            if not all([mnt_s,dsg,dt]): self.toast("⚠️ Champs manquants.",C("orange")); return
            try: total=float(mnt_s)
            except: self.toast("⚠️ Montant invalide.",C("orange")); return
            if not lignes: self.toast("⚠️ Ajoutez au moins un chèque.",C("orange")); return
            repartition=[]
            total_saisi=0
            for ch_var_l,e_mnt in lignes:
                try: mnt_l=float(e_mnt.get().strip() or 0)
                except: self.toast("⚠️ Montant ligne invalide.",C("orange")); return
                if mnt_l<=0: continue
                # Retrouver le chèque sélectionné
                sel=ch_var_l.get()
                ch_found=None
                for c in cheques_dispo:
                    if f"#{c['numero']}" in sel:
                        ch_found=c; break
                if not ch_found: self.toast("⚠️ Chèque introuvable.",C("orange")); return
                repartition.append((ch_found["id"],mnt_l))
                total_saisi+=mnt_l
            if abs(total_saisi-total)>0.01:
                self.toast(f"⚠️ Total réparti ({total_saisi:,.0f}) ≠ montant ({total:,.0f}).",C("orange")); return
            sel=cat_var.get()
            cat_id=cats[cat_names.index(sel)-1]["id"] if sel!="— Aucune —" else None
            nts=f_nts.get("1.0","end").strip()
            # Confirmation visuelle avant validation
            if not self._dlg_confirm_multi(repartition,dsg,cat_id,dt,nts,"",cheques_dispo):
                return
            ok,msg=depense_multi_cheques(repartition,dsg,cat_id,dt,nts,"",current_user["id"])
            if ok: dlg.destroy(); self.toast("✅ "+msg); self._navigate("cheques")
            else: self.toast("❌ "+msg,C("red"))
        self._btns(dlg,"✔ Enregistrer la dépense",submit,C("orange"))

    # Dépense directe (depuis transactions)
    def _dlg_depense_directe(self):
        dlg=self._dlg("Nouvelle dépense",500,600)
        sf=self._sf_form(dlg,"Nouvelle dépense sur chèque(s)")
        f_mnt =self._field(sf,"Montant *","ex: 25000")
        f_dsg =self._field(sf,"Désignation *","ex: Achat fournitures")
        f_date=self._field(sf,"Date *","AAAA-MM-JJ",default=date.today().isoformat())
        f_ref =self._field(sf,"Référence","Optionnel…")
        f_nts =self._field_text(sf,"Notes",height=60)
        cats  =get_categories(type_="sortie")
        cat_names=["— Aucune —"]+[f"{c['icone']} {c['nom']}" for c in cats]
        cat_var=ctk.StringVar(value=cat_names[0]); self._opt(sf,"Catégorie",cat_names,cat_var)
        devise=get_devise()
        cheques=[c for c in get_all_cheques() if c["statut"] not in ("cloture",)]
        ch_names=["— Aucun (sortie libre) —"]+[
            f"#{c['numero']} — {c['beneficiaire']} ({c['montant_restant']:,.0f} {devise})"
            for c in cheques]
        ch_var=ctk.StringVar(value=ch_names[0]); self._opt(sf,"Lier à un chèque",ch_names,ch_var)

        # Restant en temps réel
        lbl_rest=ctk.CTkLabel(sf,text="",font=FS,text_color=C("green"))
        lbl_rest.pack(padx=20,pady=(4,0),anchor="w")
        def on_ch_change(*_):
            sel=ch_var.get()
            if sel==ch_names[0]: lbl_rest.configure(text=""); return
            idx=ch_names.index(sel)-1
            ch=cheques[idx]
            lbl_rest.configure(text=f"Disponible : {ch['montant_restant']:,.0f} {devise}")
        ch_var.trace_add("write",on_ch_change)

        def submit():
            mnt_s=f_mnt.get().strip(); dsg=f_dsg.get().strip(); dt=f_date.get().strip()
            if not all([mnt_s,dsg,dt]): self.toast("⚠️ Champs manquants.",C("orange")); return
            try: mnt=float(mnt_s)
            except: self.toast("⚠️ Montant invalide.",C("orange")); return
            sel=cat_var.get()
            cat_id=cats[cat_names.index(sel)-1]["id"] if sel!="— Aucune —" else None
            nts=f_nts.get("1.0","end").strip()
            ch_sel=ch_var.get()
            if ch_sel!=ch_names[0]:
                idx=ch_names.index(ch_sel)-1
                ok,msg=depense_sur_cheque(cheques[idx]["id"],mnt,dsg,cat_id,dt,nts,"",current_user["id"])
                if not ok: self.toast("❌ "+msg,C("red")); return
            else:
                add_transaction("sortie",mnt,dsg,cat_id,dt,f_ref.get().strip(),nts,"",current_user["id"])
            dlg.destroy(); self.toast("✅ Dépense enregistrée."); self._navigate("transactions")
        self._btns(dlg,"✔ Enregistrer la dépense",submit,C("orange"))

    # Transaction (entrée/sortie libre)
    def _dlg_transaction(self, type_, transaction=None):
        edit=transaction is not None
        label="Modifier" if edit else ("Nouvelle entrée" if type_=="entree" else "Nouvelle sortie")
        dlg=self._dlg(label,520,600)
        sf=self._sf_form(dlg,label)
        f_mnt =self._field(sf,"Montant *","ex: 100000",default=transaction["montant"] if edit else "")
        f_dsg =self._field(sf,"Désignation *","",default=transaction["designation"] if edit else "")
        f_date=self._field(sf,"Date *","AAAA-MM-JJ",
                           default=transaction["date_transaction"] if edit else date.today().isoformat())
        f_ref =self._field(sf,"Référence","Optionnel…",default=transaction.get("reference","") if edit else "")
        f_nts =self._field_text(sf,"Notes",default=transaction.get("notes","") if edit else "",height=70)
        f_pj  =self._field_pj(sf,"Pièce jointe",default=transaction.get("piece_jointe","") if edit else "")
        cats  =get_categories(type_=type_)
        cat_names=["— Aucune —"]+[f"{c['icone']} {c['nom']}" for c in cats]
        def_cat="— Aucune —"
        if edit and transaction.get("cat_nom"):
            for cn in cat_names:
                if transaction["cat_nom"] in cn: def_cat=cn; break
        cat_var=ctk.StringVar(value=def_cat); self._opt(sf,"Catégorie",cat_names,cat_var)

        # Avertissement si transaction d'entrée initiale d'un chèque
        if edit and transaction.get("cheque_id") and transaction.get("type")=="entree":
            ctk.CTkLabel(sf,text="⚠️ Transaction liée à un chèque. La modification ajustera le montant du chèque.",
                         font=FS,text_color=C("orange"),wraplength=420).pack(padx=20,pady=(8,0),anchor="w")

        def submit():
            mnt_s=f_mnt.get().strip(); dsg=f_dsg.get().strip(); dt=f_date.get().strip()
            if not all([mnt_s,dsg,dt]): self.toast("⚠️ Champs manquants.",C("orange")); return
            try: mnt=float(mnt_s)
            except: self.toast("⚠️ Montant invalide.",C("orange")); return
            sel=cat_var.get()
            cat_id=cats[cat_names.index(sel)-1]["id"] if sel!="— Aucune —" else None
            nts=f_nts.get("1.0","end").strip()
            pj=f_pj.get().strip()
            if edit:
                ok,msg=update_transaction(transaction["id"],mnt,dsg,cat_id,dt,
                                          f_ref.get().strip(),nts,pj)
                if not ok: self.toast("❌ "+msg,C("red")); return
            else:
                add_transaction(type_,mnt,dsg,cat_id,dt,f_ref.get().strip(),nts,pj,current_user["id"])
            dlg.destroy(); self.toast("✅ Enregistré."); self._navigate("transactions")
        color=C("green") if type_=="entree" else C("red")
        self._btns(dlg,"✔ Enregistrer",submit,color)

    # Historique chèque
    def _dlg_hist_cheque(self, cheque):
        devise=get_devise()
        dlg=self._dlg(f"Historique — #{cheque['numero']}",740,540)
        ctk.CTkLabel(dlg,text=f"Chèque #{cheque['numero']} — {cheque['beneficiaire']}",
                     font=FH2,text_color=C("text")).pack(pady=(14,2),padx=20,anchor="w")
        ctk.CTkLabel(dlg,
            text=f"Initial : {cheque['montant_initial']:,.0f} {devise}  |  "
                 f"Restant : {cheque['montant_restant']:,.0f} {devise}  |  "
                 f"Utilisé : {cheque['montant_initial']-cheque['montant_restant']:,.0f} {devise}",
            font=FB,text_color=C("subtext")).pack(padx=20,anchor="w")
        if cheque.get("date_echeance"):
            ctk.CTkLabel(dlg,text=f"Échéance : {cheque['date_echeance']}",
                         font=FB,text_color=C("orange")).pack(padx=20,anchor="w")
        ctk.CTkFrame(dlg,height=1,fg_color=C("border")).pack(fill="x",padx=20,pady=8)
        sf=ctk.CTkScrollableFrame(dlg,fg_color=C("panel")); sf.pack(fill="both",expand=True,padx=10,pady=(0,10))
        trs=get_cheque_transactions(cheque["id"])
        hdr=ctk.CTkFrame(sf,fg_color=C("card2"),corner_radius=8); hdr.pack(fill="x",pady=(0,4))
        for i,(col,w) in enumerate(zip(["Date","Type","Désignation","Catégorie","Montant"],[105,80,260,150,120])):
            ctk.CTkLabel(hdr,text=col,font=("Segoe UI",11,"bold"),
                         text_color=C("subtext"),width=w).grid(row=0,column=i,padx=6,pady=7,sticky="w")
        if not trs:
            ctk.CTkLabel(sf,text="Aucune transaction.",font=FB,text_color=C("subtext")).pack(pady=16); return
        total_dep=0; solde=0
        for idx,t in enumerate(trs):
            is_e=t["type"]=="entree"; color=C("green") if is_e else C("red")
            if is_e: solde+=t["montant"]
            else: total_dep+=t["montant"]; solde-=t["montant"]
            row=ctk.CTkFrame(sf,fg_color=self._row_bg(idx),corner_radius=8); row.pack(fill="x",pady=2)
            ctk.CTkLabel(row,text=t["date_transaction"],font=FB,text_color=C("subtext"),
                         width=105,anchor="w").grid(row=0,column=0,padx=6,pady=8,sticky="w")
            ctk.CTkLabel(row,text="↑ Entrée" if is_e else "↓ Dépense",font=FB,
                         text_color=color,width=80,anchor="w").grid(row=0,column=1,padx=6,pady=8,sticky="w")
            dl=ctk.CTkLabel(row,text=trunc(t["designation"],"designation"),font=FB,
                            text_color=C("text"),width=260,anchor="w")
            dl.grid(row=0,column=2,padx=6,pady=8,sticky="w"); tooltip(dl,t["designation"])
            cat=f"{t.get('cat_icone','') or ''} {t.get('cat_nom','') or '—'}"
            ctk.CTkLabel(row,text=cat,font=FB,text_color=C("subtext"),
                         width=150,anchor="w").grid(row=0,column=3,padx=6,pady=8,sticky="w")
            ctk.CTkLabel(row,text=f"{t['montant']:,.0f} {devise}",
                         font=("Segoe UI",12,"bold"),text_color=color,
                         width=120,anchor="w").grid(row=0,column=4,padx=6,pady=8,sticky="w")
        sf2=ctk.CTkFrame(dlg,fg_color=C("panel")); sf2.pack(fill="x",padx=14,pady=(0,12))
        ctk.CTkLabel(sf2,text=f"Total dépenses : {total_dep:,.0f} {devise}  |  Solde restant : {solde:,.0f} {devise}",
                     font=FH3,text_color=C("orange")).pack(padx=12,pady=8,anchor="e")

    # Catégorie
    def _dlg_category(self, cat=None, sf=None):
        edit=cat is not None
        dlg=self._dlg("Modifier catégorie" if edit else "Nouvelle catégorie",460,430)
        f=self._sf_form(dlg,"Modifier catégorie" if edit else "Nouvelle catégorie")
        f_nom  =self._field(f,"Nom *","ex: Taxes",default=cat["nom"] if edit else "")
        f_icone=self._field(f,"Icône","ex: 💼",default=cat.get("icone","💼") if edit else "💼")
        f_coul =self._field(f,"Couleur hex","#4F8EF7",default=cat.get("couleur","#4F8EF7") if edit else "#4F8EF7")
        tv=ctk.StringVar(value=cat.get("type","sortie") if edit else "sortie")
        self._opt(f,"Type",["sortie","entree"],tv)
        def submit():
            nom=f_nom.get().strip()
            if not nom: self.toast("⚠️ Nom requis.",C("orange")); return
            if edit: ok,msg=update_category(cat["id"],nom,f_coul.get().strip(),f_icone.get().strip(),tv.get())
            else:    ok,msg=add_category(nom,f_coul.get().strip(),f_icone.get().strip(),tv.get())
            if ok: dlg.destroy(); self.toast("✅ "+msg)
            else: self.toast("❌ "+msg,C("red"))
            if sf: self._refresh_cats(sf)
        self._btns(dlg,"✔ Enregistrer",submit)

    # Utilisateurs
    def _dlg_add_user(self, sf):
        dlg=self._dlg("Nouvel utilisateur",440,430)
        f=self._sf_form(dlg,"Nouvel utilisateur")
        f_nom=self._field(f,"Nom complet *")
        f_log=self._field(f,"Login *")
        f_pwd=self._field(f,"Mot de passe *",show="●")
        rv=ctk.StringVar(value="utilisateur"); self._opt(f,"Rôle",["utilisateur","admin"],rv)
        def submit():
            ok,msg=add_user(f_nom.get().strip(),f_log.get().strip(),f_pwd.get(),rv.get())
            if ok: dlg.destroy(); self.toast("✅ "+msg); self._refresh_users(sf)
            else: self.toast("❌ "+msg,C("red"))
        self._btns(dlg,"✔ Créer",submit)

    def _dlg_pwd(self, uid):
        dlg=self._dlg("Mot de passe",400,260)
        f=self._sf_form(dlg,"Nouveau mot de passe")
        e=self._field(f,"Mot de passe *",show="●")
        def submit():
            if len(e.get())<4: self.toast("⚠️ Min. 4 caractères.",C("orange")); return
            change_password(uid,e.get()); dlg.destroy(); self.toast("✅ Mis à jour.")
        self._btns(dlg,"✔ Confirmer",submit)

    # ── Actions ───────────────────────────────────────────────────────────────
    def _do_encaisser(self, ch):
        if messagebox.askyesno("Encaisser",f"Marquer #{ch['numero']} comme encaissé ?"):
            encaisser_cheque(ch["id"],current_user["id"])
            self.toast("✅ Encaissé."); self._navigate("cheques")

    def _do_dupliquer_cheque(self, ch):
        if messagebox.askyesno("Dupliquer",
            f"Créer un nouveau chèque basé sur #{ch['numero']} ?\n\n"
            f"Bénéficiaire : {ch['beneficiaire']}\n"
            f"Montant : {ch['montant_initial']:,.0f} {get_devise()}\n"
            f"Date d'émission : aujourd'hui\n\n"
            f"Un nouveau numéro sera attribué automatiquement."):
            ok,msg=dupliquer_cheque(ch["id"],user_id=current_user["id"])
            if ok: self.toast("✅ "+msg); self._navigate("cheques")
            else:  self.toast("❌ "+msg,C("red"))

    def _del_cheque(self, ch):
        trs=get_cheque_transactions(ch["id"])
        nb_dep=sum(1 for t in trs if t["type"]=="sortie")
        msg=f"Supprimer le chèque #{ch['numero']} et TOUTES ses transactions ?\n\nIrréversible."
        if nb_dep>0:
            msg=(f"⚠️ Ce chèque a {nb_dep} dépense(s) enregistrée(s).\n\n"
                 f"Supprimer le chèque #{ch['numero']} et TOUTES ses transactions "
                 f"({nb_dep+1} au total) ?\n\nIrréversible.")
        if messagebox.askyesno("Supprimer",msg,icon="warning"):
            delete_cheque(ch["id"]); self.toast("🗑️ Supprimé.",C("subtext"))
            self._navigate("cheques")

    def _del_transaction(self, tid):
        ok,msg=delete_transaction(tid)
        if ok:
            self.toast("🗑️ Supprimée.",C("subtext"))
            if hasattr(self,"_tr_sf"): self._refresh_tr(self._tr_sf)
        else:
            self.toast("❌ "+msg,C("red"))

    def _del_cat(self, cid, sf):
        if messagebox.askyesno("Supprimer","Supprimer cette catégorie ?"):
            delete_category(cid); self.toast("🗑️ Supprimée.",C("subtext"))
            self._refresh_cats(sf)

    def _del_user(self, uid, sf):
        if messagebox.askyesno("Supprimer","Supprimer cet utilisateur ?"):
            delete_user(uid); self.toast("🗑️ Supprimé.",C("subtext"))
            self._refresh_users(sf)

    def _confirm_reset(self):
        if current_user["role"]!="admin":
            self.toast("🔒 Réservé à l'administrateur.",C("red")); return
        if messagebox.askyesno("⚠️ Réinitialisation",
            "ATTENTION : Supprime TOUTES les transactions et chèques.\n"
            "Utilisateurs, catégories et paramètres conservés.\n"
            "Une sauvegarde sera créée automatiquement.\n\nConfirmer ?",icon="warning"):
            try: backup_db()
            except: pass
            reset_all_data(current_user["id"])
            self.toast("✅ Données réinitialisées.")
            self._navigate("dashboard")

    def _export_excel(self):
        fp=filedialog.asksaveasfilename(defaultextension=".xlsx",
            filetypes=[("Excel","*.xlsx")],initialfile=f"rapport_{date.today()}.xlsx")
        if not fp: return
        try: export_to_excel(fp); self.toast("✅ Export Excel réussi.")
        except Exception as e: self.toast(f"❌ {e}",C("red"))

    def _export_pdf(self):
        fp=filedialog.asksaveasfilename(defaultextension=".pdf",
            filetypes=[("PDF","*.pdf")],initialfile=f"rapport_{date.today()}.pdf")
        if not fp: return
        ok,msg=export_to_pdf(fp)
        self.toast(("✅ " if ok else "❌ ")+msg,C("green") if ok else C("red"))

    def _export_cheque_pdf(self, ch):
        fp=filedialog.asksaveasfilename(defaultextension=".pdf",
            filetypes=[("PDF","*.pdf")],initialfile=f"cheque_{ch['numero']}.pdf")
        if not fp: return
        ok,msg=export_cheque_pdf(fp,ch["id"])
        self.toast(("✅ " if ok else "❌ ")+msg,C("green") if ok else C("red"))

    # ── Recalcul chèques (correction erreurs v4) ──────────────────────────────
    def _dlg_recalcul_cheques(self):
        dlg=self._dlg("🔧 Recalcul / Réajustement chèques",680,560)
        ctk.CTkLabel(dlg,text="🔧 Recalcul des chèques",font=FH2,
                     text_color=C("text")).pack(pady=(14,2),padx=20,anchor="w")
        ctk.CTkLabel(dlg,
            text="Recalcule montant_restant de chaque chèque à partir de ses transactions réelles.\n"
                 "Utile pour corriger les erreurs de l'ancienne version (v4).",
            font=FS,text_color=C("subtext"),wraplength=620,justify="left"
            ).pack(padx=20,anchor="w")
        ctk.CTkFrame(dlg,height=1,fg_color=C("border")).pack(fill="x",padx=20,pady=10)

        sf=ctk.CTkScrollableFrame(dlg,fg_color=C("panel"),corner_radius=10)
        sf.pack(fill="both",expand=True,padx=14,pady=(0,4))

        res_lbl=ctk.CTkLabel(sf,text="Cliquez sur Recalculer pour analyser vos chèques.",
                              font=FB,text_color=C("subtext")); res_lbl.pack(pady=20)

        cheques=get_all_cheques()
        ch_names=[f"#{c['numero']} — {c['beneficiaire']}" for c in cheques]
        ch_var=ctk.StringVar(value="Tous les chèques")

        def do_recalcul_un():
            sel=ch_var.get()
            if sel=="Tous les chèques":
                do_recalcul_tous(); return
            idx=ch_names.index(sel)
            res,msg=recalculer_cheque(cheques[idx]["id"],current_user["id"])
            if not res: self.toast("❌ "+msg,C("red")); return
            _afficher_resultats([res])

        def do_recalcul_tous():
            resultats=recalculer_tous_cheques(current_user["id"])
            _afficher_resultats(resultats)

        def _afficher_resultats(resultats):
            for w in sf.winfo_children(): w.destroy()
            nb_changes=sum(1 for r in resultats if abs(r["diff"])>0.01)
            ctk.CTkLabel(sf,
                text=f"✅ {len(resultats)} chèque(s) analysé(s) — {nb_changes} modification(s)",
                font=FH3,text_color=C("green") if nb_changes==0 else C("orange")
                ).pack(anchor="w",padx=8,pady=(8,6))

            hdr=ctk.CTkFrame(sf,fg_color=C("card2"),corner_radius=8); hdr.pack(fill="x",pady=(0,4))
            for i,(col,w) in enumerate(zip(["Numéro","Avant","Après","Écart","Statut avant→après"],
                                            [110,130,130,120,200])):
                ctk.CTkLabel(hdr,text=col,font=("Segoe UI",11,"bold"),
                             text_color=C("subtext"),width=w).grid(row=0,column=i,padx=6,pady=7,sticky="w")

            for idx,r in enumerate(resultats):
                changed=abs(r["diff"])>0.01
                bg="#2A1A0A" if changed else self._row_bg(idx)
                row=ctk.CTkFrame(sf,fg_color=bg,corner_radius=8); row.pack(fill="x",pady=2)
                devise=get_devise()
                ctk.CTkLabel(row,text=r["numero"],font=FB,text_color=C("text"),
                             width=110,anchor="w").grid(row=0,column=0,padx=6,pady=7,sticky="w")
                ctk.CTkLabel(row,text=f"{r['montant_avant']:,.0f} {devise}",font=FB,
                             text_color=C("subtext"),width=130,anchor="w").grid(row=0,column=1,padx=6,pady=7,sticky="w")
                ctk.CTkLabel(row,text=f"{r['montant_apres']:,.0f} {devise}",font=FB,
                             text_color=C("green") if not changed else C("orange"),
                             width=130,anchor="w").grid(row=0,column=2,padx=6,pady=7,sticky="w")
                ecart_txt=(f"+{r['diff']:,.0f}" if r['diff']>0 else f"{r['diff']:,.0f}") if changed else "—"
                ctk.CTkLabel(row,text=ecart_txt,font=("Segoe UI",11,"bold"),
                             text_color=C("orange") if changed else C("subtext"),
                             width=120,anchor="w").grid(row=0,column=3,padx=6,pady=7,sticky="w")
                sl={"en_attente":"En attente","encaisse":"Encaissé",
                    "partiellement_utilise":"Partiel","cloture":"Clôturé"}
                s_txt=(f"{sl.get(r['statut_avant'],r['statut_avant'])} → "
                       f"{sl.get(r['statut_apres'],r['statut_apres'])}")
                ctk.CTkLabel(row,text=s_txt,font=FB,
                             text_color=C("accent") if r['statut_avant']!=r['statut_apres'] else C("subtext"),
                             width=200,anchor="w").grid(row=0,column=4,padx=6,pady=7,sticky="w")

        # Contrôles
        bf=ctk.CTkFrame(dlg,fg_color=C("panel")); bf.pack(fill="x",padx=14,pady=(4,14))
        ctk.CTkLabel(bf,text="Chèque :",font=FS,text_color=C("subtext")).pack(side="left",padx=(8,4),pady=8)
        ctk.CTkOptionMenu(bf,values=["Tous les chèques"]+ch_names,variable=ch_var,
                          fg_color=C("card2"),button_color=C("accent"),
                          height=36,font=FB,width=260).pack(side="left",padx=4)
        ctk.CTkButton(bf,text="🔧 Recalculer",height=36,fg_color=C("orange"),font=FH3,
                      command=do_recalcul_un).pack(side="left",padx=8)
        ctk.CTkButton(bf,text="Fermer",height=36,fg_color=C("card2"),hover_color=C("hover"),
                      font=FB,command=dlg.destroy).pack(side="right",padx=8)

    # ── Changer le chèque lié d'une dépense ──────────────────────────────────
    def _dlg_changer_cheque_depense(self, transaction):
        devise=get_devise()
        dlg=self._dlg("Changer le chèque lié",520,400)
        sf=self._sf_form(dlg,"Réaffecter la dépense")
        ctk.CTkLabel(sf,
            text=f"Dépense : {transaction['designation'][:40]}\n"
                 f"Montant : {transaction['montant']:,.0f} {devise}\n"
                 f"Chèque actuel : #{transaction.get('cheque_num','?')}",
            font=FB,text_color=C("subtext"),justify="left"
            ).pack(padx=20,pady=(8,12),anchor="w")

        cheques=[c for c in get_all_cheques()
                 if c["statut"] not in ("cloture",) and c["id"]!=transaction.get("cheque_id")]
        if not cheques:
            ctk.CTkLabel(sf,text="Aucun autre chèque disponible.",
                         font=FB,text_color=C("red")).pack(padx=20,pady=20)
            self._btns(dlg,"Fermer",dlg.destroy); return

        ch_names=[f"#{c['numero']} — {c['beneficiaire']} ({c['montant_restant']:,.0f} {devise})"
                  for c in cheques]
        ch_var=ctk.StringVar(value=ch_names[0]); self._opt(sf,"Nouveau chèque",ch_names,ch_var)

        # Disponibilité en temps réel
        lbl_ok=ctk.CTkLabel(sf,text="",font=FS,text_color=C("green"))
        lbl_ok.pack(padx=20,pady=(4,0),anchor="w")
        def on_ch(*_):
            idx=ch_names.index(ch_var.get()); ch=cheques[idx]
            if transaction["montant"]<=ch["montant_restant"]:
                lbl_ok.configure(
                    text=f"✅ Disponible : {ch['montant_restant']:,.0f} {devise} — OK",
                    text_color=C("green"))
            else:
                lbl_ok.configure(
                    text=f"❌ Insuffisant : {ch['montant_restant']:,.0f} < {transaction['montant']:,.0f} {devise}",
                    text_color=C("red"))
        ch_var.trace_add("write",on_ch); on_ch()

        def submit():
            idx=ch_names.index(ch_var.get()); ch=cheques[idx]
            ok,msg=changer_cheque_depense(transaction["id"],ch["id"],current_user["id"])
            if ok:
                dlg.destroy(); self.toast("✅ "+msg)
                if hasattr(self,"_tr_sf"): self._refresh_tr(self._tr_sf)
            else: self.toast("❌ "+msg,C("red"))
        self._btns(dlg,"✔ Réaffecter",submit,C("orange"))

    # ── Historique d'un chèque ────────────────────────────────────────────────
    def _dlg_historique_cheque(self, cheque):
        dlg=self._dlg(f"Historique modifications — #{cheque['numero']}",700,460)
        ctk.CTkLabel(dlg,text=f"Modifications chèque #{cheque['numero']}",
                     font=FH2,text_color=C("text")).pack(pady=(14,2),padx=20,anchor="w")
        ctk.CTkFrame(dlg,height=1,fg_color=C("border")).pack(fill="x",padx=20,pady=8)
        sf=ctk.CTkScrollableFrame(dlg,fg_color=C("panel")); sf.pack(fill="both",expand=True,padx=10,pady=(0,10))
        logs=get_historique_cheque(cheque["id"])
        if not logs:
            ctk.CTkLabel(sf,text="Aucune modification enregistrée.",
                         font=FB,text_color=C("subtext")).pack(pady=20); return
        hdr=ctk.CTkFrame(sf,fg_color=C("card2"),corner_radius=8); hdr.pack(fill="x",pady=(0,4))
        for i,(col,w) in enumerate(zip(["Date/Heure","Action","Détail","Par"],[155,140,320,120])):
            ctk.CTkLabel(hdr,text=col,font=("Segoe UI",11,"bold"),
                         text_color=C("subtext"),width=w).grid(row=0,column=i,padx=6,pady=7,sticky="w")
        for idx,log in enumerate(logs):
            row=ctk.CTkFrame(sf,fg_color=self._row_bg(idx),corner_radius=8); row.pack(fill="x",pady=2)
            ctk.CTkLabel(row,text=log["created_at"][:16],font=FB,text_color=C("subtext"),
                         width=155,anchor="w").grid(row=0,column=0,padx=6,pady=8,sticky="w")
            ctk.CTkLabel(row,text=log["action"],font=("Segoe UI",11,"bold"),
                         text_color=C("accent"),width=140,anchor="w").grid(row=0,column=1,padx=6,pady=8,sticky="w")
            detail=log.get("detail","") or ""
            dl=ctk.CTkLabel(row,text=trunc(detail,"detail"),font=FB,
                            text_color=C("text"),width=320,anchor="w")
            dl.grid(row=0,column=2,padx=6,pady=8,sticky="w")
            if detail: tooltip(dl,detail)
            ctk.CTkLabel(row,text=log.get("user_nom","") or "",font=FB,
                         text_color=C("subtext"),width=120,anchor="w").grid(row=0,column=3,padx=6,pady=8,sticky="w")
        ctk.CTkButton(dlg,text="Fermer",height=36,fg_color=C("card2"),
                      hover_color=C("hover"),font=FB,command=dlg.destroy).pack(pady=(0,10),padx=14,fill="x")

    # ── Confirmation dépense multi-chèques ────────────────────────────────────
    def _dlg_confirm_multi(self, repartition, designation, cat_id, date_t, notes, pj, cheques_dispo):
        """Affiche un récapitulatif avant de valider la dépense multi-chèques."""
        devise=get_devise()
        dlg=self._dlg("Confirmation dépense",540,420)
        ctk.CTkLabel(dlg,text="✅ Confirmation de la dépense",font=FH2,
                     text_color=C("text")).pack(pady=(14,4),padx=20,anchor="w")
        ctk.CTkFrame(dlg,height=1,fg_color=C("border")).pack(fill="x",padx=20,pady=(0,8))
        sf=ctk.CTkScrollableFrame(dlg,fg_color=C("panel"),corner_radius=10)
        sf.pack(fill="both",expand=True,padx=14,pady=(0,4))

        ctk.CTkLabel(sf,text=f"Désignation : {designation}",font=FB,
                     text_color=C("text")).pack(padx=16,pady=(12,4),anchor="w")
        ctk.CTkLabel(sf,text=f"Date : {date_t}",font=FB,
                     text_color=C("subtext")).pack(padx=16,anchor="w")
        ctk.CTkFrame(sf,height=1,fg_color=C("border")).pack(fill="x",padx=16,pady=10)

        total=0
        for ch_id,mnt in repartition:
            ch=next((c for c in cheques_dispo if c["id"]==ch_id),None)
            num=ch["numero"] if ch else f"#{ch_id}"
            ben=ch["beneficiaire"] if ch else ""
            rf=ctk.CTkFrame(sf,fg_color=self._row_bg(total//1000 if total else 0),corner_radius=8)
            rf.pack(fill="x",padx=8,pady=3)
            ctk.CTkLabel(rf,text=f"  #{num} — {ben}",font=FB,text_color=C("text"),
                         anchor="w").pack(side="left",padx=10,pady=8)
            ctk.CTkLabel(rf,text=f"{mnt:,.0f} {devise}",font=("Segoe UI",12,"bold"),
                         text_color=C("orange")).pack(side="right",padx=14,pady=8)
            total+=mnt

        ctk.CTkFrame(sf,height=1,fg_color=C("border")).pack(fill="x",padx=16,pady=(8,4))
        ctk.CTkLabel(sf,text=f"Total : {total:,.0f} {devise}",font=FH3,
                     text_color=C("accent")).pack(padx=16,pady=(4,12),anchor="e")

        confirmed=[False]
        def confirm():
            confirmed[0]=True; dlg.destroy()
        def cancel():
            dlg.destroy()
        bf=ctk.CTkFrame(dlg,fg_color=C("panel")); bf.pack(fill="x",padx=14,pady=(4,14))
        ctk.CTkButton(bf,text="✔ Confirmer et enregistrer",height=42,font=FH3,
                      fg_color=C("orange"),command=confirm).pack(fill="x",pady=(0,6),padx=4)
        ctk.CTkButton(bf,text="← Modifier",height=36,font=FB,
                      fg_color=C("card2"),hover_color=C("hover"),
                      command=cancel).pack(fill="x",padx=4)
        dlg.wait_window()
        return confirmed[0]

    # ── Commentaires sur transaction ──────────────────────────────────────────
    def _dlg_commentaires(self, transaction):
        dlg=self._dlg(f"Commentaires — {transaction['designation'][:30]}",580,520)
        ctk.CTkLabel(dlg,text="💬 Commentaires",font=FH2,
                     text_color=C("text")).pack(pady=(14,2),padx=20,anchor="w")
        ctk.CTkLabel(dlg,text=transaction["designation"],font=FS,
                     text_color=C("subtext")).pack(padx=20,anchor="w")
        ctk.CTkFrame(dlg,height=1,fg_color=C("border")).pack(fill="x",padx=20,pady=8)

        sf=ctk.CTkScrollableFrame(dlg,fg_color=C("panel"),corner_radius=10)
        sf.pack(fill="both",expand=True,padx=12,pady=(0,4))

        def refresh_coms():
            for w in sf.winfo_children(): w.destroy()
            coms=get_commentaires(transaction["id"])
            if not coms:
                ctk.CTkLabel(sf,text="Aucun commentaire. Soyez le premier !",
                             font=FB,text_color=C("subtext")).pack(pady=16)
            for c in coms:
                is_me = c.get("user_id")==current_user["id"]
                anchor= "e" if is_me else "w"
                bg    = C("accent") if is_me else C("card2")
                txt_c = C("white")  if is_me else C("text")
                outer=ctk.CTkFrame(sf,fg_color="transparent"); outer.pack(fill="x",pady=4,padx=8)
                bubble=ctk.CTkFrame(outer,fg_color=bg,corner_radius=12)
                bubble.pack(anchor=anchor,padx=4)
                ctk.CTkLabel(bubble,text=c["texte"],font=FB,text_color=txt_c,
                             wraplength=380,justify="left").pack(padx=12,pady=(8,4))
                info=f"{c.get('user_nom','?')}  •  {c['created_at'][:16]}"
                ctk.CTkLabel(bubble,text=info,font=("Segoe UI",9),
                             text_color=txt_c if not is_me else "#C0D8FF").pack(padx=12,pady=(0,6),anchor="w")
                if is_me:
                    ctk.CTkButton(bubble,text="✕",width=22,height=18,font=("Segoe UI",9),
                                  fg_color="transparent",hover_color="#3560C4",text_color=txt_c,
                                  command=lambda cid=c["id"]:
                                      [delete_commentaire(cid,current_user["id"]),refresh_coms()]
                                  ).pack(anchor="e",padx=6,pady=(0,4))

        refresh_coms()

        # Zone saisie
        saisie_fr=ctk.CTkFrame(dlg,fg_color=C("card")); saisie_fr.pack(fill="x",padx=12,pady=(4,12))
        e_txt=ctk.CTkEntry(saisie_fr,height=40,font=FB,fg_color=C("card2"),
                           border_color=C("border"),placeholder_text="Écrire un commentaire…")
        e_txt.pack(side="left",fill="x",expand=True,padx=(8,4),pady=8)
        def envoyer():
            texte=e_txt.get().strip()
            if not texte: return
            add_commentaire(transaction["id"],texte,current_user["id"])
            e_txt.delete(0,"end"); refresh_coms()
        e_txt.bind("<Return>",lambda e:envoyer())
        ctk.CTkButton(saisie_fr,text="Envoyer",height=38,width=90,
                      fg_color=C("accent"),font=FB,command=envoyer).pack(side="left",padx=(0,8),pady=8)

    # ── Tableau de bord imprimable ────────────────────────────────────────────
    def _print_dashboard(self):
        import tempfile
        fp=os.path.join(tempfile.gettempdir(),"cg_dashboard.pdf")
        ok,msg=self._export_dashboard_pdf(fp)
        if ok: self._apercu_pdf(fp)
        else:  self.toast("❌ "+msg,C("red"))

    def _export_dashboard_pdf(self, filepath):
        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.lib import colors
            from reportlab.lib.styles import getSampleStyleSheet
            from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle,
                                             Paragraph, Spacer)
            from reportlab.lib.units import cm
            from database import _get_entete, _pdf_entete
        except ImportError:
            return False,"reportlab non installé."

        e      = _get_entete(); devise=e["devise"]
        solde,entrees,sorties,s_ouv=get_solde_caisse()
        ch_actifs=[c for c in get_all_cheques() if c["statut"] not in ("cloture",)]
        echus  =get_cheques_echus(); alertes=get_cheques_alertes()
        top    =get_top_depenses(5)
        styles =getSampleStyleSheet()
        doc    =SimpleDocTemplate(filepath,pagesize=A4,
                                   leftMargin=1.5*cm,rightMargin=1.5*cm,
                                   topMargin=1.5*cm,bottomMargin=1.5*cm)
        story=[]
        _pdf_entete(story,styles,e)
        story.append(Paragraph(f"<b>Tableau de bord</b>",styles["Title"]))
        story.append(Paragraph(f"Généré le {datetime.now().strftime('%d/%m/%Y à %H:%M')}",styles["Normal"]))
        story.append(Spacer(1,0.4*cm))

        kpi=[["Indicateur","Valeur"],
             ["Solde ouverture",f"{s_ouv:,.0f} {devise}"],
             ["Total Entrées",  f"{entrees:,.0f} {devise}"],
             ["Total Sorties",  f"{sorties:,.0f} {devise}"],
             ["Solde Actuel",   f"{solde:,.0f} {devise}"],
             ["Chèques actifs", str(len(ch_actifs))],
             ["Chèques échus",  str(len(echus))],
             ["Alertes seuil",  str(len(alertes))]]
        t=Table(kpi,colWidths=[9*cm,8*cm])
        t.setStyle(TableStyle([
            ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#1A2744")),
            ("TEXTCOLOR",(0,0),(-1,0),colors.white),
            ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
            ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.HexColor("#EEF2FF"),colors.white]),
            ("FONTNAME",(0,0),(0,-1),"Helvetica-Bold"),
            ("FONTSIZE",(0,0),(-1,-1),11),
            ("ALIGN",(1,0),(1,-1),"RIGHT"),
            ("PADDING",(0,0),(-1,-1),8),
            ("GRID",(0,0),(-1,-1),0.4,colors.HexColor("#CCCCCC")),
        ]))
        story.append(t); story.append(Spacer(1,0.5*cm))

        if top:
            story.append(Paragraph("<b>Top 5 dépenses</b>",styles["Heading2"]))
            from reportlab.platypus import Paragraph as P
            small=styles["Normal"].clone("small"); small.fontSize=8.5; small.leading=11
            top_data=[["Désignation","Total","Nb"]]+[
                [P(t["designation"],small),f"{t['total']:,.0f} {devise}",str(t["nb"])]
                for t in top]
            t2=Table(top_data,colWidths=[11*cm,4*cm,2*cm])
            t2.setStyle(TableStyle([
                ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#1A2744")),
                ("TEXTCOLOR",(0,0),(-1,0),colors.white),
                ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
                ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.HexColor("#F5F5F5"),colors.white]),
                ("FONTSIZE",(0,0),(-1,-1),9),
                ("ALIGN",(1,0),(2,-1),"RIGHT"),
                ("GRID",(0,0),(-1,-1),0.3,colors.HexColor("#DDDDDD")),
                ("PADDING",(0,0),(-1,-1),6),
            ]))
            story.append(t2)
        doc.build(story)
        return True,"Dashboard exporté."

    # ── Réinitialisation mot de passe ─────────────────────────────────────────
    def _dlg_reset_pwd_admin(self):
        if current_user["role"]!="admin":
            self.toast("🔒 Réservé à l'administrateur.",C("red")); return
        dlg=self._dlg("🔑 Réinitialiser un mot de passe",460,360)
        sf=self._sf_form(dlg,"Réinitialisation par l'administrateur")
        logins=get_all_logins()
        login_names=[f"{l['nom']} ({l['login']})" for l in logins]
        login_var=ctk.StringVar(value=login_names[0] if login_names else "")
        self._opt(sf,"Utilisateur",login_names,login_var)
        f_pwd1=self._field(sf,"Nouveau mot de passe *",show="●")
        f_pwd2=self._field(sf,"Confirmer *",show="●")
        def submit():
            if f_pwd1.get()!=f_pwd2.get():
                self.toast("❌ Mots de passe différents.",C("red")); return
            if len(f_pwd1.get())<4:
                self.toast("⚠️ Min. 4 caractères.",C("orange")); return
            idx=login_names.index(login_var.get())
            ok,msg=reset_password_by_admin(logins[idx]["login"],f_pwd1.get(),current_user["id"])
            if ok: dlg.destroy(); self.toast("✅ "+msg)
            else:  self.toast("❌ "+msg,C("red"))
        self._btns(dlg,"✔ Réinitialiser",submit,C("orange"))

    # ── Export planifié (appelé en thread au démarrage) ───────────────────────
    def _check_export_planifie(self):
        result=check_export_planifie()
        if result and isinstance(result,str):
            self.after(0,lambda:self.toast(f"📅 Export auto généré : {os.path.basename(result)}",C("green")))

    # ── Import CSV / Excel ────────────────────────────────────────────────────
    def _dlg_import(self):
        fp=filedialog.askopenfilename(
            filetypes=[("CSV / Excel","*.csv *.xlsx"),("CSV","*.csv"),("Excel","*.xlsx")])
        if not fp: return
        is_excel = fp.lower().endswith(".xlsx")
        try:
            headers = get_excel_headers(fp) if is_excel else get_csv_headers(fp)
        except Exception as ex:
            self.toast(f"❌ Lecture fichier : {ex}",C("red")); return
        if not headers:
            self.toast("⚠️ Fichier vide ou illisible.",C("orange")); return

        dlg=self._dlg("📥 Importer des transactions",520,560)
        sf=self._sf_form(dlg,"Faire correspondre les colonnes")
        ctk.CTkLabel(sf,text=f"Fichier : {os.path.basename(fp)}  ({len(headers)} colonnes détectées)",
                     font=FS,text_color=C("subtext"),wraplength=460
                     ).pack(padx=20,pady=(8,12),anchor="w")

        champs=[("date","Date * (AAAA-MM-JJ)"),("type","Type * (entrée/sortie)"),
                ("montant","Montant *"),("designation","Désignation *"),
                ("categorie","Catégorie (optionnel)")]
        vars_={}
        headers_opts=["— Ignorer —"]+headers
        for key,label in champs:
            v=ctk.StringVar(value=headers_opts[0])
            # Tentative d'auto-détection par nom de colonne
            for h in headers:
                if key.split(" ")[0].lower() in h.lower(): v.set(h); break
            self._opt(sf,label,headers_opts,v)
            vars_[key]=v

        def submit():
            mapping={}
            for key,_ in champs:
                val=vars_[key].get()
                if val!="— Ignorer —": mapping[key]=val
            if "date" not in mapping or "type" not in mapping or \
               "montant" not in mapping or "designation" not in mapping:
                self.toast("⚠️ Les champs obligatoires (*) doivent être mappés.",C("orange")); return
            if is_excel:
                nb_ok,nb_err,erreurs=importer_transactions_excel(fp,mapping,current_user["id"])
            else:
                nb_ok,nb_err,erreurs=importer_transactions_csv(fp,mapping,current_user["id"])
            dlg.destroy()
            if nb_ok>0:
                self.toast(f"✅ {nb_ok} transaction(s) importée(s)"+
                          (f", {nb_err} erreur(s)" if nb_err else ""),
                          C("green") if nb_err==0 else C("orange"))
                self._navigate("transactions")
            else:
                self.toast(f"❌ Aucune transaction importée ({nb_err} erreur(s)).",C("red"))
            if erreurs:
                detail="\n".join(erreurs[:15])
                if len(erreurs)>15: detail+=f"\n… et {len(erreurs)-15} autre(s)."
                messagebox.showwarning("Erreurs d'import",detail)
        self._btns(dlg,"✔ Importer",submit)

    def _logout(self):
        if messagebox.askyesno("Déconnexion","Voulez-vous vous déconnecter ?"):
            self.destroy(); LoginWindow().mainloop()

    # ── Impression directe ────────────────────────────────────────────────────
    def _print_direct(self, filepath):
        """Ouvre le fichier PDF avec l'application système (impression directe)."""
        try:
            if sys.platform=="win32":
                os.startfile(filepath,"print")
            elif sys.platform=="darwin":
                subprocess.Popen(["lpr",filepath])
            else:
                subprocess.Popen(["lpr",filepath])
            self.toast("🖨️ Envoyé à l'imprimante.")
        except Exception as ex:
            self.toast(f"❌ Impression : {ex}",C("red"))

    def _print_rapport(self):
        """Génère un PDF temporaire et l'envoie à l'imprimante."""
        import tempfile
        fp=os.path.join(tempfile.gettempdir(),f"cashflow_print_{date.today()}.pdf")
        ok,msg=export_to_pdf(fp)
        if ok: self._print_direct(fp)
        else:  self.toast("❌ "+msg,C("red"))

    def _print_cheque(self, ch):
        import tempfile
        fp=os.path.join(tempfile.gettempdir(),f"cheque_{ch['numero']}.pdf")
        ok,msg=export_cheque_pdf(fp,ch["id"])
        if ok: self._print_direct(fp)
        else:  self.toast("❌ "+msg,C("red"))

    # ── Aperçu PDF ────────────────────────────────────────────────────────────
    def _apercu_pdf(self, filepath):
        """Ouvre le PDF dans le visualiseur système."""
        try:
            if sys.platform=="win32":
                os.startfile(filepath)
            elif sys.platform=="darwin":
                subprocess.Popen(["open",filepath])
            else:
                subprocess.Popen(["xdg-open",filepath])
        except Exception as ex:
            self.toast(f"❌ Aperçu : {ex}",C("red"))

    def _apercu_et_export(self, export_fn, *args, suffix="rapport"):
        """Génère un PDF dans un temp, affiche l'aperçu, puis propose d'enregistrer."""
        import tempfile
        fp=os.path.join(tempfile.gettempdir(),f"cashflow_{suffix}.pdf")
        ok,msg=export_fn(fp,*args)
        if not ok: self.toast("❌ "+msg,C("red")); return
        self._apercu_pdf(fp)
        if messagebox.askyesno("Enregistrer","Voulez-vous enregistrer ce PDF ?"):
            dest=filedialog.asksaveasfilename(defaultextension=".pdf",
                filetypes=[("PDF","*.pdf")],initialfile=f"{suffix}.pdf")
            if dest:
                import shutil; shutil.copy2(fp,dest)
                self.toast("✅ PDF enregistré.")

    # ── Raccourcis clavier — aide ─────────────────────────────────────────────
    def _show_shortcuts(self):
        dlg=self._dlg("⌨️ Raccourcis clavier",500,420)
        sf=self._sf_form(dlg,"Raccourcis clavier")
        shortcuts=[
            ("Ctrl + N","Nouveau (chèque ou transaction selon la page)"),
            ("Ctrl + D","Tableau de bord"),
            ("Ctrl + H","Page Chèques"),
            ("Ctrl + T","Page Transactions"),
            ("Ctrl + S","Statistiques"),
            ("Ctrl + F","Recherche globale"),
            ("Ctrl + R","Rapports"),
            ("Ctrl + B","Budgets"),
            ("Ctrl + E","Export Excel rapide"),
            ("Ctrl + P","Export PDF rapide"),
            ("F5","Rafraîchir la page courante"),
            ("F1","Cette fenêtre d'aide"),
        ]
        for key,desc in shortcuts:
            fr=ctk.CTkFrame(sf,fg_color=C("card2"),corner_radius=8)
            fr.pack(fill="x",padx=16,pady=3)
            ctk.CTkLabel(fr,text=key,font=("Courier New",11,"bold"),
                         text_color=C("accent"),width=160,anchor="w").pack(side="left",padx=12,pady=8)
            ctk.CTkLabel(fr,text=desc,font=FB,text_color=C("text"),anchor="w").pack(side="left",padx=4)
        ctk.CTkButton(dlg,text="Fermer",height=38,fg_color=C("card2"),
                      hover_color=C("hover"),font=FB,command=dlg.destroy).pack(pady=12,padx=20,fill="x")

    # ── Convertisseur de devises ──────────────────────────────────────────────
    def _dlg_convertisseur(self):
        devise1=get_devise(); devise2=get_devise_secondaire()
        taux   =get_taux_conversion()
        if not devise2:
            self.toast("⚠️ Configurez une devise secondaire dans les Paramètres.",C("orange")); return
        dlg=self._dlg("💱 Convertisseur de devises",420,320)
        sf=self._sf_form(dlg,f"Convertisseur {devise1} ↔ {devise2}")
        f_mnt=self._field(sf,f"Montant en {devise1}","ex: 100000")
        lbl_res=ctk.CTkLabel(sf,text="",font=FH3,text_color=C("accent"))
        lbl_res.pack(padx=20,pady=(8,0),anchor="w")
        lbl_inv=ctk.CTkLabel(sf,text="",font=FS,text_color=C("subtext"))
        lbl_inv.pack(padx=20,pady=(2,0),anchor="w")
        ctk.CTkLabel(sf,text=f"Taux : 1 {devise1} = {taux} {devise2}",
                     font=FS,text_color=C("subtext")).pack(padx=20,pady=(10,0),anchor="w")
        def calc(*_):
            try:
                m=float(f_mnt.get().strip())
                r=convertir(m,True)
                lbl_res.configure(text=f"= {r:,.2f} {devise2}")
                inv=convertir(m,False)
                lbl_inv.configure(text=f"Inverse : {m:,.2f} {devise2} = {inv:,.2f} {devise1}")
            except: lbl_res.configure(text=""); lbl_inv.configure(text="")
        f_mnt.bind("<KeyRelease>",calc)
        ctk.CTkButton(dlg,text="Fermer",height=38,fg_color=C("card2"),
                      hover_color=C("hover"),font=FB,command=dlg.destroy).pack(pady=12,padx=20,fill="x")

    # ── Pièce jointe helper ───────────────────────────────────────────────────
    def _field_pj(self, parent, label="Pièce jointe", default=""):
        """Widget champ + bouton parcourir pour les pièces jointes."""
        ctk.CTkLabel(parent,text=label,font=FS,text_color=C("subtext"),
                     anchor="w").pack(fill="x",padx=20,pady=(12,2))
        fr=ctk.CTkFrame(parent,fg_color="transparent"); fr.pack(fill="x",padx=20)
        e=ctk.CTkEntry(fr,height=38,font=FB,fg_color=C("card2"),
                       border_color=C("border"),placeholder_text="Aucune pièce jointe")
        e.pack(side="left",fill="x",expand=True)
        if default: e.insert(0,str(default))
        def parcourir():
            fp=filedialog.askopenfilename(
                filetypes=[("Tous fichiers","*.*"),("PDF","*.pdf"),
                           ("Images","*.png *.jpg *.jpeg"),("Excel","*.xlsx")])
            if fp:
                nom=save_piece_jointe(fp)
                e.delete(0,"end"); e.insert(0,nom)
        def ouvrir():
            nom=e.get().strip()
            if not nom: return
            p=get_piece_jointe_path(nom)
            if p:
                try:
                    if sys.platform=="win32": os.startfile(p)
                    elif sys.platform=="darwin": subprocess.Popen(["open",p])
                    else: subprocess.Popen(["xdg-open",p])
                except: self.toast("❌ Impossible d'ouvrir le fichier.",C("red"))
            else: self.toast("⚠️ Fichier introuvable.",C("orange"))
        bf=ctk.CTkFrame(fr,fg_color="transparent"); bf.pack(side="left",padx=(4,0))
        ctk.CTkButton(bf,text="📎",width=36,height=38,font=FB,
                      fg_color=C("card2"),hover_color=C("hover"),
                      command=parcourir).pack(side="left",padx=1)
        ctk.CTkButton(bf,text="👁",width=36,height=38,font=FB,
                      fg_color=C("card2"),hover_color=C("hover"),
                      command=ouvrir).pack(side="left",padx=1)
        return e

    # ── Champs personnalisés ──────────────────────────────────────────────────
    def _dlg_champs_custom(self, objet_type, objet_id, objet_label):
        """Dialogue pour gérer les champs personnalisés (clé/valeur)."""
        if objet_type=="cheque":
            get_fn=get_champs_custom_cheque
            set_fn=set_champs_custom_cheque
        else:
            get_fn=get_champs_custom_transaction
            set_fn=set_champs_custom_transaction

        dlg=self._dlg(f"Champs personnalisés — {objet_label}",520,500)
        ctk.CTkLabel(dlg,text=f"Champs personnalisés",font=FH2,
                     text_color=C("text")).pack(pady=(14,4),padx=20,anchor="w")
        ctk.CTkLabel(dlg,text="Ajoutez vos propres champs clé / valeur",
                     font=FS,text_color=C("subtext")).pack(padx=20,anchor="w")
        ctk.CTkFrame(dlg,height=1,fg_color=C("border")).pack(fill="x",padx=20,pady=(8,0))

        sf=ctk.CTkScrollableFrame(dlg,fg_color=C("panel"),corner_radius=10)
        sf.pack(fill="both",expand=True,padx=16,pady=8)

        champs=get_fn(objet_id)
        lignes=[]  # [(key_entry, val_entry, row_frame)]

        def ajouter_ligne(k="",v=""):
            rf=ctk.CTkFrame(sf,fg_color="transparent"); rf.pack(fill="x",pady=3,padx=4)
            ek=ctk.CTkEntry(rf,width=160,height=36,font=FB,fg_color=C("card2"),
                            border_color=C("border"),placeholder_text="Clé…")
            ek.pack(side="left",padx=(0,4))
            if k: ek.insert(0,k)
            ev=ctk.CTkEntry(rf,height=36,font=FB,fg_color=C("card2"),
                            border_color=C("border"),placeholder_text="Valeur…")
            ev.pack(side="left",fill="x",expand=True,padx=(0,4))
            if v: ev.insert(0,v)
            def rm(row=rf,ek=ek,ev=ev):
                for i,(k2,v2,r2) in enumerate(lignes):
                    if r2 is row: lignes.pop(i); break
                row.destroy()
            ctk.CTkButton(rf,text="✕",width=30,height=36,font=FS,
                          fg_color=C("red"),hover_color="#C44",
                          command=rm).pack(side="left")
            lignes.append((ek,ev,rf))

        for k,v in champs.items(): ajouter_ligne(k,str(v))

        ctk.CTkButton(sf,text="＋ Ajouter un champ",height=32,font=FB,
                      fg_color=C("card2"),hover_color=C("hover"),
                      command=ajouter_ligne).pack(pady=(8,4),anchor="w",padx=4)

        def sauvegarder():
            d={}
            for ek,ev,_ in lignes:
                k=ek.get().strip(); v=ev.get().strip()
                if k: d[k]=v
            set_fn(objet_id,d)
            dlg.destroy()
            self.toast(f"✅ {len(d)} champ(s) enregistré(s).")

        bf=ctk.CTkFrame(dlg,fg_color=C("panel"))
        bf.pack(fill="x",padx=16,pady=(0,16))
        ctk.CTkButton(bf,text="✔ Enregistrer",height=42,font=FH3,
                      fg_color=C("accent"),command=sauvegarder).pack(fill="x",pady=(0,6),padx=4)
        ctk.CTkButton(bf,text="Annuler",height=36,font=FB,
                      fg_color=C("card2"),hover_color=C("hover"),
                      command=dlg.destroy).pack(fill="x",padx=4)


# ── Helpers globaux ────────────────────────────────────────────────────────────
def _safe_backup():
    try: backup_db()
    except: pass


# ═══════════════════════════════════════════════════════════════════════════════
if __name__=="__main__":
    init_db()
    _apply_theme("dark")
    LoginWindow().mainloop()