from flask import Flask, render_template, request, redirect, session, jsonify
import os
from functools import wraps
import psycopg2
from psycopg2.extras import RealDictCursor
import qrcode
import io
import base64
from flask_socketio import SocketIO, emit

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


def get_db_connection():
    conn = psycopg2.connect(
        host="localhost",
        database="menuflow_db",     # Sunucuda açtığımız isim
        user="gastro_admin",        # Sunucuda açtığımız kullanıcı
        password="X.3e!!a*dfghjklm.*WW3-.", 
        port="5432",
        cursor_factory=RealDictCursor
    )
    return conn


# TEST BAĞLANTI
try:
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('SELECT ad FROM lokantalar;')
    lokanta = cur.fetchone()
    print(f"Bağlantı Başarılı! Lokanta Adı: {lokanta['ad']}")
    cur.close()
    conn.close()
except Exception as e:
    print(f"Eyvah bağlantı patladı! Hata: {e}")


os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(QR_FOLDER, exist_ok=True)


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
    eposta = request.form.get("eposta")
    sifre = request.form.get("sifre")
    masa_sayisi = request.form.get("masa_sayisi", 1)
    
    # URL için slug oluşturma (Türkçe karakterleri temizler, boşlukları tire yapar)
    import re
    slug = ad.lower()
    tr_map = str.maketrans("çğıöşü ", "cgiosu-")
    slug = slug.translate(tr_map)
    slug = re.sub(r'[^a-z0-9-]', '', slug) # Sadece harf, rakam ve tire bırak
    
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO lokantalar (ad, eposta, sifre, slug, masa_sayisi, aktif_mi) 
            VALUES (%s, %s, %s, %s, %s, TRUE)
        """, (ad, eposta, sifre, slug, masa_sayisi))
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

    # QR'ları depolayacağımız liste
    qr_kodlar = []
    
    # Masa sayısı kadar QR üret
    for i in range(1, lokanta['masa_sayisi'] + 1):
        # Müşterinin gideceği asıl link (masa nosu ile beraber)
        # Örn: https://seninsiten.com/menu/donercimahmut?masa=1
        ipadres="http://46.225.230.249"
        url = f"{ipadres}/menu/{lokanta['slug']}/{i}"
        
        # QR Kod Oluşturma
        qr = qrcode.QRCode(version=1, box_size=10, border=2)
        qr.add_data(url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        
        # Görseli belleğe kaydet ve base64 formatına çevir (HTML'de göstermek için)
        buffered = io.BytesIO()
        img.save(buffered, format="PNG")
        img_str = base64.b64encode(buffered.getvalue()).decode()
        
        qr_kodlar.append({
            "masa_no": i,
            "qr_base64": img_str
        })

    return render_template("qr_print.html", lokanta=lokanta, qr_kodlar=qr_kodlar)

#-------------------------------------------------------------------------------
# GİRİŞ SAYFASI ROTASI
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email")
        sifre = request.form.get("password")
        
        conn = get_db_connection()
        cur = conn.cursor()
        # Senin tablondaki eposta ve sifre sütunlarına göre sorguluyoruz
        cur.execute("SELECT * FROM lokantalar WHERE eposta = %s AND sifre = %s", (email, sifre))
        user = cur.fetchone()
        cur.close()
        conn.close()

        if user:
            session["admin_logged_in"] = True
            session["lokanta_id"] = user['id'] # EN KRİTİK NOKTA BURASI!
            session["lokanta_ad"] = user['ad']
            return redirect("/admin")
        else:
            return "Hatalı giriş bilgileri!"
            
    return render_template("login.html")

# ÇIKIŞ ROTASI
@app.route("/logout")
def logout():
    session.pop("admin_logged_in", None)
    return redirect("/login")

# ---------- ANA SAYFA ----------
@app.route("/")
def index():
    l_slug = session.get("lokanta_slug")
    m_no = session.get("masa_no") # Session'dan masa numarasını da alıyoruz
    
    if l_slug and m_no:
        # Müşteriyi tam adrese gönder: /menu/donercimahmut/3
        return redirect(f"/menu/{l_slug}/{m_no}")
    
    # Eğer masa nosu yoksa ama slug varsa (nadiren olur) sadece menüye at
    if l_slug:
        return redirect(f"/menu/{l_slug}")
        
    return redirect("/login")

@app.route("/menu/<string:lokanta_slug>/<int:masa_no>")
def home(lokanta_slug, masa_no=0):
    conn = get_db_connection()
    cur = conn.cursor()

    # 1. Slug'dan hangi lokantada olduğumuzu bulalım
    cur.execute("SELECT * FROM lokantalar WHERE slug = %s", (lokanta_slug,))
    lokanta = cur.fetchone()

    if not lokanta:
        cur.close()
        conn.close()
        return "Böyle bir dükkan kayıtlı değil!", 404

    # Artık bu dükkanın ID'sini session'a atabiliriz
    session["lokanta_id"] = lokanta['id']
    session["masa_no"] = masa_no
    session["lokanta_slug"] = lokanta_slug
    
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

    return render_template("home.html", lokanta=lokanta, kategoriler=kategoriler, urunler=urunler)

# ---------- ADMIN PANEL ----------
@app.route("/admin")
def admin_ana_panel():
    if not session.get("admin_logged_in"):
        return redirect("/login")
    
    # Hangi lokanta giriş yaptıysa onun ID'sini alıyoruz
    l_id = session.get("lokanta_id")
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    # SADECE BU LOKANTAYA AİT ÜRÜNLERİ ÇEK
    cur.execute("SELECT * FROM urunler WHERE lokanta_id = %s", (l_id,))
    urunler = cur.fetchall()
    
    cur.close()
    conn.close()
    return render_template("admin.html", urunler=urunler, lokanta_ad=session.get("lokanta_ad"))

# ---------- ADMINurunekle PANEL ----------
@app.route("/adminurunekle", methods=["GET", "POST"])
@login_required
def admin_urunekle():
    # Session'dan lokanta_id'yi alıyoruz. Giriş yapmamışsa zaten login_required yakalar.
    lokanta_id = session.get("lokanta_id")
    
    if not lokanta_id:
        return redirect("/login") # Güvenlik önlemi

    conn = get_db_connection()
    cur = conn.cursor()

    if request.method == "POST":
        # ---------- KATEGORİ EKLEME (AJAX) ----------
        kategori_ad = request.form.get("kategori_ad")
        if kategori_ad:
            # Burada 'ON CONFLICT (ad) DO NOTHING' tehlikelidir çünkü 
            # Dönerci Mahmut'un 'İçecekler'i ile başkasınınki çakışabilir.
            # Tabloda (ad, lokanta_id) şeklinde UNIQUE CONSTRAINT varsa çalışır.
            cur.execute("""
                INSERT INTO kategoriler (ad, lokanta_id) 
                VALUES (%s, %s) 
                ON CONFLICT DO NOTHING
            """, (kategori_ad, lokanta_id))
            conn.commit()
            cur.close()
            conn.close()
            return "OK", 200

        # ---------- ÜRÜN EKLEME ----------
        ad = request.form["ad"]
        fiyat = float(request.form["fiyat"])
        icerik = request.form["icerik"]
        kategori_id = request.form.get("kategori")

        # Resim Kaydet
        file = request.files.get("resim")
        if file and file.filename != '':
            filename = file.filename
            file.save(os.path.join(UPLOAD_FOLDER, filename))
        else:
            filename = "default.jpg"

        # 1. ÜRÜNÜ KAYDET (Sadece bu lokantaya bağlı olarak)
        cur.execute("""
            INSERT INTO urunler (ad, fiyat, kategori_id, fotograf_url, aciklama, lokanta_id)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (ad, fiyat, int(kategori_id), filename, icerik, lokanta_id))
        
        yeni_urun_id = cur.fetchone()['id']

        # 2. EKSTRALARI AL VE KAYDET
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

    # GET İsteği: Sadece GİRİŞ YAPAN lokantanın kategorilerini çek
    cur.execute("SELECT * FROM kategoriler WHERE lokanta_id = %s ORDER BY ad ASC", (lokanta_id,))
    kategoriler = cur.fetchall()
    cur.close()
    conn.close()
    return render_template("admin_urunekle.html", kategoriler=kategoriler)

