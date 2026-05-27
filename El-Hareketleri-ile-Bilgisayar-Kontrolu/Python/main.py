import os
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"


import cv2
import numpy as np
import mediapipe as mp
import math
import time
import ctypes
import pyautogui
import json
import subprocess
import pyodbc
from datetime import datetime

# ── Ayarlar ────────────────────────────────────────────────────────────────
SMOOTHENING         = 7
TIK_MESAFE          = 40
TIK_BEKLEME         = 1.0
SCROLL_ESIK         = 0.04   # Yüksek = daha az hassas, el titremesi scroll yapmaz
SCROLL_HIZ          = 16
KAPAT_SURE          = 3.0
SES_BEKLEME         = 0.4
EKRAN_GORUNTUSU_DIR = "."
KALIBRASYON_DOSYA   = "kalibrasyon.json"
MOD_DEGISTIR_SURE   = 2.5   # Sol el yumruk kaç sn tutulunca mod değişsin


# ── Veritabanı Bağlantısı ──────────────────────────────────────────────────
# SQL Server hazır değilse program kapanmasın diye try/except kullanıldı.
DB_AKTIF = True
conn = None
cursor = None

try:
    conn = pyodbc.connect(
        "Driver={SQL Server};"
        "Server=localhost\\SQLEXPRESS;"
        "Database=ElKontrolDB;"
        "Trusted_Connection=True;"
    )
    cursor = conn.cursor()
    print("Veritabanı bağlantısı başarılı.")
except Exception as e:
    DB_AKTIF = False
    print("Veritabanı bağlantısı kurulamadı. Program veritabanı olmadan devam edecek.")
    print("Hata:", e)


def hareket_kaydet(hareket_adi, mod_adi="-", el_tipi="-"):
    """Algılanan hareketleri SQL Server'daki HareketKayitlari tablosuna kaydeder."""
    if not DB_AKTIF or cursor is None:
        return

    try:
        cursor.execute(
            "INSERT INTO HareketKayitlari (HareketAdi, ModAdi, ElTipi) VALUES (?, ?, ?)",
            (hareket_adi, mod_adi, el_tipi)
        )
        conn.commit()
    except Exception as e:
        print("Hareket veritabanına kaydedilemedi:", e)

# ── Panel boyutları ─────────────────────────────────────────────────────────
UST_PANEL_H = 50
YAN_PANEL_W = 260
CAM_W       = 640
CAM_H       = 480
pyautogui.PAUSE = 0

kamera = cv2.VideoCapture(0)
kamera.set(cv2.CAP_PROP_FRAME_WIDTH,  CAM_W)
kamera.set(cv2.CAP_PROP_FRAME_HEIGHT, CAM_H)
kamera.set(cv2.CAP_PROP_FPS, 60)

kamera_aktif = True
kamera_kapat_basladi = None

mp_el    = mp.solutions.hands
mp_cizim = mp.solutions.drawing_utils

eller = mp_el.Hands(
    static_image_mode=False,
    max_num_hands=2,
    model_complexity=0,
    min_detection_confidence=0.6,
    min_tracking_confidence=0.5
)

user32          = ctypes.windll.user32
ekran_genislik  = user32.GetSystemMetrics(0)
ekran_yukseklik = user32.GetSystemMetrics(1)

VK_VOLUME_UP    = 0xAF
VK_VOLUME_DOWN  = 0xAE
VK_VOLUME_MUTE  = 0xAD
KEYEVENTF_KEYUP = 0x0002

def tus_gonder(vk):
    ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
    ctypes.windll.user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)

def ses_yukari(): tus_gonder(VK_VOLUME_UP)
def ses_asagi():  tus_gonder(VK_VOLUME_DOWN)

def fare_hareket(x, y):
    nx = int(x * 65535 / ekran_genislik)
    ny = int(y * 65535 / ekran_yukseklik)
    ctypes.windll.user32.mouse_event(0x0001 | 0x8000, nx, ny, 0, 0)

def fare_bas():   ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)
def fare_birak(): ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)

# ── Jest tespiti ───────────────────────────────────────────────────────────
def parmak_acik_mi(lm, uc_i, pip_i):
    avuc = lm.landmark[0]
    uc   = lm.landmark[uc_i]
    pip  = lm.landmark[pip_i]
    return math.hypot(uc.x-avuc.x, uc.y-avuc.y) > math.hypot(pip.x-avuc.x, pip.y-avuc.y)

def acik_parmak_sayisi(lm):
    return sum(1 for u,p in [(8,6),(12,10),(16,14),(20,18)] if parmak_acik_mi(lm,u,p))

def yumruk_mu(lm):    return acik_parmak_sayisi(lm) <= 1
def avuc_acik_mi(lm): return acik_parmak_sayisi(lm) >= 4

def serce_tek_mu(lm):
    """Sadece serçe parmak açık, diğerleri (işaret+orta+yüzük+baş) kapalı."""
    serce  = parmak_acik_mi(lm, 20, 18)
    isaret = parmak_acik_mi(lm, 8,  6)
    orta   = parmak_acik_mi(lm, 12, 10)
    yuzuk  = parmak_acik_mi(lm, 16, 14)
    bas_ucu  = lm.landmark[4]
    isr_dibi = lm.landmark[5]
    bas_acik = math.hypot(bas_ucu.x - isr_dibi.x, bas_ucu.y - isr_dibi.y) > 0.09
    return serce and not isaret and not orta and not yuzuk and not bas_acik


def basparmak_tek_mu(lm):
    isaret = parmak_acik_mi(lm, 8, 6)
    orta   = parmak_acik_mi(lm, 12, 10)
    yuzuk  = parmak_acik_mi(lm, 16, 14)
    serce  = parmak_acik_mi(lm, 20, 18)

    bas_ucu = lm.landmark[4]
    isr_dibi = lm.landmark[5]

    bas_mesafe = math.hypot(
        bas_ucu.x - isr_dibi.x,
        bas_ucu.y - isr_dibi.y
    )

    bas_acik = bas_mesafe > 0.10

    return bas_acik and not isaret and not orta and not yuzuk and not serce

def scroll_jesti_mu(lm):
    """
    Scroll jesti: işaret + orta parmak açık olmalı.
    Uçlar arasındaki mesafeye göre scroll yönü belirlenir:
    - Parmaklar birleşince → aşağı scroll
    - Parmaklar açılınca  → yukarı scroll
    """
    isaret = parmak_acik_mi(lm, 8,  6)
    orta   = parmak_acik_mi(lm, 12, 10)
    return isaret and orta

