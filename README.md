# İHA Görüntü Aktarımı ve QR Kod Okuma

Bir bilgisayarın (İHA) kamerasından alınan canlı görüntü, ağ üzerinden ikinci bilgisayara (yer istasyonu) aktarılır. QR kodlar İHA tarafında çözülür; sonuç yer istasyonunda gösterilir ve kaydedilir.

## Mimari

```
İHA (gonderici.py)                                  Yer istasyonu (alici.py)
Kamera → QR çözme
   ├→ H.264 → RTP → UDP 5000 ───────────────────→ Görüntüyü çöz, göster
   └→ QR sonucu (JSON) → UDP 5002 ──────────────→ QR kutusunu çiz, CSV'ye kaydet
                                    ←── UDP 5001 ── Eko (gecikme ölçümü)
```

## Neden bu yöntemi seçtik?

**Görüntü aktarımı: GStreamer + H.264 + UDP**

| Seçenek | Bant genişliği | Gecikme | Neden seçmedik / seçtik |
|---|---|---|---|
| TCP + JPEG | Yüksek | Kayıpta artar | TCP kaybolan paketi beklediği için görüntü donar. Canlı görüntüde geç gelen kare işe yaramaz |
| UDP + JPEG | Yüksek (5–10 Mbps) | Düşük | Her kare ayrı resim olarak gittiği için çok veri harcar |
| **GStreamer + H.264 + UDP** | **Düşük (~2 Mbps)** | **Düşük** | **Seçildi.** H.264 yalnızca kareler arasındaki farkı gönderdiği için çok az veri harcar. Gerçek İHA'daki kablosuz bağlantının (Rocket) kapasitesi sınırlı olduğu için bu önemlidir |

H.264 kodlayıcı düşük gecikme için ayarlandı: B kareleri kapalı (`zerolatency`), en hızlı sıkıştırma (`ultrafast`), saniyede bir tam kare (`key-int-max=30`). GStreamer, sıkıştırma ve paketleme adımlarının her birini ayrı ayarlayabildiğimiz için seçildi.

**QR çözümü İHA tarafında:** QR, sıkıştırılmadan önceki temiz görüntüden okunduğu için daha güvenilir okunur. Gerçek İHA'da da tespit hava aracında yapılır, yere sonuç gönderilir.

**QR sonucu ayrı kanalda:** Görüntüyü GStreamer gönderdiği için QR bilgisi ayrı bir UDP portundan JSON olarak gider. Gerçek İHA'larda da video ve telemetri ayrı kanallardan iletilir.

**QR çözücü: cv2.QRCodeDetector:** QR kameraya yakın mesafeden gösterildiği için OpenCV'nin hızlı ve ek kurulum gerektirmeyen klasik çözücüsü yeterlidir.

## Kurulum (Ubuntu 24.04)

```bash
sudo apt install -y python3-opencv gstreamer1.0-tools gstreamer1.0-plugins-base gstreamer1.0-plugins-good gstreamer1.0-plugins-bad gstreamer1.0-plugins-ugly gstreamer1.0-libav
git clone https://github.com/azraozturker/iha-goruntu-aktarimi.git
cd iha-goruntu-aktarimi
python3 -m venv --system-site-packages venv
source venv/bin/activate
```

OpenCV apt ile kuruldu, çünkü pip'teki OpenCV'de GStreamer desteği yok.

Ağ ayarı: İHA `192.168.1.30`, yer istasyonu `192.168.1.10` (statik IP, maske `255.255.255.0`). Güvenlik duvarı açıksa: `sudo ufw allow from 192.168.1.0/24`

## Çalıştırma

Önce alıcı, sonra gönderici başlatılır. Pencereler `q` ile kapatılır.

**Tek bilgisayarda** (`ortak.py` içinde `YEREL_TEST = True`):
```bash
python alici.py --iha-ip 127.0.0.1
python gonderici.py
```

**İki bilgisayarda** (`ortak.py` içinde `YEREL_TEST = False`):
```bash
python alici.py --iha-ip 192.168.1.30    # yer istasyonunda
python gonderici.py                      # İHA'da
```

## Ölçüm sonuçları (tek bilgisayar)

| Durum | FPS | Bant genişliği | Gecikme | Kayıp kare |
|---|---|---|---|---|
| QR yok | 30 | 2,17 Mbps | - | 0 |
| QR var | 28 | 1,36 Mbps | 14,8 ms | 0 |

Gecikme, eko yöntemiyle ölçülen ağ ve işleme süresidir (kamera gecikmesi dahil değildir). H.264, ham görüntüyü (~166 Mbps) yaklaşık 80 kat küçülterek ~2 Mbps'e indirmiştir.