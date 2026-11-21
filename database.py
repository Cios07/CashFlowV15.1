"""
database.py v5 — CashFlow
Corrections :
 - update_transaction recalcule montant_restant du chèque lié
 - delete_transaction : recalcul propre du statut chèque
 - Blocage suppression transaction d'entrée initiale d'un chèque
Nouveautés :
 - depense_multi_cheques() : répartition dépense sur plusieurs chèques
 - date_echeance sur chèques + alertes dépassement
 - Numérotation automatique des chèques
 - Pièces jointes sur transactions (chemin fichier)
 - Notes enrichies (texte long)
 - Budget mensuel par catégorie
 - Rapports personnalisés (export_cheque_pdf, rapport_mensuel, rapport_categories)
 - En-tête personnalisée avec logo (société, adresse, téléphone)
 - Multi-devises dans paramètres
 - Champs personnalisés (JSON)
 - get_cheques_echus() pour alertes dépassement d'échéance
"""
import sqlite3, hashlib, os, sys, shutil, secrets, json, re
from datetime import datetime, date

if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DB_PATH    = os.path.join(BASE_DIR, "caisse_gestion.db")
BACKUP_DIR = os.path.join(BASE_DIR, "sauvegardes")
ATTACH_DIR = os.path.join(BASE_DIR, "pieces_jointes")

_login_attempts = {}
_PARAM_CACHE    = {}                      # évite d'ouvrir la base pour chaque paramètre
_HEX_COLOR      = re.compile(r"^#[0-9a-fA-F]{6}$")
MAX_ATTEMPTS    = 5

# ── Connexion ─────────────────────────────────────────────────────────────────
def get_connection():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA temp_store = MEMORY")
    conn.execute("PRAGMA cache_size = -8000")
    return conn