def scroll_mesafe_al(lm):
    """İşaret + orta parmak uçları arası normalize mesafe."""
    isr_uc  = lm.landmark[8]
    orta_uc = lm.landmark[12]
    return math.hypot(isr_uc.x - orta_uc.x, isr_uc.y - orta_uc.y)

def uc_parmak_mu(lm):
    """
    Tam 3 parmak: işaret + orta + yüzük açık.
    Serçe ve baş parmak KAPALI olmali — 5 parmakla karışmasın.
    Hem sol hem sağ elde çalışır.
    """
    isaret = parmak_acik_mi(lm, 8,  6)
    orta   = parmak_acik_mi(lm, 12, 10)
    yuzuk  = parmak_acik_mi(lm, 16, 14)
    serce  = parmak_acik_mi(lm, 20, 18)
    # Baş parmak: ucu ile işaret parmağı dibi arasındaki mesafe küçükse kapalı
    bas_ucu  = lm.landmark[4]
    isr_dibi = lm.landmark[5]
    bas_mesafe = math.hypot(bas_ucu.x - isr_dibi.x, bas_ucu.y - isr_dibi.y)
    bas_acik = bas_mesafe > 0.08   # 0.08'den büyükse açık sayılır
    return isaret and orta and yuzuk and not serce and not bas_acik

def dort_parmak_jesti(lm):
    """
    PC kapatma jesti:
    Sağ elde 4 parmak açık, baş parmak kapalı olmalı.
    İşaret + orta + yüzük + serçe açık, baş parmak kapalı.
    """
    isaret = parmak_acik_mi(lm, 8, 6)
    orta   = parmak_acik_mi(lm, 12, 10)
    yuzuk  = parmak_acik_mi(lm, 16, 14)
    serce  = parmak_acik_mi(lm, 20, 18)

    bas_ucu  = lm.landmark[4]
    isr_dibi = lm.landmark[5]

    bas_mesafe = math.hypot(
        bas_ucu.x - isr_dibi.x,
        bas_ucu.y - isr_dibi.y
    )

    bas_acik = bas_mesafe > 0.09

    return isaret and orta and yuzuk and serce and not bas_acik

# ── Mod Sistemi ─────────────────────────────────────────────────────────────
# MODLAR: her modda sadece o modun jestleri çalışır
MODLAR = ["MOUSE", "SISTEM", "EKRAN"]
MOD_RENK = {
    "MOUSE" : (0, 220, 120),    # Yeşil
    "SISTEM": (0, 255, 255),    # Sarı
    "EKRAN" : (255, 200, 0),    # Mavi
}
MOD_IKON = {
    "MOUSE" : "MOUSE MODU",
    "SISTEM": "SISTEM KONTROLU",
    "EKRAN" : "EKRAN MODU",
}
MOD_ACIKLAMA = {
    "MOUSE" : ["Sag el: Fare hareket",
               "Sag Bas+Isr -> Sol tik",
               "Sag Bas+Ort -> Sag tik",
               "Sag yumruk -> Drag&Drop",
               "Sol Isr+Orta yakin -> Scroll Asagi",
               "Sol Bas+Isr yakin -> Scroll Yukari"],
    "SISTEM": ["SAG EL: Bas+Isaret mesafe",
               "  Uzaklas -> Ses artar",
               "  Yaklasir -> Ses azalir",
               "SOL EL: Bas+Isaret mesafe",
               "  Uzaklas -> Parlaklik +",
               "  Yaklasir -> Parlaklik -"],
    "EKRAN" : ["3 parmak -> Tam SS",
               "Alan SS: yumrukla basla",
               "Isaret ucuyla surukle",
               "Eli ac -> Alan SS al",
               "Sag 4 parmak -> PC Kapat",
               "Basparmak 3sn -> Uyku",
               "Sol 5 parmak 2sn -> Kamera Kapat"],
}

aktif_mod          = "MOUSE"
mod_degistir_basladi = None   # Sol avuç ne zaman açılmaya başladı
mod_bildirim_zaman  = 0        # Mod değişince büyük yazı ne zaman çıktı
mod_bildirim_yazi   = ""

def sonraki_mod():
    idx = MODLAR.index(aktif_mod)
    return MODLAR[(idx + 1) % len(MODLAR)]

# ── Kalibrasyon ─────────────────────────────────────────────────────────────
def kalibrasyon_yukle():
    if os.path.exists(KALIBRASYON_DOSYA):
        with open(KALIBRASYON_DOSYA) as f:
            veri = json.load(f)
            print(f"Kalibrasyon yüklendi: '{veri['mouse_el']}'")
            return veri["mouse_el"]
    return None

def kalibrasyon_kaydet(etiket):
    with open(KALIBRASYON_DOSYA, "w") as f:
        json.dump({"mouse_el": etiket}, f)
    print(f"Kalibrasyon kaydedildi: '{etiket}'")

MOUSE_EL_ETIKETI = kalibrasyon_yukle()
kalibrasyon_modu = MOUSE_EL_ETIKETI is None

# ── Görsel arayüz ───────────────────────────────────────────────────────────
RENK_BG     = (0, 0, 0)
RENK_PANEL  = (0, 0, 0)
RENK_BORDER = (0, 0, 0)
RENK_BASLIK = (0, 255, 255)
RENK_PASIF  = (0, 0, 0)
RENK_VURGU  = (0, 255, 255)

def panel_ciz(img, x, y, w, h, renk=RENK_PANEL):
    ov = img.copy()
    cv2.rectangle(ov, (x,y), (x+w,y+h), renk, -1)
    cv2.addWeighted(ov, 1.0, img, 0.0, 0, img)
    cv2.rectangle(img, (x,y), (x+w,y+h), RENK_BORDER, 1)

def bar_ciz(img, x, y, w, h, oran, renk):
    cv2.rectangle(img, (x,y), (x+w,y+h), (40,40,60), -1)
    dolu = int(min(max(oran,0),1) * w)
    if dolu > 0:
        cv2.rectangle(img, (x,y), (x+dolu,y+h), renk, -1)
    cv2.rectangle(img, (x,y), (x+w,y+h), RENK_BORDER, 1)

def ses_seviyesi_al():
    try:
        from ctypes import POINTER, cast
        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
        devices   = AudioUtilities.GetSpeakers()
        interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        volume    = cast(interface, POINTER(IAudioEndpointVolume))
        return int(volume.GetMasterVolumeLevelScalar() * 100)
    except Exception:
        return -1

