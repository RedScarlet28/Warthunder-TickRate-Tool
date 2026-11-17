#!/usr/bin/env python3
"""
Record what this PC plays (WASAPI loopback = the game's sound) with precise timing.

Writes two files:
  audio_<host>_<time>.wav          the raw loopback audio (16-bit PCM, device rate, all channels)
  audio_<host>_<time>.timing.jsonl one line per audio buffer: sample index + wall clock (µs-precise)
                                   + QPC at the moment the buffer arrived
audio_onsets.py fits sample-index -> wall-clock from the timing file (lower-envelope fit,
which removes OS scheduling jitter) and detects gunshot onsets.

Requires:  pip install pyaudiowpatch
Usage:
  python audio_recorder.py --list
  python audio_recorder.py --out <dir>                     # default output device (what you hear)
  python audio_recorder.py --out <dir> --device "Headset"  # pick by name substring
Tips: turn off Windows "audio enhancements", spatial sound and loudness equalization on that
device. Set in-game music/voice volume to 0 and effects to 100 %, so gunshots stand out.
"""
import argparse, json, os, socket, sys, time, wave

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "tools"))
from telemetry_logger import wall_ns  # noqa: E402

try:
    import pyaudiowpatch as pyaudio
except ImportError:
    sys.exit("Missing dependency: run   pip install pyaudiowpatch")


def pick_loopback(p, name_sub):
    wasapi = p.get_host_api_info_by_type(pyaudio.paWASAPI)
    if name_sub:
        for d in p.get_loopback_device_info_generator():
            if name_sub.lower() in d["name"].lower():
                return d
        sys.exit(f"no loopback device matching '{name_sub}' (use --list)")
    out = p.get_device_info_by_index(wasapi["defaultOutputDevice"])
    for d in p.get_loopback_device_info_generator():
        if out["name"] in d["name"]:
            return d
    sys.exit("could not find loopback for the default output device (use --list / --device)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="audio_out")
    ap.add_argument("--device", default="")
    ap.add_argument("--frames", type=int, default=256, help="frames per buffer (smaller = finer timing samples)")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()

    p = pyaudio.PyAudio()
    if a.list:
        for d in p.get_loopback_device_info_generator():
            print(f"[{d['index']}] {d['name']}  {int(d['defaultSampleRate'])} Hz  {d['maxInputChannels']} ch")
        p.terminate(); return

    dev = pick_loopback(p, a.device)
    rate, ch = int(dev["defaultSampleRate"]), dev["maxInputChannels"]
    os.makedirs(a.out, exist_ok=True)
    base = os.path.join(a.out, f"audio_{socket.gethostname()}_{time.strftime('%Y%m%d_%H%M%S')}")
    wf = wave.open(base + ".wav", "wb"); wf.setnchannels(ch); wf.setsampwidth(2); wf.setframerate(rate)
    tf = open(base + ".timing.jsonl", "w", encoding="utf-8", buffering=1 << 16)
    tf.write(json.dumps({"ep": "_meta", "device": dev["name"], "rate": rate, "channels": ch,
                         "frames_per_buffer": a.frames, "host": socket.gethostname(),
                         "note": "sample_end = index of the first sample AFTER this buffer; t_* = arrival time"}) + "\n")
    state = {"n": 0}

    def cb(in_data, frame_count, time_info, status):
        t_w = wall_ns(); t_m = time.perf_counter_ns()
        wf.writeframes(in_data)
        state["n"] += frame_count
        tf.write(json.dumps({"sample_end": state["n"], "t_wall_ns": t_w, "t_mono_ns": t_m,
                             "adc": time_info.get("input_buffer_adc_time"), "status": status}) + "\n")
        return (None, pyaudio.paContinue)

    st = p.open(format=pyaudio.paInt16, channels=ch, rate=rate, input=True, frames_per_buffer=a.frames,
                input_device_index=dev["index"], stream_callback=cb)
    print(f"Recording loopback of '{dev['name']}' ({rate} Hz, {ch} ch) -> {base}.wav\nCtrl+C to stop.")
    stop_file = os.path.join(a.out, "STOP")
    last_n, last_change, last_warn = 0, time.time(), 0.0
    try:
        while st.is_active() and not os.path.exists(stop_file):   # stop_shooting.ps1 creates STOP
            time.sleep(0.5)
            # watchdog: Windows loopback delivers NOTHING while no program plays to this device.
            # If the game plays to another device (e.g. a headset), the recording stays empty.
            if state["n"] != last_n:
                last_n, last_change = state["n"], time.time()
            elif time.time() - last_change > 5 and time.time() - last_warn > 30:
                last_warn = time.time()
                print(f"\n!!! NO AUDIO from '{dev['name']}' for {time.time() - last_change:.0f} s.\n"
                      f"!!! Is the game playing to a different device? Check: python audio_recorder.py --list\n"
                      f"!!! and restart with --device \"<part of the right name>\" (start_shooting.ps1 -AudioDevice ...)")
                try:
                    import winsound
                    for _ in range(3):
                        winsound.Beep(300, 200)
                except Exception:
                    pass
    except KeyboardInterrupt:
        pass
    st.stop_stream(); st.close(); p.terminate()
    wf.close(); tf.close()
    print(f"saved {base}.wav  ({state['n'] / rate:.1f} s)")


if __name__ == "__main__":
    main()
