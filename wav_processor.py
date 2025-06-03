import numpy as np
from scipy.io import wavfile
from scipy import signal
import soundfile as sf
from pydub import AudioSegment

def convert_mp3_to_wav(input_file, output_file):
    """Convert MP3 file to WAV format."""
    audio = AudioSegment.from_mp3(input_file)
    audio.export(output_file, format="wav")

from pydub import AudioSegment
import opuslib
import numpy as np

def convert_wav_to_opus(input_file, output_file, target_lufs=None):
    # 1. 读取 WAV 文件
    audio = AudioSegment.from_wav(input_file)

    # 2. 转换为 16kHz、单声道、16-bit PCM
    audio = audio.set_channels(1).set_frame_rate(16000).set_sample_width(2)

    # 3. 获取 PCM 数据为 numpy 数组（short）
    pcm_data = np.array(audio.get_array_of_samples(), dtype=np.int16)

    # 4. 响度标准化（可选，简单归一化实现）
    if target_lufs is not None:
        peak = np.max(np.abs(pcm_data))
        if peak > 0:
            pcm_data = (pcm_data.astype(np.float32) / peak * 30000).astype(np.int16)

    # 5. Opus 编码：每帧 60ms = 960 samples（16kHz）
    frame_size = 960
    encoder = opuslib.Encoder(16000, 1, opuslib.APPLICATION_AUDIO)
    output_bytes = bytearray()

    for i in range(0, len(pcm_data) - frame_size + 1, frame_size):
        frame = pcm_data[i:i + frame_size]
        encoded = encoder.encode(frame.tobytes(), frame_size)
        output_bytes.extend(encoded)

    # 6. 写入输出文件
    with open(output_file, "wb") as f:
        f.write(output_bytes)

if __name__ == "__main__":
    # Example usage
    input_file = "tts-output.mp3"
    output_file = "tts-output.wav"
    output_file_p3 = 'tts.p3'
    convert_mp3_to_wav(input_file, output_file)

    convert_wav_to_opus(output_file, output_file_p3, target_lufs=-14.0) 