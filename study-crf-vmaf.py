#!/usr/local/bin/python3

import re
import sys
import json
import argparse
import subprocess
from pathlib import Path
from time import time
from datetime import timedelta

from scenecut_extractor.__main__ import get_scenecuts
from external.ffshort import ffshort

SCRIPT_DIR = Path(sys.path[0])

EXTRACTS_DIR = SCRIPT_DIR / 'tmp' / 'extracts'
EXTRACTS_DIR.mkdir(parents=True, exist_ok=True)
BIN_FFMPEG = SCRIPT_DIR / "external" / "ffmpeg"
MODEL_PATH = SCRIPT_DIR / "external" / "vmaf_v0.6.1.json"
OUTPUT_DIR = SCRIPT_DIR / "output"
# CRF_VALUES = range(23, 31)
CRF_VALUES = [25, 27, 30]
# EXTRACT_DURATIONS = [15, 30, 60, 120]
EXTRACT_DURATIONS = [30, 45, 60]

def get_video_duration(file_path):
    cmd = f"ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 {file_path}"
    return float(subprocess.check_output(cmd.split(" ")))


def get_line_count(file_path):
    x = 0
    with open(file_path) as fd:
        for line in fd:
            x += 1
    return x


def encode_and_vmaf(input_path, crf, mode="simple"):
    extract_name = Path(input_path).name
    extract_name = re.sub(r'\.[^.]+$', '', extract_name)
    output_path = EXTRACTS_DIR / f"{extract_name}.crf{crf}.simple.mp4"

    if mode == 'simple':
        print("Encodage simple ...")
        encode_cmd = f"{BIN_FFMPEG} -hide_banner -loglevel quiet -stats -i {str(input_path)} -crf {crf} -y {str(output_path)}"
    else:
        print("Encodage complexe ...")
        encode_cmd = ffshort(str(input_path), str(output_path), crf=crf, dry_run=True, force_encode=True, ffmpeg_path=BIN_FFMPEG)
                
    print(encode_cmd)
    start_cmd = time()
    subprocess.run(encode_cmd.split(" "))
    encoding_duration = str(timedelta(seconds=(time() - start_cmd)))
    encoded_filesize = output_path.stat().st_size
    size_percentage = encoded_filesize / extract_filesize * 100
    print()

    vmaf_path = OUTPUT_DIR / f"{extract_name}.crf{crf}.simple.json"
    vmaf_cmd = f"{BIN_FFMPEG} -loglevel quiet -stats -i {str(input_path)} -i {str(output_path)} "
    vmaf_cmd += f"-lavfi [0:v]setpts=PTS-STARTPTS[ref];[1:v]setpts=PTS-STARTPTS[dist];[dist][ref]libvmaf=log_fmt=json:log_path={str(vmaf_path)}:model_path=/Users/murrutia/src/vendor/vmaf/model/vmaf_v0.6.1.json "
    vmaf_cmd += "-threads 0 -f null -"
    start_cmd = time()
    subprocess.run(vmaf_cmd.split(" "))
    print()
    vmaf_duration = str(timedelta(seconds=(time() - start_cmd)))

    with open(str(vmaf_path), 'r') as fd:
        vmaf_json = json.loads(fd.read())
    vmaf_score = vmaf_json['pooled_metrics']['vmaf']['harmonic_mean']

    values = {
        "CRF value": crf,
        "Encoding method": mode,
        "Encoding duration": encoding_duration,
        "VMAF harmonic mean score": vmaf_score,
        "VMAF computing duration": vmaf_duration,
        "Encoded filesize": encoded_filesize,
        "Filesize percentage": size_percentage,
        "Encoding command":  encode_cmd
    }
    return values


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('input')
    cli_args = parser.parse_args()

    # On récupère la durée et le nom de la vidéo
    # video_name = re.search(r'_(v.*)\..*$', cli_args.input).group(1) 
    duration = get_video_duration(cli_args.input)
    video_name = Path(cli_args.input).name
    video_name = re.sub(r'\.[^.]+$', '', video_name)

    ################################################################################################
    # Ici on va tester différentes combinaisons pour déterminer s'il y a une manière plus pertinente
    # qu'une autre pour juger de la qualité d'une vidéo encodée par rapport à l'originale.
    # 1 - est-ce que la durée de l'extrait a un impact ?
    # 2 - est-ce que choisir un extrait proche d'un changement de scène ou non a un impact ?
    
    ##
    # Calcul des "scores" de changement dans les frames pour détecter les changements de scene
    scenescores_filepath = OUTPUT_DIR / f"{video_name}-scenescore.json"

    if scenescores_filepath.exists():
        with open(str(scenescores_filepath), 'r') as fd:
            scenescores = json.loads(fd.read())
    else:
        # run scene change detection
        scenescores = get_scenecuts(cli_args.input, threshold=0)
        scenescores = sorted(scenescores, key=lambda ss: ss["score"], reverse=True)
        print()

        # print(get_scenecuts(cli_args.input, threshold=0))
        with open(str(scenescores_filepath), 'w') as fd:
            fd.write(json.dumps(scenescores, indent=4))

    # Réduction des résultats aux 3 meilleurs, 3 moyens et les 3 pires
    sl = len(scenescores)
    scenescores_extract = scenescores[:3] + scenescores[sl-1:sl+21] + scenescores[-3:]

    # Préparation du csv qui va accueillir les résultats
    results_csv = "Scene score; Time; Duration; Start; End; CRF value; Encoding method; Encoding time; VMAF score; VMAF computation time; Filesize; Compression %; Encoding command\n"
    results_csv_path = OUTPUT_DIR / f"{video_name}_vmaf-scores.csv"

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
            start_time = scene_time - extract_duration / 2 if scene_time > extract_duration / 2 else 0
            end_time = start_time + extract_duration if start_time + extract_duration < duration else duration

            extract_details = {
                "Duration": end_time - start_time,
                "Start time": start_time,
                "End time": end_time,
            }
            
            video_basename = re.sub(r'\.[^.]+$', '', video_name)
            extract_name = f"{video_name}-extract.duration-{extract_duration}s.timestamp-{scene_time}s.score-{score['score']}"
            extract_path = EXTRACTS_DIR / (extract_name + ".mov")
            extract_cmd = f"{BIN_FFMPEG} -hide_banner -i {cli_args.input} -ss {start_time} -t {extract_duration} -c copy -y {str(extract_path)}"
            subprocess.run(extract_cmd.split(" "))

            extract_filesize = extract_path.stat().st_size

            # out = ffshort(extract_path, dry_run=True, ffmpeg_path=BIN_FFMPEG)
            
            # Encodage et test de qualité pour chacune des valeurs de CRF à tester
            for crf in CRF_VALUES:
                
                for mode in ["simple", "complex"]:

                    encoding_details = encode_and_vmaf(extract_path, crf=crf, mode="simple")

                    all_details = {**scene_details, **extract_details, **encoding_details}
                    line_csv = ";".join(all_details.values) + "\n"
                    file_csv.write(line_csv)

