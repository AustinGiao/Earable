import os
import matplotlib.pyplot as plt
import torch
torch.manual_seed(0)
import torch.utils.data as Data
from dataset import NoisyCleanSet
import json

from fullsubnet import FullSubNet
# from vibvoice import A2net
from new_vibvoice import A2net
from conformer import TSCNet
from SEANet import SEANet

import numpy as np
from tqdm import tqdm
import argparse
from discriminator import Discriminator_time, Discriminator_spectrogram
from model_zoo import train_SEANet, test_SEANet, train_vibvoice, test_vibvoice, train_fullsubnet, test_fullsubnet, \
    train_conformer, test_conformer

seg_len_mic = 640
overlap_mic = 320
seg_len_imu = 64
overlap_imu = 32
rate_mic = 16000
rate_imu = 1600


freq_bin_high = 8 * int(rate_imu / rate_mic * int(seg_len_mic / 2)) + 1

def train(dataset, EPOCH, lr, BATCH_SIZE, model, discriminator=None, save_all=False):
    if isinstance(dataset, list):
        # with pre-defined train/ test
        train_dataset, test_dataset = dataset
    else:
        # without pre-defined train/ test
        length = len(dataset)
        test_size = min(int(0.1 * length), 2000)
        train_size = length - test_size
        train_dataset, test_dataset = torch.utils.data.random_split(dataset, [train_size, test_size])
    train_loader = Data.DataLoader(dataset=train_dataset, num_workers=8, batch_size=BATCH_SIZE, shuffle=True, drop_last=True,
                                   pin_memory=True)
    test_loader = Data.DataLoader(dataset=test_dataset, num_workers=4, batch_size=BATCH_SIZE, shuffle=False)

    optimizer = torch.optim.Adam(params=model.parameters(), lr=lr, betas=(0.9, 0.999))
    if discriminator is not None:
        optimizer_disc = torch.optim.AdamW(params=discriminator.parameters(), lr=lr, betas=(0.9, 0.999))
    scheduler = torch.optim.lr_scheduler.StepLR(optimizer, step_size=5, gamma=0.5)
    loss_best = 100
    loss_curve = []
    ckpt_best = model.state_dict()
    for e in range(EPOCH):
        Loss_list = []
        for i, (acc, noise, clean) in enumerate(tqdm(train_loader)):
            loss, discrim_loss = train_SEANet(model, acc, noise, clean, optimizer, optimizer_disc, discriminator, device)
            #loss = train_fullsubnet(model, acc, noise, clean, optimizer, device)
            Loss_list.append(loss)
        mean_lost = np.mean(Loss_list)
        loss_curve.append(mean_lost)
        scheduler.step()
        Metric = []
        with torch.no_grad():
            for acc, noise, clean in tqdm(test_loader):
                metric = test_SEANet(model, acc, noise, clean, device)
                Metric.append(metric)
        avg_metric = np.mean(np.concatenate(Metric, axis=0), axis=0)
        print(avg_metric, mean_lost)
        if mean_lost < loss_best:
            ckpt_best = model.state_dict()
            loss_best = mean_lost
            metric_best = avg_metric
        if save_all:
            torch.save(ckpt_best, 'pretrain/' + str(mean_lost) + '.pth')
    torch.save(ckpt_best, 'pretrain/' + str(metric_best) + '.pth')
    return ckpt_best, loss_curve, metric_best

