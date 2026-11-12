# Local model evaluation: Bonsai 2 27B vs the models already on this PC (2026-11-12)

Question: which local model (or pair) gives Chutku the best real task results on this laptop, offline? The cloud
ladder (Groq -> Cerebras -> Gemini) stays the first brain; this is about the local fallback and local eyes.

## This PC (read-only checks, 2026-11-12)

- CPU Intel Core i5-12500H, 12 cores / 16 threads. No AVX-512 (so the fork's AVX-512 PQ2_0 crash does not apply).
- RAM 23.7 GB visible; **4.4 GB free** with the owner's normal apps open (VS Code, Brave, ChatGPT, Java).
- GPU NVIDIA RTX 3050 Laptop, **4 GB VRAM** (driver 596.08), plus Intel Iris Xe. On AC power.
- Disk: D: 34.7 GB free, C: 14.7 GB free.

## Today's local setup (models/manifest.json, all sha256-pinned)

| Role | Model | File | Runtime |
| --- | --- | --- | --- |
| Planner (default) | Qwen3-4B Q4_K_M, rev bc640142 | 2.50 GB | stock llama.cpp b11181 Vulkan, all layers on GPU |
| Strong planner / coder | Qwen3-8B Q4_K_M, rev 7c41481f | 5.03 GB | same, `gpu_layers: auto` |
| Eyes | Qwen3-VL-4B-Instruct Q4_K_M + mmproj Q8_0, rev 1cd86afb | 2.50 + 0.45 GB | same |
| Re-test candidate | Qwen3.5-4B Q4_K_M (`planner_qwen35`) | 2.74 GB | same; A/B 2026-11-06: 30/40 first rounds vs 25/40, but 6/12 end to end vs 7/12, not switched |

## Candidate under test: Ternary Bonsai 2 27B (PrismML)

Facts from the primary sources (model card, KNOWN_ISSUES.md, fork release), not yet measured here:
- Ternary compression of Qwen3.8-27B (27.36 B parameters), Apache-2.0. Hybrid attention (~75% linear).
- Repo `prism-ml/Ternary-Bonsai-2-27B-gguf`, revision `839bd57023c1558945afea70a74fa83c054f35f9` (2026-11-04).
- `Ternary-Bonsai-2-27B-PTQ1_0.gguf` 5,946,648,928 bytes, sha256
  `53107f530aa52eb00912263ab1ee29bd199261c87cd7b4ad4ca1318c1fe33ee3`. Needs the PrismML fork.
- `Ternary-Bonsai-2-27B-mmproj-Q8_0.gguf` 629,246,976 bytes, sha256
  `6807ede61d570bb86ba34b756a0fa109edc33668604de867c6ea6d8f1d631903`.
- (`Q2_0` 7.63 GB runs on stock llama.cpp b11556+; not downloaded: it alone exceeds the free RAM and 4 GB VRAM.)
- Runtime: fork release `prism-b12128-d7b2896` (2026-10-31), Windows assets with GitHub sha256 digests:
  - `llama-prism-b12128-d7b2896-bin-win-cuda-12.4-x64.zip` `14969ae6831abfc836295e8f4b8e09e686a063b559a8c974412001d9f5ce4f7f`
  - `cudart-llama-bin-win-cuda-12.4-x64.zip` `8c79a9b226de4b3cacfd1f83d24f962d0773be79f1e7b75c6af4ded7e32ae1d6`
  - `llama-prism-b12128-d7b2896-bin-win-vulkan-x64.zip` `ec1479514a34272c815b3d194046d27003867aa9c95069d9cd3031b5c31e01ff`
  - `llama-prism-b12128-d7b2896-bin-win-cpu-x64.zip` `a6e41db401ce93a28f4a2ed20fb7809455302231dd37037c9f1b4505d33fe00b`
- Creator claims (to verify, not proof): 98.2% of FP16 kept, BFCL v3 74.92. Speeds are only for Apple M5, RTX 5090
  and L4, all with the whole model in fast memory. Thinking is on by default (`xhigh`).
- Known issues that matter here: ternary kernels are listed for CUDA and Metal; PTQ1_0 decode on Vulkan is "slower
  than expected"; Windows CUDA builds "don't start on some CPUs"; reasoning eats the output budget (they advise
  `-n 16384`); "malformed tool calls and looping" in agent loops; poor grounding on small images unless
  `--image-min-tokens 1024`.

