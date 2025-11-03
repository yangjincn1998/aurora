from pathlib import Path
from typing import Tuple

from services.denoise.denoiser import Denoiser
from utils.logger import get_logger

logger = get_logger(__name__)


class SpleeterDenoiserFixed(Denoiser):
    """
    修复版的Spleeter降噪器实现。
    使用更简单和可靠的方法进行音频降噪。
    """

    def __init__(
        self,
        model_type: str = "spleeter:2stems",
        output_format: str = "wav",
        max_duration: int = 30,  # 最大处理时长（秒）
        use_fallback: bool = True,  # 是否使用备用方法
    ):
        """
        初始化 SpleeterDenoiserFixed。

        Args:
            model_type: Spleeter模型类型
            output_format: 输出音频格式
            max_duration: 最大处理时长（秒）
            use_fallback: 是否在Spleeter失败时使用备用方法
        """
        self.model_type = model_type
        self.output_format = output_format
        self.max_duration = max_duration
        self.use_fallback = use_fallback
        self._separator = None

    def _initialize_separator(self):
        """
        初始化Spleeter分离器。
        """
        if self._separator is None:
            try:
                from spleeter.separator import Separator

                logger.info(f"正在初始化Spleeter分离器，模型: {self.model_type}")
                self._separator = Separator(self.model_type)
                logger.info("Spleeter分离器初始化成功")
                return True
            except Exception as e:
                logger.warning(f"Spleeter初始化失败: {e}")
                return False
        return True

    @classmethod
    def from_config(cls, config: dict) -> "SpleeterDenoiserFixed":
        """
        从配置字典创建 SpleeterDenoiserFixed 实例。
        """
        model_type = config.get("model_type", "spleeter:2stems")
        output_format = config.get("output_format", "wav")
        max_duration = config.get("max_duration", 30)
        use_fallback = config.get("use_fallback", True)

        return cls(
            model_type=model_type,
            output_format=output_format,
            max_duration=max_duration,
            use_fallback=use_fallback,
        )

    def denoise(self, input_path: str, output_path: str) -> Tuple[bool, str]:
        """
        使用Spleeter对音频文件进行降噪处理。

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

            # 尝试使用Spleeter
            success = self._try_spleeter_denoise(input_path, output_path)
            if success:
                return True, f"降噪成功，输出文件: {output_path}"

            # 如果Spleeter失败且启用了备用方法
            if self.use_fallback:
                logger.info("Spleeter处理失败，尝试使用备用降噪方法...")
                return self._fallback_denoise(input_path, output_path)
            else:
                return False, "Spleeter降噪处理失败且未启用备用方法"

        except Exception as e:
            error_msg = f"Spleeter降噪处理失败: {str(e)}"
            logger.error(error_msg)
            return False, error_msg

    def _try_spleeter_denoise(self, input_path: str, output_path: str) -> bool:
        """
        尝试使用Spleeter进行降噪
        """
        try:
            # 初始化分离器
            if not self._initialize_separator():
                return False

            # 加载音频文件
            import librosa
            import numpy as np

            logger.info("正在加载音频文件...")
            waveform, sample_rate = librosa.load(
                input_path, sr=None, mono=False, duration=self.max_duration
            )

            # 确保立体声格式
            if len(waveform.shape) == 1:
                waveform = np.array([waveform, waveform])
                logger.info("转换单声道为立体声")

            # 确保正确的形状格式
            if waveform.shape[0] > waveform.shape[1]:
                waveform = waveform.T
                logger.info("转置音频波形格式")

            logger.info(f"音频加载完成: 形状={waveform.shape}, 采样率={sample_rate}")

            # 使用Spleeter进行音源分离
            logger.info(f"正在使用 {self.model_type} 模型进行音源分离...")
            prediction = self._separator.separate(waveform)

            logger.info(f"音源分离完成，返回的音轨: {list(prediction.keys())}")

            # 选择要保留的音轨
            denoised_data = None
            track_name = "unknown"

            if self.model_type == "spleeter:2stems":
                if "vocals" in prediction:
                    denoised_data = prediction["vocals"]
                    track_name = "vocals"
                elif "accompaniment" in prediction:
                    denoised_data = prediction["accompaniment"]
                    track_name = "accompaniment"

            # 检查数据有效性
            if denoised_data is None:
                logger.warning("无法获取有效的音轨数据")
                return False

            if np.allclose(denoised_data, 0):
                logger.warning("分离的音频数据全为零，可能是模型处理失败")
                return False

            logger.info(f"选择的音轨: {track_name}, 数据形状: {denoised_data.shape}")

            # 保存音频
            self._save_audio(denoised_data, output_path, track_name, sample_rate)
            logger.info(f"Spleeter降噪完成，结果保存到: {output_path}")
            return True

        except Exception as e:
            logger.warning(f"Spleeter处理失败: {e}")
            return False

    def _fallback_denoise(self, input_path: str, output_path: str) -> Tuple[bool, str]:
        """
        备用降噪方法，使用简单的滤波技术
        """
        try:
            logger.info("使用备用降噪方法...")

            import librosa
            import soundfile as sf
            import numpy as np
            from scipy import signal

            # 加载音频
            audio, sr = librosa.load(input_path, sr=None)

            # 应用高通滤波器去除低频噪声
            sos = signal.butter(10, 80, btype="high", fs=sr, output="sos")
            filtered = signal.sosfilt(sos, audio)

            # 应用简单的噪声门限
            noise_threshold = np.percentile(np.abs(filtered), 70)
            gated = np.where(np.abs(filtered) < noise_threshold, 0, filtered)

            # 轻微的动态范围压缩
            compressed = np.tanh(gated * 0.8)

            # 保存结果
            sf.write(output_path, compressed, sr)

            logger.info(f"备用降噪完成，结果保存到: {output_path}")
            return True, f"使用备用方法降噪成功，输出文件: {output_path}"

        except ImportError as e:
            return False, f"备用方法缺少依赖库: {e}"
        except Exception as e:
            return False, f"备用降噪方法失败: {e}"

    def _save_audio(
        self, audio_data, output_path: str, track_name: str, sample_rate: int = 44100
    ):
        """
        保存音频数据到文件
        """
        try:
            import soundfile as sf
            import numpy as np

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
                    if audio_data.shape[0] < audio_data.shape[1]:
                        audio_data = audio_data.T
                    sf.write(
                        str(output_path), audio_data, sample_rate, subtype="PCM_16"
                    )

                logger.info(f"成功保存音轨 '{track_name}' 到: {output_path}")
            else:
                raise ValueError("音频数据格式不正确")

        except Exception as e:
            raise RuntimeError(f"保存音频文件失败: {e}")

    def get_supported_formats(self) -> list:
        """
        获取支持的音频格式列表
        """
        return [".wav", ".mp3", ".ogg", ".flac", ".m4a", ".aac"]

    def get_model_info(self) -> dict:
        """
        获取当前模型信息
        """
        return {
            "model_type": self.model_type,
            "output_format": self.output_format,
            "max_duration": self.max_duration,
            "use_fallback": self.use_fallback,
            "supported_formats": self.get_supported_formats(),
        }
