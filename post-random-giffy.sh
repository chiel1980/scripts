#!/bin/bash
#
# Make sure you have set the following correct:
#
# Hipchat APIKEY (with enough rights)
# Hipchat ROOMID
# Gliphy SEARCHTERM
# 
##################################################
APIKEY=''
ROOMID=''
SEARCHTERM='Justin+Bieber'
## first get a random $SEARCHTERM giphy
#
LINK=`curl -s "http://api.giphy.com/v1/gifs/search?q="$SEARCHTERM"&api_key=dc6zaTOxFJmzC" | python -mjson.tool | grep '"url":' | grep 200w.gif | uniq | sort | awk {'print $2'} | sort -R | head -n 1 | sed 's/"//g' | sed 's/,//g'`
#
### second, post it to our favorite room :)
#
curl -d "room_id="$ROOMID"&from=Mr+Funny&message=Here+is+your+daily+"$SEARCHTERM"+gif:+&color=green" https://api.hipchat.com/v1/rooms/message?auth_token="$APIKEY"&format=json
sleep 2
curl -d "room_id="$ROOMID"&from=Mr+Funny&message=<img src=\"$LINK\">" https://api.hipchat.com/v1/rooms/message?auth_token="$APIKEY"&format=json
