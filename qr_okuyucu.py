import cv2

# QR çözücüyü bir kez oluştur (her karede yeniden oluşturmak gereksiz yavaşlık)
dedektor = cv2.QRCodeDetector()


def qr_coz(kare):
    """Karedeki QR kodları bulur.
    Döndürür: [{"metin": "...", "koseler": [[x,y], [x,y], [x,y], [x,y]]}, ...]
    QR yoksa boş liste döndürür."""
    sonuclar = []

    # Karedeki bütün QR'ları bul ve çöz
    bulundu, metinler, noktalar, _ = dedektor.detectAndDecodeMulti(kare)

    if not bulundu:          # Hiç QR yoksa boş liste
        return sonuclar

    # Her QR için metni ve 4 köşesini listeye ekle
    for metin, koseler in zip(metinler, noktalar):
        if metin == "":      # QR bulundu ama okunamadıysa atla
            continue
        sonuclar.append({
            "metin": metin,
            "koseler": koseler.astype(int).tolist()
        })

    return sonuclar


def qr_ciz(kare, sonuclar):
    """Bulunan QR'ların etrafına yeşil kutu çizer, metnini üstüne yazar."""
    for qr in sonuclar:
        koseler = qr["koseler"]

        # 4 köşeyi sırayla çizgiyle birleştir (son köşeden ilk köşeye de)
        for i in range(4):
            baslangic = tuple(koseler[i])
            bitis = tuple(koseler[(i + 1) % 4])
            cv2.line(kare, baslangic, bitis, (0, 255, 0), 3)

        # Metni ilk köşenin biraz üstüne yaz
        x, y = koseler[0]
        cv2.putText(kare, qr["metin"], (x, y - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)


# Bu dosya doğrudan çalıştırılırsa test yap
if __name__ == "__main__":
    kare = cv2.imread("hedef1.png")
    sonuclar = qr_coz(kare)
    print(sonuclar)
    qr_ciz(kare, sonuclar)
    cv2.imshow("QR testi", kare)
    cv2.waitKey(0)
    cv2.destroyAllWindows()