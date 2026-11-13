# Third-party components

Checked on 2026-09-27. This ledger covers components required by the current
Chutku runtime and locally distributed model/runtime artifacts. It is not a
license for Chutku's own source, which is MIT (`LICENSE`).

| Component | Pinned version / revision | Source | License | Integrity / notice |
|---|---|---|---|---|
| NumPy | 2.5.3 | https://github.com/numpy/numpy | BSD-3-Clause with bundled code under 0BSD, MIT, Zlib and CC0-1.0 | Version locked in `requirements.lock`; installed package metadata is authoritative for bundled notices. |
| python-sounddevice | 0.5.6 | https://github.com/spatialaudio/python-sounddevice | MIT | Version locked in `requirements.lock`. |
| CFFI | 2.1.1 | https://github.com/python-cffi/cffi | MIT-0 | Transitive runtime dependency locked in `requirements.lock`. |
| pycparser | 3.0 | https://github.com/eliben/pycparser | BSD-3-Clause | Transitive runtime dependency locked in `requirements.lock`. |
| PortAudio binaries bundled by python-sounddevice | package release 0.5.6 | https://github.com/spatialaudio/portaudio-binaries | MIT; ASIO-enabled variants also contain Steinberg ASIO material | Chutku uses the default Windows input path, not an ASIO-specific API. The `*-asio.dll` variants are excluded from the app package (`scripts/build_release.py` strips them and the stage check refuses them). |
| llama.cpp Windows CPU runtime | b11181 | https://github.com/ggml-org/llama.cpp/releases/tag/b11181 | MIT | Archive SHA-256 `d0d65ea389d16bf1cf29116589056f97b913102e6845c65664bf04e012e0bada`; server executable SHA-256 `df276e070797c3b72e92a2780adb441d7b36f871b5fa71dc3d6d9e78a34ac782`; full text in `vendor/llama-b11181/LICENSE-llama.cpp.txt`. |
| LLVM OpenMP runtime distributed with llama.cpp | bundled with b11181 | https://github.com/llvm/llvm-project | Apache-2.0 WITH LLVM-exception | Full text in `vendor/llama-b11181/LICENSE-LLVM-OpenMP`. |
| Qwen3-4B-Q4_K_M GGUF | revision `bc640142c66e1fdd12af0bd68f40445458f3869b` | https://huggingface.co/Qwen/Qwen3-4B-GGUF | Apache-2.0 | SHA-256 `7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5`; full text in `models/Qwen3-LICENSE.txt`. |
| llama.cpp Windows Vulkan runtime (GPU, added 2026-09-30) | b11181 | https://github.com/ggml-org/llama.cpp/releases/tag/b11181 | MIT | Archive SHA-256 `e2f84f99359be043722cd11ba4388ddddf2eac072032924a1ee84164890d57b9` (matches GitHub release digest); every file in `vendor/llama-b11181-vulkan/` is pinned by the directory digest in `models/manifest.json` (`gpu_runtime.directory_sha256`). |
| faster-whisper | 1.2.1 | https://github.com/SYSTRAN/faster-whisper | MIT | Locked in `requirements.lock`. |
| CTranslate2 | 4.8.2 | https://github.com/OpenNMT/CTranslate2 | MIT | Transitive; locked. |
| Hugging Face tokenizers / huggingface_hub | 0.23.2 / 1.32.0 | https://github.com/huggingface | Apache-2.0 | Transitive; locked. |
| PyAV | 18.1.0 | https://github.com/PyAV-Org/PyAV | BSD-3-Clause (bundles FFmpeg libraries under LGPL-2.1+) | Transitive dependency of faster-whisper; Chutku passes in-memory PCM and does not use FFmpeg decoding. Review FFmpeg LGPL notices before redistribution. |
| ONNX Runtime | 1.30.0 | https://github.com/microsoft/onnxruntime | MIT | Transitive (faster-whisper VAD); locked. |
| faster-whisper-small (CTranslate2 conversion of OpenAI Whisper small) | revision `536b0662742c02347bc0e980a01041f333bce120` | https://huggingface.co/Systran/faster-whisper-small | MIT (OpenAI Whisper weights are MIT) | Directory digest `73f633e435cae94022618aab68c326c61fbe2b4c5bc149faf8b9df67f4ca0296` checked before loading (`models/manifest.json` → `stt`). |
| pypdf | 6.21.4 | https://github.com/py-pdf/pypdf | BSD-3-Clause | Locked in `requirements.lock`; used only to read PDF text locally. |
| andrej-karpathy-skills (Karpathy coding guidelines) | copied 2026-11-05 | https://github.com/forrestchang/andrej-karpathy-skills | MIT | Text in `.claude/skills/karpathy-guidelines/SKILL.md` (adapted section marked), summarised in `AGENTS.md`. Development guidance only, not runtime code. |
| agent-desktop (vercel-labs) | 1.2.0 (npm) | https://github.com/vercel-labs/agent-desktop | Apache-2.0 | Pinned with its npm integrity hash in `tools/package-lock.json`; installed by `npm ci --prefix tools`, not committed. Chutku runs its CLI as a separate process (`chutku/tools/desktop.py`). |
| agent-browser (vercel-labs) | 0.27.0 (npm) | https://github.com/vercel-labs/agent-browser | Apache-2.0 | Pinned with its npm integrity hash in `tools/package-lock.json`; installed by `npm ci --prefix tools`, not committed. Chutku runs its CLI as a separate process (`chutku/tools/signed_in_browser.py`). |
| Ponytail skills (ponytail, -review, -audit, -debt) | v5.3.3, commit `96608e0`, copied 2026-11-05 | https://github.com/DietrichGebert/ponytail | MIT | Text in `.claude/skills/ponytail*/SKILL.md`, license in `.claude/skills/ponytail/LICENSE.txt`. Its hooks, task ledger and webhook are not used. Development guidance only. |
| openWakeWord | 0.6.0 | https://github.com/dscripka/openWakeWord | Code Apache-2.0; its pre-trained models CC BY-NC-SA 4.0 (non-commercial, attribution, share-alike) | Locked in `requirements.lock`. The model licence means the app package is for non-commercial use; named in the package `NOTICE` (W7, 2026-11-07). |
| espeak-ng (through espeakng-loader) | espeakng-loader 0.2.4 | https://github.com/espeak-ng/espeak-ng | GPL-3.0-or-later | Locked in `requirements.lock`; used by the Kokoro voice for phonemes. The licence travels in the package's `*.dist-info`; source link in the package `NOTICE`. |
| cryptography (pyca) | 50.0.2 | https://github.com/pyca/cryptography | Apache-2.0 OR BSD-3-Clause | Locked with hashes in `requirements.lock`; AES-256-GCM for the relay's end-to-end encryption (W6, 2026-11-07). |

Checked additions on 2026-09-30. Gemini (Google) is an optional network service,
not a distributed component; it is used only if the owner grants `cloud.gemini`.

Windows System.Speech, SAPI and PowerShell are operating-system facilities and
are not redistributed by this repository. The model/runtime pins used by code
are also machine-readable in `models/manifest.json`; setup verifies their hashes.

Chutku's own source is MIT (`LICENSE`). The app package (2026-11-07, `scripts/build_release.py`) excludes the
ASIO DLLs and ships `NOTICE`, this file and each Python package's own licence in its `*.dist-info` folder.
