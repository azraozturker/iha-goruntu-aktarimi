import socket      # Telemetri ve eko paketleri için (UDP)
import threading   # YENİ: Eko paketlerini ayrı bir işçide dinlemek için
import time        # Zaman damgası, FPS ve gecikme için
import cv2

import ortak                              # Ortak kurallar (IP, port, boru hattı)
from qr_okuyucu import qr_coz, qr_ciz     # Zehra'nın QR fonksiyonları

# ---------------- AYARLAR ----------------
KAMERA_NO = 0
KAMERA_GENISLIK = 1280
KAMERA_YUKSEKLIK = 720
QR_ARALIGI = 1        # QR kaç karede bir çözülsün (FPS düşerse 2 veya 3 yap)

# ---------------- KAMERA ----------------
kamera = cv2.VideoCapture(KAMERA_NO, cv2.CAP_V4L2)
kamera.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
kamera.set(cv2.CAP_PROP_FRAME_WIDTH, KAMERA_GENISLIK)
kamera.set(cv2.CAP_PROP_FRAME_HEIGHT, KAMERA_YUKSEKLIK)

if not kamera.isOpened():
    print("Kamera açılamadı!")
    exit()

gercek_genislik = int(kamera.get(cv2.CAP_PROP_FRAME_WIDTH))
gercek_yukseklik = int(kamera.get(cv2.CAP_PROP_FRAME_HEIGHT))
print("Kamera çözünürlüğü:", gercek_genislik, "x", gercek_yukseklik)

# QR köşelerini büyük kareden küçük kareye çevirmek için oran
olcek_x = ortak.GONDERIM_GENISLIK / gercek_genislik
olcek_y = ortak.GONDERIM_YUKSEKLIK / gercek_yukseklik

# ---------------- GÖRÜNTÜ GÖNDERİCİ (GStreamer) ----------------
video = cv2.VideoWriter(
    ortak.gonderici_boru_hatti(),   # GStreamer komutu (ortak.py'den)
    cv2.CAP_GSTREAMER,              # OpenCV'ye "bunu GStreamer ile aç" diyoruz
    0,                              # Sıkıştırma türü (GStreamer kendisi yapacağı için 0)
    ortak.FPS,
    (ortak.GONDERIM_GENISLIK, ortak.GONDERIM_YUKSEKLIK),
    True                            # Renkli görüntü
)

if not video.isOpened():
    print("GStreamer boru hattı açılamadı!")
    exit()

# ---------------- TELEMETRİ SOKETİ ----------------
telemetri_soketi = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

# ---------------- YENİ: EKO DİNLEYİCİ (gecikme ölçümü) ----------------
eko_soketi = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
eko_soketi.bind(("0.0.0.0", ortak.EKO_PORT))   # 5001 numaralı portu dinle
eko_soketi.settimeout(0.5)                      # En fazla 0,5 saniye bekle

gecikme_ms = 0.0     # Ekranda gösterilecek tek yön gecikme (milisaniye)
calisiyor = True     # Program kapanınca işçiyi durdurmak için


def eko_dinle():
    """Alıcıdan gelen eko paketlerini dinler, gecikmeyi hesaplar."""
    global gecikme_ms
    while calisiyor:
        try:
            veri, _ = eko_soketi.recvfrom(1024)
        except socket.timeout:      # 0,5 sn içinde paket gelmediyse tekrar dene
            continue
        except OSError:             # Soket kapatıldıysa çık
            break

        paket = ortak.telemetri_coz(veri)
        gidis_donus_ms = (time.time() - paket["zaman"]) * 1000
        yeni = gidis_donus_ms / 2   # Tek yön ≈ gidiş-dönüşün yarısı

        # Sayı zıplamasın diye yumuşat: eskinin %90'ı + yeninin %10'u
        if gecikme_ms == 0:
            gecikme_ms = yeni
        else:
            gecikme_ms = 0.9 * gecikme_ms + 0.1 * yeni


eko_isci = threading.Thread(target=eko_dinle, daemon=True)
eko_isci.start()

print("Gönderim başladı →", ortak.YER_IP)

# ---------------- ANA DÖNGÜ ----------------
kare_no = 0
son_qr = []                  # En son bulunan QR sonuçları
kare_sayaci = 0
saniye_basi = time.time()
fps = 0

while True:
    basarili, kare = kamera.read()
    if not basarili:
        print("Kare okunamadı!")
        break

    kare_no += 1
    zaman = time.time()      # Bu karenin çekildiği an (gecikme ölçümünde kullanılıyor)

    # 1) QR'ı büyük ve temiz karede çöz
    if kare_no % QR_ARALIGI == 0:
        son_qr = qr_coz(kare)

    # 2) Köşeleri küçük kareye göre ölçekle
    gonderilecek_qr = []
    for qr in son_qr:
        yeni_koseler = [[int(x * olcek_x), int(y * olcek_y)] for x, y in qr["koseler"]]
        gonderilecek_qr.append({"metin": qr["metin"], "koseler": yeni_koseler})

    # 3) Kareyi küçült ve GStreamer'a ver (H.264 → UDP 5000)
    kucuk = cv2.resize(kare, (ortak.GONDERIM_GENISLIK, ortak.GONDERIM_YUKSEKLIK))
    video.write(kucuk)

    # 4) QR sonucunu telemetri olarak gönder (UDP 5002)
    paket = ortak.telemetri_paketle(kare_no, zaman, gonderilecek_qr)
    telemetri_soketi.sendto(paket, (ortak.YER_IP, ortak.TELEMETRI_PORT))

    # 5) FPS hesabı
    kare_sayaci += 1
    gecen_sure = time.time() - saniye_basi
    if gecen_sure >= 1.0:
        fps = kare_sayaci / gecen_sure
        kare_sayaci = 0
        saniye_basi = time.time()
        print(f"FPS: {fps:.1f} | Gecikme: {gecikme_ms:.1f} ms")   # YENİ

    # 6) Önizleme: İHA tarafında ne gönderildiğini görmek için
    onizleme = kucuk.copy()
    qr_ciz(onizleme, gonderilecek_qr)
    cv2.putText(onizleme, f"FPS: {fps:.1f}", (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
    cv2.putText(onizleme, f"Gecikme: {gecikme_ms:.1f} ms", (10, 65),     # YENİ
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
    cv2.imshow("IHA - gonderilen", onizleme)

    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

# ---------------- KAPATMA ----------------
calisiyor = False            # YENİ: Eko işçisini durdur
eko_soketi.close()           # YENİ
kamera.release()
video.release()
telemetri_soketi.close()
cv2.destroyAllWindows()