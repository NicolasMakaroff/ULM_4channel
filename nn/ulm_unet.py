from collections import OrderedDict

import torch
import torch.nn as nn
import numpy as np

import pytorch_lightning as pl

import wandb

l2loss = nn.MSELoss(reduction='mean')

class ULM_UNet(pl.LightningModule):

    def __init__(self, in_channels=1, out_channels=3, init_features=16):
        super(ULM_UNet, self).__init__()

        features = init_features
        self.encoder1 = ULM_UNet._block(in_channels, features, name="enc1")
        self.pool1 = nn.MaxPool2d(kernel_size=2, stride=2)
        self.encoder2 = ULM_UNet._block(features, features * 2, name="enc2")
        self.pool2 = nn.MaxPool2d(kernel_size=2, stride=2)
        self.encoder3 = ULM_UNet._block(features * 2, features * 4, name="enc3")
        self.pool3 = nn.MaxPool2d(kernel_size=2, stride=2)
        self.encoder4 = ULM_UNet._block(features * 4, features * 8, name="enc4")
        self.pool4 = nn.MaxPool2d(kernel_size=2, stride=2)

        self.bottleneck = ULM_UNet._block(features * 8, features * 16, name="bottleneck")

        self.upconv4 = nn.ConvTranspose2d(
            features * 16, features * 8, kernel_size=2, stride=2
        )
        self.decoder4 = ULM_UNet._block((features * 8) * 2, features * 8, name="dec4")
        self.upconv3 = nn.ConvTranspose2d(
            features * 8, features * 4, kernel_size=2, stride=2
        )
        self.decoder3 = ULM_UNet._block((features * 4) * 2, features * 4, name="dec3")
        self.upconv2 = nn.ConvTranspose2d(
            features * 4, features * 2, kernel_size=2, stride=2
        )
        self.decoder2 = ULM_UNet._block((features * 2) * 2, features * 2, name="dec2")
        self.upconv1 = nn.ConvTranspose2d(
            features * 2, features, kernel_size=2, stride=2
        )
        self.decoder1 = ULM_UNet._block(features * 2, features, name="dec1")

        self.conv = nn.Conv2d(
            in_channels=features, out_channels=out_channels, kernel_size=1
        )
        
    def forward(self, x):

        enc1 = self.encoder1(x)
        enc2 = self.encoder2(self.pool1(enc1))
        enc3 = self.encoder3(self.pool2(enc2))
        enc4 = self.encoder4(self.pool3(enc3))

        bottleneck = self.bottleneck(self.pool4(enc4))

        dec4 = self.upconv4(bottleneck)
        dec4 = torch.cat((dec4, enc4), dim=1)
        dec4 = self.decoder4(dec4)
        dec3 = self.upconv3(dec4)
        dec3 = torch.cat((dec3, enc3), dim=1)
        dec3 = self.decoder3(dec3)
        dec2 = self.upconv2(dec3)
        dec2 = torch.cat((dec2, enc2), dim=1)
        dec2 = self.decoder2(dec2)
        dec1 = self.upconv1(dec2)
        dec1 = torch.cat((dec1, enc1), dim=1)
        dec1 = self.decoder1(dec1)
        return self.conv(dec1)

    @staticmethod
    def _block(in_channels, features, name):
        return nn.Sequential(
            OrderedDict(
                [
                    (
                        name + "conv1",
                        nn.Conv2d(
                            in_channels=in_channels,
                            out_channels=features,
                            kernel_size=3,
                            stride=1,
                            padding=1,
                            bias=False,
                        ),
                    ),
                    (name + "norm1", nn.BatchNorm2d(num_features=features)),
                    (name + "relu1", nn.ReLU(inplace=True)),
                    (
                        name + "conv2",
                        nn.Conv2d(
                            in_channels=features,
                            out_channels=features,
                            kernel_size=3,
                            stride=1,
                            padding=1,
                            bias=False,
                        ),
                    ),
                    (name + "norm2", nn.BatchNorm2d(num_features=features)),
                    (name + "relu2", nn.ReLU(inplace=True)),
                ]
            )
        )

    def configure_optimizers(self):
        optimizer = torch.optim.Adam(self.parameters(), lr=1e-4)
        return optimizer

    def training_step(self, batch, batch_idx):

        x, y_true = batch['image'].unsqueeze(1), batch['landmarks'].squeeze(1)
        y_pred = self(x)
        loss = l2loss(y_pred,y_true)
        logs={"train_loss": loss}
        batch_dictionary={
            "loss": loss,
            "log": logs,
        }
        self.log('loss', loss, prog_bar = False, on_step=False,on_epoch=True,logger=True)

        return loss

    def validation_step(self, batch, batch_idx):
        x, y = batch['image'].unsqueeze(1), batch['landmarks'].squeeze(1)
        y_hat = self(x)
        loss = l2loss(y_hat,y)
        self.log('val_loss',loss, prog_bar=False, on_step=False,on_epoch=True, logger=True)
        return loss

def wb_mask(bg_img, pred_mask, true_mask):

    """class_labels = {
        0: 'endpoint',
        1: 'biffurcation',
        2: 'crossing',
    }"""

    return wandb.Image(bg_img, masks={
        "prediction" : {
            "mask_data" : pred_mask
        },
        "ground truth" : {
            "mask_data" : true_mask
            }
        })

def gray2rgb(image):
    w, h = image.shape
    image += np.abs(np.min(image))
    image_max = np.abs(np.max(image))
    if image_max > 0:
        image /= image_max
    ret = np.empty((w, h, 3), dtype=np.uint8)
    ret[:, :, 2] = ret[:, :, 1] = ret[:, :, 0] = image * 255
    return ret

class ImagePredictionLogger(pl.Callback):
    def __init__(self, val_samples, num_samples=10):
        super().__init__()
        self.val_imgs, self.val_labels = val_samples['image'].unsqueeze(1), val_samples['landmarks'].squeeze(1)
        self.val_imgs = self.val_imgs[:num_samples]
        self.val_labels = self.val_labels[:num_samples]
          
    def on_validation_epoch_end(self, trainer, pl_module):
        val_imgs = self.val_imgs.to(device=pl_module.device)

        logits = pl_module(val_imgs)

        mask_list = []
        
        for original_image, logits, ground_truth in zip(val_imgs, logits, self.val_labels):
            # the raw background image as a numpy array
            #bg_image = image2np(original_image.data)
            print(original_image.shape)
            bg_image = gray2rgb(original_image.squeeze(0).cpu().numpy()).astype(np.uint8)
            # run the model on that image
            #prediction = pl_module(original_image)[0]

            prediction_mask = np.sum(logits.data.cpu().permute(1,2,0).numpy().astype(np.uint8),axis=2)

            # ground truth mask
            true_mask = np.sum(ground_truth.data.cpu().permute(1,2,0).numpy().astype(np.uint8),axis=2)
            # keep a list of composite images

            mask_list.append(wb_mask(bg_image, prediction_mask, true_mask))

        # log all composite images to W&B'''
        wandb.log({"predictions" : mask_list})