import numpy as np
import cv2
from shapely.geometry import LineString, Point,Polygon
from pathlib import Path
import os
import matplotlib.pyplot as plt
from scipy.interpolate import CubicSpline
import time

from lib.devernayEdgeDetector import devernayEdgeDetector
from lib.io import Nr
from lib.celdas import Celda,distancia_entre_pixeles,OperacionesCelda,AMARILLO,VERDE,ROJO,NEGRO,NARANJA
from lib.dibujar import Dibujar
from lib.utils import write_log
from lib.objetos import Distribucion,Interseccion,Rayo,Curva,Segmento
import lib.chain_v4 as ch

MODULE = "spyder"
def from_polar_to_cartesian(r,angulo,centro):
    y = centro[0] + r * np.cos(angulo * np.pi / 180)
    x = centro[1] + r * np.sin(angulo * np.pi / 180)
    return (y,x)



class SpyderWeb:
    #TODO: pensar los objetos abstrayendome de la representacion.
    #Los objetos (pixeles) tienen que ser flotantes. Definir de una biblioteca que se encarga de dibujar la representacion
    #Rayos: tienen que ser objetos independientementes de la representacion. El radio tiene que tener como objeto unicamente
    # las coordenadas del centro y un angulo
    #Curva: sucesion de puntos
    #Anillo: curva cerrada, los puntos pertenecen a radios distintos.
    #Interseccion: interseccion entre rayo y curva
    #Celda: espacio entre dos curvas consecutivas (en direccion radial) y rayos consecutivos. Los rayos dependiendo de la distancia
    # al centro podran ser consecutivos o no. Una celda esta formada por 4 objetos Interseccion.
    def __init__(self,Nr,img,lista_curvas,centro,save_path,debug=False):
        self.Nr = Nr
        self.contador = 0
        self.path = save_path
        if debug:
            self.debug_path = Path(save_path) / "debug"
            os.system(f"rm -rf {str(self.debug_path)}")
            self.debug_path.mkdir(parents=True, exist_ok=True)
        self.debug = debug
        self.centro = centro
        self.img = img
        M,N,_ = img.shape
        self.lista_curvas = self.convertir_formate_lista_curvas(lista_curvas)
        self.lista_rayos = self.construir_rayos(Nr,M,N,centro)
        self.lista_intersecciones = self.construir_intersecciones(self.lista_rayos,self.lista_curvas)



    def dibujar_curvas_rayos_e_intersecciones(self,img):
        img_dibujo = img.copy()
        for rayo in self.lista_rayos:
            img_dibujo = Dibujar.rayo(rayo,img_dibujo)

        for curva in self.lista_curvas:
            img_dibujo = Dibujar.curva(curva,img_dibujo)

        img_dibujo = Dibujar.intersecciones(self.lista_intersecciones,img_dibujo)

        cv2.imwrite(f'{self.path}/curvas_rayos_e_intersecciones.png',img_dibujo)

    def convertir_formate_lista_curvas(self,lista_curvas):
        lista_nuevo_formate_curvas = []
        for curve in lista_curvas:
            if curve.get_size()<2:
                continue
            lista_pixeles = [(pix.x,pix.y) for pix in curve.pixels_list]
            lista_nuevo_formate_curvas.append(Curva(lista_pixeles, curve.id))
        return lista_nuevo_formate_curvas

    def obtener_interseccion_por_direccion(self,lista_intersecciones,rayo_id):
        inters = [inter for inter in lista_intersecciones if inter.rayo_id == rayo_id]
        inters.sort(key=lambda x: distancia_entre_pixeles(self.centro[0], self.centro[1],x.y,x.x))
        return inters

    def construir_rayos(self,Nr,M,N,centro):
        """

        @param Nr: cantidad radios
        @param M: altura imagen
        @param N: ancho imagen
        @param centro: (y,x)
        @return: lista rayos
        """
        rango_angulos = np.arange(0, 360, 360 / Nr)
        lista_rayos = [Rayo(direccion,centro,M,N) for direccion in rango_angulos]
        return lista_rayos



    def construir_intersecciones(self,lista_rayos,lista_curvas):
        bolsa_intersecciones = []
        for  rayo in lista_rayos:
            for curva in lista_curvas:
                inter = rayo.intersection(curva)
                if not inter.is_empty:
                    if 'MULTIPOINT' in inter.wkt:
                        inter = inter[0]
                    x,y = inter.xy
                    bolsa_intersecciones.append(Interseccion(x=np.array(x)[0],y=np.array(y)[0],curva_id=int(curva.id),rayo_id=int(rayo.direccion)))

        return bolsa_intersecciones