# ── Initialisation ────────────────────────────────────────────────────────────
def init_db():
    conn = get_connection()
    conn.execute("PRAGMA journal_mode = WAL")   # persistant : inutile de le refaire à chaque connexion
    c    = conn.cursor()

    c.execute("""CREATE TABLE IF NOT EXISTS utilisateurs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nom TEXT NOT NULL, login TEXT UNIQUE NOT NULL,
        mot_de_passe TEXT NOT NULL, sel TEXT NOT NULL DEFAULT '',
        role TEXT DEFAULT 'utilisateur',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")

    c.execute("""CREATE TABLE IF NOT EXISTS parametres (
        cle TEXT PRIMARY KEY, valeur TEXT NOT NULL)""")

    c.execute("""CREATE TABLE IF NOT EXISTS categories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nom TEXT UNIQUE NOT NULL, couleur TEXT DEFAULT '#4F8EF7',
        icone TEXT DEFAULT '💼', type TEXT DEFAULT 'sortie')""")

    c.execute("""CREATE TABLE IF NOT EXISTS cheques (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        numero TEXT UNIQUE NOT NULL,
        montant_initial REAL NOT NULL, montant_restant REAL NOT NULL,
        date_emission TEXT NOT NULL, date_echeance TEXT DEFAULT '',
        beneficiaire TEXT NOT NULL, banque TEXT DEFAULT '',
        statut TEXT DEFAULT 'en_attente', notes TEXT DEFAULT '',
        champs_custom TEXT DEFAULT '{}',
        created_by INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (created_by) REFERENCES utilisateurs(id))""")

    c.execute("""CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        type TEXT NOT NULL, montant REAL NOT NULL,
        designation TEXT NOT NULL, categorie_id INTEGER,
        cheque_id INTEGER, date_transaction TEXT NOT NULL,
        reference TEXT DEFAULT '', notes TEXT DEFAULT '',
        piece_jointe TEXT DEFAULT '',
        champs_custom TEXT DEFAULT '{}',
        created_by INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (categorie_id) REFERENCES categories(id),
        FOREIGN KEY (cheque_id) REFERENCES cheques(id),
        FOREIGN KEY (created_by) REFERENCES utilisateurs(id))""")

    c.execute("""CREATE TABLE IF NOT EXISTS historique (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        action TEXT NOT NULL, detail TEXT DEFAULT '',
        user_id INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")

    c.execute("""CREATE TABLE IF NOT EXISTS budgets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        categorie_id INTEGER NOT NULL, annee INTEGER NOT NULL,
        mois INTEGER NOT NULL, montant REAL NOT NULL,
        UNIQUE(categorie_id, annee, mois),
        FOREIGN KEY (categorie_id) REFERENCES categories(id))""")

    # Migrations automatiques (safe — ADD COLUMN ne modifie jamais les données)
    migrations = [
        "ALTER TABLE utilisateurs ADD COLUMN sel TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE categories ADD COLUMN type TEXT DEFAULT 'sortie'",
        "ALTER TABLE cheques ADD COLUMN updated_at TEXT DEFAULT CURRENT_TIMESTAMP",
        "ALTER TABLE cheques ADD COLUMN banque TEXT DEFAULT ''",
        "ALTER TABLE cheques ADD COLUMN notes TEXT DEFAULT ''",
        "ALTER TABLE cheques ADD COLUMN date_echeance TEXT DEFAULT ''",
        "ALTER TABLE cheques ADD COLUMN champs_custom TEXT DEFAULT '{}'",
        "ALTER TABLE transactions ADD COLUMN reference TEXT DEFAULT ''",
        "ALTER TABLE transactions ADD COLUMN notes TEXT DEFAULT ''",
        "ALTER TABLE transactions ADD COLUMN piece_jointe TEXT DEFAULT ''",
        "ALTER TABLE transactions ADD COLUMN champs_custom TEXT DEFAULT '{}'",
    ]
    for m in migrations:
        try: c.execute(m)
        except Exception: pass

    # Table commentaires (migration safe)
    c.execute("""CREATE TABLE IF NOT EXISTS commentaires (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        transaction_id INTEGER NOT NULL,
        user_id INTEGER,
        texte TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (transaction_id) REFERENCES transactions(id) ON DELETE CASCADE,
        FOREIGN KEY (user_id) REFERENCES utilisateurs(id))""")

    # Admin par défaut
    if not c.execute("SELECT id FROM utilisateurs WHERE login='admin'").fetchone():
        sel = secrets.token_hex(16)
        c.execute("INSERT INTO utilisateurs (nom,login,mot_de_passe,sel,role) VALUES (?,?,?,?,?)",
                  ("Administrateur","admin",_hash_password("admin123",sel),sel,"admin"))

    # Paramètres par défaut
    for k, v in [
        ("solde_ouverture","0"), ("devise","FCFA"),
        ("societe","Ma Société"), ("seuil_alerte","10"),
        ("auto_backup","1"), ("adresse",""), ("telephone",""),
        ("logo_path",""), ("devise_secondaire",""), ("taux_conversion","1"),
        ("export_auto","0"), ("export_auto_dossier",""), ("export_auto_dernier",""),
    ]:
        c.execute("INSERT OR IGNORE INTO parametres (cle,valeur) VALUES (?,?)",(k,v))

    # Catégories par défaut
    for cat in [
        ("Salaires","#3DD68C","👥","sortie"),
        ("Factures","#4F8EF7","📄","sortie"),
        ("Fournitures","#F5A623","📦","sortie"),
        ("Loyer","#7C5CFC","🏢","sortie"),
        ("Transport","#F75F5F","🚗","sortie"),
        ("Alimentation","#2BC0B4","🍽️","sortie"),
        ("Divers","#7A8099","📌","sortie"),
        ("Dépôt","#3DD68C","💰","entree"),
        ("Virement","#4F8EF7","🏦","entree"),
        ("Remboursement","#F5A623","↩️","entree"),
    ]:
        c.execute("INSERT OR IGNORE INTO categories (nom,couleur,icone,type) VALUES (?,?,?,?)",cat)

    # Index : recherches / tris / jointures beaucoup plus rapides
    for ddl in (
        "CREATE INDEX IF NOT EXISTS idx_tr_date    ON transactions(date_transaction)",
        "CREATE INDEX IF NOT EXISTS idx_tr_cheque  ON transactions(cheque_id)",
        "CREATE INDEX IF NOT EXISTS idx_tr_cat     ON transactions(categorie_id)",
        "CREATE INDEX IF NOT EXISTS idx_tr_type    ON transactions(type)",
        "CREATE INDEX IF NOT EXISTS idx_ch_statut  ON cheques(statut)",
        "CREATE INDEX IF NOT EXISTS idx_hist_date  ON historique(created_at)",
        "CREATE INDEX IF NOT EXISTS idx_com_tr     ON commentaires(transaction_id)",
    ):
        c.execute(ddl)
    # Réparation : couleurs de catégories invalides (ex. « #4F8EG6 ») qui faisaient planter l'écran
    c.execute("UPDATE categories SET couleur='#4F8EF7' WHERE couleur IS NULL OR couleur NOT GLOB "
              "'#[0-9A-Fa-f][0-9A-Fa-f][0-9A-Fa-f][0-9A-Fa-f][0-9A-Fa-f][0-9A-Fa-f]'")
    conn.commit()
    conn.close()
    _PARAM_CACHE.clear()
    os.makedirs(ATTACH_DIR, exist_ok=True)


# ── Sécurité ──────────────────────────────────────────────────────────────────
def _hash_password(pwd, sel):
    return hashlib.sha256((sel+pwd).encode()).hexdigest()

def authenticate(login, password):
    attempts = _login_attempts.get(login, 0)
    if attempts >= MAX_ATTEMPTS:
        return None, "bloque"
    conn = get_connection()
    row  = conn.execute("SELECT * FROM utilisateurs WHERE login=?",(login,)).fetchone()
    conn.close()
    if not row:
        _login_attempts[login] = attempts+1
        return None, f"invalide:{max(0,MAX_ATTEMPTS-_login_attempts[login])}"
    row = dict(row)
    sel = row.get("sel","")
    ph  = _hash_password(password,sel) if sel else hashlib.sha256(password.encode()).hexdigest()
    if row["mot_de_passe"] == ph:
        _login_attempts[login] = 0
        return row, "ok"
    _login_attempts[login] = attempts+1
    return None, f"invalide:{max(0,MAX_ATTEMPTS-_login_attempts[login])}"

def get_all_users():
    conn = get_connection()
    rows = conn.execute("SELECT id,nom,login,role,created_at FROM utilisateurs").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def add_user(nom, login, password, role="utilisateur"):
    conn = get_connection()
    try:
        sel = secrets.token_hex(16)
        conn.execute("INSERT INTO utilisateurs (nom,login,mot_de_passe,sel,role) VALUES (?,?,?,?,?)",
                     (nom,login,_hash_password(password,sel),sel,role))
        conn.commit(); return True,"Utilisateur créé."
    except sqlite3.IntegrityError:
        return False,"Login déjà utilisé."
    finally:
        conn.close()

def change_password(user_id, new_password):
    conn = get_connection()
    sel  = secrets.token_hex(16)
    conn.execute("UPDATE utilisateurs SET mot_de_passe=?,sel=? WHERE id=?",
                 (_hash_password(new_password,sel),sel,user_id))
    conn.commit(); conn.close()

def delete_user(user_id):
    conn = get_connection()
    conn.execute("DELETE FROM utilisateurs WHERE id=?",(user_id,))
    conn.commit(); conn.close()


# ── Paramètres ────────────────────────────────────────────────────────────────
def get_parametre(cle, default=""):
    if cle in _PARAM_CACHE:
        v = _PARAM_CACHE[cle]
        return default if v is None else v
    conn = get_connection()
    row  = conn.execute("SELECT valeur FROM parametres WHERE cle=?",(cle,)).fetchone()
    conn.close()
    _PARAM_CACHE[cle] = row["valeur"] if row else None
    return row["valeur"] if row else default

def set_parametre(cle, valeur):
    conn = get_connection()
    conn.execute("INSERT OR REPLACE INTO parametres (cle,valeur) VALUES (?,?)",(cle,valeur))
    conn.commit(); conn.close()
    _PARAM_CACHE[cle] = valeur

def get_devise():          return get_parametre("devise","FCFA")
def get_seuil_alerte():
    try: return float(get_parametre("seuil_alerte","10"))
    except: return 10.0


# ── Catégories ────────────────────────────────────────────────────────────────
def get_categories(type_=None):
    conn = get_connection()
    if type_:
        rows = conn.execute("SELECT * FROM categories WHERE type=? ORDER BY nom",(type_,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM categories ORDER BY nom").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def add_category(nom, couleur, icone, type_="sortie"):
    if not _HEX_COLOR.match((couleur or "").strip()):
        return False,"Couleur invalide : utilisez le format #RRGGBB (ex. #4F8EF7)."
    couleur = couleur.strip()
    conn = get_connection()
    try:
        conn.execute("INSERT INTO categories (nom,couleur,icone,type) VALUES (?,?,?,?)",(nom,couleur,icone,type_))
        conn.commit(); return True,"Catégorie ajoutée."
    except sqlite3.IntegrityError:
        return False,"Catégorie déjà existante."
    finally: conn.close()

def update_category(cat_id, nom, couleur, icone, type_):
    if not _HEX_COLOR.match((couleur or "").strip()):
        return False,"Couleur invalide : utilisez le format #RRGGBB (ex. #4F8EF7)."
    couleur = couleur.strip()
    conn = get_connection()
    try:
        conn.execute("UPDATE categories SET nom=?,couleur=?,icone=?,type=? WHERE id=?",
                     (nom,couleur,icone,type_,cat_id))
        conn.commit(); return True,"Catégorie modifiée."
    except sqlite3.IntegrityError:
        return False,"Nom déjà utilisé."
    finally: conn.close()

def delete_category(cat_id):
    conn = get_connection()
    conn.execute("UPDATE transactions SET categorie_id=NULL WHERE categorie_id=?",(cat_id,))
    conn.execute("DELETE FROM budgets WHERE categorie_id=?",(cat_id,))
    conn.execute("DELETE FROM categories WHERE id=?",(cat_id,))
    conn.commit(); conn.close()


# ── Numérotation automatique ───────────────────────────────────────────────────
def get_next_numero_cheque():
    """Retourne le prochain numéro auto ex: CHQ-0042"""
    conn = get_connection()
    row  = conn.execute(
        "SELECT numero FROM cheques WHERE numero LIKE 'CHQ-%' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    conn.close()
    if row:
        try:
            n = int(row["numero"].split("-")[1]) + 1
            return f"CHQ-{n:04d}"
        except: pass
    return "CHQ-0001"


# ── Chèques ───────────────────────────────────────────────────────────────────
def _recalc_statut_cheque(conn, cheque_id):
    """Recalcule et met à jour le statut d'un chèque en fonction de montant_restant."""
    ch = conn.execute("SELECT * FROM cheques WHERE id=?",(cheque_id,)).fetchone()
    if not ch: return
    r, i = ch["montant_restant"], ch["montant_initial"]
    if ch["statut"] in ("encaisse",):
        return  # statut manuel : ne pas écraser
    if r <= 0:
        new_s = "cloture"
    elif r < i:
        new_s = "partiellement_utilise"
    else:
        new_s = "en_attente"
    conn.execute("UPDATE cheques SET statut=?,updated_at=? WHERE id=?",
                 (new_s, datetime.now().isoformat(), cheque_id))

def add_cheque(numero, montant, date_emission, beneficiaire,
               banque="", notes="", date_echeance="", user_id=1):
    conn = get_connection()
    try:
        conn.execute("""INSERT INTO cheques
            (numero,montant_initial,montant_restant,date_emission,date_echeance,
             beneficiaire,banque,notes,created_by)
            VALUES (?,?,?,?,?,?,?,?,?)""",
            (numero,montant,montant,date_emission,date_echeance,
             beneficiaire,banque,notes,user_id))
        ch_id = conn.execute("SELECT id FROM cheques WHERE numero=?",(numero,)).fetchone()["id"]
        conn.execute("""INSERT INTO transactions
            (type,montant,designation,cheque_id,date_transaction,created_by)
            VALUES ('entree',?,?,?,?,?)""",
            (montant,f"Chèque #{numero} — {beneficiaire}",ch_id,date_emission,user_id))
        _log(conn,"ADD_CHEQUE",f"#{numero} {montant:,.0f} {get_devise()}",user_id)
        conn.commit(); return True,"Chèque ajouté."
    except sqlite3.IntegrityError:
        return False,"Numéro de chèque déjà existant."
    finally: conn.close()

def update_cheque(cheque_id, numero, montant, date_emission, beneficiaire,
                  banque, notes, date_echeance="", user_id=1):
    conn = get_connection()
    try:
        old = conn.execute("SELECT * FROM cheques WHERE id=?",(cheque_id,)).fetchone()
        if not old: return False,"Chèque introuvable."
        diff            = montant - old["montant_initial"]
        nouveau_restant = max(0.0, old["montant_restant"] + diff)
        conn.execute("""UPDATE cheques SET numero=?,montant_initial=?,montant_restant=?,
            date_emission=?,date_echeance=?,beneficiaire=?,banque=?,notes=?,updated_at=?
            WHERE id=?""",
            (numero,montant,nouveau_restant,date_emission,date_echeance,
             beneficiaire,banque,notes,datetime.now().isoformat(),cheque_id))
        conn.execute("""UPDATE transactions SET montant=?,designation=?,date_transaction=?
            WHERE cheque_id=? AND type='entree'""",
            (montant,f"Chèque #{numero} — {beneficiaire}",date_emission,cheque_id))
        _recalc_statut_cheque(conn, cheque_id)
        _log(conn,"EDIT_CHEQUE",f"#{numero} modifié",user_id)
        conn.commit(); return True,"Chèque modifié."
    except sqlite3.IntegrityError:
        return False,"Numéro déjà utilisé."
    finally: conn.close()

def encaisser_cheque(cheque_id, user_id=1):
    conn = get_connection()
    conn.execute("UPDATE cheques SET statut='encaisse',updated_at=? WHERE id=?",
                 (datetime.now().isoformat(),cheque_id))
    _log(conn,"ENCAISSE",f"cheque_id={cheque_id}",user_id)
    conn.commit(); conn.close()

def get_all_cheques(search="", statut="", sort_by="created_at", sort_dir="DESC"):
    allowed = {"numero","montant_initial","montant_restant","date_emission",
               "date_echeance","beneficiaire","banque","statut","created_at"}
    if sort_by not in allowed: sort_by="created_at"
    sort_dir = "ASC" if sort_dir=="ASC" else "DESC"
    conn   = get_connection()
    query  = "SELECT * FROM cheques WHERE 1=1"
    params = []
    if search:
        query  += " AND (numero LIKE ? OR beneficiaire LIKE ? OR banque LIKE ? OR notes LIKE ?)"
        params += [f"%{search}%"]*4
    if statut:
        query += " AND statut=?"; params.append(statut)
    query += f" ORDER BY {sort_by} {sort_dir}"
    rows = conn.execute(query,params).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_cheque_by_id(cheque_id):
    conn = get_connection()
    row  = conn.execute("SELECT * FROM cheques WHERE id=?",(cheque_id,)).fetchone()
    conn.close()
    return dict(row) if row else None

def get_cheque_transactions(cheque_id):
    conn = get_connection()
    rows = conn.execute("""
        SELECT t.*, c.nom as cat_nom, c.icone as cat_icone
        FROM transactions t
        LEFT JOIN categories c ON t.categorie_id=c.id
        WHERE t.cheque_id=?
        ORDER BY t.date_transaction ASC, t.created_at ASC
    """,(cheque_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_cheques_alertes():
    seuil = get_seuil_alerte()
    conn  = get_connection()
    rows  = conn.execute("""SELECT * FROM cheques
        WHERE statut NOT IN ('cloture','encaisse') AND montant_initial>0
        AND (montant_restant*1.0/montant_initial*100) < ?
        ORDER BY montant_restant ASC""",(seuil,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_cheques_echus():
    """Chèques dont la date d'échéance est dépassée et pas encore clôturés/encaissés."""
    today = date.today().isoformat()
    conn  = get_connection()
    rows  = conn.execute("""SELECT * FROM cheques
        WHERE date_echeance != '' AND date_echeance < ?
        AND statut NOT IN ('cloture','encaisse')
        ORDER BY date_echeance ASC""",(today,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def depense_sur_cheque(cheque_id, montant, designation, categorie_id,
                       date_t, notes="", piece_jointe="", user_id=1):
    conn   = get_connection()
    cheque = conn.execute("SELECT * FROM cheques WHERE id=?",(cheque_id,)).fetchone()
    if not cheque:
        conn.close(); return False,"Chèque introuvable."
    if montant > cheque["montant_restant"]:
        conn.close()
        return False,f"Dépasse le restant ({cheque['montant_restant']:,.0f} {get_devise()})."
    nouveau_restant = cheque["montant_restant"] - montant
    conn.execute("UPDATE cheques SET montant_restant=?,updated_at=? WHERE id=?",
                 (nouveau_restant, datetime.now().isoformat(), cheque_id))
    _recalc_statut_cheque(conn, cheque_id)
    conn.execute("""INSERT INTO transactions
        (type,montant,designation,categorie_id,cheque_id,date_transaction,notes,piece_jointe,created_by)
        VALUES ('sortie',?,?,?,?,?,?,?,?)""",
        (montant,designation,categorie_id,cheque_id,date_t,notes,piece_jointe,user_id))
    _log(conn,"DEPENSE",f"#{cheque['numero']} -{montant:,.0f}",user_id)
    conn.commit(); conn.close()
    return True,"Dépense enregistrée."

def depense_multi_cheques(repartition, designation, categorie_id,
                          date_t, notes="", piece_jointe="", user_id=1):
    """
    Répartit une dépense sur plusieurs chèques.
    repartition = [(cheque_id, montant), ...]
    Retourne (True, "ok") ou (False, message_erreur)
    """
    conn = get_connection()
    try:
        for cheque_id, montant in repartition:
            cheque = conn.execute("SELECT * FROM cheques WHERE id=?",(cheque_id,)).fetchone()
            if not cheque:
                return False,f"Chèque #{cheque_id} introuvable."
            if montant > cheque["montant_restant"]:
                return False,(f"Montant ({montant:,.0f}) dépasse le restant "
                              f"du chèque #{cheque['numero']} "
                              f"({cheque['montant_restant']:,.0f}).")
            nouveau_restant = cheque["montant_restant"] - montant
            conn.execute("UPDATE cheques SET montant_restant=?,updated_at=? WHERE id=?",
                         (nouveau_restant, datetime.now().isoformat(), cheque_id))
            _recalc_statut_cheque(conn, cheque_id)
            conn.execute("""INSERT INTO transactions
                (type,montant,designation,categorie_id,cheque_id,
                 date_transaction,notes,piece_jointe,created_by)
                VALUES ('sortie',?,?,?,?,?,?,?,?)""",
                (montant, f"{designation} [chèque #{cheque['numero']}]",
                 categorie_id, cheque_id, date_t, notes, piece_jointe, user_id))
            _log(conn,"DEPENSE_MULTI",f"#{cheque['numero']} -{montant:,.0f}",user_id)
        conn.commit()
        return True, f"Dépense répartie sur {len(repartition)} chèque(s)."
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()

def delete_cheque(cheque_id):
    conn = get_connection()
    conn.execute("DELETE FROM transactions WHERE cheque_id=?",(cheque_id,))
    conn.execute("DELETE FROM cheques WHERE id=?",(cheque_id,))
    conn.commit(); conn.close()


# ── Transactions ──────────────────────────────────────────────────────────────
def add_transaction(type_, montant, designation, categorie_id, date_t,
                    reference="", notes="", piece_jointe="", user_id=1):
    conn = get_connection()
    conn.execute("""INSERT INTO transactions
        (type,montant,designation,categorie_id,date_transaction,
         reference,notes,piece_jointe,created_by)
        VALUES (?,?,?,?,?,?,?,?,?)""",
        (type_,montant,designation,categorie_id,date_t,
         reference,notes,piece_jointe,user_id))
    _log(conn,f"ADD_{type_.upper()}",f"{designation[:30]} {montant:,.0f}",user_id)
    conn.commit(); conn.close()

def update_transaction(tid, montant, designation, categorie_id,
                       date_t, reference, notes, piece_jointe=""):
    """
    Corrigé v5 : recalcule montant_restant du chèque lié si c'est une dépense.
    """
    conn = get_connection()
    old  = conn.execute("SELECT * FROM transactions WHERE id=?",(tid,)).fetchone()
    if not old:
        conn.close(); return False,"Transaction introuvable."

    # Si la transaction est liée à un chèque ET c'est une dépense
    if old["cheque_id"] and old["type"] == "sortie":
        ancien_montant  = old["montant"]
        diff            = montant - ancien_montant
        # diff > 0 = on dépense plus → montant_restant diminue
        # diff < 0 = on dépense moins → montant_restant augmente
        ch = conn.execute("SELECT * FROM cheques WHERE id=?",(old["cheque_id"],)).fetchone()
        if ch:
            nouveau_restant = ch["montant_restant"] - diff
            if nouveau_restant < 0:
                conn.close()
                return False,(f"Montant dépasse le restant disponible "
                              f"({ch['montant_restant']+ancien_montant:,.0f} {get_devise()}).")
            conn.execute(
                "UPDATE cheques SET montant_restant=?,updated_at=? WHERE id=?",
                (nouveau_restant, datetime.now().isoformat(), old["cheque_id"]))
            _recalc_statut_cheque(conn, old["cheque_id"])

    # Si la transaction d'entrée initiale d'un chèque est modifiée
    elif old["cheque_id"] and old["type"] == "entree":
        ancien_montant = old["montant"]
        diff           = montant - ancien_montant
        ch = conn.execute("SELECT * FROM cheques WHERE id=?",(old["cheque_id"],)).fetchone()
        if ch:
            # Ajuste montant_initial et montant_restant proportionnellement
            nouveau_initial  = ch["montant_initial"] + diff
            nouveau_restant  = max(0.0, ch["montant_restant"] + diff)
            conn.execute("""UPDATE cheques SET montant_initial=?,montant_restant=?,
                updated_at=? WHERE id=?""",
                (nouveau_initial, nouveau_restant,
                 datetime.now().isoformat(), old["cheque_id"]))
            _recalc_statut_cheque(conn, old["cheque_id"])

    conn.execute("""UPDATE transactions SET montant=?,designation=?,categorie_id=?,
        date_transaction=?,reference=?,notes=?,piece_jointe=? WHERE id=?""",
        (montant,designation,categorie_id,date_t,reference,notes,piece_jointe,tid))
    conn.commit(); conn.close()
    return True,"Transaction modifiée."

def delete_transaction(tid):
    conn = get_connection()
    row  = conn.execute("SELECT * FROM transactions WHERE id=?",(tid,)).fetchone()
    if not row:
        conn.close(); return False,"Transaction introuvable."

    # Bloquer la suppression de la transaction d'entrée initiale d'un chèque
    if row["cheque_id"] and row["type"] == "entree":
        conn.close()
        return False,("Impossible de supprimer l'entrée initiale d'un chèque. "
                      "Supprimez le chèque entier via la page Chèques.")

    # Restaurer le montant_restant si c'est une dépense liée à un chèque
    if row["cheque_id"] and row["type"] == "sortie":
        ch = conn.execute("SELECT * FROM cheques WHERE id=?",(row["cheque_id"],)).fetchone()
        if ch:
            nouveau_restant = ch["montant_restant"] + row["montant"]
            # Plafonner à montant_initial (sécurité)
            nouveau_restant = min(nouveau_restant, ch["montant_initial"])
            conn.execute(
                "UPDATE cheques SET montant_restant=?,updated_at=? WHERE id=?",
                (nouveau_restant, datetime.now().isoformat(), row["cheque_id"]))
            _recalc_statut_cheque(conn, row["cheque_id"])

    conn.execute("DELETE FROM transactions WHERE id=?",(tid,))
    conn.commit(); conn.close()
    return True,"Transaction supprimée."

def get_transactions(date_debut="", date_fin="", categorie_id=None, type_=None,
                     search="", sort_by="date_transaction", sort_dir="DESC"):
    allowed = {"date_transaction","montant","designation","type","created_at"}
    if sort_by not in allowed: sort_by="date_transaction"
    sort_dir = "ASC" if sort_dir=="ASC" else "DESC"
    conn  = get_connection()
    query = """SELECT t.*, c.nom as cat_nom, c.couleur as cat_couleur, c.icone as cat_icone,
               ch.numero as cheque_num
        FROM transactions t
        LEFT JOIN categories c ON t.categorie_id=c.id
        LEFT JOIN cheques ch ON t.cheque_id=ch.id WHERE 1=1"""
    params = []
    if date_debut: query+=" AND t.date_transaction>=?"; params.append(date_debut)
    if date_fin:   query+=" AND t.date_transaction<=?"; params.append(date_fin)
    if categorie_id: query+=" AND t.categorie_id=?";   params.append(categorie_id)
    if type_:      query+=" AND t.type=?";             params.append(type_)
    if search:
        query+=" AND (t.designation LIKE ? OR t.reference LIKE ? OR t.notes LIKE ? OR ch.numero LIKE ?)"
        params+=[f"%{search}%"]*4
    query+=f" ORDER BY t.{sort_by} {sort_dir}, t.id DESC"
    rows = conn.execute(query,params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Solde & Stats ─────────────────────────────────────────────────────────────
def get_solde_caisse():
    conn    = get_connection()
    entrees = conn.execute("SELECT COALESCE(SUM(montant),0) FROM transactions WHERE type='entree'").fetchone()[0]
    sorties = conn.execute("SELECT COALESCE(SUM(montant),0) FROM transactions WHERE type='sortie'").fetchone()[0]
    conn.close()
    s_ouv = float(get_parametre("solde_ouverture","0"))
    return (entrees-sorties+s_ouv), entrees, sorties, s_ouv

def get_solde_periode(date_debut="", date_fin=""):
    conn = get_connection()
    q    = "SELECT type, COALESCE(SUM(montant),0) as total FROM transactions WHERE 1=1"
    p    = []
    if date_debut: q+=" AND date_transaction>=?"; p.append(date_debut)
    if date_fin:   q+=" AND date_transaction<=?"; p.append(date_fin)
    q += " GROUP BY type"
    rows = {r["type"]:r["total"] for r in conn.execute(q,p).fetchall()}
    conn.close()
    ent = rows.get("entree",0); sor = rows.get("sortie",0)
    return ent-sor, ent, sor

def get_stats_categories(date_debut="", date_fin=""):
    conn = get_connection()
    q    = """SELECT c.nom,c.couleur,c.icone,SUM(t.montant) as total
        FROM transactions t JOIN categories c ON t.categorie_id=c.id
        WHERE t.type='sortie'"""
    p    = []
    if date_debut: q+=" AND t.date_transaction>=?"; p.append(date_debut)
    if date_fin:   q+=" AND t.date_transaction<=?"; p.append(date_fin)
    q += " GROUP BY c.id ORDER BY total DESC"
    rows = conn.execute(q,p).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_evolution_solde(nb_jours=30):
    conn = get_connection()
    rows = conn.execute("""SELECT date_transaction as date,
        SUM(CASE WHEN type='entree' THEN montant ELSE -montant END) as delta
        FROM transactions WHERE date_transaction >= date('now',?)
        GROUP BY date_transaction ORDER BY date_transaction""",
        (f"-{nb_jours} days",)).fetchall()
    conn.close()
    s_ouv  = float(get_parametre("solde_ouverture","0"))
    dates, soldes, cumul = [], [], s_ouv
    for r in rows:
        cumul+=r["delta"]; dates.append(r["date"]); soldes.append(cumul)
    return dates, soldes

def get_stats_mensuelles(annee=None):
    annee = annee or date.today().year
    conn  = get_connection()
    rows  = conn.execute("""SELECT strftime('%m',date_transaction) as mois,
        SUM(CASE WHEN type='entree' THEN montant ELSE 0 END) as entrees,
        SUM(CASE WHEN type='sortie' THEN montant ELSE 0 END) as sorties
        FROM transactions WHERE strftime('%Y',date_transaction)=?
        GROUP BY mois ORDER BY mois""",
        (str(annee),)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_top_depenses(limit=5, date_debut="", date_fin=""):
    conn = get_connection()
    q    = """SELECT designation, SUM(montant) as total, COUNT(*) as nb
        FROM transactions WHERE type='sortie'"""
    p    = []
    if date_debut: q+=" AND date_transaction>=?"; p.append(date_debut)
    if date_fin:   q+=" AND date_transaction<=?"; p.append(date_fin)
    q   += " GROUP BY designation ORDER BY total DESC LIMIT ?"
    p.append(limit)
    rows = conn.execute(q,p).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def recherche_globale(terme):
    conn    = get_connection()
    ch_rows = conn.execute("""SELECT * FROM cheques
        WHERE numero LIKE ? OR beneficiaire LIKE ? OR banque LIKE ? OR notes LIKE ?""",
        [f"%{terme}%"]*4).fetchall()
    tr_rows = conn.execute("""SELECT t.*, c.nom as cat_nom, c.icone as cat_icone,
        ch.numero as cheque_num
        FROM transactions t
        LEFT JOIN categories c ON t.categorie_id=c.id
        LEFT JOIN cheques ch ON t.cheque_id=ch.id
        WHERE t.designation LIKE ? OR t.reference LIKE ? OR t.notes LIKE ? OR ch.numero LIKE ?""",
        [f"%{terme}%"]*4).fetchall()
    conn.close()
    return [dict(r) for r in ch_rows], [dict(r) for r in tr_rows]

def get_historique(limit=300):
    conn = get_connection()
    rows = conn.execute("""SELECT h.*,u.nom as user_nom FROM historique h
        LEFT JOIN utilisateurs u ON h.user_id=u.id
        ORDER BY h.created_at DESC LIMIT ?""",(limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def _log(conn, action, detail="", user_id=1):
    conn.execute("INSERT INTO historique (action,detail,user_id) VALUES (?,?,?)",
                 (action,detail,user_id))


# ── Budget mensuel ─────────────────────────────────────────────────────────────
def get_budgets(annee, mois):
    conn = get_connection()
    rows = conn.execute("""
        SELECT b.*, c.nom as cat_nom, c.icone as cat_icone, c.couleur as cat_couleur,
               COALESCE((SELECT SUM(t.montant) FROM transactions t
                         WHERE t.categorie_id=b.categorie_id AND t.type='sortie'
                         AND strftime('%Y',t.date_transaction)=?
                         AND strftime('%m',t.date_transaction)=?),0) as depense
        FROM budgets b JOIN categories c ON b.categorie_id=c.id
        WHERE b.annee=? AND b.mois=?
        ORDER BY c.nom""",
        (str(annee), f"{mois:02d}", annee, mois)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def set_budget(categorie_id, annee, mois, montant):
    conn = get_connection()
    conn.execute("""INSERT OR REPLACE INTO budgets (categorie_id,annee,mois,montant)
        VALUES (?,?,?,?)""",(categorie_id,annee,mois,montant))
    conn.commit(); conn.close()

def delete_budget(categorie_id, annee, mois):
    conn = get_connection()
    conn.execute("DELETE FROM budgets WHERE categorie_id=? AND annee=? AND mois=?",
                 (categorie_id,annee,mois))
    conn.commit(); conn.close()


# ── Sauvegarde ────────────────────────────────────────────────────────────────
def backup_db():
    os.makedirs(BACKUP_DIR, exist_ok=True)
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = os.path.join(BACKUP_DIR, f"caisse_gestion_{ts}.db")
    shutil.copy2(DB_PATH, dest)
    backups = sorted([f for f in os.listdir(BACKUP_DIR) if f.endswith(".db")])
    for old in backups[:-10]:
        os.remove(os.path.join(BACKUP_DIR, old))
    return dest

def get_backups():
    if not os.path.exists(BACKUP_DIR): return []
    return sorted([f for f in os.listdir(BACKUP_DIR) if f.endswith(".db")],reverse=True)

def restore_backup(filename):
    src = os.path.join(BACKUP_DIR, filename)
    if not os.path.exists(src): return False,"Fichier introuvable."
    backup_db(); shutil.copy2(src, DB_PATH)
    _PARAM_CACHE.clear()
    return True,"Base restaurée."

def reset_all_data(user_id=1):
    conn = get_connection()
    conn.execute("DELETE FROM transactions")
    conn.execute("DELETE FROM cheques")
    conn.execute("DELETE FROM historique")
    _log(conn,"RESET","Réinitialisation complète",user_id)
    conn.commit(); conn.close()

# ── Pièce jointe ──────────────────────────────────────────────────────────────
def save_piece_jointe(src_path):
    """Copie un fichier dans pieces_jointes/ et retourne le nom de fichier."""
    os.makedirs(ATTACH_DIR, exist_ok=True)
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    ext  = os.path.splitext(src_path)[1]
    name = f"pj_{ts}{ext}"
    shutil.copy2(src_path, os.path.join(ATTACH_DIR, name))
    return name

def get_piece_jointe_path(filename):
    if not filename: return None
    p = os.path.join(ATTACH_DIR, filename)
    return p if os.path.exists(p) else None


# ── En-tête PDF helper ────────────────────────────────────────────────────────
def _get_entete():
    return {
        "societe":   get_parametre("societe",""),
        "adresse":   get_parametre("adresse",""),
        "telephone": get_parametre("telephone",""),
        "logo":      get_parametre("logo_path",""),
        "devise":    get_devise(),
    }

def _pdf_entete(story, styles, entete):
    """Ajoute l'en-tête standard en haut d'un rapport PDF."""
    try:
        from reportlab.platypus import Table, TableStyle, Image, Spacer, Paragraph
        from reportlab.lib import colors
        from reportlab.lib.units import cm
        logo_w = 0
        logo_cell = ""
        if entete["logo"] and os.path.exists(entete["logo"]):
            try:
                logo_cell = Image(entete["logo"], width=3*cm, height=2*cm)
                logo_w = 1
            except: pass
        soc_text = f"<b>{entete['societe']}</b>"
        if entete["adresse"]:   soc_text += f"<br/>{entete['adresse']}"
        if entete["telephone"]: soc_text += f"<br/>Tél: {entete['telephone']}"
        soc_p = Paragraph(soc_text, styles["Normal"])
        data  = [[logo_cell, soc_p]] if logo_w else [[soc_p]]
        t = Table(data, colWidths=[3*cm, 14*cm] if logo_w else [17*cm])
        t.setStyle(TableStyle([
            ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
            ("LINEBELOW",(0,0),(-1,-1),1,colors.HexColor("#1A2744")),
            ("PADDING",(0,0),(-1,-1),6),
        ]))
        story.append(t)
        story.append(Spacer(1,0.4*cm))
    except: pass


# ── Export Excel ──────────────────────────────────────────────────────────────
def export_to_excel(filepath, date_debut="", date_fin=""):
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter
    e    = _get_entete()
    wb   = openpyxl.Workbook()

    def hdr(cell, val):
        cell.value=val
        cell.font=Font(bold=True,color="FFFFFF")
        cell.fill=PatternFill("solid",fgColor="1A2744")
        cell.alignment=Alignment(horizontal="center")

    # Transactions
    ws1=wb.active; ws1.title="Transactions"
    for col,h in enumerate(["Date","Type","Désignation","Catégorie","Chèque",
                             f"Montant ({e['devise']})",f"Solde ({e['devise']})","Réf.","Notes"],1):
        hdr(ws1.cell(1,col),h)
    solde_c = float(get_parametre("solde_ouverture","0"))
    for i,t in enumerate(get_transactions(date_debut,date_fin,sort_dir="ASC"),2):
        delta    = t["montant"] if t["type"]=="entree" else -t["montant"]
        solde_c += delta
        ws1.cell(i,1,t["date_transaction"])
        ws1.cell(i,2,"Entrée" if t["type"]=="entree" else "Sortie")
        ws1.cell(i,3,t["designation"])
        ws1.cell(i,4,t.get("cat_nom","") or "")
        ws1.cell(i,5,t.get("cheque_num","") or "")
        mc=ws1.cell(i,6,t["montant"]); mc.number_format=f'#,##0.00 "{e["devise"]}"'
        mc.font=Font(color="3DD68C" if t["type"]=="entree" else "F75F5F",bold=True)
        sc=ws1.cell(i,7,round(solde_c,2)); sc.number_format=f'#,##0.00 "{e["devise"]}"'
        ws1.cell(i,8,t.get("reference",""))
        ws1.cell(i,9,t.get("notes",""))
    for col in range(1,10): ws1.column_dimensions[get_column_letter(col)].width=22

    # Chèques
    ws2=wb.create_sheet("Chèques")
    for col,h in enumerate(["Numéro","Bénéficiaire","Banque","Initial","Restant",
                             "Date émission","Échéance","Statut","Notes"],1):
        hdr(ws2.cell(1,col),h)
    sl={"en_attente":"En attente","encaisse":"Encaissé",
        "partiellement_utilise":"Partiel","cloture":"Clôturé"}
    for i,ch in enumerate(get_all_cheques(),2):
        ws2.cell(i,1,ch["numero"]); ws2.cell(i,2,ch["beneficiaire"]); ws2.cell(i,3,ch.get("banque",""))
        ws2.cell(i,4,ch["montant_initial"]).number_format=f'#,##0.00 "{e["devise"]}"'
        ws2.cell(i,5,ch["montant_restant"]).number_format=f'#,##0.00 "{e["devise"]}"'
        ws2.cell(i,6,ch["date_emission"])
        ws2.cell(i,7,ch.get("date_echeance","") or "")
        ws2.cell(i,8,sl.get(ch["statut"],ch["statut"]))
        ws2.cell(i,9,ch.get("notes",""))
    for col in range(1,10): ws2.column_dimensions[get_column_letter(col)].width=22

    # Stats mensuelles
    ws3=wb.create_sheet("Stats mensuelles")
    for col,h in enumerate(["Mois","Entrées","Sorties","Solde mois"],1):
        hdr(ws3.cell(1,col),h)
    mois_noms=["Jan","Fév","Mar","Avr","Mai","Jun","Jul","Aoû","Sep","Oct","Nov","Déc"]
    for i,s in enumerate(get_stats_mensuelles(),2):
        ws3.cell(i,1,mois_noms[int(s["mois"])-1])
        ws3.cell(i,2,s["entrees"]).number_format=f'#,##0.00 "{e["devise"]}"'
        ws3.cell(i,3,s["sorties"]).number_format=f'#,##0.00 "{e["devise"]}"'
        ws3.cell(i,4,s["entrees"]-s["sorties"]).number_format=f'#,##0.00 "{e["devise"]}"'
    for col in range(1,5): ws3.column_dimensions[get_column_letter(col)].width=20

    # Résumé
    ws4=wb.create_sheet("Résumé")
    solde,entrees,sorties,s_ouv=get_solde_caisse()
    ws4["A1"]=f"Résumé Financier — {e['societe']}"
    ws4["A1"].font=Font(bold=True,size=16,color="1A2744")
    ws4["A3"]="Généré le"; ws4["B3"]=datetime.now().strftime("%d/%m/%Y %H:%M")
    if date_debut or date_fin:
        ws4["A4"]="Période"; ws4["B4"]=f"{date_debut or '…'} → {date_fin or '…'}"
    ws4["A5"]="Solde ouverture"; ws4["B5"]=s_ouv
    ws4["A6"]="Total Entrées";   ws4["B6"]=entrees; ws4["B6"].font=Font(color="3DD68C",bold=True)
    ws4["A7"]="Total Sorties";   ws4["B7"]=sorties; ws4["B7"].font=Font(color="F75F5F",bold=True)
    ws4["A8"]="Solde Actuel";    ws4["B8"]=solde;   ws4["B8"].font=Font(bold=True,size=14)
    for col in ["A","B"]: ws4.column_dimensions[col].width=26
    wb.save(filepath)


# ── Export PDF général ────────────────────────────────────────────────────────
def export_to_pdf(filepath, date_debut="", date_fin=""):
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle,
                                         Paragraph, Spacer, HRFlowable)
        from reportlab.lib.units import cm
    except ImportError:
        return False,"reportlab non installé. Faites : pip install reportlab"

    e       = _get_entete()
    solde, entrees, sorties, s_ouv = get_solde_caisse()
    doc     = SimpleDocTemplate(filepath, pagesize=A4,
                                 leftMargin=1.5*cm, rightMargin=1.5*cm,
                                 topMargin=1.5*cm, bottomMargin=1.5*cm)
    styles  = getSampleStyleSheet()
    story   = []

    _pdf_entete(story, styles, e)
    story.append(Paragraph(f"<b>Rapport Financier</b>",styles["Title"]))
    story.append(Paragraph(f"Généré le {datetime.now().strftime('%d/%m/%Y à %H:%M')}",styles["Normal"]))
    if date_debut or date_fin:
        story.append(Paragraph(f"Période : {date_debut or '…'} → {date_fin or '…'}",styles["Normal"]))
    story.append(Spacer(1,0.4*cm))

    resume=[["Solde ouverture",f"{s_ouv:,.0f} {e['devise']}"],
            ["Total Entrées",  f"{entrees:,.0f} {e['devise']}"],
            ["Total Sorties",  f"{sorties:,.0f} {e['devise']}"],
            ["Solde Actuel",   f"{solde:,.0f} {e['devise']}"]]
    t_r=Table(resume,colWidths=[8*cm,8*cm])
    t_r.setStyle(TableStyle([
        ("ROWBACKGROUNDS",(0,0),(-1,-1),[colors.HexColor("#EEF2FF"),colors.white]),
        ("FONTNAME",(0,0),(-1,-1),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,-1),11),
        ("ALIGN",(1,0),(1,-1),"RIGHT"),("PADDING",(0,0),(-1,-1),8),
        ("GRID",(0,0),(-1,-1),0.5,colors.HexColor("#CCCCCC")),
    ]))
    story.append(t_r); story.append(Spacer(1,0.6*cm))

    story.append(Paragraph("<b>Transactions</b>",styles["Heading2"]))
    from reportlab.platypus import Paragraph as P
    small=styles["Normal"].clone("small"); small.fontSize=7.5; small.leading=10
    tr_data=[["Date","Type","Désignation","Catégorie",f"Montant",f"Solde"]]
    solde_c=s_ouv
    for t in get_transactions(date_debut,date_fin,sort_dir="ASC"):
        delta=t["montant"] if t["type"]=="entree" else -t["montant"]
        solde_c+=delta
        tr_data.append([t["date_transaction"],
                        "Entrée" if t["type"]=="entree" else "Sortie",
                        P(t["designation"],small),
                        t.get("cat_nom","") or "",
                        f"{t['montant']:,.0f}", f"{solde_c:,.0f}"])
    t_tr=Table(tr_data,colWidths=[2.2*cm,1.8*cm,5.5*cm,3*cm,2.5*cm,2.5*cm])
    t_tr.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#1A2744")),
        ("TEXTCOLOR",(0,0),(-1,0),colors.white),
        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.HexColor("#F5F5F5"),colors.white]),
        ("FONTSIZE",(0,0),(-1,-1),8),
        ("ALIGN",(4,0),(5,-1),"RIGHT"),
        ("GRID",(0,0),(-1,-1),0.3,colors.HexColor("#DDDDDD")),
        ("PADDING",(0,0),(-1,-1),5),
    ]))
    story.append(t_tr); story.append(Spacer(1,0.6*cm))

    story.append(Paragraph("<b>Chèques</b>",styles["Heading2"]))
    sl={"en_attente":"En attente","encaisse":"Encaissé",
        "partiellement_utilise":"Partiel","cloture":"Clôturé"}
    ch_data=[["Numéro","Bénéficiaire","Initial","Restant","Échéance","Statut"]]
    for ch in get_all_cheques():
        ch_data.append([ch["numero"],ch["beneficiaire"],
                        f"{ch['montant_initial']:,.0f}",f"{ch['montant_restant']:,.0f}",
                        ch.get("date_echeance","") or "—",
                        sl.get(ch["statut"],ch["statut"])])
    t_ch=Table(ch_data,colWidths=[2.5*cm,4.5*cm,2.8*cm,2.8*cm,2.5*cm,3*cm])
    t_ch.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#1A2744")),
        ("TEXTCOLOR",(0,0),(-1,0),colors.white),
        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.HexColor("#F5F5F5"),colors.white]),
        ("FONTSIZE",(0,0),(-1,-1),8),
        ("ALIGN",(2,0),(3,-1),"RIGHT"),
        ("GRID",(0,0),(-1,-1),0.3,colors.HexColor("#DDDDDD")),
        ("PADDING",(0,0),(-1,-1),5),
    ]))
    story.append(t_ch)
    doc.build(story)
    return True,"PDF exporté."


# ── Export chèque individuel PDF ───────────────────────────────────────────────
def export_cheque_pdf(filepath, cheque_id):
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle,
                                         Paragraph, Spacer, Image)
        from reportlab.lib.units import cm
    except ImportError:
        return False,"reportlab non installé."

    ch = get_cheque_by_id(cheque_id)
    if not ch: return False,"Chèque introuvable."
    e      = _get_entete()
    sl     = {"en_attente":"En attente","encaisse":"Encaissé",
              "partiellement_utilise":"Partiellement utilisé","cloture":"Clôturé"}
    doc    = SimpleDocTemplate(filepath,pagesize=A4,
                                leftMargin=1.5*cm,rightMargin=1.5*cm,
                                topMargin=1.5*cm,bottomMargin=1.5*cm)
    styles = getSampleStyleSheet()
    story  = []
    _pdf_entete(story,styles,e)

    from xml.sax.saxutils import escape as _esc
    banque = (ch.get("banque","") or "").strip()
    titre  = f"Fiche Chèque #{_esc(str(ch['numero']))}"
    if banque:
        titre += f" — {_esc(banque)}"
    story.append(Paragraph(f"<b>{titre}</b>",styles["Title"]))
    story.append(Spacer(1,0.3*cm))

    info=[
        ["Numéro",          ch["numero"]],
        ["Bénéficiaire",    ch["beneficiaire"]],
        ["Banque",          ch.get("banque","") or "—"],
        ["Date émission",   ch["date_emission"]],
        ["Date échéance",   ch.get("date_echeance","") or "—"],
        ["Montant initial", f"{ch['montant_initial']:,.0f} {e['devise']}"],
        ["Montant restant", f"{ch['montant_restant']:,.0f} {e['devise']}"],
        ["Utilisé",         f"{ch['montant_initial']-ch['montant_restant']:,.0f} {e['devise']}"],
        ["Statut",          sl.get(ch["statut"],ch["statut"])],
        ["Notes",           ch.get("notes","") or "—"],
    ]
    t_i=Table(info,colWidths=[5*cm,12*cm])
    t_i.setStyle(TableStyle([
        ("ROWBACKGROUNDS",(0,0),(-1,-1),[colors.HexColor("#EEF2FF"),colors.white]),
        ("FONTNAME",(0,0),(0,-1),"Helvetica-Bold"),
        ("FONTSIZE",(0,0),(-1,-1),10),
        ("PADDING",(0,0),(-1,-1),8),
        ("GRID",(0,0),(-1,-1),0.4,colors.HexColor("#CCCCCC")),
    ]))

    # QR code à côté de la table (si disponible)
    qr_path = generer_qrcode_cheque(ch)
    if qr_path and os.path.exists(qr_path):
        qr_img = Image(qr_path, width=3.2*cm, height=3.2*cm)
        side_by_side = Table([[t_i, qr_img]], colWidths=[17*cm-3.5*cm, 3.5*cm])
        side_by_side.setStyle(TableStyle([
            ("VALIGN",(0,0),(-1,-1),"TOP"),
            ("ALIGN",(1,0),(1,0),"CENTER"),
        ]))
        story.append(side_by_side)
    else:
        story.append(t_i)
    story.append(Spacer(1,0.6*cm))

    story.append(Paragraph("<b>Historique des transactions</b>",styles["Heading2"]))
    trs = get_cheque_transactions(cheque_id)
    from reportlab.platypus import Paragraph as P
    small=styles["Normal"].clone("small"); small.fontSize=8; small.leading=11
    tr_data=[["Date","Type","Désignation","Catégorie","Montant"]]
    for t in trs:
        tr_data.append([
            t["date_transaction"],
            "Entrée" if t["type"]=="entree" else "Dépense",
            P(t["designation"], small),
            t.get("cat_nom","") or "—",
            f"{t['montant']:,.0f} {e['devise']}",
        ])
    t_tr=Table(tr_data,colWidths=[2.5*cm,2*cm,6*cm,3*cm,3*cm])
    t_tr.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#1A2744")),
        ("TEXTCOLOR",(0,0),(-1,0),colors.white),
        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.HexColor("#F5F5F5"),colors.white]),
        ("FONTSIZE",(0,0),(-1,-1),9),
        ("ALIGN",(4,0),(4,-1),"RIGHT"),
        ("GRID",(0,0),(-1,-1),0.3,colors.HexColor("#DDDDDD")),
        ("PADDING",(0,0),(-1,-1),6),
    ]))
    story.append(t_tr)
    doc.build(story)
    return True,f"PDF chèque #{ch['numero']} exporté."


