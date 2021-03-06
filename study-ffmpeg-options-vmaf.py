#!/usr/local/Caskroom/miniconda/base/envs/vmaf/bin/python3

import os
import re
import sys
import json
import logging
import argparse
import subprocess
from time import time
from glob import glob
from pathlib import Path
from datetime import timedelta
from dotenv import find_dotenv, dotenv_values
from statistics import mean , harmonic_mean
from scenecut_extractor.__main__ import get_scenecuts
from utils.ffmpeg_scenescores import get_sorted_scenescores
from external.ffshort import ffshort, guess_frame_rate
from utils.easyVmaf.Vmaf import vmaf


config = dotenv_values(find_dotenv())

SCRIPT_DIR = Path(os.path.dirname(__file__))

OUTPUT_DIR = SCRIPT_DIR / "output"
EXTRACTS_DIR = SCRIPT_DIR / 'tmp' / 'extracts'
VMAF_DIR = SCRIPT_DIR / 'tmp' / 'vmaf'

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
EXTRACTS_DIR.mkdir(parents=True, exist_ok=True)
VMAF_DIR.mkdir(parents=True, exist_ok=True)

# CRF_VALUES = [25, 27, 30]
CRF_VALUES = [27]
EXTRACT_DURATIONS = [30, 45, 60]
# EXTRACT_DURATIONS = [10, 15, 30, 45, 60]
FFMPEG_OPTIONS = [
    # '-c:v',
    # '-sws_flags',
    # '-pix_fmt',
    # '-movflags',
    # '-b-pyramid',
    # '-b_strategy',
    # '-g',
    # '-keyint_min',
    # '-preset',
    # '-refs',
    # '-me_method',
    # '-me_range',
    # '-qcomp',
    # '-qmin',
    # '-subq',
    '-r',
    '-trellis'
]


logger = logging.getLogger(__name__)


def get_video_duration(filepath):
    cmd = f"{config['ffprobe']} -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1"
    cmd_a = cmd.split(" ")
    cmd_a.append(str(filepath))
    return float(subprocess.check_output(cmd_a))


def compute_vmaf(reference, encoded, log_path):
    if not log_path.exists():
        myVmaf = vmaf(encoded, reference, output_fmt='json', log_path=log_path, loglevel='quiet')
        offset1, psnr1 = myVmaf.syncOffset()  # TODO: étudier les arguments de cette fonction : syncWindow, start, reverse
        offset2, psnr2 = myVmaf.syncOffset(reverse=True)
        # offset, psnr = myVmaf.syncOffset()  # TODO: étudier les arguments de cette fonction : syncWindow, start, reverse

        offset, psnr = [offset1, psnr1] if psnr1 >= psnr2 else [-offset2, psnr2]
        myVmaf.offset = offset
        myVmaf.getVmaf()
    else:
        offset = "N/A"
        psnr = "N/A"

    vmaf_scores = []
    with open(str(log_path), 'r') as fd:
        jsonData = json.load(fd)
        for frame in jsonData['frames']:
            vmaf_scores.append(frame["metrics"]["vmaf"])
    
    return [offset, psnr, vmaf_scores]


def encode_and_vmaf(input_path, crf, mode="ffshort", remove_option=None, keep_temp_files=False):
    extract_name = Path(input_path).name
    extract_name = re.sub(r'\.[^.]+$', '', extract_name)
    option_name = remove_option.replace(':', '') if remove_option else 'None'

    options = {remove_option: None} if remove_option else {}

    if mode == 'ffshort':
        output_path = EXTRACTS_DIR / f"{extract_name}.crf{crf}.mode-ffshort.option{option_name}.mp4"
        encode_cmd = ffshort(str(input_path), str(output_path), crf=crf, dry_run=True, force_encode=True, ffmpeg_path=config['ffmpeg'], options=options)
    else:
        output_path = EXTRACTS_DIR / f"{extract_name}.crf{crf}.mode-simple.mp4"
        encode_cmd = f"{config['ffmpeg']} -hide_banner -loglevel quiet -stats -i {str(input_path)} -crf {crf}".split(" ")
        encode_cmd.extend(['-y', str(output_path)])
                
    start_cmd = time()
    subprocess.run(encode_cmd)
    encoding_duration = str(timedelta(seconds=(time() - start_cmd)))
    encoded_filesize = output_path.stat().st_size
    size_percentage = encoded_filesize / extract_filesize * 100

    vmaf_path = OUTPUT_DIR / f"{extract_name}.crf{crf}.mode-{mode}.option{option_name}.json"
    
    start_cmd = time()
    offset, psnr, vmaf_scores = compute_vmaf(output_path, input_path, vmaf_path)
    vmaf_duration = str(timedelta(seconds=(time() - start_cmd)))
    
    if not keep_temp_files:
        os.remove(output_path)
        os.remove(vmaf_path)


    values = {
        "CRF value": crf,
        "Option removed": "' "+ str(remove_option),
        "Encoding duration": encoding_duration,
        "VMAF offset": offset,
        "VMAF PSNR": psnr,
        "VMAF arithmetic mean score": mean(vmaf_scores),
        "VMAF harmonic mean score": harmonic_mean(vmaf_scores),
        "VMAF computing duration": vmaf_duration,
        "Encoded filesize": encoded_filesize,
        "Filesize percentage": size_percentage,
        "Encoding command":  encode_cmd
    }
    return values


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('input')
    parser.add_argument('--log-level', default='warning', help="Level of logging : debug, info, warning (default), error or critical")
    parser.add_argument('--ffmpeg-log-level', default='quiet')
    parser.add_argument('--keep-temp-files', '-k', action='store_true', help="Keep temporary files")
    parser.add_argument('--output-csv', help="CSV file where the results will be stored")

    cli_args = parser.parse_args()
    return cli_args