# ---------- ÜRÜN DETAY ----------
@app.route("/urun/<int:id>")
def urun_detay(id):
    conn = get_db_connection()
    cur = conn.cursor()
    
    # 1. Ürünün ana bilgilerini getir
    cur.execute("SELECT * FROM urunler WHERE id = %s", (id,))
    urun = cur.fetchone()
    
    if not urun:
        cur.close()
        conn.close()
        return "Ürün bulunamadı!", 404
        
    # 2. Ürüne ait ekstraları getir (Yeni tablodan çekiyoruz!)
    cur.execute("SELECT * FROM urun_ekstralar WHERE urun_id = %s", (id,))
    ekstralar = cur.fetchall()
    
    cur.close()
    conn.close()
    
    # HTML tarafına hem ürünü hem de ekstraları gönderiyoruz
    return render_template("urun.html", urun=urun, ekstralar=ekstralar)

# ---------- KATEGORİ DETAY (Ürün Listesi) ----------
@app.route("/kategori/<int:id>")
def kategori_sayfasi(id):
    conn = get_db_connection()
    cur = conn.cursor()

    # 1. Seçilen kategorinin adını alalım (Başlıkta göstermek için)
    cur.execute("SELECT ad FROM kategoriler WHERE id = %s", (id,))
    kategori = cur.fetchone()

    if not kategori:
        cur.close()
        conn.close()
        return "Kategori bulunamadı!", 404

    # 2. Bu kategoriye ait ürünleri çekelim
    # Sadece stokta olanları veya hepsini getirebilirsin, şimdilik hepsini çekiyoruz
    cur.execute("""
        SELECT * FROM urunler 
        WHERE kategori_id = %s 
        ORDER BY ad ASC
    """, (id,))
    urunler = cur.fetchall()

    cur.close()
    conn.close()
    
    return render_template("kategori.html", urunler=urunler, kategori_ad=kategori['ad'])

