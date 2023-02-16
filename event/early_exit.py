from utils.datasets.vggsound import VGGSound
import numpy as np
import torch
from model.exit_model import AVnet
import warnings
from tqdm import tqdm
warnings.filterwarnings("ignore")
# remove annoying librosa warning
def profile(model, test_dataset):
    model.load_state_dict(torch.load('17_0.5727633648323562.pth'))
    test_loader = torch.utils.data.DataLoader(dataset=test_dataset, num_workers=1, batch_size=1, shuffle=False)
    model.eval()
    model.exit = True
    thresholds = [0.8, 0.9, 0.95, 0.99]
    with torch.no_grad():
        for threshold in thresholds:
            acc = []
            ee = []
            model.threshold = threshold
            for batch in tqdm(test_loader):
                audio, image, text, _ = batch
                a, e = test_step(model, input_data=(audio.to(device), image.to(device)), label=text)
                # print(a, e)
                acc.append(a)
                ee.append(e)
            acc = np.stack(acc)
            ee = np.array(ee)
            acc = acc[np.arange(len(acc)), ee - 1]
            print('threshold', threshold)
            print('accuracy for early-exits:', np.mean(acc))
            print('early-exit percentage:', np.bincount(ee-1) / ee.shape[0])
def train_step(model, input_data, optimizers, criteria, label):
    audio, image = input_data
    # Track history only in training
    for branch in [0]:
        optimizer = optimizers[branch]
        outputs = model(audio, image)
        # Backward
        optimizer.zero_grad()
        loss = 0
        for i, output in enumerate(outputs):
            loss += (i+1) * 0.25 * criteria(output, label)
        loss.backward()
        optimizer.step()
    return loss.item()
def test_step(model, input_data, label):
    audio, image = input_data
    # Track history only in training
    early_exits = np.zeros((4))
    outputs = model(audio, image)
    for i, output in enumerate(outputs):
        early_exits[i] = (torch.argmax(output, dim=-1).cpu() == label).sum()/len(label)
    for i in range(len(outputs), 4):
        early_exits[i] = -1
    return early_exits, len(outputs)
def update_lr(optimizer, multiplier = .1):
    state_dict = optimizer.state_dict()
    for param_group in state_dict['param_groups']:
        param_group['lr'] = param_group['lr'] * multiplier
    optimizer.load_state_dict(state_dict)
def train(model, train_dataset, test_dataset):
    train_loader = torch.utils.data.DataLoader(dataset=train_dataset, num_workers=16, batch_size=64, shuffle=True,
                                               drop_last=True, pin_memory=False)
    test_loader = torch.utils.data.DataLoader(dataset=test_dataset, num_workers=16, batch_size=64, shuffle=False)
    # optimizers = [torch.optim.Adam(model.get_image_params(), lr=.0001, weight_decay=1e-4),
    #               torch.optim.Adam(model.get_audio_params(), lr=.0001, weight_decay=1e-4)]
    optimizers = [torch.optim.Adam(model.parameters(), lr=.0001, weight_decay=1e-4)]
    criteria = torch.nn.CrossEntropyLoss()
    best_acc = 0
    for epoch in range(20):
        model.train()
        model.exit = False
        if epoch % 5 == 0 and epoch > 0:
            update_lr(optimizers[0], multiplier=.2)
            # update_lr(optimizers[1], multiplier=.1)
        for idx, batch in enumerate(tqdm(train_loader)):
            audio, image, text, _ = batch
            loss = train_step(model, input_data=(audio.to(device), image.to(device)), optimizers=optimizers, criteria=criteria, label=text.to(device))
        model.eval()
        acc = []
        # model.exit = True
        with torch.no_grad():
            for batch in tqdm(test_loader):
                audio, image, text, _ = batch
                a, _ = test_step(model, input_data=(audio.to(device), image.to(device)), label=text)
                acc.append(a)
        acc = np.stack(acc)
        acc = np.mean(acc, axis=0, where=acc >= 0)
        print('epoch', epoch)
        print('accuracy for early-exits:', acc)
        if acc[-1].item() > best_acc:
            best_acc = acc[-1].item()
            torch.save(model.state_dict(), str(epoch) + '_' + str(acc[-1].item()) + '.pth')
if __name__ == "__main__":
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    torch.cuda.set_device(1)
    model = AVnet().to(device)
    dataset = VGGSound()
    len_train = int(len(dataset) * 0.8)
    len_test = len(dataset) - len_train
    train_dataset, test_dataset = torch.utils.data.random_split(dataset, [len_train, len_test], generator=torch.Generator().manual_seed(42))
    # train(model, train_dataset, test_dataset)
    profile(model, test_dataset)

