"""Export the recorded operator workflow, synchronized voices, and README media."""
import argparse
import json
import math
from pathlib import Path
import re
import struct
import subprocess
import tempfile
import textwrap


FPS = 25


def ffmpeg(*args, capture=False):
    return subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", *map(str, args)],
                          check=True, stdout=subprocess.PIPE if capture else None).stdout


def film_start(raw):
    # The recording desk flashes magenta before the first frame of the story.
    pixels = ffmpeg("-i", raw, "-t", "45", "-an", "-vf",
                    f"fps={FPS},crop=4:4:2:2,scale=1:1", "-pix_fmt", "rgb24",
                    "-f", "rawvideo", "-", capture=True)
    slate = [i // 3 for i in range(0, len(pixels), 3)
             if pixels[i] > 205 and pixels[i+1] < 45 and pixels[i+2] > 205]
    if len(slate) < 3 or slate[-1] - slate[0] + 1 != len(slate):
        raise ValueError("Could not find a single recording slate before the opening shot.")
    return (slate[-1] + 1) / FPS


def timestamp(seconds):
    ms = round(seconds * 1000)
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def write_captions(tracks, file):
    entries = []
    for clip in tracks:
        role = "Caller" if clip["file"].startswith("caller-") else "Intake agent"
        spoken = re.sub(r"^\s*\[[^\]]+\]\s*", "", clip["text"])
        # Split at sentence boundaries and replace inaudible delivery directions.
        parts = re.split(r"(?<=[.!?])\s+", spoken)
        weights = [len(part.split()) for part in parts]
        at = clip["start"]
        for part, weight in zip(parts, weights):
            until = at + clip["duration"] * weight / sum(weights)
            words = textwrap.fill(f"[{role}] {part}", width=54, break_long_words=False)
            entries.append(f"{len(entries)+1}\n{timestamp(at)} --> {timestamp(until)}\n{words}\n")
            at = until
    file.write_text("\n".join(entries), encoding="utf-8")


def captions_off_by_default(mp4):
    # FFmpeg's MOV muxer enables the first subtitle track despite disposition 0.
    # Clear only the enable bit on the text track. Its samples remain selectable.
    data = bytearray(mp4.read_bytes())

    def boxes(start, end):
        while start + 8 <= end:
            size, kind = struct.unpack_from(">I4s", data, start)
            if not 8 <= size <= end - start:
                raise ValueError("Invalid MP4 box in the local export.")
            yield kind, start + 8, start + size
            start += size

    moov = next((a, b) for kind, a, b in boxes(0, len(data)) if kind == b"moov")
    for kind, start, end in boxes(*moov):
        if kind != b"trak":
            continue
        track = list(boxes(start, end))
        media = next((a, b) for name, a, b in track if name == b"mdia")
        handler = next(a for name, a, _ in boxes(*media) if name == b"hdlr")
        if data[handler+8:handler+12] == b"sbtl":
            header = next(a for name, a, _ in track if name == b"tkhd")
            data[header+3] &= 0xfe
            mp4.write_bytes(data)
            return
    raise ValueError("The exported movie is missing its English captions.")


