import socket   # Telemetri paketlerini UDP ile göndermek için
import time     # Zaman damgası ve FPS için
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
    zaman = time.time()      # Bu karenin çekildiği an (gecikme ölçümünde kullanacağız)

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

    # 6) Önizleme: İHA tarafında ne gönderildiğini görmek için
    onizleme = kucuk.copy()
    qr_ciz(onizleme, gonderilecek_qr)
    cv2.putText(onizleme, f"FPS: {fps:.1f}", (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
    cv2.imshow("IHA - gonderilen", onizleme)

    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

kamera.release()
video.release()
telemetri_soketi.close()
cv2.destroyAllWindows()