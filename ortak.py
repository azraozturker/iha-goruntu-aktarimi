import json   # Telemetri paketlerini metne çevirmek için

# ---------------- 1. AYARLAR ----------------

# True: İki program aynı bilgisayarda (test için)
# False: İki ayrı bilgisayar (gerçek ağ)
YEREL_TEST = True

if YEREL_TEST:
    IHA_IP = "127.0.0.1"         # Bilgisayarın kendisi
    YER_IP = "127.0.0.1"
else:
    IHA_IP = "192.168.1.30"      # Azra'nın bilgisayarı (İHA)
    YER_IP = "192.168.1.10"      # Zehra'nın bilgisayarı (yer istasyonu)

# Portlar
VIDEO_PORT = 5000        # Görüntü: İHA → yer (GStreamer, H.264)
EKO_PORT = 5001          # Eko: yer → İHA (gecikme ölçümü)
TELEMETRI_PORT = 5002    # QR sonucu: İHA → yer (JSON)

# Gönderilen görüntünün ayarları
GONDERIM_GENISLIK = 640  # Kamera 1280x720 çekiyor, yarısına küçültüp gönderiyoruz
GONDERIM_YUKSEKLIK = 360
FPS = 30
BIT_HIZI = 2000          # Saniyede kaç kilobit (2000 kbps = 2 Mbps)


# ---------------- 2. TELEMETRİ PAKETİ ----------------

def telemetri_paketle(kare_no, zaman, qr_listesi):
    """QR sonucunu ağdan gönderilebilecek baytlara çevirir."""
    sozluk = {
        "kare_no": kare_no,
        "zaman": zaman,
        "qr": qr_listesi
    }
    metin = json.dumps(sozluk)        # Sözlük → JSON metni
    return metin.encode("utf-8")      # Metin → bayt


def telemetri_coz(veri):
    """Gelen baytları tekrar sözlüğe çevirir."""
    metin = veri.decode("utf-8")      # Bayt → metin
    return json.loads(metin)          # JSON metni → sözlük


# ---------------- 3. GÖNDERİCİ BORU HATTI (İHA) ----------------

def gonderici_boru_hatti():
    """OpenCV'den gelen kareleri H.264 ile sıkıştırıp UDP ile gönderen GStreamer komutu."""
    return (
        "appsrc ! videoconvert ! video/x-raw,format=I420 ! "
        f"x264enc tune=zerolatency speed-preset=ultrafast bitrate={BIT_HIZI} key-int-max={FPS} ! "
        "rtph264pay config-interval=1 pt=96 ! "
        f"udpsink host={YER_IP} port={VIDEO_PORT} sync=false"
    )


# ---------------- 4. ALICI BORU HATTI (YER İSTASYONU) ----------------

def alici_boru_hatti():
    """UDP'den gelen H.264 görüntüyü çözüp OpenCV'ye veren GStreamer komutu."""
    return (
        f"udpsrc port={VIDEO_PORT} "
        'caps="application/x-rtp,media=video,encoding-name=H264,payload=96,clock-rate=90000" ! '
        "rtpjitterbuffer latency=20 ! rtph264depay ! h264parse ! avdec_h264 ! "
        "videoconvert ! video/x-raw,format=BGR ! "
        "appsink drop=true sync=false max-buffers=1"
    )


# ---------------- TEST ----------------

if __name__ == "__main__":
    # Telemetri paketini dene
    ornek_qr = [{"metin": "HEDEF-1", "koseler": [[40, 40], [249, 40], [249, 249], [40, 249]]}]
    paket = telemetri_paketle(152, 1795779000.123, ornek_qr)
    print("Paket (bayt):", paket)
    print("Paket boyutu:", len(paket), "bayt")
    print("Çözülmüş hali:", telemetri_coz(paket))

    print()
    print("Gönderici boru hattı:")
    print(gonderici_boru_hatti())
    print()
    print("Alıcı boru hattı:")
    print(alici_boru_hatti())