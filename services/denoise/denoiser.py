from abc import ABC, abstractmethod
from pathlib import Path
from typing import Tuple

import yaml

from utils.logger import get_logger

logger = get_logger(__name__)


class Denoiser(ABC):
    """
    音频降噪器抽象基类。
    """

    @abstractmethod
    def denoise(self, input_path: str, output_path: str) -> Tuple[bool, str]:
        """
        对音频文件进行降噪处理。

        Args:
            input_path: 输入音频文件路径
            output_path: 输出音频文件路径

        Returns:
            (是否成功, 失败原因或成功信息)
        """
        pass

    @classmethod
    def from_config(cls, config: dict) -> "Denoiser":
        """
        从配置字典创建 Denoiser 实例。

        Args:
            config: 配置字典

        Returns:
            Denoiser实例
        """
        denoiser_type = config.get("type", "noisereduce")

        if denoiser_type == "noisereduce":
            return NoiseReduceDenoiser.from_config(config)
        else:
            raise ValueError(f"Unknown denoiser type: {denoiser_type}")

    @classmethod
    def from_yaml_config(cls, yaml_path: str) -> "Denoiser":
        """
        从 YAML 配置文件创建 Denoiser 实例。

        Args:
            yaml_path: YAML 配置文件路径

        Returns:
            Denoiser实例
        """
        if not Path(yaml_path).exists():
            raise FileNotFoundError(f"YAML config file not found: {yaml_path}")

        with open(yaml_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

        denoiser_config = config.get("denoiser", {})
        return cls.from_config(denoiser_config)


class NoiseReduceDenoiser(Denoiser):
    """
    基于 noisereduce 的音频降噪器实现。
    """

    def __init__(
        self,
        segment_duration: int = 30,
        prop_decrease: float = 0.8,
        stationary: bool = True,
        noise_sample_duration: float = 1.0,
    ):
        """
        初始化 NoiseReduceDenoiser。

        Args:
            segment_duration: 分段处理时长（秒）
            prop_decrease: 降低噪声的比例
            stationary: 是否使用平稳噪声假设
            noise_sample_duration: 噪声样本时长（秒）
        """
        self.segment_duration = segment_duration
        self.prop_decrease = prop_decrease
        self.stationary = stationary
        self.noise_sample_duration = noise_sample_duration

    @classmethod
    def from_config(cls, config: dict) -> "NoiseReduceDenoiser":
        """
        从配置字典创建 NoiseReduceDenoiser 实例。

        Args:
            config: 配置字典

        Returns:
            NoiseReduceDenoiser实例
        """
        segment_duration = config.get("segment_duration", 30)
        prop_decrease = config.get("prop_decrease", 0.8)
        stationary = config.get("stationary", True)
        noise_sample_duration = config.get("noise_sample_duration", 1.0)

        return cls(
            segment_duration=segment_duration,
            prop_decrease=prop_decrease,
            stationary=stationary,
            noise_sample_duration=noise_sample_duration,
        )

    def denoise(self, input_path: str, output_path: str) -> Tuple[bool, str]:
        """
        对音频文件进行降噪处理。

        Args:
            input_path: 输入音频文件路径
            output_path: 输出音频文件路径

        Returns:
            (是否成功, 失败原因或成功信息)
        """
        try:
            import librosa
            import noisereduce as nr
            import soundfile as sf
            import numpy as np

            if not Path(input_path).exists():
                return False, f"输入音频文件不存在: {input_path}"

            # 确保输出目录存在
            output_dir = Path(output_path).parent
            output_dir.mkdir(parents=True, exist_ok=True)

            logger.info(f"开始降噪处理: {input_path}")

            # 加载音频文件
            audio_data, sample_rate = librosa.load(str(input_path), sr=None)
            logger.info(f"加载音频: {len(audio_data)} 样本, {sample_rate} Hz")

            # 分段处理
            segment_samples = self.segment_duration * sample_rate
            total_segments = len(audio_data) // segment_samples + 1

            denoised_segments = []

            for i in range(total_segments):
                start_sample = i * segment_samples
                end_sample = min((i + 1) * segment_samples, len(audio_data))

                if start_sample >= len(audio_data):
                    break

                segment = audio_data[start_sample:end_sample]

                # 使用noisereduce进行降噪
                noise_samples = int(self.noise_sample_duration * sample_rate)

                if len(segment) > noise_samples * 2:
                    noise_clip = segment[:noise_samples]
                    denoised_segment = nr.reduce_noise(
                        y=segment,
                        sr=sample_rate,
                        y_noise=noise_clip,
                        prop_decrease=self.prop_decrease,
                        stationary=self.stationary,
                    )
                else:
                    # 如果片段太短，直接使用原片段
                    denoised_segment = segment

                denoised_segments.append(denoised_segment)
                logger.info(f"处理片段 {i+1}/{total_segments}")

            # 合并所有片段
            denoised_audio = np.concatenate(denoised_segments)

            # 保存结果
            sf.write(str(output_path), denoised_audio, sample_rate)

            logger.info(f"降噪完成，结果保存到: {output_path}")
            return True, f"降噪成功，输出文件: {output_path}"

        except ImportError as e:
            error_msg = f"缺少必要的依赖库: {e}"
            logger.error(error_msg)
            return False, error_msg
        except Exception as e:
            error_msg = f"降噪处理失败: {str(e)}"
            logger.error(error_msg)
            return False, error_msg
