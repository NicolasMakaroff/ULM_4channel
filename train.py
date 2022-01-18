import argparse
import os

import numpy as np
import torch
from torch.utils.data import DataLoader
from torchvision import transforms

from utils.dataset import ULMDataset
from utils.transforms import RandomCrop, Rescale, ToTensor, HeatMap
from nn.ulm_unet import ULM_UNet, ImagePredictionLogger

import pytorch_lightning
from pytorch_lightning import Trainer
from pytorch_lightning import loggers as pl_loggers
from pytorch_lightning.plugins import DDPPlugin
import matplotlib.pyplot as plt
import time

import wandb 
from pytorch_lightning.loggers import WandbLogger




def main(args,seed):

    train_dataset = ULMDataset(root_dir='./data/train_images', transform=transforms.Compose([Rescale(256), HeatMap(), ToTensor()]))
    trainloader = DataLoader(train_dataset, batch_size=1, shuffle=True, num_workers=4)

    validation_dataset = ULMDataset(root_dir='./data/val_images', transform=transforms.Compose([Rescale(256), HeatMap(), ToTensor()]))
    valloader = DataLoader(validation_dataset, batch_size=10, shuffle=False, num_workers=4)

    wandb.login()
    wandb.init()
    wandb_logger = WandbLogger(project="ULM_4CHANNEL")

    model = ULM_UNet()
    samples = next(iter(valloader))

    trainer = Trainer(
        #gpus=[0],
        #num_nodes=2,
        #accelerator='ddp',
        #plugins=DDPPlugin(find_unused_parameters=False),
        logger = wandb_logger,
        #progress_bar_refresh_rate=0,
        max_epochs=100,
        #benchmark=True,
        check_val_every_n_epoch=1,
        callbacks=[ImagePredictionLogger(samples)]
    )

    trainer.fit(model,trainloader,valloader)

if __name__ == '__main__':
    parser = argparse.ArgumentParser( description="Training U-Net model for segmentation of brain MRI")
    parser.add_argument("--batch-size", type=int, default=16, help="input batch size for training (default: 16)")
    parser.add_argument("--epochs", type=int, default=100, help="number of epochs to train (default: 100)")
    parser.add_argument("--lr", type=float, default=0.0001, help="initial learning rate (default: 0.001)")
    parser.add_argument("--device", type=str, default="cuda:0", help="device for training (default: cuda:0)")
    parser.add_argument("--workers",type=int,default=1, help="number of workers for data loading (default: 4)")
    parser.add_argument("--weights", type=str, default="./weights", help="folder to save weights")
    parser.add_argument("--images", type=str, default="./data/kaggle_3m", help="root folder with images")
    parser.add_argument("--image-size",type=int,default=64,help="target input image size (default: 256)")
    parser.add_argument("--aug-scale",type=int,default=0.05,help="scale factor range for augmentation (default: 0.05)")
    parser.add_argument("--aug-angle",type=int,default=15,help="rotation angle range in degrees for augmentation (default: 15)")
    args = parser.parse_args()

    main(args,42)

