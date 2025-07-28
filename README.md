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

      * `VIDEO_LIBRARY_DIRECTORY`: **【必需】** 用于存放所有处理完成、已归档影片的最终媒体库路径。建议设置一个空目录。

          * 示例: `VIDEO_LIBRARY_DIRECTORY=D:/MyMedia/AV_Library`

      * **API 密钥**: 根据您拥有的服务，填写对应的API Key。

          * `GEMINI_API_KEY`: Google Gemini API 密钥，拥有慷慨的免费额度，**推荐配置**。
          * `DEEPSEEK_API_KEY`: DeepSeek API 密钥。
          * `ASSEMBLYAI_API_KEY`: AssemblyAI API 密钥，用于云端语音转写，拥有免费额度。

## ▶️ 运行程序 (Running the Program)

请确保您的虚拟环境已激活。所有命令都在项目根目录下运行。

#### 主任务指令 (必需)

  * `process`: **(最常用)** 执行完整的自动化处理流水线。
    ```bash
    python main.py process
    ```
  * `organize`: 将所有已完成处理的影片进行归档和索引。
    ```bash
    python main.py organize
    ```
  * `cleanup`: **(安全模式)** 扫描源目录，并**仅报告**可以被安全删除的空目录。
    ```bash
    python main.py cleanup
    ```
  * `reconcile`: 仅执行状态同步，用于在您手动移动或删除文件后，校准 `status.json`。
    ```bash
    python main.py reconcile
    ```

#### 可选参数 (可选)

  * `--force`: 强制重新执行所有任务，即使它们之前已经完成。
    ```bash
    python main.py process --force
    ```
  * `--execute`: **【危险】** 与 `cleanup` 任务配合使用，在报告后**真实地执行删除**操作。
    ```bash
    # 强烈建议先运行一次不带 --execute 的 cleanup
    python main.py cleanup --execute
    ```

#### 推荐工作流程

1.  将新下载的影片放入您配置的 `VIDEO_SOURCE_DIRECTORY` 目录。
2.  运行 `python main.py process`。程序将自动处理所有可处理的任务。您可以随时中断，下次运行会从断点继续。
3.  当您看到日志显示任务已全部处理完毕后，运行 `python main.py organize` 进行归档和索引。
4.  （可选）运行 `python main.py cleanup` 查看清理报告，然后运行 `python main.py cleanup --execute` 清理源目录。

<!-- end list -->
# 👨‍💻 开发者与设计理念 (For Developers & Designers)

本部分旨在深入阐述 Aurora 项目的架构设计、技术选型以及在开发过程中遇到的关键问题与解决方案。它不仅是代码的说明，更是整个项目从构思到成熟的“心路历程”。

## 📐 核心架构原则

在整个开发过程中，我们始终遵循以下几个核心设计原则，它们是构建这个健壮、可维护系统的基石。

#### 1. 模块化与职责分离 (Modularity & Separation of Concerns)
项目被拆分为多个高度专一的模块（`scanner`, `crawler`, `translator` 等）。每个模块只负责一件事情并把它做好。这种设计使得代码易于理解、独立测试和未来扩展。

#### 2. “工人/核心”分层模式 ("Worker/Core" Layered Pattern)
这是我们最重要的架构模式之一。每个处理模块内部都分为两层：
* **工人层 (Worker Layer)**: 对外暴露的公共接口，负责与外部系统（文件系统、状态管理器）交互、处理流程控制（如幂等性检查）和统一的异常封装。
* **核心层 (Core Layer)**: 模块的“心脏”，负责纯粹的业务逻辑（如HTML解析、文本翻译、音频处理）。它不依赖于项目的其他部分，易于进行单元测试。

#### 3. 中央化状态管理与无状态工人 (Centralized State Management & Stateless Workers)
为了解决多进程环境下的 `pickle` 错误和状态一致性问题，我们确立了此原则：
* `StatManager` 作为**唯一**的状态管理者，只在主进程 (`main.py`) 中被实例化和调用。
* 所有的“工人”函数都是**无状态的**，它们不持有或直接修改全局状态，而是通过函数返回值向主进程报告工作成果，由主进程统一更新状态。

#### 4. 面向失败的设计 (Design for Failure)
我们假设任何一步操作都可能失败，尤其是在涉及网络I/O和外部依赖时。
* **统一异常接口**: 工人函数只对外抛出 `FatalError` (核心流程中断) 和 `IgnorableError` (辅助流程中断) 两种高级别异常，主调度器只需关心这两种情况。
* **自动重试与熔断**: 对于网络请求（爬虫、API调用），我们内置了 `tenacity` 自动重试机制。对于云服务（如AssemblyAI），我们设计了“熔断器”，在连续失败后能自动切换到备用方案（本地Whisper）。

