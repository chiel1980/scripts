#!/usr/bin/python
#
# Perform an XML export of a Confluence space with spaceKey specified as
# argument. Stolen from https://confluence.atlassian.com/display/DISC/Export+Space
# and added some more options like backup and extraction of the zip to a webroot.  
#
# see also - http://confluence.atlassian.com/display/CONF27/Remote+API+Specification
 
import sys, os, urllib2, xmlrpclib, zipfile
from urllib2 import URLError, HTTPError
 
# e.g. http://wiki.example.com
wikiURL = "https://confluence.url.blablabla"
 
# User must have rights over the space
username = "*****"
password = "*****"
 
# Path to store exported zip files (must exist)
exportDir = "/tmp/"
exportWebroot = "/var/www/html/" 

# Initialise XMLRPC session
s = xmlrpclib.ServerProxy(wikiURL + "/rpc/xmlrpc")
spaceKey = sys.argv[1]
 
print "Logging in to " + wikiURL + " as user " + username
token = s.confluence1.login(username, password)

# Create backup of older space zip file
ZIPPIE = exportDir + spaceKey + ".zip"

if os.path.isfile(ZIPPIE) and os.access(ZIPPIE, os.R_OK):
    print "Older zip file exists and is readable"
    print "Will move to bckp file"
    os.rename(ZIPPIE, ZIPPIE + ".bckp")
else:
    print "No older space zip file found or unreadable, will start the work"
 
print "Exporting Space: " + spaceKey
# Perform the export and get a download URL - choose your export option

#downloadURL = s.confluence1.exportSpace(token, spaceKey, "TYPE_XML")
#downloadURL = s.confluence1.exportSpace(token, spaceKey, "TYPE_PDF")
downloadURL = s.confluence1.exportSpace(token, spaceKey, "TYPE_HTML")
 
print "Logging out..."
s.confluence1.logout(token)
 
print "Download URL: " + downloadURL
 
# We'll need to authenticate to download the zip file
downloadURL = downloadURL + "?os_username=" + username + "&os_password=" + password
 
# Configure export file name
filePath = exportDir + spaceKey + ".zip"
 
# Delete any old copy if it exists
if os.path.exists(filePath):
    print "File exists at " + filePath + ". Deleting..."
    os.remove(filePath)
 
print "Exporting to: " + filePath
 
req = urllib2.Request(downloadURL)
try:
    f = urllib2.urlopen(req)
    localFile = open(filePath, "w")
    localFile.write(f.read())
    localFile.close()
except HTTPError, e:
    print "Error downloading file - HTTP response: ", e.code
    sys.exit(1)
except URLError, e:
    print "URL Error: ", e.reason, url
    sys.exit(1)
 
print "Export of " + spaceKey + " complete"

# Extract all files to a folder
print "Will export the zip file in the webroot" + exportWebroot
with zipfile.ZipFile(exportDir + spaceKey + ".zip", "r") as z:
    z.extractall(exportWebroot)
