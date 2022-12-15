import matplotlib.pyplot as plt
import torch.nn as nn
import torch
import time
from torch.utils.mobile_optimizer import optimize_for_mobile
import os
import numpy as np

freq_bin_high = 33

seg_len_mic = 640
overlap_mic = 256
seg_len_imu = 64
overlap_imu = 32

def noise_extraction(time_bin):
    noise_list = os.listdir('../dataset/noise/')
    index = np.random.randint(0, len(noise_list))
    noise_clip = np.load('../dataset/noise/' + noise_list[index])
    index = np.random.randint(0, noise_clip.shape[1] - time_bin)
    return noise_clip[:, index:index + time_bin]

def synthetic(clean, transfer_function):
    time_bin = clean.shape[-1]
    index = np.random.randint(0, N)
    f = transfer_function[index, 0]
    v = transfer_function[index, 1]
    response = np.tile(np.expand_dims(f, axis=1), (1, time_bin))
    for j in range(time_bin):
        response[:, j] += np.random.normal(0, v, (freq_bin_high))
    acc = clean[..., :freq_bin_high, :] * response
    # background_noise = noise_extraction(time_bin)
    # noisy += 2 * background_noise
    return acc

class IMU_branch(nn.Module):
    def __init__(self, inference=False):
        super(IMU_branch, self).__init__()
        self.conv1 = nn.Sequential(
            nn.Conv2d(1, 16, kernel_size=(3, 3), padding=(1, 1)),
            nn.BatchNorm2d(16),
            nn.ReLU(inplace=True))
        self.conv2 = nn.Sequential(
            nn.Conv2d(16, 32, kernel_size=(3, 3), padding=(2, 1), dilation=(2, 1)),
            #nn.MaxPool2d(kernel_size=(2, 1)),
            nn.BatchNorm2d(32),
            nn.ReLU(inplace=True))
        self.conv3 = nn.Sequential(
            nn.Conv2d(32, 64, kernel_size=(3, 3), padding=(2, 1), dilation=(2, 1)),
            nn.MaxPool2d(kernel_size=(2, 1)),
            nn.BatchNorm2d(64),
            nn.ReLU(inplace=True))
        self.conv4 = nn.Sequential(
            nn.Conv2d(64, 128, kernel_size=(3, 3), padding=(2, 1), dilation=(2, 1)),
            nn.MaxPool2d(kernel_size=(2, 1)),
            nn.BatchNorm2d(128),
            nn.ReLU(inplace=True))
        self.inference = inference
        if not inference:
            self.conv5 = nn.Sequential(
                nn.Conv2d(128, 64, kernel_size=(3, 3), padding=(1, 1)),
                #nn.ConvTranspose2d(64, 64, kernel_size=(2, 1), stride=(2, 1)),
                nn.BatchNorm2d(64),
                nn.ReLU(inplace=True))
            self.conv6 = nn.Sequential(
                nn.Conv2d(64, 32, kernel_size=(3, 3), padding=(1, 1)),
                nn.ConvTranspose2d(32, 32, kernel_size=(2, 1), stride=(2, 1)),
                nn.BatchNorm2d(32),
                nn.ReLU(inplace=True))
            self.conv7 = nn.Sequential(
                nn.Conv2d(32, 16, kernel_size=(3, 3), padding=(1, 1)),
                nn.ConvTranspose2d(16, 16, kernel_size=(2, 1), stride=(2, 1)),
                nn.BatchNorm2d(16),
                nn.ReLU(inplace=True))
            self.final = nn.Conv2d(16, 1, kernel_size=1)
    def forward(self, x):
        # down-sample
        x = self.conv1(x)
        x = self.conv2(x)
        x = self.conv3(x)
        x_mid = self.conv4(x)
        # up-sample with supervision
        if not self.inference:
            x = self.conv5(x_mid)
            x = self.conv6(x)
            x = self.conv7(x)
            x = self.final(x)
            return x_mid, x
        else:
            return x_mid

class Audio_branch(nn.Module):
    def __init__(self):
        super(Audio_branch, self).__init__()
        self.conv1 = nn.Sequential(
            nn.Conv2d(1, 16, kernel_size=3, padding=1),
            nn.MaxPool2d(kernel_size=(2, 1)),
            nn.BatchNorm2d(16),
            nn.ReLU(inplace=True),
        )
        self.conv2 = nn.Sequential(
            nn.Conv2d(16, 32, kernel_size=5, padding=4, dilation=2),
            nn.MaxPool2d(kernel_size=(2, 1)),
            nn.BatchNorm2d(32),
            nn.ReLU(inplace=True)
            )
        self.conv3 = nn.Sequential(
            nn.Conv2d(32, 64, kernel_size=5, padding=4, dilation=2),
            nn.MaxPool2d(kernel_size=(2, 1)),
            nn.BatchNorm2d(64),
            nn.ReLU(inplace=True)
            )
        self.conv4 = nn.Sequential(
            nn.Conv2d(64, 128, kernel_size=5, padding=2, dilation=1),
            nn.MaxPool2d(kernel_size=(2, 1)),
            nn.BatchNorm2d(128),
            nn.ReLU(inplace=True),
            )
        self.conv5 = nn.Sequential(
            nn.Conv2d(128, 256, kernel_size=5, padding=2, dilation=1),
            nn.MaxPool2d(kernel_size=(2, 1)),
            nn.BatchNorm2d(256),
            nn.ReLU(inplace=True),
            )
    def forward(self, x):
        x1 = self.conv1(x)
        x2 = self.conv2(x1)
        x3 = self.conv3(x2)
        x4 = self.conv4(x3)
        x5 = self.conv5(x4)
        return [x1, x2, x3, x4, x5]

