from flask import Flask, render_template, request, redirect, session, jsonify
import os
from functools import wraps
import psycopg2
from psycopg2.extras import RealDictCursor
import qrcode
import io
import base64
from flask_socketio import SocketIO, emit,join_room
from dotenv import load_dotenv
import uuid

app = Flask(__name__)
app.secret_key = 'gizli_anahtar_gastropro'
socketio = SocketIO(app, cors_allowed_origins="*")

UPLOAD_FOLDER = "static/uploads"
QR_FOLDER = "static/qr"

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["QR_FOLDER"] = QR_FOLDER

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(QR_FOLDER, exist_ok=True)

ADMIN_USER = "admin"
ADMIN_PASS = "1234"

load_dotenv()

def get_db_connection():
    # Artık elle yazmıyoruz, os.getenv ile dosyadan çekiyoruz
    conn = psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        database=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASS"),
        port=os.getenv("DB_PORT", "5432"),
        cursor_factory=RealDictCursor
    )
    return conn

# TEST BAĞLANTI
try:
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('SELECT ad FROM lokantalar;')
    lokanta = cur.fetchone()
    if lokanta:
        print(f"Bağlantı Başarılı! Lokanta Adı: {lokanta['ad']}")
    cur.close()
    conn.close()
except Exception as e:
    print(f"Eyvah bağlantı patladı! Hata: {e}")


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return redirect("/login")
        return f(*args, **kwargs)
    return decorated_function

# --- SÜPER ADMİN Koruması (Decorator) ---
def super_admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("super_admin_logged_in"):
            return redirect("/super-admin/login")
        return f(*args, **kwargs)
    return decorated_function

# --- SÜPER ADMİN GİRİŞ SAYFASI ---
@app.route("/super-admin/login", methods=["GET", "POST"])
def super_login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        
        conn = get_db_connection()
        cur = conn.cursor()
        # Veritabanında süper admini sorgula
        cur.execute("SELECT * FROM super_admins WHERE username = %s AND password = %s", (username, password))
        admin = cur.fetchone()
        cur.close()
        conn.close()

        if admin:
            session["super_admin_logged_in"] = True
            session["super_admin_name"] = admin['ad_soyad']
            return redirect("/super-admin/dashboard")
        else:
            return render_template("super_login.html", error="Yetkisiz erişim! Bilgileri kontrol et.")
            
    return render_template("super_login.html")

# --- SÜPER ADMİN ÇIKIŞ ---
@app.route("/super-admin/logout")
def super_logout():
    session.pop("super_admin_logged_in", None)
    session.pop("super_admin_name", None)
    return redirect("/super-admin/login")

# --- SÜPER ADMİN DASHBOARD ---
@app.route("/super-admin/dashboard")
@super_admin_required
def super_dashboard():
    conn = get_db_connection()
    cur = conn.cursor()
    # Tüm lokantaları en son eklenenden başlayarak getir
    cur.execute("SELECT * FROM lokantalar ORDER BY id DESC")
    lokantalar = cur.fetchall()
    cur.close()
    conn.close()
    return render_template("super_dashboard.html", lokantalar=lokantalar)