# ── Rapport mensuel PDF ────────────────────────────────────────────────────────
def export_rapport_mensuel_pdf(filepath, annee, mois):
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle,
                                         Paragraph, Spacer)
        from reportlab.lib.units import cm
    except ImportError:
        return False,"reportlab non installé."

    e       = _get_entete()
    mois_noms=["Janvier","Février","Mars","Avril","Mai","Juin",
               "Juillet","Août","Septembre","Octobre","Novembre","Décembre"]
    label   = f"{mois_noms[mois-1]} {annee}"
    dd      = f"{annee}-{mois:02d}-01"
    import calendar
    df      = f"{annee}-{mois:02d}-{calendar.monthrange(annee,mois)[1]:02d}"

    doc    = SimpleDocTemplate(filepath,pagesize=A4,
                                leftMargin=1.5*cm,rightMargin=1.5*cm,
                                topMargin=1.5*cm,bottomMargin=1.5*cm)
    styles = getSampleStyleSheet()
    story  = []
    _pdf_entete(story,styles,e)

    story.append(Paragraph(f"<b>Rapport Mensuel — {label}</b>",styles["Title"]))
    story.append(Paragraph(f"Généré le {datetime.now().strftime('%d/%m/%Y à %H:%M')}",styles["Normal"]))
    story.append(Spacer(1,0.4*cm))

    solde, ent, sor = get_solde_periode(dd, df)
    resume=[["Total Entrées",f"{ent:,.0f} {e['devise']}"],
            ["Total Sorties",f"{sor:,.0f} {e['devise']}"],
            ["Solde du mois",f"{solde:,.0f} {e['devise']}"]]
    t_r=Table(resume,colWidths=[8*cm,8*cm])
    t_r.setStyle(TableStyle([
        ("ROWBACKGROUNDS",(0,0),(-1,-1),[colors.HexColor("#EEF2FF"),colors.white]),
        ("FONTNAME",(0,0),(-1,-1),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,-1),11),
        ("ALIGN",(1,0),(1,-1),"RIGHT"),("PADDING",(0,0),(-1,-1),8),
        ("GRID",(0,0),(-1,-1),0.5,colors.HexColor("#CCCCCC")),
    ]))
    story.append(t_r); story.append(Spacer(1,0.5*cm))

    story.append(Paragraph("<b>Dépenses par catégorie</b>",styles["Heading2"]))
    stats = get_stats_categories(dd,df)
    if stats:
        cat_data=[["Catégorie","Total","% du total"]]
        total_dep = sum(s["total"] for s in stats)
        for s in stats:
            pct = s["total"]/total_dep*100 if total_dep else 0
            cat_data.append([f"{s['icone']} {s['nom']}",
                             f"{s['total']:,.0f} {e['devise']}",
                             f"{pct:.1f}%"])
        t_c=Table(cat_data,colWidths=[8*cm,5*cm,4*cm])
        t_c.setStyle(TableStyle([
            ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#1A2744")),
            ("TEXTCOLOR",(0,0),(-1,0),colors.white),
            ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
            ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.HexColor("#F5F5F5"),colors.white]),
            ("FONTSIZE",(0,0),(-1,-1),9),
            ("ALIGN",(1,0),(2,-1),"RIGHT"),
            ("GRID",(0,0),(-1,-1),0.3,colors.HexColor("#DDDDDD")),
            ("PADDING",(0,0),(-1,-1),6),
        ]))
        story.append(t_c); story.append(Spacer(1,0.5*cm))

    story.append(Paragraph("<b>Détail des transactions</b>",styles["Heading2"]))
    trs = get_transactions(dd,df,sort_dir="ASC")
    from reportlab.platypus import Paragraph as P
    small=styles["Normal"].clone("small"); small.fontSize=7.5; small.leading=10
    tr_data=[["Date","Type","Désignation","Catégorie","Montant"]]
    for t in trs:
        tr_data.append([
            t["date_transaction"],
            "Entrée" if t["type"]=="entree" else "Sortie",
            P(t["designation"], small),
            t.get("cat_nom","") or "—",
            f"{t['montant']:,.0f}",
        ])
    t_t=Table(tr_data,colWidths=[2.5*cm,2*cm,6*cm,3.5*cm,3*cm])
    t_t.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#1A2744")),
        ("TEXTCOLOR",(0,0),(-1,0),colors.white),
        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.HexColor("#F5F5F5"),colors.white]),
        ("FONTSIZE",(0,0),(-1,-1),8),
        ("ALIGN",(4,0),(4,-1),"RIGHT"),
        ("GRID",(0,0),(-1,-1),0.3,colors.HexColor("#DDDDDD")),
        ("PADDING",(0,0),(-1,-1),5),
    ]))
    story.append(t_t)
    doc.build(story)
    return True,f"Rapport {label} exporté."


