from qgis.core import QgsApplication
from .provider import ForstAnalyseProvider


class ForstAnalysePlugin:
    def __init__(self, iface):
        self.iface = iface
        self.provider = None

    def initProcessing(self):
        self.provider = ForstAnalyseProvider()
        QgsApplication.processingRegistry().addProvider(self.provider)

    def initGui(self):
        self.initProcessing()

    def unload(self):
        if self.provider:
            QgsApplication.processingRegistry().removeProvider(self.provider)


def classFactory(iface):
    return ForstAnalysePlugin(iface)