# --- YENİ LOKANTA EKLEME AKSİYONU ---
@app.route("/super-admin/lokanta-ekle", methods=["POST"])
@super_admin_required
def super_lokanta_ekle():
    ad = request.form.get("ad")
    gizli_kod = str(uuid.uuid4())[:8]
    eposta = request.form.get("eposta")
    sifre = request.form.get("sifre")
    masa_sayisi = request.form.get("masa_sayisi", 1)
    
    # DB hata vermesin diye slug da oluşturuyoruz ama artık yönlendirmelerde kullanmıyoruz
    import re
    slug = ad.lower()
    tr_map = str.maketrans("çğıöşü ", "cgiosu-")
    slug = slug.translate(tr_map)
    slug = re.sub(r'[^a-z0-9-]', '', slug)
    
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO lokantalar (ad, eposta, sifre, slug, masa_sayisi, aktif_mi, uuid) 
            VALUES (%s, %s, %s, %s, %s, TRUE, %s)
        """, (ad, eposta, sifre, slug, masa_sayisi, gizli_kod))
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"Hata: {e}")
    finally:
        cur.close()
        conn.close()
        
    return redirect("/super-admin/dashboard")

@app.route("/super-admin/qr-bas/<int:id>")
@super_admin_required
def qr_bas_sayfasi(id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM lokantalar WHERE id = %s", (id,))
    lokanta = cur.fetchone()
    cur.close()
    conn.close()

    if not lokanta:
        return "Lokanta bulunamadı", 404

    qr_kodlar = []
    
    # Masa sayısı kadar QR üret (ARTIK UUID İLE!)
    for i in range(1, lokanta['masa_sayisi'] + 1):
        ipadres = "https://menuflw.com"
        # SLUG YERİNE UUID KULLANILIYOR
        url = f"{ipadres}/m/{lokanta['uuid']}/{i}"
        
        qr = qrcode.QRCode(version=1, box_size=10, border=2)
        qr.add_data(url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        
        buffered = io.BytesIO()
        img.save(buffered, format="PNG")
        img_str = base64.b64encode(buffered.getvalue()).decode()
        
        qr_kodlar.append({
            "masa_no": i,
            "qr_base64": img_str
        })

    return render_template("qr_print.html", lokanta=lokanta, qr_kodlar=qr_kodlar)

# --- LOKANTAYA SIZMA AKSİYONU ---
@app.route('/super-admin/lokantaya-siz/<int:lokanta_id>')
@super_admin_required
def lokantaya_siz(lokanta_id):
    conn = get_db_connection()
    cur = conn.cursor()
    
    cur.execute("SELECT id, ad, uuid FROM lokantalar WHERE id = %s", (lokanta_id,))
    lokanta = cur.fetchone()
    cur.close()
    conn.close()

    if lokanta:
        session["admin_logged_in"] = True
        session["lokanta_id"] = lokanta['id']
        session["lokanta_ad"] = lokanta['ad']
        session["lokanta_uuid"] = lokanta['uuid'] 
        return redirect("/admin") 
    
    return "Hata: Lokanta bulunamadı!", 404

#-------------------------------------------------------------------------------
# GİRİŞ SAYFASI ROTASI
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email")
        sifre = request.form.get("password")
        
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM lokantalar WHERE eposta = %s AND sifre = %s", (email, sifre))
        user = cur.fetchone()
        cur.close()
        conn.close()

        if user:
            session["admin_logged_in"] = True
            session["lokanta_id"] = user['id']
            session["lokanta_ad"] = user['ad']
            session["lokanta_uuid"] = user['uuid'] # UUID SESSIONA EKLENDİ
            return redirect("/admin")
        else:
            return "Hatalı giriş bilgileri!"
            
    return render_template("login.html")

# ÇIKIŞ ROTASI
@app.route("/logout")
def logout():
    session.pop("admin_logged_in", None)
    return redirect("/login")

#şifre_kurtarma
@app.route("/sifremi-unuttum")
def sifremi_unuttum():
    return render_template("sifre_destek.html")

# ---------- ANA SAYFA ----------
@app.route("/")
def index():
    u_id = session.get("lokanta_uuid")
    m_no = session.get("masa_no", 0) 
    
    if u_id:
        # Müşteriyi YENİ tam adrese gönder: /m/uuid/3
        return redirect(f"/m/{u_id}/{m_no}")
        
    return redirect("/login")

@app.route("/m/<string:u_id>/<int:masa_no>")
def home(u_id, masa_no=0):
    conn = get_db_connection()
    cur = conn.cursor()

    # 1. UUID ile lokantayı bul
    cur.execute("SELECT * FROM lokantalar WHERE uuid = %s", (u_id,))
    lokanta = cur.fetchone()

    if not lokanta:
        cur.close()
        conn.close()
        return "Böyle bir dükkan kayıtlı değil!", 404

    # Session'a artık slug değil, uuid ve lokanta_id atıyoruz
    session["lokanta_id"] = lokanta['id']
    session["masa_no"] = masa_no
    session["lokanta_uuid"] = u_id 
    
    lokanta_ad = lokanta['ad']
    
    # 2. Sadece BU lokantaya ait kategorileri al
    cur.execute("SELECT * FROM kategoriler WHERE lokanta_id = %s ORDER BY sira ASC", (lokanta['id'],))
    kategoriler = cur.fetchall()

    # 3. Sadece BU lokantaya ait ürünleri al
    cur.execute("""
        SELECT u.*, k.ad as kat_ad 
        FROM urunler u 
        JOIN kategoriler k ON u.kategori_id = k.id 
        WHERE u.lokanta_id = %s AND u.stokta_mi = TRUE 
        ORDER BY k.sira, u.ad
    """, (lokanta['id'],))
    urunler = cur.fetchall()

    cur.close()
    conn.close()

    return render_template("home.html", lokanta=lokanta, kategoriler=kategoriler, urunler=urunler, lokanta_ad=lokanta_ad)

# ---------- ADMIN PANEL ----------
@app.route("/admin")
def admin_ana_panel():
    if not session.get("admin_logged_in"):
        return redirect("/login")
    
    l_id = session.get("lokanta_id")
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    cur.execute("SELECT * FROM urunler WHERE lokanta_id = %s", (l_id,))
    urunler = cur.fetchall()
    
    cur.close()
    conn.close()
    return render_template("admin.html", urunler=urunler, lokanta_ad=session.get("lokanta_ad"))

# ---------- ADMINurunekle PANEL ----------
@app.route("/adminurunekle", methods=["GET", "POST"])
@login_required
def admin_urunekle():
    lokanta_id = session.get("lokanta_id")
    
    if not lokanta_id:
        return redirect("/login") 

    conn = get_db_connection()
    cur = conn.cursor()

    if request.method == "POST":
        kategori_ad = request.form.get("kategori_ad")
        if kategori_ad:
            cur.execute("""
                INSERT INTO kategoriler (ad, lokanta_id) 
                VALUES (%s, %s) 
                ON CONFLICT DO NOTHING
            """, (kategori_ad, lokanta_id))
            conn.commit()
            cur.close()
            conn.close()
            return "OK", 200

        ad = request.form["ad"]
        fiyat = float(request.form["fiyat"])
        icerik = request.form["icerik"]
        kategori_id = request.form.get("kategori")

        file = request.files.get("resim")
        if file and file.filename != '':
            filename = file.filename
            file.save(os.path.join(UPLOAD_FOLDER, filename))
        else:
            filename = "default.jpg"

        cur.execute("""
            INSERT INTO urunler (ad, fiyat, kategori_id, fotograf_url, aciklama, lokanta_id)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (ad, fiyat, int(kategori_id), filename, icerik, lokanta_id))
        
        yeni_urun_id = cur.fetchone()['id']

        ekstra_adlar = request.form.getlist("ekstra_ad[]")
        ekstra_fiyatlar = request.form.getlist("ekstra_fiyat[]")
        
        for i in range(len(ekstra_adlar)):
            e_ad = ekstra_adlar[i].strip()
            if e_ad:
                e_fiyat = float(ekstra_fiyatlar[i]) if ekstra_fiyatlar[i] else 0.0
                cur.execute("""
                    INSERT INTO urun_ekstralar (urun_id, ekstra_ad, ekstra_fiyat)
                    VALUES (%s, %s, %s)
                """, (yeni_urun_id, e_ad, e_fiyat))
        
        conn.commit()
        cur.close()
        conn.close()
        return redirect("/admin/urunlerim")

    cur.execute("SELECT * FROM kategoriler WHERE lokanta_id = %s ORDER BY ad ASC", (lokanta_id,))
    kategoriler = cur.fetchall()
    cur.close()
    conn.close()
    return render_template("admin_urunekle.html", kategoriler=kategoriler)