def inference(dataset, BATCH_SIZE, model):
    test_loader = Data.DataLoader(dataset=dataset, num_workers=4, batch_size=BATCH_SIZE, shuffle=False)
    Metric = []
    with torch.no_grad():
        for data in test_loader:
            if len(data) == 3:
                acc, noise, clean = data
                metric = test_vibvoice(model, acc, noise, clean, device)
            else:
                text, acc, noise, clean = data
                metric = test_vibvoice(model, acc, noise, clean, device, text)
            Metric.append(metric)
    Metric = np.concatenate(Metric, axis=0)
    return Metric

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', action="store", type=int, default=0, required=False,
                        help='mode of processing, 0-pre train, 1-main benchmark, 2-mirco benchmark')
    args = parser.parse_args()
    #torch.cuda.set_device(1)
    device = (torch.device('cuda') if torch.cuda.is_available() else torch.device('cpu'))
    #model = A2net(inference=False).to(device)
    #model = FullSubNet(num_freqs=256, num_groups_in_drop_band=1).to(device)
    # model = Causal_A2net(inference=False).to(device)
    # model = TSCNet().to(device)
    model = SEANet().to(device)

    discriminator = Discriminator_time().to(device)
    time_domain = True

    model = torch.nn.DataParallel(model, device_ids=[0, 1])
    # discriminator = Discriminator_spectrogram().to(device)

    if args.mode == 0:
        # This script is for model pre-training on LibriSpeech
        BATCH_SIZE = 128
        lr = 0.00001
        EPOCH = 10
        dataset1 = NoisyCleanSet(['json/train.json', 'json/all_noise.json'], time_domain=time_domain, simulation=True,
                                ratio=1, rir=None)
        dataset2 = NoisyCleanSet(['json/train_360.json', 'json/all_noise.json'], time_domain=time_domain, simulation=True,
                                ratio=1, rir=None)
        train_dataset = torch.utils.data.ConcatDataset([dataset1, dataset2])
        model.load_state_dict(torch.load('pretrain/0.35409978383899.pth'))
        # with open('json/EMSB.json', 'r') as f:
        #     data = json.load(f)
        #     person = data.keys()
        # EMSB_dataset = NoisyCleanSet(['json/EMSB.json', 'json/all_noise.json', 'json/EMSB.json'], time_domain=time_domain, simulation=True,
        #                         ratio=1, rir=None, EMSB=True, person=person)

        ckpt_best, loss_curve, metric_best = train(train_dataset, EPOCH, lr, BATCH_SIZE, model, discriminator=None,
                                                   save_all=True)
        plt.plot(loss_curve)
        plt.savefig('loss.png')
    elif args.mode == 1:
        # This script is for model fine-tune on self-collected dataset, by default-with all noises
        BATCH_SIZE = 16
        lr = 0.0001
        EPOCH = 10

        ckpt_dir = 'pretrain/seanet'
        ckpt_name = ckpt_dir + '/' + sorted(os.listdir(ckpt_dir))[-1]
        print("load checkpoint: {}".format(ckpt_name))
        ckpt = torch.load(ckpt_name)
        for n in [2, 3]:
            people = ["1", "2", "3", "4", "5", "6", "7", "8", "yan", "wu", "liang", "shuai", "shi", "he", "hou"]
            train_dataset = NoisyCleanSet(['json/train_gt.json', 'json/all_noise.json', 'json/train_imu.json'],
                                               time_domain=time_domain, simulation=True, person=people, ratio=0.8, num_noises=n)
            test_dataset = NoisyCleanSet(['json/train_gt.json', 'json/all_noise.json', 'json/train_imu.json'],
                                              time_domain=time_domain, simulation=True, person=people, ratio=-0.2, num_noises=n)

            # extra dataset for other positions
            # positions = ['glasses', 'vr-up', 'vr-down', 'headphone-inside', 'headphone-outside', 'cheek', 'temple', 'back', 'nose']
            # train_dataset2 = NoisyCleanSet(['json/position_gt.json', 'json/all_noise.json', 'json/position_imu.json'],
            #                                time_domain=time_domain, simulation=True, person=positions, ratio=0.8, num_noises=n)
            # test_dataset2 = NoisyCleanSet(['json/position_gt.json', 'json/all_noise.json', 'json/position_imu.json'],
            #                               time_domain=time_domain, simulation=True, person=positions, ratio=-0.2, num_noises=n)
            #
            # train_dataset = torch.utils.data.ConcatDataset([train_dataset, train_dataset2])
            # test_dataset = torch.utils.data.ConcatDataset([test_dataset, test_dataset2])

            model.load_state_dict(ckpt)
            ckpt, loss_curve, metric_best = train([train_dataset, test_dataset], EPOCH, lr, BATCH_SIZE, model, discriminator=discriminator)

        # Optional Micro-benchmark
        model.load_state_dict(ckpt)

        # for num_noise in [1, 2, 3]:
        #     dataset = NoisyCleanSet(['json/train_gt.json', 'json/all_noise.json', 'json/train_imu.json'], person=people,
        #                             time_domain=time_domain, simulation=True, ratio=-0.2, num_noises=num_noise)
        #     Metric = inference(dataset, BATCH_SIZE, model)
        #     avg_metric = np.mean(Metric, axis=0)
        #     print(num_noise, avg_metric)
        #
        # for p in ["1", "2", "3", "4", "5", "6", "7", "8", "yan", "wu", "liang", "shuai", "shi", "he", "hou"]:
        #     dataset = NoisyCleanSet(['json/train_gt.json', 'json/all_noise.json', 'json/train_imu.json'],
        #                             person=[p], time_domain=time_domain, simulation=True, ratio=-0.2)
        #     Metric = inference(dataset, BATCH_SIZE, model)
        #     avg_metric = np.mean(Metric, axis=0)
        #     print(p, avg_metric)
        #
        # for noise in ['background.json', 'dev.json', 'music.json']:
        #     dataset = NoisyCleanSet(['json/train_gt.json', 'json/' + noise,  'json/train_imu.json'],
        #                             person=people, time_domain=time_domain, simulation=True, ratio=-0.2)
        #     Metric = inference(dataset, BATCH_SIZE, model)
        #     avg_metric = np.mean(Metric, axis=0)
        #     print(noise, avg_metric)
        #
        # for level in [11, 6, 1]:
        #     dataset = NoisyCleanSet(['json/train_gt.json', 'json/all_noise.json',  'json/train_imu.json'], person=people,
        #                             time_domain=time_domain, simulation=True, snr=[level - 1, level + 1], ratio=-0.2)
        #     Metric = inference(dataset, BATCH_SIZE, model)
        #     avg_metric = np.mean(Metric, axis=0)
        #     print(level, avg_metric)
        #
        # positions = ['glasses', 'vr-up', 'vr-down', 'headphone-inside', 'headphone-outside', 'cheek', 'temple', 'back', 'nose']
        # for p in positions:
        #     dataset = NoisyCleanSet(['json/position_gt.json', 'json/all_noise.json', 'json/position_imu.json'],
        #                             person=[p], time_domain=time_domain, simulation=True, ratio=-0.2)
        #     Metric = inference(dataset, BATCH_SIZE, model)
        #     avg_metric = np.mean(Metric, axis=0)
        #     print(p, avg_metric)
    elif args.mode == 2:
        # micro-benchmark per-user, length of data
        ckpt_dir = 'pretrain/new_vibvoice'
        ckpt_name = ckpt_dir + '/' + sorted(os.listdir(ckpt_dir))[-1]
        print('loaded checkpoint:', ckpt_name)
        ckpt_name = 'pretrain/[ 2.6519329  15.54417844  3.54972677].pth'
        ckpt_start = torch.load(ckpt_name)
        people_train = ["1", "2", "3", "4", "5", "6", "7", "8", "yan", "wu"]
        people_test = ["he", "hou", "liang", "shuai", "shi"]
        model.load_state_dict(ckpt_start)

        # train_dataset = NoisyCleanSet(['json/train_gt.json', 'json/all_noise.json', 'json/train_imu.json'],
        #     person=people_train, time_domain=time_domain, simulation=True, text=False, ratio=1)
        # ckpt, _, _ = train(train_dataset, 5, 0.0001, 16, model)
        # model.load_state_dict(ckpt)
        #
        # train_dataset = NoisyCleanSet(['json/train_gt.json', 'json/all_noise.json', 'json/train_imu.json'],
        #     person=people_test, time_domain=time_domain, simulation=True, text=False, ratio=0.8)
        # test_dataset = NoisyCleanSet(['json/train_gt.json', 'json/all_noise.json', 'json/train_imu.json'],
        #     person=people_test, time_domain=time_domain, simulation=True, text=False, ratio=-0.2)
        # ckpt, _, _ = train([train_dataset, test_dataset], 5, 0.00001, 8, model)

        #model.load_state_dict(ckpt)

        for num_noise in [1, 2, 3]:
            dataset = NoisyCleanSet(['json/train_gt.json', 'json/all_noise.json', 'json/train_imu.json'], person=people_test,
                                    time_domain=time_domain, simulation=True, ratio=-0.2, num_noises=num_noise)
            Metric = inference(dataset, 4, model)
            avg_metric = np.mean(Metric, axis=0)
            print(num_noise, avg_metric)

        dataset = NoisyCleanSet(['json/train_gt.json', 'json/all_noise.json', 'json/train_imu.json'],
                                    person=people_test, time_domain=time_domain, simulation=True, ratio=-0.2)
        Metric = inference(dataset, 4, model)
        avg_metric = np.mean(Metric, axis=0)
        print(p, avg_metric)

        for noise in ['background.json', 'dev.json', 'music.json']:
            dataset = NoisyCleanSet(['json/train_gt.json', 'json/' + noise,  'json/train_imu.json'],
                                    person=people_test, time_domain=time_domain, simulation=True, ratio=-0.2)
            Metric = inference(dataset, 4, model)
            avg_metric = np.mean(Metric, axis=0)
            print(noise, avg_metric)

        for level in [11, 6, 1]:
            dataset = NoisyCleanSet(['json/train_gt.json', 'json/all_noise.json',  'json/train_imu.json'], person=people_test,
                                    time_domain=time_domain, simulation=True, snr=[level - 1, level + 1], ratio=-0.2)
            Metric = inference(dataset, 4, model)
            avg_metric = np.mean(Metric, axis=0)
            print(level, avg_metric)

        positions = ['glasses', 'vr-up', 'vr-down', 'headphone-inside', 'headphone-outside', 'cheek', 'temple', 'back', 'nose']
        for p in positions:
            dataset = NoisyCleanSet(['json/position_gt.json', 'json/all_noise.json', 'json/position_imu.json'],
                                    person=[p], time_domain=time_domain, simulation=True, ratio=-0.2)
            Metric = inference(dataset, 4, model)
            avg_metric = np.mean(Metric, axis=0)
            print(p, avg_metric)
    elif args.mode == 3:
        # evaluation for WER (without reference)
        ckpt_dir = 'pretrain/new_vibvoice'
        ckpt_name = ckpt_dir + '/' + sorted(os.listdir(ckpt_dir))[-1]
        print('loaded checkpoint:', ckpt_name)
        ckpt_start = torch.load(ckpt_name)
        people = ["hou", "1", "2", "3", "4", "5", "6", "7", "8", "yan", "wu", "liang", "shuai", "shi", "he"]
        ckpts = []
        for p in ['hou']:
            model.load_state_dict(ckpt_start)
            p_except = [i for i in people if i != p]


            # train_dataset = NoisyCleanSet(['json/noise_train_gt.json', 'json/noise_train_wav.json', 'json/noise_train_imu.json'],
            #                              person=people, time_domain=time_domain, simulation=False, text=False)
            # ckpt, _, _ = train(train_dataset, 5, 0.0001, 16, model)

            train_dataset = NoisyCleanSet(['json/train_gt.json', 'json/dev.json', 'json/train_imu.json'],
                                          person=people, time_domain=time_domain, simulation=True,
                                          rir='json/rir_noise.json', text=False, snr=(0, 10))
            ckpt, _, _ = train(train_dataset, 5, 0.0001, 16, model)
            ckpts.append(ckpt)
        for ckpt, p in zip(ckpts, ['hou']):
            model.load_state_dict(ckpt)
            test_dataset = NoisyCleanSet(['json/noise_gt.json', 'json/noise_wav.json', 'json/noise_imu.json'],
                                         person=[p], time_domain=time_domain, simulation=False, text=True)
            metric = inference(test_dataset, 4, model)
            avg_metric = np.mean(metric, axis=0)
            print(p, avg_metric)
        # for env in ['airpod', 'freebud', 'galaxy', 'office', 'corridor', 'stair']:
        #     test_dataset = NoisyCleanSet(['json/noise_gt.json', 'json/noise_wav.json', 'json/noise_imu.json'],
        #                                  person=[env], time_domain=time_domain, simulation=False, text=True)
        #     metric = inference(test_dataset, 1, model)
        #     avg_metric = np.mean(metric, axis=0)
        #     print(env, avg_metric)
        #
        # test_dataset = NoisyCleanSet(['json/mobile_gt.json', 'json/mobile_wav.json', 'json/mobile_imu.json'],
        #                              person=['he'], time_domain=time_domain, simulation=False, text=True)
        # metric = inference(test_dataset, 4, model)
        # avg_metric = np.mean(metric, axis=0)
        # print('mobile result', avg_metric)