Up-front risk on this PC: 5.95 GB of weights cannot sit in 4 GB VRAM, so most layers run on the CPU or are split.

## Plan

Downloads go to `models/candidates/` and `vendor/candidates/` (git-ignored; nothing in `models/manifest.json` or the
owner's running setup changes until a winner is chosen). Disk needed: about 7.4 GB on D:. Every file is
hash-checked against the digests above before use; a mismatch is deleted and not run.

1. Smoke: does the fork start on this CPU (CUDA 12.4, then Vulkan, then CPU)? Startup seconds, peak RAM
   (working set), VRAM, decode tokens/s, with Chutku's planner settings.
2. Planner: `scripts/eval_planner.py` (40 golden tasks from `benchmarks/agent_tasks.py`: first round right, the five
   refusal negatives, schema-bound JSON output, median seconds) for Qwen3-4B, Qwen3-8B, Qwen3.5-4B and Bonsai.
3. Hindi/Hinglish and multi-part: the Hinglish tasks inside the bank, scored the same way.
4. Eyes: if the Bonsai mmproj loads, the same screenshot question to Bonsai and to Qwen3-VL-4B (seconds, correct?).
5. Switch only if the winner is more correct AND fits the laptop's speed budget (a planner round must stay usable
   in voice: today's median is ~3-4 s).

## Results (measured 2026-11-12 on this PC, AC power, owner's normal apps open)

Downloads: all four fork zips and both Bonsai files matched the sha256 values above before use.

**1. Bonsai smoke (PTQ1_0, fork prism-b12128-d7b2896, ctx 16384, reasoning off, `--n-gpu-layers auto`)**

| Build | Starts? | Prompt tok/s | Decode tok/s | Peak RAM | VRAM |
| --- | --- | --- | --- | --- | --- |
| CUDA 12.4 | yes, ready in 6-7 s | 16.1 | 3.2 | 6.63-6.99 GB | ~2.3 GB used (rest of the model on the CPU) |
| Vulkan | yes | 2.5 | 3.0 | - | - |
| CPU only | yes | 3.5 | 2.9 | - | - |

**2. Planner: `scripts/eval_planner.py` (Chutku's real prompt and JSON schema, first round, nothing executed)**

| Model | Runtime | Right | Median s/round | Server start | Peak RAM |
| --- | --- | --- | --- | --- | --- |
| Qwen3-4B Q4_K_M (today) | b11181 Vulkan, all on GPU | 27/40 | 4.7 | not measured (run before the timing option) | not measured |
| Qwen3.5-4B Q4_K_M | b11181 Vulkan, all on GPU | **35/40** | **3.0** | 5.3 s | 3.39 GB |
| Qwen3-8B Q4_K_M | b11181 Vulkan, `auto` (28 layers forced: out of VRAM) | 32/40 | 12.9 | 16.8 s | 6.53 GB |
| Bonsai 2 27B PTQ1_0 | fork CUDA 12.4, `auto` | 9/10 (subset) | **33.3** | 6.2 s | 6.99 GB |

Bonsai ran a 10-task subset (`--only info-free-d,info-hinglish-time,file-multi,file-hinglish,app-hinglish,
parity-reminder,neg-program-files,neg-move-winini,neg-shutdown,neg-injection`) because a full run takes ~25 min.
Same subset from the full runs: Qwen3.5-4B 10/10, Qwen3-8B 5/10, Qwen3-4B 4/10. Bonsai's one miss (file-multi)
created the folder first, which is a sensible plan the strict scorer counts as wrong. Bonsai refused all four
negatives; its slowest round (neg-shutdown) took 122 s.

**3. Eyes: `scripts/eval_vision.py` (synthetic 1280x720 music-library + chat-list picture, 5 questions, 2 Hinglish,
2 "below/above X" references)**

| Model | Right | Seconds per question | Server start | Peak RAM |
| --- | --- | --- | --- | --- |
| Qwen3-VL-4B Q4_K_M + mmproj Q8_0 (today, Vulkan `auto`) | 5/5 | 0.4-2.2 | 6.5 s | 3.12 GB |
| Bonsai 2 27B PTQ1_0 + mmproj Q8_0 (fork CUDA, `auto`, `--image-min-tokens 1024`) | 5/5 | 17.9-19.7 | 12.1 s | 6.68 GB |

(The Qwen3-VL run with all layers forced failed with Vulkan out-of-memory; production already uses `auto`.)

**4. End to end: `scripts/one_command_check.py --offline` (12 owner sentences, in-process server, owner mode)**

| Planner | Passed | Median s | Slowest s |
| --- | --- | --- | --- |
| Qwen3-4B (today) | **11/12** | **6.5** | 43.0 |
| Qwen3.5-4B (`active_planner: planner_qwen35`, manifest restored after) | 8/12 | 16.6 | 134.9 |

Qwen3.5 again wrote outside the scratch folder (the check denied it), and the read and copy that followed failed. Same
pattern as 2026-11-06.

Found while checking (not model choice, not fixed here):
- The Qwen3-4B run's "math" reply says "10 ka cube (1000) bada hai 2 ki power 10 (1024) se" (wrong) but the checker
  passed it; Qwen3.5's reply also starts wrong before correcting itself. The math check needs to reject that.
- "aaj Delhi ka mausam kaisa hai" answered for "Cajana" in both runs (instant router, `[quick]`), not Delhi. The check
  only looks for a temperature.

## Decision

- **No switch.** Today's split stays: Qwen3-4B planner (Qwen3-8B for hard rounds) + Qwen3-VL-4B eyes, cloud first.
  It was the best end to end (11/12 at 6.5 s median) and its eyes were as accurate as Bonsai's and ~10x faster.
- **Bonsai 2 27B is not usable on this laptop for interactive work.** Planner quality looked high (9/10, every safety
  negative refused) and its vision worked (5/5), but a planner round takes ~33 s median (up to 122 s) and a
  screen question ~18 s, at ~7 GB RAM, against 3-5 s and ~3 GB. The 4 GB RTX 3050 holds only ~2.3 GB of it, and
  the Vulkan and CPU builds were slower. It also needs a non-mainline runtime. It could make sense on a GPU with
  >= 8 GB VRAM (the whole model on the GPU); re-test then.
- **One model for everything** (Bonsai text + vision) costs ~7 GB of RAM for both jobs; the two 4B models together
  use ~6.5 GB but only one is loaded at a time on the 4 GB GPU (`claim_gpu`). Separate small models win here.
- Qwen3.5-4B stays pinned and inactive: better first rounds, worse whole tasks.

Scope: one laptop (i5-12500H, RTX 3050 4 GB, 24 GB RAM), this repo's 40-task bank, 12-sentence end-to-end set and
a 5-question synthetic screen set, temperature 0. Not a general ranking of these models.

## Follow-up the same day: the owner chose Qwen3.5-4B; thinking and the lost-folder fix

Owner (2026-11-12): "qwen 3.5 is okay ... keep it and best options out there, and work on the thinking model more".

**Why Qwen3.5 lost end to end.** Only two real misses: it dropped the typed folder (`D:\ChutkuScratch\onecmd\notes.txt`
became `D:\ChutkuScratch\notes.txt`; read and copy then failed after it), and it skipped the `report` folder in the
multi-step case (Qwen3-4B fails that too). Fix: `AgentSession._reject_lost_folders` rejects any step path that lies
above a folder the user typed and is neither inside nor a parent of one; the planner retries once with the reason
and a rejected plan never runs.

**Thinking (Qwen3.5-4B, b11181 Vulkan, all on GPU)**

| Setting | Planner first rounds (10-task subset) | 5 maths/logic questions (read by hand) | Seconds |
| --- | --- | --- | --- |
| Off (today) | 10/10 | 1/4 (said 1000 > 1024, 3:15 for "45 min before 3") | < 1 per question |
| On, no budget | 4/10 (5 rounds ran out of tokens: no JSON) | 3/5, 2 empty after 2048 tokens | 7-50 |
| On, budget 512 | - | 5/5 | 7-12.5 |
| **On, budget 256** | - | **5/5** | **~6.5** |

So thinking stays off for tool rounds and is used, per request (`chat_template_kwargs.enable_thinking`, the same
loaded model, no reload), only on the first round of a question with numbers and nothing to do on the PC
(`agent_loop._reasoning_question`) or when the owner says "dhyan se socho" (H21 `session.think`). The server runs
with `--reasoning-budget 256` and a "give the final answer now" message.

**Spare RAM.** Token speed here is set by the 4 GB GPU, not system RAM. llama-server b11181 already keeps prompt
caches in system RAM by default (`--cache-ram 8192`), so nothing to add. Not tried: a speculative-decoding draft
(no small Qwen3.5 on disk; support for its hybrid attention not checked).

**After the switch (`active_planner: planner_qwen35`)**

| Check | Before (Qwen3-4B) | After (Qwen3.5-4B + guard + thinking) |
| --- | --- | --- |
| `one_command_check --offline` | 11/12, median 6.5 s, slowest 43.0 s | **11/12, median 4.6 s, slowest 37.9 s** |
| maths case | "10 ka cube (1000) bada hai" (wrong, 8B, 43 s) | "1024 is bigger than 1000" (right, 9.7 s) |
| `eval_planner` (40) | 27/40, 4.7 s | 35/40, 3.3 s, 3.41 GB |

Still failing: multi-step skips the `report` folder (both models). Back to Qwen3-4B: set `"active_planner": "model"`.

**One part at a time (same evening).** The multi-step miss came from handing a 4B model the whole sentence. Now the
local model gets `PARTS` (numbered), `DO_NOW` (the one part to plan) and a one-line rule; `DO_NOW` moves on after
a round whose steps all completed, and "done" while parts remain is rejected and retried. Result:
`one_command_check --offline` **12/12** (median 6.5 s); `eval_planner` 34/40 (the one change is time-of-day noise:
it misses the same way without today's code).

**Qwen3.5-9B** (no Qwen3.5 8B exists): ~18-20 s per planner round here (5.68 GB does not fit the 4 GB GPU), about 6x
the 4B; stopped after 17 of 45 tasks on the owner's word and removed.

## Reproduce

```
.venv\Scripts\python.exe scripts\eval_planner.py --model models\Qwen3-4B-Q4_K_M.gguf
.venv\Scripts\python.exe scripts\eval_planner.py --model models\Qwen3-8B-Q4_K_M.gguf --ngl auto
.venv\Scripts\python.exe scripts\eval_planner.py --model models\candidates\Ternary-Bonsai-2-27B-PTQ1_0.gguf ^
    --exe vendor\candidates\llama-prism-b12128-d7b2896-bin-win-cuda-12.4-x64\llama-server.exe --ngl auto --only <ids>
.venv\Scripts\python.exe scripts\eval_vision.py --image screen_test.png --model <gguf> --mmproj <mmproj> --ngl auto
.venv\Scripts\python.exe scripts\one_command_check.py --offline
```
The cudart zip is unpacked into the CUDA folder. The test picture is drawn by System.Drawing (two panels as
described above); it is not checked in.

The candidate files (`models/candidates/`, `vendor/candidates/`, 8.4 GB) were moved to the Recycle Bin on the
owner's word (2026-11-12); re-download them from the pinned sources and hashes above to repeat the Bonsai runs.