@app.route("/sepete-ekle", methods=["POST"])
def sepete_ekle():
    # 1. Sepet oturumu yoksa oluştur
    if "sepet" not in session:
        session["sepet"] = []
    
    # 2. Formdan gelen verileri yakala
    urun_id = request.form.get("urun_id")
    ad = request.form.get("urun_ad")
    # Gizli inputtan gelen (ürün + ekstralar dahil) toplam birim fiyat
    fiyat = float(request.form.get("fiyat", 0)) 
    adet = int(request.form.get("adet", 1))
    notum = request.form.get("not", "")
    ekstralar = request.form.getlist("ekstra") # ['Sos:5', 'Peynir:10'] gibi liste gelir
    resim = request.form.get("resim")

    # 3. Seçilen ekstraları metne dök (Arayüzde şık görünmesi için: "Sos, Peynir")
    ekstra_metni = ""
    if ekstralar:
        ekstra_isimleri = [e.split(':')[0] for e in ekstralar]
        ekstra_metni = ", ".join(ekstra_isimleri)

    # 4. Sepet objesini oluştur
    item = {
        "id": urun_id,
        "ad": ad,
        "ekstra_detay": ekstra_metni, # Görsel amaçlı ("Sos, Peynir")
        "fiyat": fiyat,               # Seçenekler dahil birim fiyat
        "adet": adet,
        "toplam": fiyat * adet,       # Toplam tutar
        "ekstra_ham": ",".join(ekstralar), # Veritabanına kaydetmek için ham hali ("Sos:5,Peynir:10")
        "not": notum,
        "resim": resim
    }
    
    # 5. Listeyi güncelle ve oturuma (Session) kaydet
    temp = session["sepet"]
    temp.append(item)
    session["sepet"] = temp
    session.modified = True # Flask'ın değişikliği kesin kaydetmesini sağlar
    
    return redirect("/sepet")

# --- 2. SEPET GÖRÜNTÜLEME ---
@app.route("/sepet")
def sepet():
    # 1. Oturumdan sepeti al, eğer boşsa boş liste dön
    sepet_listesi = session.get("sepet", [])
    
    # 2. Genel toplamı hesapla (Hassas hesaplama için float/decimal dikkat)
    # item["toplam"] her ürünün (fiyat * adet) sonucudur
    genel_toplam = sum(float(item["toplam"]) for item in sepet_listesi) if sepet_listesi else 0
    
    # 3. Şablonu (template) gönder
    # Toplamı iki basamaklı (0.00) formatta gönderirsek daha profesyonel durur
    return render_template("sepet.html", 
                           sepet=sepet_listesi, 
                           toplam=f"{genel_toplam:.2f}")

# --- 3. SEPETTEN SİLME ---
@app.route("/sepet-sil/<int:index>")
def sepet_sil(index):
    if "sepet" in session:
        # 1. Mevcut sepeti bir değişkene kopyala
        temp = session["sepet"]
        
        # 2. Index kontrolü yap (Hatalı bir index gelirse uygulama patlamasın)
        if 0 <= index < len(temp):
            # Ürünü listeden çıkar
            temp.pop(index)
            
            # 3. Güncellenmiş listeyi tekrar session'a ata
            session["sepet"] = temp
            
            # 4. KRİTİK: Flask'a sepetin değiştiğini zorla bildir
            session.modified = True
            
    # Silme işleminden sonra tekrar sepet sayfasına dön
    return redirect("/sepet")

