# 极光字幕 (AURORA, Automated Universal Resources Orchestrator of Rich AV)

## 概述

这是一个强大的自动化工具，旨在帮助您处理 AV 影片，自动提取音频、转录日文字幕、将其翻译成中文，并将翻译后的影片元数据（包括标题、发行日期、演员、导演和类别）嵌入到最终生成的双语字幕文件（`.ass` 和 `.srt`）的开头。

本项目利用多线程处理和本地缓存机制，极大地提高了效率并减少了重复的 API 调用。

## 主要功能

  * **视频扫描**: 自动识别指定目录下的视频文件。
  * **AV 番号提取**: 从视频文件名中提取 AV 番号，作为影片的唯一标识符。
  * **音频提取**: 使用 `FFmpeg` 从视频文件中高效提取音频。
  * **日文转录**:
      * 支持 **Whisper (本地)** 和 **AssemblyAI (云服务)** 两种转录服务，您可以根据需求选择。
      * 将提取的音频转录为日文 `SRT` 字幕文件。
  * **智能中文翻译**:
      * 支持 **DeepSeek** 和 **Gemini** 两种大语言模型翻译服务。
      * **字幕翻译**: 将日文 `SRT` 字幕翻译成中文 `SRT` 字幕，并智能地保留原始 `SRT` 格式。
      * **元数据翻译**: 自动抓取 JavBus 上的影片元数据（标题、演员、导演、类别等），并将其翻译成中文。
      * **本地缓存**: 为**演员、导演和类别**创建本地 `JSON` 缓存字典，避免重复调用翻译 `API`，显著降低成本和提高速度。
  * **双语字幕合并**: 将日文和中文 `SRT` 字幕合并为双语字幕文件（同时生成 `.ass` 和 `.srt` 格式）。
  * **元数据嵌入**: 将翻译后的影片元数据（如影片标题、发行日期、演员、导演、类别）嵌入到最终生成的双语字幕文件的开头，方便您一目了然地获取影片信息。
  * **状态管理**: 持久化处理状态，即使程序中断，也能从上次暂停的地方继续处理，避免重复劳动。
  * **多线程并行处理**: 利用生产者-消费者模型，各阶段（音频提取、转录、切片、翻译、聚合、合并、元数据抓取）并行工作，最大化系统资源利用率。

## 实现原理概览

整个流程通过一个基于**多线程和队列**的生产者-消费者模型实现，确保各个处理阶段能够并发高效地运行。

1.  **初始化与状态加载**:
      * `main.py` 启动时，首先加载上次保存的处理状态 (`status.json`)。
      * `scanner.py` 扫描指定视频目录，识别所有待处理的视频文件并提取 `AV` 番号。
      * 根据视频文件和当前状态，将待处理任务（例如：待提取音频、待转录、待翻译、待抓取元数据）分配到不同的任务队列中。
2.  **元数据抓取 (`metadata_crawler_worker`)**:
      * `movie_crawler.py` 负责从 **JavBus** 网站抓取影片详情页的 `HTML` 内容。
      * 它解析 `HTML` 提取影片的日文元数据（标题、发行日期、演员、导演、类别）。
      * 在翻译元数据时，它会优先查询本地的 `JSON` **缓存文件** (`actors_cache.json`, `genres_cache.json`, `directors_cache.json`)。如果缓存中没有，则调用 `text_translator.py` 进行翻译，并将原文和译文对存入缓存，以减少 `API` 调用。
      * 抓取和翻译后的元数据会存储在 `status.json` 中。
3.  **音频提取 (`audio_extract_worker`)**:
      * `preprocessor.py` 使用 `FFmpeg` 工具从视频文件中高效提取音频（例如 `.mp3` 格式）。
      * 提取的音频文件会被保存到指定的音频目录。
4.  **日文转录 (`transcription_worker`)**:
      * `transformer.py` 负责将音频文件转录成日文 `SRT` 字幕。
      * 它支持**本地 Whisper 模型**（通过 `openai-whisper` 或 `faster-whisper` 库）和**云端 AssemblyAI 服务**。您可以配置优先使用的服务，并在失败时回退。
      * 转录成功后，会删除中间音频文件以节省存储空间。
5.  **字幕切片与翻译 (`srt_slicer_worker`, `translation_slice_worker`, `translated_srt_aggregator_worker`)**:
      * `srt_slicer_worker` 将大型日文 `SRT` 字幕文件分割成小块（切片），以便更有效地发送给翻译 `API`。
      * `translation_slice_worker` 并行调用 `text_translator.py` 模块，将每个日文字幕切片翻译成中文。
      * `text_translator.py` 利用 **DeepSeek** 或 **Gemini** 大语言模型进行翻译。为了确保字幕格式的完整性，会使用特定的提示词引导模型返回 `SRT` 格式。
      * `translated_srt_aggregator_worker` 负责收集所有翻译后的字幕切片，并将它们重新组合成一个完整的中文 `SRT` 字幕文件。
