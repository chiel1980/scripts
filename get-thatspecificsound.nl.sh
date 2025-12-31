#!/bin/bash
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
	#wget -qr https://thatspecificsound.wordpress.com
	wget -q -r -p -e robots=off https://thatspecificsound.wordpress.com
	echo ''
	echo 'done copying the website locally..'
	sleep 2
	echo 'now fixing the links..'
	cd ~/websites/thatspecificsound.wordpress.com/ 
	find . -type f -print0 | xargs -0 sed -i 's/thatspecificsound.wordpress.com/thatspecificsound.nl/g'
	echo 'now copying the contents to our git repo..'
	echo ''
	echo ''
	cp -frp ~/websites/thatspecificsound.wordpress.com/* ~/git-repos/thatspecificsound.github.io/
	cd ~/git-repos/thatspecificsound.github.io/
	echo ''
	echo ''
    echo 'changing remote wordpress urls to local files instead..'
    sed -i'' -e 's,https://s2.wp.com,\/,g' index.html
    sed -i'' -e 's,https://fonts.wp.com,\/,g' index.html
    sed -i'' -e 's,https://s0.wp.com,\/,g' index.html
    sed -i'' -e 's,https://stats.wp.com,\/,g' index.html
    sed -i'' -e 's,https://pixel.wp.com,\/,g' index.html
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
