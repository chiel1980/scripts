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
echo 'Answer with Y or N'
echo ''
read $answer
if $answer != Y; then echo 'you have not chosen Y as answer so we exit now..'; exit
else
	echo 'you answered Y, so we will extract the website and add it to our gitlab repository..'
	mkdir ~/websites/ && cd websites/
	wget -r https://thatspecificsound.wordpress.com
	cd thatspecificsound.wordpress.com/ && find . -type f -print0 | xargs -0 sed -i 's/thatspecificsound.wordpress.com/thatspecificsound.nl/g'
	cp -frp thatspecificsound.wordpress.com/* ~/git-repos/thatspecificsound.github.io/
	cd ~/git-repos/thatspecificsound.github.io/
	git add *
	git commit -m "`date` new interview"
	git push
	echo 'code deployed! Check https://thatspecificsound.nl/ for the new content'
	echo 'make sure you refresh the website with F5 etc'
	echo ''
fi
