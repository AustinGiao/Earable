import torch
from torch.nn import functional

from audio_zen.acoustics.feature import drop_band
from audio_zen.model.base_model import BaseModel
from audio_zen.model.module.sequence_model import SequenceModel
import time
from torchvision.utils import save_image
from torch.utils.mobile_optimizer import optimize_for_mobile

class FullSubNet(BaseModel):
    def __init__(self,
                 num_freqs=257,
                 look_ahead=2,
                 sequence_model="LSTM",
                 fb_num_neighbors=0,
                 sb_num_neighbors=15,
                 fb_output_activate_function="ReLU",
                 sb_output_activate_function=False,
                 fb_model_hidden_size=512,
                 sb_model_hidden_size=384,
                 norm_type="offline_laplace_norm",
                 num_groups_in_drop_band=2,
                 weight_init=True,
                 ):
        """
        FullSubNet model (cIRM mask)

        Args:
            num_freqs: Frequency dim of the input
            look_ahead: Number of use of the future frames
            fb_num_neighbors: How much neighbor frequencies at each side from fullband model's output
            sb_num_neighbors: How much neighbor frequencies at each side from noisy spectrogram
            sequence_model: Chose one sequence model as the basic model e.g., GRU, LSTM
            fb_output_activate_function: fullband model's activation function
            sb_output_activate_function: subband model's activation function
            norm_type: type of normalization, see more details in "BaseModel" class
        """
        super().__init__()
        assert sequence_model in ("GRU", "LSTM"), f"{self.__class__.__name__} only support GRU and LSTM."

        self.fb_model = SequenceModel(
            input_size=num_freqs,
            output_size=num_freqs,
            hidden_size=fb_model_hidden_size,
            num_layers=2,
            bidirectional=False,
            sequence_model=sequence_model,
            output_activate_function=fb_output_activate_function
        )

        self.sb_model = SequenceModel(
            input_size=(sb_num_neighbors * 2 + 1) + (fb_num_neighbors * 2 + 1),
            output_size=2,
            hidden_size=sb_model_hidden_size,
            num_layers=2,
            bidirectional=False,
            sequence_model=sequence_model,
            output_activate_function=sb_output_activate_function
        )

        self.sb_num_neighbors = sb_num_neighbors
        self.fb_num_neighbors = fb_num_neighbors
        self.look_ahead = look_ahead
        self.norm = self.norm_wrapper(norm_type)
        self.num_groups_in_drop_band = num_groups_in_drop_band

        if weight_init:
            self.apply(self.weight_init)

    def forward(self, noisy_mag):
        """
        Args:
            noisy_mag: noisy magnitude spectrogram

        Returns:
            The real part and imag part of the enhanced spectrogram

        Shapes:
            noisy_mag: [B, 1, F, T]
            return: [B, 2, F, T]
        """
        assert noisy_mag.dim() == 4
        noisy_mag = functional.pad(noisy_mag, [0, self.look_ahead])  # Pad the look ahead
        batch_size, num_channels, num_freqs, num_frames = noisy_mag.size()
        assert num_channels == 1, f"{self.__class__.__name__} takes the mag feature as inputs."

        # Fullband model
        fb_input = self.norm(noisy_mag).reshape(batch_size, num_channels * num_freqs, num_frames)
        fb_output = self.fb_model(fb_input).reshape(batch_size, 1, num_freqs, num_frames)

        # Unfold fullband model's output, [B, N=F, C, F_f, T]. N is the number of sub-band units
        fb_output_unfolded = self.unfold(fb_output, num_neighbors=self.fb_num_neighbors)
        fb_output_unfolded = fb_output_unfolded.reshape(batch_size, num_freqs, self.fb_num_neighbors * 2 + 1, num_frames)

        # Unfold noisy spectrogram, [B, N=F, C, F_s, T]
        noisy_mag_unfolded = self.unfold(noisy_mag, num_neighbors=self.sb_num_neighbors)
        noisy_mag_unfolded = noisy_mag_unfolded.reshape(batch_size, num_freqs, self.sb_num_neighbors * 2 + 1, num_frames)

        # Concatenation, [B, F, (F_s + F_f), T]
        sb_input = torch.cat([noisy_mag_unfolded, fb_output_unfolded], dim=2)
        sb_input = self.norm(sb_input)

        # Speeding up training without significant performance degradation.
        # These will be updated to the paper later.
        # if batch_size > 1:
        #     sb_input = drop_band(sb_input.permute(0, 2, 1, 3), num_groups=self.num_groups_in_drop_band)  # [B, (F_s + F_f), F//num_groups, T]
        #     num_freqs = sb_input.shape[2]
        #     sb_input = sb_input.permute(0, 2, 1, 3)  # [B, F//num_groups, (F_s + F_f), T]

        sb_input = sb_input.reshape(
            batch_size * num_freqs,
            (self.sb_num_neighbors * 2 + 1) + (self.fb_num_neighbors * 2 + 1),
            num_frames
        )

        # [B * F, (F_s + F_f), T] => [B * F, 2, T] => [B, F, 2, T]
        sb_mask = self.sb_model(sb_input)
        sb_mask = sb_mask.reshape(batch_size, num_freqs, 2, num_frames).permute(0, 2, 1, 3).contiguous()

        output = sb_mask[:, :, :, self.look_ahead:]
        return output