@app.route("/admin/sifre-degistir", methods=["GET", "POST"])
@login_required 
def admin_sifre_degistir():
    if request.method == "POST":
        yeni_sifre = request.form.get("yeni_sifre")
        yeni_sifre_tekrar = request.form.get("yeni_sifre_tekrar")
        lokanta_id = session.get("lokanta_id")

        if yeni_sifre != yeni_sifre_tekrar:
            return "Şifreler birbiriyle uyuşmuyor!", 400

        conn = get_db_connection()
        cur = conn.cursor()
        try:
            cur.execute("UPDATE lokantalar SET sifre = %s WHERE id = %s", (yeni_sifre, lokanta_id))
            conn.commit()
            return redirect("/admin")
        except Exception as e:
            conn.rollback()
            print(f"Şifre güncelleme hatası: {e}")
            return "Bir hata oluştu!", 500
        finally:
            cur.close()
            conn.close()

    return render_template("admin_sifre.html")

# ---------- ÜRÜN DETAY ----------
# ---------- ÜRÜN DETAY SAYFASI ----------
@app.route("/m/<string:u_id>/urun/<int:urun_id>")
def urun_detay(u_id, urun_id):
    session['lokanta_uuid'] = u_id
    conn = get_db_connection()
    cur = conn.cursor()
    
    # 1. Ürünü çek
    cur.execute("SELECT * FROM urunler WHERE id = %s", (urun_id,)) # Virgül eklendi
    urun = cur.fetchone()
    
    if not urun:
        cur.close()
        conn.close()
        return "Ürün bulunamadı!", 404
        
    # 2. Ekstraları çek
    # BURASI ÇOK ÖNEMLİ: (urun_id,) şeklinde virgül şart!
    cur.execute("SELECT * FROM urun_ekstralar WHERE urun_id = %s", (urun_id,)) 
    ekstralar = cur.fetchall()
    
    cur.close()
    conn.close()
    
    # urun.html şablonuna gönderiyoruz
    return render_template("urun.html", urun=urun, ekstralar=ekstralar)

