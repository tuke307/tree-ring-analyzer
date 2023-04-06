#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Apr 18 11:18:32 2022

@author: henry
"""
import cv2
import os
import numpy as np
import pandas as pd
from pathlib import Path

from lib.io import load_config
from lib.drawing import Drawing

def load_curves(output_txt):
    curves_list = pd.read_csv(output_txt, delimiter=" ", header=None).values
    return curves_list
def convert_image_to_pgm(im_pre):
    config = load_config(default=False)
    image_path = Path(config.get("result_path")) / f"test.pgm"
    cv2.imwrite(str(image_path), im_pre)
    return config, image_path
def write_curves_to_image(curves_list, img):
    img_aux = np.zeros(( img.shape[0], img.shape[1])) + 255
    for pix in curves_list:
        if pix[0]<0 and pix[1]<0:
            continue
        img_aux = Drawing.circle(img_aux, (int(pix[0]),int(pix[1])))
    return img_aux
def delete_files(files):
    for file in files:
        os.system(f"rm {file}")

def gradient_load( img, gx_path, gy_path):
    Gx = np.zeros_like(img).astype(float)
    Gy = np.zeros_like(img).astype(float)
    Gx[1:-1, 1:-1] = pd.read_csv(gx_path, delimiter=" ", header=None).values.T
    Gy[1:-1, 1:-1] = pd.read_csv(gy_path, delimiter=" ", header=None).values.T
    return Gx, Gy

def execute_command(config, image_path, sigma, low, high):
    root_path = Path(config.get("devernay_path"))
    results_path = Path(config.get("result_path"))
    output_txt = results_path / f"output.txt"
    gx_path = results_path / f"gx.txt"
    gy_path = results_path / f"gy.txt"
    command = f"{str(root_path)}/devernay  {image_path} -s {sigma} -l {low} -h {high} -t {output_txt} " \
              f" -x {gx_path} -y {gy_path}"
    os.system(command)

    return gx_path, gy_path, output_txt
def canny_deverney_edge_detector(im_pre, sigma, low, high):
    """
    Canny edge detector module. Algorithm: A Sub-Pixel Edge Detector: an Implementation of the Canny/Devernay Algorithm,
    source code downloaded from https://doi.org/10.5201/ipol.2017.216
    @param im_pre: preprocessed image.
    @param sigma: edge detection gaussian filtering
    @param low: gradient threshold low
    @param high: gradient threshold high
    @return:
    - ch_e_matrix: devernay curves
    - Gx: gradient image over x direction
    - Gy: gradient image over y direction
    """
    config, im_path = convert_image_to_pgm(im_pre)
    gx_path, gy_path, output_txt = execute_command(config, im_path, sigma, low, high)
    Gx, Gy = gradient_load(im_pre, gx_path, gy_path)
    ch_e_matrix = load_curves(output_txt)
    delete_files([output_txt, im_path, gx_path, gy_path])
    return ch_e_matrix, Gx, Gy