#### 5. 用户修改优先 (User Override Principle)
系统必须尊重用户的干预。
* **幂等性**: 所有工人函数都具备幂等性，重复执行不会产生副作用。通过检查文件存在性和时间戳，避免覆盖用户可能已经手动修改过的最终产物（如精修过的字幕）。
* **审查与同步**: 通过独立的 `organize` 和 `cleanup` 工具，系统能学习用户对 `metadata.json` 的修改，并将其同步到全局缓存和其他相关文件中，形成一个智能的反馈闭环。

## 💡 关键技术难题与演进之路

这个项目并非一蹴而就，我们在开发过程中遇到了多个经典的技术挑战。正是解决这些问题的过程，塑造了项目如今的健壮架构。

#### 1. 问题：`pickle` 错误与进程安全
* **挑战**: 在项目初期，我们尝试将 `StatManager` 对象直接传递给 `ProcessPoolExecutor` 中的子进程，导致了经典的 `TypeError: cannot pickle '_thread.lock' object` 错误，因为锁对象无法跨进程传递。
* **解决方案**: 我们进行了一次重要的架构重构，确立了**“中央化状态管理与无状态工人”**原则。工人函数不再接收 `StatManager`，而是改为返回一个包含结果的字典。所有状态的更新操作，都集中在 `main.py` 的主进程中，根据工人返回的结果来执行。这彻底解决了 `pickle` 错误，并让系统状态的管理更加安全和清晰。

#### 2. 问题：GPU 独占与服务熔断
* **挑战**: 本地Whisper转写需要独占GPU资源，多个进程同时调用会导致显存崩溃。同时，如果首选的云服务（AssemblyAI）宕机，所有进程都会反复尝试并超时，浪费大量时间。
* **解决方案**: 我们引入了 `multiprocessing.Manager` 来创建跨进程共享对象：
    1.  **`gpu_lock = manager.Lock()`**: 创建一个全局GPU锁，并传递给每个 `transcriber` 工人。工人在调用Whisper前必须获取该锁，确保了任何时候只有一个进程能使用GPU。
    2.  **`shared_status = manager.dict()`**: 创建一个共享字典作为“熔断器”。当第一个工人发现AssemblyAI失败时，它会立刻改变这个共享字典中的状态。后续所有新任务都会读取这个新状态，直接跳过AssemblyAI，使用备用方案，实现了智能的、快速的故障切换。

#### 3. 问题：流水线“假死”与事件驱动
* **挑战**: 最初的 `main.py` 调度器是一个“分批处理器”，它在开始时生成所有可执行的任务（例如，所有音频提取），等待它们全部完成后才退出。这导致流程在每个阶段之间都存在“空窗期”，无法实现真正的流水线作业。
* **解决方案**: 我们将 `main.py` 的主循环重构为一个**“事件驱动”的循环流水线**。主循环在一个 `while True` 中不断地进行“状态诊断 -> 派发任务 -> 处理结果”的循环。当一个任务（如音频提取）完成后，主循环会立刻接收到这个“完成事件”，并马上为**这一个**番号诊断出下一步任务（字幕转写）并提交，而无需等待其他番号。这使得任务能够在不同影片之间以最高效率“接力”下去。

#### 4. 问题：翻译质量的“天花板”
* **挑战**: 直接将单句字幕发送给LLM翻译，效果往往不佳，缺乏连贯性和准确性。
* **解决方案**: 我们设计并实现了**“智能上下文增强”**策略：
    * **宏观上下文**: 将影片的元数据（标题、演员等）动态注入到系统提示中，让LLM了解翻译的背景。
    * **微观上下文**: 在翻译字幕切片时，采用“滑动窗口”，将上一个切片的原文和译文作为上下文一同发送，让LLM能理解对话的来龙去脉。

## 📂 模块概览

* **`main.py`**: **总调度器**。项目的唯一入口，负责CLI、环境初始化、并发管理和流水线调度。
* **`config.py`**: **配置中心**。加载 `.env` 和 `prompt.txt`，为整个项目提供统一的配置常量。
* **`logging_config.py`**: **日志中心**。配置全局的分级日志系统。
* **`exceptions.py`**: **异常中心**。定义项目中统一的 `FatalError` 和 `IgnorableError`。
* **`status_manager.py`**: **状态管理器**。封装了所有对 `status.json` 的线程安全读写和同步逻辑，只在主进程中使用。
* **`scanner.py`**: **扫描器**。负责扫描文件系统，并从文件名中准确识别番号。
* **`movie_crawler.py`**: **元数据工人**。负责抓取和翻译影片元数据。
* **`audio_extractor.py`**: **音频提取工人**。负责从视频中提取完整的音轨。
* **`transcriber.py`**: **音频转写工人**。负责将音频转写为日文SRT，并管理云服务/本地模型的切换。
* **`text_translator.py`**: **文本翻译工人/引擎**。负责将日文SRT高质量地翻译为中文。
* **`subtitle_generator.py`**: **字幕生成工人**。负责将翻译稿合并为带特效的专业级双语字幕。
* **`organizer.py`**: **媒体库管家**。负责最终的成品归档、索引建立和源目录清理。