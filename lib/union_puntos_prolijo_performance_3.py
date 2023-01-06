#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Wed Jan 26 20:15:54 2022
@brief
    Se ramifica este modulo a partir del modulo union_puntos_prolijo.py. Se busca solucionar el problema de performance
    Se realiza un profiler para el ejemplo8 (union_cadenas_prolijo_profiler.pstat)
@author: henry
"""
import json
import numpy as np
import matplotlib.pyplot as plt 
import pandas as pd
import os 
import imageio
import logging
from shapely.geometry import LineString, Point
import glob
from natsort import natsorted

import lib.chain_v4 as ch
from lib.io import write_json,load_json, load_data, save_dots
from lib.utils import write_log
from lib.interpolacion import  pegar_dos_cadenas_interpolando_via_cadena_soporte,  calcular_dominio_de_interpolacion, interpolar_en_domino
from lib.propiedades_fundamentales import criterio_distancia_radial, criterio_derivada_maxima, criterio_distribucion_radial,\
    hay_cadenas_superpuestas, dibujar_segmentoo_entre_puntos, InfoBandaVirtual
from lib.dibujar import Color, Dibujar
from lib.celdas import Celda, ROJO
DEBUG=False

MODULE_NAME="union_chains"
NOT_REPETING_CHAIN = -1


class SystemStatus:
    def __init__(self,lista_puntos,lista_cadenas,matriz_intersecciones,centro_img,img,distancia_angular,
                path=None,radio_limit=0.1,debug=False, ancho_std=2, derivada_desde_centro = False, derivative_th=1.5):
        self.desde_el_centro = derivada_desde_centro
        self.path = path
        self.ancho_std = ancho_std
        self.debug = debug
        self.lista_puntos = lista_puntos
        self.lista_cadenas = lista_cadenas
        self.angular_distance = distancia_angular
        self.__sort_chain_list_and_update_relative_position()
        self.matriz_intersecciones = matriz_intersecciones
        self.centro = centro_img
        self.img = img
        self.M = img.shape[0]
        self.N = img.shape[1]
        self.next_chain_index = 0 
        self.iterations_since_last_change = 0
        self.radio_limit = radio_limit
        self.label="system_status"
        self.something_change_with_this_chain= False
        self.cadena_dejo_de_crecer_en_la_ultima_iteracion = NOT_REPETING_CHAIN
        self.hast_dict = {}
        self.iteracion = 0
        self.dict_buscar_cadena_candidata_a_pegar = {}
        self.dict_control_de_verificacion = {}
        self.derivative_th = derivative_th



    def buscar_cadena_comun_a_ambos_extremos(self, chain):
        dominio_angular_cadena_soporte = chain._completar_dominio_angular(chain)
        dominio_a_completar = [angulo for angulo in np.arange(0,360,360/chain.Nr) if angulo not in dominio_angular_cadena_soporte]
        dominio_a_completar += [chain.extA.angulo, chain.extB.angulo]
        cadenas_en_dominio_a_completar = []
        for cadena in self.lista_cadenas:
            dominio_angular = cadena._completar_dominio_angular(cadena)
            if np.intersect1d(dominio_angular,dominio_a_completar).shape[0] == len(dominio_a_completar):
                cadenas_en_dominio_a_completar.append(cadena)
        if len(cadenas_en_dominio_a_completar)==0:
            return None

        puntos_en_direccion_a = [cad.getDotByAngle(chain.extA.angulo)[0] for cad in cadenas_en_dominio_a_completar]
        puntos_en_direccion_a.sort(key = lambda x: ch.distancia_entre_puntos(x,chain.extA))
        id_cadena_mas_cercana = puntos_en_direccion_a[0].cadenaId
        return [cad for cad in self.lista_cadenas if cad.id == id_cadena_mas_cercana][0]

    def completar_cadena_via_anillo_soporte(self,cadena_anillo_soporte, cad1):
        extremo_cad1 = cad1.extB
        extremo_cad2 = cad1.extA

        extremo = 'B'
        lista_puntos_generados = []
        interpolar_en_domino(cadena_anillo_soporte, extremo_cad1, extremo_cad2, extremo, cad1, lista_puntos_generados)
        assert len([dot for dot in cad1.lista if dot in lista_puntos_generados]) == 0
        self.add_list_to_system(cad1, lista_puntos_generados)

        return

    def completar_cadena_si_no_hay_interseccion_con_otras(self,chain):
        chain_border = self.buscar_cadena_comun_a_ambos_extremos(chain)
        #construir bandas de busqueda
        extremo_cad1 = chain.extB
        extremo_cad2 = chain.extA
        extremo = 'B'
        puntos_virtuales = []
        chain_copy = ch.copiar_cadena(chain)
        interpolar_en_domino(chain_border, extremo_cad1, extremo_cad2, extremo, chain_copy, puntos_virtuales)
        ptos_virtuales_con_borde = [extremo_cad1] + puntos_virtuales + [extremo_cad2]
        assert len([dot for dot in chain_copy.lista if dot in puntos_virtuales]) == 0

        info_band = InfoBandaVirtual( ptos_virtuales_con_borde,  chain, chain, extremo, chain_border, ancho_banda=0.1)
        hay_cadena = hay_cadenas_superpuestas(self, info_band)
        if not hay_cadena:
            self.completar_cadena_via_anillo_soporte(chain_border,chain)
            if self.debug:
                ch.visualizarCadenasSobreDiscoTodas([chain], self.img.copy(),self.lista_cadenas,
                                f'{self.iteracion}_{chain.label_id}_completar_size_{chain.size}', save=self.path, labels=True)
                self.iteracion += 1


        return 0

    def continue_in_loop(self):
        return self.iterations_since_last_change < len(self.lista_cadenas)

    def get_current_chain(self):
        chain = self.lista_cadenas[self.next_chain_index]
        write_log(MODULE_NAME,self.label,f"iteration_since_last_change {self.iterations_since_last_change} "
        f"idx {self.next_chain_index} cad.id {self.lista_cadenas[self.next_chain_index].label_id} size "
        f"{self.lista_cadenas[self.next_chain_index].size} total_cadenas {len(self.lista_cadenas)}")
        self.chain_size_at_the_begining_of_iteration = len(self.lista_cadenas)
        if chain.esta_completa(regiones=8) and chain.size < chain.Nr:
            self.completar_cadena_si_no_hay_interseccion_con_otras(chain)

        return chain

    def new_data_in_hash_dict(self,cadena_soporte, conjunto_cadenas):
        ##########################################hash magic############################################################
        ################################################################################################################
        existe_hash = cadena_soporte.label_id in self.hast_dict.keys()
        hash_actual = self.make_hash(cadena_soporte, conjunto_cadenas)

        if not existe_hash:
            self.hast_dict[cadena_soporte.label_id] = hash_actual
            return True

        hash_previo = self.hast_dict[cadena_soporte.label_id]
        if hash_previo != hash_actual:
            self.hast_dict[cadena_soporte.label_id] = hash_actual
            return True

        write_log(MODULE_NAME,self.label,f"cad_soporte {cadena_soporte.label_id} existe hash")
        return False

    def make_hash_controles_de_verificacion(self, lista_cadenas):
        lista_cadenas.sort(key=lambda x: x.label_id)
        string = ""
        for cad in lista_cadenas:
            string += f"{cad.label_id}_{cad.size}"

        return hash(string)
    def controles_de_verificacion_if_exist_get_results(self, cadena_soporte, cadena_origen, cadena_candidata, border):
        res = None
        if False:
            #hash_actual = self.make_hash(cadena_soporte, [cadena_origen, cadena_candidata])
            hash_actual = self.make_hash_controles_de_verificacion([cadena_soporte, cadena_origen, cadena_candidata])
            res=  self.dict_control_de_verificacion[hash_actual] if hash_actual in \
                                                            self.dict_control_de_verificacion.keys() else None
            if res is not None:
                write_log(MODULE_NAME,self.label,f"cad_soporte {cadena_soporte.label_id} cad_origen {cadena_origen.label_id} "
                                                 f"No se repite proceso")
        return res

    def controles_de_verificacion_add_data_to_hash_dict(self,  cadena_soporte, cadena_origen, cadena_candidata, valida,distancia):
        if False:
            hash_actual = self.make_hash_controles_de_verificacion([cadena_soporte, cadena_origen, cadena_candidata])
            self.dict_control_de_verificacion[hash_actual] = (valida, distancia)

        return

    def remove_key_from_hash_dictionaries(self, cadena_soporte, cadena_origen, cadena_candidata):
        if False:
            hash_actual = self.make_hash_controles_de_verificacion([cadena_soporte, cadena_origen, cadena_candidata])
            if hash_actual in self.dict_control_de_verificacion.keys():
                self.dict_control_de_verificacion.pop(hash_actual)


    def buscar_cadena_candidata_a_pegar_if_exist_get_results(self, cadena_soporte, cadena_origen, border):
        hash_actual = self.make_hash(cadena_soporte, [cadena_origen], border = border)
        res=  self.dict_buscar_cadena_candidata_a_pegar[hash_actual] if hash_actual in \
                                                        self.dict_buscar_cadena_candidata_a_pegar.keys() else None
        if res is not None:
            write_log(MODULE_NAME,self.label,f"cad_soporte {cadena_soporte.label_id} cad_origen {cadena_origen.label_id} "
                                             f"No se repite proceso")
        return res


    def buscar_cadena_candidata_a_pegar_add_data_to_hash_dict(self, cadena_soporte, cadena_origen, candidata, border):
        hash_actual = self.make_hash(cadena_soporte, [cadena_origen], border= border)
        self.dict_buscar_cadena_candidata_a_pegar[hash_actual] = candidata
        # write_log(MODULE_NAME,self.label,f"cad_soporte {cadena_soporte.label_id} cad_origen {cadena_origen.label_id} "
        #                                  f"cad_can {candidata.label_id if candidata is not None else candidata}")
        return

    def buscar_cadena_candidata_a_pegar_rm_data_from_hash_dict(self, cadena_soporte, cadena_origen, border):
        hash_actual = self.make_hash(cadena_soporte, [cadena_origen], border= border)
        self.dict_buscar_cadena_candidata_a_pegar.pop(hash_actual)

        return

    def cadena_info_string_format(self, cadena):
        return f"{cadena.label_id}"

    def make_hash(self, cadena_soporte, conjunto_cadenas, border = None):
        cadenas_ordenadas = conjunto_cadenas + [cadena_soporte]
        cadenas_ordenadas.sort(key = lambda x: x.label_id)
        string = ""
        for cad in cadenas_ordenadas:
            string += self.cadena_info_string_format(cad)
        if border is not None:
            string += f"{conjunto_cadenas[0].extA.angulo if border in 'A' else conjunto_cadenas[0].extB.angulo}"
        return hash(string)

    def is_new_dot_valid(self,new_dot):
        if new_dot in self.lista_puntos:
            return False
        if new_dot.x >= self.M or new_dot.y >= self.N or new_dot.x < 0 or new_dot.y < 0:
            return False

        return True

    def actualizar_vecindad_cadenas_si_amerita(self, cadenas_posibles_a_modificar):
        dummy_chain = None
        for chain_p in cadenas_posibles_a_modificar:
            border = 'A'
            down_chain, up_chain, dot_border = get_up_and_down_chains(self.lista_puntos, self.lista_cadenas,
                                                                      chain_p,
                                                                      border)

            chain_p.A_up = up_chain if up_chain is not None else dummy_chain
            chain_p.A_down = down_chain if down_chain is not None else dummy_chain
            border = 'B'
            down_chain, up_chain, dot_border = get_up_and_down_chains(self.lista_puntos, self.lista_cadenas,
                                                                      chain_p,
                                                                      border)
            chain_p.B_up = up_chain if up_chain is not None else dummy_chain
            chain_p.B_down = down_chain if down_chain is not None else dummy_chain

        return
    @staticmethod
    def filter_all_chains_with_border_in_direction( direction, chains_over_radial_direction):
        cadenas_posibles_a_modificar = []
        for cad_inter in chains_over_radial_direction:
            if direction in [cad_inter.extA.angulo, cad_inter.extB.angulo]:
                cadenas_posibles_a_modificar.append(cad_inter)

        return cadenas_posibles_a_modificar
    def add_list_to_system(self, chain, lista_puntos):
        lista_puntos_procesados = []
        for new_dot in lista_puntos:
            if chain.id != new_dot.cadenaId:
                raise

            lista_puntos_procesados.append(new_dot)
            if new_dot in self.lista_puntos:
                raise
            self.lista_puntos.append(new_dot)
            # 1.0 Update chain list intersection
            cadenas_id_intersectantes, chains_over_radial_direction = self._chains_id_over_radial_direction(new_dot.angulo)
            self.matriz_intersecciones[chain.id, cadenas_id_intersectantes] = 1
            self.matriz_intersecciones[cadenas_id_intersectantes, chain.id] = 1

            # 2.0 Update boundary chains above and below.
            dots_over_direction = [dot for chain in chains_over_radial_direction for dot in chain.lista if dot.angulo == new_dot.angulo]
            dots_over_direction.append(new_dot)
            dots_over_direction.sort(key= lambda x: x.radio)
            idx_new_dot = dots_over_direction.index(new_dot)

            up_dot = dots_over_direction[idx_new_dot+1] if idx_new_dot < len(dots_over_direction)-1 else None
            if up_dot is not None:
                up_chain = [chain for chain in chains_over_radial_direction if chain.id == up_dot.cadenaId][0]
                if up_dot == up_chain.extA:
                    up_chain.A_down = chain
                elif up_dot == up_chain.extB:
                    up_chain.B_down = chain

            down_dot = dots_over_direction[idx_new_dot - 1] if idx_new_dot > 0 else None
            if down_dot is not None:
                down_chain = [chain for chain in chains_over_radial_direction if chain.id == down_dot.cadenaId][
                    0]
                if down_dot == down_chain.extA:
                    down_chain.A_up = chain
                elif down_dot == down_chain.extB:
                    down_chain.B_up = chain

        change_border = chain.add_lista_puntos(lista_puntos_procesados)
        self.actualizar_vecindad_cadenas_si_amerita([chain])

    def update_state(self,chain,S_up,S_down):
        self.chain_size_at_the_end_of_iteration = len(self.lista_cadenas)

        if self._state_changes_in_this_iteration():
            self.lista_cadenas = sorted(self.lista_cadenas, key=lambda x: x.size, reverse=True)
            self.iterations_since_last_change = 0

            #siguiente cadena limite
            chains_sorted = sorted([chain]+S_up+S_down, key=lambda x: x.size, reverse=True)
            if chains_sorted[0].id == chain.id:
                self.next_chain_index = (self.lista_cadenas.index(chain) + 1) % len(self.lista_cadenas)
            else:
                self.next_chain_index = self.lista_cadenas.index(chains_sorted[0])


        else:
            self.iterations_since_last_change+=1
            self.next_chain_index = (self.lista_cadenas.index(chain) + 1) % len(self.lista_cadenas)

    def _chains_id_over_radial_direction(self,angle):
        chains_in_radial_direction = get_chains_within_angle(angle, self.lista_cadenas)
        chains_id_over_radial_direction = [cad.id for cad in chains_in_radial_direction]

        return chains_id_over_radial_direction, chains_in_radial_direction

    def __sort_chain_list_and_update_relative_position(self):
        self.lista_cadenas = sorted(self.lista_cadenas, key=lambda x: x.size, reverse=True)
        self.actualizar_vecindad_cadenas_si_amerita(self.lista_cadenas)


    def _state_changes_in_this_iteration(self):
        return self.chain_size_at_the_begining_of_iteration > self.chain_size_at_the_end_of_iteration



def calcular_distancia_acumulada_vecindad(cadena_larga, cadena_candidata, extremo, cadena_soporte, vecindad_amplitud = 90):
    sentido = 'anti' if extremo in 'A' else 'horario'
    vecindad = cadena_larga.sort_dots(sentido=sentido)[:vecindad_amplitud]
    vecindad += cadena_candidata.sort_dots(sentido='anti' if sentido in 'horario' else 'horario')[:vecindad_amplitud]

    distancias = []
    cadena_ids = []
    for dot in vecindad:
        dot_list_in_radial_direction = get_closest_dots_to_angle_on_radial_direction_sorted_by_ascending_distance_to_center(
            [cadena_soporte], dot.angulo)
        distancias.append(np.abs(dot_list_in_radial_direction[0].radio - dot.radio))
        cadena_ids.append(dot.cadenaId)

    cadena_origen_extremo = cadena_larga.extA if extremo in 'A' else cadena_larga.extB
    cadena_candidata_extremo =  cadena_candidata.extB if extremo in 'A' else cadena_candidata.extA
    return distancias, cadena_ids,  ch.distancia_entre_puntos(cadena_origen_extremo, cadena_candidata_extremo)

def se_cumple_condicion_agrupamiento(distancias, cadena_ids, debug=None,histograma_test = False):
    from sklearn.cluster import KMeans
    distancias = np.array(distancias).reshape((-1, 1))
    kmeans = KMeans(n_clusters=2, random_state=0).fit(distancias)
    km_labels = kmeans.labels_
    clase_0 = np.where(km_labels == 0)[0]
    clase_1 = np.where(km_labels == 1)[0]
    if histograma_test:
        hist, bins, _ = plt.hist(distancias)
        hist_0,_,_ = plt.hist(distancias[clase_0], bins=bins)
        hist_1,_,_ = plt.hist(distancias[clase_1], bins=bins)
        interseccion = [value0+value1 for value0, value1 in zip( hist_0, hist_1) if value1>0 and value0>0]
        condicion = len(interseccion) > 0

    else:
        condicion = (np.unique(np.array(cadena_ids)[clase_1]).shape[0] > 1 and np.unique(np.array(cadena_ids)[clase_0]).shape[0] > 1)
        hist, bins, _ = plt.hist(distancias)
        #hist_0,_,_ = plt.hist(distancias[clase_0], bins=bins)
        #hist_1,_,_ = plt.hist(distancias[clase_1], bins=bins)
        cadena_ids_unique = np.unique(cadena_ids)

        cadena_id_1 = np.where(np.array(cadena_ids) == cadena_ids_unique[0])[0]
        cadena_id_2 = np.where(np.array(cadena_ids) == cadena_ids_unique[1])[0]
        media_0 = np.mean(distancias[cadena_id_1])
        media_1 = np.mean(distancias[cadena_id_2])
        ancho_bin = np.mean(np.gradient(bins))
        if media_0>media_1:
            infimo = np.max(distancias[cadena_id_2])
            supremo = np.min(distancias[cadena_id_1])
        else:
            infimo = np.max(distancias[cadena_id_1])
            supremo = np.min(distancias[cadena_id_2])

        condicion |= np.abs(supremo-infimo) < ancho_bin
        #interseccion = [value0+value1 for value0, value1 in zip( hist_0, hist_1) if value1>0 and value0>0]
        #condicion|= len(interseccion) > 0
        #condicion = (np.unique(np.array(cadena_ids)[clase_1]).shape[0] > 1 or np.unique(np.array(cadena_ids)[clase_0]).shape[0] > 1)

    if debug is not None:
        plt.figure()
        plt.subplot(121)
        hist, bins, _ = plt.hist(distancias)
        plt.hist(distancias[clase_0], bins=bins)
        plt.hist(distancias[clase_1], bins=bins)
        plt.title(f"kmeans clusters: {condicion}")

        plt.subplot(122)
        cadena_ids_unique = np.unique(cadena_ids)

        cadena_id_1 = np.where(np.array(cadena_ids) == cadena_ids_unique[0])[0]
        cadena_id_2 = np.where(np.array(cadena_ids) == cadena_ids_unique[1])[0]

        hist, bins, _ = plt.hist(distancias)
        plt.hist(distancias[cadena_id_1], bins=bins)
        plt.hist(distancias[cadena_id_2], bins = bins)
        plt.show()
        plt.savefig(debug)
        plt.close()


    return condicion

def criterio_kmeans(cadena_candidata, cadena_origen, extremo, cadena_soporte, vecindad_amplitud):
    distancias, cadena_ids, distancia_entre_bordes = calcular_distancia_acumulada_vecindad(
        cadena_origen,
        cadena_candidata,
        extremo,
        cadena_soporte, vecindad_amplitud=vecindad_amplitud)

    return se_cumple_condicion_agrupamiento(distancias, cadena_ids,
                                            debug=None,
                                            histograma_test=False), distancia_entre_bordes

def main(chain_list, dot_list, intersections_matrix, img_orig, img_center, path=None, radial_tolerance=2,
         todas_intersectantes = False, distancia_angular_maxima=22,debug_imgs=False,ancho_std=2, der_desde_centro=False,
         fast=True, derivative_th=1.5):
    state = SystemStatus(dot_list, chain_list, intersections_matrix, img_center, img_orig, distancia_angular_maxima,
                         radio_limit=radial_tolerance,path=path,debug=debug_imgs, ancho_std = ancho_std,
                         derivada_desde_centro= der_desde_centro, derivative_th=derivative_th)
    #check_duplicate_dots(state.lista_puntos)
    del dot_list
    del chain_list
    label = 'main'
    write_log(MODULE_NAME, label,
              f"\n\n\n\n\n\nradial_tolerance={radial_tolerance}\n\n\n\n\n\n\n\n")
    while state.continue_in_loop():
        chain = state.get_current_chain()
        recorrer_s_up = True; recorrer_s_down = True
        while True:
            S_up, S_down = armar_listas_up_and_down(state, chain, recorrer_s_up, recorrer_s_down,fast=fast)

            if recorrer_s_up:
                if debug_imgs:
                    ch.visualizarCadenasSobreDiscoTodas([chain] + S_up, state.img, state.lista_cadenas,
                                                        f'{state.iteracion}_soporte_{chain.label_id}_S_up_inicio_iter', save=state.path, labels=True)
                    state.iteracion += 1
                    write_log(MODULE_NAME, label,
                              f"cad.id {chain.label_id} S_up {[cad.label_id for cad in S_up]}")

                se_modifica_s_up = recorrer_subconjunto_de_cadenas_y_pegar_si_amerita(state, S_up, chain,sentido='up',check=todas_intersectantes)

                if debug_imgs:
                    ch.visualizarCadenasSobreDiscoTodas([chain]+S_up, state.img.copy(),state.lista_cadenas, f'{state.iteracion}_{chain.label_id}_S_up_fin_iter', save=state.path, labels=True)
                    state.iteracion+=1

            else:
                se_modifica_s_up = False

            if recorrer_s_down:
                if debug_imgs:
                    ch.visualizarCadenasSobreDiscoTodas([chain] + S_down, state.img, state.lista_cadenas,
                                                        f'{state.iteracion}_{chain.label_id}_S_down_inicio_iter', save=state.path, labels=True)
                    state.iteracion += 1

                    write_log(MODULE_NAME, label,
                              f"cad.id {chain.label_id} S_down {[cad.label_id for cad in S_down]}")

                se_modifica_s_down = recorrer_subconjunto_de_cadenas_y_pegar_si_amerita(state, S_down, chain,sentido='down',check=todas_intersectantes)

                if debug_imgs:
                    ch.visualizarCadenasSobreDiscoTodas([chain] + S_down, state.img, state.lista_cadenas,
                                                        f'{state.iteracion}_{chain.label_id}_S_down_fin_iter', save=state.path,
                                                        labels=True)
                    state.iteracion += 1
            else:
                se_modifica_s_down = False

            if not (se_modifica_s_down or se_modifica_s_up):
                break

            recorrer_s_down = True if se_modifica_s_down else False
            recorrer_s_up = True if se_modifica_s_up else False


        state.update_state( chain, S_up, S_down)

    #rellenar cadenas completas
    for chain in state.lista_cadenas:
        if chain.esta_completa(regiones=8) and chain.size < chain.Nr:
                state.completar_cadena_si_no_hay_interseccion_con_otras(chain)

    return state.lista_puntos, state.lista_cadenas, state.matriz_intersecciones

def ordenar_cadenas(S_up,chain):
    #TODO ordenar con orden relativo a chain. Es decir, el elemento 0 es el elemento que incluye al angulo del extremoA de chain.
    # El ultimo elemento, es el mas cercano al extremo B de chain.
    S_up.sort(key=lambda x: x.extA.angulo)

def recorrer_listas_algoritmo_rapido(state, chain, recorrer_s_down, recorrer_s_up):
    S_up = []
    S_down = []
    for ch_cand in state.lista_cadenas:
        if ch_cand == chain:
            continue
        a_up, b_up, a_down, b_down = ch_cand.A_up, ch_cand.B_up, ch_cand.A_down, ch_cand.B_down

        if (recorrer_s_up and (ch_cand not in S_up) and ((a_down is not None and chain is a_down) or
                (b_down is not None and chain is b_down))):
            S_up.append(ch_cand)

        if (recorrer_s_down and (ch_cand not in S_down) and ((a_up is not None and chain is a_up) or
                (b_up is not None and chain is b_up))):
            S_down.append(ch_cand)

    return S_up, S_down
def recorrer_listas_algoritmo_lento(state,chain,recorrer_s_down, recorrer_s_up):
    S_up = []
    S_down = []
    for punto_soporte in chain.lista:
        puntos_en_direccion = [punto for punto in state.lista_puntos if punto_soporte.angulo == punto.angulo]
        puntos_en_direccion.sort(key = lambda x: x.radio)
        idx_soporte = puntos_en_direccion.index(punto_soporte)
        if idx_soporte>0 and recorrer_s_down:
            punto_abajo = puntos_en_direccion[idx_soporte-1]
            cadena_abajo = [cad for cad in state.lista_cadenas if cad.id == punto_abajo.cadenaId][0]
            if punto_abajo in [cadena_abajo.extA, cadena_abajo.extB] and cadena_abajo not in S_down:
                S_down.append(cadena_abajo)

        if idx_soporte < len(puntos_en_direccion)-1 and recorrer_s_up:
            punto_arriba = puntos_en_direccion[idx_soporte+1]
            cadena_arriba = [cad for cad in state.lista_cadenas if cad.id == punto_arriba.cadenaId][0]
            if punto_arriba in [cadena_arriba.extA, cadena_arriba.extB] and cadena_arriba not in S_up:
                S_up.append(cadena_arriba)


    return S_up, S_down
def control_cadenas_en_ambos_grupos(state,S_up, S_down):
    up_down = [cad for cad in S_up if cad in S_down]

    return up_down

def control_lista_iguales(lista1,lista2):
    iguales = True
    lista1.sort(key=lambda  x: x.id)
    lista2.sort(key=lambda x: x.id)
    for cad1, cad2 in zip(lista1,lista2):
        if not (cad1 == cad2):
            iguales = False
            break
    return iguales
def armar_listas_up_and_down(state, chain, recorrer_s_up, recorrer_s_down,fast=True):
    if DEBUG:
        S_up_lento, S_down_lento = recorrer_listas_algoritmo_lento(state, chain, recorrer_s_down, recorrer_s_up)
        S_up, S_down = recorrer_listas_algoritmo_rapido(state, chain, recorrer_s_down, recorrer_s_up)

        iguales = control_lista_iguales(S_down_lento, S_down)
        if not iguales:
            ch.visualizarCadenasSobreDiscoTodas([chain]+S_down,state.img,[],'rapido',labels=True,save=state.path)
            ch.visualizarCadenasSobreDiscoTodas([chain]+S_down_lento,state.img,[],'lento',labels=True,save=state.path)
            raise

        iguales = control_lista_iguales(S_up_lento, S_up)
        if not iguales:
            ch.visualizarCadenasSobreDiscoTodas([chain]+S_up,state.img,[],'rapido',labels=True,save=state.path)
            ch.visualizarCadenasSobreDiscoTodas([chain]+S_up_lento,state.img,[],'lento',labels=True,save=state.path)
            raise

    if not fast:
        S_up, S_down = recorrer_listas_algoritmo_lento(state,chain,recorrer_s_down, recorrer_s_up)

    else:
        S_up, S_down = recorrer_listas_algoritmo_rapido(state, chain, recorrer_s_down, recorrer_s_up)

    if state.debug:
        label = 'armar_listas_up_and_down'
        write_log(MODULE_NAME, label,
                  f"cad.id {chain.label_id} S_up {[cad.label_id for cad in S_up]} S_down {[cad.label_id for cad in S_down]} ")

    up_down = control_cadenas_en_ambos_grupos(state,S_up, S_down)
    for cad in up_down:
        S_up.remove(cad)
    return S_up, S_down


def select_closest_chain(chain, a_neighbour_chain, b_neighbour_chain):
    if a_neighbour_chain is not None:
        d_a = distance_between_border(chain, a_neighbour_chain, 'A')
    else:
        d_a = -1

    if b_neighbour_chain is not None:
        d_b = distance_between_border(chain, b_neighbour_chain, 'B')
    else:
        d_b = -1

    if d_a >= d_b:
        closest_chain = a_neighbour_chain
    elif d_b > d_a:
        closest_chain = b_neighbour_chain
    else:
        closest_chain = None

    return closest_chain


def buscar_cadena_candidata_a_pegar_con_simetria(state, chain, S_up, S_up_no_inter, ch_up, border, sentido, check):
    label = 'buscar_cadena_candidata_a_pegar_con_simetria'
    if state.debug:
        write_log(MODULE_NAME, label,
                  f"cad.id {ch_up.label_id} border {border} conjunto_cadenas {[cad.label_id for cad in S_up_no_inter]}")

    candidata_a = buscar_cadena_candidata_a_pegar(state, chain, S_up, S_up_no_inter, ch_up, border, sentido=sentido,
                                                      check_angle=check)
    if state.debug:
        write_log(MODULE_NAME, label,
                  f"iter: {state.iteracion} cad.id {ch_up.label_id} border {border} candidata {candidata_a.label_id if candidata_a is not None else None}")

    # control de validacion simetrico
    if candidata_a is None:
        return candidata_a


    id_inter = np.where(state.matriz_intersecciones[candidata_a.id] == 1)[0]
    S_up_no_inter_a = [cad for cad in S_up if cad.id not in id_inter]
    candidata_simetrica = buscar_cadena_candidata_a_pegar(state, chain, S_up, S_up_no_inter_a, candidata_a,
                                                          'B' if border in 'A' else 'A',
                                                          sentido=sentido,
                                                          check_angle=check)
    candidata_a = None if candidata_simetrica != ch_up else candidata_a
    if state.debug:
        write_log(MODULE_NAME, label,
                  f"iter: {state.iteracion} cad.id {ch_up.label_id} border {border} candidata {candidata_a.label_id if candidata_a is not None else None}")

    if candidata_a is not None and (candidata_a.size + ch_up.size) > candidata_a.Nr:
        candidata_a = None

    return candidata_a
def control_puntos_cadenas(listaCadenas,debug=True):
    label = 'control_puntos_cadenas'
    for ch_up in listaCadenas:
        hay_error = len([punto for punto in ch_up.lista if punto.cadenaId != ch_up.id]) > 0
        if hay_error:
            write_log(MODULE_NAME, label,
                      f"ch_up {ch_up.label_id}",debug=debug)
            raise

def recorrer_subconjunto_de_cadenas_y_pegar_si_amerita(state,S_up, chain,sentido = 'up',check=True,debug=False):
    label='recorrer_subconjunto_de_cadenas_y_pegar_si_amerita'
    state.chain = chain
    lenght_s_up_init = len(S_up)
    if lenght_s_up_init == 0:
        return False
    curr_index = 0
    while True:
        ch_up = S_up[curr_index]
        # busco la proxima que no intersecta
        id_inter = np.where(state.matriz_intersecciones[ch_up.id] == 1)[0]
        if state.debug:
            write_log(MODULE_NAME, label,
                      f"iter: {state.iteracion} cad.id {ch_up.label_id} cad.size {ch_up.size} curr_index "
                      f"{curr_index} S_up_inter {[cad.label_id for cad in S_up if cad.id in id_inter]}",debug=debug)

        S_up_no_inter = [cad for cad in S_up if cad.id not in id_inter]

        if state.debug:
            write_log(MODULE_NAME, label,
                      f"iter: {state.iteracion} cad.id {ch_up.label_id} cad.size {ch_up.size} curr_index "
                      f"{curr_index} S_up_no_inter {[cad.label_id for cad in S_up_no_inter]}",debug=debug)

        if len(S_up_no_inter)>0:
            # hay cadenas candidatas para unir
            border = 'B'
            if state.debug:
                write_log(MODULE_NAME, label,
                      f"iter: {state.iteracion} cad.id {ch_up.label_id} cad.size {ch_up.size} ext {border}",debug=debug)

            candidata_b = buscar_cadena_candidata_a_pegar_con_simetria(state, chain, S_up, S_up_no_inter, ch_up, border,
                                                          sentido, check)

            if state.debug and candidata_b is not None:
                ch.visualizarCadenasSobreDiscoTodas([chain, ch_up], state.img.copy(), [],
                                                    f'{state.iteracion}_cadena_origen_{ch_up.label_id}_cand_{border}_{candidata_b.label_id}',
                                                    save=state.path, labels=True)
                write_log(MODULE_NAME, label, f'{state.iteracion}_cadena_origen_{ch_up.label_id}_cand_{border}_{candidata_b.label_id}',debug=debug)
                state.iteracion += 1

            border = 'A'
            if state.debug:
                write_log(MODULE_NAME, label,
                          f"iter: {state.iteracion} cad.id {ch_up.label_id} cad.size {ch_up.size} ext {border}",debug=debug)

            candidata_a = buscar_cadena_candidata_a_pegar_con_simetria(state, chain, S_up, S_up_no_inter, ch_up, border,
                                                          sentido, check)

            if state.debug and candidata_a is not None:
                ch.visualizarCadenasSobreDiscoTodas([chain, ch_up], state.img.copy(), [],
                                                    f'{state.iteracion}_cadena_origen_{ch_up.label_id}_cand_{border}_{candidata_a.label_id}',
                                                    save=state.path, labels=True)
                write_log(MODULE_NAME, label,
                          f'{state.iteracion}_cadena_origen_{ch_up.label_id}_cand_{border}_{candidata_a.label_id}',debug=debug)
                state.iteracion += 1

            closest_chain = select_closest_chain(ch_up, candidata_a, candidata_b)

            border = 'A' if closest_chain == candidata_a else 'B'
            se_pego_cadena = union_2_chains(state, ch_up, closest_chain, border, S_up)
            if state.debug and se_pego_cadena:
                ch.visualizarCadenasSobreDiscoTodas([chain, ch_up], state.img.copy(), [],
                                                    f'{state.iteracion}_se_pega_origen_{ch_up.label_id}_extremo_{border}_con_{closest_chain.label_id}',
                                                    save=state.path, labels=True)
                write_log(MODULE_NAME, label, f'{state.iteracion}_se_pega_origen_{ch_up.label_id}_extremo_{border}_con_{closest_chain.label_id}',debug=debug)
                state.iteracion += 1

        else:
            # no hay cadenas candidatas para unir, siguiente iteracion
            se_pego_cadena = False

        # siguiente iteracion
        curr_index = S_up.index(ch_up)
        curr_index = curr_index + 1 if not se_pego_cadena else curr_index
        if curr_index >= len(S_up):
            break

    lenght_s_up_final = len(S_up)
    return lenght_s_up_final < lenght_s_up_init



def recorrer_subconjunto_de_cadenas_y_pegar_si_amerita_INPROGRESS(state,S_up, cadena_soporte,sentido = 'up',check=True):
    label='recorrer_subconjunto_de_cadenas_y_pegar_si_amerita'
    lenght_s_up_init = len(S_up)
    if lenght_s_up_init == 0:
        return False

    #1.0 ordenar cadenas angularmente relativo a cadena soporte segun extremo A

    ###############

    lenght_s_up_final = len(S_up)
    return lenght_s_up_final < lenght_s_up_init
def ordenar_cadenas_en_vecindad(state, S_up_no_inter, ch_up, border):
    conjunto_de_cadenas_candidatas_cercanas = []
    for cad in S_up_no_inter:
        distancia = distancia_angular_entre_cadenas(ch_up, cad, border)
        if distancia < state.angular_distance and cad.id != ch_up.id:
            conjunto_de_cadenas_candidatas_cercanas.append((distancia, cad))

    # ordenar por cercania al extremo de la cadena (menor a mayor)
    conjunto_de_cadenas_candidatas_cercanas.sort(key=lambda x: x[0])


    # segundo ordenamiento. Dentro de todas las cadenas que estan a la misma distancia angular, ordenar por distancia radial
    conjunto_de_cadenas_ordenadas = []
    distancias_todas = [conj[0] for conj in conjunto_de_cadenas_candidatas_cercanas]
    distancias_unicas = np.unique(distancias_todas)
    for d in distancias_unicas:
        cad_d = [conj[1] for conj in conjunto_de_cadenas_candidatas_cercanas if conj[0]==d]
        distancias_euclidean_sub_conjunto = []
        for cadena_en_loop in cad_d:
            distancias_euclidean_sub_conjunto.append((ch.distancia_minima_entre_cadenas( cadena_en_loop, ch_up), cadena_en_loop))

        distancias_euclidean_sub_conjunto.sort(key=lambda x: x[0])
        conjunto_de_cadenas_ordenadas += [(d , cad_d) for _,cad_d in distancias_euclidean_sub_conjunto]

    control = True
    if control:
        for _,cadena in conjunto_de_cadenas_ordenadas:
            puntos = [punto for punto in cadena.lista if punto.cadenaId != cadena.id]
            if len(puntos) > 0 :
                raise
    return conjunto_de_cadenas_ordenadas

def buscar_cadena_candidata_a_pegar(state, chain, S_up, S_up_no_inter, ch_up,
                                                             border, sentido='up',check_angle=True):
    label = 'buscar_cadena_candidata_a_pegar'
    # Quedarme unicamente con las cadenas cercanas segun cierta distancia maxima
    conjunto_de_cadenas_candidatas_cercanas = ordenar_cadenas_en_vecindad(state, S_up_no_inter, ch_up, border)
    largo_conjunto = len(conjunto_de_cadenas_candidatas_cercanas)
    if largo_conjunto == 0:
        return None
    if state.debug:
        write_log(MODULE_NAME, label,
                  f"cad.id {ch_up.label_id} border {border} conjunto_cadenas {[cad[1].label_id for cad in conjunto_de_cadenas_candidatas_cercanas]}")
    cadena_para_pegar = None
    next_id = 0
    while next_id < largo_conjunto:
        next_chain = conjunto_de_cadenas_candidatas_cercanas[next_id][1]
        valida, distancia = controles_de_verificacion(state, ch_up, next_chain, chain, border, S_up, sentido=sentido,
                                                      check_angle=check_angle)
        if valida:
            #busco todas las que intersectan a next_chain
            inter_next_chain = np.where(state.matriz_intersecciones[ch_up.id] == 1)[0]
            cadenas_intersectantes_next_chain = [cad[1] for cad in conjunto_de_cadenas_candidatas_cercanas if
                                           cad[1].id in inter_next_chain and next_chain.id != cad[1].id]

            #selecciono la que esta a menor distancia radial
            lista_cadenas_distancia_radial = [( next_chain, distancia)]
            for cad_inter in cadenas_intersectantes_next_chain:
                valida, distancia = controles_de_verificacion(state, ch_up, cad_inter, chain, border, S_up,
                                                              sentido=sentido, check_angle=check_angle)
                if valida:
                    lista_cadenas_distancia_radial.append((cad_inter,distancia))

            lista_cadenas_distancia_radial.sort(key= lambda x: x[1])
            cadena_para_pegar = lista_cadenas_distancia_radial[0][0]

            break

        next_id += 1

    return cadena_para_pegar




def verificar_extremos(chain,ch_up,next_chain,border,sentido,state):
    label="verificar_extremos"
    dominio_angular_cadena_soporte = chain._completar_dominio_angular(chain)
    ext_cad_1 = ch_up.extA if border in 'A' else ch_up.extB
    ext_cad_2 = next_chain.extB if border in 'A' else next_chain.extA
    dominio_de_interpolacion = calcular_dominio_de_interpolacion(border,ext_cad_1, ext_cad_2)
    interseccion = np.intersect1d(dominio_de_interpolacion,dominio_angular_cadena_soporte)
    return True if len(interseccion)==len(dominio_de_interpolacion) else False





def controles_de_verificacion( state, ch_up, next_chain, chain, border,  S_up, sentido='up', check_angle=True):

    label = "controles_de_verificacion"
    if state.debug:
        write_log(MODULE_NAME, label,
              f"cad.id {ch_up.label_id} border {border} cad.id {next_chain.label_id} cad_limite.id {chain.label_id} sentido {sentido}")
    # res = state.controles_de_verificacion_if_exist_get_results(chain, ch_up, next_chain, border)
    # if res is not None:
    #     return res

    #0. Criterio de size
    if ch_up.size + next_chain.size > ch_up.Nr:
         return (False,-1)

    #1. Extremo valido de interseccion
    distancia = -1
    valida = verificar_extremos(chain,ch_up,next_chain,border,sentido,state)

    if valida:
        if state.debug:
            write_log(MODULE_NAME, label,
                      f"check_extremos_validos PASS")
        valida_radial , distancia, inf_banda = criterio_distancia_radial(state, chain, ch_up, next_chain, border)
        valida_dist , distancia, inf_banda = criterio_distribucion_radial(state, chain, ch_up, next_chain, border)
        valida =  valida_radial or valida_dist


        if valida and inf_banda is not None:
            if state.debug:
                write_log(MODULE_NAME, label,
                          f"check_cummulative_radio PASS")
            valida = criterio_derivada_maxima(state, ch_up, next_chain, border, inf_banda.ptos_vituales,umbral=state.derivative_th)
            if valida:
                if state.debug:
                    write_log(MODULE_NAME, label,
                              f"check_angle_between_borders PASS")

                #validar que no se tengan cadenas entre ambas.
                hay_cadena = hay_cadenas_superpuestas(state,inf_banda)
                if not hay_cadena:
                    valida = True

                else:
                    valida = False

    res = state.controles_de_verificacion_add_data_to_hash_dict(chain, ch_up, next_chain, valida, distancia)
    return (valida,distancia)

def get_ids_chain_intersection(state,chain_id):
    ids_interseccion = list(np.where(state.matriz_intersecciones[chain_id] == 1)[0])
    ids_interseccion.remove(chain_id)
    return ids_interseccion



def get_lenght_forward(cadena_limite, angulo, extremo='A'):
    label = 'get_lenght_forward'
    dots_down = cadena_limite.sort_dots(sentido='antihorario') if extremo in 'B' else cadena_limite.sort_dots(
        sentido='horario')
    dot = [dot for dot in dots_down if dot.angulo == angulo]
    if len(dot) > 1 or len(dot) == 0:
        logging.error(
            f"{label}:  cad.id {cadena_limite.id} cadena limite tiene puntos con angulo repetido  o no tiene puntos")
        largo_down = -1
    else:
        dot_idx = dots_down.index(dot[0])
        largo_down = len(dots_down) - dot_idx

    return largo_down




def distancia_angular_entre_cadenas(cad_1,cad_2,border):
        label='distancia_angular_entre_cadenas'
        ext_cad_2 = cad_2.extB if border in 'A' else cad_2.extA
        ext_cad_1 = cad_1.extA if border in 'A' else cad_1.extB
        if border in 'B':
            if ext_cad_2.angulo > ext_cad_1.angulo:
                    distancia = ext_cad_2.angulo - ext_cad_1.angulo
            else:
                    distancia = ext_cad_2.angulo + (360 - ext_cad_1.angulo)

        else:

            if ext_cad_2.angulo > ext_cad_1.angulo:
                distancia = ext_cad_1.angulo + (360-ext_cad_2.angulo)

            else:
                distancia = ext_cad_1.angulo - ext_cad_2.angulo
        write_log(MODULE_NAME, label, f"cad.id {cad_1.label_id} cad.id {cad_2.label_id} distancia = {distancia} border {border}")
        return distancia




def distance_between_border(chain_1,chain_2,border_1):
    dot_1 = chain_1.extA if border_1 in 'A' else chain_2.extB
    dot_2 = chain_2.extB if border_1 in 'A' else chain_2.extA
    d = ch.distancia_entre_puntos(dot_1,dot_2)
    return d

def select_closest_chain(chain,a_neighbour_chain,b_neighbour_chain):
    if a_neighbour_chain is not None:
        d_a = distance_between_border(chain, a_neighbour_chain, 'A')
    else:
        d_a = -1
    
    if b_neighbour_chain is not None:
        d_b = distance_between_border(chain, b_neighbour_chain, 'B')
    else:
        d_b = -1
    
    if d_a>=d_b:
        closest_chain = a_neighbour_chain
    elif d_b>d_a:
        closest_chain = b_neighbour_chain
    else:
        closest_chain = None
    
    return closest_chain



def sort_list_idx(s):
    idx = sorted(range(len(s)), key=lambda k: s[k])
    return idx

def from_polar_to_cartesian_coordinates(angles,radials,centro):
    xx,yy = [],[]
    for ang,r in zip(angles,radials):
        angle_rad = ang*np.pi/180
        x = centro[1] + r * np.cos(angle_rad)
        y = centro[0] + r * np.sin(angle_rad)
        x = int(x)
        y = int(y)
        xx.append(x)
        yy.append(y)
    return yy,xx

def get_boundaries(xx,x):
    find = False
    for idx in range(1,len(xx)):
        a = xx[idx-1]
        b = xx[idx]
        if a<= x < b:
            find = True
            break
    
    if not find:
        if x < xx[0] or x>= xx[-1]:
            find = True
            idx = 0
    
    return idx if find else -1


def pol_ord_1(x,y,deg=1):
    coef = np.polyfit(x,y,deg=deg)
    pol = np.poly1d(coef)
    return pol

def lineal_by_part_local(xx,yy,x,debug=False):
    xx = list(xx)
    yy = list(yy)
    idx = get_boundaries(xx, x)
    if idx<0:
        raise
    a,b = xx[idx-1],xx[idx]

    
    f_a,f_b = yy[idx-1],yy[idx]
    if x == a:
        return f_a
    if x==b:
        return f_b
    if a>= b:
            
        a_p = 0
        b_p = b + 360-a
        x_p = x-a if a<x<360 else x + 360-a
        pol = pol_ord_1([a_p,b_p], [f_a,f_b])
        f_x = pol(x_p)
        if debug:
            plt.figure()
            plt.plot(xx, yy, '.')
            plt.vlines(a, min(yy), max(yy),colors='r')
            plt.vlines(b, min(yy), max(yy),colors='b')
            plt.vlines(x, min(yy), max(yy))
            plt.plot([a,b,x], [f_a,f_b,f_x], '.')


    else:
        pol = pol_ord_1([a,b], [f_a,f_b])
        f_x = pol(x)

    return f_x

def lineal_by_part(xx,yy,x_range,debug=False):
    y_range = []

    for x in x_range:
        y = lineal_by_part_local(xx,yy,x)
        if y<0:
            raise
        y_range.append(y)
    if debug:
        plt.figure()
        plt.plot(xx, yy, '.', x_range, y_range, '-')
    return np.array(y_range)


def inside_angle_interval(chain,angle):
    ret = False
    A = chain.extA.angulo
    B = chain.extB.angulo
    if A <= B:
        if  A<= angle <= B:
            ret = True
        else:
            ret = False
    else:
        if angle>= A or angle<=B:
            ret = True
        else:
            ret = False

    return ret

def check_duplicate_dots(lista_puntos):
    duplicate = None
    for dot in lista_puntos:
        if len([p for p in lista_puntos if p == dot])>1:

            duplicate = dot
            break
    return duplicate
def union_2_chains(s, cad_1, cad_2,border,S_up):
    se_pego = False
    if cad_2 is not None:
        if cad_1.id != cad_2.id:
            pegar_2_cadenas(s, cad_1, cad_2,border,S_up)
            se_pego = True
            s.remove_key_from_hash_dictionaries(s.chain,cad_1, cad_2)

    return se_pego




def get_all_dots_on_radial_direction_sorted_by_ascending_distance_to_center(listaPuntos,dot_direccion):
    lista_puntos_perfil = [dot for dot in listaPuntos if dot.angulo == dot_direccion.angulo]
    lista_puntos_perfil= sorted(lista_puntos_perfil, key=lambda x: x.radio, reverse=False)
    return lista_puntos_perfil




def get_chains_within_angle(angle,lista_cadenas):
    chains_list = []
    for chain in lista_cadenas:
        A = chain.extA.angulo
        B = chain.extB.angulo
        if ((A <= B and A<=angle<=B) or 
            (A>B and (A<= angle or angle<=B))): 
            chains_list.append(chain)
    
    return chains_list

def get_closest_chain_dot_to_angle(chain,angle):
    label='get_closest_chain_dot_to_angle'
    chain_dots = chain.sort_dots(sentido='antihorario')
    #return [dot for dot in chain_dots if dot.angulo == angle][0]
    A = chain.extA.angulo
    B = chain.extB.angulo
    dominio = chain._completar_dominio_angular(chain)
    if angle not in dominio:
        if np.abs(A-angle)>np.abs(B-angle):
            return chain.extB
        else:
            return chain.extA
    closest_dot = None
    if A<=B:
        for dot in chain_dots:
            if dot.angulo>=angle:
                closest_dot = dot
                break

    else:
        for dot in chain_dots:
            if ((A<=dot.angulo and angle>=A) or (B>= dot.angulo and angle<=B)):
                if dot.angulo>=angle:
                    closest_dot = dot
                    break
            elif B>= dot.angulo and angle>B:
                closest_dot = dot
                break
    if closest_dot is None:
        d1 = np.abs(B-angle)
        d2 = np.abs(A-angle)
        if d1> d2:
            closest_dot = chain.extA
        else:
            closest_dot = chain.extB
    #write_log(MODULE_NAME, label, f"cad.id {chain.id} angle {angle} A {A} B {B} closest {closest_dot}")
    return closest_dot
        


def sort_chain_list_by_neighboorhood(chain,listaCadenas):
    listaCadenas.sort(key=lambda x: x.size, reverse=True)

def get_up_and_down_chains(listaPuntos,listaCadenas,cadena,extremo):
    label='get_up_and_down_chains'
    dot_direccion = cadena.extA if extremo in 'A' else cadena.extB
    cadena_down = None
    cadena_up = None
    #cadena_down,down_distance = get_down_relative_to_chain(dot_direccion,listaCadenas)
    dot_chain_index, lista_puntos_perfil = get_dots_in_radial_direction(dot_direccion, listaCadenas)
    if  dot_chain_index < 0:
        return None, None, dot_direccion

    if  dot_chain_index > 0:
        down_dot = lista_puntos_perfil[dot_chain_index - 1]
        cadena_down = [cad for cad in listaCadenas if cad.id == down_dot.cadenaId]
        if len(cadena_down)>0:
            cadena_down = cadena_down[0]
        radial_distance_down = np.abs(down_dot.radio - dot_direccion.radio)

    # cadena_up,up_distance = get_up_relative_to_chain(dot_direccion,listaCadenas)
    if  len(lista_puntos_perfil)-1 > dot_chain_index:
        up_dot = lista_puntos_perfil[dot_chain_index + 1]
        cadena_up = [cad for cad in listaCadenas if cad.id == up_dot.cadenaId]
        if len(cadena_up)>0:
            cadena_up = cadena_up[0]
        radial_distance_up = np.abs(up_dot.radio - dot_direccion.radio)


    write_log(MODULE_NAME,label,f"cad.id {cadena.label_id} ext {extremo} arriba {cadena_up if cadena_up is not None else None} abajo {cadena_down if cadena_down is not None else None} ")
    return cadena_down,cadena_up,dot_direccion

def get_dots_in_radial_direction(dot_direccion,listaCadenas):
    label = 'get_dots_in_radial_direction'
    #write_log(MODULE_NAME,label,f"dot_direccion {dot_direccion}")
    chains_in_radial_direction = get_chains_within_angle(dot_direccion.angulo, listaCadenas)
    #write_log(MODULE_NAME, label, f"chains_in_radial_direction {chains_in_radial_direction}")
    lista_puntos_perfil = ch.get_closest_dots_to_angle_on_radial_direction_sorted_by_ascending_distance_to_center(chains_in_radial_direction,dot_direccion.angulo)
    # duplicate = check_duplicate_dots(lista_puntos_perfil)
    # if duplicate:
    #     print(duplicate)
    #     cad = [c for c in chains_in_radial_direction if c.id == duplicate.cadenaId][0]
    #     print(cad)
    #     if check_duplicate_dots(cad.lista):
    #         raise
    #     raise
    list_dot_chain_index = [idx for idx,dot in enumerate(lista_puntos_perfil) if dot.cadenaId == dot_direccion.cadenaId]
    if len(list_dot_chain_index)>0:
        dot_chain_index = list_dot_chain_index[0]
    else:
        lista_puntos_perfil = []
        dot_chain_index = -1

    return dot_chain_index, lista_puntos_perfil

def find_start_index(angle,chain,sentido):
    dot = get_closest_dots_to_angle_on_radial_direction_sorted_by_ascending_distance_to_center([chain],angle)[0]
    dots_list = chain.sort_dots(sentido=sentido)
    return dots_list.index(dot)

def buscar_punto_umbral_index_perfil(punto_umbral,listaPuntos):
    lista_puntos_perfil = [dot for dot in listaPuntos if dot.angulo == punto_umbral.angulo]
    lista_puntos_perfil = sorted(lista_puntos_perfil, key=lambda x: x.radio, reverse=False)
    punto_umbral_index = lista_puntos_perfil.index(punto_umbral)
    return punto_umbral_index,lista_puntos_perfil

def get_closest_dot_to_angle(chain,angle):
    argmin = np.abs(chain.getDotsAngles()-angle).argmin()
    return chain.lista[argmin]
def check_cumulative_radio(cadena,cadena_down_up,cadena_limite,extremo,umbral,debug=True):
    label='check_comulative_radio'


    #ordeno al revez.
    #sentido = 'antihorario' if extremo in 'A' else 'horario'
    #sorted_cadena_dots = cadena.sort_dots(sentido=sentido)
    cad_ext = cadena.extA if extremo in 'A' else cadena.extB
    
    #extremo opuesto.
    ext_candidata = cadena_down_up.extB if extremo in 'A' else cadena_down_up.extA
    if debug:
        write_log(MODULE_NAME,label,f"cad.id {cadena.label_id} extremo {extremo}"f" cad.id {cadena_down_up.label_id}   cad.id {cadena_limite.label_id} ext_candidata {ext_candidata}")
    limit_dot_ext_candidata = get_closest_dot_to_angle(cadena_limite, ext_candidata.angulo) #get_closest_dots_to_angle_on_radial_direction_sorted_by_ascending_distance_to_center([cadena_limite], ext_candidata.angulo)[0]
    limit_dot_orig_chain = get_closest_dot_to_angle(cadena_limite, cad_ext.angulo) #get_closest_dots_to_angle_on_radial_direction_sorted_by_ascending_distance_to_center([cadena_limite], cad_ext.angulo)[0]
    
    #try:
    radio_acumulado_candidata = ch.distancia_entre_puntos(ext_candidata,limit_dot_ext_candidata)
    radio_acumulado = ch.distancia_entre_puntos(cad_ext, limit_dot_orig_chain)
    # except Exception as e:
    #     write_log(MODULE_NAME,label,f" {e}\n Union de cadenas cruzara con otras",level='error')
    #     #ch.visualizarCadenasSobreDisco([cadena,cadena_down_up,cadena_limite],img,"Error Comulative Radio",labels=True)
    #     return False,-1

    inf_limit = np.floor(radio_acumulado*( 1 - umbral ))
    sup_limit = np.ceil(radio_acumulado*( 1 + umbral ))
    if debug:
        write_log(MODULE_NAME,label,f"inf_limit {inf_limit:0.3f}  radio acumulado candidata {radio_acumulado_candidata:0.3f}  sup_limit {sup_limit:0.3f} ")
    if  inf_limit <= radio_acumulado_candidata <= sup_limit:
        return True,np.abs(radio_acumulado_candidata - radio_acumulado)
    else:
        return False,-1


def actualizar_vecindad_cadenas_existentes_luego_de_pegado(state, extremo, cad_1, cad_2, update_border_chain_1=True):
    # if update_border_chain_1:
    #     if extremo in 'A':
    #         cad_1.A_up = cad_2.A_up
    #         cad_1.A_down = cad_2.A_down
    #     else:
    #         cad_1.B_up = cad_2.B_up
    #         cad_1.B_down = cad_2.B_down

    for cad in state.lista_cadenas:
        if cad.A_up is not None:
            if cad.A_up.id == cad_2.id:
                cad.A_up = cad_1
        if cad.A_down is not None:
            if cad.A_down.id == cad_2.id:
                cad.A_down = cad_1

        if cad.B_up is not None:
            if cad.B_up.id == cad_2.id:
                cad.B_up = cad_1

        if cad.B_down is not None:
            if cad.B_down.id == cad_2.id:
                cad.B_down = cad_1
    return 0
def pegar_2_cadenas(state,cad_1,cad_2,extremo,S_up,intersecciones=True,debug=False):
    label = 'pegar_2_cadenas'
    write_log(MODULE_NAME,label,
              f"cad.id {cad_1.label_id} con cad.id {cad_2.label_id} largoListaCadenas {len(state.lista_cadenas)}"
              f" largoListaPunto {len(state.lista_puntos)} cadenas "f"{ch.contarPuntosListaCadenas(state.lista_cadenas)}",debug=debug)

    # 1.0 identificar puntos
    lista_nuevos_puntos = []
    _, change_border = pegar_dos_cadenas_interpolando_via_cadena_soporte(state.chain, cad_1, cad_2, lista_nuevos_puntos, extremo,add=False)
    if change_border:
        state.actualizar_vecindad_cadenas_si_amerita([cad_1])
        #raise
    state.add_list_to_system(cad_1, lista_nuevos_puntos)

    #apuntar cadenas bordes del extremo
    actualizar_vecindad_cadenas_existentes_luego_de_pegado(state, extremo, cad_1, cad_2,not change_border )
    # remover cad_2  de lista_cadenas
    cad_2_index = state.lista_cadenas.index(cad_2)
    del state.lista_cadenas[cad_2_index]
    cadena_pegada_id = S_up.index(cad_2)
    del S_up[cadena_pegada_id]

    # actualizar matriz de intersecciones
    if intersecciones:
        inter_cad_1 = state.matriz_intersecciones[cad_1.id]
        inter_cad_2 = state.matriz_intersecciones[cad_2.id]
        or_inter_cad1_cad2 = np.logical_or(inter_cad_1,inter_cad_2)
        state.matriz_intersecciones[cad_1.id] = or_inter_cad1_cad2
        state.matriz_intersecciones[:, cad_1.id] = or_inter_cad1_cad2

        # solo remuevo una columna/fila porque la otra se actualiza
        state.matriz_intersecciones = np.delete(state.matriz_intersecciones,cad_2.id,1)
        state.matriz_intersecciones = np.delete(state.matriz_intersecciones,cad_2.id,0)

    # 5.0 actualizo id cadenas
    for cad_old in state.lista_cadenas:
        if cad_old.id > cad_2.id:
            new_id = cad_old.id-1
            cad_old.changeId(new_id)



    #################################################################
    if state.debug:
        write_log(MODULE_NAME, label,f"cad.id_l {cad_1.label_id} cad.id {cad_1.id} largoListaCadenas {len(state.lista_cadenas)} "
            f"largoListaPunto {len(state.lista_puntos)} cadenas {ch.contarPuntosListaCadenas(state.lista_cadenas)}", debug=debug)


    if DEBUG:
        chain = cad_1
        recorrer_s_down = recorrer_s_up = True
        S_up_lento, S_down_lento = recorrer_listas_algoritmo_lento(state, chain, recorrer_s_down, recorrer_s_up)
        S_up, S_down = recorrer_listas_algoritmo_rapido(state, chain, recorrer_s_down, recorrer_s_up)

        iguales = control_lista_iguales(S_down_lento, S_down)
        if not iguales:
            ch.visualizarCadenasSobreDiscoTodas([chain] + S_down, state.img, state.lista_cadenas, 'rapido', labels=True, save=state.path)
            ch.visualizarCadenasSobreDiscoTodas([chain] + S_down_lento, state.img, state.lista_cadenas, 'lento', labels=True,
                                                save=state.path)
            ch.visualizarCadenasSobreDiscoTodas([cad_2] , state.img, [], '2', labels=True,
                                                save=state.path)
            check_duplicate_dots(state.lista_puntos)
            raise

        iguales = control_lista_iguales(S_up_lento, S_up)
        if not iguales:
            ch.visualizarCadenasSobreDiscoTodas([chain] + S_up, state.img, state.lista_cadenas, 'rapido', labels=True, save=state.path)
            ch.visualizarCadenasSobreDiscoTodas([chain] + S_up_lento, state.img, state.lista_cadenas, 'lento', labels=True,
                                                save=state.path)
            raise

    return cad_1

def get_mode(A):
    if len(A)>0:
        mode = max(set(A), key = A.count)
    else:
        mode = -1
    return mode

def update_intersecciones(state,chain,nuevos_angulos):
    cadenas_id_intersectantes = []
    for angulo in nuevos_angulos:
        cadenas_id = [dot.cadenaId for dot in state.lista_puntos if dot.angulo == angulo and dot.cadenaId != chain.id]
        cadenas_id_intersectantes += cadenas_id
    cadenas_id_intersectantes = list(set(cadenas_id_intersectantes))
    state.matriz_intersecciones[ chain.id, cadenas_id_intersectantes] = 1



def llenar_angulos(extA, extB):
    step = 360/extA.Nr
    if extA.angulo < extB.angulo:
        rango = np.arange(extA.angulo, extB.angulo + step)
    else:
        rango1 = np.arange(extA.angulo, 360)
        rango2 = np.arange(0, extB.angulo + step)
        rango = np.hstack((rango2, rango1))
    # print(rango)
    return rango.astype(int)

def cadenas_se_intersectan(cadena1, cadena2, costo=False):

    tabla = np.zeros(cadena1.Nr)
    # dominioAngular1 = cadena1.getDotsAngles()
    dominioAngular1 = llenar_angulos(cadena1.extA, cadena1.extB)
    for angulo in dominioAngular1:
       idx_tabla = angulo * cadena1.Nr//360
       tabla[idx_tabla] = 1
    # dominioAngular2 = cadena2.getDotsAngles()
    dominioAngular2 = llenar_angulos(cadena2.extA, cadena2.extB)
    pos_intersect = np.where(tabla[dominioAngular2 * cadena1.Nr //360] > 0)[0]
    # hay cadenas que se intersectan en los extremos. No son el mismo punto
    # pero el angulo debido al redondeo si lo es.
    if pos_intersect.shape[0] > 0:
        return True
    return False

def calcular_matriz_intersecciones_old(listaCadenas, costo=False, debug=False):
    #M_int = np.zeros((len(listaCadenas), len(listaCadenas)))
    M_int = np.eye(len(listaCadenas))
    for i in range(M_int.shape[0]):
        cad_i = [cad for cad in listaCadenas if cad.id == i][0]

        for j in range(M_int.shape[0]):
            cad_j = [cad for cad in listaCadenas if cad.id == j][0]
            if cad_i.id != cad_j.id:
                if cadenas_se_intersectan(cad_i, cad_j, costo=costo):
                    M_int[i, j] = 1
                    M_int[j, i] = 1

    return M_int

def calcular_matriz_intersecciones(listaCadenas, listaPuntos,Nr, debug=False):

    M_int = np.eye(len(listaCadenas))
    for angulo in np.arange(0,360,360/Nr):
        cadenas_ids_en_direccion = np.unique([punto.cadenaId for punto in listaPuntos if punto.angulo == angulo])
        x,y = np.meshgrid(cadenas_ids_en_direccion,cadenas_ids_en_direccion)
        M_int[x,y] = 1

    return M_int

############### criterio celdas


def get_puntos_lista_cadenas(lista_cadenas):
    puntos_lista = []
    for cadena in lista_cadenas:
        puntos_lista += cadena.lista
    return puntos_lista



def buscar_distancia_maxima_entre_cadena_soporte_y_conjunto_inicial(S_sub, chain, img, debug=True ):
    distancias_a_cadena_soporte = []
    pareja_puntos = []
    lista_puntos_cadenas_conjunto = get_puntos_lista_cadenas(S_sub)
    img_segmentos = img.copy() if debug else None

    for punto in chain.lista:
        punto_direccion = [punto_cand for punto_cand in lista_puntos_cadenas_conjunto if punto_cand.angulo == punto.angulo]
        if len(punto_direccion) == 0:
            continue

        punto_direccion = punto_direccion[0]
        distancias_a_cadena_soporte.append(ch.distancia_entre_puntos(punto_direccion,punto))
        pareja_puntos.append((punto_direccion, punto))
        if debug:
            img_segmentos = dibujar_segmentoo_entre_puntos(punto_direccion, punto, img_segmentos)

    if len(distancias_a_cadena_soporte)==0:
        return  -1, img

    maxima_distancia = np.max(distancias_a_cadena_soporte)
    pareja_maxima = pareja_puntos[np.argmax(distancias_a_cadena_soporte)]
    if debug:
        img_segmentos = dibujar_segmentoo_entre_puntos(pareja_maxima[0], pareja_maxima[1], img_segmentos, color=ROJO)

    return maxima_distancia, img_segmentos

def buscar_subconjunto_cadenas_en_region_delimitada_por_maxima_distancia(state,chain, maxima_distancia, sentido):
    id_cadenas_en_region = []
    for punto in chain.lista:
        lista_de_puntos_en_radio = [pto_radio for pto_radio in state.lista_puntos if pto_radio.angulo == punto.angulo]
        if len(lista_de_puntos_en_radio)==0:
            continue
        if sentido in 'up':
            lista_de_puntos_en_radio_filtrado_sentido = [pto_radio for pto_radio in lista_de_puntos_en_radio if pto_radio.radio>punto.radio]
        else:
            lista_de_puntos_en_radio_filtrado_sentido = [pto_radio for pto_radio in lista_de_puntos_en_radio if
                                                 pto_radio.radio < punto.radio]

        lista_de_puntos_en_radio_filtrado_sentido_menor_distancia_maxima = [pto_radio for pto_radio in
                        lista_de_puntos_en_radio_filtrado_sentido if ch.distancia_entre_puntos(pto_radio,punto) < maxima_distancia]

        id_cadenas_en_region+= [pto_radio.cadenaId for pto_radio in lista_de_puntos_en_radio_filtrado_sentido_menor_distancia_maxima]

    id_cadenas_en_region = np.unique(id_cadenas_en_region).tolist()
    cadenas_en_region = [cadena for cadena in state.lista_cadenas if cadena.id in id_cadenas_en_region]
    return cadenas_en_region



def buscar_cadenas_faltantes_si_amerita(state,sentido, S_sub, chain, debug=False,img=False):
    maxima_distancia, img_segmentos = buscar_distancia_maxima_entre_cadena_soporte_y_conjunto_inicial(S_sub, chain, state.img.copy(), debug=debug)
    if maxima_distancia < 0:
        return []

    if debug:
        ch.visualizarCadenasSobreDiscoTodas([chain] + S_sub , img_segmentos,[], f'{state.iteracion}_subconjunto_cadenas_inicio_radios',
                                       labels=False, save=str(state.path))
        state.iteracion +=1

    cadenas_en_region = buscar_subconjunto_cadenas_en_region_delimitada_por_maxima_distancia(state, chain, maxima_distancia, sentido)
    if debug:
        ch.visualizarCadenasSobreDiscoTodas([chain] + cadenas_en_region , state.img.copy(),[],
                        f'{state.iteracion}_subconjunto_cadenas_inicio_distancia_maxima', labels=True, save=str(state.path))
        state.iteracion+=1

    #S_sub = cadenas_en_region
    return cadenas_en_region