# --- 4. SİPARİŞİ TAMAMLA (KASAYA GÖNDER) ---
@app.route("/siparisi-tamamla", methods=["POST"])
def siparisi_tamamla():
    sepet_listesi = session.get("sepet", [])
    masa = session.get("masa_no", "Bilinmiyor")
    lokanta_id = session.get("lokanta_id")

    if not sepet_listesi:
        return redirect("/")

    genel_toplam = sum(float(item["toplam"]) for item in sepet_listesi)

    conn = get_db_connection()
    cur = conn.cursor()

    try:
        # 1. Lokanta bilgilerini al (Sarı çizgiyi ve slug sorununu çözer)
        cur.execute("SELECT slug FROM lokantalar WHERE id = %s", (lokanta_id,))
        lokanta_verisi = cur.fetchone()
        taze_slug = lokanta_verisi['slug'] if lokanta_verisi else "bilinmiyor"

        # 2. Ana Siparişi Kaydet
        cur.execute("""
            INSERT INTO siparisler (masa_no, toplam_tutar, durum, lokanta_id)
            VALUES (%s, %s, %s, %s)
            RETURNING id
        """, (str(masa), genel_toplam, 'Beklemede', lokanta_id))
        
        ana_siparis_id = cur.fetchone()['id']

        # 3. Sipariş Detaylarını Ekle
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

        # 4. Veritabanı Onayı (Commit)
        conn.commit()
        
        # 5. KASAYA BİLDİRİM GÖNDER (Kritik Düzeltme!)
        # Şimdilik oda (room) kısmını kaldırıyoruz ki tüm bağlı kasalar direkt duysun.
        # Terminalde görmek için bir de print ekledim.
        print(f"--> [SOCKET] Masa {masa} için sipariş bildirimi gönderiliyor...")
        socketio.emit('yeni_siparis', {'masa': masa})

        # 6. Sepeti temizle ve yönlendir
        session.pop("sepet", None)
        return render_template("siparis_onay.html", l_slug=taze_slug, m_no=masa)

    except Exception as e:
        if conn:
            conn.rollback()
        print(f"!!! Sipariş hatası: {e}")
        return "Sipariş verilirken bir hata oluştu!", 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()
        
# ---------- SİPARİŞ ----------
@app.route("/admin/kasa")
@login_required
def kasa_paneli():
    # Kasiyerin önüne boş sayfa gelir, içindeki JS birazdan API'ye istek atıp veriyi doldurur
    return render_template("kasa.html")

