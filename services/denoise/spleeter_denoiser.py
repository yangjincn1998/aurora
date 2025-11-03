from pathlib import Path
from typing import Tuple

from services.denoise.denoiser import Denoiser
from utils.logger import get_logger

logger = get_logger(__name__)


class SpleeterDenoiser(Denoiser):
    """
    基于 Spleeter 的音频降噪器实现。
    使用 Spleeter 的音源分离功能来实现降噪。
    """

    def __init__(
        self,
        model_type: str = "spleeter:2stems",
        output_format: str = "wav",
        stft_backend: str = "librosa",
        mwf: bool = False,
        mwf_iter: int = 2,
        codec: str = "wav",
        bitrate: str = "128k",
        ffmpeg_path: str = "ffmpeg",
    ):
        """
        初始化 SpleeterDenoiser。

        Args:
            model_type: Spleeter模型类型，可选：
                       'spleeter:2stems' (人声/伴奏),
                       'spleeter:4stems' (人声/鼓/贝斯/其他),
                       'spleeter:5stems' (人声/鼓/贝斯/钢琴/其他)
            output_format: 输出音频格式 (wav, mp3, ogg等)
            stft_backend: STFT后端 ('librosa' 或 'tensorflow')
            mwf: 是否使用Wiener滤波器增强
            mwf_iter: Wiener滤波器迭代次数
            codec: 音频编码格式
            bitrate: 音频比特率
            ffmpeg_path: FFmpeg可执行文件路径
        """
        self.model_type = model_type
        self.output_format = output_format
        self.stft_backend = stft_backend
        self.mwf = mwf
        self.mwf_iter = mwf_iter
        self.codec = codec
        self.bitrate = bitrate
        self.ffmpeg_path = ffmpeg_path
        self._separator = None

    def _initialize_separator(self):
        """
        初始化Spleeter分离器。
        """
        if self._separator is None:
            try:
                from spleeter.separator import Separator

                logger.info(f"正在初始化Spleeter分离器，模型: {self.model_type}")
                # 使用兼容的参数创建分离器
                self._separator = Separator(self.model_type)
                logger.info("Spleeter分离器初始化成功")
            except ImportError as e:
                raise ImportError(f"无法导入spleeter库，请确保已正确安装: {e}")
            except Exception as e:
                raise RuntimeError(f"初始化Spleeter分离器失败: {e}")

    @classmethod
    def from_config(cls, config: dict) -> "SpleeterDenoiser":
        """
        从配置字典创建 SpleeterDenoiser 实例。

        Args:
            config: 配置字典

        Returns:
            SpleeterDenoiser实例
        """
        model_type = config.get("model_type", "spleeter:2stems")
        output_format = config.get("output_format", "wav")
        stft_backend = config.get("stft_backend", "librosa")
        mwf = config.get("mwf", False)
        mwf_iter = config.get("mwf_iter", 2)
        codec = config.get("codec", "wav")
        bitrate = config.get("bitrate", "128k")
        ffmpeg_path = config.get("ffmpeg_path", "ffmpeg")

        return cls(
            model_type=model_type,
            output_format=output_format,
            stft_backend=stft_backend,
            mwf=mwf,
            mwf_iter=mwf_iter,
            codec=codec,
            bitrate=bitrate,
            ffmpeg_path=ffmpeg_path,
        )

    def denoise(self, input_path: str, output_path: str) -> Tuple[bool, str]:
        """
        使用Spleeter对音频文件进行降噪处理。

        Spleeter的降噪原理：
        1. 将音频分离成人声和伴奏
        2. 保留人声部分（通常包含主要的语音内容）
        3. 或者分离更多轨道，选择保留人声和其他期望的乐器

        Args:
            input_path: 输入音频文件路径
            output_path: 输出音频文件路径

        Returns:
            (是否成功, 失败原因或成功信息)
        """
        try:
            # 验证输入文件
            if not Path(input_path).exists():
                return False, f"输入音频文件不存在: {input_path}"

            # 确保输出目录存在
            output_dir = Path(output_path).parent
            output_dir.mkdir(parents=True, exist_ok=True)

            logger.info(f"开始Spleeter降噪处理: {input_path}")

            # 初始化分离器
            self._initialize_separator()

            # 加载音频文件
            import librosa
            import numpy as np

            logger.info("正在加载音频文件...")
            waveform, sample_rate = librosa.load(input_path, sr=None, mono=False)

            # 确保立体声格式
            if len(waveform.shape) == 1:
                # 转换单声道为立体声
                waveform = np.array([waveform, waveform])
                logger.info("转换单声道为立体声")

            # 确保正确的形状格式
            if waveform.shape[0] > waveform.shape[1]:
                waveform = waveform.T
                logger.info("转置音频波形格式")

            logger.info(f"音频加载完成: 形状={waveform.shape}, 采样率={sample_rate}")

            # 对于长音频文件进行分段处理
            max_samples = 10 * sample_rate  # 10秒的最大处理长度
            if waveform.shape[1] > max_samples:
                logger.info(
                    f"音频文件较长({waveform.shape[1]}样本)，将处理前{max_samples}样本({max_samples/sample_rate}秒)"
                )
                waveform = waveform[:, :max_samples]

            # 使用Spleeter进行音源分离
            logger.info(f"正在使用 {self.model_type} 模型进行音源分离...")
            prediction = self._separator.separate(waveform)

            logger.info(f"音源分离完成，返回的音轨: {list(prediction.keys())}")

            # 根据模型类型选择要保留的音轨
            denoised_data = None
            track_name = "unknown"

            if self.model_type == "spleeter:2stems":
                # 2stems: vocals, accompaniment
                if "vocals" in prediction:
                    denoised_data = prediction["vocals"]
                    track_name = "vocals"
                elif "accompaniment" in prediction:
                    denoised_data = prediction["accompaniment"]
                    track_name = "accompaniment"

            elif self.model_type == "spleeter:4stems":
                # 4stems: vocals, drums, bass, other
                # 优先保留人声
                if "vocals" in prediction:
                    denoised_data = prediction["vocals"]
                    track_name = "vocals"
                elif "other" in prediction:
                    denoised_data = prediction["other"]
                    track_name = "other"

            elif self.model_type == "spleeter:5stems":
                # 5stems: vocals, drums, bass, piano, other
                # 保留人声轨道
                if "vocals" in prediction:
                    denoised_data = prediction["vocals"]
                    track_name = "vocals"

            else:
                # 默认保留第一个可用的音轨
                available_tracks = list(prediction.keys())
                if available_tracks:
                    denoised_data = prediction[available_tracks[0]]
                    track_name = available_tracks[0]

            if denoised_data is None:
                return False, "无法提取降噪后的音频数据"

            logger.info(f"选择的音轨: {track_name}, 数据形状: {denoised_data.shape}")

            # 保存降噪后的音频
            logger.info(f"正在保存降噪后的音频到: {output_path}")
            self._save_audio(denoised_data, output_path, track_name, sample_rate)

            logger.info(f"Spleeter降噪完成，结果保存到: {output_path}")
            return True, f"降噪成功，输出文件: {output_path}"

        except ImportError as e:
            error_msg = f"缺少必要的依赖库: {e}"
            logger.error(error_msg)
            return False, error_msg
        except Exception as e:
            error_msg = f"Spleeter降噪处理失败: {str(e)}"
            logger.error(error_msg)
            return False, error_msg

    def _save_audio(
        self, audio_data, output_path: str, track_name: str, sample_rate: int = 44100
    ):
        """
        保存音频数据到文件。

        Args:
            audio_data: 音频数据 (numpy array)
            output_path: 输出文件路径
            track_name: 音轨名称（用于日志）
            sample_rate: 采样率
        """
        try:
            import soundfile as sf
            import numpy as np

            # 确保音频数据是正确的格式
            if isinstance(audio_data, np.ndarray):
                # 处理不同的音频数据形状
                if len(audio_data.shape) == 1:
                    # 单声道
                    sf.write(
                        str(output_path), audio_data, sample_rate, subtype="PCM_16"
                    )
                elif audio_data.shape[0] == 1:
                    # 单声道，但有多余的维度
                    sf.write(
                        str(output_path), audio_data[0], sample_rate, subtype="PCM_16"
                    )
                elif audio_data.shape[1] == 1:
                    # 单声道，转置的
                    sf.write(
                        str(output_path),
                        audio_data[:, 0],
                        sample_rate,
                        subtype="PCM_16",
                    )
                else:
                    # 立体声或多声道
                    # 确保形状是 (samples, channels)
                    if audio_data.shape[0] < audio_data.shape[1]:
                        audio_data = audio_data.T
                    sf.write(
                        str(output_path), audio_data, sample_rate, subtype="PCM_16"
                    )

                logger.info(f"成功保存音轨 '{track_name}' 到: {output_path}")
            else:
                raise ValueError("音频数据格式不正确")

        except ImportError:
            # 如果没有soundfile，尝试使用其他方法
            try:
                import librosa

                # 确保数据格式正确
                if (
                    len(audio_data.shape) > 1
                    and audio_data.shape[0] < audio_data.shape[1]
                ):
                    audio_data = audio_data.T
                if len(audio_data.shape) > 1 and audio_data.shape[1] == 1:
                    audio_data = audio_data[:, 0]
                sf.write(str(output_path), audio_data, sample_rate)
                logger.info(f"使用librosa保存音轨 '{track_name}' 到: {output_path}")
            except ImportError:
                raise ImportError("无法导入音频保存库，请安装 soundfile 或 librosa")
        except Exception as e:
            raise RuntimeError(f"保存音频文件失败: {e}")

    def get_supported_formats(self) -> list:
        """
        获取支持的音频格式列表。

        Returns:
            支持的音频格式列表
        """
        return [".wav", ".mp3", ".ogg", ".flac", ".m4a", ".aac"]

    def get_model_info(self) -> dict:
        """
        获取当前模型信息。

        Returns:
            包含模型信息的字典
        """
        return {
            "model_type": self.model_type,
            "output_format": self.output_format,
            "stft_backend": self.stft_backend,
            "mwf_enabled": self.mwf,
            "mwf_iterations": self.mwf_iter,
            "supported_formats": self.get_supported_formats(),
        }
