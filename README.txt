================================================================================
QGIS-Erweiterung: Waldschätzung (Bestand, Bringung & Unterabteilung)
Version 1.1.0
================================================================================

1. INSTALLATION IN QGIS
-----------------------
1. Öffne QGIS.
2. Gehe im oberen Menü auf: Erweiterungen -> Erweiterungen verwalten und installieren...
3. Wähle links den Reiter "Aus ZIP installieren".
4. Wähle die ZIP-Datei der Erweiterung aus und klicke auf "Erweiterung installieren".
5. Die Werkzeuge erscheinen dauerhaft in der Verarbeitungswerkzeugkiste
   (Strg+Alt+T) unter dem Eintrag "Waldschätzung":
   - Waldschätzung: Baumstamm, Baumkrone und Bestandesklasse
   - Bringung: Hangneigung & Einzugsgebiete
   - Unterabteilung: Forstliche Bestandes- & Bringungsgliederung


================================================================================
WERKZEUG 1: Waldschätzung: Baumstamm, Baumkrone und Bestandesklasse
================================================================================

Eingabedaten:
- AOI / Grundstücke Layer: Polygon-Layer der Waldgrundstücke (z. B. DKM).
  Tipp: Aktiviere "Nur gewählte Objekte", um nur markierte Parzellen zu rechnen.
- Feld für Grundstücksnummer (GST): Spalte mit der Grundstücksnummer (z. B. GST/GNR).
- Normalhöhen-Raster (nDOM): Oberflächenmodell minus Geländemodell in Metern.

Empfohlene Richtwerte:
- Mindesthöhe für Baumwipfel (m): 2.0 m
- Sliding Window Size (m): 4.5 - 5.5 m (Stangenholz) | 6.0 - 7.5 m (Altholz)
- Snap Distance (m): 2.5 m (max. halbe Sliding Window Size)
- Maximaler Kronenradius (m): 8.0 m
- BHD-Schätzung (BHD = a * Höhe^b):
  * Fichte / Tanne (Gebirgswald): a = 1.45, b = 1.02
  * Mischwald: a = 1.55, b = 1.02
  * Laubholz (Buche / Ahorn): a = 1.75, b = 1.02
- Unechte Formzahl f: 0.45 (Fichte/Tanne) | 0.43 (Kiefer/Lärche) | 0.48 (Buche)
- Mindestgröße je Bestandesklasse (m²): 1000 m²
- Plenter-Suchradius / Mindestklassen: 14.0 m Radius / ab 3 Klassen

Erzeugte Ergebnis-Layer:
1. 01_Tree_Tops_Punkte.gpkg: Einzelbäume mit Baumhoehe, BHD (cm) und VFM.
   Darstellung: Farbe nach Baumhöhe, Punktgröße skaliert nach BHD (0.4 - 4.0).
2. 02_Voronoi_Kronenflaechen.gpkg: Abgegrenzte Kronenflächen (kronen_m2).
3. 03_Bestandesklassen.gpkg: Bestandesklassen pro Grundstück (GST) inklusive
   Flaeche_ha, Stammzahl, mittlere_Bestandeshoehe, VFM_gesamt und VFM_pro_ha.


================================================================================
WERKZEUG 2: Bringung: Hangneigung & Einzugsgebiete
================================================================================

Eingabedaten:
- AOI / Grundstücke Layer: Polygon-Layer der untersuchten Waldfläche.
- Geländemodell (DGM): Digitales Geländemodell in Metern.

Empfohlene Richtwerte:
- Ziel-Auflösung / Glättung des DGM (m): 2.5 m
- Mindestgröße für Hangneigungs-Inseln (Pixel): 25 Pixel
- Einzugsgebiet (Watershed) Mindestgröße (Pixel): 500 Pixel
  (höherer Wert = größere Geländekammern; kleinerer Wert = feinere Gräben)
- Hangneigungsgrenzen (%):
  * Klasse 1: Schleppergelände (0 - 30 %)
  * Klasse 2: Übergangsgelände (30 - 50 %)
  * Klasse 3: Seilgelände (50 - 100 %)
  * Klasse 4: Extremes Gelände (100 - 150 %)
  * Klasse 5: Felsband (> 150 %)

Erzeugte Ergebnis-Layer:
1. 01_DGM_AOI_geglaettet.tif: Auf die AOI zugeschnittenes & geglättetes DGM.
2. 02_Hangneigung_Prozent.tif: Hangneigungsraster in Prozent.
3. 03_Betriebsklassen_nach_EZG.gpkg: Topologisch lückenlose Bringungsklassen
   gegliedert nach hydrologischen Einzugsgebieten (EZG_01, EZG_02, ...).


================================================================================
WERKZEUG 3: Unterabteilung: Forstliche Bestandes- & Bringungsgliederung
================================================================================

Eingabedaten:
- Layer Bestandesklassen: Ergebnis-Layer "03_Bestandesklassen" aus Werkzeug 1.
- Layer Betriebsklassen nach EZG: Ergebnis-Layer "03_Betriebsklassen_nach_EZG"
  aus Werkzeug 2.
- Optional: Einzelbaum-Layer "01_Tree_Tops_Punkte" für Stammzahl- und
  Vorratsberechnung (VFM) je Unterabteilung.

Empfohlene Richtwerte:
- Mindestgröße einer Unterabteilung (m²): 2500 m² (verschmilzt kleinere Splitter)
- Detailgrad der Grenzlinien (m): 3.5 m (2.5 m = detailreich | 6.0 m = ruhig)

Erzeugter Ergebnis-Layer:
- 05_Unterabteilungen.gpkg: Lückenlose und überlappungsfreie forstliche
  Unterabteilungen (nummeriert von Nord nach Süd: 1, 2, 3, ...) mit roter
  Forstkartengrenze, Nummern-Beschriftung sowie allen Kennzahlen (GST,
  Einzugsgebiet, Bestandesklasse, betriebsklasse, Flaeche_ha, Stammzahl,
  mittlere_Bestandeshoehe, VFM_gesamt, VFM_pro_ha).
================================================================================
