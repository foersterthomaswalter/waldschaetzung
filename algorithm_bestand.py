import os
import time
import numpy as np
from scipy.ndimage import maximum_filter
from osgeo import gdal
from qgis.PyQt.QtCore import QCoreApplication, QVariant
from qgis.PyQt.QtGui import QColor, QIcon
from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterField,
    QgsProcessingParameterRasterLayer,
    QgsProcessingParameterNumber,
    QgsProcessingParameterFolderDestination,
    QgsProcessingUtils,
    QgsVectorLayer,
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsField,
    QgsSymbol,
    QgsSymbolLayer,
    QgsProperty,
    QgsProject,
    QgsRendererRange,
    QgsGraduatedSymbolRenderer,
    QgsRendererCategory,
    QgsCategorizedSymbolRenderer,
    QgsWkbTypes
)


import processing

class ForstTreeTopsVoronoi(QgsProcessingAlgorithm):
    INPUT_AOI = 'INPUT_AOI'
    INPUT_NDOM = 'INPUT_NDOM'
    MIN_TREE_HEIGHT = 'MIN_TREE_HEIGHT'
    WINDOW_SIZE_M = 'WINDOW_SIZE_M'
    SNAP_DIST_M = 'SNAP_DIST_M'
    MAX_CROWN_RADIUS = 'MAX_CROWN_RADIUS'
    BHD_FAKTOR_A = 'BHD_FAKTOR_A'
    BHD_EXPONENT_B = 'BHD_EXPONENT_B'
    FORMZAHL_F = 'FORMZAHL_F'
    MIN_BESTAND_M2 = 'MIN_BESTAND_M2'
    PLENTER_RADIUS = 'PLENTER_RADIUS'
    PLENTER_MIN_CLASSES = 'PLENTER_MIN_CLASSES'
    OUTPUT_FOLDER = 'OUTPUT_FOLDER'
    GST_FIELD = 'GST_FIELD'

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return ForstTreeTopsVoronoi()

    def name(self):
        return 'forsttreetopsvoronoi'

    def displayName(self):
        return self.tr('Bestand: Stammzahl,Baumkrone und Bestandesklasse')

    def icon(self):
        icon_path = os.path.join(os.path.dirname(__file__), 'bestand.png')
        return QIcon(icon_path)

    def group(self):
        return ''

    def groupId(self):
        return ''

    def shortHelpString(self):
        return self.tr(
            'Erkennt Baumwipfel (Tree Tops) über ein gleitendes Suchfenster, '
            'berechnet Voronoi-Kronenflächen (inkl. BHD und VFM) und scheidet '
            'ruhige Unterabteilungen (03_Bestandesklassen) ab einer Mindestfläche aus.'
        )

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterField(
                self.GST_FIELD,
                self.tr('Feld für Grundstücksnummer (GST)'),
                parentLayerParameterName=self.INPUT_AOI,
                type=QgsProcessingParameterField.Any,
                optional=True
            )
        )

        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.INPUT_AOI,
                self.tr('AOI / Grundstücke Layer'),
                list((QgsProcessing.TypeVectorPolygon,))
            )
        )

        self.addParameter(
            QgsProcessingParameterRasterLayer(
                self.INPUT_NDOM,
                self.tr('Normalhöhen-Raster (nDOM)')
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                self.MIN_TREE_HEIGHT,
                self.tr('Mindesthöhe für Baumwipfel in Metern'),
                type=QgsProcessingParameterNumber.Double,
                defaultValue=2.0,
                minValue=0.1
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                self.WINDOW_SIZE_M,
                self.tr('Sliding Window Size in Metern (Suchfenster-Durchmesser, z.B. 5.0 - 6.0 m)'),
                type=QgsProcessingParameterNumber.Double,
                defaultValue=5.5,
                minValue=1.0
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                self.SNAP_DIST_M,
                self.tr('Snap Distance in Metern (verschmilzt Doppelpunkte, max. halbe Fenstergröße)'),
                type=QgsProcessingParameterNumber.Double,
                defaultValue=2.5,
                minValue=0.1
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                self.MAX_CROWN_RADIUS,
                self.tr('Maximaler Kronenradius in Metern (begrenzt Voronoi-Flächen auf Blößen)'),
                type=QgsProcessingParameterNumber.Double,
                defaultValue=8.0,
                minValue=1.0
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                self.BHD_FAKTOR_A,
                self.tr('BHD-Schätzung: Faktor a (Formel: a * Höhe ^ b | Nadelholz: 1.45, Laubholz: 1.75)'),
                type=QgsProcessingParameterNumber.Double,
                defaultValue=1.45,
                minValue=0.1
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                self.BHD_EXPONENT_B,
                self.tr('BHD-Schätzung: Exponent b (Formel: a * Höhe ^ b | Standard: 1.02)'),
                type=QgsProcessingParameterNumber.Double,
                defaultValue=1.02,
                minValue=0.1
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                self.FORMZAHL_F,
                self.tr('Unechte Formzahl f für VFM (Fichte/Tanne: 0.45, Buche: 0.48, Kiefer/Lärche: 0.43)'),
                type=QgsProcessingParameterNumber.Double,
                defaultValue=0.45,
                minValue=0.1,
                maxValue=1.0
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                self.MIN_BESTAND_M2,
                self.tr('Mindestgröße je Unterabteilung / Bestandesklasse in m² (Standard: 1000 m²)'),
                type=QgsProcessingParameterNumber.Double,
                defaultValue=1000.0,
                minValue=0.0
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                self.PLENTER_RADIUS,
                self.tr('Plenter-Suchradius in Metern (prüft Durchmischung der Wuchsklassen)'),
                type=QgsProcessingParameterNumber.Double,
                defaultValue=14.0,
                minValue=2.0
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                self.PLENTER_MIN_CLASSES,
                self.tr('Mindestanzahl verschiedener Wuchsklassen im Umkreis für "Plenterartig" (z.B. 3)'),
                type=QgsProcessingParameterNumber.Integer,
                defaultValue=3,
                minValue=2,
                maxValue=6
            )
        )

        self.addParameter(
            QgsProcessingParameterFolderDestination(
                self.OUTPUT_FOLDER,
                self.tr('Zielordner für Ergebnisse')
            )
        )

    def get_safe_gpkg_path(self, folder, base_name):
        path = os.path.join(folder, f'{base_name}.gpkg')
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                stamp = time.strftime('%H%M%S')
                path = os.path.join(folder, f'{base_name}_{stamp}.gpkg')
        return path

    def get_vec_layer(self, source):
        if isinstance(source, QgsVectorLayer):
            return source
        return QgsVectorLayer(source, 'tmp', 'ogr')

    def processAlgorithm(self, parameters, context, feedback):
        ndom_layer = self.parameterAsRasterLayer(parameters, self.INPUT_NDOM, context)
        gst_fields = self.parameterAsFields(parameters, self.GST_FIELD, context)
        gst_field = gst_fields.__getitem__(0) if gst_fields else ''
        min_height = self.parameterAsDouble(parameters, self.MIN_TREE_HEIGHT, context)
        win_size_m = self.parameterAsDouble(parameters, self.WINDOW_SIZE_M, context)
        snap_dist_m = self.parameterAsDouble(parameters, self.SNAP_DIST_M, context)
        max_radius = self.parameterAsDouble(parameters, self.MAX_CROWN_RADIUS, context)
        bhd_a = self.parameterAsDouble(parameters, self.BHD_FAKTOR_A, context)
        bhd_b = self.parameterAsDouble(parameters, self.BHD_EXPONENT_B, context)
        formzahl_f = self.parameterAsDouble(parameters, self.FORMZAHL_F, context)
        min_bestand_m2 = self.parameterAsDouble(parameters, self.MIN_BESTAND_M2, context)
        plenter_radius = self.parameterAsDouble(parameters, self.PLENTER_RADIUS, context)
        plenter_min_cls = self.parameterAsInt(parameters, self.PLENTER_MIN_CLASSES, context)
        out_folder = self.parameterAsString(parameters, self.OUTPUT_FOLDER, context)
        os.makedirs(out_folder, exist_ok=True)

        if snap_dist_m > (win_size_m / 2.0):
            snap_dist_m = win_size_m / 2.0
            feedback.pushInfo(f'Hinweis: Snap Distance wurde automatisch auf {snap_dist_m:.2f} m begrenzt.')

        treetops_path = self.get_safe_gpkg_path(out_folder, '01_Tree_Tops_Punkte')
        voronoi_path = self.get_safe_gpkg_path(out_folder, '02_Voronoi_Kronenflaechen')
        bestandes_path = self.get_safe_gpkg_path(out_folder, '03_Bestandesklassen')

        target_crs = ndom_layer.crs()

        # AOI-Auswahl extrahieren, projizieren & reparieren
        aoi_extracted = processing.run(
            'native:savefeatures',
            {
                'INPUT': parameters.get(self.INPUT_AOI),
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        aoi_reprojected = processing.run(
            'native:reprojectlayer',
            {
                'INPUT': aoi_extracted,
                'TARGET_CRS': target_crs,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        aoi_fixed = processing.run(
            'native:fixgeometries',
            {
                'INPUT': aoi_reprojected,
                'METHOD': 1,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        # 0. Zuerst AOI-Puffer berechnen, damit wir NUR den kleinen AOI-Ausschnitt aus dem nDOM laden!
        feedback.pushInfo('0. Schneide nDOM-Ausschnitt exakt auf AOI zu (Schnellmodus)...')
        aoi_buffered = processing.run(
            'native:buffer',
            {
                'INPUT': aoi_fixed,
                'DISTANCE': max_radius + win_size_m,
                'SEGMENTS': 5,
                'END_CAP_STYLE': 0,
                'JOIN_STYLE': 0,
                'MITER_LIMIT': 2.0,
                'DISSOLVE': True,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        # Rasterrechner läuft dank EXTENT nur im kleinen AOI-Rechteck (dauert < 1 Sekunde!)
        ndom_subset = processing.run(
            'native:rastercalc',
            {
                'EXPRESSION': f'"{ndom_layer.name()}@1"',
                'LAYERS': list((ndom_layer,)),
                'EXTENT': aoi_buffered,
                'CELLSIZE': ndom_layer.rasterUnitsPerPixelX(),
                'CRS': target_crs,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        # 1. Kleinen nDOM-Ausschnitt exakt auf gepufferte AOI-Maske zuschneiden
        feedback.pushInfo('1. Maskiere nDOM auf AOI-Grenze...')
        ndom_clipped = processing.run(
            'gdal:cliprasterbymasklayer',
            {
                'INPUT': ndom_subset,
                'MASK': aoi_buffered,
                'SOURCE_CRS': target_crs,
                'TARGET_CRS': target_crs,
                'CROP_TO_CUTLINE': True,
                'KEEP_RESOLUTION': True,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        # 2. Gleitendes Maximum-Filter (Sliding Window)
        feedback.pushInfo(f'2. Berechne lokale Maxima (Sliding Window: {win_size_m} m, Snap: {snap_dist_m} m)...')
        ds = gdal.Open(ndom_clipped)
        band = ds.GetRasterBand(1)
        nodata = band.GetNoDataValue()
        arr = band.ReadAsArray().astype(np.float32)
        gt = ds.GetGeoTransform()
        ds = None

        pixel_size = abs(gt.__getitem__(1))
        win_px = max(3, int(round(win_size_m / pixel_size)))
        if win_px % 2 == 0:
            win_px += 1

        radius_px = win_px // 2
        y_idx, x_idx = np.ogrid[-radius_px:radius_px + 1, -radius_px:radius_px + 1]
        circle_mask = (x_idx**2 + y_idx**2) <= (radius_px**2)

        valid_mask = np.ones(arr.shape, dtype=bool)
        if nodata is not None:
            valid_mask &= ~np.isclose(arr, nodata)
        valid_mask &= ~np.isnan(arr)

        arr_clean = np.where(valid_mask, arr, -9999.0)
        local_max = maximum_filter(arr_clean, footprint=circle_mask, mode='constant', cval=-9999.0)

        is_peak = (arr_clean == local_max) & (arr_clean >= min_height) & valid_mask
        rows, cols = np.where(is_peak)

        raw_pts_layer = QgsVectorLayer(f'Point?crs={target_crs.authid()}', 'raw_peaks', 'memory')
        prov = raw_pts_layer.dataProvider()
        prov.addAttributes(list((QgsField('hoehe_m', QVariant.Double),)))
        raw_pts_layer.updateFields()

        gt0 = gt.__getitem__(0)
        gt1 = gt.__getitem__(1)
        gt2 = gt.__getitem__(2)
        gt3 = gt.__getitem__(3)
        gt4 = gt.__getitem__(4)
        gt5 = gt.__getitem__(5)

        feats = list()
        for r, c in zip(rows, cols):
            x = gt0 + (c + 0.5) * gt1 + (r + 0.5) * gt2
            y = gt3 + (c + 0.5) * gt4 + (r + 0.5) * gt5
            h_val = round(float(arr_clean.__getitem__((r, c))), 2)
            feat = QgsFeature()
            feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(x, y)))
            feat.setAttributes(list((h_val,)))
            feats.append(feat)

        prov.addFeatures(feats)
        raw_pts_layer.updateExtents()

        # 3. Snap Distance anwenden (DBSCAN + Centroid)
        feedback.pushInfo(f'3. Verschmelze nahe Punkte innerhalb {snap_dist_m} m...')
        clustered = processing.run(
            'native:dbscanclustering',
            {
                'INPUT': raw_pts_layer,
                'MIN_SIZE': 1,
                'EPS': snap_dist_m,
                'DBSCAN*': False,
                'FIELD_NAME': 'CLUSTER_ID',
                'SIZE_FIELD_NAME': 'CLUSTER_SIZE',
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        dissolved_pts = processing.run(
            'native:dissolve',
            {
                'INPUT': clustered,
                'FIELD': list(('CLUSTER_ID',)),
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        snapped_pts = processing.run(
            'native:centroids',
            {
                'INPUT': dissolved_pts,
                'ALL_PARTS': False,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        sampled_pts = processing.run(
            'native:rastersampling',
            {
                'INPUT': snapped_pts,
                'RASTERCOPY': ndom_clipped,
                'COLUMN_PREFIX': 'ndom_',
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        tops_with_id = processing.run(
            'native:fieldcalculator',
            {
                'INPUT': sampled_pts,
                'FIELD_NAME': 'baum_id',
                'FIELD_TYPE': 1,
                'FIELD_LENGTH': 10,
                'FORMULA': '$id',
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        # Baumhoehe auf 0.5m Stufen runden
        tops_clean = processing.run(
            'native:fieldcalculator',
            {
                'INPUT': tops_with_id,
                'FIELD_NAME': 'Baumhoehe',
                'FIELD_TYPE': 0,
                'FIELD_LENGTH': 8,
                'FIELD_PRECISION': 1,
                'FORMULA': 'round(coalesce("ndom_1", "hoehe_m") * 2.0, 0) / 2.0',
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        # BHD in cm ohne Kommastelle (Integer)
        feedback.pushInfo('4. Berechne BHD (ganzzahlig) und VFM (2 Kommastellen)...')
        tops_with_bhd = processing.run(
            'native:fieldcalculator',
            {
                'INPUT': tops_clean,
                'FIELD_NAME': 'BHD',
                'FIELD_TYPE': 1,
                'FIELD_LENGTH': 8,
                'FORMULA': f'round({bhd_a} * ("Baumhoehe" ^ {bhd_b}), 0)',
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        # Volumen in Vorratsfestmetern (VFM) auf 2 Kommastellen
        vfm_formula = f'round((pi() / 4.0) * (("BHD" / 100.0) ^ 2) * "Baumhoehe" * {formzahl_f}, 2)'
        tops_with_vfm = processing.run(
            'native:fieldcalculator',
            {
                'INPUT': tops_with_bhd,
                'FIELD_NAME': 'VFM',
                'FIELD_TYPE': 0,
                'FIELD_LENGTH': 10,
                'FIELD_PRECISION': 2,
                'FORMULA': vfm_formula,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        tops_final_fields = processing.run(
            'native:deletecolumn',
            {
                'INPUT': tops_with_vfm,
                'COLUMN': list(('hoehe_m', 'CLUSTER_ID', 'CLUSTER_SIZE', 'ndom_1')),
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        processing.run(
            'native:clip',
            {
                'INPUT': tops_final_fields,
                'OVERLAY': aoi_fixed,
                'OUTPUT': treetops_path
            },
            context=context, feedback=feedback, is_child_algorithm=True
        )

        # 5. Voronoi-Polygone berechnen
        feedback.pushInfo('5. Berechne Voronoi-Polygone für die Kronenabgrenzung...')
        voronoi_raw = processing.run(
            'native:voronoipolygons',
            {
                'INPUT': tops_final_fields,
                'BUFFER': 10.0,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        max_crown_buf = processing.run(
            'native:buffer',
            {
                'INPUT': tops_final_fields,
                'DISTANCE': max_radius,
                'SEGMENTS': 8,
                'END_CAP_STYLE': 0,
                'JOIN_STYLE': 0,
                'MITER_LIMIT': 2.0,
                'DISSOLVE': False,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        voronoi_limited = processing.run(
            'native:clip',
            {
                'INPUT': voronoi_raw,
                'OVERLAY': max_crown_buf,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        voronoi_aoi = processing.run(
            'native:clip',
            {
                'INPUT': voronoi_limited,
                'OVERLAY': aoi_fixed,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        processing.run(
            'native:fieldcalculator',
            {
                'INPUT': voronoi_aoi,
                'FIELD_NAME': 'kronen_m2',
                'FIELD_TYPE': 0,
                'FIELD_LENGTH': 10,
                'FIELD_PRECISION': 2,
                'FORMULA': 'round(area($geometry), 2)',
                'OUTPUT': voronoi_path
            },
            context=context, feedback=feedback, is_child_algorithm=True
        )

        # 6. Bestandesklassen aus 02_Voronoi_Kronenflaechen durch Nachbarschaftsabgleich ableiten
        feedback.pushInfo('6. Leite 03_Bestandesklassen durch Nachbarschaftsabgleich der Voronoi-Flächen ab...')

        # 6.1 Voronoi-Kronenflächen in Wuchsklassen 2 bis 6 einteilen
        vor_klasse = processing.run(
            'native:fieldcalculator',
            {
                'INPUT': voronoi_aoi,
                'FIELD_NAME': 'klasse',
                'FIELD_TYPE': 1,
                'FIELD_LENGTH': 5,
                'FORMULA': (
                    'CASE '
                    'WHEN "Baumhoehe" <= 2.0 THEN 2 '
                    'WHEN "Baumhoehe" <= 10.0 THEN 3 '
                    'WHEN "Baumhoehe" <= 20.0 THEN 4 '
                    'WHEN "Baumhoehe" <= 30.0 THEN 5 '
                    'ELSE 6 '
                    'END'
                ),
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        vor_base = processing.run(
            'native:retainfields',
            {
                'INPUT': vor_klasse,
                'FIELDS': list(('klasse',)),
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        # 6.2 Unbestockte Zwischenräume (Blößen) als Klasse 1 ergänzen -> lückenloses Mosaik
        aoi_union = processing.run(
            'native:dissolve',
            {
                'INPUT': aoi_fixed,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        bloesse_diff = processing.run(
            'native:difference',
            {
                'INPUT': aoi_union,
                'OVERLAY': vor_base,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        bloesse_single = processing.run(
            'native:multiparttosingleparts',
            {
                'INPUT': bloesse_diff,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        bloesse_cls = processing.run(
            'native:fieldcalculator',
            {
                'INPUT': bloesse_single,
                'FIELD_NAME': 'klasse',
                'FIELD_TYPE': 1,
                'FIELD_LENGTH': 5,
                'FORMULA': '1',
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        bloesse_base = processing.run(
            'native:retainfields',
            {
                'INPUT': bloesse_cls,
                'FIELDS': list(('klasse',)),
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        mosaic_vec = processing.run(
            'native:mergevectorlayers',
            {
                'LAYERS': list((vor_base, bloesse_base)),
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        # 6.3 Nachbarschaftsabgleich (2 Durchläufe Mehrheitsfilter + Plenter-Prüfung)
        feedback.pushInfo('   -> Führe Nachbarschaftsabgleich (Mehrheitsfilter & Plenter-Check) durch...')
        for pass_idx in range(2):
            # Kleiner Puffer (0.2m) stellt sicher, dass alle angrenzenden Voronoi-Nachbarn erfasst werden
            nbr_buf = processing.run(
                'native:buffer',
                {
                    'INPUT': mosaic_vec,
                    'DISTANCE': 0.2,
                    'SEGMENTS': 2,
                    'END_CAP_STYLE': 0,
                    'JOIN_STYLE': 0,
                    'MITER_LIMIT': 2.0,
                    'DISSOLVE': False,
                    'OUTPUT': 'TEMPORARY_OUTPUT'
                },
                context=context, feedback=feedback, is_child_algorithm=True
            ).get('OUTPUT')

            # SUMMARIES: 9 = majority (häufigste Nachbarklasse), 11 = count_distinct (Anzahl versch. Klassen)
            nbr_summary = processing.run(
                'native:joinbylocationsummary',
                {
                    'INPUT': nbr_buf,
                    'PREDICATE': list((0,)),
                    'JOIN': mosaic_vec,
                    'JOIN_FIELDS': list(('klasse',)),
                    'SUMMARIES': list((9, 11)),
                    'DISCARD_NONMATCHING': False,
                    'OUTPUT': 'TEMPORARY_OUTPUT'
                },
                context=context, feedback=feedback, is_child_algorithm=True
            ).get('OUTPUT')

            # Ergebnisse zurück auf das exakte Original-Polygon übertragen (Predikat 2 = equals)
            mosaic_joined = processing.run(
                'native:joinattributesbylocation',
                {
                    'INPUT': mosaic_vec,
                    'PREDICATE': list((2,)),
                    'JOIN': nbr_summary,
                    'JOIN_FIELDS': list(('klasse_majority', 'klasse_count_distinct')),
                    'METHOD': 1,
                    'DISCARD_NONMATCHING': False,
                    'PREFIX': 'nbr_',
                    'OUTPUT': 'TEMPORARY_OUTPUT'
                },
                context=context, feedback=feedback, is_child_algorithm=True
            ).get('OUTPUT')

            # Regel: Größere Blößen (>= 150 m²) bleiben Blöße (1);
            # im 2. Durchlauf wird bei starker Durchmischung Klasse 7 (Plenterartig) gesetzt;
            # ansonsten wird die Mehrheitsklasse der Nachbarn übernommen!
            if pass_idx == 1:
                formula_str = (
                    'CASE '
                    'WHEN "klasse" = 1 AND area($geometry) >= 150.0 THEN 1 '
                    f'WHEN coalesce("nbr_klasse_count_distinct", 0) >= {plenter_min_cls} THEN 7 '
                    'ELSE coalesce("nbr_klasse_majority", "klasse") '
                    'END'
                )
            else:
                formula_str = (
                    'CASE '
                    'WHEN "klasse" = 1 AND area($geometry) >= 150.0 THEN 1 '
                    'ELSE coalesce("nbr_klasse_majority", "klasse") '
                    'END'
                )

            mosaic_updated = processing.run(
                'native:fieldcalculator',
                {
                    'INPUT': mosaic_joined,
                    'FIELD_NAME': 'klasse',
                    'FIELD_TYPE': 1,
                    'FIELD_LENGTH': 5,
                    'FORMULA': formula_str,
                    'OUTPUT': 'TEMPORARY_OUTPUT'
                },
                context=context, feedback=feedback, is_child_algorithm=True
            ).get('OUTPUT')

            mosaic_vec = processing.run(
                'native:retainfields',
                {
                    'INPUT': mosaic_updated,
                    'FIELDS': list(('klasse',)),
                    'OUTPUT': 'TEMPORARY_OUTPUT'
                },
                context=context, feedback=feedback, is_child_algorithm=True
            ).get('OUTPUT')

        # 6.4 Benachbarte Waben gleicher Klasse zu zusammenhängenden Unterabteilungen vereinigen
        diss_vec = processing.run(
            'native:dissolve',
            {
                'INPUT': mosaic_vec,
                'FIELD': list(('klasse',)),
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        current_vec = processing.run(
            'native:multiparttosingleparts',
            {
                'INPUT': diss_vec,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        # 6.5 Alle Splitter unterhalb min_bestand_m2 (außer echte Blößen) an Nachbar mit längster Grenze anschließen
        if min_bestand_m2 > 0:
            feedback.pushInfo(f'   -> Verschmelze Restflächen unter {min_bestand_m2} m² (Blößen ausgenommen)...')
            for _ in range(15):
                mem_lyr = QgsProcessingUtils.mapLayerFromString(current_vec, context)
                if not mem_lyr or mem_lyr.featureCount() <= 1:
                    break

                small_ids = list(
                    f.id() for f in mem_lyr.getFeatures()
                    if f.__getitem__('klasse') != 1 and f.geometry().area() < min_bestand_m2
                )
                if not small_ids:
                    break

                mem_lyr.selectByIds(small_ids)

                elim = processing.run(
                    'qgis:eliminateselectedpolygons',
                    {
                        'INPUT': mem_lyr,
                        'MODE': 2,
                        'OUTPUT': 'TEMPORARY_OUTPUT'
                    },
                    context=context, feedback=feedback, is_child_algorithm=True
                ).get('OUTPUT')

                diss = processing.run(
                    'native:dissolve',
                    {
                        'INPUT': elim,
                        'FIELD': list(('klasse',)),
                        'OUTPUT': 'TEMPORARY_OUTPUT'
                    },
                    context=context, feedback=feedback, is_child_algorithm=True
                ).get('OUTPUT')

                current_vec = processing.run(
                    'native:multiparttosingleparts',
                    {
                        'INPUT': diss,
                        'OUTPUT': 'TEMPORARY_OUTPUT'
                    },
                    context=context, feedback=feedback, is_child_algorithm=True
                ).get('OUTPUT')

        # 6.6 Außenkontur sanft glätten und mit einzelnen Grundstücken (GST) verschneiden
        feedback.pushInfo('   -> Verschneide Bestandesklassen mit einzelnen Grundstücken (GST)...')
        wuchs_smooth = processing.run(
            'native:smoothgeometry',
            {
                'INPUT': current_vec,
                'ITERATIONS': 1,
                'OFFSET': 0.20,
                'MAX_ANGLE': 180.0,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        wuchs_fixed = processing.run(
            'native:fixgeometries',
            {
                'INPUT': wuchs_smooth,
                'METHOD': 1,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        # Grundstücksnummer-Spalte direkt vom Eingangs-Source auslesen (100% zuverlässig)
        aoi_source = self.parameterAsSource(parameters, self.INPUT_AOI, context)
        avail_fields = list(f.name() for f in aoi_source.fields()) if aoi_source else list()

        chosen_col = ''
        if gst_field and gst_field in avail_fields:
            chosen_col = gst_field
        elif 'GST' in avail_fields:
            chosen_col = 'GST'
        elif 'GNR' in avail_fields:
            chosen_col = 'GNR'
        elif 'GSTNR' in avail_fields:
            chosen_col = 'GSTNR'

        if chosen_col:
            gst_expr = f'to_string("{chosen_col}")'
        else:
            gst_expr = 'to_string($id)'

        aoi_with_gst = processing.run(
            'native:fieldcalculator',
            {
                'INPUT': aoi_fixed,
                'FIELD_NAME': 'GST_VAL',
                'FIELD_TYPE': 2,
                'FIELD_LENGTH': 50,
                'FORMULA': gst_expr,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        # Bestandesklassen mit den einzelnen Grundstücken verschneiden (nimmt GST_VAL mit!)
        wuchs_intersect = processing.run(
            'native:intersection',
            {
                'INPUT': wuchs_fixed,
                'OVERLAY': aoi_with_gst,
                'INPUT_FIELDS': list(('klasse',)),
                'OVERLAY_FIELDS': list(('GST_VAL',)),
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        # Pro Grundstück (GST_VAL) und Bestandesklasse (klasse) zusammenführen!
        wuchs_grouped = processing.run(
            'native:dissolve',
            {
                'INPUT': wuchs_intersect,
                'FIELD': list(('GST_VAL', 'klasse')),
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        # GST_VAL sauber in GST umbenennen
        wuchs_renamed = processing.run(
            'native:renametablefield',
            {
                'INPUT': wuchs_grouped,
                'FIELD': 'GST_VAL',
                'NEW_NAME': 'GST',
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        # Nach Grundstück und Klasse sortieren
        wuchs_sorted = processing.run(
            'native:orderbyexpression',
            {
                'INPUT': wuchs_renamed,
                'EXPRESSION': '"GST" || \'_\' || to_string("klasse")',
                'ASCENDING': True,
                'NULLS_FIRST': False,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        # 6.7 VFM & Bestandeshöhe aus Tree Tops pro (GST + Bestandesklasse) auswerten
        feedback.pushInfo('   -> Berechne Stammzahl, mittlere Bestandeshöhe und VFM pro Grundstück & Klasse...')
        wuchs_stats = processing.run(
            'native:joinbylocationsummary',
            {
                'INPUT': wuchs_sorted,
                'PREDICATE': list((0,)),
                'JOIN': tops_final_fields,
                'JOIN_FIELDS': list(('VFM', 'Baumhoehe')),
                'SUMMARIES': list((0, 5, 6)), # 0=count, 5=sum, 6=mean
                'DISCARD_NONMATCHING': False,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        step1 = processing.run(
            'native:fieldcalculator',
            {
                'INPUT': wuchs_stats,
                'FIELD_NAME': 'Bestandesklasse',
                'FIELD_TYPE': 2,
                'FIELD_LENGTH': 60,
                'FORMULA': (
                    "CASE "
                    "WHEN \"klasse\" = 1 THEN '1: Blöße / Kahlfläche (unbestockt)' "
                    "WHEN \"klasse\" = 2 THEN '2: Jungwuchs / Kultur (bis 2 m)' "
                    "WHEN \"klasse\" = 3 THEN '3: Dickung (2 - 10 m)' "
                    "WHEN \"klasse\" = 4 THEN '4: Stangenholz (10 - 20 m)' "
                    "WHEN \"klasse\" = 5 THEN '5: Baumholz (20 - 30 m)' "
                    "WHEN \"klasse\" = 6 THEN '6: Starkes Baumholz / Altholz (> 30 m)' "
                    "ELSE '7: Plenterartig / Ungleichaltrig' "
                    "END"
                ),
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        step2 = processing.run(
            'native:fieldcalculator',
            {
                'INPUT': step1,
                'FIELD_NAME': 'Flaeche_ha',
                'FIELD_TYPE': 0,
                'FIELD_LENGTH': 12,
                'FIELD_PRECISION': 4,
                'FORMULA': 'round(area($geometry) / 10000.0, 4)',
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        step3 = processing.run(
            'native:fieldcalculator',
            {
                'INPUT': step2,
                'FIELD_NAME': 'Stammzahl',
                'FIELD_TYPE': 1,
                'FIELD_LENGTH': 10,
                'FORMULA': 'coalesce("VFM_count", 0)',
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        step4 = processing.run(
            'native:fieldcalculator',
            {
                'INPUT': step3,
                'FIELD_NAME': 'mittlere_Bestandeshoehe',
                'FIELD_TYPE': 0,
                'FIELD_LENGTH': 8,
                'FIELD_PRECISION': 1,
                'FORMULA': 'round(coalesce("Baumhoehe_mean", 0) * 2.0, 0) / 2.0',
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        step5 = processing.run(
            'native:fieldcalculator',
            {
                'INPUT': step4,
                'FIELD_NAME': 'VFM_gesamt',
                'FIELD_TYPE': 0,
                'FIELD_LENGTH': 12,
                'FIELD_PRECISION': 2,
                'FORMULA': 'round(coalesce("VFM_sum", 0), 2)',
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        step6 = processing.run(
            'native:fieldcalculator',
            {
                'INPUT': step5,
                'FIELD_NAME': 'VFM_pro_ha',
                'FIELD_TYPE': 0,
                'FIELD_LENGTH': 12,
                'FIELD_PRECISION': 1,
                'FORMULA': 'CASE WHEN area($geometry) > 0 THEN round(coalesce("VFM_sum", 0) / (area($geometry) / 10000.0), 1) ELSE 0 END',
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        # Exakt gewünschte Spaltenreihenfolge speichern (fid wird vom GeoPackage automatisch an Position 1 erzeugt)
        processing.run(
            'native:retainfields',
            {
                'INPUT': step6,
                'FIELDS': list((
                    'GST',
                    'Bestandesklasse',
                    'Flaeche_ha',
                    'Stammzahl',
                    'mittlere_Bestandeshoehe',
                    'VFM_gesamt',
                    'VFM_pro_ha'
                )),
                'OUTPUT': bestandes_path
            },
            context=context, feedback=feedback, is_child_algorithm=True
        )

        # Alle drei Ergebnis-Layer ins Projekt laden und einfärben
        bestandes_layer = QgsVectorLayer(bestandes_path, '03_Bestandesklassen', 'ogr')
        self.apply_wuchsklassen_style(bestandes_layer)

        voronoi_layer = QgsVectorLayer(voronoi_path, '02_Voronoi_Kronenflaechen', 'ogr')
        self.apply_height_style(voronoi_layer, is_point=False)

        tops_layer = QgsVectorLayer(treetops_path, '01_Tree_Tops_Punkte', 'ogr')
        self.apply_height_style(tops_layer, is_point=True)

        QgsProject.instance().addMapLayer(bestandes_layer)
        QgsProject.instance().addMapLayer(voronoi_layer)
        QgsProject.instance().addMapLayer(tops_layer)

        return {self.OUTPUT_FOLDER: out_folder}

    def apply_wuchsklassen_style(self, layer):
        stufen = (
            ('1: Blöße / Kahlfläche (unbestockt)', '#ffffff'),
            ('2: Jungwuchs / Kultur (bis 2 m)', '#ffe600'),
            ('3: Dickung (2 - 10 m)', '#e31a1c'),
            ('4: Stangenholz (10 - 20 m)', '#33a02c'),
            ('5: Baumholz (20 - 30 m)', '#1f78b4'),
            ('6: Starkes Baumholz / Altholz (> 30 m)', '#8c510a'),
            ('7: Plenterartig / Ungleichaltrig', '#756bb1')
        )
        categories = list()
        for label, color_hex in stufen:
            symbol = QgsSymbol.defaultSymbol(QgsWkbTypes.PolygonGeometry)
            symbol.setColor(QColor(color_hex))
            symbol.setOpacity(0.70)
            categories.append(QgsRendererCategory(label, symbol, label))

        renderer = QgsCategorizedSymbolRenderer('Bestandesklasse', categories)
        layer.setRenderer(renderer)


    def apply_height_style(self, layer, is_point):
        classes = (
            (0.0, 2.0, '0.0 - 2.0 m', '#ffffff'),
            (2.0, 5.0, '2 - 5 m', '#e5f5e0'),
            (5.0, 10.0, '5 - 10 m', '#c7e9c0'),
            (10.0, 15.0, '10 - 15 m', '#a1d99b'),
            (15.0, 20.0, '15 - 20 m', '#74c476'),
            (20.0, 25.0, '20 - 25 m', '#41ab5d'),
            (25.0, 30.0, '25 - 30 m', '#238b45'),
            (30.0, 35.0, '30 - 35 m', '#005a32'),
            (35.0, 40.0, '35 - 40 m', '#2171b5'),
            (40.0, 50.0, '40 - 50 m', '#08306b'),
            (50.0, 60.0, '50 - 60 m', '#54278f'),
            (60.0, 9999.0, '> 60 m', '#e31a1c')
        )

        # BHD-Skalierung: Punktgröße von 0.4 bis 4.0 je nach BHD (z. B. 5 cm -> 0.4 mm, >= 80 cm -> 4.0 mm)
        bhd_size_expr = 'scale_linear(clamp(5, "BHD", 80), 5, 80, 0.4, 4.0)'

        ranges = list()
        geom_type = QgsWkbTypes.PointGeometry if is_point else QgsWkbTypes.PolygonGeometry

        for low, high, label, color_hex in classes:
            symbol = QgsSymbol.defaultSymbol(geom_type)
            symbol.setColor(QColor(color_hex))
            if is_point:
                symbol.setDataDefinedSize(QgsProperty.fromExpression(bhd_size_expr))
            else:
                symbol.setOpacity(0.50)
            ranges.append(QgsRendererRange(low, high, symbol, label))

        renderer = QgsGraduatedSymbolRenderer('Baumhoehe', ranges)
        layer.setRenderer(renderer)
