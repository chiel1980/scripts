#!/bin/bash
#
#
# A simple script to get the contents of our Wordpress website
# - it tries to change *.wordpress.com -> thatspecificsound.nl
# - it tries to remove some typical wordpress links in the code
# -- I still need to clean up some of the wordpress links but 
# -- I noticed the website and styling breaks if you remove too much
# 
# PS works with sed -i '' for OS X sed, might need to change that for linux
# PS2 need to fix above by checking which OS we are using and change the sed
# arguments properly - too lazy atm :) 
############################################################################
echo ''
echo ''
echo ''
echo 'We are going to make a wget static html copy of our wordpress website'
echo 'Make sure you added your content to https://thatspecificsound.wordpress.com and that the interview is checked with the interviewee'
echo 'if all is ok according to the interview, then run the rest of this script!'
echo ''
echo ''
echo 'Are you sure you want to make a static copy of the website and the interviewee is ok with the draft on the wordpress website?'
echo ''
echo ''
read -r -p "Are you sure? [y/N] " -n 1
echo
if [[ "$REPLY" =~ ^[Yy]$ ]]; then
    echo "Operation continues"
	echo "you answered $REPLY , so we will extract the website and add it to our gitlab repository"
	mkdir ~/websites/ 1>/dev/null 2>&1
	cd ~/websites/
	wget -q -r -p -e robots=off https://thatspecificsound.wordpress.com
	echo ''
	echo 'done copying the website locally..'
	sleep 2
	echo 'now fixing the links..'
	cd ~/websites/thatspecificsound.wordpress.com/ 
	# fix very long wget-ed index.html files in _static that caused sed to break
	rm ./_static/index.html* 1>/dev/null 2>&1
	#
	find . -type f -print0 | LC_ALL=C xargs -0 sed -i'' -e 's/thatspecificsound.wordpress.com/thatspecificsound.nl/g'
    echo ''
	echo 'some sanitizing with sed..'
	# rename *.wp.com to thatspecificsound.nl so we fetch contents local
    find . -type f -print0 | LC_ALL=C xargs -0 sed -i'' -e 's/(s|s2|s0|s1|stats|fonts|pixel).wp.com/thatspecificsound.nl/g'
	# remove code in the html files with the following words
	# note: this is pretty ambigious and can also remove proper code or sentences in the interview if used by any - need to improve this
	find . -type f -print0 | LC_ALL=C xargs -0 sed -i'' -e '/dns-prefetch/d'
	find . -type f -print0 | LC_ALL=C xargs -0 sed -i'' -e '/Design/d'
	find . -type f -print0 | LC_ALL=C xargs -0 sed -i'' -e '/Created/d'
	find . -type f -print0 | LC_ALL=C xargs -0 sed -i'' -e '/window._tkq = window._tkq/d'
    # done sanitizing
	echo ''
	echo 'now copying the contents to our git repo..'
	echo ''
	echo ''
	cp -frp ~/websites/thatspecificsound.wordpress.com/* ~/git-repos/thatspecificsound.github.io/
	cd ~/git-repos/thatspecificsound.github.io/
	echo ''
	echo ''
	echo 'done copying...now adding it to our github pages repo..'
	echo ''
	git add *
	git commit -m "`date` new interview"
	git push
	echo ''
	echo ''
	echo 'code deployed! Check https://thatspecificsound.nl/ for the new content'
	echo 'make sure you refresh the website with F5 etc'
	echo ''
	echo ''
else
	echo ''
	echo 'you did not answer Y or y so we exit the script now..'
	echo ''
fi