# ── Rapport catégories PDF ─────────────────────────────────────────────────────
def export_rapport_categories_pdf(filepath, date_debut="", date_fin=""):
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle,
                                         Paragraph, Spacer)
        from reportlab.lib.units import cm
    except ImportError:
        return False,"reportlab non installé."

    e      = _get_entete()
    doc    = SimpleDocTemplate(filepath,pagesize=A4,
                                leftMargin=1.5*cm,rightMargin=1.5*cm,
                                topMargin=1.5*cm,bottomMargin=1.5*cm)
    styles = getSampleStyleSheet()
    story  = []
    _pdf_entete(story,styles,e)

    periode = ""
    if date_debut or date_fin:
        periode = f" ({date_debut or '…'} → {date_fin or '…'})"
    story.append(Paragraph(f"<b>Rapport par Catégorie{periode}</b>",styles["Title"]))
    story.append(Paragraph(f"Généré le {datetime.now().strftime('%d/%m/%Y à %H:%M')}",styles["Normal"]))
    story.append(Spacer(1,0.5*cm))

    stats     = get_stats_categories(date_debut, date_fin)
    total_dep = sum(s["total"] for s in stats)
    data=[["Catégorie","Type","Total dépensé","% du total"]]
    for s in stats:
        pct = s["total"]/total_dep*100 if total_dep else 0
        data.append([f"{s['icone']} {s['nom']}","Sortie",
                     f"{s['total']:,.0f} {e['devise']}",f"{pct:.1f}%"])
    data.append(["TOTAL","",f"{total_dep:,.0f} {e['devise']}","100%"])

    t=Table(data,colWidths=[7*cm,3*cm,5*cm,3*cm])
    t.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#1A2744")),
        ("TEXTCOLOR",(0,0),(-1,0),colors.white),
        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
        ("FONTNAME",(0,-1),(-1,-1),"Helvetica-Bold"),
        ("BACKGROUND",(0,-1),(-1,-1),colors.HexColor("#EEF2FF")),
        ("ROWBACKGROUNDS",(0,1),(-1,-2),[colors.HexColor("#F5F5F5"),colors.white]),
        ("FONTSIZE",(0,0),(-1,-1),10),
        ("ALIGN",(2,0),(3,-1),"RIGHT"),
        ("GRID",(0,0),(-1,-1),0.3,colors.HexColor("#DDDDDD")),
        ("PADDING",(0,0),(-1,-1),7),
    ]))
    story.append(t)
    doc.build(story)
    return True,"Rapport catégories exporté."


