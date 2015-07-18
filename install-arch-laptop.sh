#!/bin/bash
#
#
#
###########################
#
### Install packages
#
packages=(pulseaudio pulseaudio-alsa pa-applet-git offlineimap msmtp midori connman midori parcellite gnome-keyring synaptics xorg-server xorg-xinit i3 vlc libreoffice fish mutt curl lynx atom connman-ui-gtk terminator urxvt git ufw terminator chromium keepassx2 thunar-volman thunar-archive-plugin thunar-media-tags-plugin gvfs thunar gvfs filezilla clusterssh backintime-bzr thunar-volman thunar-archive-plugin thunar-media-tags-plugin gvfs davfs2 sshfs nfs-util pa-applet udisks2 udevil feh scrot)
dotfiles_url='https://github.com/chiel1980/dotfiles.git'
function install_packages {
pacman -Sy $packages
}
  install_packages 
#
### Get our dotfiles from github
#
mkdir tmp
cd tmp
git clone $dotfiles_url
#
### Place our .dotfiles in the right location
#
cp -rp .*   ~/
cp fish_prompt.fish ~/.config/fish/functions/
#
### Ensure that all services are started
#
sudo systemctl enable connman.service
sudo systemctl start connman.service
#
### Fix maildir for offlineimap and mutt
#
mkdir -p ~/Mail/Gmail
#
### Fix permissions on .dotfiles
#
chmod 600 .*
#
### start ufw and cron
#
sudo systemctl enable cron.service
sudo systemctl start cron.service
sudo systemctl enable ufw
sudo systemctl start ufw.service
