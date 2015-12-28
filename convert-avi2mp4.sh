#!/bin/bash
#
## install libav for avconv, the tool to convert the files 
#brew install libav #for avconv installation
## rename spaces to underscores in filenames
#ls | while read -r FILE
#do
#    mv -v "$FILE" `echo $FILE | tr ' ' '_' `
#done
for i in `ls`;do avconv -i $i -c:v libx264 -c:a copy $i.mp4;done
