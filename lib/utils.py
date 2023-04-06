#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Sun Feb  7 12:01:24 2021

@author: henry
"""
import imageio
import os
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt
import time
import pandas as pd
from PIL import Image
import re
import logging 
from typing import List

from lib.io import write_json, load_config
import lib.chain as ch
from lib.preprocessing import resize



def save_config(args, root_path, output_dir):
    config = load_config()

    config['result_path'] = output_dir

    if args.nr:
        config['nr'] = args.nr

    if args.hsize and args.wsize:
        if args.hsize>0 and args.wsize>0:
            config['resize'] = [args.hsize, args.wsize]

    if args.min_chain_length:
        config["min_chain_lenght"] = args.min_chain_length

    if args.edge_th:
        config["edge_th"] = args.edge_th

    if args.sigma:
        config['sigma'] = args.sigma

    if args.th_high:
        config['th_high'] = args.th_high

    if args.th_low:
        config['th_low'] = args.th_low

    if args.debug:
        config['debug'] = True

    config['devernay_path'] = str(Path(root_path) / "externas/devernay_1.0")

    write_json(config, Path(root_path) / 'config/general.json')

    return 0
def saving_results( res, output_dir, save_imgs=True):
    im_seg, im_pre, ch_e, ch_f, ch_s, ch_c, ch_p, rings = res
    write_json(rings, f"{output_dir}/labelme.json")
    if not save_imgs:
        return
    M,N,_ = im_seg.shape
    M_n, N_n = im_pre.shape
    if M != M_n:
        im_seg,_,_ = resize(im_seg, M_n, N_n)
    ch.visualize_chains_over_image(img=im_seg, filename=f"{output_dir}/segmentation.png")
    ch.visualize_chains_over_image(img=im_pre, filename=f"{output_dir}/preprocessing.png")
    ch.visualize_chains_over_image(img=im_pre, filename=f"{output_dir}/edges.png", devernay=ch_e)
    ch.visualize_chains_over_image(img=im_pre, filename=f"{output_dir}/filter.png", filter=ch_f)
    ch.visualize_chains_over_image(chain_list=ch_s, img=im_seg, filename=f"{output_dir}/chains.png")
    ch.visualize_chains_over_image(chain_list=ch_c, img=im_seg, filename=f"{output_dir}/connect.png")
    ch.visualize_chains_over_image(chain_list=ch_p, img=im_seg, filename=f"{output_dir}/postprocessing.png")
    ch.visualize_chains_over_image(chain_list=[chain for chain in ch_p if chain.is_full() and chain.type not in
        [ ch.TypeChains.center, ch.TypeChains.border] ], img=im_seg, filename=f"{output_dir}/output.png")


    return


def chain_2_labelme_json(chain_list: List[ch.Chain], image_height, image_width, cx, cy, img_orig, image_path,
                         exec_time):
    """
    Converting chain list object to labelme format. This format is used to store the coordinates of the rings at the image
    original resolution
    @param chain_list: chain list
    @param image_path: image input path
    @param image_height: image hegith
    @param image_width: image width_output
    @param img_orig: input image
    @param exec_time: method execution time
    @param cy: pith y's coordinate
    @param cx: pith x's coordinate
    @return:
    - labelme_json: json in labelme format. Ring coordinates are stored here.
    """
    init_height, init_width, _ = img_orig.shape
    completed_chains = [chain for chain in chain_list if chain.is_full() and  chain.type not in [ ch.TypeChains.center, ch.TypeChains.border]]



    width_cte = init_width / image_width if image_width is not 0 else 1
    height_cte = init_height / image_height if image_height is not 0 else 1
    labelme_json = {"imagePath":image_path, "imageHeight":None,
                    "imageWidth":None, "version":"5.0.1",
                    "flags":{},"shapes":[],"imageData": None, 'exec_time(s)':exec_time,'center':[cy*height_cte, cx*width_cte]}
    for idx, chain in enumerate(completed_chains):
        ring = {"label":str(idx+1)}
        ring["points"] = [[node.x*width_cte,node.y*height_cte] for node in chain.nodes_list]
        ring["shape_type"]="polygon"
        ring["flags"]={}
        labelme_json["shapes"].append(ring)

    return labelme_json



def setup_log(nroImagen,VERSION):
    logname = f"./logs/{nroImagen}.log"
    if Path(logname).exists():
        os.remove(logname)
    logging.basicConfig(
        filename=logname,
        filemode="a",
        format="%(asctime)s,%(msecs)d %(name)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
        level=logging.INFO,
    )
    
    
    logger = logging.getLogger(f"{VERSION}")
    logger.setLevel(logging.INFO)
    logging.info("Init")

    return logger

def write_log(module_name,function,message,level='info',debug=False):
    if debug:
        string = f"[{module_name}][{function}] {message}"
        if level in 'info':
            logging.info(string)
        else:
            logging.error(string)