def main(datos):
    M,N,img,centro,SAVE_PATH,sigma = datos['M'], datos['N'], datos['img'], datos['centro'], datos['save_path'] , datos['sigma']
    lista_curvas = datos['lista_curvas']
    save_path = datos['save_path']
    t0 = time.time()
    spyder = SpyderWeb(Nr=Nr, img=img, lista_curvas=lista_curvas, centro=centro[::-1], save_path=save_path)
    listaPuntos = []
    centro_id = np.max(np.unique([inter.curva_id for inter in spyder.lista_intersecciones])) + 1

    for inter in spyder.lista_intersecciones:
        i, j, angulo, radio = inter.y , inter.x, inter.rayo_id, inter.radio(centro[::-1])
        #params={'x':np.uint16(i),'y':np.uint16(j),'angulo':angulo,'radio':radio,'gradFase':-1,'cadenaId':inter.curva_id}
        params = {'x': i, 'y': j, 'angulo': angulo, 'radio': radio, 'gradFase': -1,
                  'cadenaId': inter.curva_id}
        punto = ch.Punto(**params)
        if punto not in listaPuntos:
            listaPuntos.append(punto)

    #agregar puntos artificiales pertenecientes al centro
    for angulo in np.arange(0,360,360/Nr):
        params = {'x': centro[1], 'y': centro[0], 'angulo': angulo, 'radio': 0, 'gradFase': -1,
                  'cadenaId': centro_id }
        punto = ch.Punto(**params)
        listaPuntos.append(punto)


    listaCadenas = ch.asignarCadenas(listaPuntos, centro[::-1], M, N,centro_id=centro_id)


    listaCadenas, listaPuntos, MatrizEtiquetas = ch.renombrarCadenas(listaCadenas, listaPuntos, M, N)

    datos['listaCadenas'] = listaCadenas
    datos['listaPuntos'] = listaPuntos

    listaCadenas, img = datos['listaCadenas'], datos['img']
    ch.visualizarCadenasSobreDisco(
        listaCadenas, img, f"{datos['save_path']}/chains.png", labels=False, gris=True, color=True
    )
    tf = time.time()
    datos['tiempo_muestreo'] = tf - t0
    print(f'Sampling: {tf-t0:.1f} seconds')

    return 0

if __name__=='__main__':
    from skimage.exposure import  equalize_adapthist

    image_file_name = "/media/data/maestria/datasets/FOTOS_DISCOS_1/segmentadas/F2A_CUT_up.tif"

    #image_file_name = "/media/data/maestria/datasets/artificiales/segmentadas/example_10.tif"
    image = cv2.imread(image_file_name)
    (h, w) = image.shape[:2]
    (cX, cY) = (w // 2, h // 2)
    M = cv2.getRotationMatrix2D((cX, cY), 45, 1.0)
    rotated = cv2.warpAffine(image, M, (w, h))
    sigma = 4.5
    high=15
    low=5
    centro = [1204,1264]
    #centro = [500,500]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    #img_seg = utils.segmentarImagen(gray, debug=False)
    img_eq = equalize_adapthist(np.uint8(gray), clip_limit=0.03)
    detector = devernayEdgeDetector(10,img_eq,centro[::-1],"./", sigma=sigma,highthreshold=high,lowthreshold=low)
    img_bin,bin_sin_pliegos,thetaMat ,nonMaxImg,gradientMat,Gx,Gy,img_labels,listaCadenas,listaPuntos,lista_curvas = detector.detect()
    spyder = SpyderWeb(Nr=360,img=image,lista_curvas=lista_curvas,centro=centro[::-1],save_path=".")
