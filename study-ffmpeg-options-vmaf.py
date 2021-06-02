#!/usr/bin/env python3

import os
import re
import sys
import json
import argparse
import subprocess
from pathlib import Path
from time import time
from datetime import timedelta
from statistics import mean , harmonic_mean
from scenecut_extractor.__main__ import get_scenecuts
from external.ffshort import ffshort, guess_frame_rate
from external.easyVmaf.Vmaf import vmaf

SCRIPT_DIR = Path(os.path.dirname(__file__))

EXTRACTS_DIR = SCRIPT_DIR / 'tmp' / 'extracts'
EXTRACTS_DIR.mkdir(parents=True, exist_ok=True)
BIN_FFMPEG = SCRIPT_DIR / "external" / "ffmpeg"
BIN_FFPROBE = SCRIPT_DIR / "external" / "ffprobe"
MODEL_PATH = SCRIPT_DIR / "external" / "vmaf_v0.6.1.json"
OUTPUT_DIR = SCRIPT_DIR / "output"
TMP_JSON = SCRIPT_DIR
# CRF_VALUES = [25, 27, 30]
CRF_VALUES = [27]
EXTRACT_DURATIONS = [120]
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
    '-preset',
    # '-refs',
    # '-me_method',
    # '-me_range',
    # '-qcomp',
    # '-qmin',
    # '-subq',
    # '-trellis'
]


def get_video_duration(filepath):
    cmd = f"{BIN_FFPROBE} -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1"
    cmd_a = cmd.split(" ")
    cmd_a.append(str(filepath))
    return float(subprocess.check_output(cmd_a))


def encode_and_vmaf(input_path, crf, mode="ffshort", remove_option=None):
    extract_name = Path(input_path).name
    extract_name = re.sub(r'\.[^.]+$', '', extract_name)
    option_name = remove_option.replace(':', '') if remove_option else 'None'

    options = {remove_option: None} if remove_option else {}

    if mode == 'ffshort':
        output_path = EXTRACTS_DIR / f"{extract_name}.crf{crf}.mode-ffshort.option{option_name}.mp4"
        encode_cmd = ffshort(str(input_path), str(output_path), crf=crf, dry_run=True, force_encode=True, ffmpeg_path=BIN_FFMPEG, options=options)
    else:
        output_path = EXTRACTS_DIR / f"{extract_name}.crf{crf}.mode-simple.mp4"
        encode_cmd = f"{BIN_FFMPEG} -hide_banner -loglevel quiet -stats -i {str(input_path)} -crf {crf}".split(" ")
        encode_cmd.extend(['-y', str(output_path)])
                
    start_cmd = time()
    print(encode_cmd)
    subprocess.run(encode_cmd)
    encoding_duration = str(timedelta(seconds=(time() - start_cmd)))
    encoded_filesize = output_path.stat().st_size
    size_percentage = encoded_filesize / extract_filesize * 100

    vmaf_path = OUTPUT_DIR / f"{extract_name}.crf{crf}.mode-{mode}.option{option_name}.json"
    
    frame_rate = guess_frame_rate(input_path)
    if not vmaf_path.exists():
        # vmaf_cmd = f"{BIN_FFMPEG} -loglevel quiet -stats -r {frame_rate} -i {str(input_path)} -r {frame_rate} -i {str(output_path)} "
        # vmaf_cmd += f"-lavfi [0:v]setpts=PTS-STARTPTS[ref];[1:v]setpts=PTS-STARTPTS[dist];[dist][ref]libvmaf=log_fmt=json:log_path={str(vmaf_path)}:model_path={str(MODEL_PATH)} "
        # vmaf_cmd += "-threads 0 -f null -"
        # start_cmd = time()
        # subprocess.run(vmaf_cmd.split(" "))
        # vmaf_duration = str(timedelta(seconds=(time() - start_cmd)))

        start_cmd = time()
        myVmaf = vmaf(output_path, input_path, output_fmt='json', log_path=vmaf_path)
        offset, psnr = myVmaf.syncOffset()  # TODO: étudier les arguments de cette fonction : syncWindow, start, reverse
        myVmaf.getVmaf()
        vmaf_duration = str(timedelta(seconds=(time() - start_cmd)))
    else:
        vmaf_duration = "N/A"

    vmafScore = []
    with open(str(vmaf_path), 'r') as fd:
        jsonData = json.load(fd)
        for frame in jsonData['frames']:
            vmafScore.append(frame["metrics"]["vmaf"])

    values = {
        "CRF value": crf,
        "Option removed": "' "+ str(remove_option),
        "Encoding duration": encoding_duration,
        "VMAF offset": offset,
        "VMAF PSNR": psnr,
        "VMAF arithmetic mean score": mean(vmafScore),
        "VMAF harmonic mean score": harmonic_mean(vmafScore),
        "VMAF computing duration": vmaf_duration,
        "Encoded filesize": encoded_filesize,
        "Filesize percentage": size_percentage,
        "Encoding command":  encode_cmd
    }
    return values


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('input')
    parser.add_argument('output_suffix', nargs='?', help="Un suffixe ajouté au nom du fichier de sortie csv")
    cli_args = parser.parse_args()

    # On récupère la durée et le nom de la vidéo
    # video_name = re.search(r'_(v.*)\..*$', cli_args.input).group(1) 
    duration = get_video_duration(cli_args.input)
    video_name = Path(cli_args.input).stem
    video_extension = Path(cli_args.input).suffix

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

    # Réduction des résultats au 2eme meilleur, le moyen et le 2eme pire
    sl = len(scenescores)
    # scenescores_extract = [scenescores[1], scenescores[int(sl/2)], scenescores[-2]]
    scenescores_extract = [scenescores[1]]

    # Préparation du csv qui va accueillir les résultats
    results_csv = "Scene score; Time; Duration; Start; End; CRF value; Option removed; Encoding time; VMAF offset; VMAF PSNR;VMAF arithmetic mean; VMAF harmonic mean; VMAF computation time; Filesize; Compression %; Encoding command\n"
    results_csv_path = OUTPUT_DIR / f"{video_name}_ffmpeg-options-vmaf-scores{'.'+ cli_args.output_suffix if cli_args.output_suffix else ''}.csv"

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
            
            video_basename = re.sub(r'\.[^.]+$', '', video_name)
            extract_name = f"{video_name}-extract.duration-{extract_duration}s.timestamp-{scene_time}s.score-{score['score']}"
            extract_path = EXTRACTS_DIR / (extract_name + video_extension)
            extract_cmd = f"{BIN_FFMPEG} -hide_banner -loglevel quiet -stats -i {cli_args.input} -ss {start_time} -t {extract_duration} -c copy".split(' ')
            extract_cmd.extend(['-y', str(extract_path)])
            subprocess.run(extract_cmd)

            extract_filesize = extract_path.stat().st_size

            # out = ffshort(extract_path, dry_run=True, ffmpeg_path=BIN_FFMPEG)
            
            # Encodage et test de qualité pour chacune des valeurs de CRF à tester
            for crf in CRF_VALUES:
                
                # Encodage témoin
                encoding_details = encode_and_vmaf(extract_path, crf=crf, mode="simple")

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

    
    # with open(str(results_csv_path), 'w+') as fd:
    #     fd.write(results_csv)
    file_csv.close()
    print(f"Les résultats ont été enregistrés dans le fichier {str(results_csv_path)}.")


