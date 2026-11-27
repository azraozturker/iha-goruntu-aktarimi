"""
Yer İstasyonu Alıcı Modülü (GStreamer RTP + UDP Telemetri + Eko + Kayıt)
Sorumlu: Kişi B (Yer İstasyonu - 192.168.1.10)
"""

import argparse
import csv
from datetime import datetime
import json
import os
import socket
import subprocess
import threading
import time
from typing import Any, Dict, List, Optional

import cv2
import numpy as np

from qr_okuyucu import qr_ciz

# Varsayılan Ağ ve Port Sabitleri
VARSAYILAN_IHA_IP = "192.168.1.30"
VIDEO_PORT = 5000
EKO_PORT = 5001
TELEMETRI_PORT = 5002

QR_CSV_DOSYASI = "qr_kayit_yer.csv"
OLCUM_CSV_DOSYASI = "olcum.csv"
QR_COOLDOWN_SN = 2.0
BAGLANTI_ZAMAN_ASIMI_SN = 1.0

_TR_ASCII = str.maketrans({
    "ç": "c", "Ç": "C",
    "ğ": "g", "Ğ": "G",
    "ı": "i", "İ": "I",
    "ö": "o", "Ö": "O",
    "ş": "s", "Ş": "S",
    "ü": "u", "Ü": "U",
})


def ag_arayuzu_bul(hedef_ip: str) -> Optional[str]:
    """İlgili IP alt ağına bağlı ağ arayüzü adını (örn. enp3s0 veya lo) otomatik bulur."""
    yerel_ip = "127.0.0.1" if hedef_ip.startswith("127.") else "192.168.1.10"
    try:
        cikti = subprocess.check_output(["ip", "-o", "-4", "addr", "show"], text=True)
        for satir in cikti.splitlines():
            if yerel_ip in satir:
                parcalar = satir.split()
                if len(parcalar) >= 2:
                    return parcalar[1]
    except Exception:
        pass
    return None


def arayuz_rx_bayt_oku(arayuz: Optional[str]) -> Optional[int]:
    """Ağ kartının aldığı toplam bayt sayacını okur (gerçek Mbps ölçümü için)."""
    if not arayuz:
        return None
    yol = f"/sys/class/net/{arayuz}/statistics/rx_bytes"
    try:
        with open(yol, "r", encoding="utf-8") as f:
            return int(f.read().strip())
    except Exception:
        return None


def gst_alici_pipeline_olustur(port: int, codec: str = "h264") -> str:
    """Seçilen codec türüne göre düşük gecikmeli GStreamer UDP alıcı pipeline'ı döndürür."""
    if codec.lower() == "mjpeg":
        return (
            f'udpsrc port={port} caps="application/x-rtp,media=video,clock-rate=90000,'
            f'encoding-name=JPEG,payload=26" ! rtpjitterbuffer latency=10 ! '
            f'rtpjpegdepay ! jpegdec ! videoconvert ! video/x-raw,format=BGR ! '
            f'appsink drop=true max-buffers=1 sync=false'
        )
    return (
        f'udpsrc port={port} caps="application/x-rtp,media=video,clock-rate=90000,'
        f'encoding-name=H264,payload=96" ! rtpjitterbuffer latency=10 ! '
        f'rtph264depay ! avdec_h264 ! videoconvert ! video/x-raw,format=BGR ! '
        f'appsink drop=true max-buffers=1 sync=false'
    )


def _qr_listesini_dogrula(ham_liste: Any) -> List[Dict[str, Any]]:
    """
    UDP üzerinden gelen QR listesini qr_okuyucu.qr_ciz() fonksiyonunun beklediği
    kesin formata ({"metin": str, "koseler": [[int, int], ...]}) dönüştürür.
    """
    if not isinstance(ham_liste, list):
        return []

    temiz_liste: List[Dict[str, Any]] = []
    for oge in ham_liste:
        if not isinstance(oge, dict):
            continue

        metin = str(oge.get("metin", "")).strip()
        ham_koseler = oge.get("koseler") or oge.get("noktalar")
        if not metin or not isinstance(ham_koseler, list) or len(ham_koseler) != 4:
            continue

        try:
            koseler = [
                [int(round(float(nokta[0]))), int(round(float(nokta[1])))]
                for nokta in ham_koseler
            ]
        except (TypeError, ValueError, IndexError):
            continue

        temiz_liste.append({
            "metin": metin,
            "koseler": koseler,
        })

    return temiz_liste