# ---------- KATEGORİ DETAY (Ürün Listesi) ----------
@app.route("/m/<string:u_id>/kategori/<int:kat_id>")
def kategori_sayfasi(u_id, kat_id):
    session['lokanta_uuid'] = u_id
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT ad FROM kategoriler WHERE id = %s", (kat_id,))
    kategori = cur.fetchone()

    if not kategori:
        cur.close()
        conn.close()
        return "Kategori bulunamadı!", 404

    # DİKKAT: Aşağıdaki (id,) kısmını (kat_id,) olarak değiştirdik.
    cur.execute("""
        SELECT * FROM urunler 
        WHERE kategori_id = %s 
        ORDER BY ad ASC
    """, (kat_id,)) # Burası düzeldi
    
    urunler = cur.fetchall()

    cur.close()
    conn.close()
    
    return render_template("kategori.html", urunler=urunler, kategori_ad=kategori['ad'])

@app.route("/m/<string:u_id>/sepete-ekle", methods=["POST"])
def sepete_ekle(u_id):
    # UUID'yi session'da tazele
    session['lokanta_uuid'] = u_id
    
    if "sepet" not in session:
        session["sepet"] = []
    
    # Form verilerini al
    urun_id = request.form.get("urun_id")
    ad = request.form.get("urun_ad")
    fiyat = float(request.form.get("fiyat", 0).replace(',', '.')) # Virgül/Nokta hatasını önle
    adet = int(request.form.get("adet", 1))
    notum = request.form.get("not", "")
    ekstralar = request.form.getlist("ekstra") 
    resim = request.form.get("resim")

    ekstra_metni = ""
    if ekstralar:
        ekstra_isimleri = [e.split(':')[0] for e in ekstralar]
        ekstra_metni = ", ".join(ekstra_isimleri)

    item = {
        "id": urun_id,
        "ad": ad,
        "ekstra_detay": ekstra_metni,
        "fiyat": fiyat,
        "adet": adet,
        "toplam": fiyat * adet,
        "ekstra_ham": ",".join(ekstralar),
        "not": notum,
        "resim": resim
    }
    
    temp = session["sepet"]
    temp.append(item)
    session["sepet"] = temp
    session.modified = True 
    
    # REDIRECT YERİNE JSON DÖNDÜRÜYORUZ (JavaScript bunu bekliyor)
    return jsonify({"success": True, "message": "Ürün sepete eklendi"})

