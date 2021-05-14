#!/bin/bash

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"

dir_original="/tmp/original"
dir_encoding="/tmp/encoding"
script_encode="$SCRIPT_DIR/encode.py"
script_encode=/usr/local/bin/utc/ffshort.py
list_file=$SCRIPT_DIR/videos-to-encode.txt
# list_file=$SCRIPT_DIR/empty.txt

# check if there are still videos to encode
nb_lines=`wc -l < $list_file`
if (( $nb_lines == 0 )); then
    echo There is no more videos to process
    exit
fi

# we make sure that the working directories exist
mkdir -p $dir_original
mkdir -p $dir_encoding

# check if there is not another video being processed
if [[ "$(ls -A /tmp/encoding)" || "$(ls -A /tmp/original)" ]]; then
    echo the folders are not empty
    exit
fi

first_line=$(head -n 1 $list_file)

# download the video
rsync -avz --progress murrutia@axone.utc.fr:/var/www/resources/videos/$first_line /tmp/original/$first_line



# Remove the first line in the list of videos
# tail -n +2 $list_file > $list_file.tmp
# mv $list_file.tmp > $list_file