# ── Durum değişkenleri ──────────────────────────────────────────────────────
prev_x, prev_y      = 0, 0
son_sol_tik         = 0
son_sag_tik         = 0
drag_aktif          = False
drag_hazir_zaman    = None   # Yumruk ne zaman yapıldı (drag için bekleme)
sol_el_onceki_y     = None
scroll_onceki_mesafe = None   # Scroll için ayrı değişken
iki_yumruk_basladi  = None
capraz_basladi      = None   # Çapraz jest başlangıcı
uyku_basladi        = None   # Uyku modu jest başlangıcı
alan_ss_baslangic   = None   # Alan SS başlangıç noktası (ekran koordinatı)
son_parlaklik_guncelle = 0
son_parlaklik_deger    = -1
son_ses             = 0   # Ses tuş fallback için zamanlayıcı

# ── pycaw bir kez init et ──────────────────────────────────────────────────
volume_controller = None
try:
    from ctypes import POINTER, cast
    from comtypes import CLSCTX_ALL
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
    _dev  = AudioUtilities.GetSpeakers()
    _intf = _dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    volume_controller = cast(_intf, POINTER(IAudioEndpointVolume))
    print("pycaw hazir.")
except Exception as e:
    print(f"pycaw yok, tus fallback: {e}")
son_ekran_g         = 0
ekran_moda_giris    = 0   # Ekran moduna ne zaman girildi (anlık tetiklenme önlenir)
ekran_flash         = 0
bilgi_mesaji        = ""
bilgi_zaman         = 0
fps_sayac           = 0
fps_zaman           = time.time()
fps                 = 0
son_ses_guncelle    = 0
ses_seviye          = ses_seviyesi_al()

jest_durum = {k: False for k in
    ["mouse","sol_tik","sag_tik","drag","scroll","ses_yukari","ses_asagi","ekran_g","el_yok"]}

def bilgi_goster(mesaj):
    global bilgi_mesaji, bilgi_zaman
    bilgi_mesaji = mesaj; bilgi_zaman = time.time()
    print(mesaj)