# --- 2. SEPET GÖRÜNTÜLEME ---
# ---------- SEPET SAYFASI ----------
@app.route("/m/<string:u_id>/sepet")
def sepet(u_id):
    # Kullanıcının girdiği dükkan kodunu session'a yaz
    session['lokanta_uuid'] = u_id
    
    # Sepeti al (yoksa boş liste)
    sepet_listesi = session.get("sepet", [])
    
    # Genel toplamı hesapla (toplam değerlerin float olduğundan emin olalım)
    genel_toplam = sum(float(item.get("toplam", 0)) for item in sepet_listesi)
    
    return render_template("sepet.html", 
                           sepet=sepet_listesi, 
                           toplam=f"{genel_toplam:.2f}",
                           u_id=u_id) # HTML tarafında linkler için lazım olacak

# --- 3. SEPETTEN SİLME ---
@app.route("/m/<string:u_id>/sepet-sil/<int:index>")
def sepet_sil(u_id, index):
    # Dükkan kodunu (u_id) session'da güncelliyoruz
    session['lokanta_uuid'] = u_id
    
    if "sepet" in session:
        temp = session["sepet"]
        # İndeks kontrolü
        if 0 <= index < len(temp):
            temp.pop(index)
            session["sepet"] = temp
            session.modified = True
            
    # İşlem bittiğinde aynı dükkanın sepet sayfasına yönlendir
    return redirect(f"/m/{u_id}/sepet")

@socketio.on('join_room')
def on_join(data):
    room = data['room']
    join_room(room)
    print(f"--> [SOCKET] Kasa {room} odasına katıldı.")