# ── Rapport chèques PDF (filtrable par statut/période) ────────────────────────
def export_rapport_cheques_pdf(filepath, statut="", date_debut="", date_fin=""):
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle,
                                         Paragraph, Spacer)
        from reportlab.lib.units import cm
    except ImportError:
        return False,"reportlab non installé."

    e      = _get_entete()
    cheques= get_all_cheques(search="", statut=statut)
    # Filtre période sur date_emission
    if date_debut:
        cheques=[c for c in cheques if c["date_emission"]>=date_debut]
    if date_fin:
        cheques=[c for c in cheques if c["date_emission"]<=date_fin]

    sl={"en_attente":"En attente","encaisse":"Encaissé",
        "partiellement_utilise":"Partiel","cloture":"Clôturé"}
    doc    = SimpleDocTemplate(filepath,pagesize=A4,
                                leftMargin=1.5*cm,rightMargin=1.5*cm,
                                topMargin=1.5*cm,bottomMargin=1.5*cm)
    styles = getSampleStyleSheet()
    story  = []
    _pdf_entete(story,styles,e)

    filtre_txt=""
    if statut: filtre_txt+=f" | Statut : {sl.get(statut,statut)}"
    if date_debut or date_fin: filtre_txt+=f" | Période : {date_debut or '…'} → {date_fin or '…'}"
    story.append(Paragraph(f"<b>Rapport Chèques</b>",styles["Title"]))
    story.append(Paragraph(f"Généré le {datetime.now().strftime('%d/%m/%Y à %H:%M')}{filtre_txt}",
                           styles["Normal"]))
    story.append(Spacer(1,0.4*cm))

    # Résumé
    total_init  = sum(c["montant_initial"] for c in cheques)
    total_rest  = sum(c["montant_restant"]  for c in cheques)
    total_util  = total_init - total_rest
    resume=[
        ["Nombre de chèques",str(len(cheques))],
        ["Total initial",    f"{total_init:,.0f} {e['devise']}"],
        ["Total utilisé",    f"{total_util:,.0f} {e['devise']}"],
        ["Total restant",    f"{total_rest:,.0f} {e['devise']}"],
    ]
    t_r=Table(resume,colWidths=[8*cm,8*cm])
    t_r.setStyle(TableStyle([
        ("ROWBACKGROUNDS",(0,0),(-1,-1),[colors.HexColor("#EEF2FF"),colors.white]),
        ("FONTNAME",(0,0),(-1,-1),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,-1),11),
        ("ALIGN",(1,0),(1,-1),"RIGHT"),("PADDING",(0,0),(-1,-1),8),
        ("GRID",(0,0),(-1,-1),0.5,colors.HexColor("#CCCCCC")),
    ]))
    story.append(t_r); story.append(Spacer(1,0.5*cm))

    # Table chèques
    data=[["Numéro","Bénéficiaire","Banque","Initial","Restant","Émission","Échéance","Statut"]]
    for ch in cheques:
        data.append([
            ch["numero"], ch["beneficiaire"], ch.get("banque","") or "—",
            f"{ch['montant_initial']:,.0f}",f"{ch['montant_restant']:,.0f}",
            ch["date_emission"], ch.get("date_echeance","") or "—",
            sl.get(ch["statut"],ch["statut"]),
        ])
    t=Table(data,colWidths=[2.2*cm,3.8*cm,2.5*cm,2.5*cm,2.5*cm,2.2*cm,2.2*cm,2.2*cm])
    t.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#1A2744")),
        ("TEXTCOLOR",(0,0),(-1,0),colors.white),
        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.HexColor("#F5F5F5"),colors.white]),
        ("FONTSIZE",(0,0),(-1,-1),8),
        ("ALIGN",(3,0),(4,-1),"RIGHT"),
        ("GRID",(0,0),(-1,-1),0.3,colors.HexColor("#DDDDDD")),
        ("PADDING",(0,0),(-1,-1),5),
    ]))
    story.append(t)
    doc.build(story)
    return True,f"Rapport chèques exporté ({len(cheques)} chèque(s))."


