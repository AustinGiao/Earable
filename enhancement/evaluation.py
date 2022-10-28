import scipy.signal as signal
import numpy as np
import torch
from pesq import pesq
from joblib import Parallel, delayed
from pystoi.stoi import stoi

sentences = [["HAPPY", "NEW", "YEAR", "PROFESSOR", "AUSTIN", "NICE", "TO", "MEET", "YOU"],
                    ["WE", "WANT", "TO", "IMPROVE", "SPEECH", "QUALITY", "IN", "THIS", "PROJECT"],
                    ["BUT", "WE", "DON'T", "HAVE", "ENOUGH", "DATA", "TO", "TRAIN", "OUR", "MODEL"],
                    ["TRANSFER", "FUNCTION", "CAN", "BE", "A", "GOOD", "HELPER", "TO", "GENERATE", "DATA"]]
def editDistance(r, h):
    '''
    This function is to calculate the edit distance of reference sentence and the hypothesis sentence.

    Main algorithm used is dynamic programming.

    Attributes:
        r -> the list of words produced by splitting reference sentence.
        h -> the list of words produced by splitting hypothesis sentence.
    '''
    d = np.zeros((len(r) + 1) * (len(h) + 1), dtype=np.uint8).reshape((len(r) + 1, len(h) + 1))
    for i in range(len(r) + 1):
        d[i][0] = i
    for j in range(len(h) + 1):
        d[0][j] = j
    for i in range(1, len(r) + 1):
        for j in range(1, len(h) + 1):
            if r[i - 1] == h[j - 1]:
                d[i][j] = d[i - 1][j - 1]
            else:
                substitute = d[i - 1][j - 1] + 1
                insert = d[i][j - 1] + 1
                delete = d[i - 1][j] + 1
                d[i][j] = min(substitute, insert, delete)
    return float(d[len(r)][len(h)])

def wer(r, h):
    """
    This is a function that calculate the word error rate in ASR.
    You can use it like this: wer("what is it".split(), "what is".split())
    """
    # build the matrix
    d = editDistance(r, h)
    # print the result in aligned way
    result = d / len(r) * 100
    #result = d / (d + c) * 100
    #result = str("%.2f" % result) + "%"
    #alignedPrint(list, r, h, result)
    return result

def SI_SDR(reference, estimation, sr=16000):
    """
    Scale-Invariant Signal-to-Distortion Ratio (SI-SDR)

    Args:
        reference: numpy.ndarray, [..., T]
        estimation: numpy.ndarray, [..., T]

    Returns:
        SI-SDR

    References
        SDR– Half- Baked or Well Done? (http://www.merl.com/publications/docs/TR2019-013.pdf)
    """
    estimation, reference = np.broadcast_arrays(estimation, reference)
    reference_energy = np.sum(reference ** 2, axis=-1, keepdims=True)

    optimal_scaling = np.sum(reference * estimation, axis=-1, keepdims=True) / reference_energy

    projection = optimal_scaling * reference

    noise = estimation - projection

    ratio = np.sum(projection ** 2, axis=-1) / np.sum(noise ** 2, axis=-1)
    return 10 * np.log10(ratio)
def snr(gt, est):
    # ordinary snr
    n = gt - est
    power_n = np.mean(np.abs(n) ** 2, axis=1)
    power_gt = np.mean(np.abs(gt) ** 2, axis=1)
    return 10 * np.log10(power_gt / power_n)

def safe_log10(x, eps=1e-10):
    result = np.where(x > eps, x, -10)
    return np.log10(result, out=result, where=result > 0)

def lsd(gt, est):
    spectrogram1 = 10 * safe_log10(np.abs(signal.stft(gt, fs=16000, nperseg=640, noverlap=320, axis=1)[-1]))
    spectrogram2 = 10 * safe_log10(np.abs(signal.stft(est, fs=16000, nperseg=640, noverlap=320, axis=1)[-1]))
    error = (spectrogram1 - spectrogram2) ** 2
    error = np.mean(error, axis=1) ** (1/2)
    error = np.mean(error, axis=1)
    return error

def pesq_loss(clean, noisy, sr=16000):
    try:
        pesq_score = pesq(sr, clean, noisy, 'wb')
    except:
        # error can happen due to silent period
        pesq_score = 1
    return pesq_score


def batch_pesq(clean, noisy):
    pesq_score = Parallel(n_jobs=-1)(delayed(pesq_loss)(c, n) for c, n in zip(clean, noisy))
    pesq_score = np.array(pesq_score)
    return pesq_score

def STOI(ref, est, sr=16000):
    return stoi(ref, est, sr, extended=False)

def batch_ASR(batch, asr_model):
    batch_size = batch.shape[0]
    wav_lens = torch.ones(batch_size)
    pred = asr_model.transcribe_batch(batch, wav_lens)[0]
    return pred
def eval_ASR(clean, noisy, text, asr_model):
    clean = torch.from_numpy(clean/np.max(clean, axis=1)[:, np.newaxis])
    noisy = torch.from_numpy(noisy/np.max(noisy, axis=1)[:, np.newaxis])
    pred_clean = batch_ASR(clean, asr_model)
    pred_noisy = batch_ASR(noisy, asr_model)
    #batch_size = clean.shape[0]
    wer_clean = []
    wer_noisy = []
    for p_c, p_n, t in zip(pred_clean, pred_noisy, text):
        wer_clean.append(wer(t, p_c))
        wer_noisy.append(wer(t, p_n))
    return wer_clean, wer_noisy
if __name__ == "__main__":
    # we evaluate WER and PESQ in this script
    # f = open('survey/survey.txt', 'r', encoding='UTF-8')
    # lines = f.readlines()
    # WER = []
    # for i in range(len(lines)):
    #     hy = lines[i].upper().split()
    #     if len(hy) < 3:
    #         continue
    #     gt = sentences[i // int(len(lines) / len(sentences))]
    #     WER.append(wer(gt, hy))
    # print(np.mean(WER))

    from speechbrain.pretrained import EncoderDecoderASR
    # Uncomment for using another pre-trained model
    asr_model = EncoderDecoderASR.from_hparams(source="speechbrain/asr-transformer-transformerlm-librispeech",
                                               savedir="pretrained_models/asr-transformer-transformerlm-librispeech",
                                               run_opts={"device": "cuda"})
    text = [["HAPPY", "NEW", "YEAR", "PROFESSOR", "AUSTIN", "NICE", "TO", "MEET", "YOU"],
            ["HAPPY", "NEW", "YEAR", "PROFESSOR", "AUSTIN", "NICE", "TO", "MEET", "YOU"]]
    clean = torch.zeros([2, 80000])
    noisy = torch.zeros([2, 80000])
    eval_ASR(clean, noisy, text, asr_model)