def ffmpeg_extract(input, output, start, duration, log_level='quiet'):

    extract_cmd = f"{config['ffmpeg']} -hide_banner -loglevel {log_level} -stats -i {input} -ss {start} -t {duration} -c copy".split(' ')
    extract_cmd.extend(['-y', output])
    subprocess.run(extract_cmd)


if __name__ == '__main__':
    
    cli_args = parse_args()

    # Initializations
    logging.basicConfig(level = getattr(logging,  cli_args.log_level.upper(), 'WARNING'))
    input = Path(cli_args.input)


    # On récupère la durée et le nom de la vidéo
    # video_name = re.search(r'_(v.*)\..*$', cli_args.input).group(1) 
    duration = get_video_duration(input)
    video_name = input.stem
    video_extension = input.suffix

    '''
    Ici on va tester différentes combinaisons pour déterminer s'il y a une manière plus pertinente
    qu'une autre pour juger de la qualité d'une vidéo encodée par rapport à l'originale.
    1 - est-ce que la durée de l'extrait a un impact ?
    2 - est-ce que choisir un extrait proche d'un changement de scène ou non a un impact ?
    '''
    ##
    # Calcul des "scores" de changement dans les frames pour détecter les changements de scene
    scenescores_filepath = OUTPUT_DIR / f"{video_name}-scenescore.json" if cli_args.keep_temp_files else None
    scenescores = get_sorted_scenescores(cli_args.input, scenescores_filepath, log_level=cli_args.log_level)

    # Réduction des résultats au 2eme meilleur, le moyen et le 2eme pire
    sl = len(scenescores)
    scenescores_extract = [scenescores[1], scenescores[int(sl/2)], scenescores[-2]]
    # scenescores_extract = [scenescores[1]]

    # Préparation du csv qui va accueillir les résultats
    results_csv = "Scene score; Time; Duration; Start; End; CRF value; Option removed; Encoding time; VMAF offset; VMAF PSNR;VMAF arithmetic mean; VMAF harmonic mean; VMAF computation time; Filesize; Compression %; Encoding command\n"
    results_csv_path = OUTPUT_DIR / f"{video_name}_ffmpeg-options-vmaf-scores.csv"

    file_csv = open(str(results_csv_path), 'w+')
    file_csv.write(results_csv)

    # Parcours des scores retenus
    for score in scenescores_extract:
        scene_score = score['score']
        scene_time =  score['pts_time']

        scene_details = {
            "Scene score": scene_score,
            "Scene time": scene_time,
        }
            
        print()

        # Pour chacun de ces scores, récupération d'un extrait de durées variables
        for extract_duration in EXTRACT_DURATIONS:

            print(f"Extract for score {scene_score} at time {scene_time} of duration {extract_duration}s...")
            start_time = scene_time - extract_duration / 2
            if start_time < 0:
                start_time = 0
            if start_time + extract_duration > duration:
                start_time = duration - extract_duration
            # start_time = scene_time - extract_duration / 2 if scene_time > extract_duration / 2 else 0
            # end_time = start_time + extract_duration if start_time + extract_duration < duration else duration

            extract_details = {
                "Duration": extract_duration,
                "Start time": start_time,
                "End time": start_time + extract_duration,
            }
            
            extract_name = f"{video_name}-extract.duration-{extract_duration}s.timestamp-{scene_time}s.score-{score['score']}"
            extract_path = EXTRACTS_DIR / (extract_name + video_extension)
            ffmpeg_extract(cli_args.input, extract_path, scene_time, extract_duration, log_level=cli_args.ffmpeg_log_level)

            extract_filesize = extract_path.stat().st_size

            # Encodage et test de qualité pour chacune des valeurs de CRF à tester
            for crf in CRF_VALUES:
                
                # Encodage témoin
                encoding_details = encode_and_vmaf(extract_path, crf=crf, mode="simple", keep_temp_files=cli_args.keep_temp_files)

                all_details = {**scene_details, **extract_details, **encoding_details}
                all_details_str = {k: str(v) for k, v in all_details.items()}
                line_csv = ";".join(all_details_str.values()) + "\n"
                file_csv.write(line_csv)

                # Encodage témoin 2
                encoding_details = encode_and_vmaf(extract_path, crf=crf)

                all_details = {**scene_details, **extract_details, **encoding_details}
                all_details_str = {k: str(v) for k, v in all_details.items()}
                line_csv = ";".join(all_details_str.values()) + "\n"
                file_csv.write(line_csv)

                for option in FFMPEG_OPTIONS:

                    encoding_details = encode_and_vmaf(extract_path, crf=crf, remove_option=option)

                    all_details = {**scene_details, **extract_details, **encoding_details}
                    all_details_str = {k: str(v) for k, v in all_details.items()}
                    line_csv = ";".join(all_details_str.values()) + "\n"
                    file_csv.write(line_csv)
            
            if not cli_args.keep_temp_files:
                os.remove(extract_path)

    
    for file in glob(f"{OUTPUT_DIR}/*.json"):
        os.remove(file)

    file_csv.close()
    print(f"Les résultats ont été enregistrés dans le fichier {str(results_csv_path)}.")


