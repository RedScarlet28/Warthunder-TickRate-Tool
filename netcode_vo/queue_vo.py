"""Queue one Drama 3 generation per script section in the running ComfyUI."""
import json, sys, urllib.request, pathlib

HERE = pathlib.Path(__file__).parent
URL = "http://127.0.0.1:8188"
MOODS = ["explain", "hype", "comedy", "rant", "reflective", "story", "neutral"]
only = set(sys.argv[1:])

sections, cur = {}, None
for line in (HERE / "netcode_vo_tts_script.txt").read_text(encoding="utf-8").splitlines():
    if line.startswith("### "):
        cur = line[4:].strip(); sections[cur] = []
    elif line.strip():
        sections[cur].append(line.strip())


def prompt_for(name, text):
    p = {
        "2": {"class_type": "Drama3Loader", "inputs": {"model_name": "drama3_w6a8experts_bf16.safetensors",
              "experts": "in RAM", "expert_cache_gb": 0, "second_gpu": "none", "split_layer": 0, "pin_experts": True}},
        "3": {"class_type": "Drama3CodecLoader", "inputs": {"codec_name": "drama3_codec.safetensors"}},
        "4": {"class_type": "Drama3Generate", "inputs": {"model": ["2", 0], "text": text, "seed": 777,
              "temperature": 1.0, "top_p": 0.9, "top_k": 0, "max_frames": 0, "split_long_text": True,
              "speakers": "one take per line", "voice_guidance": 0.0}},
        "12": {"class_type": "Drama3SaveCodes", "inputs": {"codes": ["4", 0], "name": f"netcode_vo_{name}"}},
        "13": {"class_type": "Drama3Decode", "inputs": {"codec": ["3", 0], "codes": ["4", 0], "shorten_long_pauses": True}},
        "14": {"class_type": "SaveAudio", "inputs": {"audio": ["13", 0], "filename_prefix": f"drama3/netcode_vo/{name}"}},
    }
    for i, m in enumerate(MOODS):
        p[str(20 + i)] = {"class_type": "Drama3LoadVoice", "inputs": {"voice": f"voice_{m}_00001_.safetensors"}}
        p["4"]["inputs"][f"voices.voice{i}"] = [str(20 + i), 0]
    return p


for name, lines in sections.items():
    if only and name not in only:
        continue
    body = json.dumps({"prompt": prompt_for(name, "\n".join(lines)), "client_id": "netcode_vo"}).encode()
    req = urllib.request.Request(URL + "/prompt", body, {"Content-Type": "application/json"})
    try:
        r = json.load(urllib.request.urlopen(req))
        print(name, r.get("prompt_id"), r.get("node_errors") or "")
    except urllib.error.HTTPError as e:
        print(name, "ERROR", e.read().decode()[:2000]); break