def model_size(model):
    param_size = 0
    for param in model.parameters():
        param_size += param.nelement() * param.element_size()
    buffer_size = 0
    for buffer in model.buffers():
        buffer_size += buffer.nelement() * buffer.element_size()

    size_all_mb = (param_size + buffer_size) / 1024 ** 2

    return size_all_mb
def model_speed(model, input):
    t_start = time.time()
    step = 1000
    with torch.no_grad():
        for i in range(step):
            model(input)
    return (time.time() - t_start)/step
def model_save(model, audio):
    from torch.jit.mobile import (
                _backport_for_mobile,
                _get_model_bytecode_version,
            )
    model.eval()
    # traced_script_module = torch.jit.trace(model, audio)
    # traced_script_module.save("model.pt")
    # traced_script_module_optimized = optimize_for_mobile(traced_script_module)
    # traced_script_module_optimized._save_for_lite_interpreter("model.ptl")
    # #torch.jit.save(traced_script_module_optimized, "model.ptl")
    # convert2version5 = True
    # if convert2version5:
    #     MODEL_INPUT_FILE = "model.ptl"
    #     MODEL_OUTPUT_FILE = "model_v5.ptl"
    #
    #     print("model version", _get_model_bytecode_version(f_input=MODEL_INPUT_FILE))
    #
    #     _backport_for_mobile(f_input=MODEL_INPUT_FILE, f_output=MODEL_OUTPUT_FILE, to_version=5)
    #
    #     print("new model version", _get_model_bytecode_version(MODEL_OUTPUT_FILE))
    scripted_module = torch.jit.trace(model, audio)
    scripted_module.save("inference.pt")
    optimized_scripted_module = optimize_for_mobile(scripted_module)
    optimized_scripted_module._save_for_lite_interpreter("inference_optimized.ptl")
    print("model version", _get_model_bytecode_version(f_input="inference.ptl"))
    save_image(audio, 'input.jpg')
if __name__ == "__main__":

    audio = torch.rand(1, 1, 264, 151)
    model = FullSubNet(
        num_freqs=264,
        look_ahead=2,
        sequence_model="LSTM",
        fb_num_neighbors=0,
        sb_num_neighbors=15,
        fb_output_activate_function="ReLU",
        sb_output_activate_function=False,
        fb_model_hidden_size=512,
        sb_model_hidden_size=384,
        norm_type="offline_laplace_norm",
        num_groups_in_drop_band=2,
        weight_init=False,
    )
    # size_all_mb = model_size(model)
    # print('model size: {:.3f}MB'.format(size_all_mb))
    #
    # latency = model_speed(model, audio)
    # print('model latency: {:.3f}S'.format(latency))

    model_save(model, audio)