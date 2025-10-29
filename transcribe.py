import sys
import os
from faster_whisper import WhisperModel


def format_time_srt(seconds):
    """ 将秒数转换为 SRT 时间格式 (HH:MM:SS,mmm) """
    hours = int(seconds // 3600)
    seconds %= 3600
    minutes = int(seconds // 60)
    seconds %= 60
    milliseconds = int((seconds - int(seconds)) * 1000)
    seconds = int(seconds)

    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"


def transcribe_audio_to_srt(audio_path):
    """
    接收音频文件路径，返回 SRT 格式的转写文本。

    参数:
    audio_path (str): 音频文件的完整路径 (例如: "C:/audio/my_talk.mp3")

    返回:
    str: SRT 格式的字幕文本
    """

    # --- 模型配置 ---
    # 6GB 显存建议使用 "medium" 模型。它在速度和准确性之间有很好的平衡。
    # 如果是英文音频，"medium.en" 效果更好。
    # 如果你想尝试更大的模型（可能显存不足），可以使用 "large-v3"
    model_size = "medium"

    # "cuda" 表示使用 GPU；"float16" 是为了在 GPU 上实现高性能计算
    try:
        model = WhisperModel(model_size, device="cuda", compute_type="float16")
    except Exception as e:
        print(f"加载模型失败，请检查 CUDA 是否正确安装: {e}")
        print("尝试使用 CPU 运行 (速度会慢很多)...")
        # 如果 CUDA 失败，回退到 CPU
        model = WhisperModel(model_size, device="cpu", compute_type="int8")

    # --- 开始转写 ---
    # vad_filter=True 可以帮助过滤掉没有语音的片段
    segments, info = model.transcribe(audio_path, beam_size=5, vad_filter=True, language="ja")

    print(f"检测到语言: {info.language} (置信度: {info.language_probability:.2f})")

    # --- 格式化为 SRT ---
    srt_content = []

    # segments 是一个生成器，我们需要迭代它
    for i, segment in enumerate(segments):
        start_time = format_time_srt(segment.start)
        end_time = format_time_srt(segment.end)
        text = segment.text.strip()

        # 添加字幕条目
        srt_content.append(str(i + 1))
        srt_content.append(f"{start_time} --> {end_time}")
        srt_content.append(text)
        srt_content.append("")  # SRT 条目之间的空行

    print("转写完成。")
    return "\n".join(srt_content)


# --- 主程序入口 (用于直接运行脚本) ---
if __name__ == "__main__":
    audio_file = r"D:\4. Collections\6.Adult Videos\PythonProject\output\BBAN-217\BBAN-217 饮尿·浴尿女同 ～我们俩将彼此的体液品尝殆尽～ 宫崎彩 × 七海唯亚 七海唯亚 宫崎彩..extract.denoised.wav"

    # 检查文件是否存在
    if not os.path.exists(audio_file):
        print(f"错误: 文件未找到 -> {audio_file}")
        sys.exit(1)

    print(f"正在处理文件: {audio_file} ...")

    # 1. 执行转写
    srt_output_text = transcribe_audio_to_srt(audio_file)

    # 2. 准备 SRT 输出文件名
    # (例如: my_audio.mp3 -> my_audio.srt)
    base_name = os.path.splitext(audio_file)[0]
    srt_file_path = base_name + ".srt"

    # 3. 写入 SRT 文件
    try:
        with open("test.srt", "w", encoding="utf-8") as f:
            f.write(srt_output_text)
        print(f"SRT 文件已保存到: {srt_file_path}")
    except Exception as e:
        print(f"保存 SRT 文件失败: {e}")