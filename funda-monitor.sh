#!/bin/bash
#
# Ensure you set CITY and RECIPIENT to
# a correct value.
######################################
NEW='funda-check.txt'
VORIGE='funda-check-vorige.txt'
DIFF='diffje.txt'
RECIPIENT='blabla@domain.com'
URL='http://partnerapi.funda.nl/feeds/Aanbod.svc/rss/?type=koop&zo=/*CITY*/275000-400000/100+woonopp/4+kamers/3+slaapkamers/'
#
### if NEW exists (from yesterday), move to VORIGE
##
if [ -f $NEW ];
then
   echo "File $NEW exists."
   echo "Will move $NEW to $VORIGE"
   mv $NEW $VORIGE
else
   echo "File $NEW does not exist."
   echo "Will continue."
fi
#
### get the NEW file
#
wget -O $NEW -q $URL
#
### diff the VORIGE and NEW
#
diff $VORIGE $NEW > $DIFF
#
### if diff exists email it!
#
if [ -s $DIFF ];
then
   echo "There is a diff so a new house has been added!"
   echo "Will send it to you"
   echo "New house found at $URL" | mutt -a $DIFF -s "new house found at `date +%Y-%M-%d`"  -- $RECIPIENT
else
   echo "No new diff so no new houses, to bad bradda!"
fi