#                 ####
#                 # Deux encodages sont testés (avec juste le CRF et plus de paramètres)

#                 ## Encodage avec juste le crf
#                 encoded_path = EXTRACTS_DIR / f"{extract_name}.crf{crf}.simple.mp4"
#                 encode_cmd = f"{BIN_FFMPEG} -hide_banner -loglevel quiet -stats -i {str(extract_path)} -crf {crf} -y {str(encoded_path)}"
#                 print("Encodage simple ...")
#                 print(encode_cmd)
#                 start_cmd = time()
#                 subprocess.run(encode_cmd.split(" "))
#                 encoding_time = str(timedelta(seconds=(time() - start_cmd)))
#                 encoded_filesize = encoded_path.stat().st_size
#                 reduction_percentage = encoded_filesize / extract_filesize * 100
#                 print()

#                 vmaf_path = OUTPUT_DIR / f"{extract_name}.crf{crf}.simple.json"
#                 vmaf_cmd = f"{BIN_FFMPEG} -loglevel quiet -stats -i {extract_path} -i {encoded_path} "
#                 vmaf_cmd += f"-lavfi [0:v]setpts=PTS-STARTPTS[ref];[1:v]setpts=PTS-STARTPTS[dist];[dist][ref]libvmaf=log_fmt=json:log_path={str(vmaf_path)}:model_path=/Users/murrutia/src/vendor/vmaf/model/vmaf_v0.6.1.json "
#                 vmaf_cmd += "-threads 0 -f null -"
#                 start_cmd = time()
#                 subprocess.run(vmaf_cmd.split(" "))
#                 print()
#                 vmaf_time = str(timedelta(seconds=(time() - start_cmd)))