class YerIstasyonuAlici:
    def __init__(
        self,
        iha_ip: str = VARSAYILAN_IHA_IP,
        video_port: int = VIDEO_PORT,
        eko_port: int = EKO_PORT,
        telemetri_port: int = TELEMETRI_PORT,
        codec: str = "h264",
        arayuz: Optional[str] = None,
    ) -> None:
        self.iha_ip = iha_ip
        self.video_port = video_port
        self.eko_port = eko_port
        self.telemetri_port = telemetri_port
        self.codec = codec
        self.arayuz = arayuz or ag_arayuzu_bul(iha_ip)

        self.calisiyor = True
        self.kilit = threading.Lock()

        # Görüntü durumu
        self.son_kare: Optional[np.ndarray] = None
        self.son_kare_zamani: float = 0.0
        self.fps: float = 0.0

        # Telemetri, QR ve paket istatistikleri
        self.guncel_qr_sonuclar: List[Dict[str, Any]] = []
        self.son_qr_zamani: float = 0.0
        self.son_okunan_qr_metni: str = ""
        self.son_kare_no: int = -1
        self.kayip_kare: int = 0
        self.sira_disi_kare: int = 0
        self.telemetri_bayt_sayaci: int = 0

        # QR tekrar engelleme (cooldown) sözlüğü: {qr_metni: son_kayit_timestamp}
        self.qr_kayit_gecmisi: Dict[str, float] = {}

        # CSV dosyalarını başlıklarıyla hazırla
        self._csv_dosyalarini_hazirla()

        # UDP Soketleri (5002 telemetri dinleme, 5001 eko gönderme)
        self.telemetri_soket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.telemetri_soket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.telemetri_soket.bind(("0.0.0.0", self.telemetri_port))
        self.telemetri_soket.settimeout(0.5)

        self.eko_soket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        # GStreamer VideoCapture başlat
        pipeline = gst_alici_pipeline_olustur(self.video_port, self.codec)
        self.cap = cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)
        if not self.cap.isOpened():
            self.telemetri_soket.close()
            self.eko_soket.close()
            raise RuntimeError(
                "GStreamer VideoCapture açılamadı! "
                "OpenCV GStreamer desteğini (cv2.getBuildInformation()) kontrol edin."
            )

    def _csv_dosyalarini_hazirla(self) -> None:
        if not os.path.exists(QR_CSV_DOSYASI):
            with open(QR_CSV_DOSYASI, "w", newline="", encoding="utf-8") as f:
                yazici = csv.writer(f)
                yazici.writerow(["Tarih_Saat", "Kare_No", "QR_Metni", "Koseler"])

        if not os.path.exists(OLCUM_CSV_DOSYASI):
            with open(OLCUM_CSV_DOSYASI, "w", newline="", encoding="utf-8") as f:
                yazici = csv.writer(f)
                yazici.writerow([
                    "Tarih_Saat",
                    "FPS",
                    "Bant_Genisligi_Mbps",
                    "Kayip_Kare",
                    "Sira_Disi_Kare",
                    "Son_QR",
                    "Baglanti_Durumu",
                ])

    def _qr_csv_kaydet(self, kare_no: int, qr_listesi: List[Dict[str, Any]]) -> None:
        simdi = time.time()
        tarih_saat = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

        for oge in qr_listesi:
            metin = oge["metin"]
            koseler = oge["koseler"]
            son_kayit = self.qr_kayit_gecmisi.get(metin, 0.0)

            # Yeni bir QR metni geldiyse veya son kaydın üzerinden en az 2 saniye geçtiyse yaz
            if (metin not in self.qr_kayit_gecmisi) or (simdi - son_kayit >= QR_COOLDOWN_SN):
                with open(QR_CSV_DOSYASI, "a", newline="", encoding="utf-8") as f:
                    yazici = csv.writer(f)
                    yazici.writerow([
                        tarih_saat,
                        kare_no,
                        metin,
                        json.dumps(koseler, ensure_ascii=False),
                    ])
                self.qr_kayit_gecmisi[metin] = simdi
                self.son_okunan_qr_metni = metin
                print(f"[QR KAYIT] {tarih_saat} | Kare #{kare_no} | {metin}")

    def _video_okuma_dongusu(self) -> None:
        """GStreamer appsink üzerinden gelen video karelerini bloklanmadan okur."""
        onceki_zaman = time.time()

        while self.calisiyor:
            ret, kare = self.cap.read()
            if not ret or kare is None:
                time.sleep(0.005)
                continue

            simdi = time.time()
            gecen = simdi - onceki_zaman
            onceki_zaman = simdi

            anlik_fps = (1.0 / gecen) if gecen > 0 else 0.0

            with self.kilit:
                self.son_kare = kare
                self.son_kare_zamani = simdi
                self.fps = anlik_fps if self.fps == 0.0 else (0.85 * self.fps + 0.15 * anlik_fps)

    def _telemetri_ve_eko_dongusu(self) -> None:
        """
        UDP 5002 portundan QR + zaman damgası paketlerini alır,
        UDP 5001 portundan Kişi A'ya anında eko paketi geri yollar.
        """
        while self.calisiyor:
            try:
                ham_veri, _ = self.telemetri_soket.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                break

            if not ham_veri:
                continue

            # Olası ikili başlık varsa ilk '{' karakterinden itibaren JSON ayrıştır
            json_baslangic = ham_veri.find(b"{")
            if json_baslangic == -1:
                continue

            try:
                paket = json.loads(ham_veri[json_baslangic:].decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue

            try:
                kare_no = int(paket.get("kare_no", paket.get("frame_id", -1)))
            except (TypeError, ValueError):
                kare_no = -1

            zaman = paket.get("zaman", paket.get("timestamp", time.time()))
            ham_qr = (
                paket.get("qr_sonuclar")
                or paket.get("qr")
                or paket.get("sonuclar")
                or []
            )
            qr_sonuclar = _qr_listesini_dogrula(ham_qr)

            # 1. Gecikme ölçümü için Kişi A'ya (Port 5001) anında eko paketi gönder
            if kare_no >= 0:
                eko_paketi = json.dumps({"kare_no": kare_no, "zaman": zaman}).encode("utf-8")
                try:
                    self.eko_soket.sendto(eko_paketi, (self.iha_ip, self.eko_port))
                except OSError:
                    pass

            with self.kilit:
                self.telemetri_bayt_sayaci += len(ham_veri)

                # 2. Kayıp ve sıra dışı kare kontrolü
                if kare_no >= 0:
                    if self.son_kare_no > 50 and kare_no <= 5:
                        # Gönderici yeniden başlatılmışsa sayacı sıfırla
                        self.son_kare_no = kare_no
                    elif self.son_kare_no != -1:
                        if kare_no <= self.son_kare_no:
                            # Eski / sıra dışı gelen paketi işleme almadan at
                            self.sira_disi_kare += 1
                            continue
                        if kare_no > self.son_kare_no + 1:
                            self.kayip_kare += (kare_no - self.son_kare_no - 1)
                        self.son_kare_no = kare_no
                    else:
                        self.son_kare_no = kare_no

                # 3. QR sonuçlarını güncelle ve 2 sn filtreli CSV'ye kaydet
                if qr_sonuclar:
                    self.guncel_qr_sonuclar = qr_sonuclar
                    self.son_qr_zamani = time.time()
                    self._qr_csv_kaydet(kare_no, qr_sonuclar)

    def calistir(self) -> None:
        video_thread = threading.Thread(target=self._video_okuma_dongusu, daemon=True)
        telemetri_thread = threading.Thread(target=self._telemetri_ve_eko_dongusu, daemon=True)

        video_thread.start()
        telemetri_thread.start()

        print(
            f"Yer İstasyonu Alıcısı başlatıldı | Video UDP:{self.video_port} ({self.codec.upper()}) | "
            f"Telemetri UDP:{self.telemetri_port} | Eko -> {self.iha_ip}:{self.eko_port}"
        )
        print("Kapatmak için pencere aktifken 'q' tuşuna basın.")

        onceki_olcum_zamani = time.time()
        onceki_rx_bayt = arayuz_rx_bayt_oku(self.arayuz)
        guncel_mbps = 0.0

        try:
            while self.calisiyor:
                simdi = time.time()

                with self.kilit:
                    kare = self.son_kare.copy() if self.son_kare is not None else None
                    son_kare_ts = self.son_kare_zamani
                    fps = self.fps
                    kayip = self.kayip_kare
                    sira_disi = self.sira_disi_kare
                    son_qr_metni = self.son_okunan_qr_metni
                    # Kutu titreşimini önlemek için son QR tespitini 0.35 sn ekranda tut
                    aktif_qr = (
                        list(self.guncel_qr_sonuclar)
                        if (simdi - self.son_qr_zamani) <= 0.35
                        else []
                    )

                baglanti_yok = (son_kare_ts == 0.0) or ((simdi - son_kare_ts) > BAGLANTI_ZAMAN_ASIMI_SN)

                if kare is None:
                    kare = np.zeros((480, 640, 3), dtype=np.uint8)

                # qr_okuyucu.qr_ciz(kare, sonuclar) kareyi yerinde (in-place) günceller
                if not baglanti_yok and aktif_qr:
                    qr_ciz(kare, aktif_qr)

                yukseklik, genislik = kare.shape[:2]

                # Saniyelik Bant Genişliği (Mbps) hesabı ve olcum.csv kaydı
                olcum_gecen = simdi - onceki_olcum_zamani
                if olcum_gecen >= 1.0:
                    guncel_rx_bayt = arayuz_rx_bayt_oku(self.arayuz)
                    if guncel_rx_bayt is not None and onceki_rx_bayt is not None:
                        bayt_farki = max(0, guncel_rx_bayt - onceki_rx_bayt)
                        guncel_mbps = (bayt_farki * 8.0) / (olcum_gecen * 1_000_000.0)
                        onceki_rx_bayt = guncel_rx_bayt
                    else:
                        with self.kilit:
                            bayt_farki = self.telemetri_bayt_sayaci
                            self.telemetri_bayt_sayaci = 0
                        guncel_mbps = (bayt_farki * 8.0) / (olcum_gecen * 1_000_000.0)

                    onceki_olcum_zamani = simdi

                    with open(OLCUM_CSV_DOSYASI, "a", newline="", encoding="utf-8") as f:
                        yazici = csv.writer(f)
                        yazici.writerow([
                            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            f"{0.0 if baglanti_yok else fps:.2f}",
                            f"{guncel_mbps:.3f}",
                            kayip,
                            sira_disi,
                            son_qr_metni,
                            "BAGLANTI_YOK" if baglanti_yok else "AKTIF",
                        ])

                # Sol üst köşe performans HUD paneli
                gosterilen_fps = 0.0 if baglanti_yok else fps
                cv2.rectangle(kare, (8, 8), (340, 95), (0, 0, 0), thickness=-1)
                cv2.putText(
                    kare,
                    f"FPS: {gosterilen_fps:.1f}  |  Hiz: {guncel_mbps:.2f} Mbps",
                    (16, 33),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.58,
                    (0, 255, 0),
                    2,
                    cv2.LINE_AA,
                )
                cv2.putText(
                    kare,
                    f"Kayip Kare: {kayip}  |  Sira Disi: {sira_disi}",
                    (16, 60),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.55,
                    (0, 255, 255),
                    2,
                    cv2.LINE_AA,
                )
                cv2.putText(
                    kare,
                    f"Codec: {self.codec.upper()}  |  IHA: {self.iha_ip}",
                    (16, 85),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.50,
                    (200, 200, 200),
                    1,
                    cv2.LINE_AA,
                )

                # Ekranın alt şeridine okunan son QR metnini yazdır
                alt_metin = f"Okunan QR: {son_qr_metni}" if son_qr_metni else "Okunan QR: -"
                alt_metin_ascii = alt_metin.translate(_TR_ASCII)
                cv2.rectangle(kare, (0, yukseklik - 36), (genislik, yukseklik), (0, 0, 0), thickness=-1)
                cv2.putText(
                    kare,
                    alt_metin_ascii,
                    (12, yukseklik - 11),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.62,
                    (0, 255, 0),
                    2,
                    cv2.LINE_AA,
                )

                # Bağlantı 1 saniyeden uzun süre kesildiyse kırmızı uyarı bas
                if baglanti_yok:
                    uyari = "BAGLANTI YOK"
                    (ug, uy), _ = cv2.getTextSize(uyari, cv2.FONT_HERSHEY_SIMPLEX, 1.3, 3)
                    ux = max(10, (genislik - ug) // 2)
                    uy_pos = max(uy + 20, yukseklik // 2)
                    cv2.rectangle(
                        kare,
                        (ux - 15, uy_pos - uy - 15),
                        (ux + ug + 15, uy_pos + 15),
                        (0, 0, 0),
                        thickness=-1,
                    )
                    cv2.putText(
                        kare,
                        uyari,
                        (ux, uy_pos),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        1.3,
                        (0, 0, 255),
                        3,
                        cv2.LINE_AA,
                    )

                cv2.imshow("Yer Istasyonu - Canli Goruntu (Cikis: q)", kare)
                if cv2.waitKey(15) & 0xFF in (ord("q"), 27):
                    break

        except KeyboardInterrupt:
            pass
        finally:
            self.calisiyor = False
            self.cap.release()
            self.telemetri_soket.close()
            self.eko_soket.close()
            cv2.destroyAllWindows()
            print("Yer İstasyonu Alıcısı temiz şekilde kapatıldı.")


def main() -> None:
    parser = argparse.ArgumentParser(description="IHA Yer Istasyonu GStreamer Alicisi")
    parser.add_argument(
        "--iha-ip",
        default=VARSAYILAN_IHA_IP,
        help="Gonderici (IHA) IP adresi (Tek PC testi icin 127.0.0.1 verin)",
    )
    parser.add_argument(
        "--codec",
        choices=["h264", "mjpeg"],
        default="h264",
        help="GStreamer video sikistirma formati (h264 veya mjpeg)",
    )
    parser.add_argument(
        "--arayuz",
        default=None,
        help="Mbps olcumu icin Ethernet arayuz adi (orn. enp3s0)",
    )
    args = parser.parse_args()

    alici = YerIstasyonuAlici(
        iha_ip=args.iha_ip,
        codec=args.codec,
        arayuz=args.arayuz,
    )
    alici.calistir()


if __name__ == "__main__":
    main()
    