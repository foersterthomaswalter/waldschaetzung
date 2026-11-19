import os
import time
from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtGui import QColor, QIcon
from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterNumber,
    QgsProcessingParameterFolderDestination,
    QgsProcessingUtils,
    QgsFeatureRequest,
    QgsVectorLayer,
    QgsProject,
    QgsSymbol,
    QgsSimpleFillSymbolLayer,
    QgsSingleSymbolRenderer,
    QgsPalLayerSettings,
    QgsTextFormat,
    QgsTextBufferSettings,
    QgsVectorLayerSimpleLabeling,
    QgsWkbTypes
)
import processing


class ForstUnterabteilungAnalyse(QgsProcessingAlgorithm):
    INPUT_BESTAND = 'INPUT_BESTAND'
    INPUT_BRINGUNG = 'INPUT_BRINGUNG'
    INPUT_TREETOPS = 'INPUT_TREETOPS'
    MIN_UA_M2 = 'MIN_UA_M2'
    DETAIL_TOL = 'DETAIL_TOL'
    OUTPUT_FOLDER = 'OUTPUT_FOLDER'

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return ForstUnterabteilungAnalyse()

    def name(self):
        return 'forstunterabteilunganalyse'

    def displayName(self):
        return self.tr('Unterabteilung: Forstliche Bestandes- & Bringungsgliederung')

    def group(self):
        return ''

    def groupId(self):
        return ''

    def icon(self):
        icon_path = os.path.join(os.path.dirname(__file__), 'unterabteilung.png')
        return QIcon(icon_path)

    def shortHelpString(self):
        return self.tr(
            'Repariert zunächst Silberlinge und Löcher in den Eingabelayern und bildet daraus '
            'lückenlose, überlappungsfreie forstliche Unterabteilungen mit klaren Grenzlinien.'
        )

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.INPUT_BESTAND,
                self.tr('Layer Bestandesklassen (03_Bestandesklassen)'),
                list((QgsProcessing.TypeVectorPolygon,))
            )
        )

        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.INPUT_BRINGUNG,
                self.tr('Layer Betriebsklassen nach EZG (03_Betriebsklassen_nach_EZG)'),
                list((QgsProcessing.TypeVectorPolygon,))
            )
        )

        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.INPUT_TREETOPS,
                self.tr('Optional: Einzelbaum-Layer für VFM & Bestandeshöhe (01_Tree_Tops_Punkte)'),
                list((QgsProcessing.TypeVectorPoint,)),
                optional=True
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                self.MIN_UA_M2,
                self.tr('Mindestgröße einer Unterabteilung in m² (alle kleineren Schnipsel werden verschmolzen)'),
                type=QgsProcessingParameterNumber.Double,
                defaultValue=2500.0,
                minValue=200.0
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                self.DETAIL_TOL,
                self.tr('Detailgrad der Grenzlinien in Metern (z.B. 2.5 m = detailreich, 6.0 m = sehr ruhig)'),
                type=QgsProcessingParameterNumber.Double,
                defaultValue=3.5,
                minValue=0.5
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

    def add_spatial_index(self, layer_path, context, feedback):
        processing.run(
            'native:createspatialindex',
            {'INPUT': layer_path},
            context=context, feedback=feedback, is_child_algorithm=True
        )
        return layer_path

    def clean_input_layer(self, input_layer, target_crs, context, feedback):
        """Repariert ungültige Geometrien, schließt Innenlöcher und entfernt Silberlinge vor der Berechnung."""
        saved = processing.run(
            'native:savefeatures',
            {
                'INPUT': input_layer,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        reproj = processing.run(
            'native:reprojectlayer',
            {
                'INPUT': saved,
                'TARGET_CRS': target_crs,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        fixed = processing.run(
            'native:fixgeometries',
            {
                'INPUT': reproj,
                'METHOD': 1,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        # Mikrolöcher (< 500 m²) innerhalb der Eingabepolygone schließen
        no_holes = processing.run(
            'native:deleteholes',
            {
                'INPUT': fixed,
                'MIN_AREA': 500.0,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        # Null-Flächen entfernen und Einzelteile bilden
        valid_only = processing.run(
            'native:extractbyexpression',
            {
                'INPUT': no_holes,
                'EXPRESSION': 'area($geometry) > 0.05',
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        single = processing.run(
            'native:multiparttosingleparts',
            {
                'INPUT': valid_only,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        # Mikrosilberlinge (< 100 m² oder extrem schmale Spalten) sofort mit Nachbarn verschmelzen
        for _ in range(30):
            lyr = QgsProcessingUtils.mapLayerFromString(single, context)
            if not lyr or lyr.featureCount() <= 1:
                break
            sliver_ids = list(
                f.id() for f in lyr.getFeatures()
                if f.geometry().area() < 100.0 or (f.geometry().length() > 0 and (f.geometry().area() / f.geometry().length()) < 1.5)
            )
            if not sliver_ids:
                break
            lyr.selectByIds(sliver_ids)
            elim = processing.run(
                'qgis:eliminateselectedpolygons',
                {
                    'INPUT': lyr,
                    'MODE': 2,
                    'OUTPUT': 'TEMPORARY_OUTPUT'
                },
                context=context, feedback=feedback, is_child_algorithm=True
            ).get('OUTPUT')

            single = processing.run(
                'native:fixgeometries',
                {
                    'INPUT': elim,
                    'METHOD': 1,
                    'OUTPUT': 'TEMPORARY_OUTPUT'
                },
                context=context, feedback=feedback, is_child_algorithm=True
            ).get('OUTPUT')

            single = processing.run(
                'native:multiparttosingleparts',
                {
                    'INPUT': single,
                    'OUTPUT': 'TEMPORARY_OUTPUT'
                },
                context=context, feedback=feedback, is_child_algorithm=True
            ).get('OUTPUT')

        self.add_spatial_index(single, context, feedback)
        return single

    def processAlgorithm(self, parameters, context, feedback):
        context.setInvalidGeometryCheck(QgsFeatureRequest.GeometrySkipInvalid)

        min_ua_m2 = self.parameterAsDouble(parameters, self.MIN_UA_M2, context)
        detail_tol = self.parameterAsDouble(parameters, self.DETAIL_TOL, context)
        out_folder = self.parameterAsString(parameters, self.OUTPUT_FOLDER, context)
        os.makedirs(out_folder, exist_ok=True)

        ua_out_path = self.get_safe_gpkg_path(out_folder, '05_Unterabteilungen')

        # 1. Beide Eingangs-Layer gründlich von Silberlingen und Löchern befreien
        feedback.pushInfo('1. Repariere Silberlinge und Löcher in den Eingangs-Layern...')
        bestand_src = self.parameterAsSource(parameters, self.INPUT_BESTAND, context)
        target_crs = bestand_src.sourceCrs()

        bestand_fixed = self.clean_input_layer(parameters.get(self.INPUT_BESTAND), target_crs, context, feedback)
        bringung_fixed = self.clean_input_layer(parameters.get(self.INPUT_BRINGUNG), target_crs, context, feedback)

        # Saubere Außenhülle der Untersuchungsfläche (inkl. Loch-Bereinigung) bilden
        total_hull = processing.run(
            'native:dissolve',
            {
                'INPUT': bestand_fixed,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        total_hull = processing.run(
            'native:fixgeometries',
            {
                'INPUT': total_hull,
                'METHOD': 1,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        total_hull = processing.run(
            'native:deleteholes',
            {
                'INPUT': total_hull,
                'MIN_AREA': min_ua_m2,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')
        self.add_spatial_index(total_hull, context, feedback)

        # 2. Bestandes- und Bringungsgrenzen verschneiden
        feedback.pushInfo('2. Verschneide Bestandesklassen und Betriebsklassen...')
        intersected = processing.run(
            'native:intersection',
            {
                'INPUT': bestand_fixed,
                'OVERLAY': bringung_fixed,
                'INPUT_FIELDS': list(('GST', 'Bestandesklasse')),
                'OVERLAY_FIELDS': list(('Einzugsgebiet', 'betriebsklasse')),
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        intersected = processing.run(
            'native:fixgeometries',
            {
                'INPUT': intersected,
                'METHOD': 1,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')
        self.add_spatial_index(intersected, context, feedback)

        # Eventuelle Randdifferenzen zwischen Bestand und Bringung auffüllen
        missing_rim = processing.run(
            'native:difference',
            {
                'INPUT': total_hull,
                'OVERLAY': intersected,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        rim_lyr = QgsProcessingUtils.mapLayerFromString(missing_rim, context)
        if rim_lyr and rim_lyr.featureCount() > 0:
            merged_base = processing.run(
                'native:mergevectorlayers',
                {
                    'LAYERS': list((intersected, missing_rim)),
                    'OUTPUT': 'TEMPORARY_OUTPUT'
                },
                context=context, feedback=feedback, is_child_algorithm=True
            ).get('OUTPUT')
        else:
            merged_base = intersected

        diss_base = processing.run(
            'native:dissolve',
            {
                'INPUT': merged_base,
                'FIELD': list(('GST', 'Einzugsgebiet', 'Bestandesklasse', 'betriebsklasse')),
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        diss_base = processing.run(
            'native:fixgeometries',
            {
                'INPUT': diss_base,
                'METHOD': 1,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        current_ua = processing.run(
            'native:multiparttosingleparts',
            {
                'INPUT': diss_base,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        # 3. Vollständige Schnipsel-Bereinigung (< min_ua_m2)
        feedback.pushInfo(f'3. Bereinige alle Kleinstflächen und Randschnipsel (< {min_ua_m2} m²)...')
        current_ua = processing.run(
            'native:deleteholes',
            {
                'INPUT': current_ua,
                'MIN_AREA': min_ua_m2,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        for _ in range(100):
            ua_lyr = QgsProcessingUtils.mapLayerFromString(current_ua, context)
            if not ua_lyr or ua_lyr.featureCount() <= 1:
                break

            small_ids = list(
                f.id() for f in ua_lyr.getFeatures()
                if f.geometry().area() < min_ua_m2 or (f.geometry().length() > 0 and (f.geometry().area() / f.geometry().length()) < 4.5)
            )
            if not small_ids:
                break

            ua_lyr.selectByIds(small_ids)
            elim_1 = processing.run(
                'qgis:eliminateselectedpolygons',
                {
                    'INPUT': ua_lyr,
                    'MODE': 2,
                    'OUTPUT': 'TEMPORARY_OUTPUT'
                },
                context=context, feedback=feedback, is_child_algorithm=True
            ).get('OUTPUT')

            current_ua = processing.run(
                'native:fixgeometries',
                {
                    'INPUT': elim_1,
                    'METHOD': 1,
                    'OUTPUT': 'TEMPORARY_OUTPUT'
                },
                context=context, feedback=feedback, is_child_algorithm=True
            ).get('OUTPUT')

            current_ua = processing.run(
                'native:deleteholes',
                {
                    'INPUT': current_ua,
                    'MIN_AREA': min_ua_m2,
                    'OUTPUT': 'TEMPORARY_OUTPUT'
                },
                context=context, feedback=feedback, is_child_algorithm=True
            ).get('OUTPUT')

            current_ua = processing.run(
                'native:multiparttosingleparts',
                {
                    'INPUT': current_ua,
                    'OUTPUT': 'TEMPORARY_OUTPUT'
                },
                context=context, feedback=feedback, is_child_algorithm=True
            ).get('OUTPUT')

        # 4. Kontrollierte Linien-Begradigung mit sicherem Rückfall (Fallback auf current_ua, falls Liniennetz offen)
        feedback.pushInfo(f'4. Optimiere Grenzlinien (Detailgrad: {detail_tol} m)...')
        ua_lines = processing.run(
            'native:polygonstolines',
            {
                'INPUT': current_ua,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        ua_lines_diss = processing.run(
            'native:dissolve',
            {
                'INPUT': ua_lines,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        ua_lines_simp = processing.run(
            'native:simplifygeometries',
            {
                'INPUT': ua_lines_diss,
                'METHOD': 0,
                'TOLERANCE': detail_tol,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        hull_lines = processing.run(
            'native:polygonstolines',
            {
                'INPUT': total_hull,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        ua_lines_snapped = processing.run(
            'native:snapgeometries',
            {
                'INPUT': ua_lines_simp,
                'REFERENCE_LAYER': hull_lines,
                'TOLERANCE': 0.5,
                'BEHAVIOR': 0,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        all_lines = processing.run(
            'native:mergevectorlayers',
            {
                'LAYERS': list((ua_lines_snapped, hull_lines)),
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        all_lines_fixed = processing.run(
            'native:fixgeometries',
            {
                'INPUT': all_lines,
                'METHOD': 1,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        rebuilt = processing.run(
            'native:polygonize',
            {
                'INPUT': all_lines_fixed,
                'KEEP_FIELDS': False,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        clean_ua = current_ua
        rebuilt_lyr = QgsProcessingUtils.mapLayerFromString(rebuilt, context)
        if rebuilt_lyr and rebuilt_lyr.featureCount() > 0:
            rebuilt_fixed = processing.run(
                'native:fixgeometries',
                {
                    'INPUT': rebuilt,
                    'METHOD': 1,
                    'OUTPUT': 'TEMPORARY_OUTPUT'
                },
                context=context, feedback=feedback, is_child_algorithm=True
            ).get('OUTPUT')
            self.add_spatial_index(rebuilt_fixed, context, feedback)

            rebuilt_clip = processing.run(
                'native:clip',
                {
                    'INPUT': rebuilt_fixed,
                    'OVERLAY': total_hull,
                    'OUTPUT': 'TEMPORARY_OUTPUT'
                },
                context=context, feedback=feedback, is_child_algorithm=True
            ).get('OUTPUT')

            rebuilt_poly_only = processing.run(
                'native:extractbyexpression',
                {
                    'INPUT': rebuilt_clip,
                    'EXPRESSION': 'area($geometry) > 0.05',
                    'OUTPUT': 'TEMPORARY_OUTPUT'
                },
                context=context, feedback=feedback, is_child_algorithm=True
            ).get('OUTPUT')

            rebuilt_single = processing.run(
                'native:multiparttosingleparts',
                {
                    'INPUT': rebuilt_poly_only,
                    'OUTPUT': 'TEMPORARY_OUTPUT'
                },
                context=context, feedback=feedback, is_child_algorithm=True
            ).get('OUTPUT')

            for _ in range(100):
                r_lyr = QgsProcessingUtils.mapLayerFromString(rebuilt_single, context)
                if not r_lyr or r_lyr.featureCount() <= 1:
                    break
                s_ids = list(
                    f.id() for f in r_lyr.getFeatures()
                    if f.geometry().area() < min_ua_m2 or (f.geometry().length() > 0 and (f.geometry().area() / f.geometry().length()) < 4.5)
                )
                if not s_ids:
                    break
                r_lyr.selectByIds(s_ids)
                elim_step = processing.run(
                    'qgis:eliminateselectedpolygons',
                    {
                        'INPUT': r_lyr,
                        'MODE': 2,
                        'OUTPUT': 'TEMPORARY_OUTPUT'
                    },
                    context=context, feedback=feedback, is_child_algorithm=True
                ).get('OUTPUT')

                fixed_step = processing.run(
                    'native:fixgeometries',
                    {
                        'INPUT': elim_step,
                        'METHOD': 1,
                        'OUTPUT': 'TEMPORARY_OUTPUT'
                    },
                    context=context, feedback=feedback, is_child_algorithm=True
                ).get('OUTPUT')

                rebuilt_single = processing.run(
                    'native:multiparttosingleparts',
                    {
                        'INPUT': fixed_step,
                        'OUTPUT': 'TEMPORARY_OUTPUT'
                    },
                    context=context, feedback=feedback, is_child_algorithm=True
                ).get('OUTPUT')

            chk_lyr = QgsProcessingUtils.mapLayerFromString(rebuilt_single, context)
            if chk_lyr and chk_lyr.featureCount() > 0:
                clean_ua = rebuilt_single

        clean_ua = processing.run(
            'native:deleteholes',
            {
                'INPUT': clean_ua,
                'MIN_AREA': min_ua_m2,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        clean_ua = processing.run(
            'native:fixgeometries',
            {
                'INPUT': clean_ua,
                'METHOD': 1,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')
        self.add_spatial_index(clean_ua, context, feedback)

        # 5. Dominante Attribute per größter Überlappung zuweisen
        feedback.pushInfo('5. Übertrage Haupt-Bestandesklasse, Bringungsklasse, GST & EZG...')
        ua_with_attrs = processing.run(
            'native:joinattributesbylocation',
            {
                'INPUT': clean_ua,
                'PREDICATE': list((0,)),
                'JOIN': intersected,
                'JOIN_FIELDS': list(('GST', 'Einzugsgebiet', 'Bestandesklasse', 'betriebsklasse')),
                'METHOD': 2,
                'DISCARD_NONMATCHING': False,
                'PREFIX': '',
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        # 6. Von Nord nach Süd sortieren und reine Nummer vergeben (1, 2, 3, ...)
        feedback.pushInfo('6. Nummeriere Unterabteilungen (1, 2, 3, ...)...')
        ua_sorted = processing.run(
            'native:orderbyexpression',
            {
                'INPUT': ua_with_attrs,
                'EXPRESSION': 'y(centroid($geometry))',
                'ASCENDING': False,
                'NULLS_FIRST': False,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        ua_numbered = processing.run(
            'native:fieldcalculator',
            {
                'INPUT': ua_sorted,
                'FIELD_NAME': 'Unterabteilung',
                'FIELD_TYPE': 1,
                'FIELD_LENGTH': 10,
                'FORMULA': '$id',
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')
        self.add_spatial_index(ua_numbered, context, feedback)

        # 7. Optional: Einzelbaumdaten (VFM & Höhe) aus 01_Tree_Tops_Punkte berechnen
        treetops_param = parameters.get(self.INPUT_TREETOPS)
        if treetops_param:
            feedback.pushInfo('7. Übertrage Stammzahl, Mittelhöhe und VFM aus Tree Tops...')
            tops_saved = processing.run(
                'native:savefeatures',
                {
                    'INPUT': treetops_param,
                    'OUTPUT': 'TEMPORARY_OUTPUT'
                },
                context=context, feedback=feedback, is_child_algorithm=True
            ).get('OUTPUT')

            tops_reproj = processing.run(
                'native:reprojectlayer',
                {
                    'INPUT': tops_saved,
                    'TARGET_CRS': target_crs,
                    'OUTPUT': 'TEMPORARY_OUTPUT'
                },
                context=context, feedback=feedback, is_child_algorithm=True
            ).get('OUTPUT')
            self.add_spatial_index(tops_reproj, context, feedback)

            ua_with_stats = processing.run(
                'native:joinbylocationsummary',
                {
                    'INPUT': ua_numbered,
                    'PREDICATE': list((0,)),
                    'JOIN': tops_reproj,
                    'JOIN_FIELDS': list(('VFM', 'Baumhoehe')),
                    'SUMMARIES': list((0, 5, 6)),
                    'DISCARD_NONMATCHING': False,
                    'OUTPUT': 'TEMPORARY_OUTPUT'
                },
                context=context, feedback=feedback, is_child_algorithm=True
            ).get('OUTPUT')
        else:
            ua_with_stats = ua_numbered

        # 8. Attributtabelle aufbauen
        step_ha = processing.run(
            'native:fieldcalculator',
            {
                'INPUT': ua_with_stats,
                'FIELD_NAME': 'Flaeche_ha',
                'FIELD_TYPE': 0,
                'FIELD_LENGTH': 12,
                'FIELD_PRECISION': 4,
                'FORMULA': 'round(area($geometry) / 10000.0, 4)',
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        if treetops_param:
            s_stamm = processing.run(
                'native:fieldcalculator',
                {
                    'INPUT': step_ha,
                    'FIELD_NAME': 'Stammzahl',
                    'FIELD_TYPE': 1,
                    'FIELD_LENGTH': 10,
                    'FORMULA': 'coalesce("VFM_count", 0)',
                    'OUTPUT': 'TEMPORARY_OUTPUT'
                },
                context=context, feedback=feedback, is_child_algorithm=True
            ).get('OUTPUT')

            s_hoehe = processing.run(
                'native:fieldcalculator',
                {
                    'INPUT': s_stamm,
                    'FIELD_NAME': 'mittlere_Bestandeshoehe',
                    'FIELD_TYPE': 0,
                    'FIELD_LENGTH': 8,
                    'FIELD_PRECISION': 1,
                    'FORMULA': 'round(coalesce("Baumhoehe_mean", 0) * 2.0, 0) / 2.0',
                    'OUTPUT': 'TEMPORARY_OUTPUT'
                },
                context=context, feedback=feedback, is_child_algorithm=True
            ).get('OUTPUT')

            s_vfm = processing.run(
                'native:fieldcalculator',
                {
                    'INPUT': s_hoehe,
                    'FIELD_NAME': 'VFM_gesamt',
                    'FIELD_TYPE': 0,
                    'FIELD_LENGTH': 12,
                    'FIELD_PRECISION': 2,
                    'FORMULA': 'round(coalesce("VFM_sum", 0), 2)',
                    'OUTPUT': 'TEMPORARY_OUTPUT'
                },
                context=context, feedback=feedback, is_child_algorithm=True
            ).get('OUTPUT')

            s_vfm_ha = processing.run(
                'native:fieldcalculator',
                {
                    'INPUT': s_vfm,
                    'FIELD_NAME': 'VFM_pro_ha',
                    'FIELD_TYPE': 0,
                    'FIELD_LENGTH': 12,
                    'FIELD_PRECISION': 1,
                    'FORMULA': 'CASE WHEN area($geometry) > 0 THEN round(coalesce("VFM_sum", 0) / (area($geometry) / 10000.0), 1) ELSE 0 END',
                    'OUTPUT': 'TEMPORARY_OUTPUT'
                },
                context=context, feedback=feedback, is_child_algorithm=True
            ).get('OUTPUT')

            final_fields = list((
                'Unterabteilung',
                'GST',
                'Einzugsgebiet',
                'Bestandesklasse',
                'betriebsklasse',
                'Flaeche_ha',
                'Stammzahl',
                'mittlere_Bestandeshoehe',
                'VFM_gesamt',
                'VFM_pro_ha'
            ))
            last_step = s_vfm_ha
        else:
            final_fields = list((
                'Unterabteilung',
                'GST',
                'Einzugsgebiet',
                'Bestandesklasse',
                'betriebsklasse',
                'Flaeche_ha'
            ))
            last_step = step_ha

        final_fixed = processing.run(
            'native:fixgeometries',
            {
                'INPUT': last_step,
                'METHOD': 1,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            },
            context=context, feedback=feedback, is_child_algorithm=True
        ).get('OUTPUT')

        processing.run(
            'native:retainfields',
            {
                'INPUT': final_fixed,
                'FIELDS': final_fields,
                'OUTPUT': ua_out_path
            },
            context=context, feedback=feedback, is_child_algorithm=True
        )

        self.add_spatial_index(ua_out_path, context, feedback)

        # 9. Ergebnis-Layer laden, als klassische Forstkarten-Grenzlinie stylen & mit Nummer beschriften
        ua_layer = QgsVectorLayer(ua_out_path, '05_Unterabteilungen', 'ogr')
        self.apply_forstkarte_style(ua_layer)
        QgsProject.instance().addMapLayer(ua_layer)

        return {self.OUTPUT_FOLDER: out_folder}

    def apply_forstkarte_style(self, layer):
        fill_layer = QgsSimpleFillSymbolLayer()
        fill_layer.setFillColor(QColor(255, 255, 255, 0))
        fill_layer.setStrokeColor(QColor('#c00000'))
        fill_layer.setStrokeWidth(0.75)

        symbol = QgsSymbol.defaultSymbol(QgsWkbTypes.PolygonGeometry)
        symbol.changeSymbolLayer(0, fill_layer)
        layer.setRenderer(QgsSingleSymbolRenderer(symbol))

        label_settings = QgsPalLayerSettings()
        label_settings.isExpression = False
        label_settings.fieldName = 'Unterabteilung'

        text_format = QgsTextFormat()
        text_format.setSize(10)
        text_format.setColor(QColor('#111111'))

        buffer_settings = QgsTextBufferSettings()
        buffer_settings.setEnabled(True)
        buffer_settings.setSize(1.2)
        buffer_settings.setColor(QColor('#ffffff'))
        text_format.setBuffer(buffer_settings)

        label_settings.setFormat(text_format)
        layer.setLabeling(QgsVectorLayerSimpleLabeling(label_settings))
        layer.setLabelsEnabled(True)