class Residual_Block(nn.Module):
    def __init__(self, in_channels):
        super(Residual_Block, self).__init__()
        self.r1 = nn.Sequential(
            nn.Conv2d(in_channels, 128, kernel_size=5, padding=2, dilation=1),
            nn.ConvTranspose2d(128, 128, kernel_size=(2, 1), stride=(2, 1)),
            nn.BatchNorm2d(128),
            nn.ReLU(inplace=True))
        self.r2 = nn.Sequential(
            nn.Conv2d(256, 64, kernel_size=5, padding=2, dilation=1),
            nn.ConvTranspose2d(64, 64, kernel_size=(2, 1), stride=(2, 1)),
            nn.BatchNorm2d(64),
            nn.ReLU(inplace=True))
        self.r3 = nn.Sequential(
            nn.Conv2d(128, 32, kernel_size=5, padding=4, dilation=2),
            nn.ConvTranspose2d(32, 32, kernel_size=(2, 1), stride=(2, 1)),
            nn.BatchNorm2d(32),
            nn.ReLU(inplace=True))
        self.r4 = nn.Sequential(
            nn.Conv2d(64, 16, kernel_size=5, padding=4, dilation=2),
            nn.ConvTranspose2d(16, 16, kernel_size=(2, 1), stride=(2, 1)),
            nn.BatchNorm2d(16),
            nn.ReLU(inplace=True))
        self.final = nn.Sequential(
            nn.Conv2d(32, 16, kernel_size=3, padding=1),
            nn.ConvTranspose2d(16, 1, kernel_size=(2, 1), stride=(2, 1)),
            nn.Sigmoid()
            )
    def forward(self, acc, audios):

        [x1, x2, x3, x4, x5] = audios
        x = torch.cat([acc, x5], dim=1)
        x = torch.cat([self.r1(x), x4], dim=1)
        x = torch.cat([self.r2(x), x3], dim=1)
        x = torch.cat([self.r3(x), x2], dim=1)
        x = torch.cat([self.r4(x), x1], dim=1)
        x = self.final(x)
        return x

class A2net(nn.Module):
    def __init__(self, inference=False):
        super(A2net, self).__init__()
        self.inference = inference
        self.IMU_branch = IMU_branch(self.inference)
        self.Audio_branch = Audio_branch()
        self.Residual_block = Residual_Block(384)

        self.transfer_function = np.load('transfer_function_EMSB_32.npy')

    def forward(self, noisy, acc=None):
        # Preprocessing
        if acc == None:
            acc = synthetic(torch.abs(noisy), self.transfer_function)
        acc = acc / torch.max(acc)

        acc = self.IMU_branch(acc)
        if self.inference:
            x = self.Residual_block(acc, self.Audio_branch(noisy)) * noisy
            return x
        else:
            acc, x_extra = acc
            x = self.Residual_block(acc, self.Audio_branch(noisy)) * noisy
            return x, x_extra

def model_size(model):
    param_size = 0
    for param in model.parameters():
        param_size += param.nelement() * param.element_size()
    buffer_size = 0
    for buffer in model.buffers():
        buffer_size += buffer.nelement() * buffer.element_size()
    size_all_mb = (param_size + buffer_size) / 1024 ** 2
    return size_all_mb

def model_save(model):
    model.eval()
    x = torch.rand((1, 1, 32, 250))
    noise = torch.rand((1, 1, 256, 250))
    scripted_module = torch.jit.trace(model, [x, noise])
    #scripted_module.save("inference.pt")
    optimized_scripted_module = optimize_for_mobile(scripted_module)
    optimized_scripted_module._save_for_lite_interpreter("vibvoice.ptl")
def model_speed(model, input):
    t_start = time.time()
    step = 100
    with torch.no_grad():
        for i in range(step):
            model(*input)
    return (time.time() - t_start)/step
if __name__ == "__main__":

    acc = torch.rand(1, 1, 32, 250)
    audio = torch.rand(1, 1, 256, 250)
    model = A2net(inference=False)
    audio, acc = model(audio)
    print(audio.shape, acc.shape)

    # size_all_mb = model_size(model)
    # print('model size: {:.3f}MB'.format(size_all_mb))

    latency = model_speed(model, [audio])
    # print('model latency: {:.3f}S'.format(latency))

    #model_save(model)