# ── Export chèque individuel Excel ────────────────────────────────────────────
def export_cheque_excel(filepath, cheque_id):
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment
        from openpyxl.utils import get_column_letter
    except ImportError:
        return False,"openpyxl non installé."

    ch=get_cheque_by_id(cheque_id)
    if not ch: return False,"Chèque introuvable."
    e  =_get_entete()
    sl ={"en_attente":"En attente","encaisse":"Encaissé",
         "partiellement_utilise":"Partiellement utilisé","cloture":"Clôturé"}
    wb =openpyxl.Workbook()

    def hdr(cell,val):
        cell.value=val
        cell.font=Font(bold=True,color="FFFFFF")
        cell.fill=PatternFill("solid",fgColor="1A2744")
        cell.alignment=Alignment(horizontal="center")

    # Fiche chèque
    ws1=wb.active; ws1.title="Fiche chèque"
    ws1["A1"]=f"Fiche Chèque — {e['societe']}"
    ws1["A1"].font=Font(bold=True,size=14,color="1A2744")
    ws1["A3"]="Généré le"; ws1["B3"]=datetime.now().strftime("%d/%m/%Y %H:%M")
    infos=[("Numéro",ch["numero"]),("Bénéficiaire",ch["beneficiaire"]),
           ("Banque",ch.get("banque","") or "—"),("Date émission",ch["date_emission"]),
           ("Date échéance",ch.get("date_echeance","") or "—"),
           ("Montant initial",ch["montant_initial"]),
           ("Montant restant",ch["montant_restant"]),
           ("Utilisé",ch["montant_initial"]-ch["montant_restant"]),
           ("Statut",sl.get(ch["statut"],ch["statut"])),
           ("Notes",ch.get("notes","") or "—")]
    for i,(k,v) in enumerate(infos,5):
        ws1.cell(i,1,k).font=Font(bold=True)
        ws1.cell(i,2,v)
    ws1.column_dimensions["A"].width=24; ws1.column_dimensions["B"].width=36

    # Historique transactions
    ws2=wb.create_sheet("Transactions")
    for col,h in enumerate(["Date","Type","Désignation","Catégorie",
                             f"Montant ({e['devise']})"],1):
        hdr(ws2.cell(1,col),h)
    trs=get_cheque_transactions(cheque_id)
    for i,t in enumerate(trs,2):
        ws2.cell(i,1,t["date_transaction"])
        ws2.cell(i,2,"Entrée" if t["type"]=="entree" else "Dépense")
        ws2.cell(i,3,t["designation"])
        ws2.cell(i,4,t.get("cat_nom","") or "—")
        mc=ws2.cell(i,5,t["montant"]); mc.number_format=f'#,##0.00 "{e["devise"]}"'
        mc.font=Font(color="3DD68C" if t["type"]=="entree" else "F75F5F",bold=True)
    for col in range(1,6): ws2.column_dimensions[get_column_letter(col)].width=24
    wb.save(filepath)
    return True,f"Excel chèque #{ch['numero']} exporté."


# ── Champs personnalisés ──────────────────────────────────────────────────────
def get_champs_custom_cheque(cheque_id):
    conn=get_connection()
    row=conn.execute("SELECT champs_custom FROM cheques WHERE id=?",(cheque_id,)).fetchone()
    conn.close()
    if not row: return {}
    try: return json.loads(row["champs_custom"] or "{}")
    except: return {}

def set_champs_custom_cheque(cheque_id, champs_dict):
    conn=get_connection()
    conn.execute("UPDATE cheques SET champs_custom=? WHERE id=?",
                 (json.dumps(champs_dict,ensure_ascii=False),cheque_id))
    conn.commit(); conn.close()

def get_champs_custom_transaction(tr_id):
    conn=get_connection()
    row=conn.execute("SELECT champs_custom FROM transactions WHERE id=?",(tr_id,)).fetchone()
    conn.close()
    if not row: return {}
    try: return json.loads(row["champs_custom"] or "{}")
    except: return {}

def set_champs_custom_transaction(tr_id, champs_dict):
    conn=get_connection()
    conn.execute("UPDATE transactions SET champs_custom=? WHERE id=?",
                 (json.dumps(champs_dict,ensure_ascii=False),tr_id))
    conn.commit(); conn.close()


# ── Multi-devises ─────────────────────────────────────────────────────────────
def get_taux_conversion():
    try: return float(get_parametre("taux_conversion","1"))
    except: return 1.0

def convertir(montant, vers_secondaire=True):
    taux=get_taux_conversion()
    if vers_secondaire: return montant*taux
    return montant/taux if taux else montant

def get_devise_secondaire():
    return get_parametre("devise_secondaire","")


# ── Statistiques chèques ──────────────────────────────────────────────────────
def get_stats_cheques():
    conn=get_connection()
    rows=conn.execute("""SELECT statut, COUNT(*) as nb,
        SUM(montant_initial) as total_init,
        SUM(montant_restant) as total_rest
        FROM cheques GROUP BY statut""").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_cheques_par_statut_count():
    stats=get_stats_cheques()
    result={"en_attente":0,"encaisse":0,"partiellement_utilise":0,"cloture":0}
    for s in stats: result[s["statut"]]=s["nb"]
    return result