# --- 4. SİPARİŞİ TAMAMLA (KASAYA GÖNDER) ---
@app.route("/m/<string:u_id>/siparisi-tamamla", methods=["POST"])
def siparisi_tamamla(u_id):
    # UUID ile dükkanı sabitle
    session['lokanta_uuid'] = u_id
    
    sepet_listesi = session.get("sepet", [])
    masa = session.get("masa_no", "Bilinmiyor")
    lokanta_id = session.get("lokanta_id")

    if not sepet_listesi:
        # Sepet boşsa menüye geri gönder
        return redirect(f"/m/{u_id}/{masa}")

    genel_toplam = sum(float(item["toplam"]) for item in sepet_listesi)

    conn = get_db_connection()
    cur = conn.cursor()

    try:
        # 1. Ana Siparişi Kaydet
        cur.execute("""
            INSERT INTO siparisler (masa_no, toplam_tutar, durum, lokanta_id)
            VALUES (%s, %s, %s, %s)
            RETURNING id
        """, (str(masa), genel_toplam, 'Beklemede', lokanta_id))
        
        ana_siparis_id = cur.fetchone()['id']

        # 2. Sipariş Detaylarını Ekle
        for item in sepet_listesi:
            cur.execute("""
                INSERT INTO siparis_detay 
                (siparis_id, urun_id, urun_ad, adet, birim_fiyat, notlar, ekstralar)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (
                ana_siparis_id,
                item.get("id"),
                item.get("ad"),
                item.get("adet"),
                item.get("fiyat"),
                item.get("not", ""),
                item.get("ekstra_ham", "")
            ))

        conn.commit()
        
        # 3. KASAYA BİLDİRİM GÖNDER
        # Odayı UUID (u_id) olarak kullanman daha güvenli olur
        socketio.emit('yeni_siparis', {'masa': masa}, room=u_id)

        # 4. Sepeti temizle ve onay sayfasına yönlendir
        session.pop("sepet", None)
        return render_template("siparis_onay.html", u_id=u_id, m_no=masa)

    except Exception as e:
        if conn:
            conn.rollback()
        print(f"!!! Sipariş hatası: {e}")
        return "Sipariş verilirken bir hata oluştu!", 500
    finally:
        if cur: cur.close()
        if conn: conn.close()
        
# ---------- KASA ----------
@app.route("/admin/kasa")
@login_required
def kasa_paneli():
    return render_template("kasa.html")

@app.route("/api/kasa_verisi")
@login_required
def kasa_verisi():
    l_id = session.get("lokanta_id")
    
    if not l_id:
        return jsonify({"error": "Yetkisiz erişim"}), 403

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT * FROM siparisler 
        WHERE lokanta_id = %s AND durum IN ('Beklemede', 'Garson Çağırıyor') 
        ORDER BY id DESC
    """, (l_id,))
    ana_siparisler = cur.fetchall()

    sonuc = []
    for s in ana_siparisler:
        cur.execute("""
            SELECT sd.urun_ad, sd.adet, sd.notlar, sd.ekstralar, u.fiyat
            FROM siparis_detay sd
            LEFT JOIN urunler u ON sd.urun_id = u.id
            WHERE sd.siparis_id = %s
        """, (s['id'],))
        
        urunler_rows = cur.fetchall()
        urunler_listesi = []
        
        for u in urunler_rows:
            urunler_listesi.append({
                "urun_ad": u['urun_ad'],
                "adet": u['adet'],
                "notlar": u['notlar'] if u['notlar'] else "",
                "ekstralar": u['ekstralar'] if u['ekstralar'] else "",
                "fiyat": float(u['fiyat']) if u['fiyat'] else 0
            })

        sonuc.append({
            "id": s['id'],
            "masa_no": s['masa_no'],
            "toplam_tutar": float(s['toplam_tutar']),
            "durum": s['durum'], 
            "tarih": s['tarih'].strftime('%H:%M'),
            "urunler": urunler_listesi 
        })

    cur.close()
    conn.close()
    
    return jsonify(sonuc)

@app.route("/admin/urun-duzenle/<int:id>")
@login_required
def urun_duzenle_sayfasi(id):
    conn = get_db_connection()
    cur = conn.cursor()
    
    cur.execute("SELECT * FROM urunler WHERE id = %s AND lokanta_id = %s", (id, session.get("lokanta_id", 1)))
    urun = cur.fetchone()
    
    if not urun:
        return "Ürün bulunamadı!", 404

    cur.execute("SELECT ekstra_ad, ekstra_fiyat FROM urun_ekstralar WHERE urun_id = %s", (id,))
    ekstralar = cur.fetchall() 

    cur.execute("SELECT * FROM kategoriler WHERE lokanta_id = %s", (session.get("lokanta_id", 1),))
    kategoriler = cur.fetchall()
    
    cur.close()
    conn.close()
    
    return render_template("admin_urunekle.html", urun=urun, kategoriler=kategoriler, ekstralar=ekstralar)

