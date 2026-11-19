import os
from qgis.PyQt.QtGui import QIcon
from qgis.core import QgsProcessingProvider
from .algorithm_bestand import ForstTreeTopsVoronoi
from .algorithm_bringung import ForstHangneigungAnalyse
from .algorithm_unterabteilung import ForstUnterabteilungAnalyse


class ForstAnalyseProvider(QgsProcessingProvider):
    def id(self):
        return 'waldschaetzung'

    def name(self):
        return 'Waldschätzung'

    def longName(self):
        return 'Waldschätzung (Bestand, Bringung & Unterabteilung)'

    def icon(self):
        icon_path = os.path.join(os.path.dirname(__file__), 'icon.png')
        return QIcon(icon_path)

    def loadAlgorithms(self):
        self.addAlgorithm(ForstTreeTopsVoronoi())
        self.addAlgorithm(ForstHangneigungAnalyse())
        self.addAlgorithm(ForstUnterabteilungAnalyse())
