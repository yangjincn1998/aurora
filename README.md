# 极光字幕 (AURORA, Automated Universal Resources Orchestrator of Rich Av) - 全自动AV媒体库管理工具

![Python Version](https://img.shields.io/badge/python-3.10+-blue.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)

**Aurora** 是一个强大的自动化工具，旨在将您杂乱的AV影片收藏，转变为一个带有高质量双语字幕、信息丰富的标准化媒体库。

---

# 📖 用户指南 (User Guide)

本部分面向希望直接使用本工具的用户。

## ✨ 主要功能

* **全自动流水线**: 从原始视频文件到生成带特效的双语字幕，全程自动化处理。
* **智能番号识别**: 采用级联正则匹配策略，能从各种复杂、不规范的文件名中准确提取番号。
* **多AI服务支持**:
    * **语音转写**: 支持云端 `AssemblyAI` 和本地 `Whisper` (通过 `faster-whisper` 高性能引擎) 两种模式，并可在云服务失败时自动**熔断**并切换到本地模式。
    * **文本翻译**: 支持 `Google Gemini` 和 `DeepSeek` 两种大语言模型，并可自动回退。
* **高质量字幕生成**:
    * **智能上下文翻译**: 在翻译字幕时，同时注入影片元数据（宏观）和前后对话（微观）作为上下文，极大提升翻译的准确性和流畅度。
    * **专业级ASS特效**: 自动生成带有动态元数据片头（淡入淡出效果）和分层对话样式（中上日下）的 `.ass` 特效字幕。
* **健壮的状态管理**: 所有处理进度都会被记录，程序可随时中断和续行。通过**文件系统同步**机制，能智能处理用户手动的删除和移动操作。
* **媒体库整理与索引**: 自动将成品归档到以番号命名的目录中，并创建按演员、类别、导演分类的快捷方式索引，方便浏览。
* **高性能并发处理**: 采用“多进程（处理不同影片）+多线程（处理单个影片内部任务）”的二级并发模型，最大化利用系统资源。

## 🚀 快速上手

对于有经验的用户，只需四步即可运行：

1.  **安装环境**: 确保您已安装 `Python 3.10+` 和 `FFmpeg`。
2.  **安装依赖**: 在项目目录下运行 `pip install -r requirements.txt`。
3.  **配置**: 复制 `example.env` 为 `.env`，并填入您的**视频源目录**和**媒体库目录**路径，以及至少一个API Key。
4.  **运行**: `python main.py process`

## 📋 环境设置 (Environment Setup)

#### 1. 安装 Python
本程序需要 **Python 3.10** 或更高版本。
-   请从 [Python官方网站](https://www.python.org/downloads/) 下载并安装。
-   在安装时，请务必勾选 **"Add Python to PATH"** 选项。

#### 2. 安装 FFmpeg (关键外部依赖)
FFmpeg 是处理音视频的开源工具，是本程序**提取音频**功能的核心。
-   请访问 [FFmpeg 官网](https://ffmpeg.org/download.html) 下载适用于您操作系统的版本。
-   **重要**: 解压后，请务必将其 `bin` 目录的完整路径，添加到您操作系统的**环境变量 `Path`** 中。
-   验证安装: 打开一个新的命令行窗口，输入 `ffmpeg -version`，如果能看到版本信息，说明安装成功。

#### 3. 下载项目
使用 Git 克隆本项目到您的本地电脑：
```bash
git clone [https://github.com/yangjincn1998/aurora.git](https://github.com/yangjincn1998/aurora.git)
cd aurora
````

#### 4\. 创建虚拟环境与安装依赖

为了避免与您系统上其他Python项目产生冲突，强烈建议使用虚拟环境。

**a) 创建并激活环境 (推荐使用 venv):**

```bash
# 在项目根目录下创建虚拟环境
python -m venv .venv

# 激活虚拟环境
# Windows:
.venv\Scripts\activate
# macOS / Linux:
source .venv/bin/activate
```

**b) 安装项目依赖:**
在激活虚拟环境后，运行以下命令来安装所有必需的 Python 库：

```bash
pip install -r requirements.txt
```

## ⚙️ 配置 (Configuration)

在首次运行前，您需要配置程序的行为和您的API密钥。

1.  在项目根目录下，找到 `example.env` 文件。

2.  **复制** 并 **重命名** 该文件为 `.env`。

3.  使用文本编辑器打开 `.env` 文件，根据您的实际情况修改：

      * `VIDEO_SOURCE_DIRECTORY`: **【必需】** 您存放原始、杂乱视频文件的目录路径。程序将扫描这里。

          * 示例: `VIDEO_SOURCE_DIRECTORY=D:/Downloads/NewVideos`

      * `VIDEO_LIBRARY_DIRECTORY`: **【必需】** 用于存放所有处理完成、已归档影片的最终媒体库路径。建议设置一个空目录（此功能尚未实现）。

          * 示例: `VIDEO_LIBRARY_DIRECTORY=D:/MyMedia/AV_Library`

      * **API 密钥**: 根据您拥有的服务，填写对应的API Key。

          * `GOOGLE_API_KEY`: Google Gemini API 密钥，拥有一定免费额度，申请次数超了只能等冷却，作为deepseek的运行失败的候选项。
          * `DEEPSEEK_API_KEY`: DeepSeek API 密钥。**推荐配置, 不想设置代理可以无脑用这个, 胜在稳定**
          * `ASSEMBLYAI_API_KEY`: AssemblyAI API 密钥，用于云端语音转写，拥有免费额度。

## ▶️ 运行程序 (Running the Program)

请确保您的虚拟环境已激活。所有命令都在项目根目录下运行`linear.py`。

#### 推荐工作流程

1.  将新下载的影片放入您配置的 `VIDEO_SOURCE_DIRECTORY` 目录。
2.  运行 `python linear.py`。程序将自动处理所有可处理的任务。您可以随时中断，下次运行会从断点继续。
3.  后续归档，索引等功能尚在开发中

## 提示

提取的日文内容会有大量无意义的语气词，翻译这些文档时deepseek会生成大量无意义的重复回答，占用消息空间，导致翻译失败，目前没有好的解决方案。如果在日志中发现某部影片的翻译由于大模型api返回长度而失败，可以确定原因是日文字幕质量太差
 
## 后续可能的迭代开发内容
1.实现索引功能

2.接入更多大模型

3.自适应设置黑名单，忽略翻译不成功的视频

4.创建常见撰写错误对照词典，引导大模型纠正转写的日文字幕错误

5.实现全流水线高并发