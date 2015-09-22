#!/bin/bash
#
###############
ROOTFILE='/etc/unbound/root.hints'
ROOTFILENEW='/etc/unbound/root.hints.new'
BCKPFILE='/etc/unbound/root.hints.bck'
DIFF='/tmp/root.hints.diff'
GPGKEY='/etc/unbound/named.cache.sig'
#
### make backup of old root.hints
#
if [ -f $ROOTFILE ]; then
  echo 'ok we can continue'
  cp -f $ROOTFILE $BCKPFILE
else
  echo 'seems the root.hint file is non existent - exit alert death!'
  echo 'restoring backup now!'
  mv $BCKPFILE $ROOTFILE
  /etc/init.d/unbound restart
  exit 1
fi
#
### get new file
#
wget -q http://www.internic.net/domain/named.cache -O $ROOTFILENEW
wget -q http://www.internic.net/domain/named.cache.sig -O $GPGKEY
#
### check if new file is not 0 bytes
#
if [ -s $ROOTFILENEW ]; then
  echo 'seems the file has contents - check for diff'
  diff $ROOTFILENEW $BCKPFILE > $DIFF
	if [ -s $DIFF ]; then
  		echo 'seems to be a diff, move new file into place and restart unbound'
		gpg --keyserver --recv-key 0xc1d27af9 1>/dev/null 2>&1
 	 	gpg --verify $GPGKEY $ROOTFILENEW
  		mv $ROOTFILENEW $ROOTFILE
  		/etc/init.d/unbound restart
		exit 1
	else
  		echo 'seems that the diff is empty'
  		echo 'no action needed'
  		exit 1
	fi
else
  echo 'new hints file seems to be empty, exiting now and restoring backup'
  mv $BCKPFILE $ROOTFILE
  /etc/init.d/unbound restart
fi
