#!/usr/bin/env python3

import json
import logging
import argparse
from pathlib import Path
from scenecut_extractor.__main__ import get_scenecuts


def get_sorted_scenescores(input, output=None, threshold=0, log_level=None):
    scenescores = get_scenescores(input, output, threshold, log_level)
    scenescores = sorted(scenescores, key=lambda ss: ss["score"])
    return scenescores


def get_scenescores(input, output=None, threshold=0, log_level=None):
    
    logging.basicConfig(level = getattr(logging,  log_level.upper(), 'INFO'))
    
    if output and Path(output).exists():
        logging.info(f"Reading scenescores from file {output}")
        with open(output, 'r') as fd:
            scenescores = json.loads(fd.read())
    else:
        logging.info(f"Computing scenescores for video {input}...")
        scenescores = get_scenecuts(input, threshold=0)
    
        if output:
            logging.info(f"Writing scenescores to file {output}")
            with open(output, 'w') as fd:
                fd.write(json.dumps(scenescores, indent=4))

    return scenescores


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('input', help="Video file to analyze")
    parser.add_argument('output', nargs='?', help="Output file where the results are written")
    parser.add_argument('--threshold', '-t', type=int, default=0, help="Minimum scenescore to retain")
    parser.add_argument('--log-level', default='info')
    args = parser.parse_args()
    scenescores = get_scenecuts(args.input, args.output, args.threshold)
    
    if not args.output:
        print(scenescores)
