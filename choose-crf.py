#!/usr/local/bin/python3

import sys
import json
import subprocess
from pathlib import Path
from argparse import ArgumentParser
from scenecut_extractor.__main__ import get_scenecuts

## Config values
SCRIPT_DIR = Path(sys.path[0])
EXTERNAL_DIR = SCRIPT_DIR / "external"
BIN_FFMPEG =  EXTERNAL_DIR / "ffmpeg"  # une version de ffmpeg incluant libvmaf
BIN_FFPROBE = EXTERNAL_DIR / "ffprobe"
MODEL_PATH = EXTERNAL_DIR / "vmaf_v0.6.1.json"

OUTPUT_DIR = SCRIPT_DIR / "output"

TMP_DIR = SCRIPT_DIR / "tmp"
EXTRACTS_DIR = TMP_DIR / "extracts"
EXTRACTS_DIR.mkdir(parents=True, exist_ok=True)
VMAF_DIR = TMP_DIR / "vmaf"
VMAF_DIR.mkdir(parents=True, exist_ok=True)

MIN_CRF = 23
MAX_CRF = 30
MIN_VMAF_SCORE = 85
EXTRACT_DURATION = 45


def video_duration(filepath):
    cmd = f"{BIN_FFPROBE} -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1"
    cmd_a = cmd.split(' ')
    cmd_a.append(str(filepath))
    print(" ".join(cmd_a))
    return float(subprocess.check_output(cmd_a))


def encode_and_vmaf(input_path, crf):
    video_name = Path(input_path).stem


def parse_args():
    
    # argument parser
    # - input filepath
    # - opt :
    #   - min crf
    #   - max crf
    #   - extract duration
    #   - min vmaf score for validation
    #   - force encoding if vmaf score not reached
    #   - "dry run" : don't encode full video at the end of the script
    #   - output filepath
    #   - clean tmp dir
    #   - erase input file
    
    parser = ArgumentParser()
    parser.add_argument('input', help="path of the input file")
    parser.add_argument('output', nargs='?', help="path of the output file")
    parser.add_argument('--extract-duration', type=int, default=EXTRACT_DURATION, help="the duration (in seconds) of the extract used to compute vmaf score")

    args = parser.parse_args()
    
    return args


def compute_scenescores(input, output):
    input = Path(input)
    output = Path(output)

    if not output.exists():
        scenescores = get_scenecuts(str(input), threshold=0)
        scenescores = sorted(scenescores, key=lambda ss: ss["score"], reverse=True)

        with open(str(output), 'w') as fd:
            fd.write(json.dumps(scenescores, indent=4))
    
    with open(str(output), 'r') as fd:
        scenescores = json.loads(fd.read())
    
    return scenescores


def generate_extract(input, output, start, duration):
    print(output)
    cmd = f"{BIN_FFMPEG} -hide_banner -loglevel quiet -stats".split(" ")
    cmd.extend(['-i', str(input)])
    cmd.extend(f'-ss {start} -t {duration} -c copy'.split(" "))
    cmd.extend(['-y', str(output)])

    subprocess.check_output(cmd)


if __name__ == '__main__':
    
    args = parse_args()

    # initialize variables
    input = Path(args.input)
    video_name = input.stem
    video_ext = input.suffix
    extract_d = args.extract_duration

    # compute scenescores
    # scenescores_filepath = OUTPUT_DIR / f"{video_name}.scenescores.json"
    # scenescores = compute_scenescores(args.input, scenescores_filepath)

    # select ? scenescore
    # selected_score = scenescores[1] # the second best scenescore (to avoid potential erroneous score dur to glitch from abrupt video file cut)
    selected_score = {'score': 1, 'pts_time': 5}

    # determine start and stop of extract
    full_duration = video_duration(input)
    if extract_d > full_duration:
        sys.exit(f"Error: the video is shorter ({full_duration} s) than the duration of the extract needed for quality check ({extract_d} s).")
    
    score_val = selected_score['score']
    score_pts = selected_score['pts_time']
    start = 0 if score_pts < extract_d / 2 else score_pts - extract_d / 2
    print(f"start : {start} - end : {start + extract_d}")

    # extract the scene
    extract_path = EXTRACTS_DIR / f"{video_name}.extract-{extract_d}s{video_ext}"
    generate_extract(input, extract_path, start, extract_d)

    # start encoding extract from worst to best crf and compute vmaf score until min vmaf score is attained
    # (opt : compute filesize gain)

    # encode video

    # clean tmp dir
    # (opt : erase original file)

    # display results (choice of crf, vmaf scores, filesizes comparison, command line)

    print("end of script")