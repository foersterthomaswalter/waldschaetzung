import os
import time
from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtGui import QColor, QIcon
from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterRasterLayer,
    QgsProcessingParameterNumber,
    QgsProcessingParameterFolderDestination,
    QgsProcessingUtils,
    QgsRasterLayer,
    QgsVectorLayer,
    QgsProject,
    QgsSymbol,
    QgsRendererCategory,
    QgsCategorizedSymbolRenderer,
    QgsWkbTypes
)
import processing


class ForstHangneigungAnalyse(QgsProcessingAlgorithm):
    INPUT_AOI = 'INPUT_AOI'
    INPUT_DGM = 'INPUT_DGM'
    PIXEL_SIZE = 'PIXEL_SIZE'
    MIN_PIXELS = 'MIN_PIXELS'
    WATERSHED_THRESHOLD = 'WATERSHED_THRESHOLD'
    GRENZE_1 = 'GRENZE_1'
    GRENZE_2 = 'GRENZE_2'
    GRENZE_3 = 'GRENZE_3'
    GRENZE_4 = 'GRENZE_4'
    OUTPUT_FOLDER = 'OUTPUT_FOLDER'

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return ForstHangneigungAnalyse()

    def name(self):
        return 'forsthangneigunganalyse'

    def displayName(self):
        return self.tr('Bringung: Hangneigung & Einzugsgebiete')

    def group(self):
        return ''

    def groupId(self):
        return ''

    def icon(self):
        icon_path = os.path.join(os.path.dirname(__file__), 'bringung.png')
        return QIcon(icon_path)

    def shortHelpString(self):
        return self.tr(
            'Schneidet das DGM auf die AOI zu, berechnet hydrologische Einzugsgebiete (Watersheds) '
            'und gliedert die 5 Hangneigungs-Betriebsklassen nach Geländekammern / Einzugsgebieten.'
        )

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.INPUT_AOI,
                self.tr('AOI / Grundstücke Layer'),
                list((QgsProcessing.TypeVectorPolygon,))
            )
        )

        self.addParameter(
            QgsProcessingParameterRasterLayer(
                self.INPUT_DGM,
                self.tr('Geländemodell (DGM)')
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                self.PIXEL_SIZE,
                self.tr('Ziel-Auflösung / Glättung des DGM in Metern'),
                type=QgsProcessingParameterNumber.Double,
                defaultValue=2.5,
                minValue=0.5
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                self.MIN_PIXELS,
                self.tr('Mindestgröße für Hangneigungs-Inseln in Pixeln'),
                type=QgsProcessingParameterNumber.Integer,
                defaultValue=25,
                minValue=1
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                self.WATERSHED_THRESHOLD,
                self.tr('Einzugsgebiet (Watershed): Mindestgröße in Pixeln (steuert Größe der Geländekammern)'),
                type=QgsProcessingParameterNumber.Integer,
                defaultValue=500,
                minValue=20
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                self.GRENZE_1,
                self.tr('Obergrenze Klasse 1: Schleppergelände (%)'),
                type=QgsProcessingParameterNumber.Double,
                defaultValue=30.0
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                self.GRENZE_2,
                self.tr('Obergrenze Klasse 2: Übergangsgelände (%)'),
                type=QgsProcessingParameterNumber.Double,
                defaultValue=50.0
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                self.GRENZE_3,
                self.tr('Obergrenze Klasse 3: Seilgelände (%)'),
                type=QgsProcessingParameterNumber.Double,
                defaultValue=100.0
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                self.GRENZE_4,
                self.tr('Obergrenze Klasse 4: Extremes Gelände (%)'),
                type=QgsProcessingParameterNumber.Double,
                defaultValue=150.0
            )
        )

        self.addParameter(
            QgsProcessingParameterFolderDestination(
                self.OUTPUT_FOLDER,
                self.tr('Zielordner für Ergebnisse')
            )
        )

    def get_safe_path(self, folder, filename):
        path = os.path.join(folder, filename)
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                base, ext = os.path.splitext(filename)
                stamp = time.strftime('%H%M%S')
                path = os.path.join(folder, f'{base}_{stamp}{ext}')
        return path

    def processAlgorithm(self, parameters, context, feedback):
        dgm_layer = self.parameterAsRasterLayer(parameters, self.INPUT_DGM, context)
        pixel_size = self.parameterAsDouble(parameters, self.PIXEL_SIZE, context)
        min_pixels = self.parameterAsInt(parameters, self.MIN_PIXELS, context)
        ws_threshold = self.parameterAsInt(parameters, self.WATERSHED_THRESHOLD, context)
        g1 = self.parameterAsDouble(parameters, self.GRENZE_1, context)
        g2 = self.parameterAsDouble(parameters, self.GRENZE_2, context)
        g3 = self.parameterAsDouble(parameters, self.GRENZE_3, context)
        g4 = self.parameterAsDouble(parameters, self.GRENZE_4, context)
        out_folder = self.parameterAsString(parameters, self.OUTPUT_FOLDER, context)
        os.makedirs(out_folder, exist_ok=True)

        dgm_clip_path = self.get_safe_path(out_folder, '01_DGM_AOI_geglaettet.tif')
        slope_raster_path = self.get_safe_path(out_folder, '02_Hangneigung_Prozent.tif')
        ezg_out_path = self.get_safe_path(out_folder, '03_Einzugsgebiete.gpkg')
        vector_out_path = self.get_safe_path(out_folder, '04_Betriebsklassen_nach_EZG.gpkg')

        target_crs = dgm_layer.crs()

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

        # Puffer um AOI (damit Wassereinzugsgebiete an den Rändern hydrologisch korrekt abfließen)
        aoi_buffered = processing.run(
            'native:buffer',
            {
                'INPUT': aoi_fixed,
                'DISTANCE': max(25.0, pixel_size * 10.0),
                'SEGMENTS': 5,
                'END_CAP_STYLE': 0,
                'JOIN_STYLE': 0,
                'MITER_LIMIT': 2.0,
                'DISSOLVE': True,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        # 0. Schneller DGM-Export nur im Bereich der AOI
        feedback.pushInfo('0. Lade DGM-Ausschnitt für AOI (Schnellmodus)...')
        dgm_subset = processing.run(
            'native:rastercalc',
            {
                'EXPRESSION': f'"{dgm_layer.name()}@1"',
                'LAYERS': list((dgm_layer,)),
                'EXTENT': aoi_buffered,
                'CELLSIZE': dgm_layer.rasterUnitsPerPixelX(),
                'CRS': target_crs,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        # 1. DGM auf gepufferte AOI zuschneiden & auf Zielauflösung glätten
        feedback.pushInfo(f'1. Schneide DGM zu und glätte auf {pixel_size} m Pixelgröße...')
        processing.run(
            'gdal:cliprasterbymasklayer',
            {
                'INPUT': dgm_subset,
                'MASK': aoi_buffered,
                'SOURCE_CRS': target_crs,
                'TARGET_CRS': target_crs,
                'CROP_TO_CUTLINE': True,
                'KEEP_RESOLUTION': False,
                'SET_RESOLUTION': True,
                'X_RESOLUTION': pixel_size,
                'Y_RESOLUTION': pixel_size,
                'RESAMPLING': 5, # Average
                'OUTPUT': dgm_clip_path
            },
            context=context, feedback=feedback, is_child_algorithm=True
        )

        # 2. Einzugsgebiete (Watersheds): >= 1000 m² + topologisch glatte Linien (0 Löcher, 0 Überlappungen!)
        feedback.pushInfo(f'2. Berechne und glätte hydrologische Einzugsgebiete (Schwellenwert: {ws_threshold} Pixel)...')
        ws_res = processing.run(
            'grass7:r.watershed',
            {
                'elevation': dgm_clip_path,
                'threshold': ws_threshold,
                'basin': 'TEMPORARY_OUTPUT',
                '-s': False,
                '-m': False,
                '-4': False,
                '-a': True,
                'GRASS_REGION_PARAMETER': None,
                'GRASS_REGION_CELLSIZE_PARAMETER': pixel_size,
                'GRASS_RASTER_FORMAT_OPT': '',
                'GRASS_RASTER_FORMAT_META': ''
            },
            context=context, feedback=feedback, is_child_algorithm=True
        )
        basin_raster = ws_res.get('basin')

        # Raster-Mehrheitsfilter (7x7) glättet grobe Ausbuchtungen vorab
        basin_mode = processing.run(
            'grass7:r.neighbors',
            {
                'input': basin_raster,
                'selection': None,
                'method': 2, # 2 = mode
                'size': 7,
                'gauss': None,
                'quantile': '',
                'weight': '',
                'output': 'TEMPORARY_OUTPUT',
                '-c': True,
                '-a': False,
                'GRASS_REGION_PARAMETER': None,
                'GRASS_REGION_CELLSIZE_PARAMETER': pixel_size,
                'GRASS_RASTER_FORMAT_OPT': '',
                'GRASS_RASTER_FORMAT_META': ''
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('output')

        basin_poly = processing.run(
            'gdal:polygonize',
            {
                'INPUT': basin_mode,
                'BAND': 1,
                'FIELD': 'ezg_raw',
                'EIGHT_CONNECTEDNESS': False,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        basin_dissolved = processing.run(
            'native:dissolve',
            {
                'INPUT': basin_poly,
                'FIELD': list(('ezg_raw',)),
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        basin_clipped = processing.run(
            'native:clip',
            {
                'INPUT': basin_dissolved,
                'OVERLAY': aoi_fixed,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        basin_single = processing.run(
            'native:multiparttosingleparts',
            {
                'INPUT': basin_clipped,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        # 2a. Alle Einzugsgebiete unter 1000 m² zuverlässig mit dem Nachbarn verschmelzen
        feedback.pushInfo('   -> Verschmelze Einzugsgebiete unter 1000 m²...')
        current_ezg = basin_single
        for _ in range(15):
            ezg_lyr = QgsProcessingUtils.mapLayerFromString(current_ezg, context)
            if not ezg_lyr or ezg_lyr.featureCount() <= 1:
                break

            small_ezg_ids = list(f.id() for f in ezg_lyr.getFeatures() if f.geometry().area() < 1000.0)
            if not small_ezg_ids:
                break

            ezg_lyr.selectByIds(small_ezg_ids)

            elim_ezg = processing.run(
                'qgis:eliminateselectedpolygons',
                {
                    'INPUT': ezg_lyr,
                    'MODE': 2, # Längste gemeinsame Grenze
                    'OUTPUT': 'TEMPORARY_OUTPUT'
                },
                context=context, feedback=feedback, is_child_algorithm=True
            ).get('OUTPUT')

            diss_ezg = processing.run(
                'native:dissolve',
                {
                    'INPUT': elim_ezg,
                    'FIELD': list(('ezg_raw',)),
                    'OUTPUT': 'TEMPORARY_OUTPUT'
                },
                context=context, feedback=feedback, is_child_algorithm=True
            ).get('OUTPUT')

            current_ezg = processing.run(
                'native:multiparttosingleparts',
                {
                    'INPUT': diss_ezg,
                    'OUTPUT': 'TEMPORARY_OUTPUT'
                },
                context=context, feedback=feedback, is_child_algorithm=True
            ).get('OUTPUT')

        # 2b. Topologische Kantenglättung (Linien extrahieren -> glätten -> neu polygonisieren = 0 Lücken, 0 Überlappungen!)
        feedback.pushInfo('   -> Glätte Einzugsgebiets-Grenzen topologisch (ohne Lücken/Überlappungen)...')
        # Leicht überstehenden Rand nutzen, damit die geglätteten Linien sauber am AOI-Rand abschließen
        ezg_lines = processing.run(
            'native:polygonstolines',
            {
                'INPUT': current_ezg,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        # Gemeinsame Kanten zwischen Nachbarn zu einer einzigen Linie verschmelzen
        ezg_lines_diss = processing.run(
            'native:dissolve',
            {
                'INPUT': ezg_lines,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        ezg_lines_simp = processing.run(
            'native:simplifygeometries',
            {
                'INPUT': ezg_lines_diss,
                'METHOD': 0, # Douglas-Peucker entfernt Zick-Zack-Stufen
                'TOLERANCE': pixel_size * 1.8,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        ezg_lines_smooth = processing.run(
            'native:smoothgeometry',
            {
                'INPUT': ezg_lines_simp,
                'ITERATIONS': 3,
                'OFFSET': 0.25,
                'MAX_ANGLE': 180.0,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        # Mit der exakten AOI-Außenkante kombinieren und wieder lückenlos in Polygone umwandeln
        aoi_border = processing.run(
            'native:polygonstolines',
            {
                'INPUT': aoi_fixed,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        all_borders = processing.run(
            'native:mergevectorlayers',
            {
                'LAYERS': list((ezg_lines_smooth, aoi_border)),
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        ezg_rebuilt = processing.run(
            'native:polygonize',
            {
                'INPUT': all_borders,
                'KEEP_FIELDS': False,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        # Exakt auf AOI zuschneiden und eventuelle Kleinst-Splitter am Rand (< 1000 m²) nochmals binden
        ezg_clipped_clean = processing.run(
            'native:clip',
            {
                'INPUT': ezg_rebuilt,
                'OVERLAY': aoi_fixed,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        ezg_single_final = processing.run(
            'native:multiparttosingleparts',
            {
                'INPUT': ezg_clipped_clean,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        for _ in range(10):
            ezg_lyr2 = QgsProcessingUtils.mapLayerFromString(ezg_single_final, context)
            if not ezg_lyr2 or ezg_lyr2.featureCount() <= 1:
                break
            small_ids2 = list(f.id() for f in ezg_lyr2.getFeatures() if f.geometry().area() < 1000.0)
            if not small_ids2:
                break
            ezg_lyr2.selectByIds(small_ids2)
            ezg_single_final = processing.run(
                'qgis:eliminateselectedpolygons',
                {
                    'INPUT': ezg_lyr2,
                    'MODE': 2,
                    'OUTPUT': 'TEMPORARY_OUTPUT'
                },
                context=context, feedback=feedback, is_child_algorithm=True
            ).get('OUTPUT')

        # Einzugsgebiete von Nord nach Süd sortieren und als EZG_01, EZG_02, ... benennen
        basin_sorted = processing.run(
            'native:orderbyexpression',
            {
                'INPUT': ezg_single_final,
                'EXPRESSION': 'y(centroid($geometry))',
                'ASCENDING': False,
                'NULLS_FIRST': False,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        basin_named = processing.run(
            'native:fieldcalculator',
            {
                'INPUT': basin_sorted,
                'FIELD_NAME': 'Einzugsgebiet',
                'FIELD_TYPE': 2,
                'FIELD_LENGTH': 25,
                'FORMULA': "'EZG_' || lpad(to_string($id), 2, '0')",
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        ezg_clean = processing.run(
            'native:retainfields',
            {
                'INPUT': basin_named,
                'FIELDS': list(('Einzugsgebiet',)),
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        # 3. Hangneigung in Prozent berechnen
        feedback.pushInfo('3. Berechne Hangneigung in Prozent...')
        processing.run(
            'gdal:slope',
            {
                'INPUT': dgm_clip_path,
                'BAND': 1,
                'SCALE': 1.0,
                'AS_PERCENT': True,
                'COMPUTE_EDGES': True,
                'OUTPUT': slope_raster_path
            },
            context=context, feedback=feedback, is_child_algorithm=True
        )

        # 4. In 5 Betriebsklassen einteilen & kleine Inseln entfernen
        feedback.pushInfo('4. Klassifiziere Hangneigung in 5 Betriebsklassen...')
        slope_reclass = processing.run(
            'native:reclassifybytable',
            {
                'INPUT_RASTER': slope_raster_path,
                'RASTER_BAND': 1,
                'TABLE': list((
                    -1, g1, 1,
                    g1, g2, 2,
                    g2, g3, 3,
                    g3, g4, 4,
                    g4, 99999, 5
                )),
                'NO_DATA': -9999,
                'RANGE_BOUNDARIES': 0,
                'NODATA_FOR_MISSING': True,
                'DATA_TYPE': 1,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        slope_sieved = processing.run(
            'gdal:sieve',
            {
                'INPUT': slope_reclass,
                'THRESHOLD': min_pixels,
                'EIGHT_CONNECTEDNESS': True,
                'NO_MASK': False,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        slope_poly = processing.run(
            'gdal:polygonize',
            {
                'INPUT': slope_sieved,
                'BAND': 1,
                'FIELD': 'klasse',
                'EIGHT_CONNECTEDNESS': False,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        slope_dissolved = processing.run(
            'native:dissolve',
            {
                'INPUT': slope_poly,
                'FIELD': list(('klasse',)),
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        slope_smoothed = processing.run(
            'native:smoothgeometry',
            {
                'INPUT': slope_dissolved,
                'ITERATIONS': 2,
                'OFFSET': 0.25,
                'MAX_ANGLE': 180.0,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        slope_fixed = processing.run(
            'native:fixgeometries',
            {
                'INPUT': slope_smoothed,
                'METHOD': 1,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        # 5. Betriebsklassen direkt mit den geglätteten Einzugsgebieten verschneiden
        feedback.pushInfo('5. Teile Betriebsklassen nach Einzugsgebieten auf...')
        slope_by_ezg = processing.run(
            'native:intersection',
            {
                'INPUT': slope_fixed,
                'OVERLAY': ezg_clean,
                'INPUT_FIELDS': list(('klasse',)),
                'OVERLAY_FIELDS': list(('Einzugsgebiet',)),
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        slope_grouped = processing.run(
            'native:dissolve',
            {
                'INPUT': slope_by_ezg,
                'FIELD': list(('Einzugsgebiet', 'klasse')),
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        slope_sorted = processing.run(
            'native:orderbyexpression',
            {
                'INPUT': slope_grouped,
                'EXPRESSION': '"Einzugsgebiet" || \'_\' || to_string("klasse")',
                'ASCENDING': True,
                'NULLS_FIRST': False,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        # 6. Beschreibungen der 5 Betriebsklassen und Flächenfelder berechnen
        feedback.pushInfo('6. Berechne Flächen (m² & ha) je Einzugsgebiet und Betriebsklasse...')
        label_1 = f'Klasse 1: Schleppergelände (0-{int(g1)}%)'
        label_2 = f'Klasse 2: Übergangsgelände ({int(g1)}-{int(g2)}%)'
        label_3 = f'Klasse 3: Seilgelände ({int(g2)}-{int(g3)}%)'
        label_4 = f'Klasse 4: Extremes Gelände ({int(g3)}-{int(g4)}%)'
        label_5 = f'Klasse 5: Felsband (>{int(g4)}%)'

        formula = (
            f"CASE "
            f"WHEN \"klasse\" = 1 THEN '{label_1}' "
            f"WHEN \"klasse\" = 2 THEN '{label_2}' "
            f"WHEN \"klasse\" = 3 THEN '{label_3}' "
            f"WHEN \"klasse\" = 4 THEN '{label_4}' "
            f"ELSE '{label_5}' "
            f"END"
        )

        step_label = processing.run(
            'native:fieldcalculator',
            {
                'INPUT': slope_sorted,
                'FIELD_NAME': 'betriebsklasse',
                'FIELD_TYPE': 2,
                'FIELD_LENGTH': 80,
                'FORMULA': formula,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        step_m2 = processing.run(
            'native:fieldcalculator',
            {
                'INPUT': step_label,
                'FIELD_NAME': 'flaeche_m2',
                'FIELD_TYPE': 0,
                'FIELD_LENGTH': 12,
                'FIELD_PRECISION': 2,
                'FORMULA': 'round(area($geometry), 2)',
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        step_ha = processing.run(
            'native:fieldcalculator',
            {
                'INPUT': step_m2,
                'FIELD_NAME': 'flaeche_ha',
                'FIELD_TYPE': 0,
                'FIELD_LENGTH': 12,
                'FIELD_PRECISION': 4,
                'FORMULA': 'round(area($geometry) / 10000.0, 4)',
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        processing.run(
            'native:retainfields',
            {
                'INPUT': step_ha,
                'FIELDS': list(('Einzugsgebiet', 'klasse', 'betriebsklasse', 'flaeche_m2', 'flaeche_ha')),
                'OUTPUT': vector_out_path
            },
            context=context, feedback=feedback, is_child_algorithm=True
        )

        # Nur DGM, Hangneigung und den kombinierten Betriebsklassen-Layer ins Projekt laden
        vec_layer = QgsVectorLayer(vector_out_path, '03_Betriebsklassen_nach_EZG', 'ogr')
        categories = list((
            self.create_category(1, label_1, '#2b83ba'),
            self.create_category(2, label_2, '#abdda4'),
            self.create_category(3, label_3, '#fdae61'),
            self.create_category(4, label_4, '#d7191c'),
            self.create_category(5, label_5, '#542788')
        ))
        renderer = QgsCategorizedSymbolRenderer('klasse', categories)
        vec_layer.setRenderer(renderer)

        QgsProject.instance().addMapLayer(QgsRasterLayer(dgm_clip_path, '01_DGM_geglaettet'))
        QgsProject.instance().addMapLayer(QgsRasterLayer(slope_raster_path, '02_Hangneigung_Prozent'))
        QgsProject.instance().addMapLayer(vec_layer)

        return {self.OUTPUT_FOLDER: out_folder}

    def create_category(self, val, label, color_hex):
        symbol = QgsSymbol.defaultSymbol(QgsWkbTypes.PolygonGeometry)
        symbol.setColor(QColor(color_hex))
        symbol.setOpacity(0.65)
        return QgsRendererCategory(val, symbol, label)
