#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Sat Nov 20 16:48:15 2021

@author: henry
"""
import numpy as np
import cv2
import matplotlib.pyplot as plt 
from copy import deepcopy
from sklearn.metrics.pairwise import euclidean_distances
from scipy.interpolate import CubicSpline
import logging 


def rgbToluminance(img):
    if img.ndim>2:
        M, N, C = img.shape
        imageGray = np.zeros((M, N))
        imageGray[:, :] = (img[:, :, 0] * 0.2126 + img[:, :, 1] * 0.7152 + img[:, :, 2] * 0.0722).reshape((M, N))
    else:
        imageGray = img

    return imageGray


class Punto:
    def __init__(self,**params):
        #self.x = np.uint32(params['x'])
        #self.y = np.uint32(params['y'])
        self.x = float(params['x'])
        self.y = float(params['y'])
        self.radio = params['radio']
        self.angulo = params['angulo'] if params['angulo']< 360 else 0
        self.gradFase = params['gradFase']
        self.cadenaId = params['cadenaId']
        self.Nr = params['Nr']
        #self.gradModulo = params['gradmodulo']
        
    def __repr__(self):
        return (f'({self.x},{self.y}) ang:{self.angulo} radio:{self.radio:0.2f} cad.id {self.cadenaId}\n')

    def __str__(self):
        return (f'({self.x},{self.y}) ang:{self.angulo} radio:{self.radio:0.2f} id {self.cadenaId}')

    def __eq__(self,other):
        return self.x == other.x and self.y == other.y and self.angulo == other.angulo



def plotVector(origin,angle,c='k'):
    U,V = np.cos(angle),np.sin(angle)
    X,Y = origin[:,0],origin[:,1]
    #print(f" X {X.shape} Y {Y.shape} U {U.shape} V {V.shape}")
    plt.quiver(X,Y,U,V,color=c,scale=5,scale_units='inches',angles='xy',headwidth=1 ,headlength=3,width =0.005)
    #plt.quiver(*origin,vx,vy,angles='xy', scale_units='xy',units='inches')  


def extraerPixelesPertenecientesAlPerfil(angle,centro,M,N):
    """
        angulo =  {0,pi/4,pi/2,3pi/4,pi,5pi/4,6pi/4,7pi/4}
        ptosCard= {S, SE , E  , NE  , N, NW  , W   , SW   }
         | 
        ----------->x
         |
         | IMAGEN
         |
         y
         
    """
    i = 0
    y_pix =[]
    x_pix = []
    angle_rad = angle * np.pi / 180 
    ctrl = True      
    while ctrl:
        x = centro[1] + i*np.sin(angle_rad)
        y = centro[0] + i*np.cos(angle_rad)
        x = x.astype(int)
        y = y.astype(int)
         
        #print(f'y={y} x={x}')

        if i==0 or not (x==x_pix[-1] and y==y_pix[-1]):
            y_pix.append(y)
            x_pix.append(x)
        if y>=M-1 or y<=1 or x>=N-1 or x<= 1 :
            ctrl = False
        
        i +=1


    return np.array(y_pix),np.array(x_pix)
##interseccion rectas
## sistema lineal
##A1x+B1y=C1
##A2x+B2y=C2

def line(p1, p2):
    A = (p1[1] - p2[1])
    B = (p2[0] - p1[0])
    C = (p1[0]*p2[1] - p2[0]*p1[1])
    return A, B, -C

def intersection(L1, L2):
    #Regla de Cramer
    D  = L1[0] * L2[1] - L1[1] * L2[0]
    Dx = L1[2] * L2[1] - L1[1] * L2[2]
    Dy = L1[0] * L2[2] - L1[2] * L2[0]
    if D != 0:
        x = Dx / D
        y = Dy / D
        return x,y
    else:
        return False
def buildMatrizEtiquetas(M, N, listaPuntos):
    MatrizEtiquetas = -1 * np.ones((M, N))
    for dot in listaPuntos:
        MatrizEtiquetas[int(dot.x), int(dot.y)] = dot.cadenaId
    return MatrizEtiquetas
def llenar_angulos(extA,extB):
    
    if extA.angulo<extB.angulo:
        rango = np.arange(extA.angulo,extB.angulo+1)
    else:
        rango1 = np.arange(extA.angulo,360)
        rango2 = np.arange(0,extB.angulo+1)
        rango = np.hstack((rango2,rango1))
    #print(rango)
    return rango.astype(int)




class Cadena:
    def __init__(self,cadenaId: int,centro,M,N,Nr,A_up=None,A_down=None,B_up=None,B_down=None,is_center = False):
        self.lista = []
        self.id = cadenaId
        self.label_id = cadenaId
        self.size = 0
        self.centro = centro
        self.M = M
        self.N = N
        self.A_up = A_up
        self.A_down = A_down
        self.B_up = B_up
        self.B_down = B_down
        self.is_center = is_center
        self.Nr = Nr
        self.extA = None
        self.extB = None

    def get_borders_chain(self, extremo):
        if extremo in 'A':
            up_chain = self.A_up
            down_chain = self.A_down
            dot_border = self.extA
        else:
            up_chain = self.B_up
            down_chain = self.B_down
            dot_border = self.extB
        return down_chain, up_chain, dot_border

    def _completar_dominio_angular(self,cadena):
        if cadena is None:
            extA = self.extA.angulo
            extB = self.extB.angulo
        else:
            extA = cadena.extA.angulo
            extB = cadena.extB.angulo
        paso = 360/self.Nr
        if extA<= extB:
            dominio_angular = list(np.arange(extA,extB+paso,paso))
        else:
            dominio_angular = list(np.arange(extA,360,paso))
            dominio_angular+= list(np.arange(0,extB+paso,paso))

        return dominio_angular




    def __eq__(self,other):
        if other is None:
             return False

        return self.id == other.id and self.size == other.size #and counter == self.size
    
    def esta_completa(self,regiones=16):
        if self.size<2:
            return False
        dominio_angular = self._completar_dominio_angular(self)
        if len(dominio_angular)>= (regiones - 1)*self.Nr/regiones:
            return True
        else:
            return False

        angulos = llenar_angulos(self.extA,self.extB)
        #print(angulos)
        #angulos = cadena.getDotsAngles()
        step = 360/regiones
        bins = np.arange(0,360,step)
        hist,_ = np.histogram(angulos,bins)
        empties = np.where(hist==0)[0]
        #print(empties)
        if len(empties)==0:
            return True
        else:
            return False

    def sort_dots(self,sentido='horario'):
        if sentido in 'horario':
            return self.puntos_ordenados_horario
        else:
            return self.puntos_ordenados_horario[::-1]

    def _sort_dots(self,sentido='horario'):
        puntos_horario = []
        step = 360 / self.Nr
        if sentido in 'horario':
            angle_k = self.extB.angulo
            while len(puntos_horario) < self.size:
                try:
                    dot = self.getDotByAngle(angle_k)[0]
                    dot.cadenaId = self.id
                    puntos_horario.append(dot)
                except:
                    pass
                    #print(angle_k)
                    #continue
                    
                angle_k = (angle_k-step) % 360

        
        else:
            
            angle_k = self.extA.angulo
            while len(puntos_horario) < self.size:
                try:
                    dot = self.getDotByAngle(angle_k)[0]
                    dot.cadenaId = self.id
                    puntos_horario.append(dot)
                except:
                    pass
                    #print(angle_k)
                    #continue
                angle_k = (angle_k+step) % 360

                
        return puntos_horario


    def __repr__(self):
        return (f'(id_l:{self.label_id},id:{self.id}, size {self.size}')

    def __encontrarExtremos(self):
        diff = np.zeros(self.size)
        extA_init = self.extA if self.extA is not None else None
        extB_init = self.extB if self.extB is not None else None
        #lista tiene que estar ordenada en orden creciente
        self.lista.sort(key=lambda x: x.angulo, reverse=False)
        diff[0] = (self.lista[0].angulo + 360 - self.lista[-1].angulo) % 360

        for i in range(1,self.size):
            diff[i] = (self.lista[i].angulo-self.lista[i-1].angulo) #% 2*np.pi

        if self.size>1:
            extremo1 = diff.argmax()
            if extremo1 == 0:
                #caso1: intervalo conectado
                extremo2 = diff.shape[0]-1
            else:
                #caso2: intervalo partido a la mitad
                extremo2 = extremo1-1

        else:
            extremo1 = extremo2 = 0
        self.extAind = extremo1
        self.extBind = extremo2

        change_border = True if (extA_init is None or extB_init is None) or \
                            (extA_init != self.lista[extremo1] or extB_init != self.lista[extremo2]) else False
        self.extA = self.lista[extremo1]
        self.extB = self.lista[extremo2]

        return change_border

    def add_lista_puntos(self,lista_puntos):
        assert len([punto for punto in lista_puntos if punto.cadenaId != self.id]) ==  0
        self.lista += lista_puntos
        change_border = self.update()
        return change_border


    def update(self):
        self.size = len(self.lista)
        if self.size>1:
            change_border = self.__encontrarExtremos()
            self.puntos_ordenados_horario = self._sort_dots(sentido='horario')
        else:
            raise

        return change_border


    def getDotsCoordinates(self):
         x = [dot.x for dot in self.lista]
         y = [dot.y for dot in self.lista]
         x_rot = np.roll(x,-self.extAind)
         y_rot = np.roll(y,-self.extAind)
         return x_rot,y_rot


    def getDotsAngles(self):
        angles = [dot.angulo for dot in self.lista]
        angles = np.array(angles,dtype=np.int16)
        angles = np.where(angles==360,0,angles)
        return angles

    def getDotByAngle(self,angulo):
        dots = [dot for dot in self.lista if dot.angulo==angulo]
        return list(dots)
    
    def changeId(self,index):
        for dot in self.lista:
            dot.cadenaId = index
        self.id = index
    


def buildMatrizEtiquetas(M, N, listaPuntos):
    MatrizEtiquetas = -1 * np.ones((M, N))
    for dot in listaPuntos:
        MatrizEtiquetas[np.floor(dot.x).astype(int), np.floor(dot.y).astype(int)] = dot.cadenaId
    return MatrizEtiquetas

def verificacion_complitud(listaCadenas):
    for cadena in listaCadenas:
        dominio_angular = cadena._completar_dominio_angular(cadena)
        if not (len(dominio_angular) == cadena.size):
            print(f"cad.id {cadena.label_id} size {cadena.size} dominio_angular {len(dominio_angular)} ")
            raise


def copiar_cadena(cadena):
    cadena_aux = Cadena(cadena.id, cadena.centro, cadena.M, cadena.N, cadena.Nr)
    lista_cadena_aux = [Punto(**{'x':punto.x,'y':punto.y,'angulo':punto.angulo,'radio':punto.radio,
                                 'gradFase':punto.gradFase,'cadenaId':cadena.id,'Nr':punto.Nr})
                    for punto in cadena.lista]
    cadena_aux.lista = lista_cadena_aux
    cadena_aux.extB = cadena.extB
    cadena_aux.extA = cadena.extA
    cadena_aux.size = cadena.size
    #cadena_aux.add_lista_puntos(lista_cadena_aux)
    assert cadena_aux.size == cadena.size
    return cadena_aux

def asignarCadenas(listaPuntos,centro,M,N,centro_id=None,min_chain_lenght=1):
    listaCadenas= []
    cadenas_ids = set([punto.cadenaId for punto in listaPuntos])
    for cad_id in cadenas_ids:
        puntos_cadena = [punto for punto in listaPuntos if punto.cadenaId == cad_id]
        if len(puntos_cadena) <= min_chain_lenght:
            for punto in puntos_cadena:
                listaPuntos.remove(punto)
            continue
        if centro_id is not None and cad_id == centro_id:
            is_center = True
        else:
            is_center = False
        cadena = Cadena(cad_id, centro, M, N, Nr=puntos_cadena[0].Nr,is_center=is_center)
        cadena.add_lista_puntos(puntos_cadena)
        listaCadenas.append(cadena)

    return listaCadenas

def imshow_components(labels):
    # Map component labels to hue val
    label_hue = np.uint8(179*labels/np.max(labels))
    blank_ch = 255*np.ones_like(label_hue)
    labeled_img = cv2.merge([label_hue, blank_ch, blank_ch])

    # cvt to BGR for display
    labeled_img = cv2.cvtColor(labeled_img, cv2.COLOR_HSV2BGR)

    # set bg label to black
    labeled_img[label_hue==0] = 0
    #labeled_imS = cv2.resize(labeled_img, (960, 540))
    cv2.imshow('labeled.png', labeled_img)
    cv2.waitKey()
    


def distancia_entre_puntos(d1,d2):
    v1 = np.array([d1.x,d1.y],dtype=float)
    v2 = np.array([d2.x,d2.y],dtype=float)
    
    return np.sqrt((v1[0]-v2[0])**2+(v1[1]-v2[1])**2)

def formato_array(c1):
    x1,y1 = c1.getDotsCoordinates()
    puntos1 = np.vstack((x1,y1)).T
    
    #print(puntos1.shape)
    c1a = np.array([c1.extA.x,c1.extA.y],dtype=float)
    c1b = np.array([c1.extB.x,c1.extB.y],dtype=float)
    return puntos1.astype(float),c1a,c1b


def dist_extremo(ext,matriz):
    distances = np.sqrt(np.sum((matriz-ext)**2,axis=1))
    return np.min(distances)

def distancia_minima_entre_cadenas(c1,c2):
    puntos1,c1a,c1b = formato_array(c1)
    puntos2,c2a,c2b = formato_array(c2)
    c2a_min = dist_extremo(puntos1,c2a)
    c2b_min = dist_extremo(puntos1,c2b)
    c1a_min = dist_extremo(puntos2,c1a)
    #print(c1b)
    #print(puntos2.astype(float)-c1b.astype(float))
    c1b_min = dist_extremo(puntos2,c1b)
    #print([c2a_min,c2b_min,c1a_min,c1b_min])
    return np.min([c2a_min,c2b_min,c1a_min,c1b_min])

def visualizarCadenasSobreDisco(listaCadenas,img,titulo,labels = False,flechas=False,color=None,hist=None,save=None, gris = False, display=False):
    cadenasSize = []
    #figsize = (30,15)
    figsize=(10,10)
    if gris:
        plt.figure(figsize=figsize)
        imageGray = rgbToluminance(img)
        plt.imshow(imageGray,cmap='gray')
        contador = 0
        for cadena in listaCadenas:
            x,y = cadena.getDotsCoordinates()
            #axs[0].plot(y,x,'-bo', markersize=2,linewidth=1)
            if cadena.esta_completa():
                plt.plot(y,x,'b',linewidth=1)
                contador +=1
            else:
                plt.plot(y,x,'r',linewidth=1)
            if labels:
                plt.annotate(str(cadena.label_id), (y[0], x[0]),c='b')

            if cadena.is_center:
                plt.scatter(y, x,s=2, zorder=10,c='r')

            cadenasSize.append(cadena.size)
        #plt.title(titulo)


        
    else:
        plt.figure(figsize=figsize)
        plt.imshow(img)
        for cadena in listaCadenas:
                if cadena.size==0:
                    continue
                x,y = cadena.getDotsCoordinates()
                #axs[0].plot(y,x,'-bo', markersize=2,linewidth=1)
                if cadena.is_center:
                    plt.scatter(y, x,s=2, zorder=10,c='r')
                if not color:
                    if cadena.size > 2:
                        plt.plot(y,x,linewidth=2)
                    else:
                        plt.scatter(y,x,s=2, zorder=10)                        
                else:
                    if cadena.size > 2:
                        plt.plot(y,x,'r',linewidth=2)
                    else:
                        plt.scatter(y,x,s=2, zorder=10,c='r')                        

                if labels:
                    plt.annotate(str(cadena.label_id), (y[0], x[0]),c='b')
                cadenasSize.append(cadena.size)

    plt.tight_layout()
    plt.axis('off')
    plt.savefig(f"{titulo}")
    if display: 
        plt.show()
    else:
        plt.close()

from lib.dibujar import Dibujar, Color


def dibujar_cadenas_en_imagen(listaCadenas, img, color=None,labels=False):
    M, N, _ = img.shape
    colors_length = 20
    np.random.seed(10)
    #colors = np.random.randint(low=100, high=255, size=(colors_length, 3), dtype=np.uint8)
    colors = Color()
    color_idx = 0
    for cadena in listaCadenas:
        y, x = cadena.getDotsCoordinates()

        pts = np.vstack((x, y)).T.astype(int)
        isClosed = False
        thickness = 5
        if color is None:
            #b,g,r = 0,255,0
            b,g,r = Color.green
        else:
            #b, g, r = colors[color_idx]
            b, g, r = colors.get_next_color()
            #r=255
        img = cv2.polylines(img, [pts],
                            isClosed, (int(b), int(g), int(r)), thickness)
        color_idx = (color_idx + 1) % colors_length


    if labels:
        for cadena in listaCadenas:
            org = cadena.extA
            img = Dibujar.put_text(str(cadena.label_id), img, (int(org.y), int(org.x)),fontScale=1.5)



    return img

def visualizarCadenasSobreDiscoTodas(listaCadenas, img,lista_cadenas_todas, titulo, labels=False, flechas=False, color=None, hist=None,
                                save=None, gris=False, display=False):

    #img_curvas = cv2.cvtColor(img.copy(), cv2.COLOR_RGB2BGR)
    img_curvas = np.zeros_like(img)
    for idx in range(3):
        img_curvas[:,:,idx] = img[:,:,1].copy()
    img_curvas = dibujar_cadenas_en_imagen(lista_cadenas_todas, img_curvas, color = color)
    img_curvas = dibujar_cadenas_en_imagen(listaCadenas,img_curvas,labels=True,color= True)


    print(f"{save}/{titulo}.png")
    cv2.imwrite(f"{save}/{titulo}.png",img_curvas)
    return

def getAngleFromCoordinates(i,j,centro):
    centro = np.array([float(centro[0]),float(centro[1])])
    vector = np.array([float(i),float(j)])-centro
    radAngle = np.arctan2(vector[1],vector[0])
    radAngle = radAngle if radAngle>0 else radAngle+2*np.pi
    gradAngle = np.round(radAngle*180/np.pi) % 360
    return gradAngle

def checkVecindad(MatrizEtiquetas, x, y, cad, ancho=10):
    W = MatrizEtiquetas[x - ancho : x + ancho + 1, y - ancho : y + ancho + 1]
    print(W)
    #plt.figure(figsize=(10, 10))
    #plt.imshow(W)
    #plt.scatter(y_d,x_d,c='r')
    unicos = list(np.unique(W))
    if -1 in unicos:
        unicos.remove(-1)
    return unicos, W


def check_total_dots(listaCadenas, debug=False):
    ####contar cantidad de puntos
    contador = 0
    for chain_check in listaCadenas:
        contador += chain_check.size
    #if debug:
    #    print(f"Se tienen un total de  {contador} puntos")
    return contador


def renombrarCadenas(listaCadenas, listaPuntos, M,N):
    check_total_dots(listaCadenas, debug=True)
    listaCadenas = sorted(listaCadenas, key=lambda x: x.size, reverse=True)
    for index, chain_fill in enumerate(listaCadenas):
        chain_fill.changeId(index)
    
    MatrizEtiquetas = buildMatrizEtiquetas(M, N, listaPuntos)
    return listaCadenas,listaPuntos, MatrizEtiquetas

def contarPuntosListaCadenas(listaCadenas):
    contadorPuntos = 0
    for cadena in listaCadenas:
        contadorPuntos += cadena.size
    return contadorPuntos



def checkMatrizEtiquetasCadenas(listaCadenas, MatrizEtiquetas):
    label='checkMatrizEtiquetasCadenas'
    for cadena in listaCadenas:
        len_etiquetas = np.where(MatrizEtiquetas==cadena.id)[0].shape[0]
        if cadena.size != len_etiquetas:
            print(
                f"{label} cadena.id {cadena.id} cadenaSize {cadena.size} MatrizEtiquetas {len_etiquetas}"
            )
