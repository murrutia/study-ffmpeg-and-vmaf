#!/usr/local/bin/python3

import re
import sys
import json
import argparse
import subprocess
from pathlib import Path

from scenecut_extractor.__main__ import get_scenecuts

SCRIPT_DIR = sys.path[0]

EXTRACTS_DIR = Path('/tmp/extracts')
EXTRACTS_DIR.mkdir(parents=True, exist_ok=True)
BIN_FFMPEG = "/usr/local/bin/ffmpeg"
MODEL_PATH = "/Users/murrutia/src/vendor/vmaf/model/vmaf_v0.6.1.json"
DATA_DIR = Path(SCRIPT_DIR) / "data"

def get_video_duration(file_path):
    cmd = f"ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 {file_path}"
    return float(subprocess.check_output(cmd.split(" ")))


def get_line_count(file_path):
    x = 0
    with open(file_path) as fd:
        for line in fd:
            x += 1
    return x


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('input')
    parser.add_argument('--duration-extract', '-t', type=int, default=60, help="Duration of the extract used for vmaf score testing")
    cli_args = parser.parse_args()
    
    extract_duration = cli_args.duration_extract

    # get video id
    video_id = re.search(r'_(v.*)\..*$', cli_args.input).group(1)

    duration = get_video_duration(cli_args.input)
    
    scenescores_filepath = f"{SCRIPT_DIR}/data/{video_id}-scenescore.json"

    if Path(scenescores_filepath).exists():
        with open(scenescores_filepath, 'r') as fd:
            scenescores = json.loads(fd.read())
    else:
        # run scene change detection
        scenescores = get_scenecuts(cli_args.input, threshold=0)
        scenescores = sorted(scenescores, key=lambda ss: ss["score"], reverse=True)

        # print(get_scenecuts(cli_args.input, threshold=0))
        with open(scenescores_filepath, 'w') as fd:
            fd.write(json.dumps(scenescores, indent=4))

    for score in scenescores[:2]:
        scene_time = score['pts_time']
        print(f"Extract for score {score['score']} at time {scene_time}...")
        start_time = scene_time - extract_duration / 2 if scene_time > extract_duration / 2 else 0
        
        extract_name = f"{video_id}-extract{extract_duration}s.{scene_time}"
        extract_path = EXTRACTS_DIR / (extract_name + ".mov")
        extract_cmd = f"{BIN_FFMPEG} -hide_banner -i {cli_args.input} -ss {start_time} -t {extract_duration} -c copy -y {str(extract_path)}"
        subprocess.run(extract_cmd.split(" "))
        
        for crf in range(23, 31):
            encoded_path = EXTRACTS_DIR / f"{extract_name}.crf{crf}.mp4"
            encode_cmd = f"{BIN_FFMPEG} -hide_banner -i {str(extract_path)} -crf {crf} -y {encoded_path}"
            subprocess.run(encode_cmd.split(" "))

            vmaf_path = DATA_DIR / f"{extract_name}.crf{crf}.json"
            vmaf_cmd = f"{BIN_FFMPEG} -i {extract_path} -i {encoded_path} "
            vmaf_cmd += f"-lavfi [0:v]setpts=PTS-STARTPTS[ref];[1:v]setpts=PTS-STARTPTS[dist];[dist][ref]libvmaf=log_fmt=json:log_path={vmaf_path}:model_path=/Users/murrutia/src/vendor/vmaf/model/vmaf_v0.6.1.json "
            vmaf_cmd += "-threads 0 -f null -"
            print(vmaf_cmd)
            subprocess.run(vmaf_cmd.split(" "))