6.  **双语合并与元数据嵌入 (`bilingual_worker`)**:
      * `bilingual_combiner.py` 接收日文和中文 `SRT` 字幕。
      * 它将这两个字幕合并为双语字幕，并同时生成 `.ass` 和 `.srt` 两种格式的文件。
      * **最关键的是**，它会读取 `status.json` 中保存的已翻译影片元数据，并将其格式化后**插入到生成的 `.ass` 和 `.srt` 字幕文件的最开头**。

这个流程中的每一步都独立且并发地运行，通过队列传递数据，并通过 `status.json` 记录进度，确保高效率和可靠性。

-----

## 依赖安装

在运行项目之前，您需要安装以下依赖：

### 1. Python 依赖

推荐使用 `pip` 安装。请确保您的 Python 版本为 3.8 或更高。

```bash
pip install -r requirements.txt
```

如果 `requirements.txt` 文件不存在，您可以手动创建或安装以下核心库：

```bash
pip install beautifulsoup4 requests python-dotenv pysrt openai google-generativeai pydub ffmpeg-python
# 对于 Whisper (本地转录，如果使用):
pip install openai-whisper  # 或者 faster-whisper (通常更快)
# pip install faster-whisper
# 对于 AssemblyAI (云转录，如果使用):
# pip install assemblyai
```

### 2. FFmpeg