#                 with open(str(vmaf_path), 'r') as fd:
#                     vmaf_json = json.loads(fd.read())
#                 vmaf_score = vmaf_json['pooled_metrics']['vmaf']['harmonic_mean']

#                 line_csv = f"\
# {scene_score};\
# {scene_time};\
# {end_time - start_time};\
# {start_time};\
# {end_time};\
# {crf};\
# simple;\
# {encoding_time};\
# {vmaf_score};\
# {vmaf_time};\
# {encoded_filesize};\
# {reduction_percentage}%;\
# {encode_cmd};\n"
#                 print(line_csv)
#                 file_csv.write(line_csv)
#                 results_csv += line_csv

#                 ## Encodage avec des paramètres plus fins
#                 encoded_path = EXTRACTS_DIR / f"{extract_name}.crf{crf}.complex.mp4"
#                 print("Encodage complexe ...")
#                 encode_cmd = ffshort(str(extract_path), str(encoded_path), crf=crf, dry_run=True, force_encode=True, ffmpeg_path=BIN_FFMPEG)
                
#                 start_cmd = time()
#                 subprocess.run(encode_cmd.split(" "))
#                 print()
#                 encoding_time = str(timedelta(seconds=(time() - start_cmd)))
#                 encoded_filesize = encoded_path.stat().st_size
#                 reduction_percentage = encoded_filesize / extract_filesize * 100

#                 vmaf_path = OUTPUT_DIR / f"{extract_name}.crf{crf}.complex.json"
#                 vmaf_cmd = f"{BIN_FFMPEG} -loglevel quiet -stats -i {extract_path} -i {encoded_path} "
#                 vmaf_cmd += f"-lavfi [0:v]setpts=PTS-STARTPTS[ref];[1:v]setpts=PTS-STARTPTS[dist];[dist][ref]libvmaf=log_fmt=json:log_path={str(vmaf_path)}:model_path=/Users/murrutia/src/vendor/vmaf/model/vmaf_v0.6.1.json "
#                 vmaf_cmd += "-threads 0 -f null -"
#                 start_cmd = time()
#                 subprocess.run(vmaf_cmd.split(" "))
#                 print()
#                 vmaf_time = str(timedelta(seconds=(time() - start_cmd)))

#                 with open(str(vmaf_path), 'r') as fd:
#                     vmaf_json = json.loads(fd.read())
#                 vmaf_score = vmaf_json['pooled_metrics']['vmaf']['harmonic_mean']

#                 line_csv = f"\
# {scene_score};\
# {scene_time};\
# {end_time - start_time};\
# {start_time};\
# {end_time};\
# {crf};\
# complex;\
# {encoding_time};\
# {vmaf_score};\
# {vmaf_time};\
# {encoded_filesize};\
# {reduction_percentage}%;\
# {encode_cmd};\n"
#                 print(line_csv)
#                 file_csv.write(line_csv)
#                 results_csv += line_csv

    
    # with open(str(results_csv_path), 'w+') as fd:
    #     fd.write(results_csv)
    file_csv.close()
    print(f"Les résultats ont été enregistrés dans le fichier {str(results_csv_path)}.")