@app.route("/urun-guncelle/<int:id>", methods=["POST"])
@login_required
def urun_guncelle(id):
    ad = request.form.get("ad")
    fiyat = float(request.form.get("fiyat", 0))
    icerik = request.form.get("icerik", "")
    kategori_id = request.form.get("kategori")
    stokta_mi = True if request.form.get("stok") == "1" else False

    ekstra_adlar = request.form.getlist("ekstra_ad[]")
    ekstra_fiyatlar = request.form.getlist("ekstra_fiyat[]")

    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        cur.execute("SELECT fotograf_url FROM urunler WHERE id=%s", (id,))
        eski_resim = cur.fetchone()["fotograf_url"]
        
        file = request.files.get("resim")
        if file and file.filename != '':
            filename = file.filename
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        else:
            filename = eski_resim

        cur.execute("""
            UPDATE urunler 
            SET ad=%s, fiyat=%s, kategori_id=%s, fotograf_url=%s, aciklama=%s, stokta_mi=%s
            WHERE id=%s AND lokanta_id=%s
        """, (ad, fiyat, int(kategori_id), filename, icerik, stokta_mi, id, session.get("lokanta_id", 1)))

        cur.execute("DELETE FROM urun_ekstralar WHERE urun_id = %s", (id,))

        for i in range(len(ekstra_adlar)):
            e_ad = ekstra_adlar[i].strip()
            if e_ad: 
                e_fiyat = float(ekstra_fiyatlar[i]) if ekstra_fiyatlar[i] else 0.0
                cur.execute("""
                    INSERT INTO urun_ekstralar (urun_id, ekstra_ad, ekstra_fiyat)
                    VALUES (%s, %s, %s)
                """, (id, e_ad, e_fiyat))

        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"GÜNCELLEME HATASI: {e}")
        return "Güncelleme sırasında hata oluştu!", 500
    finally:
        cur.close()
        conn.close()

    return redirect("/admin/urunlerim")

@app.route("/admin/urunlerim")
@login_required
def admin_urunlerim_sayfasi():
    l_id = session.get("lokanta_id")
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT * FROM kategoriler WHERE lokanta_id = %s ORDER BY sira ASC", (l_id,))
    kategoriler = cur.fetchall()

    cur.execute("""
        SELECT u.*, k.ad as kat_ad 
        FROM urunler u 
        LEFT JOIN kategoriler k ON u.kategori_id = k.id 
        WHERE u.lokanta_id = %s 
        ORDER BY k.sira, u.ad
    """, (l_id,))
    urunler = cur.fetchall()

    cur.close()
    conn.close()
    
    return render_template("admin_urunlerim.html", kategoriler=kategoriler, urunler=urunler)

@app.route("/garson-cagir")
def garson_cagir():
    masa_no = session.get('masa_no', 'Test-1')
    lokanta_id = session.get('lokanta_id', 1) 

    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        cur.execute("""
            INSERT INTO siparisler (lokanta_id, masa_no, toplam_tutar, durum) 
            VALUES (%s, %s, %s, %s)
        """, (lokanta_id, str(masa_no), 0.0, 'Garson Çağırıyor'))
        
        conn.commit()
        print(f"🔔 Masa {masa_no} için garson çağrısı başarıyla kaydedildi.")
        socketio.emit('yeni_siparis', {'data': 'Garson Çağrısı'}, namespace='/')
        return "OK", 200
        
    except Exception as e:
        conn.rollback()
        print(f"❌ Garson Çağırma Hatası: {e}")
        return "Hata", 500
    finally:
        cur.close()
        conn.close()

@app.route("/api/siparis-tamamla/<int:id>", methods=["POST", "GET"])
def api_siparis_tamamla(id):
    l_id = session.get("lokanta_id")
    
    if not l_id:
        return jsonify({"success": False, "message": "Oturum kapalı"}), 401

    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        cur.execute("""
            UPDATE siparisler 
            SET durum = 'Tamamlandı' 
            WHERE id = %s AND lokanta_id = %s
        """, (id, l_id))
        
        conn.commit()

        return jsonify({"success": True, "message": "Sipariş teslim edildi!"})

    except Exception as e:
        conn.rollback()
        print(f"Hata: {e}")
        return jsonify({"success": False, "message": "İşlem başarısız"}), 500
    
    finally:
        cur.close()
        conn.close()

if __name__ == '__main__':
    socketio.run(app, debug=False, host='0.0.0.0', port=5000)