# ── Recalcul / Réajustement chèque ────────────────────────────────────────────
def recalculer_cheque(cheque_id, user_id=1):
    """
    Recalcule montant_restant d'un chèque à partir de ses transactions réelles.
    Utile pour corriger les erreurs de l'ancienne version (v4).
    Retourne (montant_avant, montant_apres, statut_avant, statut_apres).
    """
    conn = get_connection()
    ch   = conn.execute("SELECT * FROM cheques WHERE id=?",(cheque_id,)).fetchone()
    if not ch:
        conn.close(); return None,"Chèque introuvable."

    montant_avant  = ch["montant_restant"]
    statut_avant   = ch["statut"]
    montant_initial= ch["montant_initial"]

    # Somme de toutes les dépenses (sorties) liées à ce chèque
    total_depenses = conn.execute(
        "SELECT COALESCE(SUM(montant),0) FROM transactions WHERE cheque_id=? AND type='sortie'",
        (cheque_id,)).fetchone()[0]

    nouveau_restant = max(0.0, montant_initial - total_depenses)
    conn.execute("UPDATE cheques SET montant_restant=?,updated_at=? WHERE id=?",
                 (nouveau_restant, datetime.now().isoformat(), cheque_id))
    _recalc_statut_cheque(conn, cheque_id)

    ch2 = conn.execute("SELECT statut FROM cheques WHERE id=?",(cheque_id,)).fetchone()
    statut_apres = ch2["statut"] if ch2 else statut_avant

    _log(conn,"RECALCUL",
         f"#{ch['numero']} {montant_avant:,.0f}→{nouveau_restant:,.0f} ({statut_avant}→{statut_apres})",
         user_id)
    conn.commit(); conn.close()
    return {
        "numero": ch["numero"],
        "montant_avant": montant_avant,
        "montant_apres": nouveau_restant,
        "statut_avant":  statut_avant,
        "statut_apres":  statut_apres,
        "diff": nouveau_restant - montant_avant,
    }, "ok"

def recalculer_tous_cheques(user_id=1):
    """Recalcule tous les chèques. Retourne la liste des résultats."""
    conn=get_connection()
    ids=[r["id"] for r in conn.execute("SELECT id FROM cheques").fetchall()]
    conn.close()
    resultats=[]
    for cid in ids:
        res,msg=recalculer_cheque(cid,user_id)
        if res: resultats.append(res)
    return resultats


# ── Modification du chèque lié d'une dépense ──────────────────────────────────
def changer_cheque_depense(transaction_id, nouveau_cheque_id, user_id=1):
    """
    Bascule une dépense d'un chèque vers un autre.
    - Restaure le montant sur l'ancien chèque
    - Vérifie la disponibilité sur le nouveau chèque
    - Met à jour la transaction et les deux chèques atomiquement
    """
    conn = get_connection()
    try:
        tr = conn.execute("SELECT * FROM transactions WHERE id=?",(transaction_id,)).fetchone()
        if not tr:
            return False,"Transaction introuvable."
        if tr["type"] != "sortie":
            return False,"Seules les dépenses (sortie) peuvent être réaffectées."
        if not tr["cheque_id"]:
            return False,"Cette transaction n'est pas liée à un chèque."
        if tr["cheque_id"] == nouveau_cheque_id:
            return False,"C'est déjà le même chèque."

        ancien_cheque = conn.execute("SELECT * FROM cheques WHERE id=?",(tr["cheque_id"],)).fetchone()
        nouveau_cheque= conn.execute("SELECT * FROM cheques WHERE id=?",(nouveau_cheque_id,)).fetchone()
        if not nouveau_cheque:
            return False,"Nouveau chèque introuvable."
        if tr["montant"] > nouveau_cheque["montant_restant"]:
            return False,(f"Montant ({tr['montant']:,.0f}) dépasse le restant du chèque "
                          f"#{nouveau_cheque['numero']} ({nouveau_cheque['montant_restant']:,.0f}).")

        # Restaurer sur l'ancien
        if ancien_cheque:
            rest_ancien = min(ancien_cheque["montant_restant"] + tr["montant"],
                              ancien_cheque["montant_initial"])
            conn.execute("UPDATE cheques SET montant_restant=?,updated_at=? WHERE id=?",
                         (rest_ancien, datetime.now().isoformat(), ancien_cheque["id"]))
            _recalc_statut_cheque(conn, ancien_cheque["id"])

        # Déduire sur le nouveau
        rest_nouveau = nouveau_cheque["montant_restant"] - tr["montant"]
        conn.execute("UPDATE cheques SET montant_restant=?,updated_at=? WHERE id=?",
                     (rest_nouveau, datetime.now().isoformat(), nouveau_cheque_id))
        _recalc_statut_cheque(conn, nouveau_cheque_id)

        # Mettre à jour la transaction
        conn.execute("UPDATE transactions SET cheque_id=? WHERE id=?",
                     (nouveau_cheque_id, transaction_id))

        _log(conn,"CHANGER_CHEQUE",
             f"tr#{transaction_id} #{ancien_cheque['numero'] if ancien_cheque else '?'}→#{nouveau_cheque['numero']}",
             user_id)
        conn.commit()
        return True,f"Dépense réaffectée au chèque #{nouveau_cheque['numero']}."
    except Exception as e:
        conn.rollback(); return False,str(e)
    finally:
        conn.close()


# ── Historique des modifications d'un chèque ──────────────────────────────────
def get_historique_cheque(cheque_id):
    """Retourne toutes les entrées du journal concernant ce chèque."""
    conn=get_connection()
    ch=conn.execute("SELECT numero FROM cheques WHERE id=?",(cheque_id,)).fetchone()
    if not ch: conn.close(); return []
    num=ch["numero"]
    rows=conn.execute("""
        SELECT h.*, u.nom as user_nom FROM historique h
        LEFT JOIN utilisateurs u ON h.user_id=u.id
        WHERE h.detail LIKE ? OR h.detail LIKE ? OR h.detail LIKE ?
        ORDER BY h.created_at DESC
    """,(f"%#{num}%",f"%cheque_id={cheque_id}%",f"%id={cheque_id}%")).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Journal filtrable ──────────────────────────────────────────────────────────