# ── Ana döngü ───────────────────────────────────────────────────────────────
while True:
    ret, cam = kamera.read()
    if not ret: break

    cam = cv2.flip(cam, 1)
    ch, cw, _ = cam.shape

    cam.flags.writeable = False
    rgb   = cv2.cvtColor(cam, cv2.COLOR_BGR2RGB)
    sonuc = eller.process(rgb)
    cam.flags.writeable = True

    simdi         = time.time()
    yumruk_sayisi = 0
    for k in jest_durum: jest_durum[k] = False
    jest_durum["el_yok"] = True

    if sonuc.multi_hand_landmarks and sonuc.multi_handedness:
        jest_durum["el_yok"] = False

        for el_lm, el_tipi in zip(sonuc.multi_hand_landmarks, sonuc.multi_handedness):
            label = el_tipi.classification[0].label

            # ── EKRAN MODU: Kamera kapatma / SOL EL 5 PARMAK 2sn ───────────
            # Bu kod sağ el bloğunun DIŞINDA çalışır.
            # Mouse eli olmayan el 5 parmak açılırsa kamera/program kapanır.
            if aktif_mod == "EKRAN":
                gecici_is_mouse_el = (MOUSE_EL_ETIKETI is not None and label == MOUSE_EL_ETIKETI)

                if (not gecici_is_mouse_el) and avuc_acik_mi(el_lm):
                    if kamera_kapat_basladi is None:
                        kamera_kapat_basladi = simdi

                    gecen_kamera = simdi - kamera_kapat_basladi
                    kalan_kamera = max(0.0, 2.0 - gecen_kamera)

                    cv2.putText(
                        cam,
                        f"KAMERA KAPANIYOR {kalan_kamera:.1f}s",
                        (20, 80),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.8,
                        (0, 255, 255),
                        2
                    )

                    if gecen_kamera >= 2.0:
                        bilgi_goster("Kamera kapatildi")
                        hareket_kaydet("Kamera Kapatildi", aktif_mod, "Sol El")
                        kamera.release()
                        cv2.destroyAllWindows()
                        exit()
                else:
                    kamera_kapat_basladi = None

            # Kalibrasyon
            if kalibrasyon_modu:
                MOUSE_EL_ETIKETI = label
                kalibrasyon_kaydet(MOUSE_EL_ETIKETI)
                kalibrasyon_modu = False

            el_yumruk   = yumruk_mu(el_lm)
            is_mouse_el = (label == MOUSE_EL_ETIKETI)
            if el_yumruk: yumruk_sayisi += 1

            # ── DİĞER EL (SOL EL) ──────────────────────────────────────────
            if not is_mouse_el:
                el_yumruk_sol = yumruk_mu(el_lm)

                # SISTEM modunda sol yumruk = mod değiştirme YOK (parlaklık için)
                if el_yumruk_sol and aktif_mod != "SISTEM":
                    sol_el_onceki_y = None
                    if mod_degistir_basladi is None:
                        mod_degistir_basladi = simdi
                    gecen = simdi - mod_degistir_basladi

                    bar_uzun = int((gecen / MOD_DEGISTIR_SURE) * (cw - 40))
                    cv2.rectangle(cam, (20, 10), (cw-20, 28), (40,40,60), -1)
                    cv2.rectangle(cam, (20, 10), (20+min(bar_uzun,cw-40), 28),
                                  MOD_RENK[sonraki_mod()], -1)
                    cv2.putText(cam, f"-> {sonraki_mod()}",
                                (25, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255,255,255), 1)

                    if gecen >= MOD_DEGISTIR_SURE:
                        aktif_mod = sonraki_mod()
                        mod_degistir_basladi = None
                        mod_bildirim_yazi = f"MOD: {aktif_mod}"
                        mod_bildirim_zaman = simdi
                        bilgi_goster(f"Mod degisti: {aktif_mod}")
                        hareket_kaydet("Mod Degisti", aktif_mod, "Sol El")
                        sol_el_onceki_y = None
                        if aktif_mod == "EKRAN":
                            ekran_moda_giris = simdi   # Anlık tetiklenmeyi önle

                # Yumruk değilse VEYA SISTEM modundaysa → jestleri çalıştır
                else:
                    mod_degistir_basladi = None

                    
                    # ── MOUSE MODUNDA SCROLL: SADECE SOL EL ───────────────
                    # Sağ el mouse/tık için kalır. Scroll yalnızca sol/diğer elde çalışır.
                    if aktif_mod == "MOUSE":
                        isaret_acik = parmak_acik_mi(el_lm, 8, 6)
                        orta_acik   = parmak_acik_mi(el_lm, 12, 10)

                        isr_uc  = el_lm.landmark[8]
                        orta_uc = el_lm.landmark[12]
                        bas_uc  = el_lm.landmark[4]

                        iki_mesafe = math.hypot(
                            isr_uc.x - orta_uc.x,
                            isr_uc.y - orta_uc.y
                        )

                        bas_isaret_mesafe = math.hypot(
                            bas_uc.x - isr_uc.x,
                            bas_uc.y - isr_uc.y
                        )

                        px8  = int(isr_uc.x * cw)
                        py8  = int(isr_uc.y * ch)
                        px12 = int(orta_uc.x * cw)
                        py12 = int(orta_uc.y * ch)
                        pxb  = int(bas_uc.x * cw)
                        pyb  = int(bas_uc.y * ch)

                        # AŞAĞI SCROLL: sol elde işaret + orta yakın
                        if isaret_acik and orta_acik and iki_mesafe < 0.055:
                            pyautogui.scroll(-SCROLL_HIZ)
                            cv2.line(cam, (px8, py8), (px12, py12), (0, 255, 255), 3)
                            cv2.putText(
                                cam,
                                "SOL EL SCROLL ASAGI",
                                (20, ch - 35),
                                cv2.FONT_HERSHEY_SIMPLEX,
                                1,
                                (0, 255, 255),
                                2
                            )
                            jest_durum["scroll"] = True
                            hareket_kaydet("Scroll Asagi", aktif_mod, "Sol El")
                            time.sleep(0.03)

                        # YUKARI SCROLL: sol elde baş + işaret yakın
                        elif bas_isaret_mesafe < 0.06:
                            pyautogui.scroll(SCROLL_HIZ)
                            cv2.line(cam, (pxb, pyb), (px8, py8), (0, 255, 255), 3)
                            cv2.putText(
                                cam,
                                "SOL EL SCROLL YUKARI",
                                (20, ch - 35),
                                cv2.FONT_HERSHEY_SIMPLEX,
                                1,
                                (0, 255, 255),
                                2
                            )
                            jest_durum["scroll"] = True
                            hareket_kaydet("Scroll Yukari", aktif_mod, "Sol El")
                            time.sleep(0.03)

                    # ── SİSTEM MODU: sol el baş+işaret → parlaklık ──────────
                    if aktif_mod == "SISTEM":
                        sol_el_onceki_y = None
                        bas_lm    = el_lm.landmark[4]
                        isaret_lm = el_lm.landmark[8]
                        MIN_M, MAX_M = 0.05, 0.30
                        mesafe_p = math.hypot(bas_lm.x - isaret_lm.x,
                                              bas_lm.y - isaret_lm.y)
                        oran_p = max(0.0, min(1.0, (mesafe_p - MIN_M) / (MAX_M - MIN_M)))
                        hedef_parlak = int(oran_p * 100)

                        try:
                            # Sadece 0.3sn'de bir ve değer 3'ten fazla değişince güncelle
                            if (abs(hedef_parlak - son_parlaklik_deger) > 3 and
                                    simdi - son_parlaklik_guncelle > 0.3):
                                subprocess.Popen(
                                    ["powershell", "-Command",
                                     f"(Get-WmiObject -Namespace root/WMI -Class "
                                     f"WmiMonitorBrightnessMethods).WmiSetBrightness(1,{hedef_parlak})"],
                                    stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL
                                )
                                son_parlaklik_deger    = hedef_parlak
                                son_parlaklik_guncelle = simdi
                        except Exception:
                            pass

                        # Görsel: dikey bar (sağdaki)
                        x_bas_px = int(bas_lm.x * cw)
                        y_bas_px = int(bas_lm.y * ch)
                        x_isr_px = int(isaret_lm.x * cw)
                        y_isr_px = int(isaret_lm.y * ch)
                        cv2.line(cam,(x_bas_px,y_bas_px),(x_isr_px,y_isr_px),(0,0,255),3)
                        cv2.circle(cam,(x_bas_px,y_bas_px),8,(0,0,255),-1)
                        cv2.circle(cam,(x_isr_px,y_isr_px),8,(0,0,255),-1)
                        bar_x2 = cw - 90
                        bar_h2 = 250; bar_top2 = 150
                        dolu2  = int(oran_p * bar_h2)
                        cv2.rectangle(cam,(bar_x2,bar_top2),(bar_x2+40,bar_top2+bar_h2),(50,50,50),-1)
                        cv2.rectangle(cam,(bar_x2,bar_top2),(bar_x2+40,bar_top2+bar_h2),(200,200,200),2)
                        if dolu2 > 0:
                            cv2.rectangle(cam,(bar_x2+2,bar_top2+bar_h2-dolu2),
                                          (bar_x2+38,bar_top2+bar_h2-2),(0,0,255),-1)
                        cv2.putText(cam,f"{hedef_parlak}%",(bar_x2-5,bar_top2+bar_h2+30),
                                    cv2.FONT_HERSHEY_SIMPLEX,0.9,(255,255,255),2)
                        cv2.putText(cam,"PARLAK",(bar_x2-10,bar_top2-10),
                                    cv2.FONT_HERSHEY_SIMPLEX,0.5,(0,0,255),1)

                    # ── EKRAN MODU ───────────────────────────────────────────
                    elif aktif_mod == "EKRAN":
                        sol_el_onceki_y = None
                        capraz_aktif = (capraz_basladi is not None)
                        mod_hazir    = (simdi - ekran_moda_giris > 1.5)

                        # Normal SS: 3 parmak jesti
                        if (not capraz_aktif and mod_hazir
                                and uc_parmak_mu(el_lm)
                                and simdi - son_ekran_g > 2.0):
                            dosya = os.path.join(EKRAN_GORUNTUSU_DIR,
                                        f"ekran_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
                            pyautogui.screenshot(dosya)
                            son_ekran_g = simdi; ekran_flash = simdi
                            jest_durum["ekran_g"] = True
                            bilgi_goster("Kaydedildi: Tam ekran SS")
                            hareket_kaydet("Tam Ekran Goruntusu", aktif_mod, "Sol El")

                    else:
                        sol_el_onceki_y = None

            # ── MOUSE ELİ ──────────────────────────────────────────────────
            if is_mouse_el:
                jest_durum["mouse"] = True
                bas    = el_lm.landmark[4]
                isaret = el_lm.landmark[8]
                orta   = el_lm.landmark[12]
                x_bas,    y_bas    = int(bas.x*cw),    int(bas.y*ch)
                x_isaret, y_isaret = int(isaret.x*cw), int(isaret.y*ch)
                x_orta,   y_orta   = int(orta.x*cw),   int(orta.y*ch)
                mesafe_sol = math.hypot(x_bas-x_isaret, y_bas-y_isaret)
                mesafe_sag = math.hypot(x_bas-x_orta,   y_bas-y_orta)

                # Fare HER ZAMAN hareket eder (tüm modlarda)
                ex = isaret.x * ekran_genislik
                ey = isaret.y * ekran_yukseklik
                cx = prev_x + (ex - prev_x) / SMOOTHENING
                cy = prev_y + (ey - prev_y) / SMOOTHENING
                fare_hareket(cx, cy); prev_x, prev_y = cx, cy

                # ── SİSTEM MODU: sağ el baş+işaret mesafesi → ses ──────────
                if aktif_mod == "SISTEM":
                    # Ses ayarı: aralık genişletildi, el tam açılınca %100'e ulaşır.
                    MIN_M, MAX_M = 0.03, 0.38
                    mesafe_ses = math.hypot(bas.x - isaret.x, bas.y - isaret.y)
                    oran = (mesafe_ses - MIN_M) / (MAX_M - MIN_M)
                    oran = max(0.0, min(1.0, oran))
                    hedef_ses = int(oran * 100)
                    if hedef_ses > 97:
                        hedef_ses = 100
                        oran = 1.0

                    # pycaw ile ses ayarla (başlangıçta init edildi)
                    if volume_controller is not None:
                        try:
                            volume_controller.SetMasterVolumeLevelScalar(oran, None)
                            volume_controller.SetMute(1 if oran <= 0.01 else 0, None)
                            ses_seviye = hedef_ses
                        except Exception:
                            pass
                    else:
                        # pycaw yoksa tuş gönder
                        if simdi - son_ses > 0.15:
                            fark = hedef_ses - ses_seviye
                            if abs(fark) >= 3:
                                if fark > 0:
                                    ses_yukari()
                                    jest_durum["ses_yukari"] = True
                                else:
                                    ses_asagi()
                                    jest_durum["ses_asagi"] = True
                                son_ses = simdi
                                ses_seviye = max(0, min(100, ses_seviye + (3 if fark>0 else -3)))

                    # ── Görsel: parmaklar arası çizgi + daireler ───────────
                    cv2.line(cam, (x_bas, y_bas), (x_isaret, y_isaret), (0, 255, 255), 3)
                    cv2.circle(cam, (x_bas,    y_bas),    8, (0, 255, 255), -1)
                    cv2.circle(cam, (x_isaret, y_isaret), 8, (0, 255, 255), -1)

                    # ── Dikey ses barı (resimde olduğu gibi) ───────────────
                    bar_x     = 50          # barın sol kenarı
                    bar_y_top = 150         # barın üst noktası
                    bar_y_bot = 400         # barın alt noktası
                    bar_w     = 40          # bar genişliği
                    bar_h     = bar_y_bot - bar_y_top
                    dolu_h    = int(oran * bar_h)

                    # Dış çerçeve
                    cv2.rectangle(cam, (bar_x, bar_y_top),
                                  (bar_x + bar_w, bar_y_bot), (50, 50, 50), -1)
                    cv2.rectangle(cam, (bar_x, bar_y_top),
                                  (bar_x + bar_w, bar_y_bot), (200, 200, 200), 2)
                    # Dolum (alttan yukarı)
                    if dolu_h > 0:
                        cv2.rectangle(cam,
                                      (bar_x + 2, bar_y_bot - dolu_h),
                                      (bar_x + bar_w - 2, bar_y_bot - 2),
                                      (0, 255, 255), -1)
                    # Yüzde yazısı
                    cv2.putText(cam, f"{hedef_ses} %",
                                (bar_x - 5, bar_y_bot + 30),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)
                    cv2.putText(cam, "SES",
                                (bar_x, bar_y_top - 10),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,0,255), 1)

                
                # ── EKRAN modunda kamera kapatma: sag el 5 parmak 2sn ──────
                if False and aktif_mod == "EKRAN" and label == "Left" and avuc_acik_mi(el_lm):

                    if kamera_kapat_basladi is None:
                        kamera_kapat_basladi = simdi

                    gecen_kamera = simdi - kamera_kapat_basladi

                    cv2.putText(
                        cam,
                        f"SOL EL 5 PARMAK: KAMERA KAPANIYOR {max(0, 2.0-gecen_kamera):.1f}s",
                        (20, 80),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.8,
                        (0,0,255),
                        2
                    )

                    if gecen_kamera >= 2.0:
                        bilgi_goster("Kamera kapatildi")
                        hareket_kaydet(
                            "Kamera Kapatildi",
                            aktif_mod,
                            "Sag El"
                        )

                        kamera.release()
                        cv2.destroyAllWindows()
                        exit()

                else:
                    kamera_kapat_basladi = None