本项目使用 `FFmpeg` 进行视频音频的提取。您需要根据您的操作系统安装 `FFmpeg`，并确保其可执行文件在系统的 `PATH` 环境变量中。

  * **Windows**:
    1.  访问 [FFmpeg 官网](https://ffmpeg.org/download.html) 下载 Windows 版本。
    2.  解压下载的压缩包到您喜欢的位置（例如 `C:\ffmpeg`）。
    3.  将 `FFmpeg` 的 `bin` 目录（例如 `C:\ffmpeg\bin`）添加到系统的 `PATH` 环境变量中。
    4.  打开新的命令行窗口，输入 `ffmpeg -version` 检查是否安装成功。
  * **macOS**:
    使用 Homebrew 安装：
    ```zsh
    brew install ffmpeg
    ```
  * **Linux (Ubuntu/Debian)**:
    ```bash
    sudo apt update
    sudo apt install ffmpeg
    ```

-----

## 配置 `.env` 文件

在项目根目录下创建一个名为 `.env` 的文件，并按以下格式配置您的目录路径和 `API` 密钥：

```dotenv
# --- 目录配置 ---
# 存放原始视频文件的目录
VIDEO_DIRECTORY=./videos

# 存放提取的音频文件的目录
AUDIO_DIRECTORY=./audios

# 存放日文SRT字幕文件的目录 (转录结果)
JAPSUB_DIRECTORY=./subtitles/japanese

# 存放中文SRT字幕文件的目录 (翻译结果)
SCHSUB_DIRECTORY=./subtitles/chinese

# 存放最终双语字幕文件的目录 (.ass 和 .srt)
SCH_JP_DIRECTORY=./subtitles/bilingual

# --- API 密钥配置 (至少配置您使用的服务) ---
# DeepSeek API Key (从 DeepSeek 官网获取，不免费)
DEEPSEEK_API_KEY="YOUR_DEEPSEEK_API_KEY"

# Gemini API Key (从 Google AI Studio 获取，每月有免费额度)
GEMINI_API_KEY="YOUR_GEMINI_API_KEY"

# AssemblyAI API Key (如果您选择使用 AssemblyAI 作为转录服务，每月有免费额度)
ASSEMBLYAI_API_KEY="YOUR_ASSEMBLYAI_API_KEY"
```

**重要提示**:

  * 请将 `YOUR_DEEPSEEK_API_KEY`, `YOUR_GEMINI_API_KEY` 和 `YOUR_ASSEMBLYAI_API_KEY` 替换为您的实际 `API` 密钥。
  * 根据您使用的服务，相应地配置密钥。如果您只使用 `Gemini` 进行翻译，可以不配置 `DeepSeek` 的密钥，反之亦然。

-----

## 如何运行

在配置好 `.env` 文件和安装所有依赖后，您可以通过以下命令运行项目：

```bash
python main.py
```

### `main.py` 启动参数可选项

您可以通过 `--transcriber` 参数指定首选的转录服务：

  * **使用本地 Whisper 进行转录 (默认)**
    ```bash
    python main.py --transcriber whisper
    ```
  * **使用 AssemblyAI 进行转录 (需要配置 `ASSEMBLYAI_API_KEY`)**
    ```bash
    python main.py --transcriber assemblyai
    ```

### Windows 一键启动脚本

`run.bat` 和 `run_organizer.bat` 默认会自动激活名为 `whisper` 的 conda 环境后再运行主程序或 organizer。这是开发者的个人习惯，**试用前请根据你自己的环境修改这两个 bat 文件中的 `ENV_NAME` 变量为你实际的环境名**，否则会激活失败。

如果你没有使用 conda 环境，也可以直接用 `python main.py` 或 `python av_organizer_pro.py` 启动。

---

### Python 环境配置教程

#### 1. 推荐使用 Anaconda/Miniconda

- [Anaconda 官网下载](https://www.anaconda.com/products/distribution)
- [Miniconda 官网下载](https://docs.conda.io/en/latest/miniconda.html)

**安装步骤：**
1. 下载并安装 Anaconda 或 Miniconda。
2. 打开 Anaconda Prompt（或命令行），创建新环境（如 aurora_env）：
   ```
   conda create -n aurora_env python=3.10 -y
   conda activate aurora_env
   ```
3. 安装依赖：
   ```
   pip install -r requirements.txt
   ```

#### 2. 也可使用 Python 自带 venv 虚拟环境

**步骤：**
1. 安装 Python（建议 3.8 及以上）。
2. 在项目根目录下创建虚拟环境：
   ```
   python -m venv aurora_venv
   ```
3. 激活虚拟环境：
   - Windows:
     ```
     aurora_venv\Scripts\activate
     ```
   - macOS/Linux:
     ```
     source aurora_venv/bin/activate
     ```
4. 安装依赖：
   ```
   pip install -r requirements.txt
   ```

---

### 第一次启动流程 (Windows 用户)

为了确保环境隔离和依赖管理，强烈建议使用虚拟环境运行本项目。

1.  **创建并激活虚拟环境 (Conda)**:
    打开命令行（如 Anaconda Prompt 或 PowerShell），执行以下命令：

    ```batch
    @echo off
    echo 正在创建名为 'aurora_env' 的 Conda 虚拟环境...
    conda create -n aurora_env python=3.12 -y

    echo 正在激活虚拟环境 'aurora_env'...
    call conda activate aurora_env

    echo 正在安装项目依赖...
    pip install -r requirements.txt

    echo 虚拟环境设置完成。
    echo 您现在可以运行项目了：python main.py --transcriber whisper
    echo 或者：python main.py --transcriber assemblyai
    pause
    ```

    将上述内容保存为 `setup_env.bat` 文件（例如在项目根目录），然后双击执行即可。

2.  **运行项目**:
    在 `setup_env.bat` 脚本执行完毕后，您会看到提示。此时，您可以在同一个命令行窗口中直接运行 `main.py`。

### 日志文件

  * `process.log`: 记录整个处理流程的详细信息，包括任务进度、成功/失败日志等。
  * `translate.log`: 专门记录翻译模块的日志，方便排查翻译相关的 `API` 调用问题。

-----

## 目录结构 (示例)

```
.
├── main.py
├── scanner.py
├── preprocessor.py
├── transformer.py
├── text_translator.py
├── movie_crawler.py
├── bilingual_combiner.py
├── status.py
├── prompt.txt
├── .env
├── process.log
├── translate.log
├── status.json           # 运行状态持久化文件
├── videos/               # 存放您的原始视频文件
│   └── example-123.mp4
│   └── ...
├── audios/               # 存放提取的音频文件 (中间产物，处理完后会被删除)
│   └── example-123.mp3
│   └── ...
├── subtitles/
│   ├── japanese/         # 存放日文SRT字幕文件
│   │   └── example-123.srt
│   │   └── ...
│   ├── chinese/          # 存放中文SRT字幕文件
│   │   └── example-123.srt
│   │   └── ...
│   └── bilingual/        # 存放最终的双语字幕文件 (.ass 和 .srt)
│       ├── example-123-sch-jap.ass
│       ├── example-123-sch-jap.srt
│       └── ...
└── metadata_cache/       # 存放翻译缓存字典
    ├── actors_cache.json
    ├── genres_cache.json
    └── directors_cache.json
```

-----

## 注意事项

  * **API 额度与费用**: 使用 `DeepSeek`, `Gemini` 或 `AssemblyAI` 等云服务会产生费用。请留意您的 `API` 额度，并合理使用本地缓存机制。
  * **网络稳定性**: 翻译和元数据抓取依赖于网络连接。请确保网络稳定。
  * **JavBus 访问**: 频繁的网页抓取可能导致您的 `IP` 被 JavBus 临时或永久封禁。本项目已加入基本的重试和延迟机制，但大规模使用时仍需谨慎，或考虑使用代理。
  * **HTML 结构变化**: JavBus 网站的 `HTML` 结构可能会更新，这可能导致 `movie_crawler.py` 中的解析逻辑失效。如果遇到元数据抓取失败，可能需要检查并更新 `parse_movie_html` 函数。
  * **字幕准确性**: 大模型翻译可能存在少量不准确或不自然的表达。
  * **FFmpeg 问题**: 如果您在音频提取阶段遇到问题，请检查 `FFmpeg` 是否正确安装并配置到 `PATH`。

感谢您使用本工具！希望它能为您的视频处理工作带来便利。