@app.route("/api/kasa_verisi")
@login_required
def kasa_verisi():
    l_id = session.get("lokanta_id")
    
    if not l_id:
        return jsonify({"error": "Yetkisiz erişim"}), 403

    conn = get_db_connection()
    cur = conn.cursor()

    # 1. DEĞİŞİKLİK: Filtreye 'Garson Çağırıyor' durumunu da ekledik
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

        # 2. DEĞİŞİKLİK: Durum bilgisini de pakete ekliyoruz ki JS tarafa "Bu garson çağrısıdır" diyebilelim
        sonuc.append({
            "id": s['id'],
            "masa_no": s['masa_no'],
            "toplam_tutar": float(s['toplam_tutar']),
            "durum": s['durum'], # BU ÇOK ÖNEMLİ!
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
    
    # 1. Ürün bilgilerini çek
    cur.execute("SELECT * FROM urunler WHERE id = %s AND lokanta_id = %s", (id, session.get("lokanta_id", 1)))
    urun = cur.fetchone()
    
    if not urun:
        return "Ürün bulunamadı!", 404

    # 2. Bu ürüne ait ekstraları çek
    cur.execute("SELECT ekstra_ad, ekstra_fiyat FROM urun_ekstralar WHERE urun_id = %s", (id,))
    ekstralar = cur.fetchall() # Bu bize liste döner: [{'ekstra_ad': 'Sos', 'ekstra_fiyat': 5}, ...]

    # 3. Tüm kategorileri çek (Select box için)
    cur.execute("SELECT * FROM kategoriler WHERE lokanta_id = %s", (session.get("lokanta_id", 1),))
    kategoriler = cur.fetchall()
    
    cur.close()
    conn.close()
    
    return render_template("admin_urunekle.html", urun=urun, kategoriler=kategoriler, ekstralar=ekstralar)

import os

@app.route("/urun-guncelle/<int:id>", methods=["POST"])
@login_required
def urun_guncelle(id):
    # 1. Form Verilerini Al
    ad = request.form.get("ad")
    fiyat = float(request.form.get("fiyat", 0))
    icerik = request.form.get("icerik", "")
    kategori_id = request.form.get("kategori")
    stokta_mi = True if request.form.get("stok") == "1" else False

    # Ekstra listelerini al (urun_ekstra tablosuna gidecekler)
    ekstra_adlar = request.form.getlist("ekstra_ad[]")
    ekstra_fiyatlar = request.form.getlist("ekstra_fiyat[]")

    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        # 2. Resim İşlemleri
        cur.execute("SELECT fotograf_url FROM urunler WHERE id=%s", (id,))
        eski_resim = cur.fetchone()["fotograf_url"]
        
        file = request.files.get("resim")
        if file and file.filename != '':
            filename = file.filename
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        else:
            filename = eski_resim

        # 3. Ana Ürünü Güncelle (urunler tablosu)
        cur.execute("""
            UPDATE urunler 
            SET ad=%s, fiyat=%s, kategori_id=%s, fotograf_url=%s, aciklama=%s, stokta_mi=%s
            WHERE id=%s AND lokanta_id=%s
        """, (ad, fiyat, int(kategori_id), filename, icerik, stokta_mi, id, session.get("lokanta_id", 1)))

        # 4. EKSTRALARI DÜZENLE (urun_ekstra tablosu)
        # Önce bu ürünün tüm eski ekstralarını silelim
        cur.execute("DELETE FROM urun_ekstralar WHERE urun_id = %s", (id,))

        # Şimdi formdan gelenleri tek tek ekleyelim
        for i in range(len(ekstra_adlar)):
            e_ad = ekstra_adlar[i].strip()
            if e_ad: # İsim boş değilse ekle
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

    # Önce kategorileri alalım
    cur.execute("SELECT * FROM kategoriler WHERE lokanta_id = %s ORDER BY sira ASC", (l_id,))
    kategoriler = cur.fetchall()

    # Sonra ürünleri kategorisiyle beraber alalım
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
        # Tek bir INSERT yeterli. Detay tablosuna girmeye gerek yok.
        cur.execute("""
            INSERT INTO siparisler (lokanta_id, masa_no, toplam_tutar, durum) 
            VALUES (%s, %s, %s, %s)
        """, (lokanta_id, str(masa_no), 0.0, 'Garson Çağırıyor'))
        
        conn.commit()
        print(f"🔔 Masa {masa_no} için garson çağrısı başarıyla kaydedildi.")
        socketio.emit('yeni_siparis', {'data': 'Garson Çağrısı'}, namespace='/') # KASAYI UYAR!
        return "OK", 200
        
    except Exception as e:
        conn.rollback()
        print(f"❌ Garson Çağırma Hatası: {e}")
        return "Hata", 500
    finally:
        cur.close()
        conn.close()
# Siparişi "Tamamlandı" olarak işaretlemek için küçük bir buton yolu
@app.route("/api/siparis-tamamla/<int:id>", methods=["POST", "GET"])
def api_siparis_tamamla(id):
    l_id = session.get("lokanta_id")
    
    if not l_id:
        return jsonify({"success": False, "message": "Oturum kapalı"}), 401

    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        # 1. Veritabanını güncelle: Siparişi 'Tamamlandı' yap
        # lokanta_id kontrolü ekliyoruz ki kimse başkasının siparişini kapatamasın
        cur.execute("""
            UPDATE siparisler 
            SET durum = 'Tamamlandı' 
            WHERE id = %s AND lokanta_id = %s
        """, (id, l_id))
        
        conn.commit()

        # 2. SOKET BİLDİRİMİ (Opsiyonel): 
        # Eğer SocketIO kullanıyorsan, listeyi herkes için yeniletmek istersen:
        # socketio.emit('siparis_guncellendi', {'lokanta_id': l_id})

        return jsonify({"success": True, "message": "Sipariş teslim edildi!"})

    except Exception as e:
        conn.rollback()
        print(f"Hata: {e}")
        return jsonify({"success": False, "message": "İşlem başarısız"}), 500
    
    finally:
        cur.close()
        conn.close()
# ---------- QR ----------
if __name__ == '__main__':
    # Sunucuda debug=False olmalı
    socketio.run(app, debug=False, host='0.0.0.0', port=5000)