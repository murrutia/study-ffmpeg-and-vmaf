#!/usr/bin/env python3

import logging
import sys
import json
import subprocess
from pathlib import Path
from argparse import ArgumentParser
from scenecut_extractor.__main__ import get_scenecuts
from utils.FFmpegWrapper import FFProbeWrapper, FFmpegWrapper
from utils.easyVmaf.FFmpeg import FFprobe
from dotenv import find_dotenv, dotenv_values

config = dotenv_values(find_dotenv())

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

logger = logging.getLogger(__name__)
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter('%(asctime)s %(name)-12s %(levelname)-8s %(message)s'))
logger.addHandler(handler)
logger.setLevel(logging.DEBUG)

# def video_duration(filepath):
#     cmd = f"{config['ffprobe']} -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1"
#     cmd_a = cmd.split(' ')
#     cmd_a.append(str(filepath))
#     print(" ".join(cmd_a))
#     return float(subprocess.check_output(cmd_a))


# def encode_and_vmaf(input_path, crf):
#     video_name = Path(input_path).stem


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


# def compute_scenescores(input, output):
#     input = Path(input)
#     output = Path(output)

#     if not output.exists():
#         scenescores = get_scenecuts(str(input), threshold=0)
#         scenescores = sorted(scenescores, key=lambda ss: ss["score"], reverse=True)

#         with open(str(output), 'w') as fd:
#             fd.write(json.dumps(scenescores, indent=4))
    
#     with open(str(output), 'r') as fd:
#         scenescores = json.loads(fd.read())
    
#     return scenescores


# def generate_extract(input, output, start, duration):
#     print(output)
#     cmd = f"{BIN_FFMPEG} -hide_banner -loglevel quiet -stats".split(" ")
#     cmd.extend(['-i', str(input)])
#     cmd.extend(f'-ss {start} -t {duration} -c copy'.split(" "))
#     cmd.extend(['-y', str(output)])

#     subprocess.check_output(cmd)


if __name__ == '__main__':
    
    args = parse_args()

    # initialize variables
    input = Path(args.input)
    video_name = input.stem
    video_ext = input.suffix
    extract_d = args.extract_duration
    ffmpeg = FFmpegWrapper()
    ffprobe = FFProbeWrapper(args.input)
    csv_path = OUTPUT_DIR / f"{video_name}.csv"

    # compute scenescores
    scenescores = ffmpeg.getScenescores(args.input)

    # select ? scenescore
    selected_scores = [scenescores[1], scenescores[int(len(scenescores) / 2)], scenescores[-1]]

    # extract the videos
    for i in range(len(selected_scores)):
        scene = selected_scores[i]
        scene['extract_path'] = EXTRACTS_DIR / f"{video_name}.extract.t{scene['pts_time']:.2f}-{extract_d}s{video_ext}"
        ffmpeg.getExtractAroundTime(input, scene['pts_time'], extract_d, scene['extract_path'])

    # start encoding extract from worst to best crf and compute vmaf score until min vmaf score is attained
    # (opt : compute filesize gain)
    crf = 30
    vmaf_score = 0
    csv_headers = [
        'crf',
        'time',
        'mode',
        'offset',
        'psnr',
        'vmaf mean',
        'vmaf harmonic mean',
    ]
    with open(csv_path, 'w') as fd:
        fd.write(';'.join(csv_headers) + '\n')

    while vmaf_score < 85 and crf >= 23:
        
        for i in range(len(selected_scores)):
            scene = selected_scores[i]
            scene['encoded_path'] = scene['extract_path'].parent / f"{scene['extract_path'].stem}.crf{crf}.mp4"
            
            infos = [crf, scene['pts_time']]

            ffmpeg.encode(scene['extract_path'], scene['encoded_path'], crf=crf, mode='simple')
            logger.debug('encode executed, will get vmaf')
            scores = ffmpeg.getVmaf(scene['extract_path'], scene['encoded_path'])
            with open(csv_path, 'a') as fd:
                for score in scores:
                    data = map(lambda elt: str(elt), [*infos, 'simple', *score])
                    fd.write(';'.join(data) + '\n')

            ffmpeg.encode(scene['extract_path'], scene['encoded_path'], crf=crf)
            scores = ffmpeg.getVmaf(scene['extract_path'], scene['encoded_path'])
            with open(csv_path, 'a') as fd:
                for score in scores:
                    data = map(lambda elt: str(elt), [*infos, 'complex', *score])
                    fd.write(';'.join(data) + '\n')

    # encode video

    # clean tmp dir
    # (opt : erase original file)

    # display results (choice of crf, vmaf scores, filesizes comparison, command line)

    print("end of script")