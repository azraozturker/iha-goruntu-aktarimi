import time   # FPS hesaplamak için zamanı ölçeceğiz
import cv2    # OpenCV

# Ayarlar
KAMERA_NO = 0        # 0 → /dev/video0, yani ilk kamera
GENISLIK = 1280
YUKSEKLIK = 720

# Kamerayı doğrudan Linux'un kamera sistemiyle (V4L2) aç
kamera = cv2.VideoCapture(KAMERA_NO, cv2.CAP_V4L2)

# Kameradan MJPG formatında görüntü iste (yüksek çözünürlükte FPS'i korur)
kamera.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))

# İstediğimiz çözünürlüğü iste
kamera.set(cv2.CAP_PROP_FRAME_WIDTH, GENISLIK)
kamera.set(cv2.CAP_PROP_FRAME_HEIGHT, YUKSEKLIK)

# Kamera açılamadıysa programı durdur
if not kamera.isOpened():
    print("Kamera açılamadı!")
    exit()

# Kamera gerçekte hangi çözünürlüğü verdi?
gercek_genislik = int(kamera.get(cv2.CAP_PROP_FRAME_WIDTH))
gercek_yukseklik = int(kamera.get(cv2.CAP_PROP_FRAME_HEIGHT))
print("Kamera çözünürlüğü:", gercek_genislik, "x", gercek_yukseklik)

kare_sayaci = 0              # Bu saniyede kaç kare geldi
saniye_basi = time.time()    # Sayımın başladığı an
fps = 0                      # Ekranda gösterilecek değer

while True:
    basarili, kare = kamera.read()   # Bir kare al

    if not basarili:
        print("Kare okunamadı!")
        break

    # FPS hesabı
    kare_sayaci += 1
    gecen_sure = time.time() - saniye_basi
    if gecen_sure >= 1.0:                    # 1 saniye dolduysa
        fps = kare_sayaci / gecen_sure       # Saniyede kaç kare geldi
        kare_sayaci = 0                      # Sayacı sıfırla
        saniye_basi = time.time()            # Yeni saniyeyi başlat

    # FPS'i sol üste yeşil renkle yaz
    cv2.putText(kare, f"FPS: {fps:.1f}", (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)

    cv2.imshow("Kamera", kare)       # Kareyi göster

    if cv2.waitKey(1) & 0xFF == ord("q"):   # q'ya basılırsa çık
        break

kamera.release()
cv2.destroyAllWindows()