def get_historique_filtre(action="", user_id=None, date_debut="", date_fin="",
                          search="", limit=500):
    conn  = get_connection()
    query = """SELECT h.*, u.nom as user_nom FROM historique h
               LEFT JOIN utilisateurs u ON h.user_id=u.id WHERE 1=1"""
    params= []
    if action:
        query+=" AND h.action LIKE ?"; params.append(f"%{action}%")
    if user_id:
        query+=" AND h.user_id=?"; params.append(user_id)
    if date_debut:
        query+=" AND h.created_at>=?"; params.append(date_debut)
    if date_fin:
        query+=" AND h.created_at<=?"; params.append(date_fin+" 23:59:59")
    if search:
        query+=" AND (h.action LIKE ? OR h.detail LIKE ? OR u.nom LIKE ?)"
        params+=[f"%{search}%"]*3
    query+=f" ORDER BY h.created_at DESC LIMIT ?"
    params.append(limit)
    rows=conn.execute(query,params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Commentaires sur transactions ─────────────────────────────────────────────
def init_commentaires():
    """Crée la table commentaires si elle n'existe pas (migration safe)."""
    conn=get_connection()
    conn.execute("""CREATE TABLE IF NOT EXISTS commentaires (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        transaction_id INTEGER NOT NULL,
        user_id INTEGER,
        texte TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (transaction_id) REFERENCES transactions(id) ON DELETE CASCADE,
        FOREIGN KEY (user_id) REFERENCES utilisateurs(id))""")
    conn.commit(); conn.close()

def get_commentaires(transaction_id):
    conn=get_connection()
    rows=conn.execute("""
        SELECT c.*, u.nom as user_nom FROM commentaires c
        LEFT JOIN utilisateurs u ON c.user_id=u.id
        WHERE c.transaction_id=?
        ORDER BY c.created_at ASC""",(transaction_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def add_commentaire(transaction_id, texte, user_id=1):
    if not texte.strip(): return False,"Commentaire vide."
    conn=get_connection()
    conn.execute("INSERT INTO commentaires (transaction_id,texte,user_id) VALUES (?,?,?)",
                 (transaction_id,texte.strip(),user_id))
    conn.commit(); conn.close()
    return True,"Commentaire ajouté."

def delete_commentaire(commentaire_id, user_id=1):
    conn=get_connection()
    conn.execute("DELETE FROM commentaires WHERE id=?",(commentaire_id,))
    conn.commit(); conn.close()


# ── Export planifié ───────────────────────────────────────────────────────────
def check_export_planifie():
    """
    Vérifie si un export automatique mensuel est dû (1er du mois).
    Retourne True si l'export a été effectué, False sinon.
    """
    if get_parametre("export_auto","0") != "1":
        return False
    aujourd_hui = date.today()
    if aujourd_hui.day != 1:
        return False
    dernier = get_parametre("export_auto_dernier","")
    mois_actuel = aujourd_hui.strftime("%Y-%m")
    if dernier == mois_actuel:
        return False  # déjà fait ce mois-ci

    export_dir = get_parametre("export_auto_dossier", BASE_DIR)
    os.makedirs(export_dir, exist_ok=True)
    mois_prec = aujourd_hui.month - 1 or 12
    annee_prec = aujourd_hui.year if aujourd_hui.month > 1 else aujourd_hui.year - 1
    import calendar
    dd = f"{annee_prec}-{mois_prec:02d}-01"
    df = f"{annee_prec}-{mois_prec:02d}-{calendar.monthrange(annee_prec,mois_prec)[1]:02d}"
    nom = f"rapport_auto_{annee_prec}_{mois_prec:02d}.xlsx"
    fp  = os.path.join(export_dir, nom)
    try:
        export_to_excel(fp, dd, df)
        set_parametre("export_auto_dernier", mois_actuel)
        return fp
    except Exception:
        return False


# ── Mot de passe oublié (reset par admin) ─────────────────────────────────────
def reset_password_by_admin(target_login, new_password, admin_user_id=1):
    """Un admin peut réinitialiser le mot de passe de n'importe quel utilisateur."""
    conn=get_connection()
    row=conn.execute("SELECT id FROM utilisateurs WHERE login=?",(target_login,)).fetchone()
    if not row:
        conn.close(); return False,"Utilisateur introuvable."
    sel=secrets.token_hex(16)
    conn.execute("UPDATE utilisateurs SET mot_de_passe=?,sel=? WHERE login=?",
                 (_hash_password(new_password,sel),sel,target_login))
    _log(conn,"RESET_PWD",f"login={target_login}",admin_user_id)
    conn.commit(); conn.close()
    return True,f"Mot de passe de '{target_login}' réinitialisé."

def get_all_logins():
    conn=get_connection()
    rows=conn.execute("SELECT login,nom FROM utilisateurs ORDER BY nom").fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Archivage chèques clôturés ─────────────────────────────────────────────────
def get_all_cheques_v2(search="", statut="", sort_by="created_at", sort_dir="DESC",
                       inclure_archives=False, page=0, page_size=0):
    """Version étendue de get_all_cheques : exclut les clôturés par défaut,
    avec pagination optionnelle (page_size=0 désactive la pagination)."""
    allowed = {"numero","montant_initial","montant_restant","date_emission",
               "date_echeance","beneficiaire","banque","statut","created_at"}
    if sort_by not in allowed: sort_by="created_at"
    sort_dir = "ASC" if sort_dir=="ASC" else "DESC"
    conn   = get_connection()
    query  = "SELECT * FROM cheques WHERE 1=1"
    params = []
    if not inclure_archives and not statut:
        query += " AND statut != 'cloture'"
    if search:
        query  += " AND (numero LIKE ? OR beneficiaire LIKE ? OR banque LIKE ? OR notes LIKE ?)"
        params += [f"%{search}%"]*4
    if statut:
        query += " AND statut=?"; params.append(statut)
    query_count = query.replace("SELECT *","SELECT COUNT(*)")
    total = conn.execute(query_count,params).fetchone()[0]
    query += f" ORDER BY {sort_by} {sort_dir}"
    if page_size>0:
        query += " LIMIT ? OFFSET ?"
        params += [page_size, page*page_size]
    rows = conn.execute(query,params).fetchall()
    conn.close()
    return [dict(r) for r in rows], total

def get_cheques_archives():
    return get_all_cheques(search="",statut="cloture")


# ── Dupliquer un chèque ────────────────────────────────────────────────────────
def dupliquer_cheque(cheque_id, nouveau_numero=None, user_id=1):
    """Crée un nouveau chèque avec les mêmes infos (bénéficiaire, banque, montant)
    mais une nouvelle date d'émission (aujourd'hui) et un nouveau numéro auto."""
    ch=get_cheque_by_id(cheque_id)
    if not ch: return False,"Chèque introuvable."
    numero = nouveau_numero or get_next_numero_cheque()
    return add_cheque(
        numero, ch["montant_initial"], date.today().isoformat(),
        ch["beneficiaire"], ch.get("banque",""), ch.get("notes",""),
        "", user_id)


# ── Recherche par montant ──────────────────────────────────────────────────────
def recherche_par_montant(montant_min, montant_max, type_=None):
    conn  = get_connection()
    query = """SELECT t.*, c.nom as cat_nom, c.icone as cat_icone, ch.numero as cheque_num
        FROM transactions t
        LEFT JOIN categories c ON t.categorie_id=c.id
        LEFT JOIN cheques ch ON t.cheque_id=ch.id
        WHERE t.montant>=? AND t.montant<=?"""
    params=[montant_min,montant_max]
    if type_:
        query+=" AND t.type=?"; params.append(type_)
    query+=" ORDER BY t.montant DESC"
    rows=conn.execute(query,params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Import CSV/Excel ───────────────────────────────────────────────────────────
def importer_transactions_csv(filepath, mapping, user_id=1):
    """
    Importe des transactions depuis un CSV.
    mapping = {"date":"col_date","type":"col_type","montant":"col_montant",
               "designation":"col_designation","categorie":"col_categorie"(optionnel)}
    Retourne (nb_importees, nb_erreurs, liste_erreurs)
    """
    import csv
    nb_ok=0; erreurs=[]
    cats={c["nom"].lower():c["id"] for c in get_categories()}
    conn=get_connection()
    try:
        with open(filepath,newline="",encoding="utf-8-sig") as f:
            reader=csv.DictReader(f)
            for i,row in enumerate(reader,2):
                try:
                    dt  = row.get(mapping.get("date",""),"").strip()
                    typ = row.get(mapping.get("type",""),"").strip().lower()
                    mnt = row.get(mapping.get("montant",""),"").strip().replace(",",".").replace(" ","")
                    dsg = row.get(mapping.get("designation",""),"").strip()
                    if not (dt and typ and mnt and dsg):
                        erreurs.append(f"Ligne {i}: champs manquants"); continue
                    type_norm = "entree" if typ in ("entree","entrée","in","credit","crédit") else \
                                ("sortie" if typ in ("sortie","out","debit","débit") else None)
                    if not type_norm:
                        erreurs.append(f"Ligne {i}: type invalide '{typ}'"); continue
                    montant=float(mnt)
                    cat_id=None
                    if "categorie" in mapping:
                        cat_nom=row.get(mapping["categorie"],"").strip().lower()
                        cat_id=cats.get(cat_nom)
                    conn.execute("""INSERT INTO transactions
                        (type,montant,designation,categorie_id,date_transaction,created_by)
                        VALUES (?,?,?,?,?,?)""",
                        (type_norm,montant,dsg,cat_id,dt,user_id))
                    nb_ok+=1
                except Exception as ex:
                    erreurs.append(f"Ligne {i}: {ex}")
        _log(conn,"IMPORT_CSV",f"{nb_ok} transaction(s) importée(s)",user_id)
        conn.commit()
    finally:
        conn.close()
    return nb_ok, len(erreurs), erreurs

def importer_transactions_excel(filepath, mapping, user_id=1):
    """Importe des transactions depuis un fichier Excel (.xlsx)."""
    try:
        import openpyxl
    except ImportError:
        return 0,1,["openpyxl non installé."]
    nb_ok=0; erreurs=[]
    cats={c["nom"].lower():c["id"] for c in get_categories()}
    wb=openpyxl.load_workbook(filepath,data_only=True)
    ws=wb.active
    headers=[str(c.value).strip() if c.value else "" for c in ws[1]]
    col_idx={h:i for i,h in enumerate(headers)}
    conn=get_connection()
    try:
        for i,row in enumerate(ws.iter_rows(min_row=2,values_only=True),2):
            try:
                def get_val(key):
                    col=mapping.get(key)
                    if not col or col not in col_idx: return None
                    return row[col_idx[col]]
                dt_raw = get_val("date")
                typ    = str(get_val("type") or "").strip().lower()
                mnt    = get_val("montant")
                dsg    = str(get_val("designation") or "").strip()
                if dt_raw is None or not typ or mnt is None or not dsg:
                    erreurs.append(f"Ligne {i}: champs manquants"); continue
                dt = dt_raw.strftime("%Y-%m-%d") if hasattr(dt_raw,"strftime") else str(dt_raw)
                type_norm = "entree" if typ in ("entree","entrée","in","credit","crédit") else \
                            ("sortie" if typ in ("sortie","out","debit","débit") else None)
                if not type_norm:
                    erreurs.append(f"Ligne {i}: type invalide '{typ}'"); continue
                montant=float(mnt)
                cat_id=None
                if "categorie" in mapping:
                    cat_nom=str(get_val("categorie") or "").strip().lower()
                    cat_id=cats.get(cat_nom)
                conn.execute("""INSERT INTO transactions
                    (type,montant,designation,categorie_id,date_transaction,created_by)
                    VALUES (?,?,?,?,?,?)""",
                    (type_norm,montant,dsg,cat_id,dt,user_id))
                nb_ok+=1
            except Exception as ex:
                erreurs.append(f"Ligne {i}: {ex}")
        _log(conn,"IMPORT_EXCEL",f"{nb_ok} transaction(s) importée(s)",user_id)
        conn.commit()
    finally:
        conn.close()
    return nb_ok, len(erreurs), erreurs

def get_csv_headers(filepath):
    import csv
    with open(filepath,newline="",encoding="utf-8-sig") as f:
        return next(csv.reader(f))

def get_excel_headers(filepath):
    import openpyxl
    wb=openpyxl.load_workbook(filepath,read_only=True)
    ws=wb.active
    return [str(c.value).strip() if c.value else "" for c in next(ws.iter_rows(max_row=1))]


# ── Export du journal ──────────────────────────────────────────────────────────
def export_journal_excel(filepath, logs):
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter
    wb=openpyxl.Workbook(); ws=wb.active; ws.title="Journal"
    def hdr(cell,val):
        cell.value=val; cell.font=Font(bold=True,color="FFFFFF")
        cell.fill=PatternFill("solid",fgColor="1A2744")
        cell.alignment=Alignment(horizontal="center")
    for col,h in enumerate(["Date/Heure","Action","Détail","Utilisateur"],1):
        hdr(ws.cell(1,col),h)
    for i,log in enumerate(logs,2):
        ws.cell(i,1,log["created_at"][:19])
        ws.cell(i,2,log["action"])
        ws.cell(i,3,log.get("detail","") or "")
        ws.cell(i,4,log.get("user_nom","") or "")
    for col,w in zip("ABCD",[20,20,50,20]): ws.column_dimensions[col].width=w
    wb.save(filepath)
    return True,"Journal exporté en Excel."

def export_journal_pdf(filepath, logs):
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.units import cm
    except ImportError:
        return False,"reportlab non installé."
    e=_get_entete()
    doc=SimpleDocTemplate(filepath,pagesize=A4,leftMargin=1.5*cm,rightMargin=1.5*cm,
                          topMargin=1.5*cm,bottomMargin=1.5*cm)
    styles=getSampleStyleSheet(); story=[]
    _pdf_entete(story,styles,e)
    story.append(Paragraph("<b>Journal d'activité</b>",styles["Title"]))
    story.append(Paragraph(f"Généré le {datetime.now().strftime('%d/%m/%Y à %H:%M')} — {len(logs)} entrée(s)",
                           styles["Normal"]))
    story.append(Spacer(1,0.4*cm))
    data=[["Date/Heure","Action","Détail","Utilisateur"]]
    for log in logs:
        detail=(log.get("detail","") or "")[:50]
        data.append([log["created_at"][:16],log["action"],detail,log.get("user_nom","") or ""])
    t=Table(data,colWidths=[3*cm,3*cm,8*cm,3*cm])
    t.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#1A2744")),
        ("TEXTCOLOR",(0,0),(-1,0),colors.white),
        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.HexColor("#F5F5F5"),colors.white]),
        ("FONTSIZE",(0,0),(-1,-1),8),
        ("GRID",(0,0),(-1,-1),0.3,colors.HexColor("#DDDDDD")),
        ("PADDING",(0,0),(-1,-1),5),
    ]))
    story.append(t)
    doc.build(story)
    return True,"Journal exporté en PDF."


# ── Comparatif mois par mois ───────────────────────────────────────────────────
def get_comparatif_mensuel(annee, nb_mois=12):
    """Retourne les stats entrées/sorties/solde pour les nb_mois derniers mois
    à partir de l'année donnée (gère le passage d'année)."""
    conn=get_connection()
    resultats=[]
    mois_noms=["Jan","Fév","Mar","Avr","Mai","Jun","Jul","Aoû","Sep","Oct","Nov","Déc"]
    mois_cible=12
    annee_cible=annee
    mois_liste=[]
    m,a=mois_cible,annee_cible
    for _ in range(nb_mois):
        mois_liste.append((a,m))
        m-=1
        if m==0: m=12; a-=1
    mois_liste.reverse()
    for a,m in mois_liste:
        row=conn.execute("""SELECT
            SUM(CASE WHEN type='entree' THEN montant ELSE 0 END) as entrees,
            SUM(CASE WHEN type='sortie' THEN montant ELSE 0 END) as sorties
            FROM transactions
            WHERE strftime('%Y',date_transaction)=? AND strftime('%m',date_transaction)=?""",
            (str(a),f"{m:02d}")).fetchone()
        ent=row["entrees"] or 0; sor=row["sorties"] or 0
        resultats.append({
            "annee":a,"mois":m,"label":f"{mois_noms[m-1]} {a}",
            "entrees":ent,"sorties":sor,"solde":ent-sor,
        })
    conn.close()
    return resultats


# ── QR Code pour PDF chèque ────────────────────────────────────────────────────
def generer_qrcode_cheque(cheque):
    """Génère une image QR code (en mémoire) résumant le chèque.
    Retourne le chemin du fichier temporaire PNG, ou None si qrcode non installé."""
    try:
        import qrcode
    except ImportError:
        return None
    e=_get_entete()
    contenu = (f"Chèque {cheque['numero']}\n"
               f"Bénéficiaire: {cheque['beneficiaire']}\n"
               f"Montant initial: {cheque['montant_initial']:,.0f} {e['devise']}\n"
               f"Restant: {cheque['montant_restant']:,.0f} {e['devise']}\n"
               f"Statut: {cheque['statut']}\n"
               f"Émission: {cheque['date_emission']}")
    img=qrcode.make(contenu)
    import tempfile
    fp=os.path.join(tempfile.gettempdir(),f"qr_cheque_{cheque['numero'].replace('/','_')}.png")
    img.save(fp)
    return fp