def export_movie(take, edit, dest, temp, acknowledgement_seconds):
    raw = take / "desktop.webm"
    origin = film_start(raw)
    tracks = list(edit["tracks"])
    reply = tracks[-1]
    if acknowledgement_seconds is not None:
        sentences = re.split(r"(?<=[.!?])\s+", reply["text"].strip())
        if (not reply["file"].startswith("agent-") or len(sentences) < 2
                or not sentences[-1].endswith("?") or not 0 < acknowledgement_seconds < reply["duration"]):
            raise ValueError("The cut must fall in the final agent reply before its follow-up question.")
        reply = {**reply, "duration": acknowledgement_seconds, "text": " ".join(sentences[:-1])}
        tracks[-1] = reply
    duration = math.ceil((reply["start"] + reply["duration"]) * FPS) / FPS
    if duration <= edit["marks"]["assistance"]:
        raise ValueError("The assistance report must appear before the end of the film.")
    source = Path(edit["source"])

    voice_inputs = []
    voice_filters = []
    audio = []
    for index, clip in enumerate(tracks, start=1):
        voice_inputs += ["-i", source / clip["file"]]
        delay_ms = round(clip["start"] * 1000)
        voice_filters.append(f"[{index-1}:a]loudnorm=I=-18:TP=-2:LRA=9,aresample=48000,atrim=duration={clip['duration']},"
                             f"asetpts=N/SR/TB,adelay={delay_ms}:all=1[a{index}]")
        audio.append(f"[a{index}]")
    samples = round(duration * 48000)
    voice_filters.append(f"{''.join(audio)}amix=inputs={len(audio)}:normalize=0,"
                         f"apad=whole_len={samples},atrim=end_sample={samples},asetpts=N/SR/TB[audio]")
    mix = temp / "voices.wav"
    ffmpeg(*voice_inputs, "-filter_complex", ";".join(voice_filters), "-map", "[audio]",
           "-c:a", "pcm_s24le", "-ar", "48000", mix)
    srt = temp / "english.srt"
    write_captions(tracks, srt)
    movie = dest / "library-call.mp4"
    ffmpeg("-ss", origin, "-i", raw, "-i", mix, "-i", srt, "-t", duration,
           "-vf", f"fps={FPS},setsar=1", "-map", "0:v:0", "-map", "1:a", "-map", "2:s",
           "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "144k", "-c:s", "mov_text", "-disposition:s:0", "0",
           "-metadata:s:s:0", "language=eng", "-metadata:s:s:0", "handler_name=English captions",
           "-metadata:s:a:0", "language=eng", "-metadata", "title=Emergency OS | The Central Library call",
           "-metadata", "comment=Recorded ElevenLabs intake exercise. Map data © OpenStreetMap contributors.",
           "-movflags", "+faststart", movie)
    captions_off_by_default(movie)
    print(f"Exported {duration:.1f}s. Opening frame at {origin:.2f}s in the raw capture.", flush=True)
    return movie


def export_preview(movie, marks, dest, temp):
    # Follow the operator into the call, then hold on the caller's words and map pin.
    opening = max(0, marks["pickup"] - 1.8)
    excerpts = [(opening, marks["open_call"] + 1.4 - opening), (marks["assistance"] - .65, 2.05)]
    frames = []
    for index, (start, duration) in enumerate(excerpts):
        ffmpeg("-ss", start, "-i", movie, "-t", duration, "-an", "-sn", "-vf",
               "fps=8,scale=960:540:flags=lanczos", temp / f"scene{index}-%03d.png")
        frames += sorted(temp.glob(f"scene{index}-*.png"))
    subprocess.run(["img2webp", "-loop", "0", "-lossy", "-m", "4", "-q", "77",
                    "-d", "125", *map(str, frames[:-1]), "-d", "900", str(frames[-1]),
                    "-o", str(dest/"library-assistance-preview.webp")], check=True)


def render(take, destination, acknowledgement_seconds=None):
    destination.mkdir(parents=True, exist_ok=True)
    edit = json.loads((take / "edit.json").read_text())
    with tempfile.TemporaryDirectory(prefix="operator-export-") as scratch:
        temp = Path(scratch)
        movie = export_movie(take, edit, destination, temp, acknowledgement_seconds)
        export_preview(movie, edit["marks"], destination, temp)
    for frame, label in (("pickup", "overview"), ("confirmed", "confirmed"), ("assistance", "assistance")):
        subprocess.run(["cwebp", "-quiet", "-sharp_yuv", "-q", "88", str(take/f"{frame}.png"),
                        "-o", str(destination/f"library-{label}.webp")], check=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("take", type=Path)
    parser.add_argument("--out", type=Path, help="Export directory (defaults to TAKE/export)")
    parser.add_argument("--acknowledgement-seconds", type=float,
                        help="End in the pause before the final follow-up question, measured from the start of that reply")
    args = parser.parse_args()
    render(args.take.resolve(), args.out or args.take/"export", args.acknowledgement_seconds)