# ── EKRAN modunda uyku jesti: sağ elde serçe tek + 2sn ──────
                if aktif_mod == "EKRAN" and basparmak_tek_mu(el_lm):
                    if uyku_basladi is None:
                        uyku_basladi = simdi
                    gecen_u = simdi - uyku_basladi
                    if gecen_u >= 3.0:
                        bilgi_goster("Ekran kapatiliyor...")
                        hareket_kaydet("Ekran Uyku Modu", aktif_mod, "Sag El")
                        cv2.imshow("El Fare Kontrolu", cam)
                        cv2.waitKey(800)
                        ctypes.windll.user32.SendMessageW(0xFFFF, 0x0112, 0xF170, 2)
                        uyku_basladi = None
                elif aktif_mod != "EKRAN" or not serce_tek_mu(el_lm):
                    uyku_basladi = None

                # ── EKRAN modunda alan SS: yumruk sürükle → el aç → al ───────
                if aktif_mod == "EKRAN" and capraz_basladi is None:
                    if el_yumruk:
                        # Yumruk basılıyken başlangıç noktasını kaydet ve dikdörtgen çiz
                        bx = int(el_lm.landmark[8].x * ekran_genislik)
                        by = int(el_lm.landmark[8].y * ekran_yukseklik)
                        if alan_ss_baslangic is None:
                            alan_ss_baslangic = (bx, by)
                        # Kamerada dikdörtgen göster
                        cam_x1 = int(alan_ss_baslangic[0] * cw / ekran_genislik)
                        cam_y1 = int(alan_ss_baslangic[1] * ch / ekran_yukseklik)
                        cam_x2 = int(bx * cw / ekran_genislik)
                        cam_y2 = int(by * ch / ekran_yukseklik)
                        cv2.rectangle(cam, (cam_x1, cam_y1), (cam_x2, cam_y2),
                                      (0, 255, 255), 2)
                        cv2.putText(cam, "ALAN SS", (cam_x1, cam_y1 - 8),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,0,255), 2)
                    else:
                        # El açılınca → alanı kaydet
                        if alan_ss_baslangic is not None and simdi - son_ekran_g > 1.0:
                            bx = int(el_lm.landmark[0].x * ekran_genislik)
                            by = int(el_lm.landmark[0].y * ekran_yukseklik)
                            x_min = min(alan_ss_baslangic[0], bx)
                            y_min = min(alan_ss_baslangic[1], by)
                            x_max = max(alan_ss_baslangic[0], bx)
                            y_max = max(alan_ss_baslangic[1], by)
                            if x_max - x_min > 50 and y_max - y_min > 50:
                                dosya = os.path.join(EKRAN_GORUNTUSU_DIR,
                                    f"alan_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
                                tam_ss = pyautogui.screenshot()
                                alan   = tam_ss.crop((x_min, y_min, x_max, y_max))
                                alan.save(dosya)
                                son_ekran_g = simdi; ekran_flash = simdi
                                jest_durum["ekran_g"] = True
                                bilgi_goster("Kaydedildi: Alan SS")
                                hareket_kaydet("Alan Ekran Goruntusu", aktif_mod, "Sag El")
                            alan_ss_baslangic = None
                else:
                    alan_ss_baslangic = None

                # Tık ve Drag sadece MOUSE modunda çalışır
                if aktif_mod == "MOUSE":
                    if el_yumruk:
                        # Drag: yumruk = anında drag
                        jest_durum["drag"] = True
                        if not drag_aktif:
                            fare_bas()
                            hareket_kaydet("Drag Basladi", aktif_mod, "Sag El")
                            drag_aktif = True
                    else:
                        if drag_aktif:
                            fare_birak()
                            drag_aktif = False
                            time.sleep(0.05)
                            pyautogui.click(button="right")
                            son_sol_tik = simdi + 2.0
                            son_sag_tik = simdi + 2.0
                            bilgi_goster("Drag bitti → Sag tik atıldı")
                            hareket_kaydet("Drag Bitti", aktif_mod, "Sag El")

                        if not drag_aktif:
                            if mesafe_sol < TIK_MESAFE and simdi - son_sol_tik > TIK_BEKLEME:
                                pyautogui.click(button="left")
                                son_sol_tik = simdi
                                jest_durum["sol_tik"] = True
                                hareket_kaydet("Sol Tik", aktif_mod, "Sag El")

                            elif mesafe_sag < TIK_MESAFE and simdi - son_sag_tik > TIK_BEKLEME:
                                pyautogui.click(button="right")
                                son_sag_tik = simdi
                                jest_durum["sag_tik"] = True
                                hareket_kaydet("Sag Tik", aktif_mod, "Sag El")
                else:
                    if drag_aktif:
                        fare_birak()
                        drag_aktif = False

                # Görsel göstergeler
                r_sol = (0,0,255) if mesafe_sol < TIK_MESAFE else (180,180,180)
                r_sag = (0,0,255) if mesafe_sag < TIK_MESAFE else (180,180,180)
                cv2.circle(cam,(x_isaret,y_isaret),10,(255,255,255),-1)
                cv2.circle(cam,(x_bas,y_bas),10,(255,255,255),-1)
                cv2.circle(cam,(x_orta,y_orta),10,(255,255,255),-1)
                if aktif_mod == "MOUSE":
                    cv2.line(cam,(x_bas,y_bas),(x_isaret,y_isaret),r_sol,2)
                    cv2.line(cam,(x_bas,y_bas),(x_orta,y_orta),r_sag,2)

            mp_cizim.draw_landmarks(cam, el_lm, mp_el.HAND_CONNECTIONS)

    else:
        # Eller kamerada görünmediğinde sistemi komple bozma.
        # Yüz görünse bile sadece aktif hareketleri güvenli şekilde bırak.
        if drag_aktif:
            fare_birak()
            drag_aktif = False

        scroll_onceki_mesafe = None
        mod_degistir_basladi = None
        # Ses/parlaklık/alan SS değerleri korunur.

    # ── Flash efekti ───────────────────────────────────────────────────────
    if simdi - ekran_flash < 0.15:
        ov = cam.copy()
        cv2.rectangle(ov,(0,0),(cw,ch),(255,255,255),-1)
        cv2.addWeighted(ov,0.4,cam,0.6,0,cam)

    # ── Kalibrasyon mesajı ─────────────────────────────────────────────────
    if kalibrasyon_modu:
        cv2.putText(cam,"KALİBRASYON: Sag elini goster!",(10,ch//2),
                    cv2.FONT_HERSHEY_SIMPLEX,0.8,(0,165,255),2)

    # ── Sağ 4 parmak jesti → PC kapat ──────────────────────────────────────
    # EKRAN modunda, mouse eli/sağ el 4 parmak açık + baş parmak kapalı tutulursa
    # 3 saniye geri sayım başlar. Alan SS ile karışmasın diye capraz_basladi
    # aktifken alan SS bölümü çalışmaz.
    tum_lm = sonuc.multi_hand_landmarks if sonuc.multi_hand_landmarks else []
    tum_el = sonuc.multi_handedness if sonuc.multi_handedness else []

    if aktif_mod == "EKRAN" and len(tum_lm) >= 1:
        sag_dort_parmak_var = False

        for lm, hand in zip(tum_lm, tum_el):
            label = hand.classification[0].label

            # Kalibrasyon yaptığın mouse eli sağ el gibi kullanılıyor.
            # Böylece ters kamera/MediaPipe label karışıklığında da doğru el çalışır.
            if label == MOUSE_EL_ETIKETI and dort_parmak_jesti(lm):
                sag_dort_parmak_var = True
                break

        if sag_dort_parmak_var:
            alan_ss_baslangic = None  # PC kapatma başlarken alan SS iptal

            if capraz_basladi is None:
                capraz_basladi = simdi

            gecen = simdi - capraz_basladi
            kalan = max(0.0, KAPAT_SURE - gecen)
            bar   = min(int((gecen / KAPAT_SURE) * (cw - 40)), cw - 40)

            cv2.rectangle(cam, (20, ch - 50), (cw - 20, ch - 20), (40,40,40), -1)
            cv2.rectangle(cam, (20, ch - 50), (20 + bar, ch - 20), (0,0,220), -1)
            cv2.putText(cam, f"PC KAPATILIYOR... {kalan:.1f}s",
                        (30, ch - 27), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                        (255,255,255), 2)

            if gecen >= KAPAT_SURE:
                cv2.imshow("El Fare Kontrolu", cam)
                cv2.waitKey(800)
                hareket_kaydet("PC Kapatma", aktif_mod, "Sag El")
                os.system("shutdown /s /t 1")
                break
        else:
            capraz_basladi = None
    else:
        capraz_basladi = None

    # ── Kamera kapatma barı ────────────────────────────────────────────────
    if kamera_kapat_basladi is not None:
        gecen_cam = simdi - kamera_kapat_basladi
        kalan_cam = max(0.0, 2.0 - gecen_cam)
        bar_cam = min(int((gecen_cam / 2.0) * (cw - 40)), cw - 40)

        cv2.rectangle(cam, (20, ch - 150), (cw - 20, ch - 122), (40, 40, 40), -1)
        cv2.rectangle(cam, (20, ch - 150), (20 + bar_cam, ch - 122), (0, 0, 220), -1)
        cv2.putText(
            cam,
            f"KAMERA KAPANIYOR... {kalan_cam:.1f}s",
            (30, ch - 127),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (255, 255, 255),
            2
        )

    # ── Uyku barı (PC kapatma barının üstünde) ─────────────────────────────
    if uyku_basladi is not None:
        gecen_u = simdi - uyku_basladi
        kalan_u = max(0.0, 2.0 - gecen_u)
        bar_u   = min(int((gecen_u / 2.0) * (cw-40)), cw-40)
        cv2.rectangle(cam,(20,ch-100),(cw-20,ch-72),(40,40,40),-1)
        cv2.rectangle(cam,(20,ch-100),(20+bar_u,ch-72),(100,100,255),-1)
        cv2.putText(cam, f"UYKU MODU... {kalan_u:.1f}s",
                    (30,ch-77), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255,255,255), 2)

    # ── FPS & Ses ──────────────────────────────────────────────────────────
    fps_sayac += 1
    if simdi - fps_zaman >= 1.0:
        fps = fps_sayac; fps_sayac = 0; fps_zaman = simdi
    if simdi - son_ses_guncelle > 2.0:
        yeni = ses_seviyesi_al()
        if yeni >= 0: ses_seviye = yeni
        son_ses_guncelle = simdi

    # ══════════════════════════════════════════════════════════════════════
    # GÖRSEL ARAYÜZ
    # ══════════════════════════════════════════════════════════════════════
    TW = cw + YAN_PANEL_W
    TH = ch + UST_PANEL_H
    canvas = np.full((TH, TW, 3), RENK_BG, dtype=np.uint8)
    canvas[UST_PANEL_H:UST_PANEL_H+ch, 0:cw] = cam

    # ── ÜST PANEL ─────────────────────────────────────────────────────────
    panel_ciz(canvas, 0, 0, TW, UST_PANEL_H)

    # Aktif mod göstergesi (büyük, renkli)
    mod_renk = MOD_RENK[aktif_mod]
    cv2.putText(canvas, MOD_IKON[aktif_mod], (12, 34),
                cv2.FONT_HERSHEY_DUPLEX, 0.8, mod_renk, 2)

    # Mod döngüsü küçük gösterge
    for i, m in enumerate(MODLAR):
        mx = 260 + i * 80
        aktif = (m == aktif_mod)
        renk  = MOD_RENK[m] if aktif else (60,60,80)
        cv2.rectangle(canvas, (mx, 12), (mx+72, 38), (30,30,50), -1)
        if aktif:
            cv2.rectangle(canvas, (mx, 12), (mx+72, 38), renk, 2)
        (mtw, mth), _ = cv2.getTextSize(m, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
        cv2.putText(canvas, m, (mx + (72 - mtw)//2, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, renk, 1)

    # Saat
    saat = datetime.now().strftime("%H:%M:%S")
    cv2.putText(canvas, saat, (TW-100, 32),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (210,210,210), 1)

    # ── YAN PANEL ─────────────────────────────────────────────────────────
    px = cw; py = UST_PANEL_H
    panel_ciz(canvas, px, py, YAN_PANEL_W, ch)

    # Mod başlığı (büyük renkli kutu)
    cv2.rectangle(canvas, (px+6, py+8), (px+YAN_PANEL_W-6, py+46), (30,30,50), -1)
    cv2.rectangle(canvas, (px+6, py+8), (px+YAN_PANEL_W-6, py+46), mod_renk, 2)
    (amw, amh), _ = cv2.getTextSize(aktif_mod, cv2.FONT_HERSHEY_DUPLEX, 0.7, 1)
    cv2.putText(canvas, aktif_mod,
                (px + (YAN_PANEL_W - amw)//2, py + 33),
                cv2.FONT_HERSHEY_DUPLEX, 0.7, mod_renk, 1)

    # Mod değiştirme bar (sol avuç açık tutulunca)
    if mod_degistir_basladi is not None:
        gecen_mod = simdi - mod_degistir_basladi
        oran      = gecen_mod / MOD_DEGISTIR_SURE
        bar_ciz(canvas, px+6, py+50, YAN_PANEL_W-12, 12, oran, MOD_RENK[sonraki_mod()])
        cv2.putText(canvas, f"-> {sonraki_mod()}", (px+10, py+60),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.38, MOD_RENK[sonraki_mod()], 1)

    # Durum kutusu
    if capraz_basladi is not None:
        durum_yazi = f"PC KAPAT! {max(0.0, KAPAT_SURE-(simdi-capraz_basladi)):.1f}s"
        durum_renk = (0, 0, 220)
    elif jest_durum["el_yok"]:
        durum_yazi = "El bulunamadi"; durum_renk = RENK_PASIF
    elif jest_durum["drag"]:
        durum_yazi = "DRAG & DROP";   durum_renk = (255,0,255)
    elif jest_durum["sol_tik"]:
        durum_yazi = "SOL TIK!";      durum_renk = (0,220,120)
    elif jest_durum["sag_tik"]:
        durum_yazi = "SAG TIK!";      durum_renk = RENK_VURGU
    elif jest_durum["scroll"]:
        durum_yazi = "SCROLL";        durum_renk = (0,165,255)
    elif jest_durum["ses_yukari"]:
        durum_yazi = "SES +";         durum_renk = (0,0,255)
    elif jest_durum["ses_asagi"]:
        durum_yazi = "SES -";         durum_renk = (0,0,255)
    elif jest_durum["ekran_g"]:
        durum_yazi = "EKRAN ALINDI!"; durum_renk = (0,0,255)
    elif jest_durum["mouse"]:
        durum_yazi = "Mouse aktif";   durum_renk = (0,220,120)
    else:
        durum_yazi = "Bekleniyor..."; durum_renk = (180,180,180)

    kutu_y = py + 70
    cv2.rectangle(canvas,(px+8,kutu_y),(px+YAN_PANEL_W-8,kutu_y+26),(30,30,50),-1)
    cv2.rectangle(canvas,(px+8,kutu_y),(px+YAN_PANEL_W-8,kutu_y+26),durum_renk,1)
    cv2.putText(canvas, durum_yazi, (px+12,kutu_y+18),
                cv2.FONT_HERSHEY_SIMPLEX, 0.48, durum_renk, 1)

    # FPS barı
    fps_y = py + 104
    cv2.putText(canvas,"FPS",(px+10,fps_y+10),cv2.FONT_HERSHEY_SIMPLEX,0.4,(160,160,180),1)
    bar_ciz(canvas, px+38, fps_y, 100, 12, fps/60,
            (0,220,120) if fps>=30 else (0,165,255) if fps>=15 else (0,0,200))
    cv2.putText(canvas, str(fps), (px+145,fps_y+10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (200,200,200), 1)

    # Ses barı
    if ses_seviye >= 0:
        ses_y = fps_y + 18
        cv2.putText(canvas,"SES",(px+10,ses_y+10),cv2.FONT_HERSHEY_SIMPLEX,0.4,(160,160,180),1)
        bar_ciz(canvas, px+38, ses_y, 100, 12, ses_seviye/100, (0,0,255))
        cv2.putText(canvas, f"{ses_seviye}%", (px+145,ses_y+10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (200,200,200), 1)

    rehber_y = py + 150 if aktif_mod == "EKRAN" else py + 144
    cv2.putText(canvas, "JESTLER", (px+10, rehber_y),
                cv2.FONT_HERSHEY_SIMPLEX, 0.52, (230, 230, 230), 1)
    cv2.line(canvas,(px+5,rehber_y+6),(px+YAN_PANEL_W-5,rehber_y+6),RENK_BORDER,1)

    for i, satir in enumerate(MOD_ACIKLAMA[aktif_mod]):
        sy = rehber_y + 22 + i * 22
        cv2.putText(canvas, satir, (px+12, sy),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, mod_renk, 1)

    # Mod değiştirme ipucu
    ipucu_y = rehber_y + 22 + len(MOD_ACIKLAMA[aktif_mod]) * 22 + 14
    cv2.line(canvas,(px+5,ipucu_y),(px+YAN_PANEL_W-5,ipucu_y),RENK_BORDER,1)
    cv2.putText(canvas, "MOD DEGISTIR:", (px+10, ipucu_y+14),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (230, 230, 230), 1)
    cv2.putText(canvas, "Sol el yumruk 5sn tut", (px+10, ipucu_y+28),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (160,160,180), 1)

    # Alt kısayollar
    alt_y = py + ch - 55
    cv2.line(canvas,(px+5,alt_y),(px+YAN_PANEL_W-5,alt_y),RENK_BORDER,1)
    cv2.putText(canvas,"Q:Cikis  R:Kalibrasyon  M:ModDegis",(px+10,alt_y+16),
                cv2.FONT_HERSHEY_SIMPLEX,0.38,(140,140,160),1)
    cv2.putText(canvas,"1:Mouse 2:Sistem 3:Ekran",(px+10,alt_y+30),
                cv2.FONT_HERSHEY_SIMPLEX,0.38,(140,140,160),1)
    cv2.putText(canvas,"Sag 4 parmak 3sn: PC Kapat",(px+10,alt_y+44),
                cv2.FONT_HERSHEY_SIMPLEX,0.38,(140,140,160),1)

    # ── Mod değişim bildirimi (ortada büyük yazı) ─────────────────────────
    if mod_bildirim_yazi and simdi - mod_bildirim_zaman < 1.5:
        alpha = max(0, 1.0 - (simdi - mod_bildirim_zaman) / 1.5)
        renk_bildirim = tuple(int(c * alpha) for c in MOD_RENK.get(aktif_mod, (255,255,255)))
        (tw, th), _ = cv2.getTextSize(mod_bildirim_yazi,
                                       cv2.FONT_HERSHEY_DUPLEX, 1.4, 2)
        bx = (cw - tw) // 2; by = UST_PANEL_H + ch // 2
        cv2.putText(canvas, mod_bildirim_yazi, (bx, by),
                    cv2.FONT_HERSHEY_DUPLEX, 1.4, mod_renk, 2)

    # ── Geçici bilgi mesajı ───────────────────────────────────────────────
    if bilgi_mesaji and simdi - bilgi_zaman < 3.0:
        cv2.putText(canvas, bilgi_mesaji, (10, UST_PANEL_H + 25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,0,255), 2)

    cv2.imshow("El Fare Kontrolu", canvas)

    tus = cv2.waitKey(1) & 0xFF
    if tus == ord("q"):
        break
    elif tus == ord("r"):
        if os.path.exists(KALIBRASYON_DOSYA): os.remove(KALIBRASYON_DOSYA)
        MOUSE_EL_ETIKETI = None
        kalibrasyon_modu = True
        print("Kalibrasyon sıfırlandı.")
    elif tus == ord("m"):
        aktif_mod = sonraki_mod()
        hareket_kaydet("Klavye ile Mod Degisti", aktif_mod, "Klavye")
        mod_bildirim_yazi = f"MOD: {aktif_mod}"
        mod_bildirim_zaman = simdi
        if aktif_mod == "EKRAN":
            ekran_moda_giris = simdi
    elif tus == ord("1"):
        aktif_mod = "MOUSE"
        hareket_kaydet("Mod Secildi", aktif_mod, "Klavye")
        mod_bildirim_yazi = "MOD: MOUSE"
        mod_bildirim_zaman = simdi
    elif tus == ord("2"):
        aktif_mod = "SISTEM"
        hareket_kaydet("Mod Secildi", aktif_mod, "Klavye")
        mod_bildirim_yazi = "MOD: SISTEM"
        mod_bildirim_zaman = simdi
    elif tus == ord("3"):
        aktif_mod = "EKRAN"
        hareket_kaydet("Mod Secildi", aktif_mod, "Klavye")
        mod_bildirim_yazi = "MOD: EKRAN"
        mod_bildirim_zaman = simdi
        ekran_moda_giris = simdi

if drag_aktif:
    fare_birak()

kamera.release()
cv2.destroyAllWindows()