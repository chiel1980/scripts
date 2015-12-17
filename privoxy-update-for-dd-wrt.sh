#!/bin/sh
/usr/bin/wget -q 'http://www.malwaredomainlist.com/hostslist/domains.txt' -O /jffs/tmp/malware-list1.txt
/usr/bin/wget -q 'http://hosts-file.net/download/hosts.txt' -O /jffs/tmp/malware-list2.txt

# echo the first block line for the actionsfile
echo '{+block{You visitted a potential malware website.}}' > /jffs/etc/privoxy/malware-blacklist.action

# fix the comments etc with sed for the 2nd malware list
sed -i -e 's/#.*$//' -e '/^$/d' /jffs/tmp/malware-list2.txt
# fix the 127.0.0.1 entries
sed -i "s/127.0.0.1//" /jffs/tmp/malware-list2.txt
sed -i "s/\:\:1//" /jffs/tmp/malware-list2.txt
sed -i -e "s/ //g" /jffs/tmp/malware-list2.txt
sed -i -e "s/ //g" /jffs/tmp/malware-list1.txt
sed -i -e "s/^M//" /jffs/tmp/malware-list1.txt

# combine the 2
cat /jffs/tmp/malware-list1.txt /jffs/tmp/malware-list2.txt > /jffs/tmp/malware-list-combined.txt
cat /jffs/tmp/malware-list-combined.txt | sort | uniq >> /jffs/etc/privoxy/malware-blacklist.action
sed -i 's/^M//g' /jffs/etc/privoxy/malware-blacklist.action
sed -i -e 's/^[ \t]*//' -e 's/[ \t]*$//' /jffs/etc/privoxy/malware-blacklist.action

# remove entries we do trust and use for our mediacenters like opensubtitles.org
sed -i -e 's/www\.opensubtitles\.org/d' /jffs/etc/privoxy/malware-blacklist.action

# stop & start
ps w | grep privoxy | grep -v grep | kill `awk {'print $1'}`;privoxy /tmp/privoxy.conf
