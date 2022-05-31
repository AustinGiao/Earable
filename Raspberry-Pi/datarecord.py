
from bmi160 import bmi160_accsave, bmi160_gyrosave

from mic import open_mic_stream, voice_record
from camera import webcam_save

from multiprocessing import Process
import argparse



if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Process some integers.')
    parser.add_argument('--time', action = "store",type=int, default=5, required=False, help='time of data recording')
    parser.add_argument('--mode', action = "store", type=int, default=0, required=False, help='whether have microphone')
    parser.add_argument('--device', action="store", type=int, default=0, required=False, help='device number of microphone')
    args = parser.parse_args()

    bmiaccframe = args.time * 1600
    micframe = args.time * 16000
    camframe = args.time * 15
    device = args.device
    if args.mode == 0:
        stream = open_mic_stream(device)
        thread1 = Process(target=bmi160_accsave, args=('bmiacc1', bmiaccframe, 0))
        thread2 = Process(target=bmi160_accsave, args=('bmiacc2', bmiaccframe, 1))
        thread = Process(target=voice_record, args=('mic', stream, micframe))
        thread_camera = Process(target=webcam_save, args=('cam', camframe))

        thread1.start()
        thread2.start()
        thread.start()
        thread_camera.start()

        thread1.join()
        thread2.join()
        thread.join()
        thread_camera.join()
    else:
        thread1 = Process(target=bmi160_accsave, args=('bmiacc1', bmiaccframe, 0))
        thread2 = Process(target=bmi160_accsave, args=('bmiacc2', bmiaccframe, 1))
        thread1.start()
        thread2.start()
        thread1.join()
        thread2.join()


